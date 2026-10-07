# UI 契约基线

页面路径保持：`/odds/v3-legacy/`、`/odds/v4/`。

## V3

```json
{
  "exists": true,
  "bytes": 26597747,
  "ids": [
    "bettableFilter",
    "dateCount",
    "dateSelect",
    "decisionBox",
    "fundamentalBox",
    "historyBox",
    "intentDetail",
    "intentMatrix",
    "intentSource",
    "marketTag",
    "matchList",
    "matchSearch",
    "oddsTable",
    "pickBox",
    "pmBox",
    "rateBox",
    "riskAudit20260907",
    "selectedMeta",
    "selectedScore",
    "selectedTitle",
    "sourceBox",
    "strictUpdate20260908",
    "tagPerformance"
  ],
  "tables": 9,
  "thead": 9,
  "selects": 1,
  "cardsData": 1,
  "date_selector": true,
  "bettable_filter": true,
  "responsive_css": false
}
```

核心读取：V3 `cardsData`；日期选择器 `dateSelect`；当日可投筛选 `bettableFilter`；详情使用现有展开/分析说明位置；历史仍按 `date`、`match_id` 和原字段读取。

## V4

```json
{
  "exists": true,
  "bytes": 13692,
  "ids": [
    "bettableOnly",
    "competition",
    "date",
    "decision",
    "grade",
    "rows",
    "summary"
  ],
  "tables": 1,
  "thead": 1,
  "selects": 4,
  "cardsData": 0,
  "date_selector": true,
  "bettable_filter": true,
  "responsive_css": true
}
```

核心读取：独立日期 JSON；`date`、`bettableOnly`、`competition`、`decision`、`grade`、`summary`、`rows`；手机端保留横向滚动与比赛双方固定列。

新增字段只写入后台 JSON/现有详情数据，未增加主表栏目、顶部面板或新的页面入口。
