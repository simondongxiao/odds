# V4 主场效应与重复计权审计

| 文件 | 函数/字段 | 结论 |
|---|---|---|
| `D:\codex\football_titan_data\core.py` | `_replay_elo::expected` | 已移除固定 +55 主场项；team strength 不再内置主场奖励 |
| `D:\codex\football_titan_data\core.py` | `fundamental_fair_line::venue_effect` | 仅使用 competition×season residual venue effect，并向 country/global 收缩 |
| `D:\codex\v4\core_model.py` | `evaluate_match::shared_ffl` | FFL/CMFL 已明确是 home-space；giving/receiving 只转换一次 |
| `D:\codex\v4\core_model.py` | `evaluate_match::shared_consensus` | CMFL 不再追加 home bonus；市场 1X2/OU 仅进入 CMFL 分布 |
| `D:\codex\v4\core_model.py` | `venue_effect` | neutral/unknown venue=0；不默认完整主场优势 |
| `D:\codex\v4\run_daily_v4.py` | `selected_side`/quality gate | home/away 使用同一 EV、gap、quality gate；无人工配额 |

主场效应只在共享 FFL 的 venue residual 中进入一次；主客比例由输入与盘口自然决定。
