# V3/V4 最近五个已完成 Titan007 列表日冻结名单盈亏

生成时间：2026-09-25T11:41:37.265853+08:00

口径：按 Titan007 `list_date` 取 2026-09-20 至 2026-09-24；分母为当日冻结可投名单，V4 仅 Shadow 纸面记录，不代表真实下注。历史赛前字段未重算。

|列表日|版本|冻结可投|已结算|待核|红|红半|走|黑半|黑|有效胜率|1U PnL|ROI|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|2026-09-20|V3 Production|39|39|0|11|5|1|2|20|39.13%|-8.8250U|-22.63%|
|2026-09-20|V4 Shadow|67|67|0|34|6|3|3|21|62.18%|+15.5350U|+23.19%|
|2026-09-21|V3 Production|3|3|0|1|1|0|0|1|60.00%|+0.3200U|+10.67%|
|2026-09-21|V4 Shadow|12|12|0|2|0|1|1|8|19.05%|-6.6100U|-55.08%|
|2026-09-22|V3 Production|4|4|0|2|0|0|1|1|57.14%|+0.1400U|+3.50%|
|2026-09-22|V4 Shadow|7|7|0|6|0|1|0|0|100.00%|+5.8800U|+84.00%|
|2026-09-23|V3 Production|17|17|0|5|0|1|1|10|32.26%|-6.4500U|-37.94%|
|2026-09-23|V4 Shadow|24|24|0|7|0|4|3|10|37.84%|-4.5300U|-18.88%|
|2026-09-24|V3 Production|7|7|0|1|0|0|1|5|15.38%|-4.7500U|-67.86%|
|2026-09-24|V4 Shadow|13|13|0|7|1|0|1|4|62.50%|+3.0950U|+23.81%|

## 逐日结果源

- `2026-09-20: D:\codex\outputs\football_odds_trader\reviews\daily_performance\yesterday_performance_2026-09-20_20260925_113859.csv`
- `2026-09-21: D:\codex\outputs\football_odds_trader\reviews\daily_performance\yesterday_performance_2026-09-21_20260925_113859.csv`
- `2026-09-22: D:\codex\outputs\football_odds_trader\reviews\daily_performance\yesterday_performance_2026-09-22_20260925_113859.csv`
- `2026-09-23: D:\codex\outputs\football_odds_trader\reviews\daily_performance\yesterday_performance_2026-09-23_20260925_113859.csv`
- `2026-09-24: D:\codex\outputs\football_odds_trader\reviews\daily_performance\yesterday_performance_2026-09-24_20260925_113900.csv`

## 结算约束

- 只更新比分、状态、结算标签、PnL、来源和结算时间；V3/V4 原始方向、球队、盘口、水位、概率、V4 ABCN 等级和决策时间保持冻结。
- 结果无法由最新 Titan 终场快照覆盖的比赛，使用显式记录的独立可靠赛果源，并在逐场 CSV 的 `result_source` 留痕。
