"""Roster building + Monte Carlo box score simulation."""
import numpy as np
import pandas as pd

from .config import COUNT_STATS, ModelConfig
from .features import ModelState

VOLUME = {"fg2a", "fg3a", "fta", "ast", "oreb", "dreb", "tov"}


def build_roster(state: ModelState, team_id, as_of, cfg: ModelConfig,
                 active: pd.DataFrame = None, injuries: pd.DataFrame = None):
    """Returns (roster_df[player_id, avail, injury_status, flags], gaps list)."""
    gaps = []
    P = state.players
    as_of = pd.Timestamp(as_of)
    if active is not None and len(active):
        ids = active.loc[active.team_id == team_id, "player_id"].tolist()
        names = active.set_index("player_id")
        for pid in ids:
            if pid not in P.index:
                n = names.loc[pid]
                gaps.append(dict(team_id=team_id, player_id=pid, name=f"{n.first_name} {n.last_name}",
                                 gap="no BDL box score history (rookie/new); not projected"))
        ids = [i for i in ids if i in P.index]
    else:
        fresh = P[(P.last_team_id == team_id) &
                  (P.last_date >= as_of - pd.Timedelta(days=cfg.roster_staleness_days))]
        ids = fresh.index.tolist()
        gaps.append(dict(team_id=team_id, gap="roster inferred from last team in box scores "
                         "(no /players/active data); offseason moves not reflected"))

    rows = []
    inj = injuries.set_index("player_id") if injuries is not None and len(injuries) else None
    for pid in ids:
        p = P.loc[pid]
        status, avail, flags = "", 1.0, []
        if inj is not None and pid in inj.index:
            r = inj.loc[pid]
            r = r.iloc[0] if isinstance(r, pd.DataFrame) else r
            status = str(r.status or "")
            key = status.strip().lower()
            if key in cfg.avail_by_status:
                avail = cfg.avail_by_status[key]
            else:
                avail = 0.5
                flags.append(f"unmapped injury status '{status}' -> 0.5")
        if p.last_team_id != team_id:
            flags.append("team change: rates carried over, minutes from old role")
        if (as_of - p.last_date).days > 300:
            flags.append(f"no game since {p.last_date.date()}")
        if p.min_mu < cfg.min_minutes_to_roster or avail == 0:
            if avail == 0:
                rows.append(dict(player_id=pid, avail=0.0, injury_status=status, flags="; ".join(flags)))
            continue
        rows.append(dict(player_id=pid, avail=avail, injury_status=status, flags="; ".join(flags)))
    return pd.DataFrame(rows, columns=["player_id", "avail", "injury_status", "flags"]), gaps


def _normalize_minutes(m, total, cap):
    n_active = (m > 0).sum(1, keepdims=True).clip(min=1)
    cap = np.maximum(cap, total / n_active)  # short-handed: allow up to 48
    cap = np.minimum(cap, 48.0)
    for _ in range(10):
        capped = m >= cap - 1e-9
        cap_sum = np.where(capped, cap, 0).sum(1, keepdims=True)
        free_sum = np.where(capped, 0, m).sum(1, keepdims=True)
        scale = np.where(free_sum > 0, (total - cap_sum) / np.maximum(free_sum, 1e-9), 1.0)
        m = np.where(capped, cap, m * scale)
        m = np.minimum(m, cap)
    return m


def _rotation_keep(mu, avail, total):
    """Per draw: if the AVAILABLE players' expected minutes overflow the team total (a 15-18 man
    active list), the overflow comes off the end of the bench first (lowest projected minutes),
    the way coaches shorten a rotation, instead of shrinking starters evenly. Uses expected
    minutes, not noisy draws, so game-to-game noise is still rescaled symmetrically afterwards.
    Returns keep fraction in [0, 1] per draw/player (0 = out of the rotation tonight)."""
    order = np.argsort(mu, kind="stable")              # lowest priority first
    em = (mu[None, :] * avail)[:, order]
    excess = np.maximum(em.sum(1, keepdims=True) - total, 0)
    before = np.cumsum(em, axis=1) - em
    cut = np.clip(excess - before, 0, em)
    with np.errstate(divide="ignore", invalid="ignore"):
        keep_o = np.where(em > 0, 1 - cut / em, 1.0)
    keep = np.empty_like(keep_o)
    keep[:, order] = keep_o
    return keep


def _role_uncertainty(P, cfg, team):
    """Per-player lognormal sd for 'our mean is wrong' (role, sample size, team change)."""
    gp = P.gp_season.to_numpy()
    moved = (P.last_team_id.to_numpy() != team)
    s_rate = cfg.rate_unc_base + cfg.rate_unc_new * np.exp(-gp / cfg.unc_games) + cfg.unc_team_change * moved
    s_min = cfg.min_unc_base + cfg.min_unc_new * np.exp(-gp / cfg.unc_games) + cfg.unc_team_change * moved
    return s_rate, s_min


def grab_and_go_rel(state, opp):
    """Opponent's three-point attempt rate vs league (per possession, env-adjusted team rates)."""
    tr = state.team_rate
    if opp not in tr.index:
        return 0.0
    return float(np.clip(tr.loc[opp, "fg3a"] / tr["fg3a"].mean() - 1, -0.25, 0.25))


def _grab_and_go(state, opp, P, cfg):
    """Grab & Go: more opponent threes -> more long rebounds. Rebound multiplier by position group,
    slopes measured on BDL 2023-24..2025-26 (rebounds per 10% more opponent 3PA: wings/forwards
    +2.0% +/-0.6%, guards +1.3%, centers +1.1%). The old interior boost was not supported by the data."""
    rel = grab_and_go_rel(state, opp)
    slope = P["pos"].map(cfg.grab_and_go_slope).fillna(0).to_numpy()
    return 1 + slope * rel


def _sim_side(state, roster, team, opp, is_home, pace, cfg, rng):
    n = len(pace)
    P = state.players.loc[roster.player_id.to_numpy()]
    p = len(P)
    mu, sd, av = P.min_mu.to_numpy(), P.min_sd.to_numpy(), roster.avail.to_numpy()
    s_rate, s_min = _role_uncertainty(P, cfg, team)
    mu_draw = mu * rng.lognormal(-s_min ** 2 / 2, s_min, (n, p))
    avail = rng.random((n, p)) < av
    keep = _rotation_keep(mu, avail, state.team_minutes) if cfg.rotation_cut else np.ones((n, p))
    m = np.clip((mu_draw + sd * rng.standard_normal((n, p))) * keep, 0.5, 48) * avail * (keep > 0.05)
    m = _normalize_minutes(m, state.team_minutes, cfg.max_minutes)
    game_min = state.team_minutes / 5.0
    team_poss = pace * game_min / 48.0
    on = team_poss[:, None] * m / game_min
    form = rng.gamma(cfg.form_shape, 1.0 / cfg.form_shape, (n, p))
    role = rng.lognormal(-s_rate ** 2 / 2, s_rate, (n, p))  # shared across all of a player's stats

    dfac = state.def_factor.loc[opp] if opp in state.def_factor.index else pd.Series(1.0, index=COUNT_STATS)
    trate = state.team_rate.loc[team] if team in state.team_rate.index else None
    out = {"min": m}
    info = {"usage_scale": {}}
    for s in COUNT_STATS:
        lam = P[f"r_{s}"].to_numpy() * on * dfac[s] * role
        if s in ("oreb", "dreb") and cfg.grab_and_go:
            lam = lam * _grab_and_go(state, opp, P, cfg)[None, :]
        if s in VOLUME:
            lam = lam * form
        if s in cfg.recon_stats and trate is not None:
            target = trate[s] * dfac[s] * team_poss
            tot = lam.sum(1)
            scale = np.where(tot > 0, target / np.maximum(tot, 1e-9), 1.0)
            lam = lam * scale[:, None] ** cfg.recon_alpha
            info["usage_scale"][s] = float(np.mean(scale ** cfg.recon_alpha))
        out[s] = rng.poisson(np.maximum(lam, 0))

    dp = state.def_pct.loc[opp] if opp in state.def_pct.index else pd.Series({"fg2": 1.0, "fg3": 1.0})
    hm = state.home_mult if is_home else 1.0 / state.home_mult
    p2 = np.clip(P.pct_fg2.to_numpy() * dp["fg2"] * hm, 0.05, 0.95)
    p3 = np.clip(P.pct_fg3.to_numpy() * dp["fg3"] * hm, 0.01, 0.80)
    pf = np.clip(P.pct_ft.to_numpy(), 0.2, 0.99)
    out["fg2m"] = rng.binomial(out["fg2a"], p2)
    out["fg3m"] = rng.binomial(out["fg3a"], p3)
    out["ftm"] = rng.binomial(out["fta"], pf)
    out["fgm"] = out["fg2m"] + out["fg3m"]
    out["fga"] = out["fg2a"] + out["fg3a"]
    out["pts"] = 2 * out["fg2m"] + 3 * out["fg3m"] + out["ftm"]
    out["reb"] = out["oreb"] + out["dreb"]
    out["pra"] = out["pts"] + out["reb"] + out["ast"]
    out["pr"] = out["pts"] + out["reb"]
    out["pa"] = out["pts"] + out["ast"]
    out["ra"] = out["reb"] + out["ast"]
    out["stocks"] = out["stl"] + out["blk"]
    tens = sum((out[k] >= 10).astype(int) for k in ("pts", "reb", "ast", "stl", "blk"))
    out["dd"], out["td"] = (tens >= 2).astype(int), (tens >= 3).astype(int)
    # first quarter: thin full-game draws by the player's BDL first-quarter share (needs sync --q1)
    has_q1 = "q1_share_pts" in P.columns
    for s in ("pts", "reb", "ast"):
        if has_q1:
            sh = P[f"q1_share_{s}"].to_numpy(dtype=float)
            ok = ~np.isnan(sh)
            x1 = rng.binomial(out[s], np.clip(np.nan_to_num(sh), 0, 1))
            out[f"{s}_1q"] = np.where(ok, x1, -1)        # -1 = no first-quarter data for this player
            # first 3 minutes (derived, never a suggested play): 3/q1_min of the 1Q output, times the
            # chance he is on the floor at tip (proxied by 1Q minutes: ~9+ = starter, ~3 or less = bench)
            q1m = P["q1_min"].to_numpy(dtype=float)
            start_p = np.clip((np.nan_to_num(q1m) - 3) / 6, 0, 1)
            f3 = np.clip(3 / np.maximum(np.nan_to_num(q1m, nan=12), 3), 0, 1) * start_p
            x3 = rng.binomial(np.maximum(x1, 0), f3)
            out[f"{s}_f3"] = np.where(ok & ~np.isnan(q1m), x3, -1)
        else:
            out[f"{s}_1q"] = np.full_like(out[s], -1)
            out[f"{s}_f3"] = np.full_like(out[s], -1)
    info["team_pts"] = out["pts"].sum(1)
    return P, out, info


def simulate_game(state: ModelState, home_id, away_id, home_roster, away_roster, cfg: ModelConfig,
                  n_sims=None, seed=None):
    rng = np.random.default_rng(seed)
    n = n_sims or cfg.n_sims
    ph = state.pace.get(home_id, state.lg_pace)
    pa = state.pace.get(away_id, state.lg_pace)
    mu_pace = ph * pa / state.lg_pace
    pace = np.clip(mu_pace + cfg.pace_sd * rng.standard_normal(n), mu_pace - 15, mu_pace + 15)
    Ph, H, ih = _sim_side(state, home_roster, home_id, away_id, True, pace, cfg, rng)
    Pa, A, ia = _sim_side(state, away_roster, away_id, home_id, False, pace, cfg, rng)
    return dict(pace=pace, mu_pace=mu_pace, home=(Ph, H, home_roster), away=(Pa, A, away_roster),
                info_home=ih, info_away=ia)


STATS_OUT = ["min", "pts", "reb", "ast", "fg3m", "fg3a", "fgm", "fga", "ftm", "fta", "oreb", "dreb",
             "stl", "blk", "tov", "pf", "pra", "pr", "pa", "ra", "stocks", "dd", "td",
             "pts_1q", "reb_1q", "ast_1q", "pts_f3", "reb_f3", "ast_f3"]


def summarize(sim, game_meta):
    """Player rows (stats conditional on playing, as props settle) + team row."""
    rows = []
    team_pts = {}
    for side in ("home", "away"):
        P, D, R = sim[side]
        team_pts[side] = D["pts"].sum(1)
        played = D["min"] > 0
        for j, pid in enumerate(P.index):
            msk = played[:, j]
            r = dict(game_id=game_meta["game_id"], date=game_meta["date"], side=side,
                     team_id=game_meta[f"{side}_team_id"], player_id=pid, name=P.name.iloc[j],
                     pos=P.pos.iloc[j], p_active=round(float(msk.mean()), 3),
                     injury_status=R["injury_status"].iloc[j], flags=R["flags"].iloc[j])
            for s in STATS_OUT:
                x = D[s][msk, j] if msk.any() else np.zeros(1)
                if len(x) and x[0] < 0:          # no first-quarter data for this player
                    r[f"{s}"], r[f"{s}_sd"] = np.nan, np.nan
                    continue
                r[f"{s}"] = round(float(x.mean()), 3 if s in ("dd", "td") else 2)  # dd/td = probability
                r[f"{s}_sd"] = round(float(x.std()), 2)  # full spread incl. role uncertainty; price from this, not Poisson(mean)
                if s in ("pts", "reb", "ast", "fg3m", "pra", "min"):
                    r[f"{s}_p10"], r[f"{s}_p50"], r[f"{s}_p90"] = (float(v) for v in np.percentile(x, [10, 50, 90]))
            rows.append(r)
    h, a = team_pts["home"], team_pts["away"]
    margin = h - a
    team = dict(game_id=game_meta["game_id"], date=game_meta["date"],
                home_team_id=game_meta["home_team_id"], away_team_id=game_meta["away_team_id"],
                home=game_meta.get("home_abbr"), away=game_meta.get("away_abbr"),
                proj_pace=round(float(sim["mu_pace"]), 1),
                home_pts=round(float(h.mean()), 1), away_pts=round(float(a.mean()), 1),
                total=round(float((h + a).mean()), 1), total_sd=round(float((h + a).std()), 1),
                home_margin=round(float(margin.mean()), 1), margin_sd=round(float(margin.std()), 1),
                home_win_prob=round(float((margin > 0).mean() + 0.5 * (margin == 0).mean()), 3))
    return rows, team, {"home": h, "away": a}


def american(p):
    if p <= 0 or p >= 1:
        return None
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def implied(odds):
    odds = float(odds)
    return -odds / (-odds + 100) if odds < 0 else 100 / (odds + 100)


STAT_ALIASES = {"points": "pts", "rebounds": "reb", "assists": "ast", "three_points": "fg3m",
                "threes": "fg3m", "points_rebounds_assists": "pra", "points_rebounds": "pr",
                "points_assists": "pa", "rebounds_assists": "ra", "steals": "stl", "blocks": "blk",
                "turnovers": "tov", "steals_blocks": "stocks"}


def stat_key(s):
    s = str(s).strip().lower()
    return STAT_ALIASES.get(s, s)


def _logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def _sigmoid(z):
    return 1 / (1 + np.exp(-z))


def price_lines(sims_by_player, lines: pd.DataFrame, max_ev=0.15, warn_ev=0.10, min_ev=0.0, blend_w=None):
    """lines columns: player (name) or player_id, stat, line, [over_odds, under_odds].
    Projections never see book prices.
    Option A (blend_w None): EV from the model alone; publish only if EV > min_ev.
    Option B (blend_w set): final P(over) = sigmoid(w*logit(model) + (1-w)*logit(no-vig market)),
    w measured by `fit-market`. Raw model probability is kept in p_over_model_nv either way."""
    out = []
    for _, L in lines.iterrows():
        key = L.get("player_id") if "player_id" in L and pd.notna(L.get("player_id")) else str(L["player"]).lower()
        hit = sims_by_player.get(key)
        if hit is None:
            out.append(dict(**L.to_dict(), note="player not in projected rosters"))
            continue
        draws, played = hit
        x = draws[stat_key(L["stat"])][played]
        if len(x) == 0:
            out.append(dict(**L.to_dict(), note="projected inactive"))
            continue
        line = float(L["line"])
        po, pu = float((x > line).mean()), float((x < line).mean())
        r = dict(**L.to_dict(), model_mean=round(float(x.mean()), 2), p_over=round(po, 3),
                 p_under=round(pu, 3), p_push=round(1 - po - pu, 3),
                 fair_over=american(po / (po + pu)) if po + pu > 0 else None,
                 fair_under=american(pu / (po + pu)) if po + pu > 0 else None)
        if "over_odds" in L and pd.notna(L.get("over_odds")) and "under_odds" in L and pd.notna(L.get("under_odds")):
            io, iu = implied(L["over_odds"]), implied(L["under_odds"])
            mo, mu = io / (io + iu), iu / (io + iu)
            dec_o = 1 + (100 / -L["over_odds"] if L["over_odds"] < 0 else L["over_odds"] / 100)
            dec_u = 1 + (100 / -L["under_odds"] if L["under_odds"] < 0 else L["under_odds"] / 100)
            pm = po / (po + pu) if po + pu else 0.5
            r["p_over_model_nv"] = round(pm, 4)
            if blend_w is not None:
                pf = float(_sigmoid(blend_w * _logit(pm) + (1 - blend_w) * _logit(mo)))
                po, pu = pf * (po + pu), (1 - pf) * (po + pu)
                r.update(p_over=round(po, 3), p_under=round(pu, 3), blend_w=blend_w,
                         fair_over=american(pf), fair_under=american(1 - pf))
            ev_o = po * (dec_o - 1) - pu
            ev_u = pu * (dec_u - 1) - po
            r.update(mkt_novig_over=round(mo, 3), ev_over=round(ev_o, 3), ev_under=round(ev_u, 3))
            ratio = max(pm, 1e-6) / max(mo, 1e-6)
            if ratio >= 2 or ratio <= 0.5 or (1 - pm) / max(1 - mo, 1e-6) >= 2 or (1 - pm) / max(1 - mo, 1e-6) <= 0.5:
                r["check"] = "model/market gap >=2x implied: treat as model flaw until explained"
            # publish gate: an edge above max_ev is a model error by default, never a pick
            best = max(ev_o, ev_u)
            r["side"] = "OVER" if ev_o >= ev_u else "UNDER"
            r["ev_best"] = round(best, 3)
            if best > max_ev:
                r["status"] = f"BLOCKED: EV {best:.1%} > {max_ev:.0%} cap, review inputs (minutes/role/injury)"
            elif best > warn_ev and best > min_ev:
                r["status"] = "publish: high (>10%), check news"
            elif best > max(min_ev, 0):
                r["status"] = "publish"
            elif best > 0:
                r["status"] = f"below bar ({min_ev:.0%})"
            else:
                r["status"] = "no edge"
        out.append(r)
    return pd.DataFrame(out)


def slate_health(props: pd.DataFrame, max_ev=0.15, warn_ev=0.10):
    """One-line sanity check on a priced slate. A healthy slate has few >10% edges, none >15%,
    and roughly balanced over/under among positive-EV plays."""
    if props is None or "ev_best" not in props:
        return "slate health: no odds supplied"
    e = props.dropna(subset=["ev_best"])
    pos = e[e.ev_best > 0]
    if pos.empty:
        return f"slate health: {len(e)} lines priced, 0 positive EV"
    under = (pos.side == "UNDER").mean()
    msg = (f"slate health: {len(e)} lines, {len(pos)} +EV | >{warn_ev:.0%}: {(e.ev_best > warn_ev).mean():.1%} "
           f"| blocked >{max_ev:.0%}: {(e.ev_best > max_ev).sum()} | unders among +EV: {under:.0%}")
    if (e.ev_best > warn_ev).mean() > 0.10 or under > 0.70 or under < 0.30:
        msg += "  <-- FAILS: projections are biased vs market, do not publish this slate"
    return msg
