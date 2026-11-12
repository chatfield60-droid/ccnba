"""Sync, daily projection run, and walk-forward backtest."""
import json
import logging
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .client import BDLClient, TierError
from .config import ModelConfig, Settings
from .features import build_state, prepare, q1_profile
from .markets import price_slate, slate_health
from .project import build_roster, simulate_game, summarize
from .store import Store

log = logging.getLogger("bdlbox")


def sync(client: BDLClient, store: Store, seasons, full=False, q1=False):
    report = {}
    store.upsert_teams(client.teams())
    for s in seasons:
        report[f"games_{s}"] = store.upsert_games(client.games(seasons=[s]))
        start = None if full else store.max_stat_date(s)
        if start:
            start = (pd.Timestamp(start) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        report[f"stats_{s}"] = store.upsert_stats(client.stats(seasons=[s], start_date=start))
        if q1:  # first-quarter box scores (BDL /v1/stats?period=1), for *_1q and *_first3min props
            st1 = None if full else store.max_stat_date(s, "player_stats_q1")
            if st1:
                st1 = (pd.Timestamp(st1) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
            report[f"stats_q1_{s}"] = store.upsert_stats(client.stats(seasons=[s], start_date=st1, period=1),
                                                         table="player_stats_q1")
    for name, fn, put in [("active_players", client.active_players, store.replace_active),
                          ("injuries", client.injuries, store.replace_injuries)]:
        try:
            report[name] = put(fn())
        except TierError as e:
            report[name] = f"skipped: {e}"
    return report


def load_prep(store: Store):
    return prepare(store.df("SELECT * FROM player_stats"))


def _games_on(store, d):
    return store.df("""SELECT g.*, h.abbr AS home_abbr, v.abbr AS away_abbr FROM games g
        LEFT JOIN teams h ON h.team_id=g.home_team_id LEFT JOIN teams v ON v.team_id=g.visitor_team_id
        WHERE g.date=? AND g.postponed=0 AND g.postseason=0""", (d,))


def project_date(store: Store, d: str, cfg: ModelConfig, out_dir="out", lines_path=None, n_sims=None, seed=7):
    games = _games_on(store, d)
    if games.empty:
        raise SystemExit(f"No games on {d} in the local DB. Run sync for that season first.")
    season = int(games.season.iloc[0])
    prep = load_prep(store)
    state = build_state(prep, d, season, cfg)
    q1 = store.df("SELECT * FROM player_stats_q1")
    q1p = q1_profile(q1, prep.players, d, cfg)
    if len(q1p):
        state.players = state.players.join(q1p, how="left")
    active = store.df("SELECT * FROM active_players")
    inj = store.df("SELECT * FROM injuries")
    gaps = []
    if inj.empty:
        gaps.append(dict(gap="no injury snapshot (ALL-STAR+ /player_injuries); everyone assumed available"))
    else:
        fetched = pd.Timestamp(inj.fetched_at.iloc[0]).tz_localize(None).normalize()
        if abs((pd.Timestamp(d) - fetched).days) > 1:
            gaps.append(dict(gap=f"injury snapshot from {fetched.date()} applied to {d}; refresh with sync"))

    mm = _load_minutes_model(cfg)
    if mm is not None:
        import dataclasses
        cfg = dataclasses.replace(cfg, min_unc_base=0.0, min_unc_new=0.0)   # the model's spread covers it
    tnames = store.df("SELECT team_id, abbr, full_name FROM teams").set_index("team_id")
    players, teams, sims, team_sims, ctx_players = [], [], {}, {}, {}
    hist = _history(prep, q1, d, season)
    for _, g in games.iterrows():
        meta = dict(game_id=int(g.game_id), date=d, home_team_id=int(g.home_team_id),
                    away_team_id=int(g.visitor_team_id), home_abbr=g.home_abbr, away_abbr=g.away_abbr)
        hr, hg = build_roster(state, meta["home_team_id"], d, cfg, active, inj)
        ar, ag = build_roster(state, meta["away_team_id"], d, cfg, active, inj)
        gaps += hg + ag
        if mm is not None:
            gaps += _apply_minutes_model(mm, store, state, meta, hr, ar, d, season)
        sim = simulate_game(state, meta["home_team_id"], meta["away_team_id"], hr, ar, cfg, n_sims, seed)
        rows, team, tpts = summarize(sim, meta)
        players += rows
        teams.append(team)
        gid = meta["game_id"]
        team_sims[gid] = dict(home=tpts["home"], away=tpts["away"], home_abbr=str(g.home_abbr),
                              away_abbr=str(g.away_abbr),
                              home_name=str(tnames.full_name.get(meta["home_team_id"], "")),
                              away_name=str(tnames.full_name.get(meta["away_team_id"], "")))
        rows_by_pid = {r["player_id"]: r for r in rows}
        for side, opp_side in (("home", "away"), ("away", "home")):
            P, D, R = sim[side]
            tid, oid = meta[f"{side}_team_id"], meta[f"{opp_side}_team_id"]
            out_rows = R[R.avail < 0.5]
            out_min = float(state.players.reindex(out_rows.player_id).min_mu.fillna(0).sum())
            out_txt = ", ".join(f"{state.players.name.get(p, p)} ({state.players.min_mu.get(p, 0):.0f} min)"
                                for p in out_rows.player_id)
            usage = sim[f"info_{side}"]["usage_scale"]
            for j, pid in enumerate(P.index):
                draws = {k: v[:, j] for k, v in D.items()}
                played = D["min"][:, j] > 0
                sims[pid] = sims[P.name.iloc[j].strip().lower()] = (draws, played, pid, gid)
                ctx_players[pid] = _player_ctx(pid, rows_by_pid[pid], hist, state, sim, tid, oid,
                                               str(g.away_abbr if side == "home" else g.home_abbr),
                                               usage, out_min, out_txt)
    os.makedirs(out_dir, exist_ok=True)
    pdf, tdf = pd.DataFrame(players), pd.DataFrame(teams)
    pdf.to_csv(f"{out_dir}/box_{d}.csv", index=False)
    tdf.to_csv(f"{out_dir}/games_{d}.csv", index=False)
    result = dict(players=pdf, teams=tdf, gaps=gaps)
    if lines_path:
        lookup = {}
        for gid, ts in team_sims.items():
            for a_, h_ in ((ts["away_name"], ts["home_name"]), (ts["away_abbr"], ts["home_abbr"])):
                lookup[f"{a_} @ {h_}".lower()] = gid
        ctx = dict(players=ctx_players, teams=tdf, team_l10=hist["team_l10"], game_lookup=lookup, cfg=cfg)
        shown, missing = price_slate(sims, team_sims, ctx, pd.read_csv(lines_path), cfg)
        result["health"] = slate_health(shown, missing, cfg)
        # every offered line, every player: tier suggested | lean | pass; displayed EV always < 15%
        shown.to_csv(f"{out_dir}/predictions_{d}.csv", index=False)
        over = missing.get("tier", pd.Series(index=missing.index, dtype=object)) == "over_cap"
        missing[~over].to_csv(f"{out_dir}/no_prediction_{d}.csv", index=False)   # lines the model cannot price, with why
        missing[over].to_csv(f"{out_dir}/over_cap_{d}.csv", index=False)       # INTERNAL ONLY: >=15% = model error check
        result["props"], result["review"] = shown, missing
    with open(f"{out_dir}/gaps_{d}.json", "w") as f:
        json.dump(gaps, f, indent=2, default=str)
    return result


def _load_minutes_model(cfg):
    import os, pickle
    if not cfg.minutes_model_path or not os.path.exists(cfg.minutes_model_path):
        return None
    return pickle.load(open(cfg.minutes_model_path, "rb"))


def _apply_minutes_model(mm, store, state, meta, hr, ar, d, season):
    """Sets min_mu/min_sd for tonight's available players from the minutes model. Starters come
    from BDL projected lineups for this game (confirmed or expected) when synced."""
    from . import extra
    from .minutes import predict_tonight
    notes = []
    stats = store.df("SELECT * FROM player_stats WHERE season >= ?", (season - 1,))
    games = store.df("SELECT * FROM games WHERE season >= ?", (season - 1,))
    hist = extra.load(store, "starters")
    proj = extra.load(store, "proj_starters")
    pj = proj[proj.game_id == meta["game_id"]]
    tonight = set(pj.player_id) if len(pj) else None
    status = ",".join(sorted(set(pj.status))) if len(pj) else "none"
    if tonight is None:
        notes.append(dict(game_id=meta["game_id"], gap="no projected lineup synced: minutes use recent starting rate"))
    pos = state.players["pos"]
    rows = []
    for tid, R in ((meta["home_team_id"], hr), (meta["away_team_id"], ar)):
        for pid in R[R.avail > 0].player_id:
            rows.append(dict(player_id=pid, team_id=tid, game_id=meta["game_id"], date=d, season=season,
                             position=pos.get(pid, "F"), first_name="", last_name=""))
    if not rows:
        return notes
    pr = predict_tonight(mm, stats, games, hist, pd.DataFrame(rows), tonight)
    idx = state.players.index.intersection(pr.player_id)
    pr = pr.set_index("player_id").loc[idx]
    state.players.loc[idx, "min_mu"] = pr.min_mu.values
    state.players.loc[idx, "min_sd"] = pr.min_sd.values
    state.players.loc[idx, "lineup_status"] = status
    return notes


def train_minutes(store, cfg):
    import pickle
    from . import extra
    from .minutes import build_frame, MinutesModel
    F = build_frame(store.df("SELECT * FROM player_stats"), store.df("SELECT * FROM games"), extra.load(store, "starters"))
    m = MinutesModel().fit(F)
    pickle.dump(m, open(cfg.minutes_model_path, "wb"))
    d = F[(F.played == 1) & F.m_l1.notna()]
    return f"minutes model: trained on {len(d)} player-games, spread scale {m.sd_scale:.2f} -> {cfg.minutes_model_path}"


HIST_STATS = ["pts", "reb", "ast", "fg3m", "stl", "blk", "tov", "pr", "pa", "ra", "pra", "stocks", "dd", "td", "min"]


def _history(prep, q1, d, season):
    """Last-10, current-season and prior-season averages per player (BDL box scores before d)."""
    P = prep.players[prep.players.date < pd.Timestamp(d)].copy()
    P["pr"], P["pa"], P["ra"] = P.pts + P.reb, P.pts + P.ast, P.reb + P.ast
    P["pra"], P["stocks"] = P.pts + P.reb + P.ast, P.stl + P.blk
    tens = sum((P[k] >= 10).astype(int) for k in ("pts", "reb", "ast", "stl", "blk"))
    P["dd"], P["td"] = (tens >= 2).astype(int), (tens >= 3).astype(int)
    if q1 is not None and len(q1):
        q = q1[["game_id", "player_id", "pts", "reb", "ast"]].rename(
            columns={"pts": "pts_1q", "reb": "reb_1q", "ast": "ast_1q"})
        P = P.merge(q, on=["game_id", "player_id"], how="left")
    cols = HIST_STATS + [c for c in ("pts_1q", "reb_1q", "ast_1q") if c in P]
    P = P.sort_values("date")
    l10 = P.groupby("player_id").tail(10).groupby("player_id")
    T = prep.teams[prep.teams.date < pd.Timestamp(d)].sort_values("date")
    return dict(l10=l10[cols].mean(), n_l10=l10.size(),
                season=P[P.season == season].groupby("player_id")[cols].mean(),
                prev=P[P.season == season - 1].groupby("player_id")[cols].mean(),
                team_l10=T.groupby("team_id").tail(10).groupby("team_id").pts.mean())


def state_cfg_slope(pos):
    from .config import ModelConfig
    c = ModelConfig()
    return c.grab_and_go_slope.get(pos, 0.0) if c.grab_and_go else 0.0


def _player_ctx(pid, row, hist, state, sim, tid, oid, opp_abbr, usage, out_min, out_txt):
    g = lambda frame: frame.loc[pid].to_dict() if pid in frame.index else {}
    l10, sea, prev = g(hist["l10"]), g(hist["season"]), g(hist["prev"])
    proj = {k: row.get(k) for k in row if not k.endswith(("_sd", "_p10", "_p50", "_p90"))}
    min_proj = row.get("min") or 0
    per36 = lambda src, m: {k: (src.get(k, np.nan) / m * 36 if m and m > 0 else np.nan)
                            for k in ("pts", "reb", "ast", "fg3m", "stl", "blk")}
    dfac = state.def_factor.loc[oid].to_dict() if oid in state.def_factor.index else {}
    dpct = state.def_pct.loc[oid].to_dict() if oid in state.def_pct.index else {}
    pl = state.players.loc[pid]
    fga_scale = np.mean([usage.get("fg2a", 1), usage.get("fg3a", 1)])
    from .project import grab_and_go_rel
    gng_rel = grab_and_go_rel(state, oid)
    gng_mult = 1 + state_cfg_slope(pl.pos) * gng_rel
    return dict(gng_rel=gng_rel, gng_mult=gng_mult,
                proj=proj, l10=l10, season=sea, prev=prev, n_l10=int(hist["n_l10"].get(pid, 0)),
                gp_season=int(pl.gp_season), gp_total=int(pl.gp_total),
                min_proj=min_proj, min_l10=l10.get("min", np.nan),
                per36_proj=per36(proj, min_proj), per36_l10=per36(l10, l10.get("min")),
                usage=fga_scale, pace_game=float(sim["mu_pace"]),
                pace_team=float(state.pace.get(tid, state.lg_pace)),
                opp={**dfac, **{f"pct_{k}": v for k, v in dpct.items()}}, opp_abbr=opp_abbr,
                flags=str(row.get("flags") or ""), injury_status=str(row.get("injury_status") or ""),
                out_min=out_min, out_txt=out_txt)


def backtest(store: Store, season: int, cfg: ModelConfig, start=None, end=None, n_sims=1000,
             out_dir="out", every=1):
    """Walk-forward: each date uses only box scores dated before it.
    Availability is oracle (players who logged minutes), because BDL injuries are a
    live snapshot with no history. This isolates the minutes + rate model."""
    import dataclasses
    cfg = dataclasses.replace(cfg, rotation_cut=False)  # oracle rosters: everyone listed actually played
    prep = load_prep(store)
    P = prep.players[prep.players.season == season]
    dates = sorted(P.date.dt.strftime("%Y-%m-%d").unique())
    if start: dates = [x for x in dates if x >= start]
    if end: dates = [x for x in dates if x <= end]
    dates = dates[::every]
    games = store.df("SELECT * FROM games WHERE season=? AND postseason=0", (season,))
    preds, tpreds, skipped = [], [], 0
    for d in dates:
        try:
            state = build_state(prep, d, season, cfg)
        except ValueError:
            continue
        hist = prep.players[(prep.players.date < d)]
        base = hist[hist.season == season].groupby("player_id")[["pts", "reb", "ast", "fg3m", "min"]].mean()
        base_prev = hist[hist.season == season - 1].groupby("player_id")[["pts", "reb", "ast", "fg3m", "min"]].mean()
        tbase = prep.teams[(prep.teams.date < d) & (prep.teams.season == season)].groupby("team_id").pts.mean()
        day = P[P.date == d]
        for gid, gp in day.groupby("game_id"):
            g = games[games.game_id == gid]
            if g.empty:
                continue
            g = g.iloc[0]
            rosters = {}
            for tid in (g.home_team_id, g.visitor_team_id):
                ids = [i for i in gp[gp.team_id == tid].player_id if i in state.players.index]
                skipped += int((gp.team_id == tid).sum()) - len(ids)
                rosters[tid] = pd.DataFrame(dict(player_id=ids, avail=1.0, injury_status="", flags=""))
            sim = simulate_game(state, g.home_team_id, g.visitor_team_id, rosters[g.home_team_id],
                                rosters[g.visitor_team_id], cfg, n_sims, seed=int(gid) % 2**31)
            meta = dict(game_id=int(gid), date=d, home_team_id=int(g.home_team_id),
                        away_team_id=int(g.visitor_team_id))
            rows, team, _ = summarize(sim, meta)
            act = gp.set_index("player_id")
            draws = {}
            for side in ("home", "away"):
                Ps, D, _r = sim[side]
                for j, pid in enumerate(Ps.index):
                    draws[pid] = {k: v[:, j] for k, v in D.items()}
            urng = np.random.default_rng(int(gid))
            for r in rows:
                a = act.loc[r["player_id"]]
                b = base.loc[r["player_id"]] if r["player_id"] in base.index else (
                    base_prev.loc[r["player_id"]] if r["player_id"] in base_prev.index else None)
                rec = dict(date=d, game_id=gid, player_id=r["player_id"], name=r["name"])
                for s in ("pts", "reb", "ast", "fg3m", "min"):
                    rec[f"proj_{s}"] = r[s]
                    rec[f"act_{s}"] = float(a[s])
                    rec[f"base_{s}"] = float(b[s]) if b is not None else np.nan
                for s in ("pts", "reb", "ast", "fg3m", "pra", "min"):
                    actual = float(a["pts"] + a["reb"] + a["ast"]) if s == "pra" else float(a[s])
                    x = draws[r["player_id"]][s]
                    # randomized PIT: correct calibration test for discrete stats
                    pit = (x < actual).mean() + urng.random() * (x == actual).mean()
                    rec[f"pit_{s}"] = pit
                    rec[f"in80_{s}"] = 0.1 <= pit <= 0.9
                preds.append(rec)
            ah = int(g.home_score) if pd.notna(g.home_score) else np.nan
            aa = int(g.visitor_score) if pd.notna(g.visitor_score) else np.nan
            tpreds.append(dict(date=d, game_id=gid, proj_home=team["home_pts"], proj_away=team["away_pts"],
                               act_home=ah, act_away=aa, base_home=tbase.get(g.home_team_id, np.nan),
                               base_away=tbase.get(g.visitor_team_id, np.nan),
                               proj_total=team["total"], home_win_prob=team["home_win_prob"]))
    pr, tp = pd.DataFrame(preds), pd.DataFrame(tpreds)
    os.makedirs(out_dir, exist_ok=True)
    pr.to_csv(f"{out_dir}/backtest_players_{season}.csv", index=False)
    tp.to_csv(f"{out_dir}/backtest_games_{season}.csv", index=False)
    return report(pr, tp, skipped)


def calibrate(store: Store, season: int, cfg: ModelConfig, start=None, end=None, n_sims=400, every=4,
              k_mults=(1.0, 0.5, 0.25), recons=(0.8, 0.4, 0.0), out_dir="out"):
    """Grid over shrinkage strength and team reconciliation on a real walk-forward backtest.
    Pick the row whose slopes sit closest to 1.00 without worse MAE, then set k_poss/recon_alpha."""
    import dataclasses
    rows = []
    for km in k_mults:
        for ra in recons:
            c = dataclasses.replace(cfg, k_poss={k: v * km for k, v in cfg.k_poss.items()}, recon_alpha=ra)
            rep = backtest(store, season, c, start, end, n_sims, out_dir, every)
            r = dict(k_mult=km, recon_alpha=ra)
            for line in rep.splitlines():
                parts = line.split()
                if parts and parts[0] in ("pts", "reb", "ast", "fg3m", "min") and len(parts) == 5:
                    r[f"mae_{parts[0]}"] = float(parts[1])
                if "slope" in line and "Q1" in line:
                    r[f"slope_{parts[0]}"] = float(parts[2])
            r["slope_dev"] = round(sum(abs(r.get(f"slope_{s}", 1) - 1) for s in ("pts", "reb", "ast", "fg3m")), 3)
            rows.append(r)
            log.info("k x%s recon %s done", km, ra)
    df = pd.DataFrame(rows).sort_values(["slope_dev", "mae_pts"])
    os.makedirs(out_dir, exist_ok=True)
    df.to_csv(f"{out_dir}/calibration_{season}.csv", index=False)
    return df


def _fit_logit(X, y, iters=50):
    """Plain IRLS logistic regression. Returns coefficients and standard errors."""
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b))
        W = np.clip(p * (1 - p), 1e-9, None)
        H = X.T @ (X * W[:, None])
        step = np.linalg.solve(H, X.T @ (y - p))
        b += step
        if np.abs(step).max() < 1e-8:
            break
    p = 1 / (1 + np.exp(-X @ b))
    H = X.T @ (X * (p * (1 - p))[:, None])
    se = np.sqrt(np.diag(np.linalg.inv(H)))
    return b, se


def fit_market(store: Store, season: int, lines_path: str, cfg: ModelConfig, n_sims=2000, out_dir="out"):
    """How much is a model edge worth against the market? Uses historical prop lines with prices.

    lines CSV columns: date (YYYY-MM-DD), player_id or player ("First Last"), stat, line,
    over_odds, under_odds [, book]. One row per book per prop is fine.
    For each date: model state from games strictly before that date; the game is simulated with the
    players who actually played (props void on DNP, so this matches settlement). Pushes are dropped.

    Fit: P(over) = sigmoid(a + b_m*logit(model) + b_k*logit(no-vig market)).
      w = b_m / (b_m + b_k) is the model's weight for Option B.
    Also reports realized ROI by model-only EV bucket, which sets the Option A bar."""
    import dataclasses
    from .project import implied, stat_key
    cfg = dataclasses.replace(cfg, rotation_cut=False)
    lines = pd.read_csv(lines_path)
    lines["date"] = pd.to_datetime(lines["date"]).dt.strftime("%Y-%m-%d")
    lines["skey"] = lines["stat"].map(stat_key)
    prep = load_prep(store)
    P = prep.players
    P = P.assign(ds=P.date.dt.strftime("%Y-%m-%d"), pra=P.pts + P.reb + P.ast, pr=P.pts + P.reb,
                 pa=P.pts + P.ast, ra=P.reb + P.ast, stocks=P.stl + P.blk)
    names = (P.first_name.fillna("") + " " + P.last_name.fillna("")).str.strip().str.lower()
    P = P.assign(nm=names)
    games = store.df("SELECT * FROM games WHERE season=? AND postseason=0", (season,))
    rows, miss = [], 0
    for d, Ld in lines.groupby("date"):
        day = P[P.ds == d]
        if day.empty:
            miss += len(Ld); continue
        try:
            state = build_state(prep, d, season, cfg)
        except ValueError:
            miss += len(Ld); continue
        draws = {}
        for gid, gp in day.groupby("game_id"):
            g = games[games.game_id == gid]
            if g.empty:
                continue
            g = g.iloc[0]
            ros = {}
            for tid in (g.home_team_id, g.visitor_team_id):
                ids = [i for i in gp[gp.team_id == tid].player_id if i in state.players.index]
                ros[tid] = pd.DataFrame(dict(player_id=ids, avail=1.0, injury_status="", flags=""))
            sim = simulate_game(state, g.home_team_id, g.visitor_team_id, ros[g.home_team_id],
                                ros[g.visitor_team_id], cfg, n_sims, seed=int(gid) % 2**31)
            for side in ("home", "away"):
                Ps, D, _ = sim[side]
                for j, pid in enumerate(Ps.index):
                    draws[pid] = {k: v[:, j] for k, v in D.items()}
        act = day.set_index("player_id")
        by_name = day.drop_duplicates("nm").set_index("nm")["player_id"]
        for _, L in Ld.iterrows():
            pid = L.get("player_id") if "player_id" in L and pd.notna(L.get("player_id")) else by_name.get(str(L.get("player", "")).strip().lower())
            if pid is None or pid not in draws or pid not in act.index or L.skey not in draws[pid]:
                miss += 1; continue
            a = act.loc[pid]
            a = a.iloc[0] if isinstance(a, pd.DataFrame) else a
            actual, line = float(a[L.skey]), float(L.line)
            if actual == line:
                continue
            x = draws[pid][L.skey]
            x = x[draws[pid]["min"] > 0]
            po, pu = (x > line).mean(), (x < line).mean()
            if po + pu == 0:
                continue
            io, iu = implied(L.over_odds), implied(L.under_odds)
            dec_o = 1 + (100 / -L.over_odds if L.over_odds < 0 else L.over_odds / 100)
            dec_u = 1 + (100 / -L.under_odds if L.under_odds < 0 else L.under_odds / 100)
            pm = po / (po + pu)
            ev_o, ev_u = pm * dec_o - 1, (1 - pm) * dec_u - 1
            over_won = actual > line
            side_over = ev_o >= ev_u
            won = over_won if side_over else not over_won
            rows.append(dict(date=d, player_id=pid, stat=L.skey, line=line, book=L.get("book"),
                             p_model=pm, p_mkt=io / (io + iu), y=int(over_won),
                             ev_best=max(ev_o, ev_u), side="OVER" if side_over else "UNDER",
                             profit=(dec_o - 1 if side_over else dec_u - 1) if won else -1.0))
    df = pd.DataFrame(rows)
    os.makedirs(out_dir, exist_ok=True)
    df.to_csv(f"{out_dir}/fit_market_rows_{season}.csv", index=False)
    if len(df) < 200:
        return f"only {len(df)} settled lines matched ({miss} unmatched); need a few thousand for a stable fit", df

    X = np.column_stack([np.ones(len(df)), _logit_np(df.p_model), _logit_np(df.p_mkt)])
    b, se = _fit_logit(X, df.y.to_numpy().astype(float))
    w = b[1] / (b[1] + b[2]) if (b[1] + b[2]) > 0 else float("nan")
    ll = lambda p: np.mean(df.y * np.log(p) + (1 - df.y) * np.log(1 - p))
    out = [f"settled lines: {len(df)}  (unmatched {miss}, pushes dropped)",
           f"fit: intercept {b[0]:+.3f}  model coef {b[1]:.3f} (se {se[1]:.3f})  market coef {b[2]:.3f} (se {se[2]:.3f})",
           f"=> model weight w = {w:.2f}   (Option B: set market_blend_w = {w:.2f})",
           f"log-loss  model {-ll(np.clip(df.p_model, 1e-4, 1-1e-4)):.4f}  market {-ll(np.clip(df.p_mkt, 1e-4, 1-1e-4)):.4f}  "
           f"(lower is better; model must beat market here to have any edge at all)",
           "", "model-only EV bucket -> bets, hit rate, realized ROI (Option A bar = lowest bucket that is reliably > 0):"]
    pos = df[df.ev_best > 0]
    bins = [0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.15, 10]
    for lab, g in pos.groupby(pd.cut(pos.ev_best, bins), observed=True):
        roi = g.profit.mean()
        se_roi = g.profit.std(ddof=1) / np.sqrt(len(g)) if len(g) > 1 else float("nan")
        out.append(f"  EV {str(lab):14} n={len(g):5d}  hit {(g.profit > 0).mean():5.1%}  ROI {roi:+6.1%} +/- {1.96*se_roi:5.1%}")
    by_month = pos.assign(m=pos.date.str[:7]).groupby("m").profit.agg(["size", "mean"])
    out.append("")
    out.append("ROI of all +EV model picks by month (early-season penalty shows here): " +
               ", ".join(f"{m} {r['mean']:+.1%} (n={int(r['size'])})" for m, r in by_month.iterrows()))
    return "\n".join(out), df


def _logit_np(p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def report(pr, tp, skipped=0):
    lines = []
    if pr.empty:
        return "no predictions"
    lines.append(f"player-games: {len(pr)}  (rows skipped, no prior history: {skipped})")
    lines.append(f"{'stat':6} {'MAE model':>10} {'MAE base':>9} {'bias':>7} {'80% cover':>10}")
    for s in ("pts", "reb", "ast", "fg3m", "min"):
        m = pr.dropna(subset=[f"base_{s}"])
        mae = (m[f"proj_{s}"] - m[f"act_{s}"]).abs().mean()
        mb = (m[f"base_{s}"] - m[f"act_{s}"]).abs().mean()
        bias = (pr[f"proj_{s}"] - pr[f"act_{s}"]).mean()
        cov = pr[f"in80_{s}"].mean()
        lines.append(f"{s:6} {mae:10.3f} {mb:9.3f} {bias:7.3f} {cov:10.1%}")
    lines.append(f"{'pra':6} {'':>10} {'':>9} {'':>7} {pr['in80_pra'].mean():10.1%}")
    # compression check: slope of actual on projected. 1.00 = calibrated; >1 = projections
    # squeezed toward the middle (stars under, role players over), which shows up as unders on
    # stars and overs on role players against the market.
    lines.append("compression (slope actual~proj, >1 = stars low/role players high) and actual/proj by projection quintile:")
    for s in ("pts", "reb", "ast", "fg3m", "min"):
        x, y = pr[f"proj_{s}"], pr[f"act_{s}"]
        slope = np.cov(x, y)[0, 1] / max(np.var(x, ddof=1), 1e-9)
        q = pd.qcut(x.rank(method="first"), 5, labels=False)
        ratio = (y.groupby(q).mean() / x.groupby(q).mean().clip(lower=1e-9)).round(2).tolist()
        lines.append(f"  {s:5} slope {slope:5.2f}  Q1..Q5 {ratio}")
    if not tp.empty:
        t = tp.dropna()
        pts_err = pd.concat([t.proj_home - t.act_home, t.proj_away - t.act_away])
        base_err = pd.concat([t.base_home - t.act_home, t.base_away - t.act_away])
        win = ((t.act_home > t.act_away).astype(float))
        brier = ((t.home_win_prob - win) ** 2).mean()
        lines.append(f"team pts MAE model {pts_err.abs().mean():.2f} vs base {base_err.abs().mean():.2f}, "
                     f"bias {pts_err.mean():+.2f}; total MAE {(t.proj_total - t.act_home - t.act_away).abs().mean():.2f}; "
                     f"win-prob Brier {brier:.4f} over {len(t)} games")
    return "\n".join(lines)
