# V4 Ledger Integrity Audit

- generated_at: 2026-10-07T12:00:01.212718+08:00
- V4_logic_change_at: 2026-10-04T09:52:00+08:00
- code_hash: `6577f7e7e6feb8af2a0389b0570e04c8e14c1c91fc227456be84f785dc288e90`
- evaluated_rows: 170
- frozen_historical_files: 17
- historical_write_policy: Frozen Historical Decisions；本次运行不读取赛果生成赛前字段，不回写过去日期。
- missing field counts: 0

历史行若当时从未生成某字段，保持 `HISTORICAL_FIELD_UNAVAILABLE`；禁止用赛果倒推补值。
