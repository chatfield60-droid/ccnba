# bdlbox: NBA box score model on BALLDONTLIE only

Projects a full box score (every player, every stat, plus team score, total, margin and win
probability) for each NBA game on a date, using nothing but the BALLDONTLIE NBA API.
Output is a Monte Carlo distribution, so every line comes with p10/p50/p90 and, if you hand it
prop lines, P(over), P(under), P(push), fair prices and EV.

## Tier you need

| Tier | Works? | Why |
|---|---|---|
| Free (5 req/min) | No | `/v1/stats` (game box scores) is ALL-STAR+. No box scores, no model. |
| **ALL-STAR ($9.99/mo, 60 req/min)** | **Yes, full model** | `/v1/games`, `/v1/stats`, `/v1/players/active`, `/v1/player_injuries` are everything the model reads. |
| GOAT ($39.99/mo, 600 req/min) | Yes, faster sync | Nothing GOAT-only is required. See "GOAT data not used" below. |

The model was deliberately built on the ALL-STAR endpoint set. A first full sync of one season is
roughly 260 to 300 paged calls of `/v1/stats` (100 rows each), about 5 minutes at 60 req/min.
Daily syncs after that are incremental.

## Endpoint map

| BDL endpoint | Used for |
|---|---|
| `GET /v1/teams` | team ids, abbreviations |
| `GET /v1/games?seasons[]=` | schedule, home/away, final scores (backtest grading) |
| `GET /v1/stats?seasons[]=&season_type=regular` | every player box score: min, fgm/fga, fg3m/fg3a, ftm/fta, oreb, dreb, ast, stl, blk, turnover, pf, pts. All rates, minutes, pace and defense come from these rows. |
| `GET /v1/players/active` | current rosters (handles offseason trades and signings) |
| `GET /v1/player_injuries` | `status` per player mapped to an availability probability |

Derived (not fetched): possessions `FGA - OREB + TOV + 0.44*FTA` averaged across both teams, pace per
48 using summed player minutes / 5 (so OT games are handled), and every team/opponent factor.

Excluded on purpose: `/v2/odds` and `/v1/odds/player_props`. Book lines are never model inputs.
You can pass your own lines file at the end for pricing and a calibration check.

## How a projection is built

1. **Player rates per on-floor possession** for 2PA, 3PA, FTA, OREB, DREB, AST, STL, BLK, TOV, PF.
   Recency-weighted (half-life 25 games), prior season games at 0.5 weight, then shrunk toward the
   league rate for the player's position group (G/F/C from BDL `position`).
2. **Shooting %** for 2s, 3s, FTs, shrunk toward position averages by attempt count.
3. **Minutes**: recency-weighted mean (half-life 6 games) and the player's own spread.
4. **Pace**: team pace rating (shrunk), game pace = home x away / league.
5. **Opponent factors**: what each defense allows per possession in every stat, plus 2P% and 3P%
   allowed, all shrunk toward 1.0.
6. **Home edge**: estimated from home vs road points per possession in the data, heavily shrunk.
7. **Simulation (10,000 per game)**: each draw samples who plays from injury status, samples
   minutes, renormalizes the team to its expected total minutes (cap 44), samples pace, draws
   counts as Poisson with a shared "form" multiplier on volume stats, then **reconciles shots,
   assists, boards and turnovers to the team's own per-possession rates** (that is the usage
   bump when a starter sits), and draws makes as binomial on attempts.
8. Player rows are reported **conditional on playing**, which is how props settle; `p_active`
   is shown separately.

## Run it

Python 3.10+.

```bash
cd bdl_box_model
python -m pip install -r requirements.txt
export BDL_API_KEY="your_key"
export BDL_TIER="ALL-STAR"          # or GOAT
export BDL_DB="bdl_nba.sqlite"

# first time: last season + this season (BDL season = start year, 2026 = 2026-27)
python -m bdlbox sync --seasons 2025 2026

# validate before trusting it: walk-forward on 2025-26 (every 3rd date for speed)
python -m bdlbox backtest --season 2025 --start 2025-11-15 --sims 1000 --every 3

# game day: refresh (incremental box scores, rosters, injuries), then project
python -m bdlbox sync --seasons 2026
python -m bdlbox project --date 2026-10-20 --lines lines_example.csv
```

Outputs in `out/`:

- `box_<date>.csv`: one row per player. Means for min, pts, reb, ast, fg3m, fg3a, fgm, fga, ftm, fta,
  oreb, dreb, stl, blk, tov, pf, pra, pr, pa, ra, stocks; sd and p10/p50/p90 for min, pts, reb,
  ast, fg3m, pra; `p_active`, `injury_status`, `flags`.
- `games_<date>.csv`: projected pace, team points, total and sd, home margin and sd, home win prob.
- `props_<date>.csv` (with `--lines`): P(over/under/push), fair odds, no-vig market, EV each side,
  and a `check` flag when model and market differ by 2x or more in implied probability.
- `gaps_<date>.json`: every gap that affected this slate (rookies, stale injury snapshot, etc).
- backtest: `backtest_players_<season>.csv`, `backtest_games_<season>.csv`, and a printed table of MAE vs
  a season-average baseline, bias, and 80% interval coverage via randomized PIT (should land near 80%).

Lines file columns: `player` (BDL "First Last") or `player_id`, `stat`, `line`, optional
`over_odds`, `under_odds`, and optional `p_book_over`. When supplied, `p_book_over` is the
upstream median no-vig P(over) across books at that exact line. It is used for calibration;
`over_odds` and `under_odds` remain the prices used to calculate EV. Without it, the package
devigs the two prices on the row. Stat keys match the box columns (pts, reb, ast, fg3m, pra, stocks, ...).

## v1.1: under bias and oversized edges (opening-night slate review)

The 2026-10-20 slate published 376 picks: 85% unders, 65% above 15% EV, max 84.8%. Two causes:

1. **Projected means too low for rotation players (main cause).** Active rosters run 15 to 18
   deep, so expected minutes overflowed 240 and every player was shrunk by the same percentage. Team
   reconciliation then handed the starters' lost share of shots and boards to the bench. Result:
   game totals near market, stars about 20% under their lines, low-usage players over.
   Fix: in each simulated game, overflow comes off the end of the bench first (they drop out of
   the rotation), so starters keep their minutes. Minutes half-life went from 6 to 10 games, and
   games under 50% of a player's median minutes (rest, injury exits) count half, so end-of-season
   rest no longer drags opening-night minutes down. Synthetic check with deep rosters: starters
   28.7 projected vs 31.35 true before the fix, 30.9 after.
2. **Distributions too tight.** The picks' fair odds match pure Poisson around PREDICTED for
   reb/ast/3PM (points behave like a sum of Poisson shot counts), with no allowance for the
   projection being wrong. Fix: a per-player role-uncertainty multiplier shared across all of the
   player's stats (wider early in the season and for team changes), and more night-to-night
   dispersion (`form_shape` 30 -> 15). Every stat now exports `<stat>_sd`.
   **The platform should price from `props_<date>.csv` probabilities (or from mean + `_sd`),
   not Poisson(PREDICTED).** If it keeps Poisson, fix 2 never reaches the published odds.

Guardrails in `props_<date>.csv`:
- `status`: `BLOCKED` when best-side EV > 15% (`max_ev`), `publish: high` between 10% and 15%.
  A blocked line is a model error to investigate, never a capped pick.
- `slate health` line printed by `project`: share above 10%, blocked count, and unders share among
  +EV plays. It prints FAILS when more than 10% of lines are above 10% EV or unders are outside
  30 to 70%. A FAILS slate should not be published.

## v1.2: compression check and calibration grid

The backtest report now ends with a compression check: the slope of actual on projected, plus
actual/projected by projection quintile, for pts, reb, ast, fg3m, min. A slope of 1.00 is calibrated.
Above 1 means projections are squeezed toward the middle (stars too low, role players too high),
which shows up against the market as unders on stars and overs on role players.

`python -m bdlbox calibrate --season 2025 --start 2025-11-15` reruns the backtest over a grid of
shrinkage strength (`k_poss` x1, x0.5, x0.25) and team reconciliation (`recon_alpha` 0.8, 0.4, 0) and
writes `out/calibration_2025.csv`, best row first. Defaults are unchanged until the real 2025-26
backtest picks a row; the synthetic league gives inconsistent answers depending on the window.

## v1.3: how much is a model edge worth (Options A and B)

`python -m bdlbox fit-market --season 2025 --lines hist_props_2025.csv`

Input: historical prop prices, one row per book per prop:
`date,player_id|player,stat,line,over_odds,under_odds[,book]`. Stat names can be Staicy style
(points, rebounds, three_points, points_rebounds_assists, ...). For each date the model uses only
games before it and the players who actually played (props void on DNP). Pushes are dropped.

Output:
- `P(over) = sigmoid(a + b_m*logit(model) + b_k*logit(no-vig market))` and the model weight
  `w = b_m / (b_m + b_k)`, with standard errors.
- Log-loss of model vs market. If the model loses here, it has no edge to publish at all.
- Realized ROI by model-only EV bucket, and ROI by month (the early-season penalty shows here).
- `out/fit_market_rows_<season>.csv` with every settled line.

Then set ONE of these in `bdlbox/config.py`:
- **Option A (pure model):** `min_ev_publish` = the lowest EV bucket whose ROI is reliably above 0.
  Probabilities stay model-only; lines below the bar show `below bar`.
- **Option B (blend):** `market_blend_w = w`. Final P(over) = sigmoid(w*logit(model) +
  (1-w)*logit(no-vig)). Projections are untouched; the raw model probability stays in
  `p_over_model_nv`. Example: a Wembanyama rebounds U11.5 at -110 that prices at 15.2% model-only
  is 5.5% at w=0.5 and 1.5% at w=0.3.

Fit against closing prices if you have them. Opening prices are softer, so a fit on openers
overstates w.

## v1.4: display rules, every BDL market, game check

**Files Staicy reads after `project --lines`:**
- `out/props_<date>.csv`: the ONLY file to display. Every row is `signal` (EV up to 10%) or
  `suggested` (10 to 15%). Nothing above 15% can be in it (the run aborts if one ever is).
- `out/review_<date>.csv`: internal only. Every withheld line with its `reason`.

**Suggested plays (10 to 15% EV)** must pass every check, or they're withheld:
1. The player's last-10 or season average agrees with the side (milestones: rate vs market).
2. Projected minutes within 5 of the last-10 average, unless the jump is explained by at least
   15 minutes of teammates ruled out.
3. Sample: 5+ games this season, or 20+ total with no team change.
4. No player flags and no injury designation on the player himself.
5. Not a derived market (first 3 minutes).
Each displayed row carries `backup`: projection vs line, last-10 and season averages, minutes
projected vs last-10, teammates out, per-36 rate vs last-10, team usage adjustment, pace, and the
opponent factors that moved the number.

**Game check:** if the model's game total or margin is more than 8 from the market's main line,
or a team's projected points are more than 15 from its last-10 average, every line in that game
goes to review. Market prices are only compared here, never used as inputs.

**Markets priced** (BDL `prop_type` names or Staicy names): points, rebounds, assists, threes /
three_points, steals, blocks, turnovers, blocks_steals, points_rebounds, points_assists,
rebounds_assists, points_rebounds_assists, double_double, triple_double, points_1q, rebounds_1q,
assists_1q, points_first3min, rebounds_first3min, assists_first3min, game_total, team_total,
spread, moneyline.
- 1Q props use first-quarter box scores from BDL (`/v1/stats?period=1`): run `sync --q1`.
  Each player's 1Q share of his game output is shrunk toward the league share for his role.
- First-3-minute props are derived from 1Q output and starter likelihood. They can be a
  signal but never a suggested play.
- Prices outside -200..+200 are never displayed.

**Lines CSV columns:**
- player props: `player` or `player_id`, `stat`, `line`, `over_odds`, `under_odds`
- milestones (double_double, triple_double): `yes_odds` (or over/under pair)
- game_total: `game` ("Away Team @ Home Team", full names or abbreviations) or `game_id`, `line`,
  `over_odds`, `under_odds`; team_total adds `team` = HOME / AWAY / team name
- spread: `line` = HOME spread (e.g. -4.5), `home_odds`, `away_odds`; moneyline: `home_odds`, `away_odds`

Keep `recon_alpha` at 0.8 (or 0.4). At 0 the team's shot total is just the sum of every player's
old usage, which on a roster with several high-usage players produced a 258-point game projection.

## v1.5: a prediction on every line, shown EV always under 15%, directional picks

`project --lines` now writes:
- `out/predictions_<date>.csv`: every offered line, every player, nothing dropped. Columns include
  `model_mean` (projection), `direction` (side the model thinks hits more often), `p_hit`,
  `pick`, `odds`, `p_display`, `fair`, `ev` (shown EV, always < 15%), `tier`
  (suggested | lean | pass), `reason` (why it is not a higher tier) and `backup` (written breakdown).
- `out/no_prediction_<date>.csv`: only lines the model cannot price, with why (no BDL history,
  projected inactive, no 1Q data synced).
- `out/box_<date>.csv`: every projected player, every stat, with or without a line.

How shown EV is built: model probability pulled toward the no-vig price with weight
`1 / (1 + (gap / display_d0)^2)`, where gap is the model-vs-market difference in log-odds. A small
gap keeps almost the full model, while a huge gap (a model error by default) keeps little. The side never flips.
Above 10% the EV saturates smoothly below 15%. Projections are untouched. The model-only number
stays in `internal_ev_model_only` (internal, do not display).

Tiers:
- `suggested`: shown EV 10-15%, model-only EV not above 15%, and every backup check passes.
- `lean`: positive EV, pick matches the model's direction, price within +/-200, game check ok.
- `pass`: everything else, with the reason (no edge, value against model direction, game check,
  price range).
A lean or suggested pick is always on the side the model thinks is more likely to hit.

## v2.2: Grab & Go, measured

Opponents who take more threes give up more long rebounds. Measured on BDL 2023-24..2025-26
(rebounds per 10% more opponent 3PA than league): wings/forwards +2.0% (+/-0.6%), guards +1.3%,
centers +1.1%; applied to offensive and defensive rebound rates (`grab_and_go_slope`).
Graded rebound markets: model weight 0.285 -> 0.308, rebounds alone 0.448 -> 0.475.
Not carried over from the old spec: the assist boost (data shows wings get slightly fewer assists
vs high-3PA teams) and the interior boost for bigs vs low-3PA teams (centers rebound more vs high-3PA
teams too). Rebound plays show a Grab & Go line in `backup`.

## v2.1: 10-15% suggested band, per-stat calibration, morning-only runs, team markets shown

- **Morning-only** is the default and how the numbers below were measured: tonight's starters come
  from BDL projected lineups (`sync --goat --date`) when posted, otherwise the minutes model uses
  the recent starting rate. Cost vs confirmed lineups: minutes MAE 4.84 vs 4.50 (old method 5.60).
- **Per-stat calibration** (`calib_w_market`), measured with the packaged deterministic `scorecard`
  in morning mode on 5,036 graded props, shrunk toward the pooled 0.255: reb 0.357, fg3m 0.328,
  ast 0.318, ra 0.270, pr 0.252, pra 0.234, pts 0.198, pa 0.156 (v2.2 with Grab & Go: pooled 0.266, reb 0.376).
- **Suggested = calibrated EV 10-15%** + every backup check, one per player, no count cap.
  About 5-6 a day on the graded period. **Out-of-sample warning:** weights fit on October and applied
  to November lost (all +EV: 973 bets, ROI -5% +/-3.4%; 10-15% band: 66 bets, ROI -10% +/-13%).
  The projections are more accurate; a profitable edge against these lines is not established.
- The minutes model now trains deterministically (no random early-stopping split): same data,
  same results, every run.
- **Shown EV = calibrated EV** up to 14%, flattened below 15%; anything truly above 15% is a pass.
- **Team markets** (game total, team total, spread, moneyline) get a prediction row every day, priced
  at the book (w = 0) and never suggested: v2 measured -0.73 +/-0.31 on 320 graded team lines.
- `scorecard` scores morning mode by default; `--confirmed` uses actual starters.

## v2.0: model rebuild, tested on real BDL data (2023-24 to 2026-27)

Scorecard = replay on Staicy's 5,048 graded player props (2026-10-20..11-10), model rebuilt as of
each date, minutes model trained only on games before the first graded date.

| | Staicy as run | v1.6 | v2.0 |
|---|---|---|---|
| slope of (actual - line) on (model - line) | 0.11 | 0.22 | 0.41 to 0.44 |
| model weight vs book (log-odds) | ~0.16 | 0.15 | 0.26 to 0.28 |
| stat MAE (book line's own MAE 4.13) | 4.48 | 4.31 | 4.19 to 4.20 |

What changed:
1. **Minutes model** (`minutes.py`, `train-minutes`): gradient boosting on recent minutes, starter
   status (BDL projected/confirmed lineups tonight; lineups history), rest, back-to-backs, games
   missed and games since return, teammates out (total and same position), blowout risk from
   point differential, foul rate. Held-out minutes MAE 4.48 vs 5.60 for a recent average (2026-27),
   bench 4.74 vs 6.39. Spread scale measured out-of-sample (1.29).
2. **Role-tier priors**: small samples shrink toward players of the same position AND minutes role.
3. **League environment**: rates follow this season's league shot mix, shooting and pace
   (2026-27: fewer twos, more threes and free throws, lower percentages), weight grows with games.
4. **Prior strength 25%** of v1 (best of 48 settings on 2025-26 out-of-sample rate error).
5. **Calibration** measured on the v2 replay: over-edges 0.257, under-edges 0.255 (were -0.13 / 0.40).
   Overs are back.
6. **Suggested**: top 30 per day by calibrated EV (at least 2%), any player prop market, both sides,
   all backup checks, one per player, not 2x+ off the book's implied probability.
7. **Tested and not shipped**: rebound chances (advanced stats) did not beat per-possession rates.
8. **Team totals**: the 258-point projections were reconciliation set to 0; at 0.8 plus the league
   adjustment the remaining bias is about +4.4 per game, similar to the book lines this season.
   Team markets stay off until refit on two weeks of v2 results.

Commands (GOAT):
- `sync --seasons 2026 --goat --date YYYY-MM-DD`: box scores, starters history, quarter scores,
  projected lineups for that date. Run once in the morning, again ~30 min before tip.
- `train-minutes`: weekly.
- `scorecard --lines graded.csv`: replay on graded lines; watch slope and w.

## v1.6: calibrated to graded results (2026-10-20 to 11-10)

Measured on 5,431 graded Cut 15 suggested plays (fit of win ~ market + w * (model - market), log-odds):

| group | model weight w | n |
|---|---|---|
| all player props | 0.22 +/- 0.08 | 5,093 |
| player unders | 0.40 +/- 0.10 | 3,337 |
| player overs | -0.13 +/- 0.15 | 1,756 |
| team markets (spread, game total, team total) | -0.96 +/- 0.37 | 338 |

Model claimed 55.7% win probability on these picks; the book's price implied 49.6%; realized was 49.4%.
Projection gap vs line predicted only about 11% of the actual gap (slope 0.11 +/- 0.03).

Changes (config.py):
- `calib_enabled`, `calib_w`: shown probability = market + w * (model - market). Unders 0.30 (0.40
  shrunk toward the pooled 0.22), overs 0, team 0. Refit with `fit-market` every 2 weeks.
- `team_markets_live = False`: spreads, game totals, team totals still priced, shown as pass.
- Suggested plays = today's top `suggested_max_per_day` (10) eligible leans by calibrated EV:
  single-stat markets only (`suggested_markets`), unders only (`suggest_overs = False`), calibrated EV
  at least `suggested_min_ev` (2%), every backup check passed, one per player.
- Expect few or no suggested plays on many days until the model improves: at -110, a 14-18%
  model-only edge calibrates to roughly 0-0.5%. That is the measured value of the current model.

## Known gaps (stated, not hidden)

- **Rookies and anyone with zero BDL box scores are not projected.** BDL has no college or
  summer league stats. They are listed in `gaps_<date>.json`, and their team's minutes are spread
  across players who do have history, so teams leaning on rookies will over-project those vets.
- **Opening week runs entirely on 2025-26 data.** New-team players carry their old rates and old
  minutes (flagged "team change"). Expect the most error in the first 2 to 3 weeks.
- **Injury history does not exist in BDL.** `/player_injuries` is a live snapshot, so the backtest
  uses oracle availability (who actually logged minutes). Backtest error therefore understates
  live error from injury uncertainty. Only project dates near your last sync.
- **Starting lineups**: BDL `/v1/lineups` only populates once a game tips, so it cannot feed a
  pregame projection.
- **Not modeled**: back-to-backs and rest, blowout minute cuts, coach rotation changes, foul
  trouble, positional (not team-level) defense. Minutes freed by an absence are spread in
  proportion to existing minutes, which overstates deep-bench gains.
- **Untested against the live API.** The client and flatteners are written to the documented
  response shapes and run end to end on synthetic data served in those exact shapes
  (`tests/fake_bdl.py`), but my build environment could not reach api.balldontlie.io. Run the
  backtest on real 2025-26 data before using output; `form_shape`, `pace_sd`, shrinkage `k_*`
  and half-lives in `bdlbox/config.py` are the knobs to calibrate against it.

## GOAT data not used (possible upgrades)

`/nba/v2/stats/advanced` (per-game usage%, possessions, touches, rebound chances),
`/v1/season_averages` (playtype, tracking, shot zones) and `/nba/v1/team_season_averages` (opponent
splits by zone) could sharpen usage and matchup factors. They were left out so the core model runs
on ALL-STAR and stays a single, consistent source.

## Tests

```bash
python tests/test_e2e.py
```

Synthetic league, not real NBA data. Checks: sync through the real client (pagination, auth,
flattening, min-string parsing), leakage (perturbing every row on or after the projection date
leaves model state unchanged), parameter recovery, roster edge cases (trade, Out, Questionable,
rookie), line pricing, and the backtest.
