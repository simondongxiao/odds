# V3 / V4 严格日更审计：2026-09-14

- 生成时间：2026-09-14 08:32:19（北京时间）
- 规则口径：V3 Legacy Production；V4 Independent Forward Shadow，`real_money=false`
- 历史不可变：2026-09-13 已冻结的方向、球队、盘口、水位、概率和仓位未重算；本轮仅检查赛果回填。

## V3 Legacy Production

| 项目 | 数量 |
|---|---:|
| Titan 原始快照行 | 939 |
| list_date 锁定 roster | 189 |
| Legacy 决策成功 | 66 |
| 可投 | 5 |
| 半仓可投 | 0 |
| 不投 | 61 |
| 决策缺口 | 123 |

V3 当前决策来自 `v3_legacy_decision_engine.py` 的旧页面决策链，并已写入不可变 freeze 与 bridge；页面只读取冻结结果，不再依赖浏览器临时重算。

## V4 Independent Shadow

| 项目 | 数量 |
|---|---:|
| Raw roster | 189 |
| prior 训练样本 | 78 |
| posterior / EV 真实计算 | 78 |
| A Shadow | 0 |
| B Shadow | 2 |
| C | 17 |
| N | 59 |
| Neutral | 12 |
| Missing | 99 |
| 非赛前 | 0 |
| Error | 0 |

V4 使用当日独立盘口输入、当日 prior、模型版本 `v4-market-dirichlet-20260913`；页面与数据均标注 Shadow，不改变 V3。

## 昨日赛果回填状态：2026-09-13

- 页面中可恢复的冻结记录：192 场；其中冻结可投/半仓：0 场。
- 当前本地已有明确终场来源的记录：0 场；现有 190 场标为“赛果待核”。
- 现有 `score` 分布摘要：{'-': 192}。
- 已检查来源包含 Titan 赛前快照、历史结算/冻结账本及现有页面快照；赛前默认 `0-0` 不作为终场比分。
- 因没有可靠的9月13日90分钟终场源，本轮不写入红/红半/走/黑半/黑和 PnL，待下一次可信比分源到位后 append-only 回填。

## 发布前结论

- V3/V4 页面数据分离：通过。
- 当日 V3 可投数字来自 Legacy freeze/bridge：通过。
- 当日 V4 A/B/C/N 来自 `2026-09-14` Shadow 输出：通过。
- 历史方向漂移：未发生。
- 9月13日赛果完整结算：待可信终场源，不宣称已完成。
