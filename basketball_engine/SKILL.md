---
name: basketball-odds-trader
description: 篮球数据核验、Source-Agnostic Evidence、Titan007 Feature Store、真实比分与球员/球队技术统计独立定价、盘口比较和纸面模拟。v4.4固定“先盘口、再双方资料库、再刷新盘口比较Edge”的生产顺序，采用联赛均值锚定的滚动OOS攻防效率与MatchupAdj，分离Fair Center与Game Outcome不确定性并输出W/P/L、Probability Edge、EV与市场信息风险；将NBA/CBA Spread伤停、轮换和Net Rating改为Adjustment/Uncertainty层；统一多源历史证据合同与Titan独立Provisional账本；不允许真实下注，不把工程测试当作策略有效性。
---
# 篮球研究与纸面模拟 v4.12

## v4.12 日期滚动与日本 B 联赛历史续接修复

7M 的日历文件在北京时间午夜后会滚到下一日。早间任务必须先读取
`gh-pages/dashboard_v2/data/{target_date}.json` 的已发布赛事身份，再将缺失的
7M 赛事放回本轮 detail/history 采集队列；只能续接赛事身份和赛果历史，禁止续接
盘口报价。这样“库存保留”和“历史可定价”不会被拆成两个互相矛盾的结果。

赛事页的“日本男子B联赛甲级联赛”和球队历史页的 `日B1`/`日B2`/`日B3` 必须归入同一
`JAPAN_BLEAGUE` family key；联赛分级保留在原始字段中，不能因展示简称不同把球队历史
判为 `COMPETITION_MISMATCH`。当前板没有真实报价时仍只输出 `NO_MARKET`/观察，不能用
历史盘口或默认赔率填充；历史别名修复后，若盘口稍后出现，应在下一次 05:00/20:00
刷新中直接进入正常定价链。

## v4.9 全局实体注册、时段感知盘口与性能合同

球队身份统一读取 `D:\codex\config\canonical_entity_registry.json`，解析实现统一使用
`D:\codex\odds_shared\canonical_entities.py`。Titan007、7M、ESPN、SofaScore 的源生队名、
简称、赞助商名、繁简体和英文名只能通过精确注册别名或精确来源 ID 转成
`canonical_team_id`；禁止把源生字符串直接作为跨源历史或盘口匹配键，也禁止用编辑距离
强行合并。赛事连续性使用有序的 canonical 主客队组合和开赛时间 ±5 分钟窗口。来源主客
顺序颠倒时，让分符号与两侧价格必须同步换向，并保留转换审计，不能产生相反结论。

所有正常公开 HTTP 采集统一使用 `D:\codex\odds_shared\http_retry.py`，网络异常、429、
5xx 或空响应按 `2s -> 4s -> 8s` 指数退避，默认最多 4 次且只能配置为 3–5 次；每次尝试的
URL、状态码、异常、耗时和下次等待时间必须写入 source health。没有放盘的赛事保留在库存，
标记 `NO_MARKET` 与 `UNPRICEABLE`，并使用 `market_ttl_seconds`、`next_market_retry_at` 和
`inventory_retained=true` 表达时段感知重查计划。

每次运行只允许把历史、Box Score、赛程基线各读取一次并建立内存索引。逐场定价使用
`repair_v22.history_index.HistoryIndex`，不得循环扫描整份历史或重新读取源文件。SQLite 高频
查询必须命中 team/competition/season/match_kind/tip、canonical event/cutoff 等复合索引；
非核心诊断导出默认只在内容签名变化时重写。任何性能优化都不得改变不可变账本、Evidence
Gate、阈值、真实资金关闭状态或既有业务输出契约。

## v4.7 赛事连续性与全球赛程身份修复

全球赛程发现源（ESPN、SofaScore、FIBA 等）新增赛事必须生成稳定的
`team1_id` / `team2_id`（优先使用来源球队 ID，缺失时使用来源命名空间下的
规范化球队身份）。来源没有当前盘口时，赛事仍须保留为 `NO_MARKET` 或
`UNPRICEABLE`，不得因盘口缺失或身份字段缺失从事件清单删除，也不得让逐场
定价循环因 `team1_id` 缺失中断。实时刷新继续使用当天追加事件库存；部分源
异常时保留此前已捕获的同日赛事，并明确标注当前源未观察到，不伪造报价或升级
为手动实盘候选。

NBA/WNBA 的季前标签是阶段变化，不是新的联赛身份。生产分类必须保留
NBA/WNBA 联赛身份，并由 `PRESEASON` 不确定性层处理历史降权和残差放大；
不能因为标签从 NBA 变成 NBA季前就丢失上一阶段的球队历史。跨阶段历史借用
仍须经过球队身份、性别、截止时间、终场状态、原始证据和正式 8 场/3 对手门槛。
来源重发赛事 ID 时，首写手动实盘记录按双方球队和开赛时间连续匹配保留；
后续刷新只追加当前快照和复核状态，不得把原有候选从默认视图删除。
同一场比赛在 7M、Titan007 或阶段性赛程源之间重发不同赛事 ID 时，日内赛事库存
必须用“双方球队组合 + 开赛时间”做连续性键，不能只按 provider event ID 去重；
已有首写预测、盘口和红黑不可覆盖，缺少当前盘口只标记 `NO_MARKET` / `UNPRICEABLE`。
连续性键必须优先使用主队名的规范化身份，并通过已审核的中英文/赞助商别名统一
跨源球队；不能让 Titan 的英文 alias 把同一队与 7M 的中文主名拆成两个键。
同一队对、同一开赛时间的 7M/Titan/全球发现镜像必须在源合并层确定一个 canonical
赛事，所有盘口、技术上下文和来源审计重定向到该赛事；页面层不得用 CSS 或过滤器
掩盖重复记录。
盘口方向必须同时绑定“当前 canonical 主客顺序”和“统一让分符号”：页面左侧球队让分统一显示为负号，受让统一显示为正号；Titan 的 `goal` 正值代表左侧球队让分，进入模型前必须反号，7M 则按 `hadFlag` 转成同一口径。不同源若对同一场给出相反方向，必须先完成赛事身份与球队顺序归一，再保留原始报价用于审计，不能把两个方向当成两场赛事展示。
历史补回只能引用不可变的原始抓取、事件库存和首写决定文件，标记为历史恢复或跨源别名，
不得用事后盘口新建下注、重复计入纸面盈亏或把恢复记录升级为新的手动实盘候选。

## v4.8 跨源历史归档连续性

当目标赛事由 Titan007 主导、而同一球队的可审计历史此前由 7M 抓取时，
不得因为本轮 provider 变化把球队视为新球队或直接返回历史不足。生产采集在
当前批次历史之后，必须按“精确规范化队名 + competition_key + gender”从最近的
不可变 `raw/repair_v22/*/capture.json` 归档批次增量补回历史，再执行同一套
`cutoff -> FINAL -> valid score -> dedup -> usable` 过滤。仅允许唯一映射；
模糊队名、多候选联赛或性别不一致一律不桥接。7M 原始 TeamID 必须保留在
`team*_legacy_id` 和跨源审计中，Titan canonical ID 才能进入当前目标的统一历史池。

归档复用只能恢复已存在的赛果证据，不能恢复盘口、创建新的下注、修改历史首写
或重复计入盈亏。每轮必须输出归档批次数、匹配行数、未来/未完赛拒绝数、去重数、
跨源重写数和最终每队场次/ESS。归档窗口固定为最近 3 个运行日；若 10/8 等较早
批次已经包含完整球队历史，优先复用该批次，禁止无界扫描全部旧 JSON 造成每日
更新性能退化。桥接后仍按原有 8 场/3 对手、Evidence、盘口完整性、Edge 和手动
实盘门槛判断，不得因历史恢复而降低任何正式门槛。

## 唯一生产入口

```powershell
python D:\codex\skills\basketball-odds-trader\scripts\run_basketball_daily.py --live --backtest-recent 6 --publish-beta --push
```

实际调用链：`repair_v22.cli -> pipeline.execute -> source.collect_live -> model.price_event（逐场） -> 冻结输入/预测 -> model.decide -> 不可变决定/结算 -> 逐日JSON/中文页面`。
禁止恢复旧 runner 中写死的 `coupled=[]`、`enrichment=False`、零定价漏斗。禁止再执行 `run_step5rf2.py`；其中153分与排名差定价已被证明不具备真实输入链，只能保留为旧版错误审计。

## 执行与访问

本版本真实资金执行恒为关闭。公开源采集只用正常HTTP，最多6线程、有限超时；不绕过验证码/付费/登录/访问控制。不能取到数据时保存具体URL、错误、原文路径，不把HTTP200、输出文件存在或测试数当成数据成功。

7M真实页面/数据先进入原始快照，每个响应分别记录请求/接收时间、哈希与来源。页面里的明确链接才可用于进一步取身份和球队 `n_history.js`。同一批下载不是原子市场快照，不要声称文件绝对同时产生。

### Titan007 全日赛程与盘口源（v3.8）

用户指定的公开页面 `https://lq3.titan007.com/nba.htm` 是生产链的补充赛程与盘口源，不能只把它当作人工参考。正常HTTP采集使用页面实际调用的公开接口：

- `https://lq3.titan007.com/NBA/today2.xml?t=<epoch_ms>`：当天赛程、联赛、球队、北京时间和状态；按目标北京时间日期过滤后，所有行必须保留为事件。
- `https://lq3.titan007.com/NBA/nbaGoal{1,2,3,8,9}.xml?t=<epoch_ms>`：各公开公司的当前让分与大小分快照。`goal`是带符号的team1让分，正数表示team1受让；大小分字段分别是总分、 大分水位、小分水位。正香港盘水位转十进制为`1 + water`。
- 页面明确链接的 `https://nba.titan007.com/analysis/{source_event_id}.htm` 可用于逐场分析页；已有7M详情页和球队历史链路仍是互补证据，不得用截图或搜索摘要替代原始比分。

Titan007当前盘口XML没有逐报价的最后变动时间，也没有在该接口中独立声明全场加时结算规则。因此：原始让分/大小分必须保存并在Dashboard显示为`MARKET_FOUND`，但只有在现有同场、同市场、同规则、时间新鲜和证据门禁全部满足时才可升级；不能把当前板抓到直接写成可纸面执行。缺少某一公司报价不删除赛事，写入`NO_CURRENT_BOARD_QUOTE`及具体source_event_id；不能再把“某接口没有报价”泛化为“数据抓取不到”。

对本轮实时请求实际返回、原文和哈希已保存、`current_board_contract_verified=true`、状态为`OPEN`且比赛尚未开始的当前挂牌，`received_at`是“本轮仍挂牌确认时间”，可作为独立的时效依据。即使来源没有发布逐盘口`source_quote_at`，也不得仅因此写入`QUOTE_TIME_UNKNOWN`、`STALE_QUOTE`或把赛事排除；应保留`source_quote_at=null`、标记`source_timestamp_semantics=CURRENT_BOARD_CAPTURE_ONLY`和`freshness_basis=VERIFIED_CURRENT_BOARD_CAPTURE`，严禁伪造最后变动时间。若不是本轮已验证当前板、状态非OPEN、接收时间超出TTL或比赛已经开始，则仍按原规则阻塞。

Titan007、7M、ESPN、SofaScore的赛程/盘口/历史能力必须分源记录健康状态、原始快照、请求时间、接收时间、哈希、解析条数和失败原因。Titan007新源只有在当天实际解析到目标日事件、球队和盘口字段后才能标记`PRODUCTION_VERIFIED`；历史统计仍按截止时间和同赛事过滤，不能用最终赛果倒推盘前数据。

### Titan007 历史基础库与增量链（v3.12）

球队资料页不是人工截图源。生产补全使用其公开球队搜索、`teamDetail`、`TeamScheAjax`、比赛技术页和 `jsData/tech`，首次建立两年基础库，后续只刷新当天比赛球队及最近已完赛比赛。具体接口、数据库和隔离边界见 [references/titan007_history_database.md](references/titan007_history_database.md)。普通客户端被站点中断时可使用已安装 `curl_cffi` 的 Chrome 兼容 TLS 握手；仍是正常公开 HTTP，最多 6 线程、有限超时，并按 v4.9 的 2/4/8 秒指数退避执行 3–5 次有界尝试，不绕过验证码、登录、付费或访问控制。

每次抓取必须保存不可变原文、URL、北京时间/UTC抓取时间、SHA-256、TeamID/MatchID和解析状态。球队搜索只接受唯一精确别名匹配；模糊或多候选保持未映射。赛程历史必须经过 `raw -> alias -> competition -> cutoff -> valid -> usable`，且只允许截止前已完赛、分节总和与最终比分一致的行进入模型历史。基础库存在不等于门禁通过，正式 8 场/3 对手阈值不变。

Box Score 的 Level B 只使用同场双方完整 `FGA/FTA/ORB/TOV`，按 `FGA + 0.44 × FTA - ORB + TOV` 分别复算后取 game pace estimate；字段缺失、非数值或异常必须降级。球队页的让分盘路、大小盘路、赢盘率和市场统计必须留在独立市场历史域，禁止成为独立公平价输入。该基础库不得包含 PnL/ROI/CLV 或写入正式、Provisional、Research 账本。

完整基础库必须按源内联赛成员表保存 NBA、WNBA、EuroLeague 全部现役球队：NBA 只接受当前赛季 LeagueRank 的 30 支真实球队，排除 TeamInfo 中“附加赛胜者/败者”等占位实体；WNBA 保存当前赛季 15 队；EuroLeague 在 TeamInfo 为空时改用当前 CupMatch 资产的 20 队。逐场技术统计写入独立事实表，赛季聚合必须分离常规赛、季后赛和季前赛；跨阶段总计只能标为 `ALL_PHASES_AUDIT_ONLY`，不得偷渡进同阶段定价。

### 市场优先、资料库独立定价与利润点比较（v3.13）

每次实时更新固定采用：`盘口开盘快照 -> 新球体育/Titan007双方历史与技术统计 -> 临比较盘口刷新 -> 独立理论价冻结 -> 同场同规则Edge/EV比较`。盘口先抓是为了保存真实可交易参照，不代表盘口可以进入理论价；历史和技术定价上下文必须保存 `market_inputs_used=false`，模型输入不得含盘口、盘路、赢盘率或大小分历史。

双方资料库最少提取同联赛、同阶段、截止时间前的最近比赛及 FGA、FTA、ORB、TOV、3PA、3PM、PTS、对手、比赛时间和来源快照。Level B 回合数只用完整公式；技术总分 Challenger 使用 `ExpectedPossessions × (ExpectedPPP_team1 + ExpectedPPP_team2)`，技术分差仅保存为无主场修正的中立场 Challenger。正式让分仍以现有对手校正比分模型为 Champion，未经独立前向校准不得用技术 Challenger 覆盖 Champion 或硬编码主场分。

比较阶段必须同时展示理论让分、理论总分、当前盘口、方向差值、概率、EV、证据状态和阻塞原因。所谓“利润点”仅指同场、同市场、同结算规则、新鲜真实盘口相对冻结独立理论价存在正 Edge；它不是盈利保证。只有原有历史、对手数、阵容、伤停、规则、市场完整性、Evidence、Edge 与执行门槛全部通过时才能进入正式纸面层；其余只能是 Research、Provisional、Lean 或不可投。真实资金执行继续永久关闭。

### Titan007 Feature Store 与市场盲算定价（v4.0）

Feature Store 必须复用既有 `titan007_history.sqlite`，不得另建篮球系统。原始快照继续不可变；标准化事实、派生特征、来源能力和赛前快照分别写入独立表。球队市场盘路、历史让分/大小分和当前盘口只进入 `market_history`，其 `independent_model_eligible=0`，严禁进入独立理论价特征。

来源能力按联赛与赛季实际交集分级，不按HTTP成功或文件存在推断：A=完整赛程比分+有效球队Box Score+球员Box Score；B=球队Box Score足以形成Pace/Four Factors但球员层不完整；C=仅部分球队/场次技术统计；D=只有赛程比分。每次更新都刷新 `source_capability`，Dashboard和审计必须显示能力等级、覆盖率和缺口。

Titan `tech` 的球员27字段必须落库：球员ID、中英文名、位置、首发、分钟、投篮/三分/罚球命中与出手、前后场篮板、篮板、助攻、犯规、抢断、失误、盖帽、得分、正负值、号码和图片。缺字段保持 `null`；不得由球队总计反推球员数据。赛季聚合按联赛、赛季和阶段隔离。

球队单场特征只在同场双方有完整 `FGA/FTA/ORB/TOV` 时派生：`Possessions = FGA + 0.44×FTA - ORB + TOV`；NBA按48分钟、其他联赛按40分钟标准化Pace，并保留加时分钟。结构异常场次只保留原始事实，派生值置空。派生项包括 ORtg、DRtg、NetRtg、攻防 eFG%、TOV%、ORB%、FTr、每百回合犯规与对手罚球率、分节状态。

对手强度只能用当场开赛前数据按时间顺序生成，先读取对手当时的NetRtg与联赛环境，再加入当前比赛；禁止全季终值回填过去。当前状态使用60日半衰期与ESS，记录赛程强度、比赛间隔、近窗趋势、风格向量和球员分钟所形成的轮换连续性。Strong/Medium/Weak对手分桶由盘前对手强度确定，每桶两侧至少3场才启用战术模型，并以 `n/(n+5)` 向基础模型收缩。

联赛环境允许使用当前赛季和上一赛季截止前数据，以180日半衰期估计Pace、效率、总分和主场优势；主场优势至少20个有效主场样本。没有逐回合或经验证估计器时，末节犯规溢价必须为 `null`，不可硬编码。

模型分层：A为现有Champion，不被Feature Store自动替换；B为Pace×对手校正攻防效率；C为战术分桶模型；D为球员预期分钟模型，仅在伤停和预计轮换有可靠盘前时间戳时启用。Challenger默认B 65%+C 35%，C不可用时B为100%；未经独立前向校准不得替换Champion或单独触发正式Paper。

冻结输出必须满足：`ExpectedTotal = ExpectedScore1 + ExpectedScore2`，`ExpectedMargin = ExpectedScore1 - ExpectedScore2`，`FairHandicapTeam1 = -ExpectedMargin`。冻结前模型上下文必须证明 `market_inputs_used=false`；冻结后才允许与同场、同市场、同结算规则的新鲜盘口比较。每个 `pregame_snapshot` 由事件、cutoff、模型版本和payload哈希唯一确定；同ID不同payload必须报 `IMMUTABLE_PREGAME_SNAPSHOT_CONFLICT`，不得覆盖。

修改上述链路后必须运行来源能力、球队/球员Box Score、回合数、Pace、Four Factors、对手强度as-of、战术分桶、未来信息泄漏、让分/总分/比分一致性、市场隔离和终盘泄漏测试。通过测试仅证明工程契约，不证明盈利能力；正式8场/3对手、证据、阵容、盘口和执行门槛不得自动降低。

## 身份、时间与市场

### 全场加时合同：让分与大小分的不同处理

用户确认的全局合同为`INCLUDING_OT`：所有全场让分与大小分的分析、比较和
结算均按全场含加时执行。来源没有单独写出加时规则时，保留
`source_ot_rule=UNKNOWN`作为审计元数据，但不得单独形成`UNKNOWN_OT_RULE`
或拒绝该场；只有来源明确为`REGULATION_ONLY`时，才记录
`OT_POLICY_MISMATCH`并排除与全场合同不可比的报价。

加时对让分仅影响全场结算合同，不能因加时是否发生未知而改变让分方向或阻止
让分进入。加时对大小分必须额外保留双方截止前历史的加时场次、发生率、单次
加时总得分和样本量。总分的独立训练目标若使用全场最终比分，其均值已内含历史
加时贡献，禁止再把`发生率 × 加时得分`机械加到公平总分而造成重复计数；该资料
用于审计、情景解释和总分残差不确定性。若没有可核验的加时明细，只能标记
`OT_HISTORY_UNAVAILABLE`/`OT_HISTORY_THIN_SAMPLE`、扩大总分不确定性，绝不能
单独造成`TOTAL_CONTEXT_INCOMPLETE`、取消方向或拒绝手动实盘候选。身份、真实
盘口、方向、基础回合/攻防数据、严重来源冲突和未来信息泄漏等其它硬门槛仍照常
执行。

7M源ID使用`7m:<id>`，不将会变动的开赛时间作为永久ID。源内ID匹配后还必须检查球队、比赛时间、联赛和冲突；旧2025年赛事不能计成2026年今日比赛。

已取得的7M详情页明确默认GMT+0800。无时区的7M年月日数组据此转换，原文和证据保留；不能附上UTC而将开赛时间推迟8小时。当前日按真实北京时间筛选，已开赛不允许生成盘前记录。

聚合源、公司命名空间和实际公司身份分开。保留每家公司每条盘口的完整数组、两侧水位、时间、主/替代盘、时段。不能将一侧水位复制给另一侧，也不能把所有公司改成4。缺失的原始`.raw`不能靠旧标准化JSON自动变成“已核验真盘”。

盘口解析规则放在`config/repair_market_contracts.json`。没有证据时不要激活示例。确认格式、让分符号、当前开放状态、时段、实际公司结算规则后才可纸面执行。7M是展示源，不能替所有公司制定统一加时规则。未知规则只阻止合同EV/执行，不阻止观察和独立研究定价。

新下载不等于新报价。区分报价变化时间、收到时间、仍挂牌确认时间；只有已验证当前挂牌契约才允许以确认时间刷新稳定盘口。不能仅因事件已绑定就写`quote_age=0`。若来源明确提供`LAST_CHANGE`，仍以该来源时间判断时效，不能用较新的接收时间覆盖一个已明确过期的最后变动时间。

## 数据补全与独立模型

实际解析7M身份脚本里的`a_wf`是交锋资料，不是完整球队最近比赛。必须继续跟随原页面公开的`Basketball_Team_Data/<team>/gb/n_history.js`取得球队历史；该请求成功不等于解析成功，必须输出实际比赛条数。

模型只使用截止前已确认完场的实际比分、对手、同赛事身份；排除当前比赛、未来比赛、异性别、不同competition、冲突比分及过旧资料。分节和半场总分进行一致性校验。无需高级统计就能运行的比分基线单独命名为`SCORE_BASELINE_UNVALIDATED`，不伪造ORtg、Pace、球员评级、阵容或伤停。

独立研究定价使用带时间衰减的对手校正岭回归。总分另做同数据域回归，双方预测得分由同一分差/总分一致拆分。置信度低不等于预测分差乘0.38；不以未知作为“无人受伤”。模型原始输入不得含任何盘口、赢盘率或大小分盘路。

缺高级统计时研究定价最少每队3场同赛事有效历史；这不是投注门槛。纸面模型证据还要求每队至少8场、至少3个不同对手、有真正TEAM_HISTORY流；国家队/高不确定赛事额外要求当前名册核验。该初始政策和Student-t残差参数都是未校准研究先验，不是盈利证明。只有交锋资料的2条离线基线不能升级成纸面可投。

规则与输入不足仍可返回`UNPRICEABLE`，但必须保存实际调用痕迹、解析条数、具体拒绝原因，而不是先写死结果。所有真实市场赛事均应尝试，不仅第一场。

## 概率、执行与不可变账本

采用真正Student-t CDF（标准差与scale不同）；整数盘独立计算赢/走/输。EV为`P(win)*(decimal-1)-P(loss)`；条件于非走水的盈亏平衡为`1/decimal`。胜率不替代让分覆盖率，不使用人为线性每半分+/-固定概率。

比较必须同一场、同市场、同规则。总分不能拿让分倾向代替；共识盘口不能与另书赔率拼接成可成交价格。实际报价无方向/价格/时段/OPEN/OT证据不计算正式EV。保守情景是参数压力测试，不可冒充经验置信区间或已校准概率。

新纸面单还必须经过跨公司主盘完整性检查。对同场、同市场、同全场时段、同加时规则的本轮新鲜主盘，至少两家公司可比时，按`config/market_integrity.json`计算中位数；让分偏离中位数超过4分、总分超过8分的报价标记`PROVIDER_DISAGREEMENT`。该报价及原始`.raw`、时间和双边水位必须完整保留，但不能单独触发纸面单；整场在分歧未由后续新鲜快照消除前只能观察。此规则不修改公平盘口、概率、sigma、Kelly、模型权重、历史首写或已冻结结算。

预测输入与预测结果先独立冻结，再形成比较与决定。采集器可能先看到市场，但独立模型函数输入中不含市场，采用输入哈希与隔离测试证明；禁止仅写一个`market_accessed=false`口号。

同场最多一张已触发的纸面主单；后续checkpoint记录更新观点，不重复下注计数。不改变旧首写。结算单独追加，核对球队顺序、全场/常规时间；没有有效终盘不制造CLV。真钱stake恒为0。

每次实时更新必须新建盘口采集批次，并对所有未开赛的首写纸面单执行“当前盘口复核”：仅以本轮同场、同公司、同市场、同方向、同加时结算规则，且方向与赔率均已核验并未过期的报价运行既有纸面门槛。另一公司、另一盘口或另一方向即使本轮通过，也只能是新的独立观察，不能写作旧纸面单“仍可投”。复核结果仅可为`STILL_QUALIFIES`、`NO_LONGER_QUALIFIES`、`REVALIDATION_UNAVAILABLE`或`EVENT_STARTED`，并记录本轮时间、选择、盘口、赔率和阻塞原因。首写盘口、预测、决定和结算永不被复核覆盖；网页必须同时区分“首写纸面记录”和“本轮复核”。没有新鲜、同规则盘口时只能写“无法复核”，不能使用旧首写盘口说仍可投。

复核必须计算首写与本轮真实报价的盘口差、赔率差，并用`config/execution_lifecycle.json`中的同市场初始限额标记“需要显式复核”；限额不是自动否决。让分必须按被选方向判断：同一受让方由`+6.5`变`+10.5`、或同一让球方由`-6.5`变`-3.5`，均为更有利；受让分变少或让球分变深，均为不利。大小分同理：大分总分下降更有利、上升不利；小分总分上升更有利、下降不利。赔率升高更有利、降低不利。任何大幅变化都必须以本轮同公司、同市场、同方向、同加时规则重新运行既有纸面门槛：当前门槛通过即为`STILL_QUALIFIES`，即使盘口不利；只有重新审核未通过才为`NO_LONGER_QUALIFIES`。页面只有该后者才用红色加粗显示“真实盘口差异过大，经重新审核后本轮不投注”；有利变化应明确显示“当前盘口对原方向更有利”。该复核仅影响当前是否仍可进入，不覆盖历史首写、首写结算或回测记录。

## 回测与网页

每次更新必须扫描所有原生前向纸面首写记录并尝试追加赛果结算，不限于昨天。以 prediction_id 和 event_id 核对结算，按首写盘口、赔率和加时规则计算赢/输/走水；可靠赛果缺失保持 PENDING。将已确认结算同步到全部对应历史日期 JSON 及 latest.json，输出 audits/paper_settlement_tracking.json。保留原始预测、选择、盘口、赔率和时间，不能重算覆盖。昨日回顾另行保留。

同一次更新还必须输出`audits/paper_market_revalidation.json`，分别统计仍符合、当前失效、无法复核和已开赛的首写纸面单；公开页面显示每场本轮复核状态和依据。`纸面可投`首写标签表示当时的不可变决定，不等价于当前仍可按该价格纸面进入。

`--backtest-recent 6`是最近6个已结束北京时间日，不含今天。现有代码执行真实逐场留出比分重建，重建资料有24小时可得性假设，永久标记`RECONSTRUCTED_SCORE_ONLY`；不是当时原始页面状态。无历史盘口就无投注、ROI、CLV。0个合格样本要说明无可评估样本，而非0收益或策略通过。

网页由本轮全部实际结果生成。`events`数组与同口径漏斗必须一致，场数不等于报价条数。缺失为null不变0；中文优先，最大状态条为纸面可投/观察/不可投；所有让分带具体球队。正的预测分差=team1领先，对应team1公平让分为负，不能根据球队名气反转。未知方向显示待核验。

Dashboard 首屏固定采用“纸面可投优先”布局：日期与筛选控件、今日纸面可投摘要、比赛卡片依次展示；默认筛选为`PAPER_BETTABLE`，并提供一键切换全部赛事。全部 Pricing Funnel、Edge、Total、P0、League、History、Learning 等只读诊断统一放在比赛列表之后。League Funnel 不再在页面输出 `WNBA vs NON_WNBA / 抑制归因`、Near Miss、概率瀑布等原始 JSON；这些审计数据可以保留在后台 JSON，但不得挤占用户查看可投赛事的首屏位置。该布局调整只影响展示，不得改变冻结决定、门槛、账本或结算。

原生前向、包内核查、历史重建、旧版迁移分别存储。旧153分演示和旧硬编码漏斗不计修复版校准。历史账本、旧`basketball.html`和足球/金融Skill不动。复制到发布仓库与GitHub Pages实际上线不同，`--push`必须明确指定；不得宣称已验证公共网页，除非真的访问验收。

checkpoint入口是`run_basketball_checkpoint.py`，仅当外部Windows计划任务调用时执行；创建脚本不等于后台调度已启用。所有错过时点标missed，禁止回填。

## 首写信号、纸面执行、价格透支与总分诊断（v2.2 补充）

每日生产入口在冻结每场输入、定价和决定后，必须生成派生分析
`calibration/spread_execution_total_analytics.json`。它只读取不可变的
`FORWARD_NATIVE`首写、原始7M快照和追加结算；不得改写历史预测、首写盘口、赔率、决定、赛果或账本。

统计必须严格分三层：

1. **让分信号层**：保留每个“canonical event + market”的最早有效赛前首写方向，并按其冻结盘口与赛果记录WIN/LOSS/PUSH/PENDING。它是方向研究记录，页面和报告不得称为“策略胜率”。
2. **纸面执行层**：只计当时`triggered=true`的纸面条目，按首写盘口、赔率、结算规则计算纸面P&L/ROI。重复刷新产生的同场记录不得成为额外样本。
3. **价格透支层**：只能在同公司、同市场、同方向、同加时规则的首写与后续新鲜复核都存在，且后续仅因价格已不通过而失效时标记`PRICE_EXHAUSTED`。缺少新盘口、不同公司、不同方向或事件已开始都不是价格透支；此类记录不得计纸面P&L。

首次纸面记录按`config/execution_lifecycle.json`标注：T-4h至T-90m为`EARLY_PAPER_ENTRY`，更早仅为`SIGNAL_BEFORE_EARLY_WINDOW`，T-90m以内为`LATE_PAPER_ENTRY`。初始阈值来源固定为`INITIAL_PRIOR`，不得根据赛果自动校准。T-30/T-10/T-5的复核只能追加到`outputs/basketball_odds_trader/revisions/repair_v22/<prediction_id>/`，不会覆盖早盘选择、价格或纸面结算。

市场路径必须保留首见、首写、T-90、T-30、T-10、最后观察和已验证终盘（若有）。最后观察不等于终盘；没有可验证终盘不得计算CLV。盘口向模型移动/背离仅为研究诊断，不得改变概率、sigma、Kelly、模型权重或执行门槛。

总分的基础均值与残差仍以独立比分基线保存，但纸面执行一律遵循下文的`EVIDENCE_GATED_TOTAL_DIAGNOSTIC`：缺少可核验的节奏、三分、阵容、伤停或末节情景资料时，只能诊断与观察，不能以分数均值替代关键变量，也不能自动偏向大分或小分。

总分纸面执行改为`EVIDENCE_GATED_TOTAL_DIAGNOSTIC`，不是“比分均值看到低就买小”的替代品。必须先按截止时间取得并留存：双方实际回合数或可复算的回合构成、进攻/防守效率或等价可审计拆分、三分出手与命中资料、当前阵容/预计上场时间与伤停、联赛常规时间规则；历史分节比分还要分开统计胶着局（末节前分差不超过8分）与大分差局（不少于15分）的末节得分，作为末节犯规与垃圾时间的**结果代理**，不得把它冒充犯规或回合原始数据。7M公开`avgpoint/standings/pointstat/totalstat/bqcstat`可保存为节次和赛季聚合证据，但数组语义未证实前不得推导回合数、三分或犯规。

缺任一上述关键输入时总分仅显示为诊断与观察，必须阻止总分纸面单（`TOTAL_CONTEXT_INCOMPLETE`），不能从得分反推回合数或用未知阵容偏向小分。未知输入只提高不确定度、不制造方向。盘口总分上调/下调是市场路径信息而非交易方向：必须先做同公司、同市场、同结算规则的首见/首写/T-90/T-30/T-10/最后观察路径，再以独立的节奏、效率、末节情景、三分和阵容证据确认或反驳。连续小分后盘口上调只能标为“可能大分被冷落”，不能自动买大；常态大分队的低阻力大分盘口只能标为“可能诱导”，不能自动买小。任何“诱导/阻上/阻下”均仅是审计标签，不进入公平总分、概率、EV、Kelly或执行门槛。只有足量原生前向样本和独立校准申请，才能提出参数变更，禁止依历史回测自动调参。

页面顶端必须显示：让分首写方向数及W/L/P/Pending、纸面执行数及纸面P&L、已证实价格透支数、总分已结算诊断样本数，并固定说明真实执行关闭。每场详情需要显示首写阶段、阈值来源、临场复核和总分证据诊断；旧首写不因临场价格变化消失。

## v2.3 分级风险、执行滑点、总分与联赛隔离

### 联赛分级与残差不确定性

联赛分级唯一来源是`config/league_tier_registry.yaml`。未明确映射的联赛必须按`TIER_3`处理，不得因为盘口存在、球队名气或历史胜率而降级风险。Tier 1 为 NBA/WNBA；Tier 2 为 EuroLeague、CBA 常规赛和季后赛；Tier 3 包括夏季联赛、邀请赛、热身赛、青年赛、低覆盖次级联赛及其它未分类赛事。不得把 CBA 夏联、季前赛或俱乐部杯混入 CBA 常规赛的 Tier 2 评估。

Student-t 残差必须按联赛 Tier 采用`scale_adj = base_scale * residual_scale_multiplier`，而非仅在页面上标示不确定性。Tier 1 系数为 1.00，Tier 2 为 1.15，Tier 3 强制为 1.45。`df`、基础 scale 与调整后 scale 都要冻结到预测输入和输出中；不得在结算或回测后回填改变。此规则展平 Tier 3 的覆盖率和总分概率分布，所有执行门槛仍使用同一已冻结概率与 EV 合同，禁止以降低阈值抵消风险惩罚。

Tier 3 若没有可审计的近 30 个自然日内部阵容稳定性资料（名单变动、实际轮换或预计上场时间的来源、发布时间与覆盖窗口），只能输出`DIAGNOSTIC_ONLY`。该状态可以展示独立研究、盘口和缺失项，但无论模型 edge、赔率或市场路径如何，均不得生成`PAPER_ENTRY`、纸面方向或纸面 P&L。来源缺失、日期不明、赛后资料或用最终名单倒推都视为缺失。

### 价格透支、滑点和 CLV 路径

`PRICE_EXHAUSTED`是首写之后可观测到的真实水位/盘口滑点归因，不是“盘口向不利方向移动即作废”的同义词，也不得删除、覆盖或追溯排除已冻结的纸面单。首写纸面单的资格和结算永远只由其首写时的冻结合同决定；本轮是否还可以按当前报价重新进入，仍按既有同公司、同市场、同方向、同加时规则复核。

当后续同规则新鲜报价使原选择不再满足当前纸面门槛时，记录`slippage_loss`：首写与复核的让分/总分差、赔率差、方向上的有利或不利变化、复核时间和未通过的门槛。`PRICE_EXHAUSTED`只能作为该滑点事实的子状态或分析标签，不能代替`NO_LONGER_QUALIFIES`，更不能将尚未复核、不同公司、不同市场、不同结算规则或已开赛事件标为价格透支。

结算账本和`calibration/spread_execution_total_analytics.json`必须按首写、T-90、T-30、T-5 三种**可实际取得同规则报价**分别模拟执行延迟；每条路径记录可执行样本数、WIN/LOSS/PUSH/PENDING、纸面 P&L、ROI、相对首写的盘口/赔率滑点与样本删失原因。没有该时点原始报价的记录是`UNAVAILABLE`，不是零滑点，也不得用之后报价补齐。所有统计必须按联赛 Tier 与具体联赛拆分；样本不足仅报告计数和区间，不宣称真实胜率、CLV 优势或策略有效。

### EVIDENCE_GATED_TOTAL_DIAGNOSTIC：胶着局、加时与末节情景

总分模型必须将独立比分基线与以下可审计输入分开保存：预期回合数或可复算回合构成、双方进攻/防守效率、三分出手/命中与波动区间、阵容和预计上场时间、伤停、联赛加时规则、胶着局末节与大分差垃圾时间的历史分节情景。不能只使用历史总分均值，也不得把盘口上调/下调、连续大小分或历史盘路当作这些变量的替代。

以已冻结的`predictive_spread`评估胶着局：当绝对预测分差`<= 4.5`时，必须计算并单列`close_game_probability`，并在总分诊断中加入两项独立、可追溯的期望得分：`late_foul_premium`与`ot_premium`。前者只可由同联赛的胶着末节、罚球/犯规或可验证结果代理资料估计；后者只可由联赛加时规则与同联赛可用的加时发生资料估计。必须记录来源、窗口、样本数、适用性和不确定性；不存在可审计证据时为`UNAVAILABLE`，不得凭常识填默认分数。

胶着局溢价会修正独立总分的期望和残差不确定性，但不自动产生大分观点；同理，垃圾时间风险、三分回归和阵容变化必须可以支持或反驳大/小分，而非把上升盘口解释为买大、下降盘口解释为买小。只有全部关键总分输入、溢价证据和同规则市场合同都完整时，才可通过总分纸面门槛；否则维持`EVIDENCE_GATED_TOTAL_DIAGNOSTIC`或`TOTAL_CONTEXT_INCOMPLETE`，不能创建总分`PAPER_ENTRY`。

### WNBA、NBA 与 CBA 的独立评估通道

训练、校准、回测、残差、CLV/滑点和策略统计必须至少按具体联赛分开输出，禁止用 WNBA 样本校准 NBA/CBA，或用 NBA/CBA 的残差、特征权重、阈值和结果替代 WNBA。WNBA 只使用 WNBA 可验证的基础数据、时间衰减对手校正岭回归及其自身冻结的残差合同；WNBA 数据不足时降级为诊断，而不是借用男子联赛样本补足。

NBA 与 CBA 的让分纸面决策不再把赛前伤停、轮休/预计上场时间和 NetRtg（或同定义、同窗口的可审计高级效率上下文）作为存在性硬门禁。缺失信息必须标记为 `UNKNOWN` / `VALUABLE_CONTEXT`，通过 `spread_residual_scale` 与可审计的不确定性倍率反映，不能单独输出 `SPREAD_CONTEXT_INCOMPLETE` 或禁止让分 `PAPER_ENTRY`；禁止把缺失默认解释为健康、正常轮换或零调整。只有身份、真实盘口、方向/队序、结算规则、独立公平让分、核心数据完整性或严重来源冲突等真实硬阻断，才能阻止让分纸面进入。

每轮生产报告、公开 JSON 和页面必须显示：league、tier、基础/调整后残差 scale、`DIAGNOSTIC_ONLY`或上下文阻塞原因、总分胶着局/OT/末节证据状态，以及按联赛分开的执行延迟样本计数。首写、冻结预测、真实盘口原始快照、历史账本和真实执行关闭原则优先于任何新规则；新规则只能约束未来生成的诊断与纸面决定，不得回写既有记录。

## v2.4 同场双市场、总分分层证据与联赛覆盖

### 同一比赛允许让分与总分各有一条独立建议

同一 `canonical_event_id` 可以同时产生一条 `SPREAD` 建议和一条 `TOTAL` 建议，但两条建议必须是两个互相隔离的市场记录：

- 决策主键为 `canonical_event_id + market_type`；同一场同一市场仍最多一条首写纸面决定。
- 每个市场分别保存 `selected`、盘口、赔率、概率、EV、阻塞项、首写时间、复核状态、结算和审计字段；不得用一个全场 `selected` 覆盖另一个市场。
- 让分通过而总分被阻断时，允许输出“让分纸面可投、总分诊断观察”；总分通过而让分未通过时反之。两条建议都必须单独显示，不能因另一市场失败而隐藏。
- 纸面执行计数、结算、P&L、CLV 和 `PRICE_EXHAUSTED` 均按 `market_type` 分组；同场双市场不是重复下注同一市场，也不允许合并成一张模糊建议。
- 真实执行仍永久关闭；页面使用“纸面让分建议”和“纸面大小分建议”，不得显示实盘下注。

### 总分证据门禁改为 Hard Blocker 与 Soft Missing 两层

`TOTAL_CONTEXT_INCOMPLETE` 不能再把所有缺失都视为完全不能定方向。总分必须先按以下层级处理：

**Hard Blocker：只能 `TOTAL_DIAGNOSTIC_ONLY`，不得给出大/小分纸面方向**

- 比赛身份、球队映射或联赛规则冲突/无法确认；
- 没有真实、同场、同规则的总分盘口；
- 没有基础攻防数据，且没有足够 Box Score 反推回合数；
- 只有最终得分、没有任何可审计的 FGA/FTA/ORB/TO 或 Pace 证据；
- 关键数据明显过期、互相矛盾，或使用了赛后才获得的信息。

**Soft Missing：允许形成带不确定性的总分预测，但不得伪装成完整证据**

- 伤停未知；
- 轮换/预计时间不完整；
- 三分资料部分缺失；
- 末节犯规环境或加时发生率暂时无法直接确认。

Soft Missing 必须扣减数据质量、扩大总分残差区间并在输出中列明缺项；不得因为这些缺项自动偏向大分或小分。只有总分市场存在、基本攻防和回合层级达到可执行最低等级、加时/常规时间规则已核验且纸面门槛仍通过时，才可输出 `SHADOW_BET` 或 `SHADOW_LIMIT_ONLY`；否则输出 `TOTAL_DIAGNOSTIC_ONLY`。

### 回合数、三分与比赛规则必须补全并冻结

总分核心使用：`ExpectedTotal = ExpectedPossessions × (ExpectedPPP_team1 + ExpectedPPP_team2)`，并在同一输入截止时间加入 ORtg/DRtg、eFG%、3PA rate、3P%、FT rate、ORB%、TOV%、阵容、休息、旅行、主场、末节和加时证据。历史总分均值只能作为辅助特征，不能单独决定方向。

回合数按证据等级计算并记录：

- `LEVEL_A`：来源直接提供 Possessions/Pace；
- `LEVEL_B`：双方至少有 `FGA + 0.44*FTA - ORB + TO` 的完整构成，按比赛复算；
- `LEVEL_C`：只有部分 Box Score 与历史 Pace，允许估计但扩大不确定度并降级；
- `LEVEL_D`：连上述资料都没有，触发 Hard Blocker。

生产采集必须优先解析 7M 或其它公开来源的 `Basketball_Team_Data/<team>/gb/n_history.js`。双方至少取得最近 8 场有效比赛的回合构成或直接 Pace，并保存每场的 FGA、FTA、ORB、TO、3PA、3PM、来源 URL、发布时间/抓取时间和输入哈希。三分至少计算赛前 3P% 均值、标准差及 3PA rate，供总分诊断和 `THREE_POINT_VARIANCE` 错因审计使用；不能用最终赛果倒填赛前资料。

常规时间与加时规则必须从 `config/game_rule_registry.json` 或等价官方规则来源确认并冻结。预测分差绝对值不超过 4.5 分时计算 `close_game_probability`；`late_foul_premium` 和 `ot_premium` 只可用同联赛真实样本估计，样本不足标为 `UNAVAILABLE`，不能写死默认分值。

### NBL、NCAA 与欧篮联覆盖规则

`NBL_AU`、`NCAAB`、`WNCAAB`、`EUROLEAGUE` 已属于正式联赛池，必须执行 broad source、官方/联赛专项源、球队历史源和盘口源的独立 UNION；不得因为当前日期没有赛事、单个源返回空数组或尚无可投建议而从页面和 coverage manifest 删除。

- `EUROLEAGUE` 当前按 Tier 2 进入成熟职业联赛通道；若没有至少 3 场同赛事有效历史、同场真实盘口、球队身份/规则确认或市场完整性验证，只能 `UNPRICEABLE`、`WATCH` 或 `PASS`，必须显示具体原因。
- `NBL_AU`、`NCAAB`、`WNCAAB` 当前按 Tier 3 高不确定性通道处理；这表示它们会被发现、抓取、独立定价和展示，但缺少近 30 天阵容稳定性/预计时间证据时只能 `DIAGNOSTIC_ONLY`，不能生成纸面单。补齐合格阵容稳定性、历史样本、规则和同场盘口后才可进入纸面门槛。
- NBL/NCAA 不推荐的原因必须拆成可审计枚举：`NO_EVENT_FOUND`、`NO_MARKET`、`INSUFFICIENT_HISTORY`、`ROSTER_STABILITY_MISSING`、`TOTAL_CONTEXT_INCOMPLETE`、`SPREAD_CONTEXT_INCOMPLETE`、`PROVIDER_DISAGREEMENT` 或 `EDGE_BELOW_THRESHOLD`；禁止统一写成“数据不足”。
- 每轮报告必须分别输出这些联赛的 `events_found`、`market_observed`、`independent_priceable`、`spread_recommendations`、`total_recommendations` 和各阻塞原因。未推荐不等于没有比赛。

### 深盘受让偏多：先校准中心，再校准残差

深受让比例偏高不得通过强行平衡方向、增加热门方权重、压低受让概率、手工修改公平分差或单纯放大残差解决。必须分开审计：

1. `Raw Independent Margin -> League/Global Mean Calibration -> Deep-Spread Calibration -> Calibrated Fair Margin`。使用冻结的严格 OOS/walk-forward 数据检查 `actual_margin = a + b * raw_model_margin`、intercept、slope、mean error、MAE、RMSE，并至少拆分 `NORMAL abs(market_spread)<10` 与 `DEEP abs(market_spread)>=10`。
2. 中心校准完成后才使用 Student-t residual scale 描述不确定性。scale 优先级为联赛 OOS 实证乘数、Tier prior、global fallback；Tier 1/2/3 的 1.00/1.15/1.45 只是 cold-start prior，不得当成永久参数，也不能改变 Calibrated Fair Margin 中心。
3. 深受让比例异常只触发 `DEEP_SPREAD_BIAS_DIAGNOSTIC`，检查 Margin Compression、联赛漂移、伤停/轮换覆盖、垃圾时间、板凳深度、大胜概率和热门方上限，不自动改变估值。

每条信号必须分离保存 `raw_model_margin`、`calibrated_fair_margin`、`market_spread_at_signal`、`cover_probability`、`expected_value`、`residual_scale`、`league_multiplier` 和 `model_version`；执行层另存实际执行盘口、价格、终盘、slippage 与 CLV。`Line Movement`、`CLV` 和 `Execution Slippage` 不得混称。盘口向模型方向移动不自动等于 `PRICE_EXHAUSTED`，只有当前剩余 EV 低于最低门槛才可标记。

### 结算错因审计（Failure Audit Ledger）

错因审计的唯一策略配置是`config/failure_audit_policy.yaml`。每次新增或修正为已验证`LOSS`的结算，必须在冻结预测、首写合同和赛果结算之后，自动向`outputs/basketball_odds_trader/audits/post_mortem.json`追加一条审计卡。审计只解释已发生的偏差，绝不回写首写预测、盘口、决定、赛果、结算、残差参数、Kelly 或模型权重；真实执行仍永久关闭。

每条审计至少写入`prediction_id`、`event_id`、`settlement_id`、`market_type`、首写方向与合同、冻结输入哈希、赛果来源、审计时间和如下 JSON 核心字段。`hard_evidence`只能填入实际取得且可复核的原始指标、数值、阈值与来源；不得以“表现不佳”“防守松懈”“手感火热”等主观形容词替代指标。

```json
{
  "event_id": "7m:xxxx",
  "failure_label": "GARBAGE_TIME_COVER | THREE_POINT_VARIANCE | ROSTER_NOISE | FOUL_ENGINE_BURST | CAUSE_UNKNOWN_INSUFFICIENT_DATA",
  "hard_evidence": {
    "metric_name": "Q4_margin",
    "metric_value": -12,
    "threshold_triggered": "<= -8",
    "source_ref": "immutable raw score snapshot"
  },
  "audit_passed": true,
  "reasoning_chain": "首写让分合同在第三节结束时仍覆盖；所选一方第四节净负12分，最终让分结算为LOSS，满足已配置的Q4净负至少8分阈值。"
}
```

标签必须按以下可量化规则判定，并且只有全部`requires`字段来自赛前冻结记录或可信赛后原始赛果/技术统计时才能`audit_passed=true`：

1. `GARBAGE_TIME_COVER`仅适用于让分 LOSS：第三节结束时所选方向按首写让分仍覆盖、所选方第四节净负至少8分、最终为 LOSS，并具备分节比分与让分合同。标签是量化末节吞噬模式，不得据此声称已证明替补上场或比赛态度。
2. `THREE_POINT_VARIANCE`适用于让分或总分 LOSS：必须有赛前冻结的同赛事最近10场三分命中率均值和标准差，以及双方赛后命中/出手。所选方或对手的实际三分命中率相对该赛前基线绝对 z-score 至少2.5，记录是哪支队、基线、实际值和 z-score。没有赛前基线，不能以赛后十场回填。
3. `ROSTER_NOISE`适用于让分或总分 LOSS：冻结赛前资料显示核心球员预计至少20分钟，赛后正式出场时间少于10分钟，且首写阵容快照没有捕捉到相应限制。必须记录球员、预计/实际分钟、赛前来源和赛后技术统计；没有预计分钟或实际分钟时不得推断伤停或轮休。
4. `FOUL_ENGINE_BURST`仅适用于总分 LOSS：常规时间最后120秒得分超过常规时间总分的15%，且与首写总分合同的失效方向一致。记录末120秒得分、常规时间总分、比例、是否含加时和总分结算。加时得分不得混入该指标。

若某条 LOSS 缺分节、三分、分钟、赛前基线或其它必要证据，或者所有可验证规则均未触发，必须写`CAUSE_UNKNOWN_INSUFFICIENT_DATA`，`audit_passed=false`，并在`reasoning_chain`逐项列明缺失的字段/来源。不得猜测原因，也不得仅因最终比分偏离预测给出特定标签。存在多个已满足标签时，按`ROSTER_NOISE`、`GARBAGE_TIME_COVER`、`FOUL_ENGINE_BURST`、`THREE_POINT_VARIANCE`的顺序选定一个主标签；其余已验证指标可附于`secondary_hard_evidence`，每项同样必须有数值、阈值与来源。

错因审计是风险监控，而不是赛后自动调参器：`GARBAGE_TIME_COVER`只能提出未来深盘末节风险的研究假设；`THREE_POINT_VARIANCE`归为不可控随机噪声，不调整基础参数；`ROSTER_NOISE`必须记录数据时效性缺失并加强未来赛前来源要求；`FOUL_ENGINE_BURST`只能进入同联赛胶着局溢价的候选校准队列。任何参数、权重、阈值或执行规则的改变都需要足量独立原生前向样本、分联赛评估和单独授权，禁止因单场或小样本失败自动修改。

页面与日报必须显示已结算纸面 LOSS 是否已有错因审计、主标签和`audit_passed`。不存在足够证据时必须明确显示“错因未确认：数据不足”，不能用空白、默认原因或主观文案掩盖。`post_mortem.json`为追加式账本；后续补充证据只能新建带版本与时间戳的审计修订，不得覆盖初版审计。

## v3.1 Pricing Funnel Diagnostic（只读诊断）

每次真实生产运行在不改变模型、阈值、Evidence Gate、fallback、纸面决定、账本或真实执行状态的前提下，必须生成定价漏斗诊断。诊断只读取本轮冻结的 `event`、`market`、`pricing` 和 `execution` 行，不把诊断结果反写回这些字段。

标准阶段为：`DISCOVERED -> CANONICALIZED -> MARKET_FOUND -> LEAGUE_RULE_READY -> TEAM_MAPPING_READY -> HISTORY_READY -> BASE_STATS_READY`，之后让分与大小分分叉为 `SPREAD_FEATURES_READY -> SPREAD_PRICEABLE` 和 `TOTAL_FEATURES_READY -> TOTAL_PRICEABLE`，再分别进入 `EVIDENCE_GATE -> EDGE_GATE -> EXECUTION_GATE`。大小分缺证据不得把整场让分一起标成无法定价。

每个市场只能有一个 `primary_block_stage` 与 `primary_block_reason`，按第一个未通过阶段确定；其余阻塞只进入 `secondary_warnings[]`。状态必须区分：`NOT_PRICEABLE`、`PRICEABLE_NO_EDGE`、`EDGE_FOUND_EVIDENCE_BLOCKED`、`EDGE_FOUND_EXECUTION_BLOCKED`、`SHADOW_TRIGGERED`。缺失数字保持 `null`/空值，不得填零。

诊断至少区分以下归因：`FIXABLE_DATA_ENGINEERING`、`GENUINE_DATA_ABSENCE`、`MODEL_LIMITATION`、`INTENTIONAL_RISK_BLOCK`。必须检查联赛/层级/地区/全局注册表、历史与球队别名链、回合数可复算路径、联赛规则和残差 scale fallback 是否实际被调用；“文件存在”不等于 fallback 已生产验证。Hard Missing 与 Soft Missing 分开统计，伤停未知、轮换未知、三分细节缺失、末节犯规样本不足和 OT 证据不足不能未经现有规则明确规定就被诊断为 Hard Block。

生产入口每轮输出：

```text
D:\codex\outputs\basketball_odds_trader\diagnostics\pricing_funnel_YYYYMMDD.csv
D:\codex\outputs\basketball_odds_trader\diagnostics\pricing_funnel_summary_YYYYMMDD.json
D:\codex\outputs\basketball_odds_trader\diagnostics\pricing_funnel_summary_YYYYMMDD.md
```

CSV 每行一场比赛，必须同时含赛事身份、北京时间、让分/大小分盘口存在性、canonical/规则/球队映射/历史/基础数据阶段、两条市场的 feature ready 与 priceable、各自 primary 阶段/原因、secondary warnings、data/evidence quality、fair/market 值、edge 与最终状态。JSON/Markdown 必须包含总赛事、让分/大小分独立漏斗、每一步转化率、按联赛与地区统计、各市场 Top blocking reasons 及占全部阻塞比例、Hard/Soft 清单、四类归因、fallback 审计和 15 项结论：市场为何未定价、让分数、大小分数、最大损耗阶段、Top 10 原因、四类问题、工程修复上限、仍应不可定价数、提前 return 证据、Hard/Soft 混淆、已配置但未使用的 registry、工程修复后的非保证性估计。

页面必须增加可展开的“定价漏斗诊断”区域，展示总赛事、盘口、映射、历史、基础数据、让分可定价、大小分可定价、Edge、纸面触发、最大瓶颈和前五阻塞；逐场详情必须能查看两条市场的阶段和主次原因。该区域是审计信息，不是额外的下注建议。诊断结束后只给出 P0/P1/P2 修复优先级，禁止在同一阶段实施修复或为了增加纸面机会降低任何门槛。

## v3.2 Pricing Funnel Terminal Accounting & History Readiness（只读诊断）

定价漏斗诊断必须把每个 `event × market_type` 记录分配到且仅分配到一个终态：`NO_MARKET`、`STALE_MARKET`、`RULE_BLOCKED`、`MAPPING_BLOCKED`、`HISTORY_BLOCKED`、`BASE_STATS_BLOCKED`、`FEATURE_BLOCKED`、`PRICEABLE_NO_EDGE`、`EVIDENCE_BLOCKED`、`EXECUTION_BLOCKED` 或 `SHADOW_TRIGGERED`。`events_total × market_types` 必须等于终态计数总和；不相等必须输出 `FUNNEL_ACCOUNTING_ERROR`，不能用 `events - priceable` 作为“未定价”。

漏斗顺序固定为：`events_total -> market_found -> FRESH_MARKET -> canonical/rule/mapping -> history -> base/features -> priceable -> evidence/edge/execution`。没有盘口与盘口过期分别记为 `NO_MARKET` 与 `STALE_MARKET`；过期盘口不得静默进入历史或执行分支。摘要必须同时提供 `market_found_but_not_priceable` 与 `fresh_market_but_not_priceable`，并分别列出 `no_market`、`stale_market`、`fresh_market` 与 `priceable`。

每次生产运行还必须生成球队级历史就绪瀑布：原始抓取 -> 球队别名匹配 -> 联赛/competition 匹配 -> 截止时间前 -> 有效比分 -> 去重 -> 可用样本。每个球队至少保存 canonical id、原始队名、联赛、来源、抓取是否尝试/成功、各阶段场次、最低要求、是否 ready 和首要失败原因。失败原因使用固定枚举：`HISTORY_SOURCE_FAILED`、`TEAM_ALIAS_HISTORY_MISMATCH`、`LEAGUE_ALIAS_HISTORY_MISMATCH`、`NO_PRE_CUTOFF_HISTORY`、`TOO_FEW_PRE_CUTOFF_GAMES`、`HISTORY_FILTER_TOO_STRICT`、`SEASON_TRANSITION_FILTER`、`COMPETITION_ID_MISMATCH`、`DATE_TIMEZONE_FILTER_ERROR`、`DUPLICATE_REMOVAL_OVERFILTER`、`INVALID_SCORE_FILTER`、`SOURCE_HISTORY_GENUINELY_ABSENT`。不得把解析成功但过滤掉的历史统称为“没有数据”。

历史来源审计必须报告 raw -> alias -> league -> pre-cutoff -> valid -> dedup -> usable 的计数、地区别名匹配、联赛过滤移除、日期/时区拒绝、无效比分、重复删除，以及 ESPN/SofaScore 等来源的尝试/失败/fallback/early-return 轨迹。无法从运行时证据证明 fallback 是否调用时，必须写 `NOT_INSTRUMENTED` 或 `NOT_PROVEN`，不能声称已修复。工程修复、来源降级、真实数据缺失、模型要求四类只能用于诊断，不得自动放宽既有定价门槛。

v3.2 的诊断区域必须在 Dashboard 中可展开，并允许逐场查看双方球队历史。该区域只读，不修改 pricing、Evidence Gate、阈值、sigma、纸面决定、ledger 或真实执行状态。

## v3.0 全球赛事发现与生产覆盖

每日生产入口必须先运行 `scripts/global_discovery.py`，建立全球篮球赛事池，再由 `scripts/odds_discovery.py` 为每场赛事查询盘口。7M 是重要盘口源，不是赛事存在的唯一入口。赛事没有盘口时必须保留为 `DISCOVERED_ONLY / NO_MARKET`。

标准链路：`GLOBAL EVENT DISCOVERY -> CANONICAL EVENT REGISTRY -> ODDS DISCOVERY -> ENRICHMENT -> INDEPENDENT PRICING -> SHADOW ELIGIBILITY -> EXECUTION ELIGIBILITY`。

每场赛事必须保存五级状态：`DISCOVERED_ONLY`、`MARKET_FOUND`、`PRICEABLE`、`SHADOW_ELIGIBLE`、`EXECUTABLE`。状态只允许由实际字段和证据升级，不允许因盘口缺失删除赛事，也不允许因模型有 Edge 自动升级为可执行。

`config/league_registry.yaml` 是注册表，不是生产覆盖证明。每个联赛至少维护 canonical id/name、国家/地区、family、competition type、性别、年龄组、赛制分钟、发现源、盘口源、统计源、别名和 active status。未知赛事进入 `UNCLASSIFIED_DISCOVERED` 与 `PENDING_LEAGUE_CLASSIFICATION`，不得静默归入 `OTHER_DISCOVERED`。

生产状态必须区分：`REGISTERED`、`DISCOVERY_ACTIVE`、`MARKET_ACTIVE`、`PRICING_ACTIVE`、`PRODUCTION_VERIFIED`、`CONFIGURED_ONLY`、`TEST_ONLY`、`DISCOVERY_ONLY`、`FAILED`。只有 `PRODUCTION_VERIFIED` 才能称为真实生产覆盖。

中国联赛必须分别识别 `CHINA_CBA`、`CHINA_WCBA`、`CHINA_NBL`、`CHINA_CUBA`、`CHINA_UNIVERSITY_OTHER`、`CHINA_YOUTH`、`CHINA_CLUB_CUP`、`CHINA_FRIENDLY`。FIBA 每日必须主动尝试 `FIBA_MEN`、`FIBA_WOMEN`、`FIBA_QUALIFIER`、`FIBA_CONTINENTAL`、`FIBA_YOUTH`、`FIBA_FRIENDLY` 官方赛事日历；官方源只负责发现，盘口源单独负责市场。官方源不可访问时记录健康状态，不能解释成当天没有国家队比赛。

日本/韩国、大洋洲、欧洲、美洲、海湾及其他亚洲赛事进入对应 family；欧洲新赛事进入 pending onboarding。新联赛默认 `COLD_START`，样本数规则为 `<20 DISCOVERY_ONLY`、`20-49 WEAK_SIGNAL`、`50-99 PROVISIONAL`、`>=100 META_CALIBRATION_ELIGIBLE`，不因扩大研究池降低 spread/total Evidence Gate。

所有来源能力写入 `config/source_capabilities.yaml`。赛程、结果、统计、伤停、阵容和盘口是独立能力。盘口路由必须记录 source、时间、匹配方法、市场状态和失败原因；不得用历史均值、Fair Line 或模型值冒充真实盘口。多源盘口必须 reconciliation，7M 无盘口只记 `7M_MARKET_NOT_FOUND`。

每日输出并在 v2 页面显示：`TOTAL DISCOVERED -> MARKET FOUND -> DATA READY -> PRICEABLE -> SHADOW SIGNAL -> EXECUTABLE SIGNAL`，同时按中国、日本韩国、欧洲、北美、拉美、FIBA、大洋洲、海湾和其他亚洲拆分。页面还必须列出无盘口、数据不足、无法定价和未识别联赛的实际赛事与原因。

新增来源必须先验证可访问、赛事识别、队名映射、北京时间、盘口字段、让分方向和总分字段，并在 health 中标记 `PRODUCTION_READY` 或失败状态。历史回填与 `FORWARD_NATIVE` 严格分离并标注 `HISTORICAL/OOS/PROSPECTIVE`；不能用历史回填伪装为今日前向输入。

## v3.3 冷启动与 Bootstrap 定价治理

冷启动只解决“新联赛有真实历史但不足以走成熟通道”的研究定价问题，不是降低正式门槛的办法。实现配置唯一来源为 `config/cold_start_pricing.yaml`，其中的历史权重、竞争强度调整、ESS 门槛和残差放大系数均是可审计 prior，必须在独立前向样本上评估后才能申请调整，禁止用最近胜负自动调参。

每场必须分别保存以下三层状态：

- `RESEARCH_PRICE`：只表示独立模型可以在冻结输入上产生公平分差/总分；不需要市场，也不等于有交易方向。
- `SHADOW_BET`：必须同时具备本轮真实、同场、同规则盘口，独立定价，原有证据门禁和 Edge 门槛；真实执行永久关闭。
- `EXECUTABLE_BET`：当前系统保留的最高治理层。冷启动、国家队 Bootstrap、`PRIOR_ONLY_PRICE` 均不得进入该层，当前全局 `real_execution_allowed` 永远为 `false`。

成熟通道不得改写：同赛事身份、截止前、已确认终场、最小历史场次、对手覆盖、伤停/轮换/NetRtg、高不确定性阵容稳定性、总分回合/效率/规则和市场完整性门槛仍按原规则执行。只有成熟通道不足时，才可以在 `TEAM_HISTORY` 证据上进入 Bootstrap；`H2H`、搜索摘要、赛后资料、最终阵容倒推和没有时间证据的行不得借力。

Bootstrap 历史权重按 `season_bucket × competition_strength_adjustment` 计算：当前赛季为 `1.0`，前一有效赛季使用配置的 `0.50-0.70` 区间，较早历史使用 `0.20-0.40` 区间。竞争强度至少区分 Tier 1 continental、Tier 1 domestic、Tier 2 domestic、cup、friendly、national window 和 unknown。输出必须含原始场数、当前/前季/更早场数、每队及最小 `effective_sample_size`、关系类型、竞争调整和输入指纹；不能只报告 raw count。

冷启动状态定义：

- `NATIVE_PRICEABLE`：成熟通道按原有同赛事历史产生定价。
- `COLD_START_PRICEABLE`：Bootstrap 历史达到配置的研究 ESS，可产生扩大残差的不确定性研究价；默认不具备 Shadow 资格。
- `NATIONAL_TEAM_BOOTSTRAP`：使用 12-24 个月国家队历史、FIBA/Elo 先验（若已真实取得）、阵容强度、球员俱乐部强度、赛事类型、主客/中立场、休息和旅行证据；名单未知会扩大不确定性，不能凭空补全。
- `PRIOR_ONLY_PRICE`：只有先验、没有足够赛前球队比赛事实时，只能诊断观察，不得产生纸面方向。

冷启动允许的残差放大必须写入预测快照和输出；它不能永久硬编码为最终校准系数。`COLD_START_PRICEABLE` 若要进入 `COLD_START_SHADOW`，必须同时满足配置的 shadow ESS、当前赛季最低场数、近 30 日阵容连续性、市场质量和原有 Evidence/Edge/执行门槛。任何一项缺失都必须输出具体 blocker，不得用盘口或最终比分替代。

职业球队可以跨国内联赛、EuroLeague、EuroCup、杯赛和热身赛进入 Team State History，但每行必须携带竞争调整和证据关系；跨赛事只能提高研究覆盖，不能把不同赛事当作同源独立样本。WNBA、NBA、CBA、EuroLeague、NBL、国家队的训练、残差、CLV、滑点、结算和错误审计必须分联赛/模型通道隔离。

联赛生命周期固定为 `DISCOVERY -> BOOTSTRAP -> SHADOW -> PROVISIONAL -> QUALIFIED`。升级只能基于有效 ESS、独立前向样本量、校准、CLV、MAE/RMSE、Brier、数据质量和市场质量；最近几场赢球、纸面盈利或单次回测不得触发升级。每日 JSON、审计报告和页面必须展示各 family 的发现数、盘口数、本季/前季历史、ESS、研究定价、冷启动定价、Shadow 和 Executable 数；缺失数据保持 `null`，不填 0。

结算学习层必须把 `NATIVE_PRICEABLE`、`COLD_START_PRICEABLE`、`NATIONAL_TEAM_BOOTSTRAP` 和 `PRIOR_ONLY_PRICE` 分开统计 MAE、RMSE、CLV、cover calibration、ROI 与残差规模。历史重建只作 OOS/研究证据，不能回写冻结预测、首写盘口、决定、账本或当前模型参数。真实下注永远禁止。

## v3.4 总分盘口可见性与全链路审计

总分盘口不得因为总分证据不足、独立定价失败、Edge 不足或未触发纸面执行而从页面和数据中消失。总分必须沿用独立的生命周期：`TOTAL_MARKET_FOUND -> TOTAL_MARKET_FRESH -> TOTAL_PRICEABLE -> TOTAL_EVIDENCE_COMPLETE -> TOTAL_EDGE_FOUND -> TOTAL_SHADOW_ELIGIBLE -> TOTAL_EXECUTABLE`。每个阶段独立记录；`TOTAL_MARKET_FOUND` 不等于可投注，`TOTAL_PRICEABLE` 也不等于有优势。

生产运行必须同时保留 `RAW -> PARSED -> NORMALIZED -> CANONICAL -> FRESH` 的总分审计。每场保存原始总分、双方赔率、公司、源报价时间、抓取时间、报价年龄、标准化状态、事件绑定状态和所有阻塞原因；缺失数值使用 `null`，不得用 `0` 伪装。让分与总分分别计算，不能因为让分分支有盘口或有纸面结论而隐藏总分。

总分市场审计文件为 `outputs/basketball_odds_trader/diagnostics/total_market_pipeline_YYYYMMDD.csv` 及同日 JSON 摘要。页面必须显示总分已抓到、新鲜、可独立定价、证据完整、有 Edge、纸面触发的分层数量，并提供“有总分盘口”“总分可定价”“总分有优势”筛选。证据门槛仍严格执行：真实盘口先展示，再明确标记 `TOTAL_CONTEXT_INCOMPLETE`、`TOTAL_NOT_PRICEABLE`、`TOTAL_NO_EDGE` 或 `TOTAL_MARKET_NOT_FRESH`，不得为了填满页面降低回合、效率、三分、阵容、末节和加时证据要求。

7M 解析必须在同一 `bOdds` 事件下独立解析 `HB` 让分和 `TP` 总分。任一盘口数组格式错误时，错误记录必须携带 `market_type`、原始市场键和 `loss_stage`；一个盘口失败不得提前返回并丢弃另一市场。页面的市场比较区必须展示已抓到的原始总分，即使它没有被选为有效比较报价；盘口原文详情仍保留全部公司、双边赔率和时间。该版本只修复可见性和审计，不修改总分公式、概率、sigma、Evidence Gate、Edge、Kelly、纸面决定或真实执行状态。

## v3.5 总分近况与分节证据层

总分诊断必须在每场可用的截止时间前终场事实中，单独保存双方最近 `5` 场和 `10` 场：总分、球队得分、对手得分、分差、Q1-Q4/加时得分、总分波动、分差波动、14 日比赛密度和相邻比赛休息间隔。必须保留 `event_id`、`tip_at`、来源 URL/raw snapshot、抓取时间和输入截止时间，禁止使用截止时间后的赛果或修订。

末节结构必须分开统计：赛前三节分差 `<=8` 分定义为胶着局样本，`>=15` 分定义为大分差/垃圾时间代理样本；同时报告两类样本的 Q4 总分和样本量。该分类只描述可量化的历史场景，不把“领先/落后”或 Q4 得分直接当成回合数、三分率、犯规率、伤停、轮换或旅行数据。

总分方向分析必须同时考虑：近期 5/10 场总分趋势、分节得分变化、胶着局末节犯规/加时证据是否真实存在、领先与大分差场景、得分方差、赛程密度和休息间隔，以及当前真实总分盘口。盘口上升或下降本身不得直接解释为大分或小分；必须先对照上述证据。缺少具体变量时输出 `UNKNOWN`/`INSUFFICIENT_DATA`，不允许从盘口或最终比分补猜。

比分与分节数据属于 `FINAL_SCORE_AND_PERIODS_ONLY` 证据层：可以用于总分基线、状态和波动诊断，但不得冒充回合数、Pace、三分命中率、末节犯规或阵容变化。后四类变量只有在来源明确、时间有效且字段语义已验证时，才可升级对应 Evidence Gate。若总分已有真实盘口但回合/效率/规则等硬证据仍缺失，仍必须保留盘口并显示 `TOTAL_CONTEXT_INCOMPLETE`，不得为了产生推荐放松门槛。

Dashboard 必须展示“近况、分节与赛程波动（总分证据）”区域，并能逐队查看近 5/10 场均值、Q1-Q4 总分、波动和 14 日场次；同时显示“未从比分推断回合/三分/犯规/伤停/旅行”的审计提示。总分盘口没有消失，只是在 `TOTAL_MARKET_FOUND`、`TOTAL_MARKET_FRESH`、`TOTAL_PRICEABLE`、`TOTAL_EVIDENCE_COMPLETE`、`TOTAL_EDGE_FOUND` 和 `TOTAL_SHADOW_ELIGIBLE` 之间如实停留。

## v3.6 Edge Funnel 与零触发审计

本版本新增的是只读诊断层，不是新定价模型。不得修改 Fair Spread、Fair Total、Evidence Gate、Edge threshold、Residual Scale、Meta Calibration、Market Weight、Execution threshold、Paper trigger、Champion model、历史首写或账本。诊断运行在冻结预测与决定之后，不能把诊断字段反写为模型输入或纸面决定。

完整漏斗必须按 `market_type` 独立计算，且至少输出：

`DISCOVERED -> MARKET_FOUND -> FRESH_MARKET -> RESEARCH_PRICEABLE -> MARKET_COMPARABLE -> RAW_EDGE_FOUND -> CALIBRATED_EDGE_FOUND -> EVIDENCE_PASS -> EXECUTION_PASS -> SHADOW_TRIGGERED`

让分与总分不能合并成一个“独立定价”数字。`MARKET_COMPARABLE` 只统计同一赛事、同一市场、同一时段、同一加时结算规则、存在新鲜有效盘口并且已完成独立定价的记录；盘口存在、研究价存在或旧报价存在，都不能单独算作可比较样本。

`31 -> 16` 必须对每个 `game_id × market_type` 产生唯一 `primary_final_reason`，并区分：`NO_MATCHING_MARKET`、`MARKET_TYPE_MISMATCH`、`RULE_MISMATCH`、`STALE_MARKET`、`INVALID_MARKET`、`SOURCE_CONFLICT`、`CANONICALIZATION_MISMATCH`、`RESEARCH_ONLY_NO_MARKET`、`OTHER`。不能用“无法比较”吞掉真实原因。

Raw Edge 只表示独立模型公平线与同场真实市场线的差异，未经 Meta Calibration、Residual Scale、Market Prior 或 Probability Calibration：

- 让分：`raw_edge_points = raw_fair_spread - market_spread`。
- 总分：`raw_edge_points = raw_fair_total - market_total`。

诊断保存 `raw_fair_line`、`market_line`、`raw_edge_points`、`raw_cover_probability`。只有生产模型明确输出 `calibrated_fair_line` 或等价校准字段时，才保存 `calibrated_edge_points`、`adjusted_probability` 与 `adjusted_EV`；不得从市场融合线倒推出“校准后公平线”。缺失保持 `null`，不能填 0。

对可比较样本必须逐层输出 `Comparable`、`Raw Edge Found`、`Calibrated Edge Found`、`Evidence Pass`、`Execution Pass`、`Shadow Triggered`，并为每个样本只保留一个最终原因：`NO_RAW_EDGE`、`EDGE_REMOVED_BY_CALIBRATION`、`CALIBRATED_EDGE_BELOW_THRESHOLD`、`PROBABILITY_BELOW_THRESHOLD`、`NEGATIVE_EV`、`EVIDENCE_BLOCKED`、`EXECUTION_BLOCKED`、`PRICE_EXHAUSTED`、`MARKET_MOVED`、`LOW_DATA_QUALITY`、`SHADOW_TRIGGERED`。可以保留多个 `secondary_warnings`，但不能用多个 primary 原因替代终态。

过度收缩只做审计：当 `abs(raw_edge_points) >= MIN_DIAGNOSTIC_EDGE_POINTS` 且存在明确校准 Edge 时，计算 `edge_retention_ratio = abs(calibrated_edge_points) / abs(raw_edge_points)`，输出均值、中位数和 `possible_over_shrinkage`。至少按 `SPREAD/TOTAL`、联赛、Tier、`NATIVE/COLD_START`、`DEEP_SPREAD/NORMAL_SPREAD` 分组；该阈值是诊断阈值，不是下注门槛，不得自动调参。

每次生产运行输出 `diagnostics/comparable_edge_YYYYMMDD.csv`，字段至少为：`game_id`、`league`、`market_type`、`home_team`、`away_team`、`start_time`、`pricing_mode`、`market_line`、`raw_fair_line`、`raw_edge_points`、`raw_probability`、`calibrated_fair_line`、`calibrated_edge_points`、`adjusted_probability`、`adjusted_EV`、`residual_scale`、`league_residual_multiplier`、`meta_confidence`、`model_weight`、`market_weight`、`data_quality`、`evidence_status`、`execution_score`、`edge_retention_ratio`、`primary_final_reason`、`secondary_warnings`。

Dashboard 必须使用真实诊断 JSON 显示 Edge Funnel，分别展示让分/总分各阶段数量，并在 `SHADOW_TRIGGERED = 0` 时显示“今日为什么 0 场”及可比较样本的 primary reason 分布。页面中的该区域只读，明确说明不修改公平线、概率、证据门槛或执行决定。诊断文件缺失、校准字段未输出或盘口不可比较时，页面必须显示缺失/阻塞，不得把空值渲染为 0 后宣称没有 Edge。

## v3.7 P0 结构审计与方向偏置监控

P0 审计必须继续使用现有 `repair_v22`、Forward Native 首写账本和当前 Dashboard，不得另建篮球系统，不得删除历史账本、Learning Engine、Error Attribution、Meta Calibration、Champion/Challenger、Spread/Total、Cold-start、Pricing Funnel、League Decision Funnel 或 HTML 页面。

每笔新产生的 Spread 决定必须尽量永久保存完整 Fair Spread 分解：`raw_team_strength_home`、`raw_team_strength_away`、`raw_expected_home_score`、`raw_expected_away_score`、`raw_independent_margin`、`after_mean_calibration_margin`、`after_deep_spread_calibration_margin`、`market_spread`、`model_market_gap`、`betting_fair_spread`、`base_residual_scale`、`tier_residual_multiplier`、`league_residual_multiplier`、`deep_spread_residual_multiplier`、`raw_cover_probability`、`calibrated_cover_probability`、`final_cover_probability`、`expected_value`、`selected_side`。尚未实现的校准层必须保留 `null` 并标记缺失原因，不能用 Raw 值冒充已校准值。

每次生产运行必须生成只读 `diagnostics/p0_bias_audit_YYYY-MM-DD.json` 与 Markdown 摘要，并在 Dashboard 提供可展开区域，至少包括：Favorite/Underdog 方向统计（last 10/20/50、rolling 7d、all Forward Native）、WNBA 专项统计、概率双边一致性、`actual_margin = a + b * predicted_margin` 的 Forward Native 描述性回归、预测分差 bucket、Normal/Deep Spread 分桶、PnL 集中度、联赛 Market Freshness 和 Ridge/校准审计状态。

`UNDERDOG_DIRECTION_BIAS` 与 `SEVERE_UNDERDOG_DIRECTION_BIAS` 只能报警，不能自动平衡上下盘、强制 Favorite、修改具体 Fair Spread、改变 Edge 门槛、Residual Scale、市场权重或 Champion。若样本不足以分离 OOS、Walk-forward 与 Prospective，应明确输出 `NOT_ENOUGH_SEPARATE_OOS_WINDOWS`，不得把同一批前瞻样本拟合后的 slope 当成验证结果。

概率一致性必须逐场检查 `P(home cover) + P(away cover) + P(push) ≈ 1`，并保留 Counterfactual Favorite 的概率/EV；发现 sign、home/away 或方向转换异常时只记录审计，不回写历史决定。深盘 `15+` 的小样本收益必须标记 `SMALL_SAMPLE_OUTLIER`，总体收益集中在少数交易时标记 `PNL_CONCENTRATION_HIGH`。真实执行继续永久关闭，任何审计结果不得因单日 W/L 自动调参。

## v3.9 四层 Shadow Learning 与 Evidence Gate 验证

现有正式 Paper/Champion 不改阈值，继续使用每队至少 8 场、至少 3 个不同对手及现有证据门禁。新增四层必须明确分开：`RESEARCH_SIGNAL` 只验证冻结方向；`PROVISIONAL_SHADOW` 只允许核心定价完整、已有真实盘口和现有 Edge、缺失主要属于 Soft Evidence 的前瞻学习；`QUALIFIED_SHADOW` 等同当前严格正式 Paper；`EXECUTABLE` 保留但真实执行永久关闭。Lean 只能是 `LEAN_RESEARCH`，No Edge 继续不推荐。

`MODEL_EVIDENCE_NOT_PAPER_ELIGIBLE` 不得再作为新记录的泛化原因。至少拆分并分类：`HISTORY_ESS_TOO_LOW`、`OPPONENT_DIVERSITY_TOO_LOW`、`TEAM_HISTORY_FEED_NOT_CAPTURED`、`ROSTER_STABILITY_UNKNOWN`、`LINEUP_UNKNOWN`、`INJURY_UNKNOWN`、`PACE_EVIDENCE_MISSING`、`LEAGUE_RULE_UNKNOWN`、`MARKET_RULE_AMBIGUOUS`、`MODEL_CORE_INPUT_MISSING`、`SOURCE_CONFLICT`；分类只能是 `HARD_BLOCK`、`SOFT_MISSING` 或 `DATA_PIPELINE_FAILURE`。球队映射、影响盘口含义的规则、方向歧义、无真实市场、无独立价格、严重源冲突、未来数据泄漏和核心输入缺失继续阻止所有 Paper。

Soft Missing 不得让有真实 Edge 的样本永久消失。阵容稳定性未知、轮换未知、伤停未知、有限本季历史、低对手多样性、Cold Start、部分三分、末节犯规和 OT 证据不足可进入 `PROVISIONAL_SHADOW`，但必须保存 `uncertainty_penalty`、`provisional_residual_scale_multiplier`、`confidence_penalty`，且不得改变 Champion、Edge、Probability 或 EV 门槛。对应配置唯一来源为 `config/shadow_learning_policy.json`。

### Provisional 账本隔离红线

`PROVISIONAL_SHADOW` 只能写入 `ledger/repair_v22_provisional/<run_id>`，结算只能写入 `ledger/repair_v22_provisional_settlements`，收益字段只能是 `provisional_pnl`。它不得设置正式 `decision.triggered=true`，不得写入 `ledger/repair_v22_settlements`，不得拥有非空 `paper_pnl`。研究反事实记录另写 `ledger/repair_v22_research` 及其 settlements。

**用户授权的正式手动总账例外（2026-10-08）**：物理源账本、首写和结算文件仍保持不动，但生成派生的`formal_manual_live`统一正式统计索引，纳入`QUALIFIED_SHADOW`、`PROVISIONAL_SHADOW`和`TITAN_PROVISIONAL_SHADOW`的历史及后续`FORWARD_NATIVE`首写，并按“双方球队+开赛时间+市场”去重；`RESEARCH_SIGNAL`仍不纳入。统一总账须同时展示来源层拆分及合计。未补录人工成交时，盈亏按冻结盘口的一单位手动账面结算，不能冒充券商成交回单。

四层统计必须分别输出 `N`、`W-L-P`、`PnL`、`ROI`、`CLV`、`MAE`、`RMSE`、`Brier`、`Calibration` 和 Max Drawdown。`calibration/shadow_learning_analytics.json` 与 `calibration/gate_validation.json` 只从不可变首写和独立结算派生；Gate Validation 按 Evidence Reason 统计反事实结果。Gate Challenger 最少 50 个独立 Forward Native 样本，检查 CLV、ROI、Brier、MAE、回撤和校准后才可人工评审，禁止自动晋升。

### ESS 与历史链性能

历史必须输出 `raw -> alias -> competition -> cutoff -> valid -> usable` 瀑布、`history_ess`、Kish `effective_sample_size` 以及 `effective_opponent_diversity`。EuroLeague Team State History 可按可审计权重借用国内联赛、杯赛、EuroCup 和季前赛，必须同时施加 competition adjustment、time decay 和 opponent diversity；不同赛事不得直接平均。Australia NBL 的 `TEAM_HISTORY_FEED_NOT_CAPTURED` 必须归为 `DATA_PIPELINE_FAILURE` 并显示 source/fallback 状态，不得伪装成模型风险。

ESS、时间衰减与对手多样性必须对本轮已载入的 history 列表一次遍历完成。严禁在球队、比赛或联赛循环中反复读取历史 `.js`/JSON；源文件只能在采集/索引阶段读取一次，再以内存结构复用。正式 Champion 的 8 场/3 对手门槛本版不自动修改，ESS 与加权多样性先作为 Gate Challenger 和 Provisional 证据。

### Pace Level B 安全派生

总分回合证据分为：Level A 直接 Pace；Level B 完整 Box Score 派生；Level C 部分数据加联赛 prior 并扩大不确定性；Level D 核心输入不足。Level B 唯一公式为 `Possessions ≈ FGA + 0.44 × FTA - ORB + TOV`，必须同时取得双方可复算字段后取 game pace estimate，并保存 `pace_source=DERIVED_BOX_SCORE`。任何一方缺 FGA、FTA、ORB 或 TOV、字段非数值或结果异常时，必须用安全 `.get` 验证并降级为 Level C（仅在真实 league prior 存在时）或 Level D；绝对不能抛出 `KeyError` 使整场或整次更新崩溃。

末节犯规、OT、三分与伤停缺失在基础 Pace/攻防成立时属于 Soft Missing，只扩大总分残差并记录不确定性。Level D 仍只能 Research/Diagnostic。每日页面和 JSON 必须展示 Comparable、Edge、Qualified、Provisional、Research-only Edge、Lean、No Edge，以及 Tier 3 和 Total 的 Level/Pace 分解；日期、Pricing Funnel、事件和 snapshot 必须保持同一北京时间日期。

## Source-Agnostic Evidence 与 Titan Ladder（v4.1）

所有来源先进入 `SOURCE -> NORMALIZED EVIDENCE / FEATURE STORE -> PRICING -> EVIDENCE GATE -> EDGE/PAPER`。Champion、Titan Technical Challenger 和后续 Challenger 只能读取标准化证据；Evidence Gate 不得按来源名称判断资格。`scripts/titan007_evidence_bridge.py` 必须从既有 `titan007_history.sqlite` 完成 canonical team、competition、cutoff、终场比分一致性、原始快照、去重和可用性校验，并将累计事实写入 `normalized_history` 后注入 Champion 的同一历史池。不得另建篮球系统或并行维护互不承认的 Champion/Titan 历史世界。

每场必须生成 `pregame_evidence_bundle`，至少分为 IDENTITY、HISTORY、PACE、EFFICIENCY、FOUR_FACTORS、ROTATION、RULE、MARKET、DATA_QUALITY。每个证据字段保存 `value/source/source_timestamp/cutoff_valid/quality/raw_ref`。公平价冻结前 MARKET 保持未加载；冻结后才附加真实盘口合同，且必须明确 `market_inputs_used_in_fair_price=false`。比赛规则与博彩公司是否含加时的结算合同分别验证。

正式历史门槛仍是每队同赛事截止前有效终场至少 8 场、至少 3 个不同对手。满足同等真实性、身份、截止时间与去重合同的 Titan、7M 或其它生产源必须获得同等资格；不得继续要求旧 Champion 来源名称。Titan 已满足而 Champion 仍返回历史不足时必须标记 `SOURCE_BRIDGE_FAILURE` 并中止宣称修复完成。

Titan 模型治理阶梯固定为 `TITAN_RESEARCH_PRICE -> TITAN_PROVISIONAL_SHADOW -> TITAN_QUALIFIED_ELIGIBLE -> TITAN_CHAMPION_ELIGIBLE`。Titan Fair Line 不能自动触发 Qualified；只有完整核心证据、完整真实市场合同和不变的 Edge/EV 门槛均通过，但模型尚未通过严格 Forward Native OOS 晋升时，才进入 `TITAN_PROVISIONAL_SHADOW`。该层只写 `ledger/titan_provisional/<run_id>` 与 `ledger/titan_provisional_settlements`，收益字段只能是 `provisional_pnl`，不得写正式 Paper 账本、不得产生 `paper_pnl`、不得计入主策略 PnL/ROI/CLV。只有 Line 没有双边赔率时仅记 `LINE_EDGE_RESEARCH`，不能计算正式 EV。

Titan 球员比赛分钟与首发可形成最近 3/5/10 场 Rotation Continuity，包括 starter continuity、top5/top8 minutes share、player appearances、minutes concentration 与 returning minutes。它只能证明历史轮换稳定；`current_availability` 必须独立保存为 KNOWN/UNKNOWN。Tier 3 在近30日真实分钟证据满足既有政策时可满足 Roster Stability，但不得把历史连续性冒充当日无伤病。

同一冻结 Box Score 若含双方完整 FGA/FTA/ORB/TOV，按 `FGA + 0.44×FTA - ORB + TOV` 进入 PACE Level B；Titan Technical Model 能读取的同一证据必须同时供 Total Evidence Gate 使用。模型有 Pace 而 Gate 仍报缺失时标记 `EVIDENCE_PIPELINE_DISCONNECT`。3PA/3PM、PF、opponent FTA、Four Factors 与 Net Rating 同样保留来源链。盘口盘路、赢盘率、大小盘历史继续只属于 Market Analytics。

每日验收必须输出 `audits/unified_evidence_audit.json`，逐场列出 Titan 理论价、Titan/其它来源 History Ready、Unified Evidence Ready、Champion Priceable、Titan Ladder、Qualified 和未升级精确原因，并回答理论价、History Gate、Unified Ready、Champion Priceable、Titan Provisional、Qualified、Research-only、No Market、No Edge、历史桥接修复、NBL History Feed、Possessions、Game Rule、Rotation Continuity 和剩余真实阻塞共15项。Dashboard 顶部必须同时显示 Qualified Paper、Titan Provisional、Research Edge、Lean；两类账本分色、分账且默认可直接筛选。

Challenger 页面必须分别显示 Raw Score Ridge、Score Ridge + Titan Pace、Pace + Efficiency、Four Factors、Matchup/Tactical、Titan Possession-Efficiency 和 Ensemble。禁止无 OOS 依据的简单平均；Ensemble 未经严格 Walk-forward 只可标记 Challenger，不得自动晋升。晋升优先比较 Spread/Total MAE、Bias、Slope，再看 CLV，最后看 ROI；单日盈亏不得触发晋升。

## v4.2 攻防效率与 MatchupAdj 正式定价规则

当前 Model B 不得再把进攻效率与对手防守效率简单做 `50/50` 平均后作为 Titan Fair Price。该平均只能作为没有足够校准样本时明确标记为 `BASELINE_PRIOR` 的回退先验。正式链路使用：

```text
ExpectedPPP_home = μ
  + βO × (AdjORtg_home - μ)
  + βD × (AdjDRtg_away - μ)
  + MatchupAdj

MatchupAdj = β1×ΔeFG + β2×ΔTOV + β3×ΔORB + β4×ΔFTr + β5×Δ3PA
```

客队使用对称的进攻/防守输入，并反转 MatchupAdj。`μ` 为截止时点的联赛平均 PPP；最终比分必须继续使用 `Expected Possessions × Expected PPP`，主场优势只在比分层按既有环境字段加入，不能倒灌到历史攻防效率。

β 参数只能由不读取盘口的逐场 walk-forward/OOS 历史样本拟合：每一场训练观察只能使用该场开赛前的球队状态和联赛均值，当前比赛之后的数据不得进入。校准来源按固定层级选择：联赛有效观察数达到 `30` 才用 `LEAGUE_WALK_FORWARD`；否则全篮球历史达到 `60` 才用 `GLOBAL_WALK_FORWARD`；再不足才用 `BASELINE_PRIOR`。样本数、截止时间、来源、`walk_forward_oos`、参数和五项 MatchupAdj 输入必须写入 `model_b`、`top_factors`、冻结 snapshot 和每日审计。

效率校准不能改变正式历史门槛、残差 scale、Edge/EV 门槛、Paper 晋升或真实执行状态。盘口只在公平价冻结后进入比较链，`market_inputs_used=false` 必须在效率校准与理论价上下文中保持可审计。所有 β 计算应复用当前轮已经载入的历史内存/缓存，不能在球队或比赛循环中反复读取原始 JSON/JS。

## v4.3 NBA/CBA Spread Context Adjustment 规则

本规则只修改 NBA、CBA 常规赛和 CBA 季后赛的 Spread 上下文处理，并向其它联赛推广同一“缺失增加不确定性、不自动清零公平价”的原则。`injury_status`、`rotation_or_expected_minutes`、`net_rating_context` 是 `VALUABLE_CONTEXT`，不再是 NBA/CBA Spread 的 `MANDATORY_EXISTENCE_GATE`；三项缺失不得单独产生 `SPREAD_CONTEXT_INCOMPLETE`，不得单独禁止 `PAPER_ENTRY`。

Spread 必须先生成 `BASE_FAIR_SPREAD`：历史比分模型、对手调整、Titan Pace/Efficiency、主场和休息因素优先形成独立基础价。伤停、球员可用性、预计分钟、轮换与当前球队强度只能按下列顺序作为调整层：

```text
BASE FAIR
→ PLAYER AVAILABILITY ADJUSTMENT
→ ROTATION ADJUSTMENT
→ CURRENT TEAM STRENGTH ADJUSTMENT
→ FINAL FAIR SPREAD
```

只有截止时点存在明确的数值调整证据才可 `adjustment_applied=true`。没有新闻不能写成 0；必须写 `UNKNOWN`、`value_points=null`、`adjustment_applied=false`、`reason=DATA_UNAVAILABLE`。明确的 `KNOWN_NO_INJURY` 才能记录无伤停，不得把“未找到信息”当作全员健康。Adjustment 层与当前 Champion 基础价、历史首写决定和旧 Paper 完全隔离，不回写历史输赢。

伤停或轮换未知时，只扩大 Spread 的残差尺度并保留可审计分解：`base × league × cold_start × context`。`injury_uncertainty_multiplier`、`rotation_uncertainty_multiplier`、`season_regime_multiplier` 和最终 `spread_residual_scale` 必须逐场输出。组合方式由 `config/spread_context_uncertainty_policy.json` 控制，默认采用 `MAX_OF_CONTEXT_PENALTIES`，避免多次对同一不确定性重复惩罚；这些值只是可审计 prior，必须在 OOS 样本充足后再学习，不能宣称为经验真值。

Titan Box Score 若能得到 ORtg 和 DRtg，必须自行生成 `NetRtg = ORtg - DRtg`，并记录 `net_rating_source=DERIVED_TITAN`。Net Rating 缺失时，Champion 仍可使用 Score Ridge、Titan efficiency、ORtg/DRtg 和 current-season team state，只要仍能形成独立基础公平价。

没有 `expected_minutes` 时，Titan 最近 3/5/10 场的首发、分钟和出场记录可形成 `rotation_continuity`、`top5_minutes_share`、`top8_minutes_share`、`starter_continuity` 和 `player_appearances`。这些是阵容稳定性证据，不得冒充当天预计分钟；它们只能降低不确定性，不能生成虚假的当日可用性。

`PRESEASON` 和 `SUMMER_LEAGUE` 允许使用上赛季历史、Titan 最新技术数据、已发生比赛和 Rotation Continuity 生成 Fair Spread，但分别标记 `season_regime` 与 `HIGH` 不确定性，按配置降低旧历史权重、扩大残差并压缩概率；不自动禁止 Paper。`DATA_QUALITY_A/B/C` 均可进入 Edge 计算，`DATA_QUALITY_D` 仅 Research-only。真正 Hard Block 仅保留：身份无法确认、真实 Spread 盘口不存在、盘口方向/球队顺序无法确认、结算规则严重不明、无法形成独立 Fair Spread、严重 source conflict、未来数据泄漏或基础历史/篮球数据不足以运行模型。
## v4.4 Fair Center / Outcome Residual / EV 审计规则

本版本增加让分概率审计，但不扩大赛事覆盖、不降低既有 Edge/EV/Champion 门槛，也不把审计卡片自动变成 Paper。每场让分必须同时保存：`raw_fair_spread`、`calibrated_fair_spread`（未实现时保持 `null`）、Fair Center 标准误、80%/95% Fair Center 区间，以及独立的 Game Outcome 80%/95% 预测区间。前者回答“公平价估计有多不确定”，后者回答“比赛结果在公平价周围可能波动多大”，两者禁止混为一个 residual。

Fair Center 区间优先由已载入历史的时间块 bootstrap 生成；历史按时间块重采样，禁止以盘口或当前比赛之后的数据进入公平价。Game Outcome residual 只能来自严格 OOS/Forward Native 首写结算记录，写入追加式 `calibration/oos_spread_residuals.jsonl`，按 `prediction_id` 去重且不可回写旧记录。OOS 样本达到联赛级门槛时使用联赛 Student-t 经验分布，样本不足按 `league -> global -> tier -> cold-start prior` 层级回退；每次必须显示来源、N、df、scale 和 `fit_status`。

让分方向必须按整数结算，显式统计 `W/P/L`，并保留走盘。十进制赔率的无走盘 break-even 为 `1/odds`；含走盘的 break-even 为 `((1-push)*odds + push - 1) = 0` 的可审计表达。概率 Edge、Line Edge 与 EV 只在盘口冻结后计算，EV 使用 `p_win*(odds-1)-p_loss`（走盘收益为 0），不得反向修改 Fair Price 或正式门槛。

每个方向还需输出 80% 区间方向稳健性、市场分歧百分位、盘口路径（可用节点才填值）、收敛/发散与 information risk。市场信息只用于公平价冻结后的诊断；缺失路径不能伪造，不能以市场反推模型。概率质量另行输出 Brier、LogLoss、ECE 和 fair-line calibration；没有真实 OOS 结果时保持空值而不是补算。

页面单独展示 `Spread Probability / EV` 只读区块，且与 Qualified Paper、`PROVISIONAL_SHADOW` 和研究记录分开。`PROVISIONAL_SHADOW` 的 PnL、ROI、CLV 永远不得进入正式 Paper 或主策略长期收益；真实执行永久关闭。每日必须写入 `diagnostics/uncertainty_audit_YYYYMMDD.json`、`diagnostics/comparable_edge_YYYY-MM-DD.csv` 和 `diagnostics/spread_probability_ev_validation.md`，并在运行漏斗与审计报告如实记录样本不足、历史阻塞、数据源失败和未完成字段。

## v4.5 Model-implied EV / Empirical Expected Return 分离与 Probability Health

`MODEL_IMPLIED_EV` 与 `EMPIRICAL_EXPECTED_RETURN` 是两个不同字段、不同样本世界和不同治理状态。前者只按冻结盘口、十进制赔率和模型 `W/P/L` 概率计算：`p_win × (odds - 1) - p_loss`；后者只能来自同市场类型、同口径 Forward Native / 严格 OOS / walk-forward 的已结算首写样本，不能由当前盘口、市场隐含概率、近期连续红黑或模型 EV 反推。

经验收益采用固定样本门槛：`N<20=MODEL_ONLY`（经验收益点估计必须为 null）、`20-49=EARLY_EMPIRICAL`、`50-99=PROVISIONAL_EMPIRICAL`、`>=100=EMPIRICAL_ESTIMATE`。每场必须显示 `sample_N/source/governance`；相似样本不足时按 `同联赛+同市场+同赛季阶段 -> 同赛季阶段+同市场 -> 同市场 -> 同层级+同市场 -> 全局同市场` 回退，并明确 `FALLBACK_*`，禁止静默混入非相似样本。经验收益需同时输出均值、中位数、Bootstrap 95% 区间和最大回撤，分 Spread/Total、联赛、赛季阶段、方向、主客/让分深度、概率桶与 Edge 桶保存。

让分和大小分残差分开治理；`PRESEASON / REGULAR / PLAYOFF / SUMMER_LEAGUE` 分开分组并支持层级收缩。每场保存 `residual_source/residual_N/df/scale/fit_status`，Fair Center 标准误/区间与实际结果 residual 区间绝不合并。当前模型未显式建模主场优势时必须写 `HOME_COURT_NOT_MODELLED`，并将主场变量保留为未通过的 challenger，而不是伪造为 0。

概率审计必须输出概率来源、raw/calibrated 概率（未校准则为 null）、W/P/L、无走盘及含走盘 break-even、Brier、LogLoss、ECE、概率桶校准差和过度自信标记。模型与市场分歧使用历史百分位；让分同时保留 `raw_team1_line_gap` 与 `selected_side_line_edge_points`，后者大于 0 才表示对所选方向有利。所有字段均为只读派生审计，不回写历史首写账本、不自动调参、不因近期红黑改变模型参数。

每日写入 `diagnostics/probability_ev_empirical_validation.md/json`、`uncertainty_audit_YYYYMMDD.json`、`comparable_edge_YYYY-MM-DD.csv`；Dashboard 单独显示 Probability Health / Model vs Empirical。真实执行继续关闭。

## v4.6 手动实盘模式

用户明确要求后，`FORWARD_NATIVE` 新信号进入 `MANUAL_LIVE_CANDIDATE`：页面按“手动实盘候选”展示，`real_execution_allowed=true` 仅表示允许人工依据冻结方向下单；`automated_execution_allowed=false`、`manual_order_required=true`，系统不得调用任何自动下注接口。`real_bet_flag` 和真实成交信息只有在人工补录确认后才能为真，不得由模型触发自动填写。重复首写、盘口失效、比赛开始、规则不明和所有既有 Hard Block 继续禁止进入手动实盘候选。历史纸面首写记录不可回写；切换只对后续 `FORWARD_NATIVE` 运行生效。


## v4.10 日更编排、回填与 GitHub/飞书交付合同

本节把 2026-10-13 实际日更中暴露的错误固化为生产顺序。它不改变 Fair Line、概率、Evidence Gate、Edge/EV 阈值、纸面账本口径或真实资金关闭原则，只规定采集、回填、展示和交付的可重复编排。

### 固定的日更顺序

1. **先结算、后生成当天候选。** 每轮启动先扫描所有不可变前向首写和待结算记录，优先回填前一日及更早已结束比赛的最终比分、加时口径、赛果来源 URL、settlement_id 和 PnL。只补齐仍为 PENDING 的记录；不得重写首写盘口、方向、赔率、冻结输入哈希或历史结论。结算结果必须同步到对应日期 JSON、latest.json、累计 Excel 和 HTML 的同一市场行。
2. **再发现和抓取目标日。** 赛事库存按 canonical event 保留。次日盘口尚未发布时写 NO_MARKET/UNPRICEABLE、inventory_retained=true、next_market_retry_at 和 source health，不得从事件清单删除，也不得把空响应当作 0 盘口。HTTP 请求统一走指数退避，并记录每次 URL、状态码、异常、耗时和重试序号。
3. **再做统一实体和盘口匹配。** 先用 canonical_team_id、competition_key、gender、阶段和“双方规范化主客队 + 开赛时间 ±5 分钟”连续性键合并 7M/Titan/ESPN/SofaScore。来源名称不同不能产生两场比赛或两种相反结论；身份无法唯一确认时停在 SOURCE_CONFLICT/CANONICALIZATION_MISMATCH，而不是猜测合并。展示名称优先使用注册表中的中文名，原始英文名仅保留在审计字段。
4. **最后定价和发布。** 当前挂牌必须经过本轮实际验证、比赛未开始、结算规则明确和 TTL 检查才参与定价；收到时间、报价变动时间和当前挂牌确认时间分开保存。生成 JSON、Excel、HTML 后做一致性检查：canonical event 不重复、赛事数与漏斗一致、同赛事多市场不丢失、赛果颜色/中文名/列宽契约成立。Excel 有公式时先以 LibreOffice 或等价引擎重算缓存，再原子替换正式文件。

### 联赛和历史统计口径

NBA、NBA季前、NBA常规赛、NBA季后赛统一使用 league_key=NBA 做同联赛累计胜率和盈亏；season_phase 仍单独保留用于审计和分组诊断。其它同一联赛的季前、常规、季后也遵循同样规则，除非用户明确要求阶段隔离。墨联、日B联赛、瑞典甲等必须通过联赛别名注册表归并，不能因网页具体名称不同而显示“无样本”。

### 幂等、性能和页面验收

同一 target_date 重跑必须只追加新的原始快照和新的健康审计，不复制 event、首写或 settlement。历史、Box Score 和赛程基线在初始化阶段一次读取并构建内存索引，逐场循环禁止再次读 JSON/JS；SQLite 查询必须命中复合索引；非核心诊断仅在内容签名变化时写盘。每轮必须记录开始/结束时间、HTTP 尝试与成功数、缓存命中、索引加载耗时、定价耗时和发布耗时，连续超时或失败不能静默成功。
早间运行必须把 gh-pages 中同一 target_date 的已发布 JSON 作为上一轮赛事库存续接，再与当前源按 canonical continuity key 合并；源端日期文件滚动导致的缺场只能标记为当前源未观察到并保留 `NO_MARKET`，不得从页面删除。

HTML 顶部只显示本轮真实 paper_bettable，历史胜率/盈亏按 league_key 统计并支持展开/收起；同赛事历史按 canonical event/team，而不是网页字符串。所有结束比赛必须显示比分，W/L/P 使用稳定颜色，行宽和中文名由固定渲染契约验证。公开 URL 的缓存参数只能用于刷新浏览器，不能改变数据日期。

### GitHub Actions 与飞书通知

生产仓库的 .github/workflows/basketball-daily.yml 使用 0 21 * * *（UTC，即北京时间每天 05:00）生成当天版本，并使用 0 12 * * *（UTC，即北京时间每天 20:00）自动把目标日期设为次日，生成次日版本；同时支持 workflow_dispatch.target_date 重跑指定北京时间日期。工作流从 main 运行引擎，从 gh-pages 种子化最近状态，生成目标日 JSON/HTML 后提交 gh-pages；提交前保留并合并并发产生的最新页面状态，避免覆盖足球或人工更新。提交得到的 SHA 必须写入步骤输出并等待 Pages workflow 对该 SHA 返回 completed/success，只有部署成功或页面已是最新时才发送飞书页面链接。

飞书只读取 GitHub Secret FEISHU_WEBHOOK，禁止把 webhook 写入仓库、日志、数据或 HTML。通知至少包含北京时间日期、运行状态、赛事数、纸面可投数、Pages 状态、发布提交短 SHA、Actions 运行链接和 https://simondongxiao.github.io/odds/basketball-v2.html。引擎失败时也发送失败状态；发送失败按 2/4 秒重试三次并把原因留在 Actions 日志。真实资金执行永久关闭。

### 每轮最低验收

- python -m py_compile automation/*.py basketball_engine/scripts/run_basketball_daily.py 通过；
- python D:\codex\skills\skill-creator\scripts\quick_validate.py D:\codex\skills\basketball-odds-trader 通过；
- 目标日与前一日回填 JSON 中 event、settlement、league_key、中文展示名可按 canonical key 对齐；
- NO_MARKET 赛事仍在库存，429/空响应有退避审计；
- gh-pages 提交后 Pages 成功，飞书消息只在此后发送；
- 任何失败不得删除不可变账本、历史档案或把 PENDING 伪装成已结算。

## v4.13 日本 B.League 盘口连续性与稳定抓取

`JAPAN_BLEAGUE` 必须统一覆盖 7M 的 `日B1`、`日B2`、`日B3`、日本男子 B 联赛展示名及英文 `B.League`。目标日和次日的日本 B.League 赛事先进入库存，再进入详情、历史和技术统计预热；不得因为次日 `comlive_*.js` 尚未列出盘口而删除赛事。

7M 当前盘口板以 `comlive_0/1/2/3/4.js` 为唯一当前板入口。HTTP 返回非空不等于目标赛事已经挂牌；当已识别的日本 B.League 赛事没有任何当前板报价时，按 2 秒、4 秒做最多两轮目标赛事重试，并在 `deep_capture_audit.japan_b_league_market_retry` 中记录候选、每轮 URL/解析数、命中赛事和未解决赛事。历史赔率页不得作为当前盘口回退，未命中仍写 `NO_MARKET` 并保留 `inventory_retained`。

当 7M 当前板在目标日明确返回空目标行时，允许使用 Betmonitor 日本 B.League 当前赔率比较页作为受控补源。补源只读取 `japan-b-league-1/10007979` 的当日赛事页及其 `content/get_odds.php` 当前盘口响应，按注册表英文/中文别名、主客顺序和开赛时间 ±5 分钟匹配；让分与大小分必须分别抓取主线，不能把独立盘口的空缺当成整场空缺。每个补源报价必须保存原始 HTML、哈希、请求 URL、收到时间、当前挂牌确认、公司名、主线、十进制双边赔率和 `BETMONITOR` feed_provider，并进入同一 `quote_state`/Evidence Gate；不读取 Betmonitor 历史赛果或历史赔率，不覆盖已有 7M 同市场报价。补源失败、名称无法唯一匹配或盘口响应只有空壳时仍写 `NO_MARKET`，并在 `deep_capture_audit.betmonitor_japan_b_league_fallback` 留下原因。

同一场日本 B.League 的当前盘口只能按 `canonical_event_id` 与 7M 赛事 ID 关联，方向仍须经过主客顺序和 `hadFlag`/公司合同核验。重跑 10/11 及更早日期时，已写入的盘口、首写方向、结算和 PnL 视为不可变历史，不得因当前板过期或日期滚动被清空。

## v4.14 多源盘口恢复合同（防止单一网站空抓）

任何一场目标日赛事都不得把“7M 当前板没有返回”直接当作“当天没有盘口”。盘口采集必须使用按市场拆分的多源恢复链，并在本轮采集内完成：

1. **主源与补源顺序固定但允许并行预热。** 先抓 7M `comlive_0/1/2/3/4.js` 和详情页；目标赛事未命中时，按同一 `canonical_event_id` 继续抓 Titan007 当前盘口接口；仍未命中时抓 Betmonitor 当日赛事页及 `content/get_odds.php`；再未命中时调用已验证的公开赔率比较适配器（如 OddsPortal/Flashscore/其它配置在 `config/source_capabilities.yaml` 中标记为 `CURRENT_MARKET=TRUE` 的站点）。ESPN、SofaScore、FIBA 等只能作为赛程、球队身份或比分补源，除非运行时证据证明它们返回当前让分/大小分，否则不得声称有盘口。新站点必须先做小样本适配器验证，再进入生产源池。
2. **让分和大小分分别恢复。** 每个来源对 `SPREAD`、`TOTAL` 独立记录 `FOUND / EMPTY / PARSE_ERROR / RATE_LIMIT / BLOCKED`；一个市场抓到不代表另一市场抓到。主源只缺大小分时，只对 `TOTAL` 走补源；严禁把半场线、历史赔率、模型 Fair Line 或旧快照冒充当前全场主线。
3. **分层重试与时间窗口。** 每个源首次失败后按 2 秒、4 秒、8 秒、16 秒退避，最多 5 次；空响应、429、5xx、连接重置和解析到 0 条目标行都要重试。早间运行在北京时间 05:00 后至少保留一次 20–40 分钟内的目标赛事重查，晚间 20:00 运行同时预抓次日赛事；距离开赛不足 6 小时的 `NO_MARKET` 赛事必须在下一来源完成后再次轮询。所有重试必须记录 URL、源、市场、状态码、响应哈希、耗时、重试序号、下一次时间和停止原因。
4. **跨源对账后才允许入价。** 报价必须通过规范化主客队、`competition_key`、性别、阶段和开赛时间 ±5 分钟匹配。至少一个来源的当前盘口验证通过（本轮收到、盘口变动时间、仍挂牌确认均在 TTL 内）才进入定价；多源同线冲突时保留全部原始报价，按来源优先级和时间做可审计选择，方向冲突先回到主客顺序校正，不能静默取平均或任选一边。
5. **不丢赛事、不伪造盘口。** 所有来源耗尽仍未得到当前报价时，赛事和两个市场仍保留在库存，分别写 `NO_MARKET`/`UNPRICEABLE`、`inventory_retained=true`、`next_market_retry_at` 和 `market_recovery_exhausted=true`，并把每个源的失败原因写入 `deep_capture_audit.multi_source_market_recovery`。这表示“本轮所有配置来源均未验证到当前线”，不能写成“无盘口”、不能生成虚拟盘口，也不能删掉赛事。
6. **生产门槛。** 新增来源只有在连续三轮目标日采集都能解析出真实公司、主线、双边十进制赔率、收到时间和当前挂牌确认后，才可标记 `PRODUCTION_VERIFIED`；否则保持 `EXPERIMENTAL`，只用于诊断，不影响既有 Evidence Gate。每日审计必须同时输出来源覆盖率、各市场恢复率、首次命中来源、补源命中数、仍未命中赛事清单和下一次重试时间。

该合同只扩大盘口发现与恢复，不降低实体消歧、盘口有效期、规则、Evidence Gate、Edge/EV、纸面可投或真实资金关闭要求；任何来源都不能用历史赔率替代当前盘口。

## v4.15 日更耗时控制合同

每轮运行必须先读取上一轮的 `stage_timings`，不能把超过 20 分钟的网络等待当作正常。历史库和源快照必须跨 GitHub Actions 运行复用：`reference_data/titan007_history` 使用带版本哈希的 Actions cache，缓存命中时只刷新过期或缺失的原始响应；team mapping 复用精确命中，team detail 24 小时 TTL，team schedule 10 小时 TTL，box score/period 直接复用数据库已验证记录。缓存只复用哈希校验通过的原始证据，不能改变历史首写或当前盘口 TTL。

彼此独立的 ESPN、SofaScore、FIBA 赛程发现请求使用有界并发；盘口、实体匹配和历史定价仍按既定依赖顺序执行。每轮审计必须记录 `cache_reuse_by_stage`、网络请求数、缓存命中数及 `reference_database_update_seconds`、`market_identity_global_collection_seconds`、`collect_live_total_seconds`。目标是缓存后的常规日更控制在 20 分钟内；若连续两轮超过 30 分钟，自动按阶段报告并优先修复重复网络抓取，不能靠减少证据门槛或删除赛事来缩短时间。

## v4.16 KBL补源与Edge门槛可审计化

韩国KBL当前板不得因7M/Titan缺行直接写成无盘口。对`KOREA_KBL`目标赛事，先保留7M与Titan结果，再使用公开Cloudbet KBL SSR赛事页作为实验性补源；只接受页面同一轮返回的全场让分/总分主线、双边十进制赔率、当前挂牌状态、收到时间和原始HTML哈希。Cloudbet使用显式中英文/韩文注册别名和双方规范化身份+开赛时间±5分钟匹配，补源状态写入`deep_capture_audit.cloudbet_kbl_fallback`，连续三轮目标日验证后才能升级为`PRODUCTION_VERIFIED`。补源只能扩大盘口发现，不能用来绕过Evidence、盘口新鲜度或真实资金关闭。

`Probability Edge`、`Line Edge`和`EV`必须分开显示。正式`手动实盘候选`的Edge Gate固定为：保守情景`adverse_ev >= 2.5%`且条件概率Edge`conditional_edge >= league_buffer`（CLUB_MATURE为2.5%，其它模型族沿用各自buffer）。普通EV为正但保守EV为负的记录只能显示为`LEAN/研究信号`，不得因为“明天比赛多”自动升级；每条比较结果必须输出`edge_gate`，分别列出两个子门槛、通过/未通过状态及值域。伤停、轮换、三分 profile、末节犯规、胶着/垃圾时间样本属于不确定性说明；只有`paper_evidence_blockers`、当前盘口有效性、规则冲突、严重来源冲突和正式Edge Gate才能阻塞正式候选。
