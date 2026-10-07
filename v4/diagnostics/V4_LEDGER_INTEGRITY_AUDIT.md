# V4 Ledger Integrity Audit

- generated_at: 2026-10-07T11:57:07.074743+08:00
- V4_logic_change_at: 2026-10-04T09:52:00+08:00
- code_hash: `69fb84c45660cb77f08d938251afdbb94424071b1b697b566b12c027b0e0f39f`
- evaluated_rows: 170
- frozen_historical_files: 17
- historical_write_policy: Frozen Historical Decisions；本次运行不读取赛果生成赛前字段，不回写过去日期。
- missing field counts: 0

历史行若当时从未生成某字段，保持 `HISTORICAL_FIELD_UNAVAILABLE`；禁止用赛果倒推补值。
