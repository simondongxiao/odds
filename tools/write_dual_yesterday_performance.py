"""Settle yesterday's frozen V3/V4 bettable lists without recomputing decisions."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from asian_settlement import mirror_result, settle_giving

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
    text = str(value if value is not None else "").strip()
    aliases = {
        "平手": 0.0, "平手/半球": 0.25, "半球": 0.5, "半球/一球": 0.75,
        "一球": 1.0, "一球/球半": 1.25, "球半": 1.5, "球半/两球": 1.75,
        "两球": 2.0, "两球/两球半": 2.25, "两球半": 2.5,
    }
    if text in aliases:
        return aliases[text]
    return as_float(text.removesuffix("球").replace("+", ""))


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
    # Use floor/ceil so negative quarter lines split symmetrically:
    # -0.25 -> -0.5/0 and -0.75 -> -1/-0.5.
    return [math.floor(quarter * 2) / 2, math.ceil(quarter * 2) / 2]


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
    # A live feed drops yesterday's finished matches. Retain explicit final
    # observations from earlier snapshots, with their actual source paths.
    # Snapshot folders follow the natural capture date, not Titan list_date;
    # after midnight the same slate can span two adjacent folders.
    raw_root = raw_path.parent.parent
    paths = sorted(
        p for p in raw_root.glob("*/*_titan007_odds_snapshot.csv")
        if p.name <= raw_path.name
    )
    results: dict[str, dict[str, str]] = {}
    for path in paths:
        for row in read_csv(path):
            if str(row.get("list_date", "")) != target:
                continue
            mid = str(row.get("match_id", ""))
            row["_source"] = str(path)
            previous = results.get(mid, {})
            new_final = verified_final_score(row)[0] is not None
            old_final = verified_final_score(previous)[0] is not None
            if new_final or not old_final:
                results[mid] = row
    return results


def verified_final_score(source: dict[str, str]) -> tuple[int | None, int | None, str]:
    """Accept only Titan's explicit finished state; score text alone is not final."""
    state = str(source.get("state", "") or "").strip()
    if state != "-1":
        return None, None, f"NOT_FINAL_STATE_{state or 'UNKNOWN'}"
    hs, aws = as_float(source.get("home_score")), as_float(source.get("away_score"))
    if hs is None or aws is None:
        return None, None, "NO_VERIFIED_SCORE_IN_FINAL_SNAPSHOT"
    return int(hs), int(aws), ""


def settle_v3(rows: list[dict[str, Any]], raw: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        match_id = str(row.get("match_id", ""))
        source = raw.get(match_id, {})
        home, away = str(row.get("home_team", "")), str(row.get("away_team", ""))
        hs, aws, score_reason = verified_final_score(source)
        water = as_float(row.get("water"))
        team = str(row.get("selected_team", "")).split("（", 1)[0].strip()
        side = str(row.get("selected_side", ""))
        line = parse_line(row.get("line"))
        result, reason = "", ""
        if hs is None or aws is None:
            reason = score_reason
        elif water is None or line is None or team not in {home, away}:
            reason = "MISSING_FROZEN_SIDE_LINE_WATER_OR_TEAM"
        elif line == 0:
            result = "W" if (hs > aws if team == home else aws > hs) else "L" if (hs < aws if team == home else aws < hs) else "P"
        else:
            # Legacy freeze's side is the selected market side.  The frozen
            # line is a magnitude, so convert it to the home signed line
            # expected by settle(): giving side = negative handicap.
            giving_team = team if side == "upper" else (away if team == home else home)
            home_handicap = -line if giving_team == home else line
            giving_result = settle(int(hs), int(aws), "home" if giving_team == home else "away", home_handicap)
            result = giving_result if team == giving_team else {"W": "L", "HW": "HL", "P": "P", "HL": "HW", "L": "W"}[giving_result]
        out.append({
            "version": "V3", "match_id": match_id, "list_date": row.get("list_date", ""),
            "competition": row.get("competition", ""), "match": row.get("match", ""),
            "selected_team": team, "selected_side": side, "line": row.get("line", ""), "water": water or "",
            "score": f"{int(hs)}-{int(aws)}" if hs is not None and aws is not None else "",
            "result_state": str(source.get("state", "") or ""),
            "result": result, "pnl_1u": round(pnl(result, water), 4) if result and water is not None else "",
            "result_source": str(source.get("_source", "")), "settlement_status": "SETTLED" if result in RESULTS else reason,
            "decision_id": row.get("decision_id", ""), "run_id": row.get("run_id", ""), "model_id": row.get("model_id", "V3_LEGACY_PRODUCTION"),
            "quote_at": row.get("quote_at", ""), "last_confirmed_at": row.get("last_confirmed_at", ""), "kickoff_at": row.get("kickoff_at", ""),
            "hours_from_last_refresh_to_kickoff": row.get("hours_from_last_refresh_to_kickoff", ""), "is_morning_baseline": row.get("is_morning_baseline", False), "is_latest_valid_prematch": row.get("is_latest_valid_prematch", False),
        })
    return out


def settle_v4(rows: list[dict[str, Any]], raw: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        match_id = str(row.get("match_id", ""))
        source = raw.get(match_id, {})
        market = row.get("market", {}) or {}
        home = str(market.get("home_team", "")); away = str(market.get("away_team", ""))
        hs, aws, score_reason = verified_final_score(source)
        team = str(row.get("selected_team", row.get("candidate_team", "")))
        water = as_float(row.get("selected_water_hk"))
        selected_line = as_float(row.get("selected_handicap_signed"))
        candidate_side = str(row.get("selected_side", row.get("candidate_side", "")) or "").strip()
        result, reason = "", ""
        if hs is None or aws is None:
            reason = score_reason
        elif not home or not away or team not in {home, away} or water is None or selected_line is None:
            reason = "MISSING_V4_SIDE_LINE_WATER_OR_TEAM"
        else:
            # Titan's raw line field is a magnitude with the giving side encoded
            # separately.  V4 selected_handicap_signed uses -abs(line) for the
            # giving side and +abs(line) for the receiving side.  Settle from the
            # giving margin so a 2-2 result on -1.25 is L, not W.
            giving_team = str(market.get("giving_team", "") or "").strip()
            if giving_team not in {home, away}:
                reason = "MISSING_V4_GIVING_TEAM"
            else:
                giving_margin = int(hs) - int(aws) if giving_team == home else int(aws) - int(hs)
                giving_result = settle_giving(giving_margin, abs(selected_line))
                result = giving_result if candidate_side == "giving" else mirror_result(giving_result) if candidate_side == "receiving" else ""
                if not result:
                    reason = "MISSING_V4_CANDIDATE_SIDE"
        out.append({
            "version": "V4_SHADOW", "match_id": match_id, "list_date": row.get("list_date", ""),
            "competition": row.get("competition", ""), "match": f"{home} vs {away}",
            "selected_team": team, "selected_side": row.get("selected_side", row.get("candidate_side", "")),
            "line": row.get("selected_handicap_signed", ""), "water": water or "", "grade": row.get("grade", ""),
            "score": f"{int(hs)}-{int(aws)}" if hs is not None and aws is not None else "",
            "result_state": str(source.get("state", "") or ""),
            "result": result, "pnl_1u": round(pnl(result, water), 4) if result and water is not None else "",
            "result_source": str(source.get("_source", "")), "settlement_status": "SETTLED" if result in RESULTS else reason,
            "decision_id": row.get("decision_id", ""), "run_id": row.get("run_id", ""), "model_id": row.get("model_id", "V4_DIRECTION_FIXED_R1"),
            "quote_at": row.get("quote_at", (market or {}).get("quote_at", "")), "last_confirmed_at": row.get("last_confirmed_at", (market or {}).get("last_confirmed_at", "")), "kickoff_at": row.get("kickoff_at", row.get("kickoff", "")),
            "hours_from_last_refresh_to_kickoff": row.get("hours_from_last_refresh_to_kickoff", ""), "is_morning_baseline": row.get("is_morning_baseline", False), "is_latest_valid_prematch": row.get("is_latest_valid_prematch", False),
        })
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled = [row for row in rows if row.get("result") in RESULTS]
    counts = Counter(row["result"] for row in settled)
    pnl_total = sum(float(row["pnl_1u"]) for row in settled)
    return {"frozen_bettable": len(rows), "settled": len(settled), "counts": dict(counts), "effective_win_rate": effective_rate(counts), "pnl_1u": round(pnl_total, 4), "roi": round(pnl_total / len(rows), 4) if rows else None, "settled_roi": round(pnl_total / len(settled), 4) if settled else None, "roi_denominator": "FROZEN_BETTABLE_1U", "pending": len(rows) - len(settled)}


def cohort_summary(rows: list[dict[str, Any]], name: str, predicate) -> dict[str, Any]:
    selected = [row for row in rows if predicate(row)]
    result = summarize(selected)
    result["name"] = name
    return result


def cohort_line(name: str, result: dict[str, Any]) -> str:
    roi = "NA" if result["roi"] is None else f"{result['roi']:.2%}"
    return f"- {name}: n={result['settled']}；有效胜率={('NA' if result['effective_win_rate'] is None else f'{result['effective_win_rate']:.2%}')}；PnL={result['pnl_1u']:+.4f}U；ROI={roi}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-date", required=True)
    parser.add_argument("--raw-csv", required=True)
    args = parser.parse_args()
    target = args.list_date
    raw_path = Path(args.raw_csv)
    raw = raw_result_map(raw_path, target)
    for row in raw.values():
        row.setdefault("_source", str(raw_path))
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
    fields = ["version", "match_id", "list_date", "competition", "match", "selected_team", "selected_side", "line", "water", "grade", "score", "result_state", "result", "pnl_1u", "result_source", "settlement_status", "decision_id", "run_id", "model_id", "quote_at", "last_confirmed_at", "kickoff_at", "hours_from_last_refresh_to_kickoff", "is_morning_baseline", "is_latest_valid_prematch"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore"); writer.writeheader(); writer.writerows(all_rows)
    v3_summary, v4_summary = summarize(v3_settled), summarize(v4_settled)
    report_path = out_dir / f"yesterday_performance_{target}_{stamp}.md"
    def line(name: str, summary: dict[str, Any]) -> str:
        counts = summary["counts"]
        rate = "NA" if summary["effective_win_rate"] is None else f"{summary['effective_win_rate']:.2%}"
        roi = "NA" if summary["roi"] is None else f"{summary['roi']:.2%}"
        return f"- {name}: 冻结可投 {summary['frozen_bettable']}；已结算 {summary['settled']}；红/红半/走/黑半/黑 {counts.get('W',0)}/{counts.get('HW',0)}/{counts.get('P',0)}/{counts.get('HL',0)}/{counts.get('L',0)}；有效胜率 {rate}；1U平注盈亏 {summary['pnl_1u']:+.4f}U；ROI {roi}；待核 {summary['pending']}"
    all_settled = v3_settled + v4_settled
    def morning(row: dict[str, Any]) -> bool:
        text = str(row.get("kickoff_at", ""))
        try:
            hour = dt.datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(CN_TZ).hour
        except ValueError:
            return False
        return 4 <= hour < 10
    def other(row: dict[str, Any]) -> bool: return not morning(row)
    def latest(row: dict[str, Any]) -> bool: return str(row.get("is_latest_valid_prematch", "")).lower() in {"true", "1"}
    def baseline(row: dict[str, Any]) -> bool: return str(row.get("is_morning_baseline", "")).lower() in {"true", "1"}
    cohort_lines = ["", "## 报价时段监控（不改变策略）"]
    for label, predicate in (("ALL", lambda row: True), ("04:00-10:00", morning), ("其他时段", other), ("MORNING_BASELINE", baseline), ("LATEST_VALID_PREMATCH", latest)):
        cohort_lines.append(cohort_line("V3 " + label, cohort_summary(v3_settled, label, predicate)))
        cohort_lines.append(cohort_line("V4 " + label, cohort_summary(v4_settled, label, predicate)))
    report_path.write_text("\n".join([f"# {target} V3/V4 昨日冻结名单结算", "", "- 仅合并冻结决策与当前 Titan 终场比分；没有重算昨日方向、盘口、水位、概率或等级。", "- V4 为 Shadow，不代表真实下注。", line("V3 Production", v3_summary), line("V4 Shadow ABC", v4_summary), *cohort_lines, "", f"- 逐场文件：`{csv_path}`", f"- 结果源快照：`{raw_path}`", ""]) , encoding="utf-8")
    print(json.dumps({"target": target, "v3": v3_summary, "v4": v4_summary, "csv": str(csv_path), "report": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
