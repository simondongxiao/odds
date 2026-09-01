# Football Odds Trader Data Structure

This file defines the stable local data contract for future daily updates and dashboard rendering.

## Core Rule

All generated data must stay under `D:\codex\outputs\football_odds_trader\` and must be UTF-8 with BOM for CSV files that contain Chinese headers.

Past pre-match fields are immutable after kickoff. Settlement jobs may append scores, status, PnL, source, and review notes only.

## Daily Simulation Ledger

Path pattern:

`D:\codex\outputs\football_odds_trader\ledger\YYYY-MM-DD_titan007_simulations.csv`

Required columns:

`日期, 赛事, 比赛, 模拟ID, 赛制阶段, 市场框架, 模拟盘口/价格, 模拟方向, 虚拟仓位单位, 基本面拉力, 盘口倾向, Polymarket/交易所情绪, 流动性, 模拟目的, 是否主单, 赛果, 模拟盈亏单位, 过程评级, 错误类型, 模型更新`

## Asian Intent History Detail

Path pattern:

`D:\codex\outputs\football_odds_trader\ledger\asian_intent_history_detail_YYYY-MM-DD_YYYY-MM-DD.csv`

Required columns:

`日期, 赛事, 比赛分类, 比赛, 赛果, 比分来源, 模拟ID, 市场框架, 即时亚盘, 盘口线, 盘口档位, 上盘方, 候选标签, 候选依据, 候选映射方向, 意图水位, 意图结算, 意图盈亏单位, 意图均注盈亏, 反向方向, 反向水位, 反向结算, 反向盈亏单位, 反向均注盈亏, 有真实投注量, Polymarket/交易所情绪, 流动性`

## Micro-Region Tag Edge

Path pattern:

`D:\codex\outputs\football_odds_trader\ledger\micro_region_tag_edge_YYYY-MM-DD.csv`

Required columns and order:

`统计日期, 数据起始日, 数据截止日, 微观板块, 候选标签, 样本数, 正向红, 正向红半, 正向走水, 正向黑半, 正向黑, 正向有效胜率, 正向负率, 正向均注盈亏, 反向红, 反向红半, 反向走水, 反向黑半, 反向黑, 反向有效胜率, 反向负率, 反向均注盈亏, 标签总样本, 标签正向胜率, 标签正向盈亏, 标签反向胜率, 标签反向盈亏, 微观优先方向, 标签优先方向, 贝叶斯综合胜率, 盈亏平衡胜率, 安全垫, 通过阈值, 同盘口否决, 风控状态, 建议动作`

Micro-region buckets:

- `北美系列`: United States and Canada.
- `南美系列`: Brazil, Argentina, Chile, Ecuador, Uruguay, Colombia, Paraguay, Bolivia, Peru, Venezuela, and South American continental cups.
- `日韩系列`: Japan and Korea.
- `西亚/中亚系列`: Kuwait, Kazakhstan, Qatar, UAE, Saudi Arabia, Oman, Uzbekistan, and AFC markets.
- `欧洲五大系列`: England, Spain, Italy, Germany, France.
- `欧洲非五大系列`: other European senior leagues and cups.
- `其他系列`: unmapped official senior competitions; observation only until classified.

## Micro-Region Risk State

Path pattern:

`D:\codex\outputs\football_odds_trader\ledger\micro_region_risk_state_YYYY-MM-DD.csv`

Required columns:

`统计日期, 微观板块, 昨日样本, 昨日ROI, 连续负ROI天数, 近期累积亏损场, 风控状态, 仓位系数, 说明`

Risk states:

- `状态A-正常态`: standard stake.
- `状态B-预警/降半仓`: half stake.
- `状态C-熔断/静默观望`: observe only.
- `状态D-复活机制`: restored to normal after a positive ROI settlement day.

## Dashboard Red EV Box

The red EV box must remain compact. It should show:

`亚盘意图历史EV：标签...；标签整体...；微观板块...；结论...；正期望方...；不投原因...`

Full reasoning must be hidden behind an expandable control named `查看1-4步测算`.
