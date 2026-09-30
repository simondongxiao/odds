# V3 杯赛重构实施报告

生成时间：2026-09-30 15:55（北京时间）

## 实施结论

- 已在现有 `V3_LEGACY_PRODUCTION` 原地接入 `V3_CUP_MATCH_STATE_R1_20260930`，未新建独立下注系统。
- 生效边界为 `2026-09-30T15:45:00+08:00`。只有生效后生成、且开球时间晚于生效时间的未开赛杯赛可进入新逻辑。
- 历史 67 个 V3 冻结文件的 SHA-256 校验全部保持一致；没有回写历史方向、盘口、水位、概率、结论或决策时间。
- 赛事名称只用于标准化、赛事域与分层统计，不能直接输出 BET / NO_BET。
- 缺失的赛制、总比分、轮换和休息日统一保存为 `MISSING`；缺失本身不会触发 `if cup: NO_BET`。

## 原因审计

旧 V3 的实际链路是：

`盘口升降/水位/欧赔变化 -> asian_intent_candidate -> 历史微观组合 -> 水位阈值 -> 决策`

原页面虽展示过赛制与轮换字段，但这些字段在盘口 Intent 形成后才进入卡片，没有前置参与 Intent。也就是说，旧 V3 不是简单写了 `if cup`，但杯赛状态、晋级效用和轮换证据未真正进入方向形成链路，容易把不同杯赛环境混入同一盘口标签。

新链路为：

`Cup_Match_State_Gateway -> Football Pull / Public Pull / Fair Line -> 盘口Intent校验 -> 四级贝叶斯收缩 -> 原V3价格阈值与风控 -> 冻结`

## 新增字段

- `Competition_Domain`
- `Cup_Match_State`
- `Cup_Aggregate_State`
- `Cup_Qualification_Utility`
- `Cup_Rotation_Risk`
- `Cup_Rest_Days`
- `Cup_Context_Missing`
- `Football_Pull_Score`
- `Public_Pull`
- `fair_goal_margin`
- `fair_handicap`
- `line_gap`
- `Cup_Bayes_Level`
- `Cup_Bayes_Posterior`
- `Cup_Bayes_P10`
- `Cup_Bayes_Weight`
- `Cup_Intent` / `Cup_Raw_Intent` / `Cup_Intent_Reason`
- `cup_regression_guard`

## 四级收缩

严格按以下顺序回退：

1. Exact Competition + Intent + Match State
2. Competition Domain + Intent
3. Micro Region + Intent
4. Global Tag

局部样本只以有限权重收缩原 V3 概率，不直接按赛事名熔断。当前可核的历史杯赛冻结样本只有 30 场，因此最大后验权重限制为 35%，并保留原 V3 价格阈值。非洲杯若没有可核样本会明确显示样本缺失，不伪造“非洲杯应降权”的历史结论。

## Fair Line 说明

当前 `fair_goal_margin` / `fair_handicap` 是基于去水 1X2 与已核比赛状态的未校准代理，状态标记为 `UNCALIBRATED_MARKET_PROXY`，不冒充独立进球模型。`Public_Pull` 没有真实同市场资金证据时为 `MISSING`，不会用豪门名称或主观叙事补值。

## 回归结果

- 修改前基线：`v3_cup_baseline_20260930_153959.*`
- 修改后 Coverage Retention：`v3_cup_coverage_retention_20260930_155020.*`
- 历史冻结不可变：通过。
- 历史可投重放中，欧冠 1/1、欧联 3/3、英联杯 1/1 保留；样本量很小，仅证明本次规则没有机械误杀，不能据此宣称未来收益提升。
- 当前列表日在按 Titan match_id 去重后，修改前后均为 75 场、4 场冻结可投；新规则没有删除或降级既有 V3 可投。原始追加账本曾包含 4 个重复 match_id，现仅在当日展示层去重，历史账本未删除。

## 自动测试

- 新增杯赛测试：9 项全部通过。
- 既有 Cup Rotation Gateway：24 项全部通过。
- 既有 Asian Risk V3：28 项全部通过。
- 既有 Market Move Guard：35 项全部通过。

测试覆盖：无杯名硬禁投、缺失显式化、两回合状态识别、Football/Public Pull 分离、Fair Line 随比赛实力变化、同杯赛可保留或否决不同 Intent、四级回退、上线时间边界、历史冻结哈希不变。

## 限制与后续验证

- 本次不是用近期红黑调参，也没有根据最近非洲杯结果反向改历史方向。
- 历史杯赛状态字段覆盖不足，因此 L1 经常回退到 L2-L4；页面会显示真实层级与样本数。
- 是否改善收益只能由上线后的冻结 Forward 样本验证，不能用已反复分析过的历史区间宣称成功。
