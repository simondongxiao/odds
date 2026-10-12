"""Read-only audit of the total-market path.

This module deliberately does not change pricing or execution.  It makes a
real total quote visible even when the total evidence gate rejects a paper
entry, so market absence is not confused with model ineligibility.
"""
from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from .common import atomic, stamp


def _quotes(row, market="TOTAL"):
    return [q for q in (row.get("market") or {}).get("quotes", [])
            if q.get("market_type") == market]


def _state_map(row):
    quotes = (row.get("market") or {}).get("quotes", [])
    states = (row.get("market") or {}).get("quote_states", [])
    return {q.get("quote_id"): (states[i] if i < len(states) else {})
            for i, q in enumerate(quotes)}


def _finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def _first(values):
    return next((x for x in values if x is not None), None)


def diagnose_total(row):
    event = row.get("event") or {}
    pricing = row.get("pricing") or {}
    execution = row.get("execution") or {}
    decision = (execution.get("market_decisions") or {}).get("TOTAL") or {}
    diagnostic = pricing.get("total_diagnostic") or {}
    learning = ((execution.get("learning_classification") or {}).get("markets") or {}).get("TOTAL") or {}
    quotes = _quotes(row)
    states = _state_map(row)

    raw_quotes = [q for q in quotes if q.get("raw_verified") or not states]
    parsed_quotes = [q for q in quotes if q.get("raw_line") is not None]
    normalized_quotes = [q for q in parsed_quotes if _finite(q.get("raw_line"))]
    canonical_quotes = [q for q in normalized_quotes
                        if q.get("event_id") == event.get("event_id")]
    fresh_quotes = [q for q in canonical_quotes
                    if states.get(q.get("quote_id"), {}).get("fresh_observation")]

    selected = decision.get("selected") or {}
    first_quote = _first(fresh_quotes or canonical_quotes or normalized_quotes or quotes)
    first_state = states.get(first_quote.get("quote_id"), {}) if first_quote else {}
    classified_hard = [x.get("reason") for x in learning.get("evidence_reasons", [])
                       if x.get("class") in ("HARD_BLOCK", "DATA_PIPELINE_FAILURE")]
    hard_blockers = list(dict.fromkeys(list(diagnostic.get("hard_blockers") or []) + classified_hard))
    soft_missing = list(dict.fromkeys(list(diagnostic.get("soft_missing") or []) +
                                     [x.get("reason") for x in learning.get("evidence_reasons", [])
                                      if x.get("class") == "SOFT_MISSING"]))
    blockers = list(dict.fromkeys(hard_blockers + soft_missing))

    if not quotes:
        primary_failure = "RAW_MARKET_MISSING"
    elif not raw_quotes:
        primary_failure = "TOTAL_RAW_NOT_VERIFIED"
    elif not parsed_quotes:
        primary_failure = "TOTAL_PARSER_LOSS"
    elif not normalized_quotes:
        primary_failure = "TOTAL_NORMALIZATION_FAILED"
    elif not canonical_quotes:
        primary_failure = "TOTAL_CANONICALIZATION_FAILED"
    elif not fresh_quotes:
        primary_failure = "TOTAL_MARKET_NOT_FRESH"
    elif pricing.get("total_raw") is None:
        primary_failure = "TOTAL_NOT_PRICEABLE"
    elif hard_blockers:
        primary_failure = "TOTAL_CONTEXT_INCOMPLETE"
    elif not decision.get("comparison_ready"):
        primary_failure = "TOTAL_COMPARISON_NOT_READY"
    elif decision.get("model_state") != "EDGE":
        primary_failure = "TOTAL_NO_EDGE"
    elif decision.get("triggered"):
        primary_failure = None
    else:
        primary_failure = "TOTAL_EXECUTION_BLOCKED"

    market_total = first_quote.get("raw_line") if first_quote else None
    prices = first_quote.get("decimal_prices") if first_quote else None
    raw_prices = first_quote.get("raw_prices") if first_quote else None
    return {
        "game_id": event.get("canonical_event_id") or event.get("event_id") or row.get("id"),
        "event_id": event.get("event_id") or row.get("id"),
        "canonical_event_id": event.get("canonical_event_id") or event.get("event_id") or row.get("id"),
        "league": event.get("league"), "league_family": event.get("league_family"),
        "team_1": event.get("team1_name"), "team_2": event.get("team2_name"),
        "tip_time_bj": event.get("tip_time_bj"), "archive_type": row.get("archive_type"),
        "raw_total_market_found": bool(raw_quotes),
        "parsed_total_market_found": bool(parsed_quotes),
        "normalized_total_market_found": bool(normalized_quotes),
        "canonical_total_market_found": bool(canonical_quotes),
        "fresh_total_market_found": bool(fresh_quotes),
        "raw_total_quote_count": len(raw_quotes),
        "parsed_total_quote_count": len(parsed_quotes),
        "normalized_total_quote_count": len(normalized_quotes),
        "fresh_total_quote_count": len(fresh_quotes),
        "market_total": market_total,
        "over_price": prices[0] if isinstance(prices, list) and prices else None,
        "under_price": prices[1] if isinstance(prices, list) and len(prices) > 1 else None,
        "raw_prices": raw_prices,
        "bookmaker": first_quote.get("bookmaker") if first_quote else None,
        "source_quote_at": first_quote.get("source_quote_at") if first_quote else None,
        "captured_at": first_quote.get("received_at") if first_quote else None,
        "quote_age_seconds": first_state.get("age_seconds"),
        "pricing_attempted": bool(row.get("pricing") is not None),
        "total_priceable": pricing.get("total_raw") is not None and not hard_blockers,
        "fair_total": pricing.get("total_raw"),
        "pace_source": diagnostic.get("pace_source", "UNAVAILABLE"),
        "possessions_level": diagnostic.get("evidence_level", "LEVEL_D"),
        "total_edge": selected.get("conditional_edge", decision.get("ev")),
        "evidence_status": "TOTAL_CONTEXT_COMPLETE" if not hard_blockers and not soft_missing else "TOTAL_SOFT_MISSING" if not hard_blockers else "TOTAL_CONTEXT_INCOMPLETE",
        "edge_found": decision.get("model_state") == "EDGE",
        "shadow_eligible": bool(decision.get("triggered") or decision.get("shadow_action") == "SHADOW_BET"),
        "provisional_shadow": learning.get("shadow_level") == "PROVISIONAL_SHADOW",
        "qualified_shadow": learning.get("shadow_level") == "QUALIFIED_SHADOW",
        "final_status": execution.get("display_action") or execution.get("shadow_action"),
        "primary_failure": primary_failure,
        "decision_blockers": blockers,
        "hard_blockers": hard_blockers,
        "soft_missing": soft_missing,
    }


def build_total_market_pipeline_diagnostic(rows, root, day, asof):
    """Persist a total-specific event audit and return its JSON summary."""
    root = Path(root)
    records = [diagnose_total(row) for row in rows]
    spread_found = sum(bool(_quotes(row, "SPREAD")) for row in rows)
    spread_fresh = sum(any(_state_map(row).get(q.get("quote_id"), {}).get("fresh_observation")
                           for q in _quotes(row, "SPREAD")) for row in rows)
    counts = {
        "events_discovered": len(rows),
        "raw_total_market_found": sum(r["raw_total_market_found"] for r in records),
        "parsed_total_market_found": sum(r["parsed_total_market_found"] for r in records),
        "normalized_total_market_found": sum(r["normalized_total_market_found"] for r in records),
        "canonical_total_market_found": sum(r["canonical_total_market_found"] for r in records),
        "fresh_total_market_found": sum(r["fresh_total_market_found"] for r in records),
        "total_pricing_attempted": sum(r["pricing_attempted"] for r in records),
        "total_priceable": sum(r["total_priceable"] for r in records),
        "total_evidence_complete": sum(r["evidence_status"] == "TOTAL_CONTEXT_COMPLETE" for r in records),
        "total_edge_found": sum(r["edge_found"] for r in records),
        "total_shadow_eligible": sum(r["shadow_eligible"] for r in records),
        "total_provisional_shadow": sum(r["provisional_shadow"] for r in records),
        "total_qualified_shadow": sum(r["qualified_shadow"] for r in records),
        "pace_direct": sum(r["pace_source"] == "DIRECT" for r in records),
        "pace_derived": sum(r["pace_source"] == "DERIVED_BOX_SCORE" for r in records),
        "level_a": sum(r["possessions_level"] == "LEVEL_A" for r in records),
        "level_b": sum(r["possessions_level"] == "LEVEL_B" for r in records),
        "level_c": sum(r["possessions_level"] == "LEVEL_C" for r in records),
        "level_d": sum(r["possessions_level"] == "LEVEL_D" for r in records),
        "spread_market_found": spread_found,
        "spread_market_fresh": spread_fresh,
    }
    failures = Counter(r["primary_failure"] or "SHADOW_ELIGIBLE" for r in records)
    summary = {
        "schema_version": "total-market-pipeline-diagnostic-1.0",
        "generated_at": stamp(), "asof": asof, "date_bj": day,
        "diagnostic_only": True, "real_execution_allowed": False,
        "counts": counts, "failure_counts": dict(failures),
        "records": records,
        "market_presence_is_independent_of_betting": True,
        "notes": [
            "真实总分报价即使未通过证据门槛也保留并显示。",
            "缺失字段使用null；0只表示真实计数为零。",
            "该诊断不修改总分公式、Evidence Gate、概率、Kelly或执行决定。",
        ],
    }
    out = root / "diagnostics"
    out.mkdir(parents=True, exist_ok=True)
    fields = list(records[0].keys()) if records else [
        "game_id", "event_id", "canonical_event_id", "league", "league_family",
        "team_1", "team_2", "tip_time_bj", "archive_type",
    ]
    csv_path = out / f"total_market_pipeline_{day.replace('-', '')}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in record.items()})
    atomic(out / f"total_market_pipeline_summary_{day.replace('-', '')}.json", summary)
    return summary
