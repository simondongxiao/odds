# Git与运行代码版本审计

基准发布提交 `66e62351db87d649a7d1651eb2f3a7434c3bde9f`。D:/codex运行目录不是Git仓库；文件SHA256才是此次冻结运行代码身份。公开仓库中的V4核心代码最后一次入库是9/14的b916810，不能把随后发布提交当作完整运行代码版本。

| commit | 修改文件 | 已核查修改逻辑 | 可能影响 |
| --- | --- | --- | --- |
| 4524781 | tools/run_football_update.py | 每日双轨编排及CSV raw路由首次入库 | 可能改变输入覆盖；不是新的概率权重 |
| b916810 | v4/direction_contract.py; v4/run_daily_v4.py; tools/run_v4_direction_fix.py | 引入Titan真实让/受让方；intent选边；receiving五状态镜像；旧giving-only归档 | 与9/14 receiving首次出现高度对应；旧版并非已验证正常版本 |
| 7318fec / 744af5f | tools/run_football_update.py; performance/export tools | 冻结名单和昨日绩效交付 | 报表/分母可见性变化，不是选边训练 |
| 44d701a | tools/run_football_update.py | 历史列表日锁及导出调整（见完整patch） | 历史数据保护；不能当新胜率模型 |
| e790f94 | tools/run_football_update.py | quote_at/last_confirmed及LATEST_VALID_PREMATCH元数据引入 | latest实际是本次有效赛前记录标记，不证明临场 |
| 9ae9974 / 9da0e0d | tools/run_football_update.py | 已开赛冻结记录不再套用本轮报价时间；拒绝决策之后的quote时间 | 9/15时间字段语义修正；早期缺口保留 |
| 60c7f39 | tools/run_football_update.py | 前日V4结算回填并锁grade | 结算覆盖变化，不重算方向 |
| 3c3f585 / 5d15954 | tools/run_football_update.py; delivery tools | 防结算退回待核、交付校验；补导出球队/盘口/快照字段 | 数据交付质量，不证明概率改进 |
| 74f88b7 | tools/run_football_update.py | started_lock跳过metadata改写，按最早有效开赛时钟锁定 | 减少已开赛元数据漂移 |
| 2b2da1d | tools/run_football_update.py | V3冻结结论回填页面 | 无V4方向权重变化证据 |

## 关键比较与限制

9/13是European favorite + 强制负盘口的旧giving-only逻辑，不能称为最后一个“正常”模型。9/14 FIXED_R1使用真实Titan侧并镜像receiving prior，解释首次0%→47.37%的结构断点。9/15—18概率prior来源与alpha哈希未变化；没有已存证据支持“最近两天训练权重变了”。

冻结运行版相对于发布仓库的差异单独保存在 published_vs_runtime.diff：包括CSV适配、赛前时间字段、已开赛保留逻辑。必须补运行代码完整版本化后才可精确归因到每次刷新。Git首次记录时间也不等于部署生效时间。

原始证据：git_relevant_history.txt、git_relevant_patches.txt、runtime_identity.csv；不能仅凭commit标题解释因果。
