# FORWARD_TEST_PLAN

1. 每次人工执行先完成原 V4 冻结，再运行 `python -m v4_expert.cli update --list-date YYYY-MM-DD`。
2. 只在原 V4 A/B/C 候选、同方向、同盘口/水位、报价仍处于可验证新鲜度且比赛未开赛时产生 `BET/NO_BET`。
3. 所有 `BET` 固定 1U；同一原始 decision_id 与模型版本只冻结一次；修订追加新 decision_id，不覆盖旧记录。
4. 赛后只镜像赛果、比分、状态、结算时间和 PnL；赛前字段不可变。
5. 每日检查四视图对账、重复 stake、时间泄漏、价格路径覆盖和数据版本变化。
6. 默认累计至少 7 个新列表日且 100 场新已结算唯一比赛后，只提示可以训练 Challenger；不得自动训练或晋级。

当前重训检查：新已结算 0 场、0 个列表日；是否到期：False。
