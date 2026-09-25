# 篮球 v2 今日更新审计：2026-09-25

## 运行结果

本轮按当前 `SKILL.md` 运行真实前向流程：赛事发现、7M 新采集、盘口匹配、历史补全、独立定价、盘口比较、纸面决定、前一日纸面复核和结算错因账本检查均已执行。没有使用旧盘口代替本轮盘口，没有修改定价公式、Evidence Gate、阈值、Residual Scale、Meta Calibration 或历史首写。

```text
run_id       = 20260925T001544_31cd90c379
asof         = 2026-09-25T00:16:21.386474+00:00
Beijing date = 2026-09-25
events       = 46
quote rows   = 180
source ids   = 312
update       = PARTIAL
real execute = OFF
```

## 今日盘口与漏斗

|市场|赛事总数|找到盘口|无盘口|新鲜盘口|过期盘口|盘口存在但未定价|新鲜但未定价|可定价|Edge|纸面触发|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|让分|46|31|15|18|13|27|14|4|4|3|
|大小分|46|31|15|18|13|31|18|0|0|0|

终态核算：`92/92`，状态为 `OK`。让分终态为 `SHADOW_TRIGGERED=3`、`EVIDENCE_BLOCKED=1`、`HISTORY_BLOCKED=14`、`STALE_MARKET=13`、`NO_MARKET=15`；大小分终态为 `HISTORY_BLOCKED=14`、`BASE_STATS_BLOCKED=4`、`STALE_MARKET=13`、`NO_MARKET=15`。

大小分本轮没有进入纸面执行，不是把大小分建议删除，而是 4 个新鲜分支中基础数据/回合证据仍未满足既有合同，其他分支分别是历史不足或盘口过期。

## 今日纸面可投

本轮有 3 场让分 `SHADOW_BET`，真实执行仍关闭。由于 7M 当前球队文本中有源编码替换字符，报告保留 canonical event id、原始队名字段和明确的 TEAM1/TEAM2 选择，不根据乱码猜中文队名；网页以同一原始字段展示。

```text
7m:1339259  选择 TEAM2  让分 11.5  @ 1.90  p_win 0.6237
7m:1339261  选择 TEAM1  让分 12.0  @ 1.96  p_win 0.6233
7m:1339262  选择 TEAM1  让分 9.5   @ 2.00  p_win 0.6138
```

以上均为冻结纸面模拟，不是真实下注建议或真实仓位。今日没有大小分纸面单。

## 历史就绪诊断

```text
目标球队槽位             92
历史抓取尝试/成功          34 / 34（当前日目标关联）
本轮 7M 历史请求/成功      100 / 100
解析历史事实               2,000
目标关联原始历史           2,203
球队别名匹配后             2,203
联赛匹配后                 1,420
截止日前                   1,420
有效比分                   1,420
去重后                     1,420
模型合同可用               384
```

失败分类：`HISTORY_SOURCE_FAILED=58`、`HISTORY_FILTER_TOO_STRICT=24`、`LEAGUE_ALIAS_HISTORY_MISMATCH=2`、`READY=8`。`DATE_TIMEZONE_FILTER_ERROR=0`，`DUPLICATE_REMOVAL_OVERFILTER=0`，本轮没有被证实为 `SOURCE_HISTORY_GENUINELY_ABSENT` 的目标球队。

原始历史存在但被联赛过滤移除：`783` 条。该数字只作为诊断，不自动放宽 competition identity 合同。

## 来源健康

```text
HTTP attempts = 503
HTTP success  = 492
source errors = 5 个明确适配器错误
```

ESPN NBA、WNBA、男篮大学、女篮大学和 SofaScore 本轮返回 403。系统没有绕过限制；fallback 运行时链目前没有埋点，记录为 `fallback_invocation_trace=NOT_INSTRUMENTED`、`HISTORY_FALLBACK_EARLY_RETURN_BUG=NOT_PROVEN`，不能把未观测的 fallback 当成成功。

## 前一天纸面复核

2026-09-24 保留的首写纸面记录共 1 场，当前没有可用终场赛果，状态为 `PENDING`，没有删除，也没有提前写入赢输。结算错因账本本轮追加 0 条，继续保持追加式和不可变。

## 文件

- 今日数据：[latest.json](../dashboard_v2/data/latest.json)
- 今日日期数据：[2026-09-25.json](../dashboard_v2/data/2026-09-25.json)
- 漏斗 CSV：[pricing_funnel_20260925.csv](../diagnostics/pricing_funnel_20260925.csv)
- 历史就绪 JSON：[history_readiness_20260925.json](../diagnostics/history_readiness_20260925.json)
- 当前生产清单：[repair_v22_latest.json](../manifests/repair_v22_latest.json)

本地页面：[dashboard_v2/basketball.html](../dashboard_v2/basketball.html)。本轮未发布 GitHub，也未修改旧版 `basketball.html`。
