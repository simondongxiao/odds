# FORWARD_TEST_PLAN_R2

1. 每个新列表日只使用该列表日前、且在最早赛前决策时点前已可得的结算样本冻结 Forward 模型。
2. 同列表日新结算结果不得进入后续比赛的 R2 模型或仓位。
3. 所有 SELECTED 固定纸面 1U；REJECTED 固定 0U但继续记录原方向反事实 PnL。
4. CORE 覆盖目标 >=95%；E2/E3 缺失只降级能力层，不改变为 UNAVAILABLE。
5. 分 CORE/MARKET/FULL 独立累计样本、校准与排序；校准不足时只显示 raw score、rank 和 Shadow 结论。
6. 至少积累多个全新列表日与足够 FROZEN FORWARD 样本后，再评估可靠性、校准和晋级；晋级必须人工批准。
