# V4 Fair Line Implementation Audit

审计时间：2026-10-07

本审计基于当前实际运行入口 `D:\codex\v4\run_daily_v4.py`、V4决策核心 `D:\codex\v4\core_model.py` 和共享Titan公平线实现 `D:\codex\football_titan_data\core.py`，不根据需求文本推测。

## 1. 当前运行链路

- 运行入口：`D:\codex\v4\run_daily_v4.py`
- V4决策函数：`D:\codex\v4\core_model.py::evaluate_match`
- FFL/CMFL共享层：`D:\codex\football_titan_data\core.py::fundamental_fair_line`、`consensus_market_fair_line`、`build_shared_snapshot`
- 共享快照加载：`D:\codex\v4\run_daily_v4.py::load_feature_snapshot`
- 亚洲盘五状态与EV：`D:\codex\v4\core_model.py::asian_probabilities`、`expected_value`

## 2. FFL当前实现

`football_titan_data/core.py::fundamental_fair_line` 读取球队历史样本、Elo、攻防、近5场PPG、休息天数、主场/中立场、杯赛调整和联赛强度。

当前实际公式是：

```text
margin = (home_elo-away_elo)/400*0.72
       + 0.18*(home_form_ppg-away_form_ppg)
       + clamp((home_rest-away_rest)*0.025, -0.15, 0.15)
       + home_advantage
       + cup_margin_adjustment
```

总进球由攻防和联赛强度得到，再令 `lambda_home=(total+margin)/2`、`lambda_away=(total-margin)/2`，由独立Poisson构造净胜球分布。

当前问题：这些系数是手工固定的，不是历史赛前数据的walk-forward校准；当前返回的 `fair_handicap` 是 `round(margin*4)/4`，因此存在“理论净胜球直接四舍五入成亚洲盘口”的路径。

## 3. 理论净胜球到亚洲盘口的具体代码

具体位置：`D:\codex\football_titan_data\core.py` 第385行附近：

```python
central = round(margin * 4) / 4
"fair_handicap": central
```

这正是 `1.18 -> -1.25` 类问题的来源（符号随后由V4方向映射处理）。

## 4. 当前CMFL实现

`consensus_market_fair_line(euro, total_line)` 当前读取：

- 去水前的1X2欧赔，并在函数内转为去水三项概率；
- 大小球盘口的盘口值；

当前不读取：

- 大小球Over水位；
- 大小球Under水位；

当前会枚举总进球和均值差，用Poisson/Skellam结果的1X2概率与目标1X2去水概率做平方误差，选择最小误差的 `margin`。返回的拟合误差仅是1X2误差，没有OU拟合误差、lambda输出或CMFL完整净胜球分布。

## 5. 当前Poisson/Skellam实现

位置：`D:\codex\football_titan_data\core.py::margin_distribution`。

给定 `lambda_home` 和 `lambda_away`，分别计算0至14球独立Poisson联合分布，再按 `home_goals-away_goals` 聚合到-9至9。V4自身还有一个等价的 `D:\codex\v4\core_model.py::margin_distribution(mean_margin,total_goals)` 实现。

## 6. 当前MARKET_REFERENCE_FALLBACK

位置：`D:\codex\v4\core_model.py::evaluate_match`。

当共享共识、FFL、CMFL均不可用时，当前代码使用：

```python
football_margin = 1.18 * strength_log_ratio + 0.0015 * elo
```

其中 `strength_log_ratio` 来源于欧赔主客胜强弱比。它没有显式使用平局结构，也没有完整市场条件模型。当前源字段标记为 `MARKET_REFERENCE_FALLBACK`，但后续仍把它送入正式分布和EV判断，可靠性限制不足。

## 7. 当前正式方向与EV来源

`core_model.py::evaluate_match` 先用一个fair margin构造分布，再对当前实际盘口调用 `asian_probabilities`，分别计算：

```text
EV_giving = expected_value(giving_probs, giving_water)
EV_receiving = expected_value(receiving_probs, receiving_water)
```

四分之一盘拆分、W/HW/P/HL/L和香港盘EV公式已经存在；但当前方向前置逻辑仍使用fair line gap、候选边和阈值作为选边的重要条件，公平盘口四舍五入会间接影响方向。需要改为当前实际盘口与实际水位下的双边EV为唯一选边依据，fair line gap仅作解释。

## 8. 审计结论

当前系统已经具备基础净胜球分布和四分之一盘EV计算，但仍存在四个必须修正的结构问题：

1. FFL把均值直接四舍五入为 `fair_handicap`；
2. CMFL未使用OU双边水位，也未输出lambda、OU误差和完整分布；
3. FFL/CMFL存在固定比例融合，未由时间外验证权重支持；
4. fallback仍可能进入正式EV路径，且fair line gap仍可能影响方向。

历史冻结V4决策不在本审计或后续上线重算范围内；新逻辑只对新的Forward决策生效。
