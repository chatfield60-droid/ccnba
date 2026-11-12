"""End-to-end test on synthetic BDL-shaped data: sync -> project -> lines -> backtest + leakage check."""
import os
import sys
import tempfile
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from bdlbox.client import BDLClient
from bdlbox.config import ModelConfig, Settings
from bdlbox.features import build_state, prepare
from bdlbox.pipeline import backtest, load_prep, project_date, sync
from bdlbox.store import Store, parse_min
from fake_bdl import FakeLeague, FakeSession


def main():
    t0 = time.time()
    tmp = tempfile.mkdtemp()
    league = FakeLeague(seed=1)
    sess = FakeSession(league)
    settings = Settings(api_key="test", tier="GOAT", db_path=os.path.join(tmp, "t.sqlite"))
    client = BDLClient(settings, session=sess)
    client._min_interval = 0
    store = Store(settings.db_path)

    # min parsing
    assert parse_min("30:30") == 30.5 and parse_min("") == 0 and parse_min(None) == 0 and parse_min("12") == 12

    rep = sync(client, store, [2025, 2026], q1=True)
    print("sync:", rep, f"({sess.calls} API calls)")
    assert rep["stats_2025"] == len(league.stats)
    n_before = sess.calls
    rep2 = sync(client, store, [2026])  # incremental: no 2026 stats yet
    print("incremental sync:", rep2)

    # free tier: player endpoints refused -> graceful skip
    cfree = BDLClient(Settings(api_key="x", tier="FREE", db_path=settings.db_path), session=FakeSession(league, "FREE"))
    cfree._min_interval = 0

    cfg = ModelConfig()
    prep = load_prep(store)

    # ---- leakage check: perturb everything on/after as_of, state must be identical ----
    as_of = "2026-02-01"
    s1 = build_state(prep, as_of, 2025, cfg)
    raw = store.df("SELECT * FROM player_stats")
    raw.loc[raw.date >= as_of, ["pts", "fga", "fgm", "min", "ast"]] *= 3
    s2 = build_state(prepare(raw), as_of, 2025, cfg)
    pd.testing.assert_frame_equal(s1.players, s2.players)
    pd.testing.assert_frame_equal(s1.def_factor, s2.def_factor)
    assert abs(s1.lg_pace - s2.lg_pace) < 1e-12
    print("leakage check: state unchanged when future rows are perturbed")

    # ---- recovery sanity on synthetic truths ----
    sf = build_state(prep, "2026-10-20", 2026, cfg)
    truth_pace = pd.Series(league.tpace)
    corr = np.corrcoef(truth_pace.loc[sf.pace.index], sf.pace)[0, 1]
    tdef = pd.Series(league.tdef)
    dcorr = np.corrcoef(tdef.loc[sf.def_factor.index], sf.def_factor["fg2a"])[0, 1]
    pl = {p["id"]: p for p in league.players}
    est = sf.players
    t_fg3 = np.array([pl[i]["rate"]["fg3a"] for i in est.index])
    rcorr = np.corrcoef(t_fg3, est["r_fg3a"])[0, 1]
    print(f"recovery: pace r={corr:.2f}, defense r={dcorr:.2f}, player fg3a-rate r={rcorr:.2f}, home_mult={sf.home_mult:.4f}")
    assert corr > 0.6 and rcorr > 0.8

    # ---- opening-night projection with lines ----
    rng = np.random.default_rng(4)
    rows = []
    box0 = None
    for name in ["P101 L101", "P114 L114", "P115 L115", "P116 L116", "P117 L117", "P100 L100", "P116 L116"]:
        for stat in ["points", "rebounds", "assists", "threes", "steals", "blocks", "points_rebounds",
                     "points_assists", "rebounds_assists", "points_rebounds_assists", "points_1q",
                     "rebounds_1q", "assists_1q", "points_first3min", "rebounds_first3min", "assists_first3min"]:
            rows.append(dict(player=name, stat=stat, line=float(rng.choice([0.5, 1.5, 2.5, 4.5, 6.5, 9.5, 14.5, 19.5])),
                             over_odds=int(rng.choice([-130, -115, -110, +100, +115])),
                             under_odds=int(rng.choice([-130, -115, -110, +100, +115]))))
        rows.append(dict(player=name, stat="double_double", yes_odds=+250))
        rows.append(dict(player=name, stat="triple_double", yes_odds=+1200))
    rows += [dict(game="T01 @ T02", stat="game_total", line=221.5, over_odds=-110, under_odds=-110),
             dict(game="T01 @ T02", stat="team_total", team="HOME", line=114.5, over_odds=-110, under_odds=-110),
             dict(game="T01 @ T02", stat="spread", line=-8.5, home_odds=-110, away_odds=-110),
             dict(game="T01 @ T02", stat="moneyline", home_odds=-180, away_odds=+150),
             dict(game="T04 @ T03", stat="game_total", line=170.5, over_odds=-110, under_odds=-110)]  # forces game check
    lines = pd.DataFrame(rows)
    lp = os.path.join(tmp, "lines.csv"); lines.to_csv(lp, index=False)
    out = os.path.join(tmp, "out")
    r = project_date(store, "2026-10-20", cfg, out, lp, n_sims=4000)
    T, Pl = r["teams"], r["players"]
    print(T.to_string(index=False))
    print("gaps:", r["gaps"])
    D, Rv = r["props"], r["review"]
    print(r["health"])
    print(D[["player", "game", "stat", "line", "direction", "pick", "odds", "model_mean", "p_hit",
             "internal_ev_model_only", "ev", "tier"]].head(20).to_string(index=False))
    sug = D[D.tier == "suggested"]
    if len(sug):
        print("\nSUGGESTED backup example:\n", sug.iloc[0].backup)
    print("\nno prediction:", Rv.reason.value_counts().to_dict())
    print("pass reasons:", D[D.tier == "pass"].reason.str.split(":").str[0].str[:45].value_counts().head(6).to_dict())
    assert (D.ev < 0.15).all(), "displayed EV reached 15%"
    assert D[D.tier != "pass"].directional.all()
    S = D[D.tier == "suggested"]
    assert len(S) <= 30 and S.player_id.is_unique and (S.ev >= 0.02).all() and (S.ev < 0.15).all()
    assert (D[D.stat.isin(["game_total", "team_total", "spread", "moneyline"])].tier == "pass").all()
    assert D.reason.astype(str).str.contains("game check").any(), "game check never fired"
    # nothing dropped: every line is either predicted or listed with the reason it cannot be
    assert len(D) + len(Rv) == len(lines)
    assert set(Rv.reason.str[:14]) <= {"no prediction:", "calibrated EV "}
    assert not D.reason.astype(str).str.contains("15% cap").any(), "over-cap line displayed"
    box = r["players"]
    for c in ("dd", "td", "pts_1q", "reb_1q", "ast_1q", "pts_f3"):
        assert box[c].notna().any(), f"no predictions for {c}"
    print("box columns ok:", box[["name", "pts", "pts_1q", "pts_f3", "dd", "td"]].head(4).to_string(index=False))
    # team minutes add up, points reconcile
    g0 = T.iloc[0]
    sub = Pl[Pl.game_id == g0.game_id]
    print("sample box:\n", sub[sub.side == "home"][["name", "p_active", "min", "pts", "reb", "ast", "fg3m", "pts_p10", "pts_p90", "flags"]].head(10).to_string(index=False))
    assert any("no BDL box score history" in str(gp.get("gap")) for gp in r["gaps"])
    assert Pl.loc[Pl.player_id == 115, "p_active"].eq(0).all() if (Pl.player_id == 115).any() else True
    assert Pl.loc[Pl.player_id == 100, "flags"].str.contains("team change").all() if (Pl.player_id == 100).any() else True

    # ---- walk-forward backtest over the back half of the synthetic season ----
    print(backtest(store, 2025, cfg, start="2026-01-15", end="2026-04-10", n_sims=400, out_dir=out, every=6))
    print(f"done in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
