# V4 Ledger Integrity Audit

- generated_at: 2026-10-05T08:49:13.042891+08:00
- V4_logic_change_at: 2026-10-04T09:52:00+08:00
- code_hash: `789c012f4ad6a78389460c3f9e3a243462cb55e4f0ceeebc179ec0f8bbec6503`
- evaluated_rows: 0
- frozen_historical_files: 17
- historical_write_policy: Frozen Historical Decisions；本次运行不读取赛果生成赛前字段，不回写过去日期。
- missing field counts: 0

历史行若当时从未生成某字段，保持 `HISTORICAL_FIELD_UNAVAILABLE`；禁止用赛果倒推补值。
