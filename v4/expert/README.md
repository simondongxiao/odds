# V4_EXPERT_FILTER_R2

这是原 V4 的独立 Shadow 专家选择器。它只在原 V4 的 A/B/C 候选中做保留或拒绝，不改变方向、不新增候选、不使用 ABC 决定仓位。所有保留项固定纸面 1U，`real_money=false`。

R1 已冻结为 `EVALUABILITY_FAILED`。R2 将可评估性分为 `TIER_CORE / TIER_MARKET / TIER_FULL`：只有核心身份、方向、盘口、水位或赛前冻结证明失败时才是 `UNAVAILABLE`；E2 盘口路径或 E3 基本面缺失只会降级到 CORE。

## Windows 手动命令

在 PowerShell 中先进入工作区：

```powershell
Set-Location 'D:\codex'
```

完整人工更新：

```powershell
python -m v4_expert.cli update --list-date 2026-09-23
```

分步命令：

```powershell
python -m v4_expert.cli audit
python -m v4_expert.cli build-dataset
python -m v4_expert.cli train
python -m v4_expert.cli historical
python -m v4_expert.cli infer --list-date 2026-09-23
python -m v4_expert.cli settle
python -m v4_expert.cli compare
python -m v4_expert.cli unavailable-audit
python -m v4_expert.cli report
```

## 状态含义

- `ENGINEERING_EVALUABILITY_PASSED`：历史 CORE 可评估率已达到工程目标。
- `UNCALIBRATED_SHADOW`：当前只输出 raw E(PnL)、相对排名和 Shadow 结论，不声称真实概率。
- `DEVELOPMENT / IN-SAMPLE OR REUSED HISTORY`：历史重跑，仅用于工程与机制检查。
- `FROZEN FORWARD`：新比赛的真实冻结前瞻记录。
- `RANKING_EFFICACY_UNPROVEN`：覆盖率修复不等于筛选能力已证明。
- `PROMOTION_ELIGIBLE`：只有满足前瞻门槛并经用户明确批准才可能出现。

本模块不包含定时任务。只有人工调用会执行更新。
