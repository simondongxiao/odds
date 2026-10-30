# V4 Ledger Integrity Audit

- generated_at: 2026-10-30T22:42:59.445489+08:00
- V4_logic_change_at: 2026-10-22T22:15:00+08:00
- code_hash: `db56570e25076f02ba314e3348b9dfdba673690ed536707836cd45a6dabc0a8f`
- evaluated_rows: 241
- frozen_historical_files: 17
- historical_write_policy: Frozen Historical Decisions；本次运行不读取赛果生成赛前字段，不回写过去日期。
- missing field counts: 0

历史行若当时从未生成某字段，保持 `HISTORICAL_FIELD_UNAVAILABLE`；禁止用赛果倒推补值。
