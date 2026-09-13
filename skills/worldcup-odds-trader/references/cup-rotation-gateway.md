# 赛制、主客场与轮换前置网关

版本：cup-rotation-v1-20260907。适用于新赛前决策；保留原有v3.1的Delta、历史EV、同档风控、冷却及Kelly规则。新增门只能拦截或收紧，不能把原策略的不投改成可投。

## 1. 四个字段及配套数据

| 新增字段 | 飞书建议类型 | 取值/含义 |
|---|---|---|
| Match_Nature | 单选 | 联赛 / 单场杯赛 / 两回合首回合 / 两回合次回合 |
| Schedule_Density | 单选 | 正常 / 一周双赛 / 一周三赛；主字段对应Assessment_Team_ID |
| Rotation_Risk | 单选 | 低 / 中 / 高；主字段对应Assessment_Team_ID |
| Strategic_Intent | 单选 | 正常 / 战意成疑 / 必须全力争胜；主字段对应Assessment_Team_ID |

四个字段只描述风险，不能替代其证据。Match_Nature由该赛季、阶段的正式赛制和赛程确认，不能凭“杯”字推导单场或两回合。小组赛、混合赛制或阶段未核清时保留空值，网关待核。

配套字段是避免计算歧义所必需的：

| 字段组 | 飞书建议类型/用途 |
|---|---|
| Match_ID、Tie_ID、First_Leg_Match_ID | 文本；比赛/两回合对阵唯一关联，不只用队名匹配 |
| Home_Team_ID、Away_Team_ID、Selected_Team_ID | 文本；本场主客队和原策略拟评估球队 |
| Assessment_Team_ID / Name | 文本；当前让球方，平手时为拟评估方；红框所选球队可能不同 |
| First_Leg_Home_Team_ID / Away_Team_ID、First_Leg_Home_Goals / Away_Goals | 文本/整数；首回合的真实身份及比分，绝不按本场主客位置直接相减 |
| First_Leg_Leader_ID、First_Leg_Lead | 文本/数字；程序计算领先方和净胜差，不含点球大战 |
| Home_Handicap、Neutral_Venue、Selected_Venue | 数字/复选框/单选；主队给让为负；场地必须核验，不能因列在主队就当主场 |
| Home_Schedule_Density、Away_Schedule_Density | 单选；分别保存双方赛程，防止拿主队风险套给客队 |
| Home_Rotation_Risk、Away_Rotation_Risk | 单选；分别保存双方轮换风险 |
| Home_Strategic_Intent、Away_Strategic_Intent | 单选；分别保存双方战意 |
| Base_Confidence、Adjusted_Confidence、Confidence_Factor | 数字；0-100评分及折扣，不是新的历史胜率 |
| Confidence_Basis | 文本；必须为before_context_adjustment，防止重复扣分 |
| Strategic_Factor、Fatigue_Factor、Rotation_Factor | 数字；保留本次实际采用的系数 |
| Gateway_Status、Execution_Code、Execution_Status、Failed_Gate | 单选/文本；网关状态、机器原因码、用户状态和具体失败环节 |
| Stake_Cap_Units、Stake_Before_Context_Cap、Stake | 数字；最多几标准仓、原策略金额和最终金额 |
| Nature/Team/Venue/FirstLeg_Source、Available_At | 文本/日期时间；分别记录赛制、人员、场地和首回合赛果证据 |
| Guardrail_Version、Decision_ID、Decision_At | 文本/时间；按整份决策留底，与HTML相同 |

Python输入按Teams[team_id]保存双方三项评级；飞书适配层展开为Home_/Away_列。原有Fundamental_Evidence继续分别保存双方schedule、absences、rotation_depth、motivation的状态、来源及可用时间。任何未来证据不得用于当前决策。

Schedule_Density按开赛前滚动7天、该队去重的赛事，再加本场计算：总1场为正常，2场双赛，>=3场三赛。休息小时、旅途、过去加时消耗仍单独保存。未来已公布赛程可以作为当时已知计划使用，但不能把尚未踢完的体能或首发写成已确认事实。

飞书只追加字段，不删除或改名旧列。赛制归入名册/赛事阶段资料，人员评级及信心归入决策快照；后续修订不能覆盖过去决策。通过[官方字段新增接口](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-field/create)实施时先读取已有字段，按名称和类型检查，避免重复创建。当前未配置具体飞书表，因此本次交付字段方案，不声称已改云端表。

## 2. 硬性拦截

### 两回合次回合

Match_Nature为两回合次回合时，先核验Tie_ID、首回合比赛ID、双方球队ID、比分及赛果可用时间。

将首回合两个球队ID映射到同一组本场球队，取首回合净胜差。这里将“优势方”明确为首回合比分领先方，不将“首回合客队”误当作“本场客队”。任一方首回合净胜>=2（包含恰好2球），整场执行：

```text
Execution_Code = SKIP_SECOND_LEG_LEAD
Execution_Status = 强制跳过（警惕轮换与功利控盘）
Stake = 0
Delta_Conv = null（被前置拦截，不计算）
```

整场跳过，不自动转投落后方。该规则是用户指定的风险排除，不代表领先队必输盘。单场杯赛和首回合不套此规则；领先1球也不自动触发，但仍继续全部其他检查。首回合未知不当作0-0。

### 密集赛程深盘

当前真实让球方按Home_Handicap符号识别，与主客名称或纸面排名无关。绝对让球在0.75至1.0（含端点），且让球方一周双赛/三赛、Rotation_Risk=高：

- 默认dense_deep_action=skip：强制跳过；Delta再好也不得覆盖。
- 明确配置quarter：最多0.25标准仓；其他基本面、置信度、EV、盲区验证、日风控未过仍为0。
- quarter是原策略之后的绝对金额上限，不是再次把已经0.25仓的金额乘0.25；1.5倍高置信度也不能突破此上限。
- 例如资金10000、标准单位5%=500，最终最多125；原策略只给80则保留80，不能补足125。

0.5或1.25以上不触发这条精确区间规则，但仍受一般深盘、伤停及赛制风控。不能把“未触发此门”解释为可投。

### 核心伤停不得后置

网关同步调用既有fundamental_gate。所选侧核心缺席且无替代等adverse状态直接跳过；双方四项核心资料缺失或晚于决策时间，先待核，均不进入Delta。原策略仍负责风险折扣与概率模型，不能只靠三项评级取代球员伤停事实。

## 3. 主客场与信心调整

采用可审计、只降不升的初始系数：

| 维度 | 状态 | 系数 |
|---|---|---:|
| 战意 | 正常 / 必须全力争胜 / 战意成疑 | 1.00 / 1.00 / 0.85 |
| 赛程-主场 | 正常 / 双赛 / 三赛 | 1.00 / 0.95 / 0.90 |
| 赛程-客场 | 正常 / 双赛 / 三赛 | 1.00 / 0.90 / 0.85 |
| 赛程-中立 | 正常 / 双赛 / 三赛 | 1.00 / 0.925 / 0.875 |
| 轮换 | 低 / 中 / 高 | 1.00 / 0.90 / 0.75 |

```text
Adjusted_Confidence = Base_Confidence × Strategic_Factor × Fatigue_Factor × Rotation_Factor
```

系数作用于拟投注球队，而深盘高轮换硬门检查让球方；这两个身份分开记录。客场疲劳扣分较重，中立场不套主场优势。必须争胜只表示动机明确，不增加穿盘概率；比分模型已包含主客优势时不再额外加一次主场概率。

例：原信心80，客场一周双赛、战意成疑、轮换低：80×0.85×0.90×1=61.2分。若同时高轮换则45.9分。初始minimum_confidence=60，低于此值不投。

这些系数和60分是待样本外验证的风险参数，并非经验胜率。历史p_comb、标签胜率、原始模型概率、独立Delta均不被改写。若以后要将分数转为可执行概率，应另做时间留出的概率校准；不能把61.2分当61.2%胜率去做Kelly。

## 4. Python集成

完整实现：`scripts/cup_rotation_gateway.py`；现有Delta与仓位计算仍在`scripts/asian_risk_v3.py`。

```python
from cup_rotation_gateway import GatewayPolicy, run_guarded_analysis


def analyze_with_context(context, calculate_delta, existing_strategy, bankroll):
    return run_guarded_analysis(
        context,
        calculate_delta=calculate_delta,
        existing_funnel=existing_strategy,
        bankroll=bankroll,
        unit_rate=0.05,
        minimum_stake=20,
        policy=GatewayPolicy(dense_deep_action="skip", minimum_confidence=60),
    )
```

调用契约：calculate_delta是零参数回调，仅在网关通过后调用，返回包含Delta_Conv的字典。existing_strategy接收该字典以及附加的Context_Gateway，并运行已有报价新鲜度、意图双检、标签/微观历史、EV、冷却、盲区和Kelly逻辑，返回Execution_Status与Stake。必须使用Context_Gateway中的基本面状态，不能忽略reduced折扣。

真实顺序由包装器固定：

1. 提供Frozen_Decision时直接返回深拷贝，不运行任何新门、不改变历史金额。
2. 校验赛制与首回合，执行强制跳过规则。
3. 校验双方风险评级、核心伤停、真实主客场；计算调整后信心，执行深盘轮换门。
4. 只有PASS/QUARTER_CAP才能调用Delta计算；无有效Delta不得进入原策略。
5. 原策略不投或熔断时金额强制0，不得被新网关重新升级。
6. 原策略READY时施加0.25仓绝对上限，再检查最低投注额；不足则0。
7. 保存整份决策；执行前仍按v3.1验证报价、开赛、授权和回执。该模块不真实下单。

## 5. HTML及历史一致性

电脑基本面面板及手机比赛展开页都新增四个核心字段，并显示评估球队、所选侧主客场、调整后信心和网关状态。使用文本转义，不能把来源内容直接当HTML。

字段只从同一份决策/冻结记录读入。旧决策没有Guardrail_Version时显示“未采集（旧版未计算）”，不从最新资料补一个貌似历史已通过的判断；红框原选队、盘口、赔率、可投状态不变。网关计算结果与比赛进行状态分离。

本次已实现：纯Python前置网关与原策略包装器、24项网关测试、HTML字段传递和电脑/手机渲染。既有v3.1的28项测试仍需同时通过。尚未完成：实时数据采集器的赛制/伤停字段适配、真实样本校准、飞书云端字段创建，以及将旧日更全面切换到新包装器。新增HTML字段不代表缺失数据已经补齐。
