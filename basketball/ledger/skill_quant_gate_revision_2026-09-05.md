# Basketball skill quant-gate revision - 2026-09-05

Backup: `D:\codex\outputs\basketball_odds_trader\backups\skill_quant_gate_backup_20260905_141358.zip`

Changed files:

- `D:\codex\skills\basketball-odds-trader\SKILL.md`
- `D:\codex\skills\basketball-odds-trader\references\model.md`
- `D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py`
- `D:\codex\skills\basketball-odds-trader\agents\openai.yaml`
- `D:\codex\skills\basketball-odds-trader\assets\dashboard_template.html`
- `D:\codex\outputs\basketball_odds_trader\dashboard\index.html`

New mandatory rules:

- Standard 1.91 price uses breakeven near 52.38%.
- No spread/total action unless conservative `p_low >= 55%`.
- No action unless `p_low * decimal_odds > 1.025`.
- No build queue unless selected-side `Line-Pred` gap clears `K = 2.5-4.0` points.
- Line-move triggers must be inside the final 2 hours; moves more than 5 hours out are ignored as probing.
- Final-hour line volatility above 5 points triggers SKIP/不可投.
- Final steam movement must align with model direction.
- Real stake uses strict `1/4 Kelly`; any failed hard gate forces `Kelly=0`.

Verification:

- `python -m py_compile D:\codex\skills\basketball-odds-trader\scripts\basketball_market_snapshot.py`
- `quant-gate` pass example returned `可投-主单`.
- `quant-gate` fail example returned `不可投` with p_low/K/fuse/steam blockers.
- Dashboard script parsed and rendered with quant fields visible in the execution panel.

