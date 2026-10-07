# 诱阻与价格抵抗审计

- 当前 V4 `hard_direction_rule`：未设置为方向命令；共享快照的市场诊断逐行保留 `hard_direction_rule=false`。
- `market_interpretation` 是 `PRICE_OBSERVATION`、`UNKNOWN` 或 `MIXED_EVIDENCE` 等观察状态，不是投注方向。
- V4 方向由同一比赛级净胜球分布分别映射让球方/受让方五状态，再用对应水位计算 `ev_giving` 与 `ev_receiving`。
- `bucket_prior` 只留下收缩样本与小幅 margin nudge；没有 `1球 -> 下盘` 或 `1.5球 -> 上盘` 分支。
- 真实资金、净持仓、庄家赔付压力仍不能从公开 Titan 聚合报价识别。

## 当前方向矩阵摘要

`handicap_direction_matrix.csv` 已按盘口档位 × Domain 生成。100% 集中只触发复核，不自动反选；概率多样性仍由真实欧赔、FFL/市场参考、盘口、水位、赛事域和不确定性产生。
