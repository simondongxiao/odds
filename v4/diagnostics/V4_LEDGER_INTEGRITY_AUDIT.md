# V4 Ledger Integrity Audit

- generated_at: 2026-10-01T08:41:51.357903+08:00
- V4_logic_change_at: 2026-09-30T16:18:06+08:00
- code_hash: `08ec395656ff724eb628f65b12c5f2b710b592bf6000f278896c1903957ed053`
- evaluated_rows: 0
- frozen_historical_files: 17
- historical_write_policy: Frozen Historical Decisions；本次运行不读取赛果生成赛前字段，不回写过去日期。
- missing field counts: 0

历史行若当时从未生成某字段，保持 `HISTORICAL_FIELD_UNAVAILABLE`；禁止用赛果倒推补值。
