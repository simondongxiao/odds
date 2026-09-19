# V4 Diagnostics

此目录为独立、只读基线诊断。入口index.html；结论executive_diagnosis.md；实验提案PROPOSED_FORWARD_TESTS.md。未实施规则调整。V3仍为唯一Production，V4 SHADOW ONLY / real_money=false。

冻结基准：2026-09-19 14:56:44 +08:00，公开提交66e6235。baseline/manifest.json记录193个代码/决策文件，evidence_manifest.json补充70个原始证据文件；运行代码身份以SHA256为准。公开仓库不是运行代码完整版本。

分析窗口9/13—18。188 ABC；旧9/13为33条，当前修复版155条；两者分层不混为同一策略验证。六日753 computed。只用冻结概率和冻结决定评分。CSV的比例是0—1、PnL为平注1U；ROI_frozen分母包括待核，ROI_settled仅辅助；有效胜率=(W+0.5HW)/(W+0.5HW+0.5HL+L)。无结果/无分母为空，不填虚假零。

运行complete_report.py会从baseline重建诊断CSV/报告/图，不调用模型main，不写模型或原历史。freeze_baseline.py不可重复覆盖原冻结基准。baseline完整原始副本保留本地，不公开重复上传；公开提供文件hash清单、40场追踪及诊断产物。UTC Z与北京时钟分别解析，凌晨比赛沿用原list_date。

核心数据说明：

- daily_direction_drift：ABC与全computed分别统计，10pp为描述标记非显著性检验。
- coverage_reconciliation/audit_rows：原结算与仅诊断终场恢复分开；后者不改原JSON。来源逐场保留。
- direction_trace_samples：seed20260919；20 receiving ABC，16 giving ABC加4 giving N，未按赛果选样。
- probability_calibration：有效权重Brier-like及五状态Brier；P(EV>0)不当成赢盘概率。ECE总体见facts.json。
- ev_bucket_performance：ABC与COMPUTED_ABCN独立，N为对照不是当时推荐。
- c_grade_sensitivity：历史敏感性，不代表已采用新门槛。
- snapshot_timing：报价距开赛而非决策时刻；缺失显式保留。
- region_performance：唯一现有分类器，覆盖缺陷披露，青年/女足/杯赛可重叠，small_sample以结算少于30为标记而非统计定理。
- predictive_check/uncertainty：独立模型预测检验与仅5日期簇的描述区间，非因果证据。
- runtime_identity/published_vs_runtime.diff/git_relevant_patches：运行代码与公开代码差异及可追溯版本。

来源：本地已存Titan007原始盘口/终场、V4冻结ledger和公开repo git对象。没有额外抓取并替换旧赛前输入，没有根据赛果重算candidate_side。模型改进只能用未来实验检验。
