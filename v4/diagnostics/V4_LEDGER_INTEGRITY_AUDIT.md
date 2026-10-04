# V4 Ledger Integrity Audit

- generated_at: 2026-10-04T09:06:58.080315+08:00
- V4_logic_change_at: 2026-10-04T08:30:00+08:00
- code_hash: `4c4b9c6308b2567be6ef2aeb478eb8d26296d9866e456942ae1ecb693caeb529`
- evaluated_rows: 223
- frozen_historical_files: 17
- historical_write_policy: Frozen Historical Decisions；本次运行不读取赛果生成赛前字段，不回写过去日期。
- missing field counts: 0

历史行若当时从未生成某字段，保持 `HISTORICAL_FIELD_UNAVAILABLE`；禁止用赛果倒推补值。
