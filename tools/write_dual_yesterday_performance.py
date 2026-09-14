"""Settle yesterday's frozen V3/V4 bettable lists without recomputing decisions."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(r"D:\codex")
OUT = ROOT / "outputs" / "football_odds_trader"
CN_TZ = dt.timezone(dt.timedelta(hours=8))
RESULTS = {"W", "HW", "P", "HL", "L"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def as_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_line(value: Any) -> float | None:
    text = str(value or "").strip()
    aliases = {
        "平手": 0.0, "平手/半球": 0.25, "半球": 0.5, "半球/一球": 0.75,
        "一球": 1.0, "一球/球半": 1.25, "球半": 1.5, "球半/两球": 1.75,
        "两球": 2.0, "两球/两球半": 2.25, "两球半": 2.5,
    }
    if text in aliases:
        return aliases[text]
    return as_float(text.replace("+", ""))


def one(diff: float, handicap: float) -> str:
    value = diff + handicap
    if value > 1e-9:
        return "W"
    if value < -1e-9:
        return "L"
    return "P"


def split_handicap(value: float) -> list[float]:
    quarter = round(value * 4) / 4
    if int(round(quarter * 4)) % 2 == 0:
        return [quarter]
    return [int(quarter * 2) / 2, (int(quarter * 2) + 1) / 2]


def settle(home_goals: int, away_goals: int, selection: str, home_handicap: float) -> str:
    diff = home_goals - away_goals if selection == "home" else away_goals - home_goals
    signed = home_handicap if selection == "home" else -home_handicap
    parts = [one(diff, part) for part in split_handicap(signed)]
    if parts == ["W"]:
        return "W"
    if parts == ["L"]:
        return "L"
    if parts == ["P"]:
        return "P"
    if parts == ["W", "W"]:
        return "W"
    if parts == ["L", "L"]:
        return "L"
    if parts == ["P", "P"]:
        return "P"
    if set(parts) == {"W", "P"}:
        return "HW"
    if set(parts) == {"L", "P"}:
        return "HL"
    raise ValueError(f"unsupported settlement parts: {parts}")


def pnl(result: str, water: float) -> float:
    return {"W": water, "HW": water / 2, "P": 0.0, "HL": -0.5, "L": -1.0}[result]


def effective_rate(counter: Counter[str]) -> float | None:
    wins = counter["W"] + 0.5 * counter["HW"]
    losses = counter["L"] + 0.5 * counter["HL"]
    return wins / (wins + losses) if wins + losses else None


def raw_result_map(raw_path: Path, target: str) -> dict[str, dict[str, str]]:
    return {str(row.get("match_id", "")): row for row in read_csv(raw_path) if str(row.get("list_date", "")) == target}


def settle_v3(rows: list[dict[str, Any]], raw: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        match_id = str(row.get("match_id", ""))
        source = raw.get(match_id, {})
        home, away = str(row.get("home_team", "")), str(row.get("away_team", ""))
        hs, aws = as_float(source.get("home_score")), as_float(source.get("away_score"))
        water = as_float(row.get("water"))
        team = str(row.get("selected_team", "")).split("（", 1)[0].strip()
        side = str(row.get("selected_side", ""))
        line = parse_line(row.get("line"))
        result, reason = "", ""
        if hs is None or aws is None:
            reason = "NO_VERIFIED_SCORE_IN_CURRENT_TITAN_SNAPSHOT"
        elif water is None or line is None or team not in {home, away}:
            reason = "MISSING_FROZEN_SIDE_LINE_WATER_OR_TEAM"
        elif line == 0:
            result = "W" if (hs > aws if team == home else aws > hs) else "L" if (hs < aws if team == home else aws < hs) else "P"
        else:
            # Legacy freeze stores upper/lower identity; preserve it while using the frozen line magnitude.
            giving_team = team if side == "upper" else (away if team == home else home)
            giving_margin = (hs - aws) if giving_team == home else (aws - hs)
            giving_result = settle(int(hs), int(aws), "home" if giving_team == home else "away", line)
            result = giving_result if team == giving_team else {"W": "L", "HW": "HL", "P": "P", "HL": "HW", "L": "W"}[giving_result]
        out.append({
            "version": "V3", "match_id": match_id, "list_date": row.get("list_date", ""),
            "competition": row.get("competition", ""), "match": row.get("match", ""),
            "selected_team": team, "selected_side": side, "line": row.get("line", ""), "water": water or "",
            "score": f"{int(hs)}-{int(aws)}" if hs is not None and aws is not None else "",
            "result": result, "pnl_1u": round(pnl(result, water), 4) if result and water is not None else "",
            "result_source": str(source.get("_source", "")), "settlement_status": "SETTLED" if result in RESULTS else reason,
        })
    return out


def settle_v4(rows: list[dict[str, Any]], raw: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        match_id = str(row.get("match_id", ""))
        source = raw.get(match_id, {})
        market = row.get("market", {}) or {}
        home = str(market.get("home_team", "")); away = str(market.get("away_team", ""))
        hs, aws = as_float(source.get("home_score")), as_float(source.get("away_score"))
        team = str(row.get("selected_team", row.get("candidate_team", "")))
        water = as_float(row.get("selected_water_hk"))
        home_line = as_float(market.get("titan_home_handicap_signed", market.get("home_handicap_signed")))
        result, reason = "", ""
        if hs is None or aws is None:
            reason = "NO_VERIFIED_SCORE_IN_CURRENT_TITAN_SNAPSHOT"
        elif not home or not away or team not in {home, away} or water is None or home_line is None:
            reason = "MISSING_V4_SIDE_LINE_WATER_OR_TEAM"
        else:
            result = settle(int(hs), int(aws), "home" if team == home else "away", home_line)
        out.append({
            "version": "V4_SHADOW", "match_id": match_id, "list_date": row.get("list_date", ""),
            "competition": row.get("competition", ""), "match": f"{home} vs {away}",
            "selected_team": team, "selected_side": row.get("selected_side", row.get("candidate_side", "")),
            "line": row.get("selected_handicap_signed", ""), "water": water or "", "grade": row.get("grade", ""),
            "score": f"{int(hs)}-{int(aws)}" if hs is not None and aws is not None else "",
            "result": result, "pnl_1u": round(pnl(result, water), 4) if result and water is not None else "",
            "result_source": str(source.get("_source", "")), "settlement_status": "SETTLED" if result in RESULTS else reason,
        })
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled = [row for row in rows if row.get("result") in RESULTS]
    counts = Counter(row["result"] for row in settled)
    pnl_total = sum(float(row["pnl_1u"]) for row in settled)
    return {"frozen_bettable": len(rows), "settled": len(settled), "counts": dict(counts), "effective_win_rate": effective_rate(counts), "pnl_1u": round(pnl_total, 4), "roi": round(pnl_total / len(settled), 4) if settled else None, "pending": len(rows) - len(settled)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-date", required=True)
    parser.add_argument("--raw-csv", required=True)
    args = parser.parse_args()
    target = args.list_date
    raw_path = Path(args.raw_csv)
    raw = raw_result_map(raw_path, target)
    for row in raw.values():
        row["_source"] = str(raw_path)
    bridge_path = ROOT / "bridge" / "v3_production" / f"{target}.json"
    v3_payload = json.loads(bridge_path.read_text(encoding="utf-8")) if bridge_path.exists() else {"matches": []}
    v3_rows = [row for row in v3_payload.get("matches", []) if str(row.get("action", "")) in {"可投", "半仓可投"}]
    v4_path = ROOT / "v4" / "outputs" / f"v4_decisions_{target}.json"
    v4_payload = json.loads(v4_path.read_text(encoding="utf-8")) if v4_path.exists() else {"matches": []}
    v4_rows = [row for row in v4_payload.get("matches", []) if row.get("grade") in {"A", "B", "C"}]
    v3_settled = settle_v3(v3_rows, raw)
    v4_settled = settle_v4(v4_rows, raw)
    stamp = dt.datetime.now(CN_TZ).strftime("%Y%m%d_%H%M%S")
    out_dir = OUT / "reviews" / "daily_performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"yesterday_performance_{target}_{stamp}.csv"
    all_rows = v3_settled + v4_settled
    fields = ["version", "match_id", "list_date", "competition", "match", "selected_team", "selected_side", "line", "water", "grade", "score", "result", "pnl_1u", "result_source", "settlement_status"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore"); writer.writeheader(); writer.writerows(all_rows)
    v3_summary, v4_summary = summarize(v3_settled), summarize(v4_settled)
    report_path = out_dir / f"yesterday_performance_{target}_{stamp}.md"
    def line(name: str, summary: dict[str, Any]) -> str:
        counts = summary["counts"]
        rate = "NA" if summary["effective_win_rate"] is None else f"{summary['effective_win_rate']:.2%}"
        roi = "NA" if summary["roi"] is None else f"{summary['roi']:.2%}"
        return f"- {name}: 冻结可投 {summary['frozen_bettable']}；已结算 {summary['settled']}；红/红半/走/黑半/黑 {counts.get('W',0)}/{counts.get('HW',0)}/{counts.get('P',0)}/{counts.get('HL',0)}/{counts.get('L',0)}；有效胜率 {rate}；1U平注盈亏 {summary['pnl_1u']:+.4f}U；ROI {roi}；待核 {summary['pending']}"
    report_path.write_text("\n".join([f"# {target} V3/V4 昨日冻结名单结算", "", "- 仅合并冻结决策与当前 Titan 终场比分；没有重算昨日方向、盘口、水位、概率或等级。", "- V4 为 Shadow，不代表真实下注。", line("V3 Production", v3_summary), line("V4 Shadow ABC", v4_summary), "", f"- 逐场文件：`{csv_path}`", f"- 结果源快照：`{raw_path}`", ""]) , encoding="utf-8")
    print(json.dumps({"target": target, "v3": v3_summary, "v4": v4_summary, "csv": str(csv_path), "report": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
