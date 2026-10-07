# Fair Line Model

## Fundamental Fair Line (FFL)

FFL 函数没有亚洲盘和水位参数。输入包括动态 Elo、主客场、近 5/10 场状态、攻防表现、休息天数、中立场、杯赛状态和可得阵容信息。当前采用可审计的 Poisson/Skellam 净胜球分布；样本稀疏时收缩并扩大不确定区间。

输出：主客预期进球、净胜球完整分布、中心理论盘、上下界、不确定性，以及 0/0.25/0.5…盘口的双边 W/HW/P/HL/L 与公平港赔曲线。中心 `fair_handicap` 使用 Titan 的“正数=主队让球”表示；曲线同时保存标准投注 handicap 与 `titan_home_line`，避免符号歧义。

## Consensus Market Fair Line (CMFL)

CMFL 只使用去水 1X2 与大小球总线，通过网格拟合进球均值与净胜球；严禁读取亚洲盘或水位。

## Consensus

FFL 与 CMFL 独立保存，并保留 disagreement。CMFL 缺失时不伪造，consensus 退回 FFL。当前状态统一为 `FAIR_LINE_UNCALIBRATED`。

## Price-adjusted gap

市场偏离同时使用盘口和该侧水位，以亚洲盘五状态期望 PnL 计算；不能只比较盘口数字。
