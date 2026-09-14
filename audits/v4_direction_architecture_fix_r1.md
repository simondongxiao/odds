# V4 Direction Architecture Fix R1

- old model: `V4_GIVING_LEGACY`; new model: `V4_DIRECTION_FIXED_R1`.
- scope: structural direction repair only; no ABC/kappa/Kelly/weekend/league tuning.

## Root cause

1. `v4/run_daily_v4.py:parse_market` used European favorite to choose the team and forced `selected_handicap_signed=-abs(raw_line)`. This erased Titan signed-side identity.
2. The same function hard-coded `selected_side=giving`, so receiving intents could not create receiving candidates.
3. The prior was trained only as a giving-side alpha table and was reused for the selected row; the fixed version mirrors one market outcome into receiving space rather than duplicating the match.
4. Titan identity is now: raw home AH > 0 => home gives; raw home AH < 0 => away gives; PK is neutral.

## Blind replay direction

- old strict-blind directional baseline: 483; giving 483; receiving 0 (legacy report baseline).
- new strict-blind rows 2026-09-07..14: 246; giving 210; receiving 36.
- mapping parity: 246/246 = 100.0%.
- historical prediction file is prematch-only and hashed separately; no result/settlement/PnL is used to create this direction output.

## Current-day canary

- current list date: 2026-09-14; evaluated/frozen: 72; giving 32; receiving 40; neutral 30.
- A/B/C/N: Counter({'N': 53, 'C': 18, 'B': 1}).
- sampled giving: 10; sampled receiving: 10; team/water parity sample: PASS.

## Status

- `real_money=false`; V4 remains Shadow/Research only.
- V3 Production and its history are untouched.
- Old giving-only artifacts remain under `v4/legacy_giving_only/` and are not overwritten by this report.
