from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(r"D:\codex")
OUTPUT = ROOT / "outputs" / "football_odds_trader"
VERSION_ROOT = OUTPUT / "decision_versions"
EXECUTION_ROOT = OUTPUT / "executions"


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def now_cn() -> datetime:
    return datetime.now(timezone.utc).astimezone(timezone.utc).replace(tzinfo=timezone.utc)


def run_id(now: datetime | None = None) -> str:
    # UTC is used for uniqueness; the run manifest also stores the local time.
    value = now or datetime.now(timezone.utc)
    return "RUN_" + value.astimezone(timezone.utc).strftime("%Y%m%d_%H%M%S")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return ""


def flatten_v3(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "match_id": str(_value(row, "match_id", "比赛ID")),
        "action": _value(row, "action", "下注建议"),
        "team": _value(row, "selected_team", "team", "投注球队"),
        "side": _value(row, "selected_side", "market_side", "方向"),
        "line": _value(row, "line", "handicap", "盘口", "模拟盘口/价格"),
        "water": _value(row, "water", "selected_water", "selected_water_hk", "水位"),
        "probability": _value(row, "probability", "displayed_probability", "综合概率"),
        "decision_at": _value(row, "decision_at"),
        "decision_source": _value(row, "decision_source", "source_card", "source"),
        "frozen": _value(row, "frozen"),
        "status": _value(row, "status", "settlement", "状态"),
        "score": _value(row, "score", "赛果"),
    }


def flatten_v4(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "match_id": str(_value(row, "match_id")),
        "grade": _value(row, "grade", "shadow_grade"),
        "team": _value(row, "candidate_team", "selected_team"),
        "side": _value(row, "candidate_side", "market_side"),
        "line": _value(row, "line", "selected_handicap_signed"),
        "water": _value(row, "water", "selected_water_hk"),
        "ev_mean": _value(row, "EV_mean", "ev_mean"),
        "ev_p10": _value(row, "EV_p10", "ev_p10"),
        "p_ev_positive": _value(row, "P_EV_gt_0", "p_ev_gt_0", "p_ev_positive"),
        "decision_at": _value(row, "decision_at"),
        "status": _value(row, "status", "analysis_status"),
        "real_money": _value(row, "real_money"),
    }


def compare_rows(old_rows: Iterable[dict[str, Any]], new_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    old = {str(r.get("match_id", "")): r for r in old_rows if r.get("match_id")}
    new = {str(r.get("match_id", "")): r for r in new_rows if r.get("match_id")}
    fields = ("action", "team", "side", "line", "water", "grade", "ev_mean", "ev_p10", "p_ev_positive", "status")
    out: list[dict[str, Any]] = []
    for match_id in sorted(set(old) | set(new)):
        a, b = old.get(match_id, {}), new.get(match_id, {})
        changed = [field for field in fields if str(a.get(field, "")) != str(b.get(field, ""))]
        if not a:
            state = "NEW"
        elif not b:
            state = "MISSING_FROM_NEW_ROSTER"
        elif not changed:
            state = "UNCHANGED"
        elif a.get("team") != b.get("team") or a.get("side") != b.get("side") or a.get("action") != b.get("action"):
            state = "DIRECTION_OR_ACTION_CHANGED"
        elif a.get("line") != b.get("line"):
            state = "LINE_CHANGED"
        elif a.get("water") != b.get("water"):
            state = "WATER_CHANGED"
        elif a.get("grade") != b.get("grade"):
            state = "GRADE_CHANGED"
        elif a.get("status") != b.get("status"):
            state = "STATUS_CHANGED"
        else:
            state = "VALUE_CHANGED"
        out.append({
            "match_id": match_id,
            "change_state": state,
            "changed_fields": ",".join(changed),
            "old_action": a.get("action", ""), "new_action": b.get("action", ""),
            "old_team": a.get("team", ""), "new_team": b.get("team", ""),
            "old_side": a.get("side", ""), "new_side": b.get("side", ""),
            "old_line": a.get("line", ""), "new_line": b.get("line", ""),
            "old_water": a.get("water", ""), "new_water": b.get("water", ""),
            "old_grade": a.get("grade", ""), "new_grade": b.get("grade", ""),
            "old_ev_mean": a.get("ev_mean", ""), "new_ev_mean": b.get("ev_mean", ""),
            "change_reason": ";".join(changed) or state,
        })
    return out


def write_comparison(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ["version", "match_id", "change_state", "changed_fields", "old_action", "new_action", "old_team", "new_team",
              "old_side", "new_side", "old_line", "new_line", "old_water", "new_water", "old_grade", "new_grade",
              "old_ev_mean", "new_ev_mean", "change_reason"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: row.get(k, "") for k in fields} for row in rows)


def write_execution_ledger(list_date: str) -> Path:
    path = EXECUTION_ROOT / f"executions_{list_date}.csv"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["execution_id", "list_date", "match_id", "version_id", "execution_type", "placed_at", "team", "side", "line", "water", "stake", "status", "note"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        csv.DictWriter(f, fieldnames=fields).writeheader()
    return path


def save_run_bundle(list_date: str, run: dict[str, Any], v3: dict[str, Any], v4: dict[str, Any], previous: dict[str, Any] | None) -> tuple[Path, Path, Path]:
    directory = VERSION_ROOT / list_date / run["run_id"]
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "run_manifest.json", run)
    write_json(directory / "v3_decisions.json", v3)
    write_json(directory / "v4_shadow.json", v4)
    old_v3 = (previous or {}).get("v3", {}).get("matches", [])
    old_v4 = (previous or {}).get("v4", {}).get("matches", [])
    v3_comparison = compare_rows([flatten_v3(r) for r in old_v3], [flatten_v3(r) for r in v3.get("matches", [])])
    v4_comparison = compare_rows([flatten_v4(r) for r in old_v4], [flatten_v4(r) for r in v4.get("matches", [])])
    for row in v3_comparison:
        row["version"] = "V3"
    for row in v4_comparison:
        row["version"] = "V4_SHADOW"
    comparison = v3_comparison + v4_comparison
    comparison_path = directory / "decision_comparison.csv"
    write_comparison(comparison_path, comparison)
    v3_path = directory / "v3_decision_comparison.csv"
    v4_path = directory / "v4_shadow_comparison.csv"
    write_comparison(v3_path, v3_comparison)
    write_comparison(v4_path, v4_comparison)
    latest = VERSION_ROOT / list_date / "latest.json"
    write_json(latest, {"run": run, "v3": v3, "v4": v4, "comparison": comparison})
    return directory, comparison_path, latest
