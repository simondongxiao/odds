from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


CAUSES = (
    "DATA_OR_SETTLEMENT_ERROR", "STALE_PRICE", "WRONG_EXECUTION_PRICE",
    "KNOWN_PREMATCH_INFORMATION_MISSED", "POST_DECISION_PREMATCH_CHANGE",
    "MODEL_FEATURE_GAP", "INPLAY_RED_CARD", "INPLAY_INJURY", "PENALTY_OR_VAR_EVENT",
    "PRICE_ANOMALY", "VOLUME_ANOMALY_IF_REAL_DATA_EXISTS", "NO_DEMONSTRATED_PROCESS_ERROR", "UNKNOWN",
)


def _score(row: dict[str, Any]) -> str:
    for key in ("score", "赛果", "final_score"):
        value = str(row.get(key, "") or "").strip()
        if value and value not in {"待赛", "待结算", "0-0"}:
            return value
    home, away = row.get("home_score", ""), row.get("away_score", "")
    return f"{home}-{away}" if str(home).strip() and str(away).strip() else ""


def build_review_rows(list_date: str, raw_rows: list[dict[str, Any]], v3: dict[str, Any], v4: dict[str, Any]) -> list[dict[str, Any]]:
    raw = {str(row.get("match_id", "")): row for row in raw_rows}
    v3_map = {str(row.get("match_id", "")): row for row in v3.get("matches", [])}
    v4_map = {str(row.get("match_id", "")): row for row in v4.get("matches", [])}
    out: list[dict[str, Any]] = []
    for match_id in sorted(set(raw) | set(v3_map) | set(v4_map)):
        source = raw.get(match_id, {})
        score = _score(source) or _score(v3_map.get(match_id, {}))
        finished = str(source.get("state", "")) == "-1" and bool(score)
        status = "SETTLED_CANDIDATE" if finished else "PENDING_RESULT"
        cause = "NO_DEMONSTRATED_PROCESS_ERROR" if finished else "UNKNOWN"
        for version, decision in (("V3", v3_map.get(match_id, {})), ("V4", v4_map.get(match_id, {}))):
            out.append({
                "list_date": list_date, "match_id": match_id, "version": version,
                "competition": source.get("league_cn", decision.get("competition", "")),
                "match": f"{source.get('home_cn', '')} vs {source.get('away_cn', '')}",
                "fact_score": score, "known_at_decision": "not reconstructed from future result",
                "new_after_decision": "", "process_gap": "", "error_hypothesis": cause,
                "preventability": "unknown", "evidence_confidence": "low" if not finished else "source-state only",
                "research_hypothesis": "", "review_status": status,
                "decision_at": decision.get("decision_at", ""), "decision_hash": decision.get("decision_id", ""),
                "original_action_or_grade": decision.get("action", decision.get("grade", "")),
            })
    return out


def write_review(list_date: str, raw_csv: Path, v3_path: Path, v4_path: Path, output_dir: Path, run_id: str) -> tuple[Path, Path]:
    with raw_csv.open(encoding="utf-8-sig", newline="") as f:
        raw_rows = list(csv.DictReader(f))
    v3 = json.loads(v3_path.read_text(encoding="utf-8")) if v3_path.exists() else {"matches": []}
    v4 = json.loads(v4_path.read_text(encoding="utf-8")) if v4_path.exists() else {"matches": []}
    rows = build_review_rows(list_date, raw_rows, v3, v4)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"review_{list_date}_{run_id}.csv"
    fields = list(rows[0]) if rows else ["list_date", "match_id", "version", "review_status"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    summary = {"list_date": list_date, "run_id": run_id, "rows": len(rows), "pending": sum(row.get("review_status") == "PENDING_RESULT" for row in rows), "settled_candidates": sum(row.get("review_status") == "SETTLED_CANDIDATE" for row in rows), "causes": sorted({row.get("error_hypothesis") for row in rows})}
    md_path = output_dir / f"review_{list_date}_{run_id}.md"
    lines = [f"# {list_date} 赛后复盘入口", "", "- 本模块只追加 FACT/复盘字段，不覆盖原始 V3/V4 prediction。", f"- rows: {summary['rows']}", f"- pending_result: {summary['pending']}", f"- settled_candidate: {summary['settled_candidates']}", "- 当前未把价格移动称为资金流；没有真实成交数据时仅记录 PRICE_MOVE。", "- 未结束比赛不读取未来赛果，不生成结算结论。", "", "## 复盘字段契约", "- FACT / KNOWN_AT_DECISION / NEW_AFTER_DECISION / PROCESS_GAP / ERROR_HYPOTHESIS / PREVENTABILITY / EVIDENCE_CONFIDENCE / RESEARCH_HYPOTHESIS", "- 复盘不会自动修改 V3/V4 模型；任何新假设需另行进入 shadow 实验和固定评审。"]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, md_path
