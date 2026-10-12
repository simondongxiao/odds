"""Acceptance audit for the source-agnostic evidence and Titan ladder."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .common import atomic, stamp


def _blockers(row):
    pricing = row.get("pricing") or {}
    decision = row.get("execution") or {}
    values = list(pricing.get("blockers") or []) + list(pricing.get("paper_evidence_blockers") or [])
    values += list(decision.get("blockers") or [])
    values += list((pricing.get("total_diagnostic") or {}).get("hard_blockers") or [])
    return set(str(value).split(":", 1)[0] for value in values)


def build_unified_evidence_audit(root, rows, day, asof, baseline_document=None, capture_audit=None):
    baseline = {row.get("id"): _blockers(row) for row in (baseline_document or {}).get("events", [])}
    records = []
    classes = Counter(); remaining = Counter()
    fixed = Counter()
    for row in rows:
        event, pricing, decision = row.get("event") or {}, row.get("pricing") or {}, row.get("execution") or {}
        foundation = pricing.get("titan_foundation_pricing") or {}
        bundle = decision.get("pregame_evidence_bundle") or pricing.get("pregame_evidence_bundle") or {}
        quality = bundle.get("DATA_QUALITY") or {}
        titan_decisions = decision.get("titan_market_decisions") or {}
        titan_statuses = [item.get("status") for item in titan_decisions.values()]
        theoretical = any(isinstance(foundation.get(key), (int, float)) for key in
                          ("technical_fair_margin_neutral", "technical_fair_total"))
        history_ready = bool(quality.get("history_ready"))
        rule_ready = bool(quality.get("rule_ready"))
        unified_ready = theoretical and history_ready and rule_ready
        champion_priceable = pricing.get("pricing_status") != "UNPRICEABLE"
        qualified = bool(decision.get("triggered"))
        titan_provisional = "TITAN_PROVISIONAL_SHADOW" in titan_statuses
        quotes = (row.get("market") or {}).get("quotes") or []
        no_market = not quotes
        any_edge = qualified or titan_provisional or any(
            (item.get("model_state") == "EDGE") for item in (decision.get("market_decisions") or {}).values())
        research_only = (not qualified and not titan_provisional and
                         any(status in ("TITAN_RESEARCH_PRICE", "LINE_EDGE_RESEARCH") for status in titan_statuses))
        no_edge = bool(quotes) and not any_edge and any(
            item.get("comparison_ready") for item in list((decision.get("market_decisions") or {}).values()) +
            list(titan_decisions.values()))
        blockers = _blockers(row)
        old = baseline.get(row.get("id"), set())
        source_bridge_failure = bool(foundation.get("foundation_history_ready") and
                                     not champion_priceable and
                                     blockers.intersection({"INSUFFICIENT_PRE_CUTOFF_HISTORY", "INSUFFICIENT_HISTORY"}))
        if theoretical: classes["titan_theoretical_price"] += 1
        if foundation.get("foundation_history_ready"): classes["titan_history_gate_pass"] += 1
        if unified_ready: classes["unified_evidence_ready"] += 1
        if champion_priceable: classes["champion_priceable"] += 1
        if titan_provisional: classes["titan_provisional"] += 1
        if qualified: classes["qualified"] += 1
        if research_only: classes["research_only"] += 1
        if no_market: classes["no_market"] += 1
        if no_edge: classes["no_edge"] += 1
        if source_bridge_failure: classes["source_bridge_failure"] += 1
        if (old.intersection({"INSUFFICIENT_PRE_CUTOFF_HISTORY", "INSUFFICIENT_HISTORY"}) and
                not blockers.intersection({"INSUFFICIENT_PRE_CUTOFF_HISTORY", "INSUFFICIENT_HISTORY"})):
            fixed["history"] += 1
        if "TEAM_HISTORY_FEED_NOT_CAPTURED" in old and "TEAM_HISTORY_FEED_NOT_CAPTURED" not in blockers:
            fixed["team_history_feed"] += 1
        if "POSSESSIONS_EVIDENCE_MISSING" in old and "POSSESSIONS_EVIDENCE_MISSING" not in blockers:
            fixed["possessions"] += 1
        if "GAME_RULE_UNKNOWN" in old and "GAME_RULE_UNKNOWN" not in blockers:
            fixed["game_rule"] += 1
        if "ROSTER_STABILITY_MISSING" in old and "ROSTER_STABILITY_MISSING" not in blockers:
            fixed["roster_stability"] += 1
        remaining.update(blockers)
        records.append({
            "event_id": row.get("id"), "league": event.get("league"),
            "teams": [event.get("team1_name"), event.get("team2_name")],
            "titan_theoretical_price": theoretical,
            "history_ready_from_titan": bool(foundation.get("foundation_history_ready")),
            "history_ready_from_other_sources": bool(history_ready and not foundation.get("foundation_history_ready")),
            "unified_evidence_ready": unified_ready, "champion_priceable": champion_priceable,
            "titan_statuses": titan_statuses, "qualified": qualified,
            "exact_reason_if_not_champion_priceable": sorted(blockers) if not champion_priceable else [],
            "source_bridge_failure": source_bridge_failure,
            "history": bundle.get("HISTORY"), "pace": bundle.get("PACE"),
            "rule": bundle.get("RULE"), "rotation": bundle.get("ROTATION"),
            "remaining_blockers": sorted(blockers),
        })
    result = {
        "schema_version": "unified-evidence-audit-1.0", "date_bj": day,
        "generated_at": stamp(), "asof": asof, "events": len(rows),
        "counts": dict(classes), "fixed_vs_previous_dashboard": dict(fixed),
        "remaining_blockers": dict(remaining.most_common()),
        "records": records, "capture_bridge_audit": capture_audit or [],
        "thresholds_unchanged": {"minimum_games_per_team": 8, "minimum_unique_opponents_per_team": 3},
        "model_promotion_auto_allowed": False, "real_execution_allowed": False,
    }
    atomic(Path(root) / "audits" / "unified_evidence_audit.json", result)
    return result
