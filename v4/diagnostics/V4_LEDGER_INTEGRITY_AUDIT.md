# V4 Ledger Integrity Audit

- generated_at: 2026-10-23T07:45:56.312695+08:00
- V4_logic_change_at: 2026-10-22T22:15:00+08:00
- code_hash: `a47b5f5039a2b9030ef291bebc6617f4057c68428376cbdecb43f5add0049333`
- evaluated_rows: 175
- frozen_historical_files: 17
- historical_write_policy: Frozen Historical Decisions；本次运行不读取赛果生成赛前字段，不回写过去日期。
- missing field counts: 0

历史行若当时从未生成某字段，保持 `HISTORICAL_FIELD_UNAVAILABLE`；禁止用赛果倒推补值。
