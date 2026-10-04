# 数据覆盖与模型支持

- Titan roster：`899`
- 共享快照：`slate_raw_5496ac532a49_asof_20261004_100640`
- 新鲜度：`{'status': 'PASS', 'odds_age_hours': 1.289, 'max_age_hours': 12.0, 'last_team_update': '2026-10-04T08:49:19+08:00', 'last_standings_update': '2026-10-04T08:49:19+08:00', 'last_schedule_update': '2026-10-04T08:49:19+08:00', 'last_odds_update': '2026-10-04T08:49:19+08:00'}`
- V4 evaluated：`223`
- V4 CORE evaluable rate：`n/a`
- V4 model support：`{'MARKET_REFERENCE_FALLBACK': 223}`

## 证据覆盖计数

- `asian_market=AVAILABLE`：223
- `asian_market=MISSING`：676
- `cross_book_quotes=MISSING`：223
- `euro_market=AVAILABLE`：223
- `euro_market=MISSING`：676
- `ffl=MISSING_OPTIONAL`：899
- `identity=AVAILABLE`：899
- `kickoff=AVAILABLE`：899
- `market_path=TWO_POINT_OBSERVATION`：223
- `real_flow=MISSING`：899
- `team_history=SPARSE_OR_MISSING`：223

缺失分层：P0 身份/时间/必要盘口；P1 报价路径和历史背景；P2 详细阵容、伤停、公众成交和 FFL。P2 缺失不覆盖 P0/P1，也不伪造为正常值。
