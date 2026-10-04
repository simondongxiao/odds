# 小比赛证据规则

小比赛不再等待 P2 资料全部齐全才进入价格评估。当前顺序是：

1. 先确认比赛、球队、开赛时间、结算范围、亚盘和双边水位；
2. 有多少 Titan 近期赛果、主客场、赛事域、级别、休息和赛制就用多少；
3. FFL 有充分 AS-OF 支持才使用，否则标 `MISSING_OPTIONAL`；
4. 盘口路径只有一个报价时写 `STATIC_QUOTE`，只有初盘与本轮时写 `TWO_POINT_OBSERVATION`，不虚构中间阶段；
5. 先比较两侧 1U 结算状态和 EV，再决定 BET_GIVING、BET_RECEIVING 或 NO_BET；
6. UNKNOWN/MIXED_EVIDENCE 只说明解释无法识别，不自动等于 NO_BET。

公众拉力仅保存排名差、主场、近期表现等可观测代理，字段明确为 `PROXY_ONLY`；没有同场、同市场、同时间的真实成交数据时，`real_flow=MISSING`，不会写成资金占比或庄家持仓。
