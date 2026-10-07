# Shared Titan / Fair Line Forward Test Plan

- Champion 身份保持现有 V3 与现有 V4，不创建新版本名。
- 2026-10-04 起，每日冻结共享事实快照、FFL、CMFL、市场偏离与两模型输入 snapshot_id。
- 只在未来赛果可用后结算，禁止回写历史概率、方向、盘口或水位。
- 滚动观察 20/50/100 场：理论盘误差、概率评分、gap-PnL 单调性、V3/V4 覆盖、领域与盘口分层。
- 在独立时间外样本充分前，状态保持 `FAIR_LINE_UNCALIBRATED`。
