# Fair Line Validation

验证采用按比赛分组的 Walk-Forward：`Train -> Validation -> Test -> Frozen Forward`，禁止随机拆分。

主要评分：主客进球 Poisson deviance、净胜球 MAE、1X2 Brier/log loss、亚洲盘五状态 Brier、理论盘相对收盘盘误差。收盘盘只作为 benchmark。

经济性检查按 price-adjusted gap 分桶，要求 gap 增大时未来平均 PnL 至少具备合理单调性。样本不足或排序失效时保持 `FAIR_LINE_UNCALIBRATED`，不允许用历史 ROI 反复调参后宣称校准。

当前 Frozen Forward 起点：2026-10-04；旧 V3/V4 历史冻结记录不变。
