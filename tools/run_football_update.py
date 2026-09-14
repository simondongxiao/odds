"""Manual V3/V4 football refresh entry point.

The legacy engines remain the decision authorities for their own versions.
This file only coordinates source refresh, immutable snapshots, comparison,
settlement/review metadata, V4 diagnostics, and the existing publish paths.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(r"D:\codex")
PYTHON = ROOT / "python" / "python.exe"
if not PYTHON.exists():
    PYTHON = Path(r"D:\python\python.exe")
V3_ROOT = ROOT / "v3_legacy"
V3_OUT = V3_ROOT / "outputs" / "football_odds_trader"
OUT = ROOT / "outputs" / "football_odds_trader"
RAW_ROOT = V3_OUT / "raw" / "titan007"
CN_TZ = dt.timezone(dt.timedelta(hours=8))

sys.path.insert(0, str(ROOT))
from football_update import context_r1, feature_usage, review, two_side_audit, versioning  # noqa: E402


def now_cn() -> dt.datetime:
    return dt.datetime.now(CN_TZ)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def latest_raw(list_date: str) -> Path:
    day_dir = RAW_ROOT / list_date.replace("-", "")
    files = sorted(day_dir.glob("*_titan007_odds_snapshot.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"no Titan snapshot for {list_date}: {day_dir}")
    return files[0]


def run_command(args: list[str], env: dict[str, str], log_path: Path, timeout: int = 900) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(args, cwd=str(ROOT), env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=timeout)
        log_path.write_text(result.stdout + ("\n[stderr]\n" + result.stderr if result.stderr else ""), encoding="utf-8")
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr, "log": str(log_path)}
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + "\n[timeout]\n" + (exc.stderr or "")
        log_path.write_text(output, encoding="utf-8")
        return {"returncode": 124, "stdout": "", "stderr": "timeout", "log": str(log_path)}


def backup_before_run(list_date: str, run_id: str, raw_path: Path | None = None) -> Path:
    target = OUT / "backups" / f"manual_refresh_{list_date}_{run_id}"
    target.mkdir(parents=True, exist_ok=True)
    candidates = [
        OUT / "dashboard" / "index.html",
        OUT / "dashboard" / "data" / "current.json",
        V3_OUT / "dashboard" / "index.html",
        V3_OUT / "ledger" / "simulated_bets.csv",
        ROOT / "v4" / "outputs" / f"v4_decisions_{list_date}.json",
        ROOT / "bridge" / "v3_production" / f"{list_date}.json",
    ]
    if raw_path:
        candidates.append(raw_path)
    manifest = []
    for source in candidates:
        if not source.exists():
            continue
        destination = target / source.name
        shutil.copy2(source, destination)
        manifest.append({"source": str(source), "backup": str(destination), "sha256": versioning.sha256_file(destination)})
    write_json(target / "manifest.json", {"list_date": list_date, "run_id": run_id, "created_at": now_cn().isoformat(), "files": manifest})
    return target


def parse_kickoff(value: str) -> dt.datetime | None:
    text = str(value or "").strip()
    import re
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T]+(\d{1,2}):(\d{2})", text)
    if m:
        return dt.datetime(*map(int, m.groups()), tzinfo=CN_TZ)
    m = re.search(r"(\d{1,2})[-/](\d{1,2})[ T]+(\d{1,2}):(\d{2})", text)
    if m:
        year = now_cn().year
        return dt.datetime(year, int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), tzinfo=CN_TZ)
    return None


def preserve_started_bridge(path: Path, previous: dict[str, Any] | None, run_at: dt.datetime) -> dict[str, Any]:
    payload = read_json(path, {}) or {}
    old_map = {str(row.get("match_id")): row for row in (previous or {}).get("matches", [])}
    for row in payload.get("matches", []):
        old = old_map.get(str(row.get("match_id")))
        kickoff = parse_kickoff(str(row.get("kickoff", "")))
        if not old or not kickoff or kickoff > run_at:
            continue
        current = {key: row.get(key) for key in ("score", "settlement", "settlement_label", "pnl", "status", "match_status") if key in row}
        frozen = dict(old)
        frozen.update({key: value for key, value in current.items() if value not in (None, "")})
        frozen["started_lock"] = True
        row.clear(); row.update(frozen)
    return payload


def preserve_started_v4(path: Path, previous: dict[str, Any] | None, run_at: dt.datetime) -> dict[str, Any]:
    payload = read_json(path, {}) or {}
    old_map = {str(row.get("match_id")): row for row in (previous or {}).get("matches", [])}
    for row in payload.get("matches", []):
        old = old_map.get(str(row.get("match_id")))
        kickoff = parse_kickoff(str(row.get("kickoff", "")))
        if not old or not kickoff or kickoff > run_at:
            continue
        frozen = dict(old)
        if old.get("grade") is not None and old.get("ev_mean") is not None:
            frozen["analysis_status"] = "FROZEN_PREMATCH_DECISION"
        else:
            frozen["analysis_status"] = "NOT_PREMATCH"
        frozen["reason_codes"] = ["STARTED_DECISION_LOCKED"]
        frozen["started_lock"] = True
        row.clear(); row.update(frozen)
    payload["started_lock_policy"] = "started rows retain original pre-match prediction; only status/settlement/review may append"
    return payload


def raw_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def slate_rows(path: Path, list_date: str) -> list[dict[str, str]]:
    """Return only the immutable roster for this list date.

    A refreshed Titan snapshot can also carry prior-date rows needed for
    settlement updates. Those rows remain in the raw snapshot but cannot be
    counted as today's slate.
    """
    rows = raw_rows(path)
    roster_paths = (
        ROOT / "v3_legacy" / "outputs" / "football_odds_trader" / "ledger" / "slate_rosters" / f"titan007_roster_{list_date.replace('-', '')}.json",
        ROOT / "outputs" / "football_odds_trader" / "ledger" / "slate_rosters" / f"titan007_roster_{list_date.replace('-', '')}.json",
    )
    for roster_path in roster_paths:
        if not roster_path.exists():
            continue
        try:
            payload = json.loads(roster_path.read_text(encoding="utf-8"))
            ids = {str(match_id) for match_id in (payload.get("matches") or {}).keys()}
        except (OSError, json.JSONDecodeError):
            ids = set()
        if ids:
            return [row for row in rows if str(row.get("match_id", "")) in ids]
    return [row for row in rows if str(row.get("list_date", "")) == list_date]


def write_rows_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else ["match_id"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_timestamped_bettable_lists(list_date: str, bridge: dict[str, Any], v4: dict[str, Any], run_at: dt.datetime) -> tuple[Path, Path]:
    """Freeze the user-facing V3/V4 bettable populations for this run.

    These are exports of already-frozen decisions, not a second decision engine.
    V4 remains shadow-only; A/B/C are exported as shadow candidates for review.
    """
    stamp = run_at.strftime("%Y%m%d_%H%M%S")
    root = OUT / "ledger" / "daily_bettable"
    v3_path = root / "v3" / f"bettable_{list_date}_{stamp}.csv"
    v4_path = root / "v4" / f"bettable_{list_date}_{stamp}.csv"
    v3_rows = []
    for row in bridge.get("matches", []):
        action = str(row.get("action", "") or "")
        if action not in {"可投", "半仓可投"}:
            continue
        v3_rows.append({
            "version": "V3_PRODUCTION", "list_date": list_date, "match_id": row.get("match_id", ""),
            "competition": row.get("competition", ""), "kickoff_beijing": row.get("kickoff", ""),
            "home_team": row.get("home_team", ""), "away_team": row.get("away_team", ""),
            "action": action, "grade": "", "selected_team": row.get("selected_team", ""),
            "market_side": row.get("market_side", row.get("selected_side", "")),
            "giving_team": row.get("giving_team", ""), "receiving_team": row.get("receiving_team", ""),
            "direction": row.get("direction", ""), "handicap": row.get("handicap", row.get("line", "")),
            "water": row.get("water", ""), "probability": row.get("probability", ""),
            "ev_mean": row.get("ev_mean", ""), "decision_at": row.get("decision_at", ""),
            "rule_version": row.get("rule_version", ""), "source_snapshot": row.get("odds_snapshot_id", row.get("source", "")),
            "real_money": "true", "status": row.get("settlement", row.get("status", "")),
        })
    v4_rows = []
    for row in v4.get("matches", []):
        grade = str(row.get("grade", "") or "")
        if grade not in {"A", "B", "C"}:
            continue
        v4_rows.append({
            "version": "V4_SHADOW", "list_date": list_date, "match_id": row.get("match_id", ""),
            "competition": row.get("competition", ""), "kickoff_beijing": row.get("kickoff", ""),
            "home_team": row.get("home_team", ""), "away_team": row.get("away_team", ""),
            "action": "SHADOW_CANDIDATE", "grade": grade, "selected_team": row.get("selected_team", row.get("candidate_team", "")),
            "market_side": row.get("selected_side", row.get("candidate_side", "")),
            "giving_team": row.get("giving_team", ""), "receiving_team": row.get("receiving_team", ""),
            "direction": row.get("direction", ""), "handicap": row.get("handicap", row.get("line", "")),
            "water": row.get("selected_water_hk", row.get("water", "")), "probability": row.get("p_ev_positive", row.get("P_EV_gt_0", "")),
            "ev_mean": row.get("ev_mean", row.get("EV_mean", "")), "decision_at": row.get("decision_at", ""),
            "rule_version": row.get("model_version", row.get("model_id", "")), "source_snapshot": row.get("odds_snapshot_id", row.get("source", "")),
            "real_money": "false", "status": row.get("analysis_status", row.get("status", "")),
        })
    fields = ["version", "list_date", "match_id", "competition", "kickoff_beijing", "home_team", "away_team", "action", "grade", "selected_team", "market_side", "giving_team", "receiving_team", "direction", "handicap", "water", "probability", "ev_mean", "decision_at", "rule_version", "source_snapshot", "real_money", "status"]
    for path, rows in ((v3_path, v3_rows), (v4_path, v4_rows)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader(); writer.writerows(rows)
    return v3_path, v4_path


def num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def merged_date_json(list_date: str, raw_path: Path, bridge: dict[str, Any], v4: dict[str, Any], run_id: str, run_at: dt.datetime) -> dict[str, Any]:
    raw = slate_rows(raw_path, list_date)
    v3_map = {str(x.get("match_id", "")): x for x in bridge.get("matches", [])}
    v4_map = {str(x.get("match_id", "")): x for x in v4.get("matches", [])}
    matches = []
    for source in raw:
        match_id = str(source.get("match_id", ""))
        home, away = source.get("home_cn", ""), source.get("away_cn", "")
        if not match_id or not home or not away:
            continue
        v3 = v3_map.get(match_id, {})
        shadow = v4_map.get(match_id, {})
        ah_line = num(source.get("ah_full_current_line_or_draw") or source.get("xml_ah_line"))
        hw = num(source.get("ah_full_current_home_or_over") or source.get("xml_ah_home_water"))
        aw = num(source.get("ah_full_current_away_or_under") or source.get("xml_ah_away_water"))
        euro = "/".join(str(source.get(k, "") or "") for k in ("euro_full_current_home_or_over", "euro_full_current_line_or_draw", "euro_full_current_away_or_under"))
        state = str(source.get("state", "") or "")
        finished = state == "-1"
        score = f"{source.get('home_score','')}-{source.get('away_score','')}" if source.get("home_score", "") != "" and source.get("away_score", "") != "" else ""
        v3_action = v3.get("action", "")
        if not v3:
            v3_status, v3_reason = "V3生产源缺失", "本次未产生Legacy冻结记录"
        else:
            v3_status, v3_reason = v3_action, v3.get("reason", "")
        grade = shadow.get("grade")
        status = "已完场" if finished else "进行中" if state not in {"", "0", "-1"} else "未开赛"
        matches.append({
            "identity": {"match_id": match_id, "list_date": list_date, "kickoff": source.get("bj_time", ""), "competition": source.get("league_cn", ""), "home": home, "away": away},
            "market": {"line_bucket": abs(ah_line) if ah_line is not None else "", "candidate_side": shadow.get("candidate_side", ""), "candidate_team": shadow.get("selected_team", shadow.get("candidate_team", "")), "water": shadow.get("selected_water_hk", shadow.get("water", "")), "giving_team": "", "receiving_team": "", "giving_water": hw if hw is not None else "", "receiving_water": aw if aw is not None else "", "euro_current": euro},
            "v3_decision": {"match_id": match_id, "competition": source.get("league_cn", ""), "kickoff": source.get("bj_time", ""), "home_team": home, "away_team": away, "action": v3_action or v3_status, "status": v3_status, "team": v3.get("selected_team", ""), "side": v3.get("selected_side", ""), "intent": v3.get("intent", ""), "line": v3.get("line", ""), "water": v3.get("water", ""), "probability": v3.get("probability", ""), "reason": v3_reason, "decision_at": v3.get("decision_at", "")},
            "v4_shadow": {"grade": grade, "status": shadow.get("analysis_status", shadow.get("status", "MISSING_DATA")), "team": shadow.get("selected_team", shadow.get("candidate_team", "")), "side": shadow.get("selected_side", shadow.get("candidate_side", "")), "ev_mean": shadow.get("ev_mean", shadow.get("EV_mean")), "ev_p10": shadow.get("ev_p10", shadow.get("EV_p10")), "p_ev_gt_0": shadow.get("p_ev_positive", shadow.get("P_EV_gt_0")), "kappa": 20, "real_money": False},
            "settlement": {"result": score if finished else "待结算", "pnl_1u": ""},
            "audit": {"source": str(raw_path), "state": status, "data_status": "赛后状态仅更新结算" if finished else "赛前市场输入", "run_id": run_id, "quote_at": source.get("snapshot_stamp", "") or source.get("latest_snapshot_stamp", ""), "last_confirmed_at": run_at.isoformat(), "refresh_status": source.get("refresh_status", "") or "PRICE_NOT_REFRESHED" if not source.get("snapshot_stamp") else "REFRESHED"},
        })
    return {"list_date": list_date, "run_id": run_id, "generated_at": run_at.isoformat(), "matches": matches}


def summary(v3: dict[str, Any], v4: dict[str, Any], total: int) -> dict[str, Any]:
    v3_rows = v3.get("matches", [])
    v4_rows = v4.get("matches", [])
    def is_v4_computed(row: dict[str, Any]) -> bool:
        return row.get("analysis_status") in {"EVALUATED", "FROZEN_PREMATCH_DECISION"} or row.get("status") == "COMPUTED"
    actions = [str(row.get("action", "")) for row in v3_rows]
    return {
        "total": total,
        "v3_computed": len(v3_rows), "v3_bettable": actions.count("可投"), "v3_half": actions.count("半仓可投"), "v3_no_bet": actions.count("不投"), "v3_missing": max(0, total - len(v3_rows)),
        "v4_computed": sum(row.get("analysis_status") in {"EVALUATED", "FROZEN_PREMATCH_DECISION"} or row.get("status") == "COMPUTED" for row in v4_rows),
        "v4_A": sum(row.get("grade") == "A" and is_v4_computed(row) for row in v4_rows), "v4_B": sum(row.get("grade") == "B" and is_v4_computed(row) for row in v4_rows), "v4_C": sum(row.get("grade") == "C" and is_v4_computed(row) for row in v4_rows), "v4_N": sum(row.get("grade") == "N" and is_v4_computed(row) for row in v4_rows),
        "v4_neutral": sum(row.get("analysis_status") == "NEUTRAL" or row.get("status") == "NEUTRAL" for row in v4_rows), "v4_missing": sum(row.get("analysis_status") in {"MISSING_DATA", "ERROR"} or row.get("status") == "MISSING" for row in v4_rows), "v4_not_prematch": sum(row.get("analysis_status") == "NOT_PREMATCH" and row.get("grade") is None for row in v4_rows),
    }


def refresh_v4_summary(v4: dict[str, Any]) -> dict[str, Any]:
    """Reconcile the persisted V4 summary after started-row preservation."""
    rows = v4.get("matches", [])
    computed = {"EVALUATED", "FROZEN_PREMATCH_DECISION"}
    is_computed = lambda row: row.get("analysis_status") in computed or row.get("status") == "COMPUTED"
    v4["summary"] = {
        "total": len(rows),
        "computed": sum(is_computed(row) for row in rows),
        "A": sum(row.get("grade") == "A" and is_computed(row) for row in rows),
        "B": sum(row.get("grade") == "B" and is_computed(row) for row in rows),
        "C": sum(row.get("grade") == "C" and is_computed(row) for row in rows),
        "N": sum(row.get("grade") == "N" and is_computed(row) for row in rows),
        "neutral": sum(row.get("analysis_status") == "NEUTRAL" or row.get("status") == "NEUTRAL" for row in rows),
        "missing_data": sum(row.get("analysis_status") in {"MISSING_DATA", "ERROR"} or row.get("status") == "MISSING" for row in rows),
        "not_prematch": sum(row.get("analysis_status") == "NOT_PREMATCH" and row.get("grade") is None for row in rows),
        "errors": sum(row.get("analysis_status") == "ERROR" for row in rows),
    }
    return v4


def update_root_data(date_payload: dict[str, Any], metrics: dict[str, Any], run_id: str, run_at: dt.datetime) -> tuple[Path, Path]:
    data_dir = OUT / "dashboard" / "data"
    dates_dir = data_dir / "dates"
    dates_dir.mkdir(parents=True, exist_ok=True)
    date_path = dates_dir / f"{date_payload['list_date']}.json"
    write_json(date_path, date_payload)
    dates = sorted(path.stem for path in dates_dir.glob("*.json"))
    write_json(data_dir / "dates" / "index.json", dates)
    current = {
        "list_date": date_payload["list_date"], "display_list_date": date_payload["list_date"], "date_file": f"./data/dates/{date_payload['list_date']}.json", "generated_at": run_at.isoformat(), "run_id": run_id,
        "today_update_status": "COMPLETE_DATA_REFRESH" if metrics["v3_computed"] else "V3_PRODUCTION_FEED_MISSING", "total_matches": metrics["total"], "prematch_matches": sum(x["audit"]["state"] == "未开赛" for x in date_payload["matches"]),
        "v3": {"computed_count": metrics["v3_computed"], "bettable_count": metrics["v3_bettable"], "half_count": metrics["v3_half"], "no_bet_count": metrics["v3_no_bet"], "missing_count": metrics["v3_missing"], "status": "V3_PRODUCTION_UPDATED" if metrics["v3_computed"] else "V3_PRODUCTION_FEED_MISSING"},
        "v4": {"computed_count": metrics["v4_computed"], "A_count": metrics["v4_A"], "B_count": metrics["v4_B"], "C_count": metrics["v4_C"], "N_count": metrics["v4_N"], "neutral_count": metrics["v4_neutral"], "missing_count": metrics["v4_missing"], "not_prematch_count": metrics.get("v4_not_prematch", 0), "real_money": False, "status": "V4_SHADOW_UPDATED"},
    }
    current_path = data_dir / "current.json"
    write_json(current_path, current)
    return current_path, date_path


def update_v4_data(v4_path: Path, list_date: str) -> Path:
    data_dir = ROOT / "v4" / "dashboard" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    date_path = data_dir / f"{list_date}.json"
    shutil.copy2(v4_path, date_path)
    dates = sorted(path.stem for path in data_dir.glob("*.json") if path.stem != "index")
    write_json(data_dir / "index.json", dates)
    return date_path


def write_refresh_report(list_date: str, run_id: str, run_at: dt.datetime, raw_path: Path, metrics: dict[str, Any], comparison: Path, review_md: Path, two_side_csv: Path, context_path: Path, fetch_result: dict[str, Any]) -> Path:
    directory = OUT / "daily"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"manual_refresh_{list_date}_{run_id}.md"
    lines = [f"# {list_date} 手动刷新 {run_id}", "", f"- run_at: {run_at.isoformat()}", f"- raw_snapshot: `{raw_path}`", f"- raw_snapshot_id: `{raw_path.stem}`", f"- source refresh returncode: `{fetch_result.get('returncode')}`", "", "## 漏斗", f"- roster/raw: {metrics['total']}", f"- V3 computed: {metrics['v3_computed']}；可投 {metrics['v3_bettable']}；半仓 {metrics['v3_half']}；不投 {metrics['v3_no_bet']}；missing {metrics['v3_missing']}", f"- V4 posterior computed: {metrics['v4_computed']}；A {metrics['v4_A']}；B {metrics['v4_B']}；C {metrics['v4_C']}；N {metrics['v4_N']}；Neutral {metrics['v4_neutral']}；Missing {metrics['v4_missing']}", "", "## 版本与复盘", f"- 同 list_date 上一版本逐场比较：`{comparison}`", f"- 复盘入口：`{review_md}`；未结束比赛不读取未来赛果。", f"- V4 双边诊断：`{two_side_csv}`；仅诊断，real_money=false。", f"- V4_CONTEXT_R1：`{context_path}`；不晋升、不改当前V4。", "", "## 不变式", "- V3 remains Production; V4 remains Shadow Only.", "- Started/frozen decisions are immutable; repeat refresh does not create executions.", "- Missing / Neutral / N are distinct; a runner failure is not a real zero decision."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def copy_publish_assets(list_date: str, date_path: Path, run_dir: Path) -> None:
    public = OUT / "github_publish" / "odds"
    public.mkdir(parents=True, exist_ok=True)
    copies = [
        (V3_OUT / "dashboard" / "index.html", public / "v3-legacy" / "index.html"),
        (ROOT / "v4" / "dashboard" / "index.html", public / "v4" / "index.html"),
        (ROOT / "v4" / "dashboard" / "data" / "index.json", public / "v4" / "data" / "index.json"),
        (date_path, public / "data" / "dates" / date_path.name),
        (OUT / "dashboard" / "data" / "current.json", public / "data" / "current.json"),
        (OUT / "dashboard" / "data" / "dates" / "index.json", public / "data" / "dates" / "index.json"),
        (ROOT / "v4" / "dashboard" / "data" / f"{list_date}.json", public / "v4" / "data" / f"{list_date}.json"),
        (run_dir / "run_manifest.json", public / "decision_versions" / list_date / run_dir.name / "run_manifest.json"),
        (run_dir / "decision_comparison.csv", public / "decision_versions" / list_date / run_dir.name / "decision_comparison.csv"),
    ]
    for source, destination in copies:
        if source.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    # Publish the current V4 raw output under its own namespace without
    # changing the legacy V3 page or its compatibility payload.
    v4_out = ROOT / "v4" / "outputs" / f"v4_decisions_{list_date}.json"
    if v4_out.exists():
        shutil.copy2(v4_out, public / "v4" / "data" / f"{list_date}.json")
    for source in (two_side_audit_path for two_side_audit_path in (OUT / "v4_shadow").glob(f"*_{run_dir.name}.*")):
        destination = public / "v4" / "shadow" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)
    for source in (OUT / "reviews").glob(f"*_{run_dir.name}.*"):
        destination = public / "reviews" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)
    for source in (OUT / "ledger" / "daily_bettable" / "v3").glob(f"bettable_{list_date}_*.csv"):
        destination = public / "ledger" / "daily_bettable" / "v3" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)
    for source in (OUT / "ledger" / "daily_bettable" / "v4").glob(f"bettable_{list_date}_*.csv"):
        destination = public / "ledger" / "daily_bettable" / "v4" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)
    for source, destination in (
        (ROOT / "skills" / "worldcup-odds-trader" / "SKILL.md", public / "skills" / "worldcup-odds-trader" / "SKILL.md"),
        (ROOT / "football_update", public / "tools" / "football_update"),
        (ROOT / "run_football_update.py", public / "tools" / "run_football_update.py"),
    ):
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        elif source.exists():
            destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)


def publish() -> dict[str, Any]:
    path = ROOT / "v3_legacy" / "tools" / "publish_football_dashboard_to_github.py"
    sys.path.insert(0, str(path.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("football_publisher", path)
    if not spec or not spec.loader:
        return {"pushed": False, "error": "publisher import failed"}
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.publish(push=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh V3 Legacy Production and V4 independent Shadow for one Titan list date.")
    parser.add_argument("--list-date", default="")
    parser.add_argument("--current", action="store_true")
    parser.add_argument("--no-publish", action="store_true")
    parser.add_argument("--no-refresh", action="store_true", help="Use the latest local raw snapshot; report its timestamp.")
    args = parser.parse_args()
    list_date = args.list_date or now_cn().date().isoformat()
    run_at = now_cn()
    run_id = "RUN_" + run_at.strftime("%Y%m%d_%H%M%S")
    run_dir = OUT / "decision_versions" / list_date / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    previous_latest = read_json(OUT / "decision_versions" / list_date / "latest.json", {}) or {}
    old_bridge_path = ROOT / "bridge" / "v3_production" / f"{list_date}.json"
    old_v3 = read_json(old_bridge_path, {})
    old_v4_path = ROOT / "v4" / "outputs" / f"v4_decisions_{list_date}.json"
    old_v4 = read_json(old_v4_path, {})
    try:
        old_raw = latest_raw(list_date)
    except FileNotFoundError:
        old_raw = None
    backup = backup_before_run(list_date, run_id, old_raw)
    logs = run_dir / "logs"
    env = os.environ.copy(); env["FOOTBALL_LIST_DATE"] = list_date

    fetch_result = {"returncode": 0, "skipped": True}
    if not args.no_refresh:
        fetch_result = run_command([str(PYTHON), str(V3_ROOT / "tools" / "fetch_titan007_odds.py")], env, logs / "titan_fetch.log", 1200)
    raw_path = latest_raw(list_date)
    current_rows = slate_rows(raw_path, list_date)
    scoped_raw_path = write_rows_csv(run_dir / "slate_raw.csv", current_rows)
    v3_result = run_command([str(PYTHON), str(V3_ROOT / "tools" / "build_football_daily_update.py"), "--no-publish"], env, logs / "v3_daily.log", 1200)
    v3_html = V3_OUT / "dashboard" / "index.html"
    freeze_result = run_command([str(PYTHON), str(V3_ROOT / "tools" / "run_v3_legacy_daily_freeze.py"), list_date, "--html", str(v3_html)], env, logs / "v3_freeze.log", 600)
    bridge_path = ROOT / "bridge" / "v3_production" / f"{list_date}.json"
    bridge = preserve_started_bridge(bridge_path, old_v3, run_at)
    bridge["run_id"] = run_id; bridge["raw_snapshot_id"] = raw_path.stem; bridge["odds_cutoff"] = raw_path.stem.split("_titan007", 1)[0]; bridge["decision_version_path"] = str(run_dir / "v3_decisions.json")
    write_json(bridge_path, bridge)
    v4_result = run_command([str(PYTHON), str(ROOT / "v4" / "run_daily_v4.py"), "--list-date", list_date, "--raw-csv", str(scoped_raw_path)], env, logs / "v4_shadow.log", 1200)
    v4_path = ROOT / "v4" / "outputs" / f"v4_decisions_{list_date}.json"
    v4 = preserve_started_v4(v4_path, old_v4, run_at)
    v4 = refresh_v4_summary(v4)
    v4["run_id"] = run_id; v4["raw_snapshot_id"] = raw_path.stem; v4["real_money"] = False; write_json(v4_path, v4)
    v3_bettable_export, v4_bettable_export = write_timestamped_bettable_lists(list_date, bridge, v4, run_at)
    metrics = summary(bridge, v4, len(current_rows))
    v4_data_path = update_v4_data(v4_path, list_date)
    merged = merged_date_json(list_date, raw_path, bridge, v4, run_id, run_at)
    current_path, date_path = update_root_data(merged, metrics, run_id, run_at)
    (OUT / "executions").mkdir(parents=True, exist_ok=True); execution_path = versioning.write_execution_ledger(list_date)
    two_side_csv, two_side_json, _ = two_side_audit.write_two_side_audit(v4_path, ROOT / "v4" / "ledger" / "prior" / list_date / f"prior-{list_date}-v1.json", OUT / "v4_shadow", run_id)
    feature_csv, feature_json = feature_usage.write_feature_audit(scoped_raw_path, v4_path, OUT / "v4_shadow", list_date, run_id)
    context_path = context_r1.write_context_manifest(scoped_raw_path, list_date, OUT / "v4_shadow" / f"v4_context_r1_{list_date}_{run_id}.json", "v4.2-independent-market-shadow")
    review_csv, review_md = review.write_review(list_date, scoped_raw_path, bridge_path, v4_path, OUT / "reviews", run_id)
    run_manifest = {"run_id": run_id, "list_date": list_date, "run_at": run_at.isoformat(), "raw_snapshot_id": raw_path.stem, "raw_snapshot": str(raw_path), "scoped_roster_snapshot": str(scoped_raw_path), "model_version": v4.get("model_version", v4.get("model_id", "v4.2-independent-market-shadow")), "prior_id": v4.get("prior_snapshot_id", f"prior-{list_date}-v1"), "roster_total": len(current_rows), "prematch_total": sum(str(row.get("state", "")) == "0" for row in current_rows), "refreshed_total": sum(bool(row.get("snapshot_stamp") or row.get("latest_snapshot_stamp")) for row in current_rows), "computed_total": metrics["v3_computed"], "missing_total": metrics["v3_missing"], "v3": metrics, "v4": metrics, "backup": str(backup), "fetch": fetch_result, "steps": {"v3_daily": v3_result, "v3_freeze": freeze_result, "v4_shadow": v4_result}, "artifacts": {"current_json": str(current_path), "date_json": str(date_path), "bridge": str(bridge_path), "v4": str(v4_path), "v3_bettable_timestamped": str(v3_bettable_export), "v4_bettable_timestamped": str(v4_bettable_export), "execution_ledger": str(execution_path), "two_side_csv": str(two_side_csv), "two_side_json": str(two_side_json), "context_r1": str(context_path), "review_csv": str(review_csv), "review_md": str(review_md)}}
    run_manifest["artifacts"].update({"v4_dashboard_data": str(v4_data_path), "feature_usage_csv": str(feature_csv), "feature_usage_json": str(feature_json)})
    report_path = write_refresh_report(list_date, run_id, run_at, raw_path, metrics, run_dir / "decision_comparison.csv", review_md, two_side_csv, context_path, fetch_result)
    run_manifest["artifacts"]["manual_refresh_report"] = str(report_path)
    write_json(run_dir / "run_manifest.json", run_manifest)
    directory, comparison_path, latest_path = versioning.save_run_bundle(list_date, run_manifest, bridge, v4, previous_latest)
    write_json(run_dir / "merged_dashboard_date.json", merged)
    publish_result = {"pushed": False, "skipped": True}
    if not args.no_publish:
        copy_publish_assets(list_date, date_path, run_dir)
        publish_result = publish()
    commit = ""
    repo = OUT / "github_publish" / "odds"
    if (repo / ".git").exists():
        git = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], text=True, capture_output=True, encoding="utf-8", errors="replace")
        commit = git.stdout.strip()
    run_manifest["publish"] = publish_result; run_manifest["git_commit_short"] = commit; run_manifest["status"] = "COMPLETE" if v3_result.get("returncode") == 0 and v4_result.get("returncode") == 0 else "PARTIAL"
    write_json(run_dir / "run_manifest.json", run_manifest); write_json(latest_path, {"run": run_manifest, "v3": bridge, "v4": v4, "comparison_csv": str(comparison_path)})
    print(json.dumps({"run_id": run_id, "list_date": list_date, "raw": len(current_rows), "v3_computed": metrics["v3_computed"], "v3_bettable": metrics["v3_bettable"], "v3_half": metrics["v3_half"], "v3_no_bet": metrics["v3_no_bet"], "v4_computed": metrics["v4_computed"], "v4_A": metrics["v4_A"], "v4_B": metrics["v4_B"], "v4_C": metrics["v4_C"], "v4_N": metrics["v4_N"], "v4_neutral": metrics["v4_neutral"], "v4_missing": metrics["v4_missing"], "v4_not_prematch": metrics.get("v4_not_prematch", 0), "git_commit_short": commit, "publish": publish_result, "run_dir": str(directory), "comparison": str(comparison_path), "dashboard": str(current_path)}, ensure_ascii=False))
    return 0 if run_manifest["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
