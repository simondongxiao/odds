# Titan007 历史基础库

需要补充球队历史、阵容或 Box Score 时使用本参考。

## 数据链

1. 球队搜索：`/cn/aspx/Search_Team.aspx?str1=<球队名>`，解析联赛、简体/繁体/英文别名与 TeamID；只接受规范化后唯一精确别名匹配。站内联想接口返回空响应时不得据此判定球队不存在。
2. 球队身份与当前阵容：`/jsData/teamInfo/teamDetail/td<TeamID>.js`。
3. 按年赛程：`/cn/Team/TeamScheAjax.aspx?TeamID=<TeamID>&y=<YYYY>`。
4. 分节比分：`/cn/Tech/TechTxtLive.aspx?matchid=<MatchID>`。
5. Box Score：`/jsData/tech/<首位>/<第2-3位>/<MatchID>.js`。
6. 完整联赛成员：NBA 使用当前赛季 `LeagueRank` 资产（排除 TeamInfo 中的附加赛占位队）；WNBA 使用 `TeamInfo`；EuroLeague 使用当前赛季 `CupMatch` 资产，因为其 `TeamInfo` 可能合法返回空 `arrTeam`。

正常 HTTP 使用 `curl_cffi` 的 Chrome 兼容握手，因为该站点会中断普通客户端连接；这不是验证码、登录、付费墙或访问控制绕过。最多 6 线程、有限超时；网络异常、429、5xx 或空响应按 2/4/8 秒指数退避，默认 4 次且总尝试数只能配置在 3–5 次。

## 存储与隔离

- 数据库：`D:\codex\outputs\basketball_odds_trader\reference_data\titan007_history\titan007_history.sqlite`
- 原文：同目录 `raw\YYYYMMDD\`，以响应哈希命名且不可变。
- 最新审计：`latest_audit.json`。
- 完整球队清单：`foundation_manifest.json`，列出当前 NBA、WNBA、EuroLeague 的 TeamID、中英文名称、阵容人数和已保存技术统计场次。
- 球队身份、阵容、赛程、分节比分和 Box Score 属于事实库。
- `letGoal`、`bigSmall`、HandicapDetail、OuHandicapDetail 属于市场历史，只能进入独立市场审计；禁止作为独立公平价模型输入。
- 本库没有 PnL、ROI、CLV 或正式/Provisional 账本表，不能写入或重算既有首写记录。

核心事实表：

- `league_team_membership`：按联赛、赛季保存现役球队；历史占位项只降为 `active=0`，不伪装成现役球队。
- `team_game_stat`：每队每场的 FGM/FGA、3PM/3PA、FTM/FTA、ORB/DRB、助攻、失误、得分和 Level B 回合数等源事实。
- `team_season_stat`：单次内存遍历聚合的赛季/阶段统计，避免逐队重复读取 JSON；NBA/WNBA 明确分成 `REGULAR_SEASON`、`POSTSEASON`、`PRESEASON`，`ALL_PHASES_AUDIT_ONLY` 仅供审计，不得直接混入同阶段模型。

## 更新策略

首次使用 `build_titan007_history_db.py --foundation-leagues NBA,WNBA,EUROLEAGUE --all-league-boxscores` 对三大联赛完整球队和两年比赛回填；以后日更仍只对当天赛事球队增量刷新，并对每队最近 10 场已完赛比赛抓取分节与 Box Score。所有事实仍必须通过 `alias -> competition -> cutoff -> valid -> usable`；数据库存在不等于可用。

Level B Pace 只在同场双方都有数值型 `FGA/FTA/ORB/TOV` 时计算：`FGA + 0.44 × FTA - ORB + TOV`。任何字段缺失时降级，不抛异常。

## 每日市场比较链

每日不是先看盘口再拟合模型，而是先保存盘口事实，再让资料库模型盲算理论价：

1. 保存开盘/当前盘口不可变快照；
2. 按双方 TeamID 抓取并更新截止前历史、分节与 Box Score；
3. 从 `team_game_stat` 一次查询同联赛、同阶段最近窗口，形成双方 Pace、进攻 PPP、防守 PPP、三分与罚球画像；
4. 历史完成后再次刷新盘口，避免长时间抓取造成比较报价过期；
5. 冻结不含市场输入的比分 Champion 和技术统计 Challenger；
6. 与同场、同市场、同结算规则的最新盘口比较 Edge、概率和 EV。

技术 Challenger 缺少每队 8 场或 3 个不同对手时仍可保留研究理论价，但不得据此升级纸面门禁。让分技术价当前是中立场分差，`home_adjustment=null`；没有独立校准前不得补写固定主场优势。市场盘路、历史赢盘率和大小球盘路不得进入理论价。

## v4 Feature Store

Feature Store 仍位于同一 `titan007_history.sqlite`，不复制原始库。新增事实和派生域：

- `player`、`player_game_boxscore`、`player_season_stat`：保存Titan技术页的球员ID、首发、分钟、投篮、三分、罚球、篮板、助攻、犯规、抢断、失误、盖帽、得分和正负值；缺失保持空值。
- `period_score`、`team_game_feature`：保存分节及球队单场Pace、攻防效率、Four Factors、犯规/罚球环境和对手盘前强度。异常场次不删除原始事实，只令派生字段不可用。
- `source_capability`：按联赛/赛季/阶段记录A/B/C/D等级、赛程比分、球队Box Score、球员Box Score、分节和市场历史覆盖率。
- `team_state_feature`、`league_environment`、`matchup_feature`：只使用cutoff之前的事实，生成时间衰减状态、ESS、赛程强度、轮换连续性、战术分桶、模型B/C和市场盲算Challenger。
- `pregame_snapshot`：冻结事件、cutoff、模型版本、特征哈希和独立理论价；同一快照ID禁止内容变化。
- `market_history`：保存开盘/当前/终盘的来源事实，但固定 `independent_model_eligible=0`，与独立模型特征隔离。

球队单场回合数为 `FGA + 0.44×FTA - ORB + TOV`，双方均完整且结构合理时才生成game possessions。NBA按48分钟、其他联赛按40分钟归一。对手强度必须按比赛时间顺序先取盘前状态再写当前比赛，Strong/Medium/Weak战术分桶不得使用赛季终值。

独立Challenger固定输出双方理论得分、分差、team1理论让分和理论总分，满足比分恒等式后才可冻结。市场比较发生在冻结之后；若没有前向残差校准、可靠阵容、完整合同或正式历史门槛，概率和EV保持空值，不能用明显价差越过证据门禁。
