# Titan Football Database Schema

共享底座为 `D:\codex\data\football_titan\titan_football.db`。V3 与 V4 只读取同一 `feature_store_snapshots` 快照。

数据链：`Titan public source -> raw_ingest -> normalized master/history -> AS-OF feature store -> FFL/CMFL -> V3/V4`。

核心表：`competition_master`、`season_master`、`team_master`、`player_master`、`fixture_master`、`competition_rules`、`standings_history`、`team_match_history`、`team_strength_history`、`schedule_history`、`cup_match_state`、`market_snapshots`、`fair_line_snapshots`、`market_interpretation_snapshots`。

所有实体同时保留 Titan ID（可得时）和稳定内部 ID；别名以 JSON 保存。不可获得的球员、首发、伤停、赛程距离、多公司深度均为 `NULL`，不以 0 代替。

`raw_ingest` 保存来源、URL、抓取时间、生效时间、解析器版本、SHA-256 和原始文件引用。原始文件不改写。
