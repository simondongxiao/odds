from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


FEATURES = (
    "line_bucket", "competition", "intent", "euro_odds", "asian_movement",
    "water", "totals", "timing", "fundamentals", "flow",
)


def _has(row: dict[str, Any], *keys: str) -> bool:
    return any(str(row.get(key, "") or "").strip() for key in keys)


def audit_rows(raw_rows: list[dict[str, Any]], v4_payload: dict[str, Any]) -> list[dict[str, Any]]:
    v4_map = {str(row.get("match_id", "")): row for row in v4_payload.get("matches", [])}
    out = []
    for raw in raw_rows:
        match_id = str(raw.get("match_id", ""))
        if not match_id:
            continue
        v4 = v4_map.get(match_id, {})
        line_present = _has(raw, "ah_full_current_line_or_draw", "xml_ah_line")
        euro_present = _has(raw, "euro_full_current_home_or_over", "xml_euro_home")
        out.append({
            "match_id": match_id, "competition": raw.get("league_cn", ""),
            "line_bucket": line_present, "competition_used": False,
            "intent_available": False, "euro_odds_used": False,
            "asian_movement_available": _has(raw, "ah_full_open_line_or_draw", "ah_full_current_line_or_draw"),
            "water_used": line_present, "totals_available": _has(raw, "total_full_current_line_or_draw"),
            "timing_available": _has(raw, "bj_time"), "fundamentals_available": False,
            "flow_available": False, "prior_level": "line_bucket" if v4.get("analysis_status") == "EVALUATED" else "not_computed",
            "fallback_reason": "current_v4_model_uses_line_bucket_prior; other fields remain audit/evidence-only" if v4.get("analysis_status") == "EVALUATED" else "not_computed",
            "model_version": v4.get("model_id", "v4-market-dirichlet-20260913"),
        })
    return out


def write_feature_audit(raw_csv: Path, v4_json: Path, output_dir: Path, list_date: str, run_id: str) -> tuple[Path, Path]:
    with raw_csv.open(encoding="utf-8-sig", newline="") as f:
        raw = list(csv.DictReader(f))
    v4 = json.loads(v4_json.read_text(encoding="utf-8"))
    rows = audit_rows(raw, v4)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"v4_feature_usage_{list_date}_{run_id}.csv"
    fields = list(rows[0]) if rows else ["match_id", "model_version"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    counts = {feature: sum(bool(row.get(feature)) for row in rows) for feature in ("line_bucket", "competition_used", "intent_available", "euro_odds_used", "asian_movement_available", "water_used", "totals_available", "timing_available", "fundamentals_available", "flow_available")}
    json_path = output_dir / f"v4_feature_usage_{list_date}_{run_id}.json"
    json_path.write_text(json.dumps({"list_date": list_date, "run_id": run_id, "rows": len(rows), "coverage": counts, "model_note": "The current V4 production shadow posterior is keyed by line bucket. This audit records captured-but-not-used features and does not inject noise or change grades."}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return csv_path, json_path
