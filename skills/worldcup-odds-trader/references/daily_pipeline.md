# Football V3/V4 daily pipeline reliability

Use this runbook whenever the task is a daily V3/V4 update, score backfill, settlement, Excel refresh, HTML publish, or Feishu notification. It records the failure patterns found in the October 8-14 runs and is part of the data contract.

## Date and authoritative views

- Compute `list_date` in `Asia/Shanghai`. A scheduled 23:00 UTC run is the next day at 07:00 Beijing time. Pass the same date to the fetcher, ledger, JSON exports, HTML query string, and Feishu message.
- The Excel ledger is the full bottom layer. Keep every fetched fixture, including matches filtered out of the strategy view. `data_full.json` mirrors that full set. `data_filtered.json` is only a presentation subset.
- The actionable V4 count is `BET_GIVING + BET_RECEIVING` from the selected date summary. Grade C/NO_BET rows and rows with no selected side are not actionable bets, even if they remain in the filtered JSON for auditability. V3 uses the same distinction between computed and bettable.
- Historical results must remain queryable by competition and date. The current-day HTML summary and the collapsed historical panel must come from the same validated payload; HTML must not silently replace missing history with an empty fetch result.

## Stable ledger contract

- Use a deterministic `match_id`; if the source does not provide one, derive it from normalized `list_date + kickoff + home_team + away_team`. Normalize whitespace, punctuation, and timezone before hashing.
- Merge incoming rows with `pd.concat`, then de-duplicate on `match_id`. Never use `concat([new_df, locked_df], keep="first")`: incoming rows can hide locked rows and existing rows can disappear when a source returns a partial roster.
- Preserve locked pre-match fields for rows whose state is `已开赛` or `已结算`: opening/current handicap, water, candidate label, decision, model values, and the original source snapshot. Only score, settlement state, result tag, PnL, and verified settlement metadata may be updated after lock.
- Keep a `frozen_actionable`/`history_key` marker and an update timestamp so a later run can prove which fields were immutable. Existing rows absent from the incoming roster stay in the ledger; absence is not deletion.
- Write Excel atomically: write to a sibling temporary `.xlsx`, close the writer, validate the temporary workbook and sheet names, then replace the target. Do not rebuild all formatting or other sheets on every run; preserve the workbook structure whenever possible.

## Score backfill and settlement

- Backfill final scores for every finished V3/V4 actionable match, including dates before the current run. Use a verified result source (Titan007 or another configured result source), cache the raw response, and record source/time. Never infer `0-0` from a blank result, PnL, or a missing page.
- Treat postponed, cancelled, abandoned, and genuinely unresolvable matches as explicit non-settled states. Do not include them in win-rate or ROI denominators.
- Freeze the pre-match selected side and signed handicap before calculating settlement. Normalize direction exactly once: source home handicap positive means home gives; negative means home receives. Store `selected_side`, `selected_handicap_signed`, and the normalized giving/receiving team together.
- Recompute settlement and 1U PnL from the verified score and frozen line. Keep one canonical mapping for W/HW/P/HL/L and use it in Excel, JSON, HTML, and historical summaries. A settlement/PnL combination that cannot be explained by the frozen line is a data-contract failure.

## Three-way reconciliation before publish

Compare the same `match_id` set and key fields across: (1) Excel ledger, (2) date/full and filtered JSON, and (3) rendered HTML data. At minimum compare competition, teams, kickoff, signed line, selected side, score, settlement, PnL, and actionable flag. Fail the build when Excel has a settled score that JSON or HTML drops, when HTML shows a different handicap direction, or when the displayed BET count differs from `BET_GIVING + BET_RECEIVING`.

Run a count-shrink guard by competition and date. If the incoming roster falls below the previous verified roster without an explicit cancellation/postponement record, log `ROW_COUNT_SHRINK_WARNING`, keep the previous ledger rows, and do not overwrite the full view. A filtered V4 count falling from 11 to 6 can be valid when the date or BET definition changed; a full-roster loss is not.

## HTML and GitHub delivery

- Render current data from the date JSON and keep historical details collapsed behind an explicit control. Include the selected `?date=YYYY-MM-DD` URL in notifications.
- Preserve the V4 controls: date, current bettable filter, historical league-rate filter, competition, final decision, and grade. A missing control is a failed build.
- Validate the local file, raw GitHub file, and GitHub Pages response after publish. Use cache-busting query strings only for verification; do not create duplicate data files.
- The morning workflow runs at `0 23 * * *` (07:00 Asia/Shanghai) for the current list date. A separate evening workflow runs at `0 12 * * *` (20:00 Asia/Shanghai) and always passes the next Beijing calendar date to the updater. Both run on a self-hosted Windows runner because the production fetcher and ledgers live under `D:\codex`; check those paths before the update and fail with a clear message if they are unavailable.
- Keep the Feishu webhook only in the GitHub Actions secret `FEISHU_WEBHOOK_URL`. Send a result message after both success and failure, including list date, run id, roster, V3/V4 computed and actionable counts, shrink-guard status, history row count, and the dated HTML link. Never write the webhook into source, generated JSON, or logs.

## Failure policy

Retry transient fetches with bounded backoff and preserve the last verified snapshot. When a score or handicap remains unverified, mark the exact field as missing/data-gate failure and keep the row non-actionable; never fabricate a score, line, water, or settlement merely to increase the count. Do not publish until the three-way reconciliation and count-shrink guard pass.
