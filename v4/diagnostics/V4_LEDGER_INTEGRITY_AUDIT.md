# V4 Ledger Integrity Audit

- generated_at: 2026-10-13T23:44:31.781868+08:00
- V4_logic_change_at: 2026-10-04T09:52:00+08:00
- code_hash: `04568073b34c6a4cb33f988702aa823014bd0183b09390b96d01484ccf938e5f`
- evaluated_rows: 25
- frozen_historical_files: 17
- historical_write_policy: Frozen Historical Decisions；本次运行不读取赛果生成赛前字段，不回写过去日期。
- missing field counts: 0

历史行若当时从未生成某字段，保持 `HISTORICAL_FIELD_UNAVAILABLE`；禁止用赛果倒推补值。
