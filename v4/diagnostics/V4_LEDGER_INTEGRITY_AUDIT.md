# V4 Ledger Integrity Audit

- generated_at: 2026-10-09T09:01:21.127001+08:00
- V4_logic_change_at: 2026-10-04T09:52:00+08:00
- code_hash: `efcc993e2c60d81e22b3224da4dff2a87a2767f062b303f842d4e0afe5d90aa0`
- evaluated_rows: 372
- frozen_historical_files: 17
- historical_write_policy: Frozen Historical Decisions；本次运行不读取赛果生成赛前字段，不回写过去日期。
- missing field counts: 0

历史行若当时从未生成某字段，保持 `HISTORICAL_FIELD_UNAVAILABLE`；禁止用赛果倒推补值。
