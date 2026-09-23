# V4_EXPERT_FILTER_R1

这是原 V4 的独立 Shadow 专家过滤器。它只在原 V4 的 A/B/C 候选中做保留或拒绝，不改变方向、不新增候选、不使用 ABC 决定仓位。所有保留项固定纸面 1U，`real_money=false`。

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
python -m v4_expert.cli infer --list-date 2026-09-23
python -m v4_expert.cli settle
python -m v4_expert.cli compare
python -m v4_expert.cli retrain-check
python -m v4_expert.cli report
```

## 状态含义

- `ENGINEERING_READY`：管线、审计、冻结、结算、对账和页面已可运行。
- `TRAINING_READY`：已生成可复现训练产物和 OOS 预测。
- `UNCALIBRATED`：当前目标是预期 1U 净收益，不声称概率已校准。
- `FORWARD_RUNNING`：开始积累真正的前瞻冻结记录。
- `EFFICACY_UNPROVEN`：工程可用不等于盈利能力已证明。
- `PROMOTION_ELIGIBLE`：只有满足前瞻门槛并经用户明确批准才可能出现。

本模块不包含定时任务。只有人工调用会执行更新。

