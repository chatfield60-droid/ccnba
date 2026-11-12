"""CLI: python -m bdlbox {sync,project,backtest} ..."""
import argparse
import logging
from datetime import date

import numpy as np
import pandas as pd

from .client import BDLClient
from .config import ModelConfig, Settings
from .pipeline import backtest, calibrate, fit_market, project_date, sync, train_minutes
from .store import Store


def _scorecard_hook(store, cfg, prep, season, cutoff, morning=True):
    """Minutes model inside the replay. Trained only on games before `cutoff` (the first graded
    date), so the scorecard never sees the future. Actual starters stand in for the confirmed lineup."""
    from . import extra
    from .minutes import build_frame, MinutesModel
    F = build_frame(store.df("SELECT * FROM player_stats"), store.df("SELECT * FROM games"), extra.load(store, "starters"))
    mm = MinutesModel().fit(F[F.date < cutoff])
    F = F[(F.season == season) & F.m_l1.notna()].copy()
    if morning:   # live runs are morning-only: tonight's starter unknown unless BDL posted an expected lineup
        F["starter"] = np.nan
        F["start_change"] = np.nan
    F["mu"], F["sd"] = mm.predict(F)
    F["ds"] = F.date.dt.strftime("%Y-%m-%d")
    def hook(state, ds):
        t = F[F.ds == ds].set_index("player_id"); idx = state.players.index.intersection(t.index)
        state.players.loc[idx, "min_mu"] = t.loc[idx, "mu"].values
        state.players.loc[idx, "min_sd"] = t.loc[idx, "sd"].values
        return state
    return hook


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bdlbox", description="NBA box score model on BALLDONTLIE data")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="pull teams, games, box scores, active players, injuries")
    s.add_argument("--seasons", nargs="+", type=int, required=True, help="BDL season = start year, e.g. 2025 2026")
    s.add_argument("--full", action="store_true", help="refetch all stats instead of incremental")
    s.add_argument("--q1", action="store_true", help="also pull first-quarter box scores (needed for 1Q/first-3-min props)")
    s.add_argument("--goat", action="store_true", help="GOAT: starters history, quarter scores, projected lineups for --date")
    s.add_argument("--date", default=None, help="with --goat: pull projected lineups for this date's games")
    tm = sub.add_parser("train-minutes", help="train the minutes model on everything synced (weekly)")
    sc = sub.add_parser("scorecard", help="replay the model on graded lines exported from the results admin")
    sc.add_argument("--lines", required=True)
    sc.add_argument("--season", type=int, default=2026)
    sc.add_argument("--sims", type=int, default=1000)
    sc.add_argument("--confirmed", action="store_true", help="score with actual starters (as if run after lineups confirm)")
    p = sub.add_parser("project", help="project every game on a date")
    p.add_argument("--date", default=date.today().isoformat())
    p.add_argument("--sims", type=int, default=None)
    p.add_argument("--lines", help="optional CSV: player,stat,line[,over_odds,under_odds]")
    p.add_argument("--out", default="out")
    b = sub.add_parser("backtest", help="walk-forward backtest over a completed season")
    b.add_argument("--season", type=int, required=True)
    b.add_argument("--start"); b.add_argument("--end")
    b.add_argument("--sims", type=int, default=1000)
    b.add_argument("--every", type=int, default=1, help="use every Nth date (speed)")
    b.add_argument("--out", default="out")
    k = sub.add_parser("calibrate", help="grid shrinkage x reconciliation on a real backtest (compression fix)")
    k.add_argument("--season", type=int, required=True)
    k.add_argument("--start"); k.add_argument("--end")
    k.add_argument("--sims", type=int, default=400)
    k.add_argument("--every", type=int, default=4)
    k.add_argument("--out", default="out")
    f = sub.add_parser("fit-market", help="measure model weight vs market on historical prop prices")
    f.add_argument("--season", type=int, required=True)
    f.add_argument("--lines", required=True, help="CSV: date,player_id|player,stat,line,over_odds,under_odds[,book]")
    f.add_argument("--sims", type=int, default=2000)
    f.add_argument("--out", default="out")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings, cfg = Settings(), ModelConfig()
    store = Store(settings.db_path)
    if a.cmd == "sync":
        client = BDLClient(settings)
        print(sync(client, store, a.seasons, full=a.full, q1=a.q1))
        if a.goat:
            from . import extra
            g = store.df("SELECT game_id, date, status FROM games WHERE season = ?", (max(a.seasons),))
            done = store.df("SELECT DISTINCT game_id FROM starters") if "starters" in str(
                store.con.execute("SELECT name FROM sqlite_master").fetchall()) else pd.DataFrame(columns=["game_id"])
            fin = [x for x in g[g.status.astype(str).str.contains("Final")].game_id if x not in set(done.game_id)]
            print("starters", extra.sync_starters(client, store, fin))
            print("quarter scores", extra.sync_game_periods(client, store, [max(a.seasons)]))
            if a.date:
                print("projected lineups", extra.sync_projected(client, store, list(g[g.date == a.date].game_id)))
    elif a.cmd == "project":
        r = project_date(store, a.date, cfg, a.out, a.lines, a.sims)
        with pd.option_context("display.width", 200, "display.max_columns", 20):
            print(r["teams"].to_string(index=False))
        if "health" in r:
            print(r["health"])
        print(f"\n{len(r['players'])} player lines -> {a.out}/box_{a.date}.csv; {len(r['gaps'])} gap notes -> {a.out}/gaps_{a.date}.json")
    elif a.cmd == "train-minutes":
        print(train_minutes(store, cfg))
    elif a.cmd == "scorecard":
        import pickle, os
        from .pipeline import load_prep
        from .replay import load_lines, replay, score, score_by
        from .pipeline import _load_minutes_model
        prep = load_prep(store)
        L = load_lines(a.lines, prep)
        import dataclasses
        cfg = dataclasses.replace(cfg, min_unc_base=0.0, min_unc_new=0.0)
        hook = _scorecard_hook(store, cfg, prep, a.season, L.gdate.min(), morning=not a.confirmed)
        df = replay(store, prep, L, cfg, a.sims, a.season, state_hook=hook)
        os.makedirs("out", exist_ok=True); df.to_csv("out/scorecard_rows.csv", index=False)
        print("ALL", score(df)); print(score_by(df, "stat").to_string())
    elif a.cmd == "fit-market":
        txt, _ = fit_market(store, a.season, a.lines, cfg, a.sims, a.out)
        print(txt)
    elif a.cmd == "calibrate":
        df = calibrate(store, a.season, cfg, a.start, a.end, a.sims, a.every, out_dir=a.out)
        with pd.option_context("display.width", 200, "display.max_columns", 30):
            print(df.to_string(index=False))
        print(f"\nBest row first. Set k_poss multiplier and recon_alpha in bdlbox/config.py; table -> {a.out}/calibration_{a.season}.csv")
    else:
        print(backtest(store, a.season, cfg, a.start, a.end, a.sims, a.out, a.every))


if __name__ == "__main__":
    main()
