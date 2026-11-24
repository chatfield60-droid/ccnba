# CC Analytics NBA

Next.js in `web/` serves the public CC Analytics NBA matchup board and separate player-props page. Python in `model/` and `pipeline/` runs in GitHub Actions. Vercel only reads published JSON from Blob. The live project is `ccanalytics-nba` and the site is `https://ccanalytics-nba.vercel.app`.

## Setup

1. Vercel project `ccanalytics-nba` uses root directory `web`. Two Blob stores are connected: public `bdlbox-public` for JSON and private `bdlbox-private` for SQLite and the minutes pickle. The deployed site reads the public store. The supplied database and minutes model were seeded on November 12, 2026.
2. In the new GitHub repository's Actions secrets, set `BDL_API_KEY`, the public `BLOB_READ_WRITE_TOKEN`, and the private `PRIVATE_READ_WRITE_TOKEN`. The Blob tokens are available in the Vercel project's environment settings. Never commit these values.
3. The daily workflow refreshes the model and odds at 12:17 AM, 3:17 AM, 6:17 AM, 9:17 AM, 12:17 PM, and 3:17 PM Eastern, with a manual dispatch available. Its JSON appears under `slates/<date>/` and `slates/latest.json`. GitHub's scheduled runs can start late; the midnight refresh helps cover the early morning. No-odds runs leave the last published slate in place without creating a failure notification.
   The separate scores workflow refreshes the last seven days of finals, today's live games, and the next two days of schedule every 30 minutes. It publishes `games/live.json` with scores only after tipoff. The Games page joins those results to each day's stored pregame projections.
4. Vercel's root directory is `web`. Code deployment currently uses `vercel deploy --prod` from the repository root because the Vercel Git identity cannot connect this repository. The GitHub daily and scores jobs publish data independently of code deployment.

The site displays an honest empty state until a slate is published. The first slate, November 12, 2026, was published manually after live odds ingestion. The model database and pickle are never deployed with the web app. The public JSON allowlist excludes internal probability and over-cap fields. Alternate thresholds stay distinct by player, stat, game, and line, including yes-only milestones. `/` is the matchup-first board. `/props` has fixture-specific player pricing, best edges, projected opportunity, and alternate ladders. The top edges on `/` retain each pick's suggested or lean label.

## Staicy model handoff

`/api/model-slate` exposes the exact public prediction rows shown by the website, including each line, side, price, book, EV, tier, and written breakdown. It also returns the slate date, model run time, model version, odds source, and a SHA-256 `snapshot_id` for the published predictions file. Staicy Beta should consume this model output if its picks and results are intended to match the website. Both systems must identify a pick by slate date, game ID, player ID, stat, line, side, and snapshot ID, and grade the published price rather than a later quote. This feed currently uses BALLDONTLIE odds; a separate Betstamp line and price feed will produce different selections and ROI even when projections are close. Do not treat the Staicy Beta graded export as a model input or overwrite the website's model slate with it.

The current BALLDONTLIE paths and response fields are documented in `pipeline/README.md`. Both daily UTC cron entries are needed for Eastern daylight saving changes; the script exits for the entry that does not match the current offset.

The model alone assigns the `suggested` tier. A player line must pass the existing backup, game, price, direction, and calibration checks. It then qualifies with either at least 8% calibrated EV or at least 6% EV and 65% calibrated hit probability. Alternate lines qualify under the same rule. One suggested pick per player and the 15% publication cap remain in force. This broader rule was requested to increase suggestion volume; it is a policy change and requires monitoring in graded results.

For local UI work: `cd web && npm ci && npm run dev`. Provide a public Blob token as `BLOB_READ_WRITE_TOKEN` in `web/.env.local` to see real data.
