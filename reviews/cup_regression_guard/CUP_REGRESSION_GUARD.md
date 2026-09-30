# CUP_REGRESSION_GUARD

状态：`PASS_WITH_FORWARD_MONITORING`

- 历史冻结哈希：通过（67/67 未变化）。
- 一刀切杯赛禁投扫描：未发现 `if cup: NO_BET` 等按赛事名直接否决路径。
- Competition 仅作为赛事域、微观区域及贝叶斯层级特征。
- Coverage Retention 重放：所有具有冻结可投样本的杯赛均保留 100%；欧冠 1/1、欧联 3/3、英联杯 1/1。
- 样本警告：上述优质资产样本很小，不能把 100% retention 解释成未来胜率保证。
- 非洲杯：当前可核冻结可投样本不足，系统不会伪造局部劣势，也不会按杯名自动禁投；未来由 L1/L2 Forward 样本逐步形成后验。
- 触发规则：单赛事冻结可投样本不少于 5 且 Coverage Retention 低于 70% 时输出 `COVERAGE_RETENTION_WARNING`，阻止升级为默认规则并要求人工审计；不会自动反选或强行恢复配额。

机器可读结果：

- `v3_cup_baseline_20260930_153959.json/csv`
- `v3_cup_coverage_retention_20260930_155020.json/csv`
