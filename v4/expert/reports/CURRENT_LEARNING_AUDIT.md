# CURRENT_LEARNING_AUDIT

生成时间：2026-09-23T22:11:44.944162+08:00

## 当前学习链

- 目标：固定 1U 亚洲盘净收益；未把 ABC 当作执行门槛或特征。
- E0：按方向、盘口深度、水位和原 V4 版本做层级收缩历史基线。
- E1：只用赛前可得的原 V4 信号和盘口字段做正则化净收益回归。
- E2：只在至少两个真实、早于原决策时点的快照存在时启用；两点样本标记 `TWO_POINT_ONLY`。
- E3：当前缺少独立、带 available_at 的赛况数据，状态为 `UNAVAILABLE`，未填充虚假中性值。
- Meta：仅用扩展窗口 OOS 的 E0/E1 输出训练，当前不使用无足够历史支持的 E2/E3。

## 当前状态

- 模型：`V4_EXPERT_FILTER_R1_70f0d3a60d78`
- 训练截止：`2026-09-23T20:27:55.514003+08:00`
- 训练行数：302
- 基础专家 OOS 行数：85
- Meta 嵌套 OOS 行数：11
- Meta 嵌套 OOS RMSE：0.885
- 校准状态：`UNCALIBRATED_EXPECTED_PNL_REGRESSION`
- 效力状态：`EFFICACY_UNPROVEN`

## 泄漏防线

`feature_available_at <= historical_decision_at`、`result_available_at <= training_cutoff`、`training_cutoff < evaluated_decision_at` 均在数据筛选、OOS 构造和前瞻推断中显式检查。结果、PnL、ID 和 ABC 等审计字段不进入特征。
