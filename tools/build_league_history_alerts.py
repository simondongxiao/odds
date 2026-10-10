from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import load_workbook


SETTLED_LABELS = {"红", "半红", "走", "半黑", "黑"}


def clean(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", "", text).strip()


def clean_team(value: object) -> str:
    text = re.sub(r"（反向=[^）]+）|（(?:上盘|下盘)）", "", str(value or ""))
    return re.sub(r"<[^>]+>", "", html.unescape(text)).strip()


def kickoff_beijing(item: dict[str, str]) -> str:
    raw = str(item.get("kickoff_at") or item.get("kickoff_beijing") or "").strip()
    if not raw:
        return "时间待核"
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})", raw)
        if match:
            year, month, day, hour, minute = map(int, match.groups())
            return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"
    return raw.replace("北京时间（东8区）", "").strip()


def settled_pnl(result: str, water: object) -> float | None:
    try:
        odds = float(water)
    except (TypeError, ValueError):
        return None
    return {
        "红": odds,
        "半红": odds * 0.5,
        "走": 0.0,
        "半黑": -0.5,
        "黑": -1.0,
    }.get(result)


def read_history(path: Path, cutoff: str) -> dict[str, dict[str, object]]:
    wb = load_workbook(path, data_only=True, read_only=False)
    ws = wb["赛事明细"]
    table = next(iter(ws.tables.values()))
    last = int("".join(ch for ch in table.ref.split(":")[-1] if ch.isdigit()))
    headers = {clean(ws.cell(3, col).value): col for col in range(1, ws.max_column + 1)}
    date_col = headers.get("日期筛选", 1)
    competition_col = headers.get("联赛/杯赛", 5)
    status_col = headers.get("结算状态", 16)
    result_col = headers.get("红黑", 17)
    water_col = headers.get("投注水位", 18)
    pnl_col = headers.get("盈亏(u)", 19)
    match_col = headers.get("具体比赛", 6)
    score_col = headers.get("赛果", 15)
    team_col = headers.get("投注方", 12)
    line_col = headers.get("即时盘口", 8)
    action_col = headers.get("投注动作", 14)
    source_col = headers.get("比分来源", headers.get("来源", 20))
    stats: dict[str, dict[str, object]] = defaultdict(
        lambda: {"counts": Counter(), "pnl": 0.0, "pnl_rows": 0, "details": []}
    )
    for row in range(4, last + 1):
        list_date = str(ws.cell(row, date_col).value or "")[:10]
        if not list_date or list_date >= cutoff:
            continue
        if clean(ws.cell(row, status_col).value) != "已结算":
            continue
        result = clean(ws.cell(row, result_col).value).replace("红半", "半红").replace("黑半", "半黑")
        if result not in SETTLED_LABELS:
            continue
        competition = clean(ws.cell(row, competition_col).value)
        if competition:
            bucket = stats[competition]
            counts = bucket["counts"]
            assert isinstance(counts, Counter)
            counts[result] += 1
            pnl = None
            if pnl_col:
                raw_pnl = ws.cell(row, pnl_col).value
                try:
                    pnl = float(raw_pnl)
                except (TypeError, ValueError):
                    pnl = None
            if pnl is None:
                pnl = settled_pnl(result, ws.cell(row, water_col).value)
            if pnl is not None:
                bucket["pnl"] = float(bucket["pnl"]) + pnl
                bucket["pnl_rows"] = int(bucket["pnl_rows"]) + 1
            details = bucket["details"]
            assert isinstance(details, list)
            details.append(
                {
                    "date": list_date,
                    "match": clean_team(ws.cell(row, match_col).value),
                    "score": clean(ws.cell(row, score_col).value),
                    "selected_team": clean_team(ws.cell(row, team_col).value),
                    "settlement": result,
                    "water": ws.cell(row, water_col).value,
                    "pnl_1u": round(float(pnl), 4) if pnl is not None else "",
                    "roi": round(float(pnl), 8) if pnl is not None else "",
                    "line": clean(ws.cell(row, line_col).value),
                    "action": clean(ws.cell(row, action_col).value),
                    "source": clean(ws.cell(row, source_col).value),
                }
            )
    return stats


def rate(counter: Counter) -> float | None:
    denominator = counter["红"] + 0.5 * counter["半红"] + counter["黑"] + 0.5 * counter["半黑"]
    return (counter["红"] + 0.5 * counter["半红"]) / denominator if denominator else None


def read_bettable(path: Path, version: str) -> list[dict[str, str]]:
    valid = {"可投", "半仓可投"} if version == "V3" else {"BET_GIVING", "BET_RECEIVING"}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row.get("action") in valid]


def read_all_matches(path: Path, version: str) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, str]] = []
    for item in payload.get("matches", []) or []:
        # Current public snapshots are flattened.  Older bridge snapshots used
        # identity + v3_decision/v4_shadow.  Accept both shapes so that a
        # daily history refresh never silently emits blank match rows.
        identity = item.get("identity") or {}
        decision = item.get("v3_decision" if version == "V3" else "v4_shadow") or {}
        market = item.get("market") or {}
        if not identity and item.get("match_id"):
            identity = {
                "list_date": item.get("list_date", payload.get("list_date", "")),
                "match_id": item.get("match_id", ""),
                "competition": item.get("competition") or market.get("competition", ""),
                "kickoff": item.get("kickoff") or item.get("kickoff_at", ""),
                "home": item.get("home_team") or market.get("home_team", ""),
                "away": item.get("away_team") or market.get("away_team", ""),
            }
            decision = item
        rows.append({
            "list_date": str(identity.get("list_date", payload.get("list_date", ""))),
            "match_id": str(identity.get("match_id", "")),
            "competition": str(identity.get("competition", "")),
            "kickoff": str(identity.get("kickoff", "")),
            "home_team": str(identity.get("home", "")),
            "away_team": str(identity.get("away", "")),
            "selected_team": str(decision.get("team", "")),
            "market_side": str(decision.get("side", "")),
            "action": str(decision.get("action", decision.get("status", ""))),
        })
    return rows


def evaluate(version: str, ledger: Path, bettable: Path, cutoff: str, matches_json: Path | None = None) -> list[dict[str, object]]:
    history = read_history(ledger, cutoff)
    output = []
    current_rows = read_all_matches(matches_json, version) if matches_json else read_bettable(bettable, version)
    for item in current_rows:
        competition = clean(item.get("competition"))
        bucket = history.get(competition, {"counts": Counter(), "pnl": 0.0, "pnl_rows": 0, "details": []})
        counts = bucket["counts"]
        assert isinstance(counts, Counter)
        sample = sum(counts.values())
        win_rate = rate(counts)
        pnl = float(bucket["pnl"])
        roi = pnl / sample if sample else None
        history_details = list(bucket.get("details", []))
        if sample >= 8 and win_rate is not None and win_rate < 0.45:
            alert = "严重：历史有效胜率<45%"
        else:
            alert = ""
        if sample >= 8 and win_rate is not None and win_rate > 0.55:
            band = "高：历史有效胜率>55%"
        else:
            band = alert
        output.append(
            {
                "version": version,
                "list_date": item.get("list_date", cutoff),
                "match_id": item.get("match_id", ""),
                "competition": item.get("competition", ""),
                "kickoff_beijing": kickoff_beijing(item),
                "match": f"{clean_team(item.get('home_team'))} vs {clean_team(item.get('away_team'))}",
                "selected_team": clean_team(item.get("selected_team")),
                "market_side": item.get("market_side", ""),
                "historical_settled_sample": sample,
                "红": counts["红"],
                "半红": counts["半红"],
                "走": counts["走"],
                "半黑": counts["半黑"],
                "黑": counts["黑"],
                "effective_win_rate": "" if win_rate is None else round(win_rate, 8),
                "pnl_1u": round(pnl, 4) if sample else "",
                "roi": round(roi, 8) if roi is not None else "",
                "pnl_rows": int(bucket["pnl_rows"]),
                "alert_band": alert,
                "rate_band": band,
                "history_cutoff": f"list_date < {cutoff}",
                "history_matches": history_details,
            }
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="V3/V4 exact-competition dynamic history warning")
    parser.add_argument("--list-date", required=True)
    parser.add_argument("--v3-ledger", type=Path, required=True)
    parser.add_argument("--v4-ledger", type=Path, required=True)
    parser.add_argument("--v3-bettable", type=Path, required=True)
    parser.add_argument("--v4-bettable", type=Path, required=True)
    parser.add_argument("--matches-json", type=Path, default=None)
    parser.add_argument("--v3-matches-json", type=Path, default=None)
    parser.add_argument("--v4-matches-json", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    v3_json = args.v3_matches_json or args.matches_json
    v4_json = args.v4_matches_json or args.matches_json
    all_rows = evaluate("V3", args.v3_ledger, args.v3_bettable, args.list_date, v3_json)
    all_rows += evaluate("V4", args.v4_ledger, args.v4_bettable, args.list_date, v4_json)
    alerts = [row for row in all_rows if row["alert_band"]]
    fields = list(all_rows[0].keys()) if all_rows else []
    csv_path = args.output_dir / f"league_history_alert_{args.list_date}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)
    md_path = args.output_dir / f"league_history_alert_{args.list_date}.md"
    lines = [
        f"# {args.list_date} V3/V4 同名联赛历史动态复核",
        "",
        "口径：V3、V4分开；仅统计当前列表日前已结算的同名联赛；历史已结算场次>8且有效胜率>55%列为高胜率参考，<45%列为低胜率风险；45%-55%不纳入高低胜率列表；走盘不进入有效胜率分母；ROI=平注1U累计PnL/已结算样本。",
        "",
    ]
    def table(rows: list[dict[str, object]]) -> list[str]:
        lines = ["| 级别 | 联赛 | 历史已结算 | 有效胜率 | PnL(1U) | ROI | 北京时间 | 比赛 | 投注球队 | 盘向 |", "|---|---|---:|---:|---:|---:|---|---|---|---|"]
        for row in rows:
            roi = "—" if row["roi"] == "" else f"{float(row['roi']):.1%}"
            pnl = "—" if row["pnl_1u"] == "" else f"{float(row['pnl_1u']):+.2f}U"
            lines.append(f"| {row['rate_band']} | {row['competition']} | {row['historical_settled_sample']} | {float(row['effective_win_rate']):.1%} | {pnl} | {roi} | {row['kickoff_beijing']} | {row['match']} | {row['selected_team']} | {row['market_side']} |")
        return lines

    for version in ("V3", "V4"):
        version_high = [row for row in all_rows if row["version"] == version and row["rate_band"] == "高：历史有效胜率>55%"]
        version_alerts = [row for row in alerts if row["version"] == version]
        lines += [f"## {version}", ""]
        lines += ["### 高胜率参考（历史已结算场次>8且有效胜率>55%）", ""]
        lines += table(version_high) if version_high else ["无。"]
        lines.append("")
        lines += ["### 低胜率风险（历史已结算场次>8且有效胜率<45%）", ""]
        if not version_alerts:
            lines += ["无触发。", ""]
            continue
        lines += table(version_alerts)
        lines.append("")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {
        "list_date": args.list_date,
        "rows_checked": len(all_rows),
        "alerts": len(alerts),
        "v3_alerts": sum(row["version"] == "V3" for row in alerts),
        "v4_alerts": sum(row["version"] == "V4" for row in alerts),
        "high_rate_rows": sum(row["rate_band"] == "高：历史有效胜率>55%" for row in all_rows),
        "v3_high_rate_rows": sum(row["version"] == "V3" and row["rate_band"] == "高：历史有效胜率>55%" for row in all_rows),
        "v4_high_rate_rows": sum(row["version"] == "V4" and row["rate_band"] == "高：历史有效胜率>55%" for row in all_rows),
        "rows": all_rows,
        "csv": str(csv_path),
        "markdown": str(md_path),
    }
    (args.output_dir / f"league_history_alert_{args.list_date}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
