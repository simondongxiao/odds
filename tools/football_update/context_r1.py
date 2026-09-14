from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


FEATURES = (
    "devig_euro", "asian_line_move", "asian_water_move", "euro_probability_move",
    "totals", "time_to_kickoff", "quote_age", "competition", "side_identity",
)


def _present(row: dict[str, Any], feature: str) -> bool:
    mapping = {
        "devig_euro": ("euro_raw", "euro_current"),
        "asian_line_move": ("asian_raw", "opening_ah", "current_ah"),
        "asian_water_move": ("asian_raw", "opening_water", "current_water"),
        "euro_probability_move": ("euro_raw", "opening_euro", "current_euro"),
        "totals": ("totals_raw", "total"),
        "time_to_kickoff": ("kickoff",),
        "quote_age": ("quote_at", "observed_at"),
        "competition": ("competition",),
        "side_identity": ("giving_team", "receiving_team", "candidate_team"),
    }
    return any(str(row.get(key, "") or "").strip() for key in mapping[feature])


def build_context_manifest(raw_rows: list[dict[str, Any]], list_date: str, model_version: str) -> dict[str, Any]:
    coverage = {feature: sum(_present(row, feature) for row in raw_rows) for feature in FEATURES}
    return {
        "list_date": list_date,
        "model_version": model_version,
        "context_version": "V4_CONTEXT_R1",
        "promotion_status": "NOT_PROMOTED",
        "real_money": False,
        "feature_coverage": {feature: {"present": count, "total": len(raw_rows), "share": count / len(raw_rows) if raw_rows else 0.0} for feature, count in coverage.items()},
        "reason": "Independent shadow contract only; no probability or A/B/C/N is promoted without chronological OOS training and validation.",
    }


def write_context_manifest(raw_csv: Path, list_date: str, output: Path, model_version: str) -> Path:
    with raw_csv.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    payload = build_context_manifest(rows, list_date, model_version)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
