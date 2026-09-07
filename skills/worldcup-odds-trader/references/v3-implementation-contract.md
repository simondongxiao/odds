# 亚盘量化 v3.2.1：数据、信号、风控与执行契约

版本：asian-risk-v3.2.1-20260908。适用于新决策；不重写历史计划。核心规则见[选边风控标准](asian-side-risk-v3.md)，最新改向与撤回周末加严见[临场变盘细则](market-move-weekend.md)。这是可以交给开发人员实施的工作流，不代表已开通飞书或真实下单服务。

## 0. 单一流水线与权限边界

原始数据 -> 时间/市场对齐 -> 双方隐性基本面 -> 独立比分分布 -> Delta/意图双检 -> 截止当时的标签/微观统计 -> 当前水位EV -> 同档/近期/集中度/日风控 -> 保守仓位 -> 冻结计划 -> HTML/飞书 -> 执行前复核 -> 回执 -> 按日结算。

Python计算一次，HTML和飞书读取同一个decision_id与decision_hash；前端不得重新查全历史来选队。新规则默认SHADOW，旧版可投计划独立保留，不冒充已通过v3。READY仅表示计划满足规则，不等于已成交。真实执行还需要用户授权、正确平台、有效报价及回执。

## 1. 数据输入层

### 必须抓取的盘口原始字段

每家机构每次抓取分别保存，字段不得用其他机构的最高报价拼接。

| 数据对象 | 字段及类型 | 缺失/错误时处理 |
|---|---|---|
| 比赛身份 | match_id、source_match_id、list_date、region、country、competition_id/name、tier/cup、home_id/name、away_id/name：文本 | 无稳定ID不得自动合并；list_date第一次归属冻结 |
| 时钟 | kickoff_at、quoted_at、observed_at、available_at：带时区时间；period=90m；state=pre/live/closed | 缺源报价时间标未知，不宣称实时；不得混用滚球和赛前 |
| 欧赔初/即 | eu_open_home/draw/away、eu_now_home/draw/away：decimal浮点；bookmaker_id；open_snapshot_id；current_snapshot_id | 赔率必须>1；逐机构去水后形成共识 |
| 亚盘初/即 | ah_open/now_home_hcap、有符号主队让球；ah_open/now_home_water、away_water：HK浮点 | 给让为负、受让为正；两边同一档位；缺一侧水位不能做转换校验 |
| 大小球初/即 | total_open/now_line、over_water、under_water；对应机构和时钟 | 没有真实总进球约束不能默认2.5补入深盘模型 |
| 执行报价 | venue、market/selection_id、line、water、market_status、minimum_stake、maximum_stake、quote_valid_until | 聚合报价可研究；未经指定平台验证不能报真实执行金额 |
| 原始留底 | source_url、raw_file、raw_hash、source_revision、ingest_version | 供应商修订初赔只追加revision，不覆盖首次观测 |

数值导出保留4位小数，胜率保存0-1、Delta保存概率差（0.03=3个百分点）；金额向下取至分。内部计算不先行四舍五入，尤其不在阈值附近用显示值判定通过。缺值为null，绝不写0冒充。

当前面板初始质量参数：报价不超过10分钟；同机构欧/亚/大小球报价最大差120秒。执行前报价再收紧至120秒。参数须按真实更新频率验证；超过时限就是待刷新，不挪动时间戳。

### 隐性基本面必须先于意图审批

双方都记录四个结构化条目，每个条目包含status、事实摘要、source、available_at：

1. schedule：过去7/14天比赛、距上一场休息、旅途、下一场/欧战日期，区分90分钟与加时消耗。
2. absences：核心前锋/边锋/组织者/中卫/门将缺席、确认程度、最近出场时间、替代人选及能力。
3. rotation_depth：预计轮换人数、替补深度、双线优先级；首发约赛前1小时复核，预测阵容不能写已确认。
4. motivation：联赛积分目标、杯赛回合及总比分、是否必须进球、可能轮换或保平的事实依据。

附加近5场主客拆分、失球/射门/xG（确实有才用）、对手质量、战术匹配；交锋仅作旁证。先记录事实，再给clear/reduced/adverse；不以纸面排名、强队名气或一条H2H自动填clear。

休息<=72小时或7天>=3场是检查触发器，不是自动判输。密集赛程+薄替补/关键缺席无替代：所选侧veto；风险可解释且已调整模型：reduced；核心事实未知：pending；全部核验：pass。对手受损不能误记成本方伤停，但也不能不经模型调整就提高本方胜率。

## 2. 指标、历史与信号映射

### 欧亚转换公式

对每家机构欧赔O_i：p_i=(1/O_i)/sum(1/O)。该结果只解释胜平负，不直接等同穿盘。

用历史攻防模型及当前去水欧赔、真实大小球约束，形成独立净胜球分布。记录model_version、trained_until、calibration_id、calibration_available_at、fit_error和不确定区间。不得用待检验的亚盘线/水倒推分布，再以此证明亚盘有偏离。

按当场真实让球将分布转换为全赢、赢半、走水、输半、全输五类：

```text
A = P_win + 0.5 * P_half_win
B = P_loss + 0.5 * P_half_loss
Theo_Water = B / A
P_Euro_AH = A / (A + B)
P_AH = [1/(1+w_selected)] / [1/(1+w_selected) + 1/(1+w_opposite)]
Delta_Conv = P_AH - P_Euro_AH
EV_model = A*w_selected - B - costs
```

上下盘各自计算，平手不归上盘。该Delta是本项目明确定义的价格偏离指标，不是通行的“机构意图真值”或真实资金比例。

### 标签交叉确认

| 原标签 | 初始影子规则 | 输出 |
|---|---|---|
| 阻上/诱下 | 上盘Delta在-8至-3个百分点，基本面支持穿盘、实际阻力有证据、无已证实“热上未阻住”；两个机构方向一致，一次新报价即可启动，无固定5分钟等待 | 阻上交叉验证候选，继续检查EV及风控；改向另查逆公众阻力 |
| 诱上/阻下 | 上盘Delta>=+3个百分点，且公众热度、低阻力及基本面不足有独立支持 | 上盘否决；只有下盘自己的EV通过才可转下，否则不投 |
| 降温保护 | 退盘后基本面和净胜球尾部仍支持上盘，转换价值持续 | 可保留上盘候选；不得与诱上混为一谈 |
| 任意 | abs(Delta)>10个百分点、源时间错位、拟合质量不合格、候选与基本面冲突 | 数据/模型待核，不加仓、不强行翻边 |

以上3/8/10个百分点是待样本外校准的初值，不声称已提高胜率。单凭负Delta不能宣称“真实有效阻上”；满足所有独立证据与验证门后，才允许进入后续投注池。

假设Theo_Water=0.85，上/下盘水0.96/0.92：P_Euro_AH=54.05%，P_AH=49.48%，Delta=-4.57个百分点。它落在候选区间，但伤停待核、历史EV不足或熔断中的任一项，都必须拒绝执行。

### 历史统计和综合胜率

先按日期、开赛时间、比赛ID确定性排序；对每场decision_at，只使用结算信息的available_at严格早于该时刻的唯一比赛。相同开赛时间不得通过行号伪造先后可知赛果。没有结算可用时间的旧数据，使用有来源的保守下一日截止并标明降级；不用于临场时间优势结论。

正反向都计算：全局同标签M、同微观同标签n、同盘口同标签、最近15场标签。每场必须按它当时冻结的上下盘映射、线、水结算，不按今天推荐球队回填。地区样本不得混入其他意图标签。

```text
A_hist = 红 + 0.5*红半
B_hist = 黑 + 0.5*黑半
p_eff = A_hist/(A_hist+B_hist)
p_comb = (n*p_local + M*p_global)/(n+M)
Threshold = 1/(1+Water) + Safety_Buffer
```

全局含局部，n+M不是独立样本总数；既定加权规则不能冒充严格独立贝叶斯后验。两个方向按同口径比较；同向一致优先，分歧用p_comb；同盘口反向警戒不能越过基本面/转换门。样本>8而所选侧p_eff<40%仍否决。

周末上盘加严规则及配置入口已删除，所有日期使用相同基础公式。execution_plan可接收带时区kickoff_at，仅输出Is_Weekend/Kickoff_Date_BJ/Weekend_Policy=AUDIT_ONLY供复盘，不影响阈值、方向和金额。禁止通过旧配置重新启用10%-15%。显示值四舍五入不参与比较。

近期15场的恶化门槛应在版本配置中预先固定，不根据目标赛果临时调整；沿用已验证旧配置时保留其版本。未配置或未校准的新滚动门只记录shadow状态，不宣称已经通过实盘准入。

## 3. 仓位、熔断和执行状态

### 仓位不是将Delta乘到胜率上

历史、模型与当前赔率往往相关，不能把三者当独立证据简单叠加。仓位先用：

```text
p_size = min(p_comb_or_consensus, P_Euro_AH, validated_probability_lower_bound_if_available)
```

保留模型走水概率以及赢侧/输侧各自的全赢与半赢结构，调整总赢侧概率使其结算权重胜率等于p_size，再重算五状态EV、广义Kelly。此重加权是一项保守工程假设，需要影子验证；不回写独立转换模型或Delta。

只有p_size>Threshold且扣成本EV>0才继续。五状态收益r={w,w/2,0,-0.5,-1}，求最大化sum(P*log(1+f*r))的f，再使用1/4 Kelly。

```text
planned = Bankroll * Unit_Rate * Signal_Mult * Blind_Mult * Day_Mult * Upper_Mult * Fundamental_Mult
stake = min(planned, Bankroll*0.25*Kelly_Full, Bankroll*Single_Cap,
            Remaining_Daily_Capacity, Venue_Maximum)
```

| 系数 | 规则 |
|---|---|
| Unit_Rate | 沿用现有标准5%计划单位；不是每场必须下注5% |
| Signal_Mult | 普通1；高置信度、持续双检且分层样本外验证通过才允许1.5；Delta绝对值大不自动升档 |
| Blind_Mult | 绝对让球0.75-1.0未验证为0；完成该档独立验证后先0.25，不事后按某场胜负解禁 |
| Day_Mult | 正常1、预警0.5、冷却0；联赛/盘口/微观取最严限制 |
| Upper_Mult | 集中度风控触发时上盘0.5，下盘不自动增加；上盘安全垫2个百分点升至4个百分点 |
| Fundamental_Mult | pass为1，reduced为0.5；pending/veto不执行 |
| 上限 | 当前单场绝对上限5%；更严格赛事/平台上限优先，日剩余额度必须有配置 |

金额向下取整，低于平台最低投注额则0，不向上凑仓。高置信度和降级系数叠加不突破硬限制。

数值演示（全为假设、普通半球盘、无成本）：资金10000，模型有效概率54%，历史综合56.67%，水0.96，则p_size=54%，门槛53.02%，1/4 Kelly上限约152.08。若示例单位设1%，普通100、高置信度150；若沿用5%单位，普通500和高置信度750都被压到152.08，不能承诺1.5倍实际下注。0.75/1.0档必须另用真实半赢/走水分布重算，不能直接套此示例。

### 按日冷却

赛前冻结expected_cover_side、line、water、rule_version、prediction_time。按该预测的真实结算，全黑记1个失败等价、黑半0.5、走水既不新增也不清零、正收益清零。失败不是“模型逻辑一定错”，只是一项预定义风险事件。

按每个联赛、盘口档位及微观板块分别计数，忽略未结算行；并发比赛同日共用上一完整结算日风险状态，不用当日后续赛果阻断更早的单。

- 昨日完整已结算ROI<0，或连续失败等价>=3：下一个有赛日半仓。
- 连续两个完整有赛日ROI<0，或连续失败等价>=5：下一个有赛日冷却，stake=0。
- 冷却期间继续存影子计划，不能停止采样后永远无法恢复。
- 至少一个完整影子日、>=3场符合条件的已结算计划、ROI>0：次日恢复；半仓也按同样恢复条件。此恢复参数为待验证初值。
- 比分待核时该日风险统计为provisional，不准当作完整正收益日复活；无比赛日不计输赢天数。

### 执行前检查

冻结计划有效期内，重新检查是否开赛、平台、market_id、球队、线、结算周期、报价时间、水位下限、额度。盘口线变了必须新增决策版本；不能拿旧胜率直接执行新盘。只改善水位而其他条件不变时可沿用原金额，但不得自动加仓。

真实执行默认未授权。授权范围必须明确平台和资金限制。一个decision_id仅允许一个未决执行动作；PENDING/UNKNOWN/PARTIAL/FILLED存在时先对账，不重复下单。请求超时不是失败证明，先查回执。未实际成交的计划不能写FILLED。

## 4. HTML、Feishu Bitable与长期复盘

### HTML紧凑展示

红框保留标签总体样本、正反向胜率/盈亏及所选球队；新增两行，不堆公式：

```text
计划：可执行/半仓可执行/不投/待核；球队：xxx（正向/反向，上盘/下盘）；计划金额：xx
双检：基本面通过/待核；欧亚通过/冲突；风控：正常/半仓/冷却；未通过：具体第一道门
```

展开“基本面与欧亚双检”，显示以下字段：

| 字段 | 含义 |
|---|---|
| Fundamental_Status / Failed_Gates | 基本面状态、具体缺失或否决项 |
| Theo_Water / Actual_Water | 同一所选侧理论公平HK水、实际可执行HK水 |
| Delta_Conv_pp / Conv_Status | 偏离百分点、独立校验状态及证据时间 |
| Raw_Intent / Verified_Intent | 原盘口候选与经过验证的意图分开 |
| P_Combined / P_Size / Threshold / EV | 历史合力、保守仓位概率、价格门槛、扣成本收益 |
| Upper_Share / Risk_State | 上盘笔数/金额比例，所属系列的风险状态 |
| Move_Status / Move_Reason / Previous_Decision_ID | 单次变盘审查、阻力证据与前一完整版本；仅在折叠详情展示 |
| Is_Weekend / Kickoff_Date_BJ / Weekend_Policy | 实际开球日周末标记；AUDIT_ONLY表示仅分组复盘、不加严 |
| Rule_Version / Snapshot_ID / Decision_ID | 复盘所用的完整版本与原价 |
| Execution_Status / Reason_Code | 观察/待核/通过/过期/执行待核/已成交，以及独立失败原因 |

将计划状态与当前执行状态分开：过去的可投依然出现在可投筛选中，比赛已开赛仅表示现在不能新执行，不得把历史红框改成不投。新字段缺失的旧行显示“旧版未计算”，不能填0或用赛后数据补成已通过。

### 飞书表及字段类型

| 表 | 唯一键 | 核心类型/写入原则 |
|---|---|---|
| MatchRoster | match_id | 文本ID与list_date；日期时间kickoff；国家/地区/赛事层级单选；只增名册、状态独立更新 |
| MarketSnapshot | snapshot_id | 关联比赛；机构文本、盘口/水位数字、时间日期；raw_hash/来源URL；只追加 |
| Decision | decision_id | 关联比赛/快照；球队ID文本、计划方向单选、概率/Delta/金额数字、规则与hash文本、门状态单选；冻结记录不覆盖 |
| SettlementExecution | decision_id + event_type + event_version | 关联决策；赛果/红黑单选、盈亏金额、来源/回执ID文本、结算可用时间日期；更正追加版本 |
| RiskState | scope_type + scope_id + effective_date | 当日之前的ROI/连败数字、风险状态单选、触发比赛与恢复依据；生效日期冻结 |

list_date用YYYY-MM-DD文本避免时区重归属；时间字段由适配层转为飞书所需格式。完整原始JSON留本地，不塞到每个表格单元格。字段映射集中维护；概率列存0-1显示百分比，Delta列以百分点显示。飞书不再另写公式重算推荐。

官方接口提供[记录新增](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/batch_create)和[记录更新](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/batch_update)，可使用[官方Python SDK](https://github.com/larksuite/oapi-sdk-python)。实施时核验当前权限和批量限制，不将未经确认的限制写死。

本地outbox保存event_id、table、business_key、payload_hash、record_id、status、attempts。新增前按业务键查映射；已有同hash则跳过，不同hash须遵守表的追加/更新规则。HTTP成功还需核对业务状态与返回记录。超时先查业务键是否已创建再重试；最多3次退避重试，仍失败转待人工。401/403/字段错误立即停止，不反复撞接口。outbox的幂等约束由本地实现，不假设接口自动提供。

凭证只读环境或用户已有凭证管理，不写入CSV、HTML、日志或GitHub。没有app_token/table_id/权限时只输出待同步事件，不宣称飞书已更新。

### 周末及长期验证

周末定义使用北京时间实际开赛日并保存is_weekend，list_date仍冻结。拆分周末/工作日、国家联赛/杯赛、上下盘、档位、水位、距开赛时间及规则版本。按相同赛前时点公平比较，排除赛后快照和目标比赛结果泄漏。

每组输出样本、红/红半/走/黑半/黑、旧命中率、结算权重胜率、Unit盈亏、真实资金ROI、区间和上下盘占比；不足样本不写“稳定高胜率”。按时间划训练/校准/最终留出集，参数只能由前段选择；最终留出集仅评估一次。重叠多版本同场须按match_id处理相关性，不当独立比赛扩充样本。

必须对照：旧模型、只加基本面、再加Delta、再加集中度及冷却。先看同条件ROI和回撤，而非只挑胜率升高的子组；热门上盘占比下降也不自动等于盈利提升。

## 5. 实施顺序与验收

1. 采集适配：真实源字段、时钟、机构ID对齐，基本面四项有来源；先影子运行，缺口如实显示。
2. 概率校准：保存独立净胜球分布和训练截止，验证深盘/浅盘、周末/杯赛的可靠度；未通过不启用READY。
3. 决策生成：从只读历史构造样本，调用风险模块，保存不可变决策与outbox。
4. 双端渲染：相同decision_hash进入HTML和飞书；历史名册/可投数不能缩减，旧数据不重新选边。
5. 执行接入：报价复核、额度、授权、幂等回执全部测试后，才接用户授权执行器。当前代码不包含真实下单。

已实现并测试的纯函数：de_vig_1x2、quote_alignment、fundamental_gate、settlement_distribution、conversion_metrics、combined_rate、conservative_masses、intent_crosscheck、exposure_gate、next_day_risk、execution_plan、execution_recheck。它们不抓数据、不训练模型、不写飞书、不下单。

关键验收：未来证据必须拦截；同线双方结算互为相反；红半/黑半不能按全赢全输计算；概率降低仓位不能增大；报价过期/变盘不执行；未决回执不重复；开赛后仅当前执行资格改变、原计划不变；当前样本不能进入自己的历史统计。

当前状态：Skill规范与上述计算/检查模块已升级；新参考入口已有改向审查，周末加严已撤回，尚未把现有日更采集器、旧HTML决策计算和飞书同步器全量迁移为v3.2.1。公开的工作流页是设计与验收说明，不是实时投注清单。不能声称已解决周末亏损或已获得可验证的胜率提升。
