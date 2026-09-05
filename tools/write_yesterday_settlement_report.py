from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


BASE = Path(r"D:\codex\outputs\football_odds_trader")
LEDGER = BASE / "ledger"
REVIEWS = BASE / "reviews"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def to_float(value: str | None) -> float:
    try:
        return float(str(value or "0").replace("+", ""))
    except ValueError:
        return 0.0


def signed(value: float) -> str:
    return f"{value:+.3f}"


def rate_fmt(value: float | None) -> str:
    return "NA" if value is None else f"{value * 100:.1f}%"


def settle_counts(rows: list[dict[str, str]], col: str) -> dict[str, int]:
    counts = Counter((r.get(col) or "").strip() for r in rows)
    return {
        "红": counts["赢"],
        "红半": counts["赢半"],
        "走水": counts["走"],
        "黑半": counts["输半"],
        "黑": counts["输"],
    }


def effective_rate(counts: dict[str, int]) -> float | None:
    wins = counts["红"] + 0.5 * counts["红半"]
    losses = counts["黑"] + 0.5 * counts["黑半"]
    denom = wins + losses
    return None if denom == 0 else wins / denom


def summarize(rows: list[dict[str, str]], cols: dict[str, str]) -> dict[str, object]:
    forward_counts = settle_counts(rows, cols["forward_settle"])
    reverse_counts = settle_counts(rows, cols["reverse_settle"])
    forward_pnl = sum(to_float(r.get(cols["forward_pnl"])) for r in rows)
    reverse_pnl = sum(to_float(r.get(cols["reverse_pnl"])) for r in rows)
    forward_rate = effective_rate(forward_counts)
    reverse_rate = effective_rate(reverse_counts)

    if len(rows) < 8:
        advice = "小样本观察"
    elif forward_pnl > 0 and (forward_rate or 0) >= (reverse_rate or 0):
        advice = "正向优先"
    elif reverse_pnl > 0 and (reverse_rate or 0) > (forward_rate or 0):
        advice = "反向优先"
    elif forward_pnl > reverse_pnl:
        advice = "正向较好但未过阈值"
    elif reverse_pnl > forward_pnl:
        advice = "反向较好但未过阈值"
    else:
        advice = "无明显优势"

    return {
        "样本": len(rows),
        "正向红": forward_counts["红"],
        "正向红半": forward_counts["红半"],
        "正向走水": forward_counts["走水"],
        "正向黑半": forward_counts["黑半"],
        "正向黑": forward_counts["黑"],
        "正向有效胜率": rate_fmt(forward_rate),
        "正向均注盈亏Unit": signed(forward_pnl),
        "反向红": reverse_counts["红"],
        "反向红半": reverse_counts["红半"],
        "反向走水": reverse_counts["走水"],
        "反向黑半": reverse_counts["黑半"],
        "反向黑": reverse_counts["黑"],
        "反向有效胜率": rate_fmt(reverse_rate),
        "反向均注盈亏Unit": signed(reverse_pnl),
        "读法": advice,
    }


def load_dashboard_status(target_date: str) -> tuple[int, Counter[str]]:
    html_path = BASE / "dashboard" / "index.html"
    if not html_path.exists():
        return 0, Counter()
    text = html_path.read_text(encoding="utf-8")
    match = re.search(r"const cardsData = (\[.*?\]);\n", text, re.S)
    if not match:
        return 0, Counter()
    cards = json.loads(match.group(1))
    rows = [r for r in cards if r.get("date") == target_date]
    return len(rows), Counter(str(r.get("display_status") or "") for r in rows)


def build_report(target_date: str) -> dict[str, Path | int | str]:
    REVIEWS.mkdir(parents=True, exist_ok=True)
    LEDGER.mkdir(parents=True, exist_ok=True)

    hist_path = sorted(LEDGER.glob("asian_intent_history_detail_*.csv"))[-1]
    sim_path = LEDGER / "simulated_bets.csv"
    hist_rows = read_csv(hist_path)
    sim_rows = read_csv(sim_path)
    hist_header = list(hist_rows[0].keys())
    sim_header = list(sim_rows[0].keys())

    hist_cols = {
        "date": hist_header[0],
        "event": hist_header[1],
        "class": hist_header[2],
        "match": hist_header[3],
        "score": hist_header[4],
        "line_bucket": hist_header[10],
        "tag": hist_header[12],
        "side": hist_header[14],
        "forward_settle": hist_header[16],
        "forward_pnl": hist_header[18],
        "reverse_settle": hist_header[21],
        "reverse_pnl": hist_header[23],
    }
    sim_cols = {
        "date": sim_header[0],
        "event": sim_header[1],
        "match": sim_header[2],
        "market": sim_header[5],
        "price": sim_header[6],
        "direction": sim_header[7],
        "score": sim_header[15],
        "pnl": sim_header[16],
        "update": sim_header[19],
    }

    official = [r for r in sim_rows if r.get(sim_cols["date"]) == target_date]
    candidates_all = [r for r in hist_rows if r.get(hist_cols["date"]) == target_date]
    countable = [
        r
        for r in candidates_all
        if r.get(hist_cols["side"]) in {"上盘", "下盘"}
        and r.get(hist_cols["forward_settle"]) in {"赢", "赢半", "走", "输半", "输"}
    ]

    official_detail_path = LEDGER / f"yesterday_official_settlement_{target_date}.csv"
    with official_detail_path.open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["日期", "赛事", "比赛", "市场框架", "模拟盘口/价格", "模拟方向", "赛果", "模拟盈亏单位", "模型更新"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in official:
            writer.writerow(
                {
                    "日期": row.get(sim_cols["date"], ""),
                    "赛事": row.get(sim_cols["event"], ""),
                    "比赛": row.get(sim_cols["match"], ""),
                    "市场框架": row.get(sim_cols["market"], ""),
                    "模拟盘口/价格": row.get(sim_cols["price"], ""),
                    "模拟方向": row.get(sim_cols["direction"], ""),
                    "赛果": row.get(sim_cols["score"], ""),
                    "模拟盈亏单位": row.get(sim_cols["pnl"], ""),
                    "模型更新": row.get(sim_cols["update"], ""),
                }
            )

    candidate_detail_path = LEDGER / f"yesterday_candidate_intent_detail_{target_date}.csv"
    with candidate_detail_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=hist_header)
        writer.writeheader()
        writer.writerows(countable)

    summary_rows: list[dict[str, str | int]] = []

    def add_group(group_type: str, group_name: str, rows: list[dict[str, str]]) -> None:
        summary_rows.append({"分组类型": group_type, "分组": group_name, **summarize(rows, hist_cols)})

    add_group("总计", f"{target_date} 候选亚盘意图", countable)
    for group_type, col in [
        ("按候选标签", hist_cols["tag"]),
        ("按盘口档位", hist_cols["line_bucket"]),
        ("按比赛分类", hist_cols["class"]),
        ("按赛事", hist_cols["event"]),
    ]:
        groups: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
        for row in countable:
            groups[row.get(col) or "未识别"].append(row)
        for name, rows in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
            add_group(group_type, name, rows)

    for group_type, cols in [
        ("按盘口档位+标签", (hist_cols["line_bucket"], hist_cols["tag"])),
        ("按比赛分类+标签", (hist_cols["class"], hist_cols["tag"])),
    ]:
        groups = defaultdict(list)
        for row in countable:
            groups["/".join(row.get(col) or "未识别" for col in cols)].append(row)
        for name, rows in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
            add_group(group_type, name, rows)

    summary_path = LEDGER / f"yesterday_candidate_intent_summary_{target_date}.csv"
    fields = [
        "分组类型",
        "分组",
        "样本",
        "正向红",
        "正向红半",
        "正向走水",
        "正向黑半",
        "正向黑",
        "正向有效胜率",
        "正向均注盈亏Unit",
        "反向红",
        "反向红半",
        "反向走水",
        "反向黑半",
        "反向黑",
        "反向有效胜率",
        "反向均注盈亏Unit",
        "读法",
    ]
    with summary_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary_rows)

    dashboard_count, dashboard_status = load_dashboard_status(target_date)
    market_counts = Counter(row.get(sim_cols["market"], "") for row in official)
    pnl_counts = Counter(row.get(sim_cols["pnl"], "") for row in official)

    report_path = REVIEWS / f"yesterday_settlement_{target_date}.md"
    lines: list[str] = [
        f"# {target_date} 昨日比赛结算统计",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 北京时间",
        f"- dashboard 状态：{dashboard_count} 场；" + "，".join(f"{k} {v}" for k, v in dashboard_status.items()),
        f"- 官方模拟账本：{len(official)} 场；亚盘EV待筛选 {market_counts.get('亚盘意图框架-待EV筛选', 0)} 场，盘口缺失不形成模拟 {market_counts.get('亚盘盘口缺失-不形成模拟', 0)} 场。",
        f"- 官方盈亏口径：{dict(pnl_counts)}；这些行未冻结为正式可投方向，只允许回补比分，不计算官方红黑。",
        f"- 候选亚盘意图审计：{len(candidates_all)} 场有候选记录，其中 {len(countable)} 场可按即时亚盘和赛果做正反向红黑测算。",
        "",
        "## 候选意图总览",
        "| 样本 | 正向红/红半/走/黑半/黑 | 正向胜率 | 正向盈亏 | 反向红/红半/走/黑半/黑 | 反向胜率 | 反向盈亏 |",
        "|---:|---|---:|---:|---|---:|---:|",
    ]
    total = summary_rows[0]
    lines.append(
        f"| {total['样本']} | {total['正向红']}/{total['正向红半']}/{total['正向走水']}/{total['正向黑半']}/{total['正向黑']} | "
        f"{total['正向有效胜率']} | {total['正向均注盈亏Unit']} | "
        f"{total['反向红']}/{total['反向红半']}/{total['反向走水']}/{total['反向黑半']}/{total['反向黑']} | "
        f"{total['反向有效胜率']} | {total['反向均注盈亏Unit']} |"
    )
    lines.append("")

    for title, group_type, limit in [
        ("按候选标签", "按候选标签", 20),
        ("按盘口档位", "按盘口档位", 20),
        ("按比赛分类", "按比赛分类", 20),
        ("按赛事", "按赛事", 30),
    ]:
        rows = [r for r in summary_rows if r["分组类型"] == group_type][:limit]
        lines.extend(
            [
                f"## {title}",
                "| 分组 | 样本 | 正向胜率 | 正向盈亏 | 反向胜率 | 反向盈亏 | 读法 |",
                "|---|---:|---:|---:|---:|---:|---|",
            ]
        )
        for row in rows:
            lines.append(
                f"| {row['分组']} | {row['样本']} | {row['正向有效胜率']} | {row['正向均注盈亏Unit']} | "
                f"{row['反向有效胜率']} | {row['反向均注盈亏Unit']} | {row['读法']} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 文件",
            f"- 官方逐场比分：`{official_detail_path}`",
            f"- 候选意图逐场：`{candidate_detail_path}`",
            f"- 候选意图分组统计：`{summary_path}`",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "report": report_path,
        "official_detail": official_detail_path,
        "candidate_detail": candidate_detail_path,
        "candidate_summary": summary_path,
        "official_rows": len(official),
        "dashboard_cards": dashboard_count,
        "candidate_countable": len(countable),
        "forward_rate": str(total["正向有效胜率"]),
        "forward_pnl": str(total["正向均注盈亏Unit"]),
        "reverse_rate": str(total["反向有效胜率"]),
        "reverse_pnl": str(total["反向均注盈亏Unit"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("date", help="YYYY-MM-DD")
    args = parser.parse_args()
    result = build_report(args.date)
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
