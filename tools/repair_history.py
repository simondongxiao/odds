"""Batch repair queue for historical V3/V4 Excel ledgers.

The queue reads each workbook once, reuses local Titan final snapshots, writes
score facts first, and settles only rows whose frozen team/line/water are
present.  A confirmed score without frozen bet evidence remains explicitly
``赛果已核/冻结投注未核`` and is never reverse-engineered from the result.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

import asian_settlement
import football_ledger_store as ledger


CN_TZ = dt.timezone(dt.timedelta(hours=8))
FINAL = "-1"
CANCELLED = {"-10", "-11", "-12", "-13", "-14"}
RESULT_LABEL = asian_settlement.RESULT_LABEL


def text(value: Any) -> str:
    return "" if value is None else " ".join(str(value).replace("\u3000", " ").split()).strip()


def date10(value: Any) -> str:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return text(value)[:10]


def source_date(value: Any, fallback_year: str = "") -> str:
    """Normalize Titan's ``MM-DD HH:MM`` kickoff to an ISO date."""
    raw = text(value)
    full = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", raw)
    if full:
        return f"{full.group(1)}-{int(full.group(2)):02d}-{int(full.group(3)):02d}"
    short = re.search(r"(?:^|\D)(\d{1,2})[-/](\d{1,2})(?:\D|$)", raw)
    if short and fallback_year:
        return f"{fallback_year}-{int(short.group(1)):02d}-{int(short.group(2)):02d}"
    return raw[:10]


def number(value: Any) -> float | None:
    try:
        result = float(str(value).strip())
        return result if result == result else None
    except (TypeError, ValueError):
        return None


def parse_line(value: Any) -> float | None:
    aliases = {"平手": 0.0, "平手/半球": 0.25, "半球": 0.5, "半球/一球": 0.75, "一球": 1.0, "一球/球半": 1.25, "球半": 1.5, "球半/两球": 1.75, "两球": 2.0, "两球/两球半": 2.25, "两球半": 2.5}
    raw = text(value)
    if raw in aliases:
        return aliases[raw]
    raw = raw.replace("+", "").replace("球", "")
    return number(raw)


def clean_selected_team(value: Any) -> str:
    """Return the actual team name from a display annotation.

    V3 display rows may append ``（反向=上盘）``/``（反向=下盘）`` to
    ``投注方``.  That annotation is presentation metadata and must not be
    included in the team identity used by the settlement matcher.
    """
    raw = text(value)
    if not raw:
        return ""
    return re.split(r"\s*[（(]\s*(?:反向|正向)\s*=.*?[）)]\s*$", raw, maxsplit=1)[0].strip()


def score_text(row: dict[str, Any]) -> str:
    home, away = text(row.get("home_score")), text(row.get("away_score"))
    return f"{int(float(home))}-{int(float(away))}" if re.fullmatch(r"\d+(?:\.0)?", home) and re.fullmatch(r"\d+(?:\.0)?", away) else ""


def snapshot_sort(path: Path) -> tuple[str, str]:
    match = re.search(r"(20\d{6})_(\d{6})", path.name)
    return (match.group(1), match.group(2)) if match else ("", "")


def build_score_cache(raw_root: Path, cache_path: Path | None = None) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    file_mtimes: dict[str, float] = {}
    if cache_path and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cache = dict(cached.get("matches", cached)) if isinstance(cached, dict) else {}
            file_mtimes = {
                str(key): float(value)
                for key, value in (cached.get("file_mtimes", {}) if isinstance(cached, dict) else {}).items()
            }
        except (OSError, json.JSONDecodeError):
            cache = {}
            file_mtimes = {}
    raw_files = sorted(raw_root.rglob("*_titan007_odds_snapshot.csv"))
    # Keep a per-file high-water mark.  A new daily snapshot normally contains
    # the current scores for the whole slate, so rescanning only new/changed
    # snapshots is sufficient and avoids walking the complete multi-week raw
    # archive on every run.  If an older cache predates this index, the first
    # run intentionally rebuilds it once.
    changed_files = [
        path for path in raw_files
        if str(path) not in file_mtimes or path.stat().st_mtime > file_mtimes[str(path)] + 1e-6
    ]
    if cache and not changed_files:
        return cache
    for path in changed_files:
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    mid = text(row.get("match_id"))
                    if not mid:
                        continue
                    state = text(row.get("state"))
                    score = score_text(row)
                    candidate = {
                        "match_id": mid, "home_score": text(row.get("home_score")), "away_score": text(row.get("away_score")),
                        "score": score, "state": state, "competition": text(row.get("league_cn") or row.get("league_tw")),
                        "home": text(row.get("home_cn")), "away": text(row.get("away_cn")), "kickoff": text(row.get("bj_time")),
                        "list_date": date10(row.get("list_date")) or snapshot_sort(path)[0],
                        "source": str(path), "source_type": "titan007_snapshot", "fetched_at": dt.datetime.now(CN_TZ).isoformat(),
                    }
                    current = cache.get(mid)
                    if current is None or ((state == FINAL and current.get("state") != FINAL) or (state == FINAL and snapshot_sort(path) > snapshot_sort(Path(str(current.get("source", "")))))):
                        cache[mid] = candidate
        except (OSError, UnicodeError):
            continue
        file_mtimes[str(path)] = path.stat().st_mtime
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"schema_version": "football-score-cache-v2", "generated_at": dt.datetime.now(CN_TZ).isoformat(), "matches": cache, "file_mtimes": file_mtimes}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cache


def build_identity_index(score_cache: dict[str, dict[str, Any]]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    """Index fallback score matches once instead of scanning every source row.

    Most rows use ``Match_ID``.  Older Excel rows without that field used to
    scan the complete score cache for every row, which became quadratic as the
    archive grew.  The index preserves the same exact date/competition/team
    matching rule while making the fallback lookup constant time.
    """
    index: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for source in score_cache.values():
        date = source_date(source.get("list_date") or source.get("kickoff"), str(source.get("list_date", ""))[:4])
        competition = text(source.get("competition")).casefold()
        target = normalize_match(f"{source.get('home', '')} vs {source.get('away', '')}")
        if date and competition and target:
            index[(date, competition, target)].append(source)
    return index


def headers(ws) -> dict[str, int]:
    return ledger._headers(ws)


def match_key(row: dict[str, Any]) -> str:
    return "|".join((date10(row.get("日期筛选")), text(row.get("联赛/杯赛")).casefold(), text(row.get("具体比赛")).casefold()))


def normalize_match(value: Any) -> str:
    return re.sub(r"\s+", "", text(value)).replace("（", "(").replace("）", ")").casefold()


def row_score_pending(row: dict[str, Any], now: dt.datetime) -> bool:
    kickoff = date10(row.get("日期筛选"))
    if not kickoff or kickoff >= now.date().isoformat():
        return False
    # A pre-match feed commonly writes a placeholder 0-0 together with state
    # 0/NOT_FINAL_STATE_0.  Numeric-looking 0-0 must not be treated as a
    # verified final score in that case; otherwise a later authoritative score
    # can never reach the ledger or the historical statistics.
    score = text(row.get("赛果") or row.get("score")).replace("：", "-")
    score_status = text(row.get("Score_Status"))
    settlement_status = text(row.get("结算状态") or row.get("settlement_status"))
    result_state = text(row.get("Result_State") or row.get("result_state") or row.get("state"))
    audit_status = text(row.get("Settlement_Audit_Status"))
    exclude_reason = text(row.get("Exclude_Reason"))
    lock_state = text(row.get("Row_Lock_State"))
    not_final = (
        score == "0-0"
        and (
            result_state in {"0", "NOT_FINAL_STATE_0", "NOT_FINAL", "PENDING"}
            or score_status in {"", "SCORE_MISSING", "SCORE_PENDING"}
            or settlement_status in {"", "未开赛", "进行中", "结算待核", "赛果未匹配待人工核验", "赛果已核/冻结投注未核", "RESULT_PENDING_VERIFICATION"}
            or audit_status in {"SCORE_PENDING", "CANCELLED_OR_SCORE_PENDING"}
            or exclude_reason in {"SCORE_MISSING", "SETTLEMENT_UNRESOLVED"}
            or lock_state == "PREMATCH_MUTABLE"
        )
    )
    score_verified = ledger._score_verified(row) and not not_final
    return (not score_verified) or settlement_status in {"结算待核", "赛果未匹配待人工核验", "赛果已核/冻结投注未核", "RESULT_PENDING_VERIFICATION"} or (ledger._countable(row) and ledger._number(row.get("盈亏(u)")) is None)


def source_for_row(
    row: dict[str, Any],
    score_cache: dict[str, dict[str, Any]],
    identity_index: dict[tuple[str, str, str], list[dict[str, Any]]] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    mid = text(row.get("Match_ID"))
    if mid and mid in score_cache:
        return score_cache[mid], "exact_match_id"
    target = normalize_match(row.get("具体比赛"))
    competition = text(row.get("联赛/杯赛")).casefold()
    date = date10(row.get("日期筛选"))
    if identity_index is not None:
        candidates = identity_index.get((date, competition, target), [])
    else:
        candidates = [source for source in score_cache.values() if source_date(source.get("list_date") or source.get("kickoff"), date[:4]) == date and source.get("competition", "").casefold() == competition and normalize_match(f"{source.get('home','')} vs {source.get('away','')}") == target]
    if len(candidates) == 1:
        return candidates[0], "exact_identity"
    return None, ""


def frozen_fields(row: dict[str, Any], h: dict[str, int], version: str) -> tuple[str, float | None, float | None, str]:
    selected_team = clean_selected_team(row.get("投注方"))
    action = text(row.get("Final_Decision") or row.get("投注动作") or row.get("投注说明"))
    water = number(row.get("投注水位"))
    # V4's hidden frozen columns are named “选中盘口/选中水位”.  The older
    # short aliases existed in a few early ledgers; prefer the exact hidden
    # columns so the signed team-perspective line is used for settlement.
    frozen_line_key = "选中盘口" if h.get("选中盘口") else "选盘口"
    frozen_water_key = "选中水位" if h.get("选中水位") else "选水位"
    line = parse_line(row.get(frozen_line_key)) if version == "V4" and h.get(frozen_line_key) else parse_line(row.get("即时盘口"))
    if version == "V4" and h.get(frozen_water_key) and number(row.get(frozen_water_key)) is not None:
        water = number(row.get(frozen_water_key))
    if version == "V3":
        direction = text(row.get("V4等级/信号"))
        if line is not None and any(token in direction for token in ("上盘", "upper")):
            line = -abs(line)
        elif line is not None and any(token in direction for token in ("下盘", "lower")):
            line = abs(line)
    return selected_team, line, water, action


def identity_teams(match: str) -> tuple[str, str]:
    if " vs " in text(match):
        return tuple(part.strip() for part in text(match).split(" vs ", 1))  # type: ignore[return-value]
    return "", ""


def repair_workbook(path: Path, version: str, score_cache: dict[str, dict[str, Any]], now: dt.datetime, backup_dir: Path, audit_rows: list[dict[str, Any]], identity_index: dict[tuple[str, str, str], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    workbook = load_workbook(path, data_only=False)
    ws = workbook[ledger.SHEET_NAME]
    h = ledger._ensure_metadata_headers(ws, version)
    ledger._set_machine_header_visibility(ws, h)
    last = ledger._table_last_row(ws)
    pending = changed = scored = settled = unresolved = 0
    by_id = {text(ws.cell(row, h["Match_ID"]).value): row for row in range(4, last + 1) if h.get("Match_ID") and text(ws.cell(row, h["Match_ID"]).value)}
    by_match = {normalize_match(ws.cell(row, h.get("具体比赛", 6)).value): row for row in range(4, last + 1)}
    for rownum in range(4, last + 1):
        values = {header: ws.cell(rownum, col).value for header, col in h.items()}
        if not row_score_pending(values, now):
            continue
        pending += 1
        source, confidence = source_for_row(values, score_cache, identity_index)
        old_score = text(values.get("赛果"))
        old_status = text(values.get("结算状态"))
        new_score = score_text(source or {})
        if not source or not new_score or source.get("state") in CANCELLED:
            unresolved += 1
            reason = "CANCELLED" if source and source.get("state") in CANCELLED else "SCORE_MISSING"
            if h.get("Score_Status"):
                ws.cell(rownum, h["Score_Status"]).value = "SCORE_MISSING"
            if h.get("Settlement_Audit_Status"):
                ws.cell(rownum, h["Settlement_Audit_Status"]).value = "CANCELLED_OR_SCORE_PENDING" if reason == "CANCELLED" else "SCORE_PENDING"
            if h.get("Exclude_Reason"):
                ws.cell(rownum, h["Exclude_Reason"]).value = reason
            audit_rows.append({"model": version, "list_date": date10(values.get("日期筛选")), "match_id": text(values.get("Match_ID")), "competition": text(values.get("联赛/杯赛")), "match": text(values.get("具体比赛")), "kickoff": text(values.get("比赛时间")), "old_score": old_score, "new_score": "", "score_source": source.get("source", "") if source else "", "score_confidence": confidence or "unmatched", "old_status": old_status, "new_status": old_status, "bet_data_complete": False, "settlement": "PENDING", "pnl": "", "countable_history": False, "exclude_reason": reason})
            changed += 1
            continue
        ws.cell(rownum, h.get("赛果", 15)).value = new_score
        ws.cell(rownum, h.get("比分来源", h.get("来源", 20))).value = source.get("source", "")
        selected_team, line, water, action = frozen_fields(values, h, version)
        home, away = identity_teams(values.get("具体比赛"))
        bet_complete = bool(selected_team and line is not None and water is not None and (ledger._is_actionable_value(action) or ledger._as_bool(values.get("Frozen_Actionable")) is True or old_status == "已结算"))
        settlement_result = None
        pnl = None
        if bet_complete and home and away and selected_team in {home, away}:
            try:
                settlement_result = asian_settlement.settle_selected(int(source["home_score"]), int(source["away_score"]), selected_team, float(line), float(water), home_team=home, away_team=away)
                ws.cell(rownum, h.get("红黑", 17)).value = settlement_result["label"]
                ws.cell(rownum, h.get("盈亏(u)", 19)).value = settlement_result["pnl_1u"]
                ws.cell(rownum, h.get("结算状态", 16)).value = "已结算"
                settled += 1
                status = "SCORE_AND_BET_VERIFIED"
                audit_status = "SETTLEMENT_VERIFIED"
                exclude = ""
                countable = True
                pnl = settlement_result["pnl_1u"]
            except (TypeError, ValueError):
                settlement_result = None
        if settlement_result is None:
            ws.cell(rownum, h.get("结算状态", 16)).value = "赛果已核/冻结投注未核"
            ws.cell(rownum, h.get("红黑", 17)).value = ""
            ws.cell(rownum, h.get("盈亏(u)", 19)).value = None
            status = "SCORE_VERIFIED_BET_UNVERIFIED"
            audit_status = "BET_UNVERIFIED"
            exclude = "BET_DIRECTION_MISSING" if not selected_team else "LINE_OR_WATER_MISSING"
            countable = False
            unresolved += 1
        for key, value in (("Score_Status", status), ("Score_Source_Type", source.get("source_type", "titan007_snapshot")), ("Score_Fetched_At", source.get("fetched_at", now.isoformat())), ("Score_Match_Confidence", confidence), ("Settlement_Audit_Status", audit_status), ("Exclude_Reason", exclude), ("Countable_History", countable), ("Row_Lock_State", "STARTED_OR_SETTLED_LOCKED"), ("Updated_At", now.isoformat())):
            if h.get(key):
                ws.cell(rownum, h[key]).value = value
        scored += 1
        changed += 1
        audit_rows.append({"model": version, "list_date": date10(values.get("日期筛选")), "match_id": text(values.get("Match_ID")), "competition": text(values.get("联赛/杯赛")), "match": text(values.get("具体比赛")), "kickoff": text(values.get("比赛时间")), "old_score": old_score, "new_score": new_score, "score_source": source.get("source", ""), "score_confidence": confidence, "old_status": old_status, "new_status": "已结算" if countable else "赛果已核/冻结投注未核", "bet_data_complete": bet_complete, "settlement": settlement_result["result"] if settlement_result else "BET_UNVERIFIED", "pnl": pnl if pnl is not None else "", "countable_history": countable, "exclude_reason": exclude})
    changed = ledger._backfill_metadata(ws, h, last) or changed
    ledger._resize_tables(ws, last, max(h.values()))
    if changed:
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_dir / path.name)
        ledger._atomic_workbook_save(workbook, path)
    workbook.close()
    return {"version": version, "path": str(path), "queue_rows": pending, "scores_resolved": scored, "settlements_completed": settled, "unresolved": unresolved, "changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-date", required=True)
    parser.add_argument("--v3-ledger", required=True, type=Path)
    parser.add_argument("--v4-ledger", required=True, type=Path)
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cache-path", type=Path, default=None, help="Persistent score-cache path; defaults to output-dir/score_cache.json")
    parser.add_argument("--now", default="")
    args = parser.parse_args()
    now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(CN_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=CN_TZ)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = args.cache_path or (args.output_dir / "score_cache.json")
    score_cache = build_score_cache(args.raw_root, cache_path)
    identity_index = build_identity_index(score_cache)
    # V3 and V4 operate on different workbooks.  Repair them concurrently and
    # merge their audit rows only after both atomic writes have completed.
    audit_buffers: dict[str, list[dict[str, Any]]] = {"V3": [], "V4": []}
    jobs = {
        "V3": (args.v3_ledger, args.output_dir / "backups" / "v3"),
        "V4": (args.v4_ledger, args.output_dir / "backups" / "v4"),
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            version: pool.submit(
                repair_workbook, workbook, version, score_cache, now, backup_dir,
                audit_buffers[version], identity_index,
            )
            for version, (workbook, backup_dir) in jobs.items()
        }
        results = [futures[version].result() for version in ("V3", "V4")]
    audit_rows = audit_buffers["V3"] + audit_buffers["V4"]
    # Refresh the lightweight caches from the repaired workbooks in the same
    # pass so the HTML exporter never reads a stale pre-repair cache.
    def refresh_cache(version: str, workbook_path: Path) -> tuple[str, str, int]:
        workbook = load_workbook(workbook_path, data_only=True, read_only=False)
        ws = workbook[ledger.SHEET_NAME]
        records = ledger._cache_records(ws, ledger._headers(ws))
        workbook.close()
        cache_file = args.output_dir / f"ledger_{version.lower()}.json"
        cache_file.write_text(json.dumps({"schema_version": "football-ledger-cache-v1", "version": version, "source_workbook": str(workbook_path), "generated_at": now.isoformat(), "rows": records}, ensure_ascii=False, default=ledger._clean, indent=2) + "\n", encoding="utf-8")
        return version, str(cache_file), len(records)

    with ThreadPoolExecutor(max_workers=2) as pool:
        cache_results = list(pool.map(lambda item: refresh_cache(*item), (("V3", args.v3_ledger), ("V4", args.v4_ledger))))
    for version, cache_file, _count in cache_results:
        for result in results:
            if result["version"] == version:
                result["cache"] = cache_file
    fields = ["model", "list_date", "match_id", "competition", "match", "kickoff", "old_score", "new_score", "score_source", "score_confidence", "old_status", "new_status", "bet_data_complete", "settlement", "pnl", "countable_history", "exclude_reason"]
    audit_path = args.output_dir / f"score_backfill_audit_{now.date().isoformat()}.csv"
    with audit_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(audit_rows)
    integrity = {"generated_at": now.isoformat(), "list_date": args.list_date, "versions": results, "score_cache_size": len(score_cache), "audit": str(audit_path)}
    (args.output_dir / f"settlement_repair_queue_{now.date().isoformat()}.json").write_text(json.dumps(integrity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = [f"# Excel history integrity {now.date().isoformat()}", "", f"- list_date: `{args.list_date}`", f"- score cache: `{len(score_cache)}` matches", ""]
    for item in results:
        md.append(f"## {item['version']}")
        md.extend([f"- repair queue: {item['queue_rows']}", f"- score resolved: {item['scores_resolved']}", f"- settlement completed: {item['settlements_completed']}", f"- unresolved: {item['unresolved']}", ""])
    (args.output_dir / f"excel_history_integrity_{now.date().isoformat()}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(integrity, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
