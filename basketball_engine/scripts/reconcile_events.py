#!/usr/bin/env python3
"""Reconcile normalized source events without mutating any historical ledger."""
from __future__ import annotations
from collections import defaultdict
from typing import Any
from discover_events import STATUS

def reconcile(union: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    canonical, conflicts = [], []
    for event_id, rows in union.items():
        families = {r.get("league_family", "OTHER_DISCOVERED") for r in rows}
        teams = {(r.get("team_1_normalized"), r.get("team_2_normalized")) for r in rows}
        tips = {r.get("tip_utc") for r in rows}
        conflict = len(families) > 1 or len(teams) > 1 or len(tips) > 1
        base = dict(rows[0])
        base["canonical_event_id"] = event_id
        base["sources"] = sorted({r["source"] for r in rows})
        base["source_count"] = len(rows)
        base["reconciliation_status"] = "conflict" if conflict else "reconciled"
        base["source_records"] = rows
        canonical.append(base)
        if conflict: conflicts.append({"canonical_event_id":event_id,"sources":base["sources"],"families":sorted(families),"teams":sorted(teams),"tips":sorted(tips)})
    return canonical, conflicts

def reconcile_status(source_status: dict[str, Any], event_count: int, secondary_checked: bool) -> str:
    if event_count: return "reconciled"
    if any(v == "source_zero_result" for v in source_status.values()) and secondary_checked:
        return "source_unavailable_with_secondary_check"
    if all(isinstance(v, dict) for v in source_status.values()): return "incomplete"
    return "verified_no_games"
