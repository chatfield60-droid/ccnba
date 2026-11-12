"""Minutes model: gradient-boosted projection of minutes (and its spread) per player-game.

Every feature uses only games before the one projected, except the starter flag, which is known
pregame from BDL /nba/v1/projected_lineups (confirmed ~30 min before tip). In backtests the actual
starter flag (BDL /nba/v1/lineups) stands in for the confirmed lineup.

Features
  m_l1, m_l3, m_l5, m_l10, m_ewm3, m_ewm10   minutes in recent games he played
  m_season, n_season                          current-season average and games
  starter, start_rate10, start_change         starting tonight vs recent starting rate
  rest, b2b                                    team rest days (capped at 5)
  missed_before, games_back                    games missed right before tonight; games since return
  out_min, out_min_pos                         recent minutes of regular teammates not playing tonight
                                               (all, and same position group)
  exp_margin_abs                               |expected margin| from point differential (blowout risk)
  pf36                                         fouls per 36 (foul-trouble risk)
  game_no                                      team game number in the season
"""
import numpy as np
import pandas as pd

FEATS = ["m_l1", "m_l3", "m_l5", "m_l10", "m_ewm3", "m_ewm10", "m_season", "n_season", "starter",
         "start_rate10", "start_change", "rest", "b2b", "missed_before", "games_back", "out_min",
         "out_min_pos", "exp_margin_abs", "pf36", "game_no"]


def _pos(p):
    p = (p or "").strip().upper()
    return p[0] if p and p[0] in "GFC" else "F"


def build_frame(stats: pd.DataFrame, games: pd.DataFrame, starters: pd.DataFrame = None) -> pd.DataFrame:
    """stats: raw player_stats rows (including 0-minute rows). Returns one row per player-team-game
    with features (from prior games) and target `min`."""
    s = stats[stats.postseason == 0].copy()
    s["date"] = pd.to_datetime(s["date"])
    s["pos"] = s["position"].map(_pos)
    s["played"] = (s["min"] > 0).astype(int)
    if starters is not None and len(starters):
        s = s.merge(starters[["game_id", "player_id", "starter"]], on=["game_id", "player_id"], how="left")
    else:
        s["starter"] = np.nan

    # team schedule: rest, game number, expected margin from prior point differential
    # all regular-season games, including scheduled ones (for tonight's rest/game number); point
    # differential only from finished games
    g = games[(games.postseason == 0) & (games.postponed == 0)].copy()
    g["date"] = pd.to_datetime(g["date"])
    fin = g.status.astype(str).str.contains("Final") & (g.home_score.fillna(0) + g.visitor_score.fillna(0) > 0)
    hd = np.where(fin, g.home_score - g.visitor_score, np.nan)
    tg = pd.concat([
        g.assign(team_id=g.home_team_id, opp_id=g.visitor_team_id, diff=hd, home=1),
        g.assign(team_id=g.visitor_team_id, opp_id=g.home_team_id, diff=-hd, home=0)
    ])[["game_id", "date", "season", "team_id", "opp_id", "diff", "home"]].sort_values(["team_id", "date"])
    tg["rest"] = tg.groupby(["team_id", "season"]).date.diff().dt.days.clip(upper=5).fillna(5)
    tg["b2b"] = (tg.rest == 1).astype(int)
    tg["game_no"] = tg.groupby(["team_id", "season"]).cumcount() + 1
    tg["rating"] = tg.groupby("team_id")["diff"].transform(
        lambda x: x.shift().ewm(halflife=15, min_periods=1, ignore_na=True).mean()).ffill().fillna(0)
    opp = tg[["game_id", "team_id", "rating"]].rename(columns={"team_id": "opp_id", "rating": "opp_rating"})
    tg = tg.merge(opp, on=["game_id", "opp_id"], how="left")
    tg["exp_margin_abs"] = (tg.rating - tg.opp_rating + np.where(tg.home == 1, 2.0, -2.0)).abs()
    s = s.merge(tg[["game_id", "team_id", "rest", "b2b", "game_no", "exp_margin_abs"]], on=["game_id", "team_id"], how="left")

    # player history features (shifted: strictly prior games)
    s = s.sort_values(["player_id", "date"])
    gp = s.groupby("player_id")
    mp = s["min"].where(s.played == 1)                      # minutes in games he played
    s["_mp"] = mp
    roll = lambda w: gp["_mp"].transform(lambda x: x.shift().rolling(w, min_periods=1).mean())
    # rolling over PLAYED games only: drop DNP rows inside the window via a played-only index
    played = s[s.played == 1].copy()
    pg = played.groupby("player_id")["min"]
    for w in (1, 3, 5, 10):
        played[f"m_l{w}"] = pg.transform(lambda x, w=w: x.shift().rolling(w, min_periods=1).mean())
    played["m_ewm3"] = pg.transform(lambda x: x.shift().ewm(halflife=3, min_periods=1).mean())
    played["m_ewm10"] = pg.transform(lambda x: x.shift().ewm(halflife=10, min_periods=1).mean())
    played["pf36"] = played.groupby("player_id").apply(
        lambda d: (d.pf.shift().rolling(10, min_periods=1).sum() /
                   d["min"].shift().rolling(10, min_periods=1).sum().clip(lower=1) * 36), include_groups=False
    ).reset_index(level=0, drop=True)
    cols = ["m_l1", "m_l3", "m_l5", "m_l10", "m_ewm3", "m_ewm10", "pf36"]
    # carry the latest prior played-game values onto every row (incl. DNP rows) via asof merge
    s = s.drop(columns=["_mp"])
    played_last = played[["player_id", "date"] + cols].copy()
    played_last["date_feat"] = played_last["date"]
    s = pd.merge_asof(s.sort_values("date"), played_last.drop(columns="date").rename(columns={"date_feat": "date"}).sort_values("date"),
                      on="date", by="player_id", direction="backward", allow_exact_matches=True)
    # allow_exact_matches picks up the current game's own shifted features (which use only prior games)
    s = s.sort_values(["player_id", "date"])
    gp = s.groupby("player_id")
    s["m_season"] = gp.apply(lambda d: d["min"].where(d.played == 1).shift().groupby(d.season).transform(
        lambda x: x.expanding().mean()), include_groups=False).reset_index(level=0, drop=True)
    s["n_season"] = gp.apply(lambda d: d.played.shift().fillna(0).groupby(d.season).cumsum(),
                             include_groups=False).reset_index(level=0, drop=True)
    s["start_rate10"] = gp["starter"].transform(lambda x: x.shift().rolling(10, min_periods=1).mean())
    s["start_change"] = s["starter"] - s["start_rate10"]
    # absence: consecutive missed (0-min or missing-row) team games right before tonight
    s["missed_before"] = gp["played"].transform(
        lambda x: x.shift().fillna(1).groupby((x.shift().fillna(1) == 1).cumsum()).cumcount())
    s["back_flag"] = (s.missed_before >= 2).astype(int)
    seg = s.groupby("player_id").back_flag.cumsum()
    s["games_back"] = s.groupby([s.player_id, seg]).cumcount().clip(upper=10)

    # teammates out: regulars (m_l10 >= 15 and played in one of the team's previous 3 games) not playing tonight
    s = s.sort_values(["team_id", "date"])
    s["reg"] = (s.m_l10.fillna(0) >= 15)
    team_games = s[["team_id", "game_id", "date"]].drop_duplicates().sort_values(["team_id", "date"])
    team_games["tg_idx"] = team_games.groupby("team_id").cumcount()
    s = s.merge(team_games[["game_id", "team_id", "tg_idx"]], on=["game_id", "team_id"], how="left")
    last_play_idx = s[s.played == 1][["player_id", "team_id", "tg_idx", "m_l10", "pos"]]
    out_rows = []
    for tid, T in s.groupby("team_id"):
        P = last_play_idx[last_play_idx.team_id == tid]
        for gid, G in T.groupby("game_id"):
            k = int(G.tg_idx.iloc[0])
            recent = P[(P.tg_idx < k) & (P.tg_idx >= k - 3) & (P.m_l10 >= 15)].drop_duplicates("player_id", keep="last")
            playing = set(G[G.played == 1].player_id)
            out = recent[~recent.player_id.isin(playing)]
            tot = float(out.m_l10.sum())
            by_pos = out.groupby("pos").m_l10.sum().to_dict()
            out_rows.append((gid, tid, tot, by_pos))
    om = pd.DataFrame([(a, b, c) for a, b, c, _ in out_rows], columns=["game_id", "team_id", "out_min"])
    s = s.merge(om, on=["game_id", "team_id"], how="left")
    pos_map = {(a, b): d for a, b, _, d in out_rows}
    s["out_min_pos"] = [pos_map.get((g_, t_), {}).get(p_, 0.0) for g_, t_, p_ in zip(s.game_id, s.team_id, s.pos)]
    return s


class MinutesModel:
    """Two gradient-boosted models: mean minutes, and the size of the miss (for the spread)."""

    def __init__(self):
        from sklearn.ensemble import HistGradientBoostingRegressor
        # fixed iterations, no random early-stopping split: identical results on every run
        self.mean = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                                  min_samples_leaf=80, l2_regularization=1.0,
                                                  early_stopping=False, random_state=0)
        self.spread = HistGradientBoostingRegressor(loss="absolute_error", max_iter=200, learning_rate=0.05,
                                                    max_leaf_nodes=15, min_samples_leaf=150,
                                                    early_stopping=False, random_state=0)

    def fit(self, F: pd.DataFrame):
        """Fits on all played games. The spread scale is set out-of-sample: fit on the earliest 80%
        of dates, measure how much wider real misses are than predicted on the last 20%."""
        d = F[(F.played == 1) & F.m_l1.notna()].sort_values("date")
        cut = d.date.quantile(0.8)
        a, b = d[d.date < cut], d[d.date >= cut]
        self._fit_core(a)
        mu, sd = self._raw(b)
        self.sd_scale = float(np.clip(np.std((b["min"] - mu) / sd), 1.0, 2.0))
        self._fit_core(d)
        return self

    def _fit_core(self, d):
        self.mean.fit(d[FEATS], d["min"])
        self.spread.fit(d[FEATS], (d["min"] - self.mean.predict(d[FEATS])).abs())

    def _raw(self, F):
        mu = np.clip(self.mean.predict(F[FEATS]), 0, 46)
        return mu, np.clip(self.spread.predict(F[FEATS]) * 1.2533, 2.0, 14.0)

    def predict(self, F: pd.DataFrame):
        """mean minutes and sd (mean absolute miss -> normal sd, times the out-of-sample scale)"""
        mu, sd = self._raw(F)
        return mu, sd * getattr(self, "sd_scale", 1.35)


def live_rows(stats, games, rosters, starters_tonight):
    """Placeholder rows for tonight's projected players so build_frame computes their features from
    history. rosters: DataFrame[player_id, team_id, game_id, date, season, position] of players
    expected to be available; starters_tonight: set of player_ids in confirmed/expected lineups
    (None = unknown, model falls back to recent starting rate)."""
    r = rosters.copy()
    for c in ("fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "reb", "ast", "stl", "blk", "tov",
              "pf", "pts", "plus_minus"):
        r[c] = 0
    r["min"] = 1.0                 # marks the row as a game he plays; his own minutes never feed his features
    r["postseason"] = 0
    r["stat_id"] = -1
    return r


def predict_tonight(model, stats, games, starters_hist, rosters, starters_tonight=None):
    """mu, sd per player for tonight's games. Features use only finished games."""
    live = live_rows(stats, games, rosters, starters_tonight)
    allrows = pd.concat([stats, live[stats.columns.intersection(live.columns)]], ignore_index=True)
    st = starters_hist
    if starters_tonight is not None:
        add = live[["game_id", "player_id"]].assign(starter=live.player_id.isin(starters_tonight).astype(int))
        st = pd.concat([starters_hist[["game_id", "player_id", "starter"]], add], ignore_index=True)
    F = build_frame(allrows, games, st)
    key = set(zip(live.game_id, live.player_id))
    T = F[[(g_, p_) in key for g_, p_ in zip(F.game_id, F.player_id)]].copy()
    T = T[T.m_l1.notna()]
    mu, sd = model.predict(T)
    return pd.DataFrame({"player_id": T.player_id.values, "game_id": T.game_id.values, "min_mu": mu, "min_sd": sd})
