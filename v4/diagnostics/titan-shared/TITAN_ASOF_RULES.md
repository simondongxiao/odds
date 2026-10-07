# Titan AS-OF Rules

1. 任一特征必须满足 `feature_available_at <= decision_at`。
2. 赛果进入训练历史前必须满足 `result_available_at <= training_cutoff`。
3. 排名以抓取时间为可用时间，不能把后来排名回填给过去决策。
4. 同一比赛的所有快照按 `match_id` 分区，Train/Validation/Test/Forward 不得拆分到不同区间。
5. 收盘盘只用于事后 benchmark，不能进入早盘 FFL、CMFL 或决策特征。
6. 历史冻结决策不回刷；新版诊断只能写独立 snapshot/report。
7. 缺失字段保持 `NULL/MISSING`，并通过不确定性与 CORE/MARKET/FULL 层降级。
