---
name: github-football-update
description: Run the repository-portable V3/V4 football refresh on a GitHub-hosted runner, preserving the append-only ledger and publishing lightweight mobile dashboards. Use for scheduled cloud runs; use the desktop football_update skill when local Excel and full evidence sources are available.
---

# GitHub Football Update

This is the cloud companion to the desktop football skill. It must run from the
checked-out repository and must not assume `D:\codex`, a local Excel path, a
Windows browser, or a running desktop session.

Run `python tools/github_football_update.py --list-date YYYY-MM-DD`. The script
fetches the Titan snapshot into `data/raw/titan007`, merges by `match_id`, and
writes the append-only state to `data/github_football/ledger.json` and
`ledger.csv`. Started/settled rows are locked: refresh may update score and
settlement fields but must not replace the earlier market or decision.

The script publishes date-scoped JSON and small responsive HTML shells under
`github_site/v3` and `github_site/v4`. The HTML loads only the requested date's
JSON, so mobile clients do not download the historical ledger on every visit.
V3 and V4 are separate views; V4 is the stricter cloud shadow view and neither
view may force a bet when current AH or Euro evidence is missing.

Before replacing the ledger, compare the incoming same-date count with the
previous count. A drop below 65% is a `ROW_COUNT_SHRINK_WARNING`; retain the
union of existing and incoming rows and expose the warning in `last_run.json`
and Feishu. Never silently shrink the ledger.

The GitHub workflow must install `requirements.txt`, run this script on a
GitHub-hosted runner, copy `github_site` into the `gh-pages` worktree, commit
and push the site, then send a short Feishu result using the
`FEISHU_WEBHOOK_URL` secret. Desktop runs continue to use the existing local
skill and Excel ledgers; do not mix the two ledgers during a single run.
