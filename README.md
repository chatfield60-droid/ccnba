# CC Analytics NBA

Next.js in `web/` serves the public CC Analytics NBA props board. Python in `model/` and `pipeline/` runs in GitHub Actions. Vercel only reads published JSON from Blob. The live project is `ccanalytics-nba` and the site is `https://ccanalytics-nba.vercel.app`.

## Setup

1. Vercel project `ccanalytics-nba` uses root directory `web`. Two Blob stores are connected: public `bdlbox-public` for JSON and private `bdlbox-private` for SQLite and the minutes pickle. The deployed site reads the public store. The supplied database and minutes model were seeded on November 12, 2026.
2. In the new GitHub repository's Actions secrets, set `BDL_API_KEY`, the public `BLOB_READ_WRITE_TOKEN`, and the private `PRIVATE_READ_WRITE_TOKEN`. The Blob tokens are available in the Vercel project's environment settings. Never commit these values.
3. The daily workflow runs the model at 10:30 AM Eastern. Dispatch `.github/workflows/daily.yml` after adding secrets. Its JSON appears under `slates/<date>/` and `slates/latest.json`.
   The separate scores workflow refreshes the last seven days of finals, today's live games, and the next two days of schedule every 30 minutes. It publishes `games/live.json` with scores only after tipoff. The Games page joins those results to each day's stored pregame projections.
4. Link the GitHub repository to the existing Vercel project. Vercel's root directory is `web`; each push to the production branch can then rebuild the site.

The site displays an honest empty state until a slate is published. The first slate, November 12, 2026, was published manually after live odds ingestion. The model database and pickle are never deployed with the web app. The public JSON allowlist excludes internal probability and over-cap fields. Alternate thresholds stay distinct by player, stat, game, and line, including yes-only milestones. Top picks reserve one slot for a higher-probability positive-EV play while retaining the model's suggested or lean label.

The current BALLDONTLIE paths and response fields are documented in `pipeline/README.md`. Both daily UTC cron entries are needed for Eastern daylight saving changes; the script exits unless the scheduled run is at 10:30 Eastern.

The model alone assigns the `suggested` tier. The 10–15% calibrated EV band, backup checks, one pick per player, and 15% publication cap remain in force. On the November 13 slate, seven clean 8–10% EV leans belonged to six players; two already had a different suggested play, so lowering the floor would add at most four players. That single-slate observation is not a performance test, and the floor has not been lowered.

For local UI work: `cd web && npm ci && npm run dev`. Provide a public Blob token as `BLOB_READ_WRITE_TOKEN` in `web/.env.local` to see real data.
