# V4 主场特征 A/B（样本外诊断）

- A：正式冻结流程的逐场概率；B：同一输入将 venue residual 置零的中性场地反事实。
- 该 A/B 不改变正式阈值、不增加主场奖励、不做主客配额；仅量化 venue residual 对概率的贡献。
- 可做反事实的行数：56；venue delta 达到 5 个百分点的行数：0。
- 正式模型没有独立的 market-home bonus；1X2/OU CMFL 仅作为市场条件参考，不再次追加主场项。
- 训练截止和冻结边界遵守 `V4_logic_change_at`；历史冻结行不回写。
