from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd


ROOT = Path(r"D:\codex\outputs\football_odds_trader")
SEQ_DIR = ROOT / "backtests" / "sequential_asian"
TOP5_DIR = ROOT / "backtests" / "top5_tier_split"


def latest(pattern: str, root: Path) -> Path:
    files = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No file matches {pattern} under {root}")
    return files[-1]


def newest(pattern: str, root: Path) -> Path:
    files = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No file matches {pattern} under {root}")
    return files[0]


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def pct(value: object) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "NA"


def unit(value: object) -> str:
    try:
        return f"{float(value):+.4f}"
    except Exception:
        return "NA"


def summary_get(summary: dict[str, object], *keys: str) -> object:
    for key in keys:
        value = summary.get(key, "")
        if value != "":
            return value
    return ""


def md_table(df: pd.DataFrame, columns: list[str], max_rows: int | None = None) -> str:
    view = df[columns].copy()
    if max_rows is not None:
        view = view.head(max_rows)
    if view.empty:
        return "暂无。"
    return view.to_markdown(index=False)


def main() -> int:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    current_path = newest("current_intent_matches_*.csv", SEQ_DIR)
    summary_path = newest("sequential_asian_backtest_*_summary.json", SEQ_DIR)
    type_path = newest("sequential_asian_backtest_*_by_type.csv", SEQ_DIR)
    region_path = newest("sequential_asian_backtest_*_by_region.csv", SEQ_DIR)
    tag_path = newest("sequential_asian_backtest_*_by_tag.csv", SEQ_DIR)
    detail_path = newest("sequential_asian_backtest_*_detail.csv", SEQ_DIR)
    report_path = newest("sequential_asian_backtest_*.md", SEQ_DIR)

    current = read_csv(current_path)
    by_type = read_csv(type_path)
    by_region = read_csv(region_path)
    by_tag = read_csv(tag_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    s = summary.get("summary", {})
    cfg = summary.get("config", {})

    high = by_type[
        (by_type["已结算投注数"] >= 8)
        & (by_type["胜率"] >= 0.55)
        & (by_type["盈亏Unit"] > 0)
    ].sort_values(["盈亏Unit", "胜率"], ascending=False)
    weak = by_type[by_type["已结算投注数"] >= 8].sort_values(["盈亏Unit", "胜率"]).head(15)

    top5_summary = ""
    try:
        top5_overall_path = newest("top5_high_win_side_policy_overall_*.csv", TOP5_DIR)
        top5_league_path = newest("top5_high_win_side_policy_by_league_*.csv", TOP5_DIR)
        top5_overall = read_csv(top5_overall_path)
        top5_league = read_csv(top5_league_path)
        top5_min3 = top5_overall[top5_overall["策略"].astype(str).str.contains("顺序回测min3", na=False)]
        top5_league_min3 = top5_league[top5_league["策略"].astype(str).str.contains("顺序回测min3-赛事级\\+盘口倾向择高", na=False)]
        top5_summary = f"""

## 五大联赛地区单独结论

这部分只看英/西/意/德/法的顶级、次级、次次级和国内杯赛。重点结论：全样本事后体检不能当赛前胜率，顺序回测才是可交易口径。

{md_table(top5_min3, ["策略", "总场数", "下注场数", "跳过", "红/红半/走/黑半/黑", "有效胜率", "均注盈亏", "ROI", "选正向", "选反向"])}

### 五大地区分赛事：顺序回测 min3

{md_table(top5_league_min3, ["国家", "层级", "赛事", "总场数", "下注场数", "红/红半/走/黑半/黑", "有效胜率", "均注盈亏", "ROI", "选正向", "选反向"])}

文件：
- `{top5_overall_path}`
- `{top5_league_path}`
"""
    except Exception as exc:
        top5_summary = f"\n## 五大联赛地区单独结论\n\n未生成或读取失败：{exc}\n"

    tag_counts = current["候选标签"].value_counts().reset_index()
    tag_counts.columns = ["候选标签", "当前场数"]
    region_counts = current["微观板块"].value_counts().reset_index()
    region_counts.columns = ["微观板块", "当前场数"]

    lines = [
        "# 当前有意图比赛与严格顺序回测汇总",
        "",
        f"- 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        f"- 当前有意图比赛清单：`{current_path}`",
        f"- 严格顺序回测明细：`{detail_path}`",
        f"- 严格顺序回测类型统计：`{type_path}`",
        f"- 严格顺序回测报告：`{report_path}`",
        "",
        "## 方法口径",
        "",
        "- 当前比赛只列出有非平衡亚盘意图标签的场次；平衡盘、等待临场、不计和盘口缺失不进入这张清单。",
        "- 历史回测按 `日期、开赛时间、比赛ID` 确定性排序；每一场只使用它之前已经结算的历史样本，不允许用赛后结果反推当场方向。",
        f"- 当前严格门槛：标签最小样本 `{cfg.get('min_tag_sample', '')}`，微观板块最小样本 `{cfg.get('min_micro_sample', '')}`，安全垫 `{cfg.get('safety_buffer', '')}`，同盘口同标签低胜率否决开启。",
        "",
        "## 严格顺序回测总览",
        "",
        f"- 完整测算比赛数：{s.get('完整测算比赛数', '')}",
        f"- 符合投注条件数：{s.get('符合投注条件数', '')}",
        f"- 已结算数：{s.get('已结算数', '')}",
        f"- 已结算投注数：{summary_get(s, '已结算投注数', '投注已结算数')}",
        f"- 不投数：{s.get('不投数', '')}",
        f"- 熔断拦截数：{s.get('熔断拦截数', '')}",
        f"- 实际总胜率：{pct(s.get('实际总胜率'))}",
        f"- 实际总负率：{pct(s.get('实际总负率'))}",
        f"- 实际总盈亏：{unit(s.get('实际总盈亏Unit'))}u",
        f"- 整体资金流水 ROI：{pct(s.get('整体资金流水ROI'))}",
        "",
        "## 当前有意图比赛分布",
        "",
        f"- 当前有意图比赛：{len(current)} 场",
        "",
        "### 按候选标签",
        "",
        md_table(tag_counts, ["候选标签", "当前场数"]),
        "",
        "### 按微观板块",
        "",
        md_table(region_counts, ["微观板块", "当前场数"]),
        "",
        "## 严格回测里表现较好的类型",
        "",
        "筛选口径：样本 >= 8、胜率 >= 55%、均注收益 > 0。",
        "",
        md_table(high, ["分组类型", "分组", "已结算投注数", "胜率", "盈亏Unit", "ROI", "红", "红半", "走水", "黑半", "黑"]),
        "",
        "## 严格回测里需要避开的类型",
        "",
        md_table(weak, ["分组类型", "分组", "已结算投注数", "胜率", "盈亏Unit", "ROI", "红", "红半", "走水", "黑半", "黑"]),
        "",
        "## 分微观板块",
        "",
        md_table(by_region, ["微观板块", "已结算投注数", "胜率", "负率", "盈亏Unit", "ROI", "红", "红半", "走水", "黑半", "黑"]),
        "",
        "## 分标签",
        "",
        md_table(by_tag, ["盘口意图标签", "已结算投注数", "胜率", "负率", "盈亏Unit", "ROI", "红", "红半", "走水", "黑半", "黑"]),
        top5_summary,
        "",
        "## 当前有意图比赛全清单",
        "",
        md_table(
            current,
            ["北京时间", "赛事", "比赛", "盘口档位", "候选标签", "正向球队", "反向球队", "正向水位", "反向水位", "亚盘"],
        ),
        "",
    ]

    out = SEQ_DIR / f"current_intent_strict_backtest_report_{stamp}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(out)
    print(f"current_intent_count={len(current)}")
    print(
        f"strict_bets={summary_get(s, '已结算投注数', '投注已结算数')} "
        f"win_rate={pct(s.get('实际总胜率'))} pnl={unit(s.get('实际总盈亏Unit'))}u"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
