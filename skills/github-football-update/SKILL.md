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

`YYYY-MM-DD` is a Beijing business slate, defined as 12:00 on that date through
11:59 on the following date. A fixture before 12:00 is assigned to the prior
business date, so the dashboard does not mix two half-days.

For prematch coverage, Titan007 is the primary source and 500.com plus
BetExplorer are independent supplements. BetExplorer is joined after Beijing
date normalization because its schedule timestamps are UTC, and supplies both
Asian handicap and 1X2 prices through its public event endpoints. A missing
opening line remains allowed, but a row is bettable only after current Asian
line/waters and current 1X2 prices are present.

BetExplorer-only fixtures carry English provider labels, so the pipeline applies
`data/github_football/team_aliases.json` before writing the ledger and dashboard;
extend that alias file when a new club is first encountered.

## Handicap direction contract (mandatory)

At ingestion every source is normalized to one signed convention: a positive
home line means the home team gives the handicap; a negative home line means
the home team receives it. `market_row()` must use this normalized AH sign as
the source of truth. It must never reverse the sign a second time, and must not
replace a non-zero AH direction with a 1X2 favourite guess. Euro odds may be
used only as a fallback when the AH line is exactly level or absent, and any
clear AH/Euro conflict must be retained as an audit warning.

Every rendered row must expose `handicap_giving_team`,
`handicap_receiving_team`, and a signed home-line field. The visible text must
say which team is the 让球方, so a positive/negative number cannot be
misread as the opposite side. If a card displays a selected team, its displayed
line must be from that selected team's perspective: giving is negative and
receiving is positive; never reuse the home-team signed line for an away pick.
Team and competition labels must be Chinese;
when a BetExplorer-only English label appears, add its mapping to
`team_aliases.json` before publishing.

The script publishes date-scoped JSON and small responsive HTML shells under
`github_site/v3` and `github_site/v4`. The HTML loads only the requested date's
JSON, so mobile clients do not download the historical ledger on every visit.
V3 and V4 are separate views; V4 is the stricter cloud shadow view and neither
view may force a bet when current AH or Euro evidence is missing.

An opening AH line is optional. A pending senior match may be evaluated when
the current Asian line and both current waters plus the current 1X2 prices are
present. Recompute every unstarted row on each refresh so a transient blank
quote can recover later; preserve the last non-empty market fields when the
new snapshot omits them. Only rows already started/settled are decision-locked.

Before replacing the ledger, compare the incoming same-date count with the
previous count. A drop below 65% is a `ROW_COUNT_SHRINK_WARNING`; retain the
union of existing and incoming rows and expose the warning in `last_run.json`
and Feishu. Never silently shrink the ledger.

The GitHub workflow must install `requirements.txt`, run this script on a
GitHub-hosted runner, copy `github_site` into the `gh-pages` worktree, commit
and push the site, then send a short Feishu result using the
`FEISHU_WEBHOOK_URL` secret. Desktop runs continue to use the existing local
skill and Excel ledgers; do not mix the two ledgers during a single run.

## Performance guard

The fast path is HTTP/API fetch plus append-only JSON merge. Browser recovery is
an emergency path only: cap it at 48 market jobs, use at most four concurrent
workers, a 12-second page timeout, and one attempt. Keep mobile-page recovery
disabled unless a targeted investigation explicitly enables it. When the cap is
hit, log `future_browser_capped=used/queued` and leave the remaining rows as
explicit missing-data rows for the next refresh; never let a source outage turn
the daily job into an unbounded serial crawl. Each subprocess result records
`elapsed_seconds` so a slow phase is visible in the run manifest.
