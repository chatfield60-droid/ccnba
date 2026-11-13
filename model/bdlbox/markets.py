"""Pricing every BDL market, calibration from graded results, tiers, and the written backup.

Every offered line gets a row (tier suggested | lean | pass, with the reason it is not higher).
  probability shown = market + w * (model - market) in log-odds, w measured on graded picks
  EV shown is always under 15%
  suggested = today's top N eligible leans by calibrated EV: single-stat market, unders only
              (until refit), every backup check passed, one per player
  team markets (spread, game total, team total) are priced but shown as pass while suspended
Book prices are compared to model output; they never feed the projections (box_<date>.csv).
"""
import numpy as np
import pandas as pd

from .config import ModelConfig
from .project import _logit, _sigmoid, american, implied

# BDL prop_type / Staicy names -> internal stat keys
MARKETS = {
    "points": "pts", "rebounds": "reb", "assists": "ast", "threes": "fg3m", "three_points": "fg3m",
    "steals": "stl", "blocks": "blk", "turnovers": "tov", "blocks_steals": "stocks", "steals_blocks": "stocks",
    "points_rebounds": "pr", "points_assists": "pa", "rebounds_assists": "ra",
    "points_rebounds_assists": "pra", "double_double": "dd", "triple_double": "td",
    "points_1q": "pts_1q", "rebounds_1q": "reb_1q", "assists_1q": "ast_1q",
    "points_first3min": "pts_f3", "rebounds_first3min": "reb_f3", "assists_first3min": "ast_f3",
}
for _k in list(set(MARKETS.values())):
    MARKETS.setdefault(_k, _k)
TEAM_MARKETS = {"game_total": "total", "total": "total", "team_total": "team_total",
                "spread": "spread", "moneyline": "moneyline"}
YES_NO = {"dd", "td"}                                  # milestone: P(yes), usually a single yes price
DERIVED = {"pts_f3", "reb_f3", "ast_f3"}               # model-derived estimates, never suggested
# which opponent factors drive each stat (for the written backup)
DRIVERS = {"pts": ["fg2a", "fg3a", "fta", "pct_fg2", "pct_fg3"], "reb": ["oreb", "dreb"], "ast": ["ast"],
           "fg3m": ["fg3a", "pct_fg3"], "stl": ["stl"], "blk": ["blk"], "tov": ["tov"]}
COMPONENTS = {"pr": ["pts", "reb"], "pa": ["pts", "ast"], "ra": ["reb", "ast"], "pra": ["pts", "reb", "ast"],
              "stocks": ["stl", "blk"], "dd": ["pts", "reb", "ast"], "td": ["pts", "reb", "ast"]}


def _dec(o):
    o = float(o)
    return 1 + (100 / -o if o < 0 else o / 100)


def _display_prob(pm, mo, cfg):
    """Probability shown to users. Starts from the model, pulled toward the no-vig market harder the
    more the two disagree (redescending weight: small gaps keep almost full model weight, huge gaps,
    which are model errors by default, keep little). Side is never flipped. Projections untouched."""
    d = float(_logit(pm) - _logit(mo))
    w0 = cfg.market_blend_w if cfg.market_blend_w is not None else 1.0
    w = w0 / (1 + (d / cfg.display_d0) ** 2)
    return float(_sigmoid(_logit(mo) + w * d))


def _calibrate(pdisp, mo, cfg, kind="player", mkt=None):
    """Graded-results calibration (fit-market): final = market + w * (model - market) in log-odds.
    w is measured on graded picks; it depends on which side the model's edge is on.
    Team markets measured negative (model worse than no model), so their w is 0 until refit."""
    if not cfg.calib_enabled:
        return pdisp
    if kind == "team":
        w = cfg.calib_w["team"]
    elif mkt is not None and mkt in cfg.calib_w_market:
        w = cfg.calib_w_market[mkt]
    else:
        w = cfg.calib_w["player_over"] if pdisp >= mo else cfg.calib_w["player_under"]
    return float(_sigmoid(_logit(mo) + w * (_logit(pdisp) - _logit(mo))))


def _bound_ev(ev, cfg):
    """Calibrated EV shown as-is up to display_knee (14%), then flattened so it never reaches the
    15% cap. Rows whose real calibrated EV is above the cap are marked pass in _classify."""
    knee = cfg.display_knee
    if ev <= knee:
        return ev
    span = cfg.max_ev - knee
    return knee + span * 0.99 * np.tanh((ev - knee) / span)


def _priced(p_side_model, p_side_disp, dec, mkt_p, cfg):
    ev_raw = p_side_model * dec - 1
    ev = _bound_ev(p_side_disp * dec - 1, cfg)
    p_shown = (1 + ev) / dec
    return ev_raw, ev, p_shown


def _two_sided(p_over_raw, p_under_raw, over_odds, under_odds, cfg, kind="player", mkt=None,
               p_book_over=None):
    """Both sides. Pick = the value side, but only if it is also the side the model thinks is more
    likely to hit (directional); otherwise the row is a pass with that reason."""
    tot = p_over_raw + p_under_raw
    pm = p_over_raw / tot if tot else 0.5
    io, iu = implied(over_odds), implied(under_odds)
    # p_book_over is the upstream median no-vig probability across books at this exact line.
    # Odds remain the best available prices used below to calculate EV for either side.
    mo = float(p_book_over) if pd.notna(p_book_over) else io / (io + iu)
    if not 0 < mo < 1:
        raise ValueError(f"p_book_over must be between 0 and 1, got {mo}")
    # calibrated (w measured on the raw model probability) replaces the display shrink when enabled
    pdisp = _calibrate(pm, mo, cfg, kind, mkt) if cfg.calib_enabled else _display_prob(pm, mo, cfg)
    do, du = _dec(over_odds), _dec(under_odds)
    ev_o_raw, ev_o, p_o = _priced(pm, pdisp, do, mo, cfg)
    ev_u_raw, ev_u, p_u = _priced(1 - pm, 1 - pdisp, du, 1 - mo, cfg)
    side_over = ev_o >= ev_u
    likely_over = pm >= 0.5
    raw_cal = (pdisp * do - 1) if side_over_cal(pdisp, mo, do, du) else ((1 - pdisp) * du - 1)
    return dict(ev_calibrated_raw=round(float(raw_cal), 4),
                direction="OVER" if likely_over else "UNDER", p_hit=round(pm if likely_over else 1 - pm, 4),
                pick="OVER" if side_over else "UNDER", directional=side_over == likely_over,
                p_model_nv=round(pm, 4), mkt_nv=round(mo, 4), p_display=round(p_o if side_over else p_u, 4),
                ev=round(ev_o if side_over else ev_u, 4),
                internal_ev_model_only=round(ev_o_raw if side_over else ev_u_raw, 4),
                odds=over_odds if side_over else under_odds,
                fair=american(p_o if side_over else p_u))


def side_over_cal(p, mo, do, du):
    return p * do - 1 >= (1 - p) * du - 1


def _one_sided(p_yes, yes_odds, cfg, mkt=None):
    """Milestone (yes-only price). No devig possible, so the vigged implied is the reference."""
    mo = implied(yes_odds)
    pdisp = _calibrate(p_yes, mo, cfg, mkt=mkt) if cfg.calib_enabled else _display_prob(p_yes, mo, cfg)
    ev_raw, ev, p_shown = _priced(p_yes, pdisp, _dec(yes_odds), mo, cfg)
    return dict(ev_calibrated_raw=round(float(pdisp * _dec(yes_odds) - 1), 4),
                direction="YES" if p_yes >= 0.5 else "NO", p_hit=round(max(p_yes, 1 - p_yes), 4),
                pick="YES", directional=p_yes >= 0.5, p_model_nv=round(p_yes, 4), mkt_nv=round(mo, 4),
                p_display=round(p_shown, 4), ev=round(ev, 4), internal_ev_model_only=round(ev_raw, 4),
                odds=yes_odds, fair=american(p_shown))


# ------------------------------------------------------------------ game check
def game_checks(team_rows: pd.DataFrame, lines: pd.DataFrame, team_hist: pd.Series, cfg: ModelConfig):
    """Per game: model total/margin vs the market's main total/spread, and each team's projected
    points vs its own last-10 average. Market is a check here, never an input."""
    res = {}
    for _, t in team_rows.iterrows():
        why = []
        g = lines[lines.game_id == t.game_id]
        tot = g[g.mkt == "total"]
        if len(tot):
            main = tot.iloc[(tot.over_odds.astype(float).abs() - 110).abs().argsort()].iloc[0] \
                if "over_odds" in tot else tot.iloc[0]
            if abs(t.total - float(main.line)) > cfg.game_total_tol:
                why.append(f"model total {t.total:.1f} vs market {float(main.line):.1f}")
        spr = g[g.mkt == "spread"]
        if len(spr) and "home_odds" in spr:
            main = spr.iloc[(spr.home_odds.astype(float).abs() - 110).abs().argsort()].iloc[0]
            mkt_margin = -float(main.line)        # line = home spread; -5.5 means home favored by 5.5
            if abs(t.home_margin - mkt_margin) > cfg.game_spread_tol:
                why.append(f"model home margin {t.home_margin:+.1f} vs market {mkt_margin:+.1f}")
        for side, tid in (("home", t.home_team_id), ("away", t.away_team_id)):
            hist = team_hist.get(tid)
            proj = t.home_pts if side == "home" else t.away_pts
            if hist is not None and not np.isnan(hist) and abs(proj - hist) > cfg.team_pts_tol:
                why.append(f"{side} proj {proj:.1f} pts vs its L10 {hist:.1f}")
        res[t.game_id] = why
    return res


# ------------------------------------------------------------------ backup
def backup_for(pid, skey, pick, line, ctx, mkt_p=None):
    """Plain-language decomposition of a player projection and the checks for a suggested play."""
    p = ctx["players"].get(pid)
    if p is None:
        return "", ["no player context"]
    comps = COMPONENTS.get(skey, [skey.replace("_1q", "").replace("_f3", "")])
    num = lambda v: float(v) if v is not None and v == v else float("nan")
    proj = num(p["proj"].get(skey))
    l10, sea, prev = num(p["l10"].get(skey)), num(p["season"].get(skey)), num(p["prev"].get(skey))
    p = dict(p, min_l10=num(p["min_l10"]), min_proj=num(p["min_proj"]))
    n_l10 = p["n_l10"]
    lines_txt = []
    if skey in YES_NO:
        lines_txt.append(f"Model {proj:.0%} chance; last {n_l10}: {l10:.0%}" + (f", season {sea:.0%}" if sea == sea else ""))
    else:
        bits = [f"Projection {proj:.1f} vs line {line}"]
        if l10 == l10: bits.append(f"L{n_l10} avg {l10:.1f}")
        if sea == sea: bits.append(f"season {sea:.1f} ({p['gp_season']} gp)")
        elif prev == prev: bits.append(f"last season {prev:.1f}")
        lines_txt.append(", ".join(bits) + ".")
    lines_txt.append(f"Minutes {p['min_proj']:.1f} projected vs {p['min_l10']:.1f} L{n_l10}"
                     + (f"; teammates out: {p['out_txt']}" if p["out_txt"] else "") + ".")
    if p["per36_proj"].get(comps[0]) is not None and p["per36_l10"].get(comps[0]) == p["per36_l10"].get(comps[0]):
        lines_txt.append(f"{comps[0].upper()} per 36: {p['per36_proj'][comps[0]]:.1f} projected vs "
                         f"{p['per36_l10'][comps[0]]:.1f} L{n_l10}" +
                         (f" (team usage x{p['usage']:.2f})" if abs(p["usage"] - 1) > 0.02 else "") + ".")
    lines_txt.append(f"Pace {p['pace_game']:.1f} vs his team's {p['pace_team']:.1f} ({p['pace_game'] / p['pace_team'] - 1:+.1%}).")
    opp = []
    for c in comps:
        for f in DRIVERS.get(c, []):
            v = p["opp"].get(f)
            if v is not None and abs(v - 1) >= 0.02:
                opp.append(f"{f.replace('pct_', '').upper()}{'%' if f.startswith('pct') else ''} x{v:.2f}")
    lines_txt.append(f"Opponent {p['opp_abbr']}: " + (", ".join(dict.fromkeys(opp)) if opp else "neutral") + ".")
    if "reb" in comps and abs(p.get("gng_mult", 1) - 1) >= 0.005:
        lines_txt.append(f"Grab & Go: {p['opp_abbr']} takes {p['gng_rel']:+.0%} threes vs league, "
                         f"rebounds x{p['gng_mult']:.3f}.")
    if p["flags"]:
        lines_txt.append(f"Flags: {p['flags']}.")

    # checks for a suggested play
    fails = []
    want_over = pick in ("OVER", "YES")
    ref = (mkt_p if mkt_p is not None else 0.5) if skey in YES_NO else line
    agree = [(v > ref) if want_over else (v < ref)
             for v in (l10, sea if sea == sea else prev) if v is not None and v == v]
    if not any(agree):
        fails.append("neither L10 nor season average agrees with the side")
    gap = p["min_proj"] - p["min_l10"]
    if p["min_l10"] == p["min_l10"] and abs(gap) > ctx["cfg"].sug_min_gap:
        if not (gap > 0 and p["out_min"] >= ctx["cfg"].sug_out_min_explains):
            fails.append(f"minutes {p['min_proj']:.1f} vs L10 {p['min_l10']:.1f} not explained by absences")
    if not (p["gp_season"] >= ctx["cfg"].sug_min_games_season or
            (p["gp_total"] >= ctx["cfg"].sug_min_games_total and "team change" not in p["flags"])):
        fails.append(f"thin sample ({p['gp_season']} gp this season)")
    if p["flags"]:
        fails.append("player flagged")
    if p["injury_status"]:
        fails.append(f"own status {p['injury_status']}")
    if skey in DERIVED:
        fails.append("derived market (first 3 minutes)")
    return " ".join(lines_txt), fails


# ------------------------------------------------------------------ slate pricing
def price_slate(sims, team_sims, ctx, lines: pd.DataFrame, cfg: ModelConfig):
    lines = lines.copy()
    lines["mkt"] = lines["stat"].map(lambda s: TEAM_MARKETS.get(str(s).lower(), MARKETS.get(str(s).lower())))
    if "game_id" not in lines:
        lines["game_id"] = np.nan
    if "game" in lines:
        miss = lines.game_id.isna()
        if miss.any():
            lines["game_id"] = lines["game_id"].astype(object)
            lines.loc[miss, "game_id"] = lines.loc[miss, "game"].map(
                lambda g: ctx["game_lookup"].get(str(g).strip().lower(), np.nan))
    game_bad = game_checks(ctx["teams"], lines, ctx["team_l10"], cfg)
    rows = []
    for _, L in lines.iterrows():
        base = L.to_dict()
        mkt = L.mkt
        if mkt is None:
            rows.append(dict(base, tier=None, reason="no prediction: " + f"unknown market '{L.stat}'")); continue
        if mkt in ("total", "team_total", "spread", "moneyline"):
            rows.append(_price_team(L, base, team_sims, ctx, cfg, game_bad)); continue
        key = L.get("player_id") if "player_id" in L and pd.notna(L.get("player_id")) else str(L.get("player", "")).strip().lower()
        hit = sims.get(key)
        if hit is None:
            rows.append(dict(base, tier=None, reason="no prediction: " + "player not in projected rosters")); continue
        draws, played, pid, gid = hit
        x = draws[mkt][played]
        if len(x) == 0:
            rows.append(dict(base, tier=None, reason="no prediction: " + "projected inactive")); continue
        if x[0] < 0:
            rows.append(dict(base, tier=None, reason="no prediction: " + "no first-quarter data: run sync --q1")); continue
        if mkt in YES_NO:
            yes = L.get("yes_odds", L.get("over_odds"))
            if pd.isna(yes):
                rows.append(dict(base, tier=None, reason="no prediction: " + "no price")); continue
            r = _one_sided(float(x.mean()), float(yes), cfg, mkt=mkt)
            if pd.notna(L.get("under_odds")) and "yes_odds" not in L:
                r = _two_sided(float(x.mean()), 1 - float(x.mean()), float(yes), float(L.under_odds), cfg)
                r["pick"] = "YES" if r["pick"] == "OVER" else "NO"
                r["direction"] = "YES" if r["direction"] == "OVER" else "NO"
            line = 0.5
        else:
            line = float(L.line)
            if pd.isna(L.get("over_odds")) or pd.isna(L.get("under_odds")):
                yes = L.get("yes_odds")
                if pd.isna(yes):
                    rows.append(dict(base, tier=None, reason="no prediction: " + "need both sides or a yes price")); continue
                r = _one_sided(float((x >= line).mean()), float(yes), cfg, mkt=mkt)
            else:
                r = _two_sided(float((x > line).mean()), float((x < line).mean()), float(L.over_odds), float(L.under_odds), cfg,
                               mkt=mkt, p_book_over=L.get("p_book_over"))
        if r.get("pick") in ("OVER", "YES"):
            r["book"] = L.get("over_book") if pd.notna(L.get("over_book")) else L.get("book")
        elif r.get("pick") in ("UNDER", "NO"):
            r["book"] = L.get("under_book") if pd.notna(L.get("under_book")) else L.get("book")
        r.update(model_mean=round(float(x.mean()), 3), game_id=gid, player_id=pid)
        text, fails = backup_for(pid, mkt, r["pick"], line, ctx, r["mkt_nv"])
        rows.append(_classify(dict(base, **r), text, fails, game_bad.get(gid, []), cfg))
    out = pd.DataFrame(rows)
    if len(out) and "suggest_ok" in out:
        cand = out[out.suggest_ok.fillna(False).astype(bool)].sort_values("ev", ascending=False)
        cand = cand.drop_duplicates("player_id")          # one suggested play per player
        top = cand.head(cfg.suggested_max_per_day).index
        out.loc[top, "tier"] = "suggested"
        out.loc[top, "reason"] = ""
        out.loc[top, "backup"] = out.loc[top, "backup"] + (
            " Checks passed: recent and season averages agree with the side; projected minutes consistent "
            "with recent role (or explained by absences); sample size; no player flags; game total/margin "
            "within tolerance of market. Calibrated EV in the 10-15% band.")
        rest = out.suggest_ok.fillna(False).astype(bool) & ~out.index.isin(top)
        out.loc[rest, "reason"] = f"eligible, outside today's top {cfg.suggested_max_per_day}"
    tier = out["tier"] if "tier" in out else pd.Series(None, index=out.index)
    has = tier.isin(["suggested", "lean", "pass"])
    order = {"suggested": 0, "lean": 1, "pass": 2}
    shown = out[has].assign(_o=lambda x: x.tier.map(order)).sort_values(["_o", "ev"], ascending=[True, False]).drop(columns="_o")
    return shown, out[~has]          # not shown: no prediction possible, or over the 15% cap (tier over_cap)


def _classify(r, text, fails, game_fail, cfg):
    """Every row is kept. tier: lean | pass here; the daily suggested list is picked afterwards in
    price_slate from eligible leans (suggest_ok), ranked by calibrated EV."""
    r["backup"] = text
    ev, odds = r["ev"], float(r["odds"])
    why_not = []
    team = r.get("mkt") in ("total", "team_total", "spread", "moneyline")
    if team and not cfg.team_markets_live:
        why_not.append("team markets suspended: graded results showed the model worse than the market")
    if game_fail:
        why_not.append("game check: " + "; ".join(game_fail))
    if (odds < 0 and -odds > cfg.max_odds_abs) or (odds > 0 and odds > cfg.max_odds_abs):
        why_not.append(f"price {odds:+.0f} outside +/-{cfg.max_odds_abs:.0f}")
    if not r.get("directional", True):
        why_not.append(f"value is on {r['pick']} but model leans {r['direction']}")
    if r.get("ev_calibrated_raw", 0) >= cfg.max_ev:
        # never displayed anywhere: routed to the internal over_cap file by price_slate
        return dict(r, tier="over_cap", suggest_ok=False,
                    reason=f"calibrated EV {r['ev_calibrated_raw']:.1%} at or above the 15% cap: treated as model error")
    if ev <= max(cfg.min_ev_publish, 0):
        return dict(r, tier="pass", suggest_ok=False, reason="; ".join(why_not + ["no edge after calibration"]))
    if why_not:
        return dict(r, tier="pass", suggest_ok=False, reason="; ".join(why_not))
    elig = list(fails)
    pm_side = r["p_model_nv"] if r["pick"] in ("OVER", "YES", "HOME") else 1 - r["p_model_nv"]
    mk_side = r["mkt_nv"] if r["pick"] in ("OVER", "YES", "HOME") else 1 - r["mkt_nv"]
    ratio = max(pm_side / max(mk_side, 1e-6), (1 - pm_side) / max(1 - mk_side, 1e-6),
                mk_side / max(pm_side, 1e-6), (1 - mk_side) / max(1 - pm_side, 1e-6))
    if ratio >= 2:
        elig.append("model vs book 2x+ apart in implied probability: model flaw until explained")
    if team and not cfg.suggest_team_markets:
        elig.append("team market: priced at the book until a team-level model earns weight")
    elif not team and r.get("mkt") not in cfg.suggested_markets:
        elig.append("market not in suggested set")
    if r.get("pick") == "OVER" and not cfg.suggest_overs:
        elig.append("overs not suggested: graded overs showed no model signal")
    if ev < cfg.suggested_min_ev:
        elig.append(f"calibrated EV under {cfg.suggested_min_ev:.0%} (suggested band is {cfg.suggested_min_ev:.0%}-{cfg.max_ev:.0%})")
    note = "derived estimate (first 3 minutes)" if r.get("mkt") in DERIVED else ""
    return dict(r, tier="lean", suggest_ok=not elig,
                reason="; ".join([x for x in [note, ("not suggested: " + "; ".join(elig)) if elig else ""] if x]))


def _price_team(L, base, team_sims, ctx, cfg, game_bad):
    gid = L.get("game_id")
    if pd.isna(gid):
        gid = ctx["game_lookup"].get(str(L.get("game", "")).strip().lower())
    ts = team_sims.get(gid) if gid is not None else None
    if ts is None:
        return dict(base, tier=None, reason="no prediction: " + "game not projected")
    h, a = ts["home"], ts["away"]
    mkt = L.mkt
    if mkt in ("total", "team_total"):
        if mkt == "total":
            x = h + a
        else:
            tm = str(L.get("team", "")).strip().lower()
            x = h if tm in ("home", ts["home_abbr"].lower(), ts["home_name"].lower()) else (
                a if tm in ("away", ts["away_abbr"].lower(), ts["away_name"].lower()) else None)
            if x is None:
                return dict(base, tier=None, reason="no prediction: " + "team_total needs team = HOME/AWAY or team name")
        line = float(L.line)
        r = _two_sided(float((x > line).mean()), float((x < line).mean()), float(L.over_odds), float(L.under_odds), cfg, "team")
        r["model_mean"] = round(float(x.mean()), 2)
    else:
        if pd.isna(L.get("home_odds")) or pd.isna(L.get("away_odds")):
            return dict(base, tier=None, reason="no prediction: " + "need home_odds and away_odds")
        m = h - a
        if mkt == "spread":
            line = float(L.line)                       # home spread
            ph, pa = float((m + line > 0).mean()), float((m + line < 0).mean())
        else:
            ph, pa = float((m > 0).mean()) + 0.5 * float((m == 0).mean()), float((m < 0).mean()) + 0.5 * float((m == 0).mean())
        r = _two_sided(ph, pa, float(L.home_odds), float(L.away_odds), cfg, "team")
        r["pick"] = "HOME" if r["pick"] == "OVER" else "AWAY"
        r["direction"] = "HOME" if r["direction"] == "OVER" else "AWAY"
        r["model_mean"] = round(float(m.mean()), 2)
    t = ctx["teams"].set_index("game_id").loc[gid]
    text = (f"Model {t.away} {t.away_pts:.1f} @ {t.home} {t.home_pts:.1f} (total {t.total:.1f}, home margin "
            f"{t.home_margin:+.1f}), pace {t.proj_pace:.1f}. Last 10: {t.away} {ctx['team_l10'].get(t.away_team_id, np.nan):.1f}, "
            f"{t.home} {ctx['team_l10'].get(t.home_team_id, np.nan):.1f} pts.")
    fails = []
    if mkt in ("total", "team_total"):
        l10 = ctx["team_l10"].get(t.home_team_id, np.nan) + ctx["team_l10"].get(t.away_team_id, np.nan) \
            if mkt == "total" else np.nan
        if l10 == l10 and not ((l10 > float(L.line)) == (r["pick"] == "OVER")):
            fails.append("teams' last-10 scoring disagrees with the side")
    r.update(game_id=gid)
    return _classify(dict(base, **r), text, fails, game_bad.get(gid, []), cfg)


def slate_health(shown: pd.DataFrame, missing: pd.DataFrame, cfg: ModelConfig):
    n = len(shown)
    tiers = shown.tier.value_counts().to_dict() if n else {}
    assert n == 0 or shown.ev.max() < cfg.max_ev, "a displayed EV reached the cap"
    assert n == 0 or not (shown.get("ev_calibrated_raw", pd.Series(dtype=float)) >= cfg.max_ev).any(), "an over-cap line reached predictions"
    assert n == 0 or shown[shown.tier != "pass"].directional.all(), "a lean/suggested pick against model direction"
    ev10 = (shown.ev > cfg.warn_ev).mean() if n else 0
    leans = shown[shown.tier.isin(["lean", "suggested"])] if n else shown
    unders = leans.pick.isin(["UNDER", "NO", "AWAY"]).mean() if len(leans) else float("nan")
    over = int((missing.get("tier", pd.Series(dtype=object)) == "over_cap").sum()) if len(missing) else 0
    return (f"predictions: {n} lines ({tiers.get('suggested', 0)} suggested, {tiers.get('lean', 0)} lean, "
            f"{tiers.get('pass', 0)} pass) | removed over 15% cap: {over} | no prediction possible: {len(missing) - over} | max shown EV "
            f"{(shown.ev.max() if n else 0):.1%} | >10%: {ev10:.1%} | unders among leans {unders:.0%}")
