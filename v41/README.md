# V4.1_R1 Shadow — CHALLENGER

**SHADOW ONLY · NOT FOR PRODUCTION · real_money=false**

V3 remains sole production. Original `D:\codex\v4` and its website/history remain unchanged. This directory is independent and failures cannot prevent the original V4 workflow.

## Run

From `D:\codex`, with Python dependencies `numpy scipy pyyaml requests pytest`:

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m v41.runner tick --list-date 2026-09-19
python -m v41.runner verify
python -m pytest v41/tests -q --basetemp=D:/codex/v41/tests/tmp
python v41/scripts/forward_tick.py
```

`forward_tick.py` collects current Titan list date and earlier list dates with pending frozen matches. It does not retrain, publish original pages, or place bets. Since execution policy `V41_EXEC_4H_R2_20260920`, a match enters the primary freeze window at T-4h and the first valid manual run in `(T-4h, kickoff)` freezes A/B/C. Historical T-30 freezes remain immutable. V4.1 remains manual-only; no scheduler is created.

## Architecture

Snapshot → allowlisted as-of features → masked multinomial match probabilities → independent validation temperature calibration → unified direction → calibrated EV + date-cluster uncertainty → multi-gate grade → immutable paired freeze → isolated HTML → append-only outcome comparison.

Model coefficients, train/validation dates, calibration and thresholds are locked. Historical test is evaluated once, not optimized. Model B is a train-only bucket prior. Match-specific Model A uses the bucket prior as an offset, not its final prediction. Intent is an explanatory covariate, never a side lookup.

## Important current limitation

Train 1,688, validation 450, locked test 1,008. The probability model remains the locked R1 artifact. The execution policy is now independently versioned: strict A/B/C uses all-prematch calibration-cell support, while any otherwise valid directional freeze that misses strict gates is forced into C under the user's observation rule. Forced C keeps `strict_grade=N` and the failed gates visible. This is **data collection / research readiness**, not evidence of improved trading performance.

The locked test currently does **not** beat the bucket baseline. Calibration reduces raw-model overconfidence, but does not prove good calibration or profitable EV. See `diagnostics/V41_BUILD_REPORT.md`.

## Data contracts

- `quote_at`: actual local price observation; `provider_quote_at=null` because the source has no reliable per-tick clock. No invented OPEN timestamp.
- `list_date`: official Titan roster identity; kickoff natural date is separate.
- Titan positive home line means home giving; selected giving handicap is negative. Receiving reverses the same five-state distribution exactly.
- Effective cover probability is `(W + 0.5*HW)/(W+0.5*HW+L+0.5*HL)`, excluding push; it is not literal probability of a full win.
- Unavailable Elo/form/multi-book dispersion/neutral venue remain MISSING. Required-feature and all-feature completeness are separately reported.
- Historical research sample is one actual prematch observation per match, nearest T-30 without pretending outside-window observations are T-30. First persisted confirmed-final observation is conservative `result_available_at`.
- Control source is an exact-byte frozen V4 copy, run in a redirected sandbox. CONTROL probabilities retain the original historical methodology, including its known limitations. The paired table does not rewrite or claim equivalence to the original page's earlier daily picks.
- Decisions are exclusive-create immutable JSON. Results are separate immutable observations/events. A conflicting score becomes pending, not a silent correction of recommendations.
- Comparison is 1u per ABC candidate, settled-stake ROI, with pending count explicit. N has zero actual stake and optional hypothetical unit outcome. Maximum drawdown orders completed matches by kickoff, not an invented cashflow order.

## Files

Configs: `config/`; immutable model: `models/V4.1_R1.json`; calibration: `calibration/TEMP_R1.json`; raw/snapshot/provenance: `data/`, `snapshots/`, `features/`; original baseline: `data/control_baseline/`; isolated CONTROL runs: `control_runs/`; immutable picks: `decisions/<list_date>/<match_id>.json`; independent outcomes: `forward/results/`; comparison: `forward/forward_comparison.csv`; delivery: `dashboard/`; audit: `diagnostics/`.

Never promote automatically. A minimum 200 ABC and preferably 500+, multiple weekends/leagues/times and both sides, are necessary observation conditions, not sufficient proof of superiority.
