"""Turns cached BDL box scores into model state as of a date (strictly games before it).

Everything is derived from /v1/stats player rows:
  * team-game totals are sums of player rows
  * possessions = FGA - OREB + TOV + 0.44*FTA, averaged across both teams
  * pace = possessions per 48, using summed player minutes / 5 for game length (catches OT)
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import COUNT_STATS, ModelConfig

SUM_COLS = ["min", "fgm", "fga", "fg3m", "fg3a", "fg2m", "fg2a", "ftm", "fta", "oreb",
            "dreb", "reb", "ast", "stl", "blk", "tov", "pf", "pts"]


def pos_group(p):
    p = (p or "").strip().upper()
    return p[0] if p and p[0] in "GFC" else "F"


@dataclass
class Prepared:
    players: pd.DataFrame   # one row per player-game appearance
    teams: pd.DataFrame     # one row per team-game


def prepare(stats: pd.DataFrame) -> Prepared:
    df = stats[(stats["postseason"] == 0)].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["fg2m"] = df["fgm"] - df["fg3m"]
    df["fg2a"] = df["fga"] - df["fg3a"]
    df["pos"] = df["position"].map(pos_group)

    tg = df.groupby(["game_id", "team_id"], as_index=False).agg(
        date=("date", "first"), season=("season", "first"), opp_id=("opp_id", "first"),
        is_home=("is_home", "first"), **{c: (c, "sum") for c in SUM_COLS})
    gm = (tg["min"] / 5.0)
    tg["game_min"] = np.where((gm >= 46) & (gm <= 75), gm, 48.0)  # guard bad minute data
    tg["poss_own"] = tg["fga"] - tg["oreb"] + tg["tov"] + 0.44 * tg["fta"]
    opp = tg[["game_id", "team_id", "poss_own"]].rename(columns={"team_id": "opp_id", "poss_own": "poss_opp"})
    tg = tg.merge(opp, on=["game_id", "opp_id"], how="left")
    tg["poss"] = tg[["poss_own", "poss_opp"]].mean(axis=1)
    tg["pace"] = tg["poss"] * 48.0 / tg["game_min"]
    tg = tg[tg["poss"] > 50]  # drops partial/incomplete games

    df = df[df["min"] > 0].merge(tg[["game_id", "team_id", "poss", "game_min", "pace"]],
                                 on=["game_id", "team_id"], how="inner")
    df["onfloor_poss"] = df["poss"] * df["min"] / df["game_min"]
    return Prepared(players=df, teams=tg)


def _decay(df, key, hl, prior_w, season):
    d = df.sort_values("date", ascending=False)
    r = d.groupby(key).cumcount().to_numpy()
    w = 0.5 ** (r / hl) * np.where(d["season"].to_numpy() < season, prior_w, 1.0)
    return d.assign(w=w)


@dataclass
class ModelState:
    as_of: pd.Timestamp
    season: int
    lg_pace: float
    team_minutes: float
    home_mult: float
    lg_rate_pos: pd.DataFrame      # pos x stat, per on-floor possession
    lg_pct_pos: pd.DataFrame       # pos x {fg2,fg3,ft}
    pace: pd.Series                # team -> pace rating
    team_rate: pd.DataFrame        # team x stat per team possession
    def_factor: pd.DataFrame       # defending team x stat (multiplier on opponent rate)
    def_pct: pd.DataFrame          # defending team x {fg2,fg3}
    players: pd.DataFrame          # player_id -> rates, pcts, minutes, metadata


def build_state(prep: Prepared, as_of, season: int, cfg: ModelConfig) -> ModelState:
    as_of = pd.Timestamp(as_of)
    P = prep.players[prep.players["date"] < as_of]
    T = prep.teams[prep.teams["date"] < as_of]
    if P.empty:
        raise ValueError(f"No BDL box score history before {as_of.date()}; sync earlier seasons.")

    sw_p = np.where(P["season"] < season, cfg.prior_season_weight, 1.0)
    sw_t = np.where(T["season"] < season, cfg.prior_season_weight, 1.0)

    # ---------- league baselines ----------
    lg_pace = np.average(T["pace"], weights=sw_t)
    team_minutes = np.average(T["game_min"] * 5.0, weights=sw_t)
    Pw = P.assign(sw=sw_p)
    g = Pw.groupby("pos")
    lg_rate_pos = pd.DataFrame({s: g.apply(lambda x, s=s: (x[s] * x.sw).sum() / (x.onfloor_poss * x.sw).sum(),
                                           include_groups=False) for s in COUNT_STATS})
    lg_pct_pos = pd.DataFrame({
        "fg2": g.apply(lambda x: (x.fg2m * x.sw).sum() / max((x.fg2a * x.sw).sum(), 1), include_groups=False),
        "fg3": g.apply(lambda x: (x.fg3m * x.sw).sum() / max((x.fg3a * x.sw).sum(), 1), include_groups=False),
        "ft": g.apply(lambda x: (x.ftm * x.sw).sum() / max((x.fta * x.sw).sum(), 1), include_groups=False),
    })
    for pos in "GFC":  # make sure every group exists
        if pos not in lg_rate_pos.index:
            lg_rate_pos.loc[pos] = lg_rate_pos.mean()
            lg_pct_pos.loc[pos] = lg_pct_pos.mean()

    lg_team_rate = {s: np.average(T[s] / T["poss"], weights=sw_t * T["poss"]) for s in COUNT_STATS}
    lg_pct2 = (T.fg2m * sw_t).sum() / (T.fg2a * sw_t).sum()
    lg_pct3 = (T.fg3m * sw_t).sum() / (T.fg3a * sw_t).sum()

    # home edge on shooting efficiency, from points per possession home vs road
    h = T[T.is_home == 1]; a = T[T.is_home == 0]
    raw_ratio = (h.pts.sum() / h.poss.sum()) / max(a.pts.sum() / a.poss.sum(), 1e-9)
    n_h = len(h)
    ratio = (n_h * raw_ratio + cfg.k_home_games * 1.0) / (n_h + cfg.k_home_games)
    home_mult = float(np.sqrt(ratio))

    # ---------- team offense: pace + per-possession rates ----------
    To = _decay(T, "team_id", cfg.hl_team, cfg.prior_season_weight, season)
    go = To.groupby("team_id")
    neff = go["w"].sum()
    pace_raw = go.apply(lambda x: np.average(x.pace, weights=x.w), include_groups=False)
    pace = (neff * pace_raw + cfg.k_pace_games * lg_pace) / (neff + cfg.k_pace_games)
    team_rate = pd.DataFrame({s: go.apply(lambda x, s=s: (x[s] * x.w).sum() / (x.poss * x.w).sum(),
                                          include_groups=False) for s in COUNT_STATS})
    for s in COUNT_STATS:
        team_rate[s] = (neff * team_rate[s] + cfg.k_def_games * lg_team_rate[s]) / (neff + cfg.k_def_games)

    # ---------- team defense: what opponents produce vs this team ----------
    Td = _decay(T.rename(columns={"team_id": "off_id", "opp_id": "def_id"}), "def_id",
                cfg.hl_team, cfg.prior_season_weight, season)
    gd = Td.groupby("def_id")
    neff_d = gd["w"].sum()
    def_factor = pd.DataFrame({s: gd.apply(lambda x, s=s: (x[s] * x.w).sum() / (x.poss * x.w).sum(),
                                           include_groups=False) / lg_team_rate[s] for s in COUNT_STATS})
    def_factor = def_factor.mul(neff_d, axis=0).add(cfg.k_def_games).div(neff_d + cfg.k_def_games, axis=0)
    def_pct = pd.DataFrame({
        "fg2": gd.apply(lambda x: (x.fg2m * x.w).sum() / (x.fg2a * x.w).sum(), include_groups=False) / lg_pct2,
        "fg3": gd.apply(lambda x: (x.fg3m * x.w).sum() / (x.fg3a * x.w).sum(), include_groups=False) / lg_pct3,
    })
    def_pct = def_pct.mul(neff_d, axis=0).add(cfg.k_def_pct_games).div(neff_d + cfg.k_def_pct_games, axis=0)

    # ---------- players ----------
    Pr = _decay(P, "player_id", cfg.hl_player_rates, cfg.prior_season_weight, season)
    wcols = COUNT_STATS + ["onfloor_poss", "fg2m", "fg3m", "ftm"]
    Pr_w = Pr[wcols].mul(Pr["w"], axis=0)
    Pr_w["player_id"] = Pr["player_id"].to_numpy()
    agg = Pr_w.groupby("player_id").sum()

    latest = Pr.drop_duplicates("player_id", keep="first").set_index("player_id")  # sorted desc
    pos = latest["pos"]
    out = pd.DataFrame(index=agg.index)
    out["name"] = latest["first_name"].fillna("") + " " + latest["last_name"].fillna("")
    out["pos"] = pos
    out["last_team_id"] = latest["team_id"]
    out["last_date"] = latest["date"]
    out["gp_season"] = P[P.season == season].groupby("player_id").size().reindex(out.index).fillna(0).astype(int)
    out["gp_total"] = P.groupby("player_id").size().reindex(out.index).fillna(0).astype(int)
    if cfg.role_tier_prior:
        # shrink toward players in the same position AND minutes role: bench players really do
        # shoot/assist less than the position average, so a position-wide prior inflates them
        # (measured: +6.6-10% two-point attempts league-wide on 2026-27).
        pmin = P.groupby("player_id")["min"].mean()
        tier_of = pd.cut(pmin, cfg.role_tiers, labels=False, include_lowest=True).fillna(0).astype(int)
        Pt = Pw.assign(tier=Pw.player_id.map(tier_of))
        gt = Pt.groupby(["pos", "tier"])
        lg_rt = pd.DataFrame({s: gt.apply(lambda x, s=s: (x[s] * x.sw).sum() / max((x.onfloor_poss * x.sw).sum(), 1e-9),
                                          include_groups=False) for s in COUNT_STATS})
        lg_pt = pd.DataFrame({key: gt.apply(lambda x, m=m, a=a: (x[m] * x.sw).sum() / max((x[a] * x.sw).sum(), 1),
                                            include_groups=False)
                              for key, m, a in [("fg2", "fg2m", "fg2a"), ("fg3", "fg3m", "fg3a"), ("ft", "ftm", "fta")]})
        keys = list(zip(pos, tier_of.reindex(out.index).fillna(0).astype(int)))
        rate_prior = lambda s: np.array([lg_rt[s].get(k_, lg_rate_pos.loc[k_[0], s]) for k_ in keys])
        pct_prior = lambda c: np.array([lg_pt[c].get(k_, lg_pct_pos.loc[k_[0], c]) for k_ in keys])
    else:
        rate_prior = lambda s: lg_rate_pos.loc[pos, s].to_numpy()
        pct_prior = lambda c: lg_pct_pos.loc[pos, c].to_numpy()
    for s in COUNT_STATS:
        k = cfg.k_poss[s]
        out[f"r_{s}"] = (agg[s] + k * rate_prior(s)) / (agg["onfloor_poss"] + k)
    for key, m, a in [("fg2", "fg2m", "fg2a"), ("fg3", "fg3m", "fg3a"), ("ft", "ftm", "fta")]:
        k = cfg.k_pct[key]
        out[f"pct_{key}"] = (agg[m] + k * pct_prior(key)) / (agg[a] + k)

    Pm = _decay(P, "player_id", cfg.hl_player_minutes, cfg.prior_season_weight_minutes, season)
    med = Pm.groupby("player_id")["min"].transform("median")
    short = Pm["min"] < cfg.short_game_frac * med
    Pm = Pm.assign(w=Pm["w"] * np.where(short, cfg.short_game_weight, 1.0))
    gm = Pm.assign(wm=Pm["w"] * Pm["min"]).groupby("player_id")
    mu = gm["wm"].sum() / gm["w"].sum()
    Pm = Pm.assign(dev=(Pm["min"] - Pm["player_id"].map(mu)) ** 2 * Pm["w"])
    var = Pm.groupby("player_id")["dev"].sum() / gm["w"].sum()
    out["min_mu"] = mu.reindex(out.index)
    sd = np.sqrt(var.reindex(out.index)).clip(lower=cfg.min_sd_floor)
    out["min_sd"] = np.where(out["gp_total"] >= 5, sd, cfg.min_sd_default)

    if cfg.league_env:
        # league environment: this season's league-wide shot mix, shooting % and pace so far vs the
        # history-weighted baseline the team and player rates are built on; weight grows with games
        # played this season (measured 2026-27: -4% 2PA, +2% 3PA, +4% FTA, lower 2P%/3P%).
        cur = T[T.season == season]
        wgt = len(cur) / (len(cur) + cfg.k_env_games)
        if len(cur):
            base_w = To["w"]
            for s in COUNT_STATS:
                base = (To[s] * base_w).sum() / max((To.poss * base_w).sum(), 1e-9)
                now = cur[s].sum() / max(cur.poss.sum(), 1e-9)
                f = 1 + wgt * (now / max(base, 1e-9) - 1)
                team_rate[s] = team_rate[s] * f
                out[f"r_{s}"] = out[f"r_{s}"] * f
            for key, m, a in [("fg2", "fg2m", "fg2a"), ("fg3", "fg3m", "fg3a"), ("ft", "ftm", "fta")]:
                base = (To[m] * base_w).sum() / max((To[a] * base_w).sum(), 1)
                now = cur[m].sum() / max(cur[a].sum(), 1)
                out[f"pct_{key}"] = out[f"pct_{key}"] * (1 + wgt * (now / base - 1))
            base_pace = np.average(To.pace, weights=base_w)
            fp = 1 + wgt * (cur.pace.mean() / base_pace - 1)
            pace = pace * fp
            lg_pace = lg_pace * fp

    return ModelState(as_of=as_of, season=season, lg_pace=float(lg_pace), team_minutes=float(team_minutes),
                      home_mult=home_mult, lg_rate_pos=lg_rate_pos, lg_pct_pos=lg_pct_pos, pace=pace,
                      team_rate=team_rate, def_factor=def_factor, def_pct=def_pct, players=out)


def q1_profile(q1: pd.DataFrame, full: pd.DataFrame, as_of, cfg: ModelConfig) -> pd.DataFrame:
    """Per-player first-quarter shares from BDL /v1/stats?period=1, games strictly before as_of.
    share_s = player's 1Q s / full-game s, shrunk toward the league share for players in the same
    minutes tier (starter-level vs bench), because a bench player's 1Q share is structurally lower.
    q1_min = recent first-quarter minutes (drives the first-3-minutes estimate)."""
    if q1 is None or q1.empty:
        return pd.DataFrame()
    as_of = pd.Timestamp(as_of)
    q = q1.copy(); q["date"] = pd.to_datetime(q["date"])
    q = q[(q.date < as_of) & (q.postseason == 0)]
    f = full[(full.date < as_of)][["game_id", "player_id", "min", "pts", "reb", "ast"]]
    j = q[["game_id", "player_id", "min", "pts", "reb", "ast", "date"]].merge(
        f, on=["game_id", "player_id"], suffixes=("_q", "_f"))
    j = j[j.min_f > 0]
    if j.empty:
        return pd.DataFrame()
    avg_min = j.groupby("player_id").min_f.mean()
    j["tier"] = j.player_id.map(avg_min >= 24).astype(int)
    out = pd.DataFrame(index=j.player_id.unique())
    for s, k in (("pts", cfg.k_q1["pts"]), ("reb", cfg.k_q1["reb"]), ("ast", cfg.k_q1["ast"])):
        lg = j.groupby("tier").apply(lambda g, s=s: g[f"{s}_q"].sum() / max(g[f"{s}_f"].sum(), 1), include_groups=False)
        g = j.groupby("player_id")[[f"{s}_q", f"{s}_f"]].sum()
        prior = g.index.map(lambda pid: lg.get(int(avg_min.get(pid, 0) >= 24), lg.mean()))
        out[f"q1_share_{s}"] = (g[f"{s}_q"] + k * prior) / (g[f"{s}_f"] + k)
    recent = j.sort_values("date").groupby("player_id").tail(20)
    out["q1_min"] = recent.groupby("player_id").min_q.mean()
    out["q1_games"] = j.groupby("player_id").size()
    return out
