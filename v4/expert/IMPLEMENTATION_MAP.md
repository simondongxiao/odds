# V4_EXPERT_FILTER_R1 实施映射

生成日期：2026-09-23（Asia/Shanghai）

## 1. 边界与保护原则

- 本模块只消费已经冻结的原 V4 输出；不调用旧版生产更新链，不读取其他模型版本的数据目录。
- 原 V4 是唯一对照组 `V4_RAW_CONTROL`，其方向、概率、EV、ABCN、历史盘口/水位、决策时间和结算证据均只读。
- 新模块只能在原 V4 的 A/B/C 候选中输出 `BET`、`NO_BET` 或 `UNAVAILABLE`，不能反向、不能新增非候选。
- 所有 `BET` 固定纸面 1U；其余 0U；`status=SHADOW`、`real_money=false`。
- ABC 只保留为审计字段，不进入模型特征、不控制阈值和仓位。

## 2. 现有实现与入口

| 组件 | 路径/入口 | 当前版本或用途 | 本次处理 |
|---|---|---|---|
| 原 V4 日更入口 | `D:/codex/v4/run_daily_v4.py` | 生成冻结 V4 决策 | 保护；新模块不调用 |
| 原 V4 双轨管线 | `D:/codex/v4/v4_dual_pipeline.py` | 旧 V4 管线 | 保护；新模块不调用 |
| 原 V4 方向契约 | `D:/codex/v4/direction_contract.py` | 原方向映射 | 保护；只验证哈希 |
| 原 V4 模型 | `D:/codex/v4/models/v4-market-dirichlet-20260913/model.json` | 原 V4 概率模型 | 保护；仅作为版本元数据 |
| 原 V4 训练清单 | `D:/codex/v4/models/v4-market-dirichlet-20260913/training_manifest.csv` | 原训练记录 | 保护；不重新训练原 V4 |
| 原 V4 冻结输出 | `D:/codex/v4/outputs/v4_decisions_YYYY-MM-DD.json` | CONTROL 数据源 | 只读消费 |
| 原 V4 页面 | `D:/codex/v4/dashboard/index.html` | 原始展示 | 保留；仅增加独立入口时做最小集成 |
| 已有 V4.1 | `D:/codex/v41/` | 独立概率/方向挑战系统 | 只复用时间快照和防泄漏思想；不复用改方向逻辑 |
| 新专家过滤器 | `D:/codex/v4_expert/` | `V4_EXPERT_FILTER_R1` | 本次新增 |

## 3. 已确认诊断输入

- `D:/codex/v4_diagnostics/executive_diagnosis.md`
- `D:/codex/v4_diagnostics/root_cause_ranking.md`
- 原 V4 2026-09-13 至 2026-09-23 冻结输出。
- 原 V4 模型、训练清单和已发布页面。
- V4.1 的模型、校准、前瞻、快照和健康检查实现。

诊断所指出的固定方向映射、盘口桶概率塌缩、EV 假精度、C 级拥挤、快照漂移和短样本不确定性，将转换成显式专家、缺失状态和消融项；不会回写原 V4。

## 4. 新模块文件与调用入口

| 文件 | 职责 |
|---|---|
| `config/filter_r1.json` | 冻结参数、阈值公式、重训门槛和禁用特征 |
| `protected_manifest.json` | 原 V4 核心 SHA-256 保护清单 |
| `common.py` | 时间、哈希、结算、原子写入等公共能力 |
| `pipeline.py` | V4-only 数据契约、去重、时间分区、训练、推断、结算、对比、归因 |
| `web.py` | 四视图和中文 HTML 生成 |
| `cli.py` | 八个必需命令及完整手动更新入口 |
| `tests/test_filter_r1.py` | 防泄漏、不可变、独立性和 PnL 对账测试 |
| `README.md` | Windows 可复制命令和状态解释 |

命令入口：`python -m v4_expert.cli <command>`，支持 `audit`、`build-dataset`、`train`、`infer`、`settle`、`compare`、`retrain-check`、`report`、`update`。

## 5. 版本与数据标识

- 运行时模型版本来自训练产物内容哈希，不使用网页发布 commit 冒充模型版本。
- 未能从原始冻结行确认的版本统一标记 `UNKNOWN_VERSION`。
- 原始 `snapshot_id` 若只是通用占位值，保留原值并生成内容哈希作为 `derived_snapshot_id`，质量标记为 `DERIVED_STABLE_KEY`。
- 比赛、球队和赛事标识只从冻结 V4 行稳定派生，不访问禁止的数据路径。

## 6. 已存在能力、缺口与实现选择

| 能力 | 现状 | 本次实现 |
|---|---|---|
| 原 V4 CONTROL | 已存在 | 只读标准化和四视图对账 |
| 防时间泄漏 | V4.1 有部分实现 | 在每行强制三条 as-of 约束 |
| 快照保存 | V4.1 已存在 | 新模块独立存档原 V4 冻结快照，禁止覆盖 |
| E0 历史基线 | 缺失 | 层级收缩的固定 1U PnL 基线 |
| E1 信号有效性 | 缺失 | 正则化预期 PnL 回归 |
| E2 价格路径 | 历史覆盖不足 | 有真实路径才启用；两点时明确 `TWO_POINT_ONLY` |
| E3 赛况条件 | 无可靠独立源 | 默认 `UNAVAILABLE`，绝不伪造中性 0.5 |
| Meta 选择器 | 缺失 | 仅用扩展窗口 OOS 专家输出训练的强正则回归 |
| 市场状态监控 | 缺失 | 全市场 as-of 分布与关系变化；允许 `REFERENCE_INSUFFICIENT` |
| 固定 1U Shadow | 部分存在 | 强制 `BET=1U`，其他 0U，禁止 Kelly/动态仓位 |
| Champion/Challenger | 缺失 | 冻结 Champion；只提示重训，不自动晋级 |
| 页面入口 | 缺失 | 原 V4 页面旁增加独立专家选择器入口 |

## 7. 明确禁止

- 不读取或调用其他版本模型、赛果、页面或更新脚本。
- 不修改原 V4 已冻结字段和结算证据。
- 不把结果时间、赛果、PnL、ID、ABCN 等放入模型特征。
- 不根据当日早先赛果改变后续选择。
- 不自动晋级 Challenger，不建立定时任务。
