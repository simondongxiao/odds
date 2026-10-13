# V4 Ledger Integrity Audit

- generated_at: 2026-10-13T22:46:29.144947+08:00
- V4_logic_change_at: 2026-10-04T09:52:00+08:00
- code_hash: `f4973b49f305b6ee76b6d1e5564e8032681ec8b8867a487f01c2bac95f71faaa`
- evaluated_rows: 25
- frozen_historical_files: 17
- historical_write_policy: Frozen Historical Decisions；本次运行不读取赛果生成赛前字段，不回写过去日期。
- missing field counts: 0

历史行若当时从未生成某字段，保持 `HISTORICAL_FIELD_UNAVAILABLE`；禁止用赛果倒推补值。
