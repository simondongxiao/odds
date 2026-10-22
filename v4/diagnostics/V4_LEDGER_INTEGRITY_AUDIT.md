# V4 Ledger Integrity Audit

- generated_at: 2026-10-22T22:16:10.401066+08:00
- V4_logic_change_at: 2026-10-22T22:15:00+08:00
- code_hash: `2481e4fb88f7e006ab9393d9f35da0afcb5c8fb10421f160a9ed814a4b6296c0`
- evaluated_rows: 68
- frozen_historical_files: 17
- historical_write_policy: Frozen Historical Decisions；本次运行不读取赛果生成赛前字段，不回写过去日期。
- missing field counts: 0

历史行若当时从未生成某字段，保持 `HISTORICAL_FIELD_UNAVAILABLE`；禁止用赛果倒推补值。
