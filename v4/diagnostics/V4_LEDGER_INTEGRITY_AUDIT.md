# V4 Ledger Integrity Audit

- generated_at: 2026-10-14T09:38:17.107504+08:00
- V4_logic_change_at: 2026-10-04T09:52:00+08:00
- code_hash: `7710ba183823a7439ad48d5880ff16489e017dfb669401ffd9bd04df9bc4623c`
- evaluated_rows: 20
- frozen_historical_files: 17
- historical_write_policy: Frozen Historical Decisions；本次运行不读取赛果生成赛前字段，不回写过去日期。
- missing field counts: 0

历史行若当时从未生成某字段，保持 `HISTORICAL_FIELD_UNAVAILABLE`；禁止用赛果倒推补值。
