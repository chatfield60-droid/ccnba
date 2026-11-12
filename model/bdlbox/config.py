"""Settings and model hyperparameters.

Every model input comes from BALLDONTLIE (BDL). Nothing here is a
hard-coded stat; the numbers below are modelling choices (decay, shrinkage
strength, simulation noise), not data.
"""
import os
from dataclasses import dataclass, field

BASE_URL = "https://api.balldontlie.io"

# Requests per minute by NBA tier (docs.balldontlie.io, Account Tiers table).
TIER_RPM = {"FREE": 5, "ALL-STAR": 60, "GOAT": 600, "TRIAL": 5}


@dataclass
class Settings:
    api_key: str = field(default_factory=lambda: os.environ.get("BDL_API_KEY", ""))
    tier: str = field(default_factory=lambda: os.environ.get("BDL_TIER", "ALL-STAR").upper())
    db_path: str = field(default_factory=lambda: os.environ.get("BDL_DB", "bdl_nba.sqlite"))

    @property
    def rpm(self) -> int:
        return TIER_RPM.get(self.tier, 60)


@dataclass
class ModelConfig:
    # --- recency weighting (half-lives measured in games) ---
    hl_player_rates: float = 25.0      # per-possession production rates
    hl_player_minutes: float = 10.0    # was 6: too reactive to end-of-season rest/limits
    short_game_frac: float = 0.5       # game under 50% of player's median minutes = rest/injury exit/blowout
    short_game_weight: float = 0.5     # ...counts half in the minutes estimate
    hl_team: float = 20.0              # pace, team rates, defensive factors
    prior_season_weight: float = 0.5   # multiplier on games from earlier seasons
    prior_season_weight_minutes: float = 0.35

    # --- empirical-Bayes shrinkage (prior strength) ---
    # per-possession counting rates: prior in team possessions on floor
    k_poss: dict = field(default_factory=lambda: {
        # 25% of the original strength: best on 2025-26 out-of-sample rate error (grid of 48 settings)
        "fg2a": 37.5, "fg3a": 37.5, "fta": 62.5, "oreb": 50, "dreb": 37.5,
        "ast": 37.5, "stl": 100, "blk": 100, "tov": 62.5, "pf": 62.5,
    })
    # shooting percentages: prior in attempts
    k_pct: dict = field(default_factory=lambda: {"fg2": 120, "fg3": 200, "ft": 60})
    league_env: bool = True            # adjust rates to this season's league shot mix / shooting / pace
    k_env_games: float = 50.0          # team-games of this season at which the adjustment is half weight
    role_tier_prior: bool = True       # shrink toward same position + minutes role, not position only
    role_tiers: tuple = (0, 15, 24, 31, 60)
    # team defensive factors: prior in games
    k_def_games: float = 15.0
    k_def_pct_games: float = 35.0
    k_pace_games: float = 10.0
    k_home_games: float = 400.0

    # --- simulation ---
    n_sims: int = 10000
    pace_sd: float = 4.0               # game-to-game possession noise
    min_sd_floor: float = 3.0
    min_sd_default: float = 6.0
    max_minutes: float = 44.0
    min_minutes_to_roster: float = 4.0
    form_shape: float = 15.0           # gamma "night-to-night form" on volume stats (was 30: too tight)
    # "our mean is wrong" uncertainty, lognormal sd, shared by all of a player's stats
    rate_unc_base: float = 0.06
    rate_unc_new: float = 0.10         # extra when few games this season (decays over unc_games)
    min_unc_base: float = 0.05
    min_unc_new: float = 0.10
    unc_games: float = 15.0
    unc_team_change: float = 0.08
    # first-quarter shares: prior strength in full-game stat units
    k_q1: dict = field(default_factory=lambda: {"pts": 60, "reb": 25, "ast": 15})
    grab_and_go: bool = True
    grab_and_go_slope: dict = field(default_factory=lambda: {"F": 0.197, "G": 0.131, "C": 0.108})
    minutes_model_path: str = "minutes_model.pkl"   # `train-minutes` writes it; used when present
    rotation_cut: bool = True          # trim roster overflow from the end of the bench (off in oracle backtest)
    # pick publishing gate
    max_ev: float = 0.15               # anything above is blocked as a model error
    warn_ev: float = 0.10
    # set both from `python -m bdlbox fit-market`
    min_ev_publish: float = 0.0        # Option A: model-only EV must clear this to publish
    market_blend_w: float = None       # Option B: model weight vs no-vig market; None = off (pure model)
    # calibration: shown probability = book + w * (model - book) in log-odds. w measured with the
    # packaged `scorecard` (morning mode, deterministic minutes model) on Staicy's 5,036 graded player
    # props (2026-10-20..11-10), per stat, shrunk toward the pooled 0.255 (600-line prior).
    # Out-of-sample warning: weights fit on October and applied to November lost (EV 0-15%: n=973,
    # ROI -5% +/-3.4%; 10-15% band: n=66, ROI -10% +/-13%). Refit every two weeks with `scorecard`.
    # Team markets measured -0.73 +/-0.31: shown at the book price (w = 0), never suggested.
    calib_enabled: bool = True
    # Set at the optimistic end of the measured range: measured + 1 standard error of the pooled
    # estimate (0.266 + 0.058), i.e. every measured weight x1.22. ~14 suggested plays/day vs ~6.
    calib_w: dict = field(default_factory=lambda: {"player_under": 0.324, "player_over": 0.324, "team": 0.0})
    calib_w_market: dict = field(default_factory=lambda: {
        "pts": 0.259, "reb": 0.459, "ast": 0.366, "fg3m": 0.414,
        "pr": 0.327, "pa": 0.201, "ra": 0.354, "pra": 0.303})
    team_markets_live: bool = True     # every team line gets a prediction row
    suggest_team_markets: bool = False # team lines can't be suggested until a team model earns weight
    suggest_overs: bool = True
    suggested_markets: tuple = ("pts", "reb", "ast", "fg3m", "pr", "pa", "ra", "pra")
    suggested_min_ev: float = 0.10     # suggested = calibrated EV 10-15% + every backup check
    suggested_max_per_day: int = 1000  # no count cap: the band itself sets volume (~8-13/day measured)
    display_knee: float = 0.14         # shown EV equals calibrated EV up to here, flattened below 15%
    display_d0: float = 0.8            # display shrink: logit gap at which model weight halves
    max_odds_abs: float = 200          # prices outside -200..+200 are never displayed
    sug_min_gap: float = 5.0           # projected vs L10 minutes must agree within this, unless explained
    sug_out_min_explains: float = 15.0 # teammate minutes out that can explain a minutes jump
    sug_min_games_season: int = 5
    sug_min_games_total: int = 20
    # game check: any pick in a failing game is withheld
    game_total_tol: float = 8.0        # model total vs market main total
    game_spread_tol: float = 8.0       # model margin vs market main spread
    team_pts_tol: float = 15.0         # model team points vs team's last-10 average
    recon_alpha: float = 0.8           # 0 = no team reconciliation, 1 = full
    recon_stats: tuple = ("fg2a", "fg3a", "fta", "ast", "oreb", "dreb", "tov")

    # availability probability by BDL injury `status`
    avail_by_status: dict = field(default_factory=lambda: {
        "out": 0.0, "out for season": 0.0, "suspended": 0.0,
        "doubtful": 0.25, "questionable": 0.5, "day-to-day": 0.6,
        "game time decision": 0.5, "probable": 0.9,
    })
    roster_staleness_days: int = 240   # fallback roster: last game with team within N days


COUNT_STATS = ["fg2a", "fg3a", "fta", "oreb", "dreb", "ast", "stl", "blk", "tov", "pf"]
BOX_STATS = ["min", "pts", "reb", "ast", "fg3m", "fgm", "fga", "fg3a", "ftm", "fta",
             "oreb", "dreb", "stl", "blk", "tov", "pf", "pra", "pr", "pa", "ra", "stocks"]
