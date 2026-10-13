# Football Odds Dashboard

This public snapshot is generated from the local quantitative odds projects. The basketball automation is defined in `.github/workflows/basketball-daily.yml`.

## Basketball schedule and Feishu delivery

The workflow runs every day at **07:00 Asia/Shanghai** (`23:00 UTC` on the previous day) for the same-day version and again at **20:00 Asia/Shanghai** (`12:00 UTC`) for the next-day version. The evening run automatically targets tomorrow's Beijing date; both runs can also be started from the Actions tab with `workflow_dispatch` and an explicit `target_date`. Each run uses the committed basketball engine, updates the `gh-pages` dashboard, waits for the Pages deployment, and sends a compact result to Feishu after publication.

Before the first run, add a repository secret named `FEISHU_WEBHOOK` containing the Feishu bot webhook. The URL is deliberately read only from the secret and is never written to the repository, workflow log, dashboard, or generated data. The workflow uses the existing `GITHUB_TOKEN` to push the dashboard to `gh-pages`, waits for the Pages deployment for the exact pushed commit, and only then sends the Feishu message. A failed engine or Pages deployment still produces a status notification without claiming a successful publication.

Dashboard: `https://simondongxiao.github.io/odds/basketball-v2.html`

GitHub Actions runners cannot read a local `D:\codex` folder. The workflow therefore keeps a bounded dashboard state in `gh-pages` and stores detailed run audits as Actions artifacts. The local Codex task output remains under `D:\codex\outputs\basketball_odds_trader`; the local daily command is still available at `basketball_engine/scripts/run_basketball_daily.py`.
