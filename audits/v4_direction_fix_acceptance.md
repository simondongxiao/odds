# V4 Direction Architecture Fix R1 Acceptance

- Status: PASS WITH SHADOW-ONLY QUALIFICATION
- Old version: `V4_GIVING_LEGACY`
- New version: `V4_DIRECTION_FIXED_R1`
- V3 Production: unchanged
- ABC thresholds, kappa, Kelly, weekend and league rules: unchanged
- real_money: `false`

## Root cause and repair

- Old `D:\codex\v4\run_daily_v4.py::parse_market` selected a team from the European favorite and forced `-abs(raw_line)`, then fixed `candidate_side` to `giving`.
- This prevented receiving intents from creating receiving candidates and made the old output a giving-only accidental model.
- `D:\codex\v4\direction_contract.py` now uses Titan signed AH only: positive home line means home gives; negative home line means away gives; PK is neutral.
- Candidate team and water are selected only after authoritative intent mapping. Any mismatch is `SIDE_IDENTITY_ERROR` and cannot be graded.
- Receiving prior is the exact W/HW/P/HL/L mirror of one market outcome; the same match is never duplicated as two training observations.

## Parity and canary

- Mapping tests: 8/8 passed, including three receiving intents, three giving intents, neutral, unknown, Titan sign, water identity and mirror transformation.
- Historical fixed blind replay, 2026-09-07 through 2026-09-14: 246 directional rows; 210 giving; 36 receiving.
- Historical legacy baseline: 483 giving; 0 receiving.
- Historical team/water identity parity: 246/246 = 100%.
- Current 2026-09-14 V4 computed/frozen rows: 72; giving 32; receiving 40; neutral 30.
- Current grades: A 0; B 1; C 18; N 53.
- Current sampled canary: 10 giving and 10 receiving; team/water parity PASS.
- Two-side diagnostic: 144 rows, 72 giving plus 72 receiving; no identity error.

## Tests and publish

- Full test suite: 116 passed, 1 skipped.
- Public commit: `03424e9`.
- V4 page: https://simondongxiao.github.io/odds/v4/?v=03424e9
- V3 page remains separate and was not modified by the direction engine.

## Rollback

Restore the pre-fix V4 files from `D:\codex\v4\legacy_giving_only\` or the pre-fix backup `D:\codex\_backups\football_v3_v4_upgrade_rerun_20260914_2145\v4\`. Do not delete the fixed artifacts; they are versioned separately.
