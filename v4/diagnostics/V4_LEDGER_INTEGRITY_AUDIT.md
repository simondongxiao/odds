# V4 Ledger Integrity Audit

- generated_at: 2026-10-20T21:35:34.160825+08:00
- V4_logic_change_at: 2026-10-04T09:52:00+08:00
- code_hash: `36982d9ae8f9b4aeb6e42df6719e98d026e5ecfc8ad4073cde181b26e25ec5d5`
- evaluated_rows: 84
- frozen_historical_files: 17
- historical_write_policy: Frozen Historical Decisions；本次运行不读取赛果生成赛前字段，不回写过去日期。
- missing field counts: 0

历史行若当时从未生成某字段，保持 `HISTORICAL_FIELD_UNAVAILABLE`；禁止用赛果倒推补值。
