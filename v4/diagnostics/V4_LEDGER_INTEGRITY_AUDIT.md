# V4 Ledger Integrity Audit

- generated_at: 2026-10-22T21:26:49.519213+08:00
- V4_logic_change_at: 2026-10-04T09:52:00+08:00
- code_hash: `8000fb33dad858ccbd2378d79a101cbb21099f2c28c00341252e1a0712a04563`
- evaluated_rows: 68
- frozen_historical_files: 17
- historical_write_policy: Frozen Historical Decisions；本次运行不读取赛果生成赛前字段，不回写过去日期。
- missing field counts: 0

历史行若当时从未生成某字段，保持 `HISTORICAL_FIELD_UNAVAILABLE`；禁止用赛果倒推补值。
