# V4 Mechanical Direction Audit

代码审计结论：旧 V4 的 `derive_market_intent -> map_intent` 在最终 EV 计算前先产生单一候选方向；随后 `run_daily_v4.py` 只对该方向计算主 EV，且 bucket alpha 直接生成最终状态概率。因此旧结构存在“intent/bucket 先行决定方向”的机械风险。

R2 不修改旧文件，改为：盘口桶只作 prior anchor；当前欧赔、盘口、水位和赛事 Domain 进入比赛级 margin distribution；先分别计算 giving/receiving 五状态概率与 EV，再做方向选择。

R2 明确禁止 1.0、1.5、2.0 等盘口到固定方向的映射。
