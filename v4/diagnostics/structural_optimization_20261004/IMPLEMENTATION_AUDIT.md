# 实施审计（原地 V3/V4）

- 审计时间：`2026-10-04T10:08:16.215570+08:00`
- 逻辑变更时间：`2026-10-04T09:52:00+08:00`
- 正式运行入口：现有 V3 Legacy Production、现有 V4 Shadow；没有新增版本入口。
- 回滚备份：`D:\codex\outputs\football_odds_trader\backups\structural_audit_pre_change_20261004_094815`

## 旧门槛核查

| 项目 | 实际文件/函数 | 调整 |
|---|---|---|
| FFL | `football_titan_data/core.py::fundamental_fair_line` | 样本不足返回 `UNAVAILABLE_OPTIONAL`；V4 转走市场参考路径，不再因 FFL 缺失整场不可用 |
| H1-H4 | `football_titan_data/core.py::_market_diagnostic` | H1/H3/H4 可为 NULL；单一聚合报价不再冒充流动性或真实资金证据 |
| V4 盘口桶 | `v4/core_model.py::evaluate_match` | 仅作收缩 prior margin nudge；最终仍由比赛级分布、双边 EV 和不确定性决定 |
| Intent | `v4/direction_contract.py`、V3 页面旧漏斗 | 解释字段；不存在 `intent -> side` 的直接映射 |
| 可评估性 | `v4/run_daily_v4.py` | FFL、首发、伤停、T-30、真实资金流等均为可选证据，不再统一写成 UNAVAILABLE |
| V3 旧漏斗 | `v3_legacy/dashboard/index.html::frameworkDecision` | 保留正式 V3 历史兼容规则；核心阻断仍只限盘口/必要价格/历史条件统计/风控，不新增 FFL 必答题 |

## 当前真实漏斗（V4）

- 总行数：`899`；状态：`{'NEUTRAL': 41, 'EVALUATED': 223, 'NOT_PREMATCH': 635}`
- 最终决策：`{'NO_BET': 125, 'BET_RECEIVING': 68, 'BET_GIVING': 71, 'UNAVAILABLE': 635}`
- 模型支持：`{'MARKET_REFERENCE_FALLBACK': 223}`
- 解释状态：`{'PRICE_OBSERVATION': 219, 'MIXED_EVIDENCE': 4}`
- 当前数据层：`{'status': 'PASS', 'odds_age_hours': 1.289, 'max_age_hours': 12.0, 'last_team_update': '2026-10-04T08:49:19+08:00', 'last_standings_update': '2026-10-04T08:49:19+08:00', 'last_schedule_update': '2026-10-04T08:49:19+08:00', 'last_odds_update': '2026-10-04T08:49:19+08:00'}`
- 当前共享快照：`slate_raw_5496ac532a49_asof_20261004_100640`

重点：`NOT_PREMATCH` 表示已开赛/不再生成新赛前判断，不等于缺少基本面；`MISSING_DATA` 才表示核心市场输入不足；`NO_BET` 是完成价格评估后的结论。
