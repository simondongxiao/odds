# V4 核心原地升级报告

## 结论

- 唯一正式名称：`V4`。
- 状态：`SHADOW ONLY`，`real_money=false`，所有 BET 固定 `1U`。
- 逻辑生效时间：`2026-09-30T16:18:06+08:00`。
- code hash：`08ec395656ff724eb628f65b12c5f2b710b592bf6000f278896c1903957ed053`。
- 概率状态：`UNCALIBRATED_SHADOW`；尚未把开发样本包装成独立校准结果。
- Forward 状态：`FROZEN_FORWARD`。

## 旧逻辑根因

旧 V4 的正式链路先调用 `derive_market_intent`，再由 `map_intent` 中的 `INTENT_TO_SIDE` 将 Intent 映射为 `candidate_side`，最后仅对该候选方向生成正式结果。盘口桶 posterior 又使同盘口大量比赛共享近似五状态概率。因此，方向虽不一定以 `if line == 1.0` 的字面形式硬编码，但存在与硬映射等价的“Intent → Side”命令链；1 球盘偏受让、1.5 球盘偏让球是该映射与桶先验共同造成的结构性集中。

正式 V4 已移除这条方向命令链：`map_intent` 只返回市场解释，不再返回让球或受让指令。

## 新 V4 决策链

1. 盘口桶只提供经过收缩的弱 prior。
2. 以去水 1X2、主客关系、盘口路径、价格、Domain、League Level 和可用比赛信息生成比赛级净胜球分布。
3. 由同一净胜球分布分别映射让球方与受让方的 W/HW/P/HL/L；整数盘 Push 和四分之一盘拆分均按亚洲盘规则处理。
4. 独立计算 `EV_giving` 与 `EV_receiving`。
5. 将 Data Quality、Market Quality 和缺失项转化为不确定性与门槛；不直接命令方向。
6. 某侧优势超过 EV 与双边差值门槛才输出 `BET_GIVING` 或 `BET_RECEIVING`，否则 `NO_BET`。
7. Expert 只评估 Edge 可靠度；只要比赛身份、双边盘口、水位与欧赔齐全即可进入 CORE。缺少 Public Pull、伤停、首发或轮换不会直接变成 UNAVAILABLE。

## Pull / Fair Line / Domain

- Football Pull：去水 1X2 为高覆盖核心，Elo、状态、伤停、首发、轮换与战意有真实数据时加入；没有则保留 `MISSING`。
- Public Pull：无可靠输入时为 `MISSING`，不按球队名或名气猜测。
- 先生成 `fair_goal_margin` 与 `fair_handicap`，再计算 `Market Line - Fair Line`。
- 联赛通过 `league_level_map.csv` 和标准化映射分层；低级联赛没有硬禁投。
- 杯赛/国家队 Domain 独立进入不确定性体系；赛制、总比分与轮换缺失时为 `MISSING`，没有 `if cup: NO_BET`。

## 冻结完整性

- 2026-09-13 至 2026-09-29 共 17 个历史 V4 日文件 SHA-256 与升级前完全一致，变更数为 0。
- 2026-09-30 升级时已开赛/已有赛前决策的 18 行继续保留旧 `model_id/model_version`、方向、概率、EV、ABCN 和决策时间；新版不回刷。
- 新版账本完整性审计的缺失必填字段计数为 0；NO BET 不要求伪造 selected 字段。
- 历史表现表只读既有比分、结算与 PnL，不写回任何历史赛前字段。

## 当日 Forward 起点

- 总赛事：306；页面 computed：82（含升级前已冻结旧行）。
- 升级后完整比赛级计算：74 场。
- 新 V4：`BET_GIVING 10`、`BET_RECEIVING 5`、`NO_BET 59`。
- Expert CORE 可评估率：100%。
- 页面总览仍会保留升级前冻结行，因此顶部总计为让球 12、受让 5、NO BET 59。

## 自动测试与监控

- 27 项测试全部通过，包括：1 球盘可产生三种结果、1.5 球不锁死让球、强度/水位敏感性、双边 EV、NO BET、概率和、整数 Push、四分之一盘、Domain、未来信息隔离、固定 1U、ABC 不改仓位、可重复推断。
- `V4_DIRECTION_MECHANICAL_AUDIT.md`：方向集中只报警，不自动反选。
- `probability_diversity.csv`：监控同盘口概率重复率与方差，不加随机噪声。
- `V4_PULL_LAYER_AUDIT.md/.csv`：审计 Pull、Fair Line 与 Quality。
- `league_level_performance.csv`：只读冻结历史结算，并列展示当前覆盖。

旧 V4.1、V4.2 和 Match-Specific 独立公开入口保留兼容跳转，但不再作为运行版本；均跳转至唯一正式 `/odds/v4/`。
