"""Scorecard: replay the model on Staicy's graded lines (as-of each date, no look-ahead).

Input CSV (exported from the results admin): id, game_time, player_name, bet_type, side, line,
odds, predicted, actual, result, ev_milli, teams_playing.

For each graded date the model is rebuilt from games strictly before that date and each game is
simulated with the players who actually played (oracle availability, same for every model version,
so versions are comparable; live error from injury news is not in this number).

Metrics on the graded player props:
  slope   regression of (actual - line) on (model mean - line): 1.0 = gaps fully real, 0 = noise
  w       logistic weight of the model vs the book price in log-odds (what calibration would use)
  ll      log-loss of the model's probability for the graded side vs the book's implied
  picks   hit rate and ROI of the side the model prefers where its own EV > 5%
"""
import numpy as np
import pandas as pd

from .features import build_state
from .project import simulate_game

BET_TO_STAT = {"points": "pts", "rebounds": "reb", "assists": "ast", "three_points": "fg3m",
               "points_rebounds": "pr", "points_assists": "pa", "rebounds_assists": "ra",
               "points_rebounds_assists": "pra", "steals": "stl", "blocks": "blk", "turnovers": "tov"}


def _dec(o):
    return 1 + (100 / -o if o < 0 else o / 100)


def load_lines(path, prep):
    L = pd.read_csv(path)
    L = L[L.bet_type.isin(BET_TO_STAT)].copy()
    L["stat"] = L.bet_type.map(BET_TO_STAT)
    L["gdate"] = pd.to_datetime(L.game_time.str[:10])
    P = prep.players
    nm = (P.first_name.fillna("") + " " + P.last_name.fillna("")).str.strip().str.lower()
    key = pd.DataFrame({"nm": nm, "player_id": P.player_id, "date": P.date, "game_id": P.game_id})
    key = key[key.date >= pd.Timestamp("2026-10-01")]
    L["nm"] = L.player_name.str.strip().str.lower()
    m = []
    for _, r in L.iterrows():
        k = key[(key.nm == r.nm) & ((key.date - r.gdate).abs() <= pd.Timedelta(days=1))]
        m.append((k.player_id.iloc[0], k.game_id.iloc[0], k.date.iloc[0]) if len(k) else (np.nan, np.nan, pd.NaT))
    L[["player_id", "game_id", "date"]] = pd.DataFrame(m, index=L.index)
    return L


def replay(store, prep, lines, cfg, n_sims=1500, season=2026, state_hook=None):
    """state_hook(state, date) lets a model variant modify the state (e.g. new minutes) before sims."""
    games = store.df("SELECT * FROM games WHERE season=? AND postseason=0", (season,))
    out = []
    L = lines.dropna(subset=["player_id"])
    for d, Ld in L.groupby("date"):
        ds = d.strftime("%Y-%m-%d")
        state = build_state(prep, ds, season, cfg)
        if state_hook:
            state = state_hook(state, ds)
        day = prep.players[(prep.players.date == d)]
        for gid, Lg in Ld.groupby("game_id"):
            g = games[games.game_id == gid]
            gp = day[day.game_id == gid]
            if g.empty or gp.empty:
                continue
            g = g.iloc[0]
            ros = {}
            for tid in (g.home_team_id, g.visitor_team_id):
                ids = [i for i in gp[gp.team_id == tid].player_id if i in state.players.index]
                ros[tid] = pd.DataFrame(dict(player_id=ids, avail=1.0, injury_status="", flags=""))
            sim = simulate_game(state, g.home_team_id, g.visitor_team_id, ros[g.home_team_id],
                                ros[g.visitor_team_id], cfg, n_sims, seed=int(gid) % 2**31)
            draws = {}
            for side in ("home", "away"):
                Ps, D, _ = sim[side]
                for j, pid in enumerate(Ps.index):
                    draws[pid] = (D, j)
            for _, r in Lg.iterrows():
                if r.player_id not in draws:
                    continue
                D, j = draws[r.player_id]
                played = D["min"][:, j] > 0
                x = D[r.stat][played, j]
                if len(x) == 0:
                    continue
                po, pu = (x > r.line).mean(), (x < r.line).mean()
                pm = po / (po + pu) if po + pu else 0.5
                out.append(dict(id=r.id, date=ds, stat=r.stat, side=r.side, line=r.line, odds=r.odds,
                                actual=r.actual, staicy_pred=r.predicted, model_mean=float(x.mean()),
                                model_min=float(D["min"][played, j].mean()), p_over=pm))
    return pd.DataFrame(out)


def score(df):
    df = df[df.actual != df.line].copy()
    df["y_over"] = (df.actual > df.line).astype(int)
    imp = lambda o: np.where(o < 0, -o / (-o + 100), 100 / (o + 100))
    # book probability of the graded side, vig removed approximately (one side known)
    p_side_book = np.clip(imp(df.odds) / 1.045, 0.02, 0.98)
    df["p_over_book"] = np.where(df.side == "over", p_side_book, 1 - p_side_book)
    gap_m, gap_a = df.model_mean - df.line, df.actual - df.line
    slope = np.cov(gap_m, gap_a)[0, 1] / np.var(gap_m, ddof=1)
    lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
    off, dd, y = lg(df.p_over_book), lg(df.p_over) - lg(df.p_over_book), df.y_over.to_numpy()
    w = 0.0
    for _ in range(50):
        p = 1 / (1 + np.exp(-(off + w * dd)))
        g, h = ((y - p) * dd).sum(), (p * (1 - p) * dd * dd).sum()
        w += g / h
    p = 1 / (1 + np.exp(-(off + w * dd)))
    se_w = 1 / np.sqrt((p * (1 - p) * dd * dd).sum())
    ll = lambda q: -np.mean(y * np.log(np.clip(q, 1e-4, 1)) + (1 - y) * np.log(np.clip(1 - q, 1e-4, 1)))
    # model's own picks: side with model EV > 5% at the graded price (graded side only is priced)
    p_side_model = np.where(df.side == "over", df.p_over, 1 - df.p_over)
    ev = p_side_model * df.odds.map(_dec) - 1
    won = np.where(df.side == "over", y == 1, y == 0)
    pick = ev > 0.05
    units = np.where(won, np.where(df.odds < 0, 1.0, df.odds / 100), np.where(df.odds < 0, df.odds / 100, -1.0))
    mm = (df.model_mean - df.actual)
    return dict(n=len(df), slope=round(float(slope), 3), w=round(float(w), 3), w_se=round(float(se_w), 3),
                ll_model=round(ll(df.p_over), 4), ll_book=round(ll(df.p_over_book), 4),
                mae=round(float(mm.abs().mean()), 3), bias=round(float(mm.mean()), 3),
                picks=int(pick.sum()), pick_hit=round(float(won[pick].mean()), 3) if pick.any() else None,
                pick_roi=round(float(units[pick].mean()), 3) if pick.any() else None)


def score_by(df, col):
    return pd.DataFrame({k: score(g) for k, g in df.groupby(col) if len(g) >= 80}).T
