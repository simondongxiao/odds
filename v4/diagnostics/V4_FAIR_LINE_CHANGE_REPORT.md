# V4 Fair Line Change Report

- FFL输出完整净胜球分布和FFL_FAIR_AH_CURVE；fair_handicap仅为曲线摘要。
- CMFL输出lambda_home/lambda_away、1X2与OU拟合误差、完整分布和曲线。
- 未验证权重下不做FFL/CMFL简单平均；优先选择有支持的primary distribution。
- Fallback不再覆盖可靠CMFL；无可靠Fair模型时进入MARKET_CONDITIONAL。
- 历史冻结账本不回写。
