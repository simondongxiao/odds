"""Pre-match reassessment gate. Pure, append-only outputs; never places orders."""
from __future__ import annotations

from copy import deepcopy
from typing import Callable, Mapping

from asian_risk_v3 import aware_time, finite, probability, split_line

VERSION = "market-move-v1-20260907"
IDENTITY = ("match_id", "home_team_id", "away_team_id", "bookmaker_id", "period", "model_version")


def _snapshot(snapshot: Mapping, cutoff, *, fresh: bool) -> None:
    if any(not snapshot.get(k) for k in (*IDENTITY, "snapshot_id")):
        raise ValueError("Snapshot identity missing")
    if snapshot["home_team_id"] == snapshot["away_team_id"]:
        raise ValueError("Duplicate team IDs")
    if snapshot.get("state") != "pre" or snapshot["period"] != "90m":
        raise ValueError("Comparable pre-match 90-minute quotes required")
    quoted, available = (aware_time(snapshot[k]) for k in ("quoted_at", "available_at"))
    if not quoted <= available <= cutoff or (fresh and (cutoff - quoted).total_seconds() > 600):
        raise ValueError("Quote stale or unavailable at decision time")
    split_line(snapshot["home_handicap"])
    for k in ("home_water", "away_water"):
        if finite(snapshot[k], k) <= 0:
            raise ValueError("Both HK water prices required")


def _evidence(entry: Mapping, snapshot: Mapping, cutoff) -> None:
    if any(not entry.get(k) for k in ("evidence_id", "sources", "fact_summary")):
        raise ValueError("Evidence provenance missing")
    sources = entry["sources"]
    if not isinstance(sources, list) or not sources or any(not isinstance(s, str) or not s.strip() for s in sources):
        raise ValueError("Evidence sources invalid")
    for k in ("match_id", "period", "home_handicap", "snapshot_id"):
        if entry.get(k) != snapshot[k]:
            raise ValueError("Evidence market/snapshot mismatch")
    observed, available = (aware_time(entry[k]) for k in ("observed_at", "available_at"))
    if not observed <= available <= cutoff or (cutoff - observed).total_seconds() > 600:
        raise ValueError("Evidence stale or from future")


def assess_market_move(previous: Mapping, current: Mapping, *, decision_at: str,
                       public: Mapping | None = None, resistance: Mapping | None = None) -> dict:
    """One NEW quote is sufficient to trigger review, not to prove public causation."""
    result = {"Move_Guard_Version": VERSION, "Move_Status": "DATA_PENDING",
              "Move_Reason": "", "Public_Heat_Excess": None, "Supports_Team_ID": None,
              "Previous_Snapshot_ID": previous.get("snapshot_id"),
              "Current_Snapshot_ID": current.get("snapshot_id")}
    try:
        cutoff = aware_time(decision_at)
        _snapshot(previous, cutoff, fresh=False)
        _snapshot(current, cutoff, fresh=True)
        if any(previous[k] != current[k] for k in IDENTITY):
            raise ValueError("Provider/team/model change is not a comparable market move")
        if previous["snapshot_id"] == current["snapshot_id"] or aware_time(previous["quoted_at"]) >= aware_time(current["quoted_at"]):
            raise ValueError("A newer independent quote required")
        changed = [k for k in ("home_handicap", "home_water", "away_water") if previous[k] != current[k]]
        result["Changed_Fields"] = changed
        if not changed:
            return {**result, "Move_Status": "UNCHANGED"}
        result["Move_Status"] = "PUBLIC_EVIDENCE_PENDING"
        public = public or {}
        _evidence(public, current, cutoff)
        teams = {current["home_team_id"], current["away_team_id"]}
        if public.get("team_id") not in teams:
            raise ValueError("Public side not mapped to this match")
        kind = public.get("kind")
        if kind == "actual_money_share":
            if not public.get("theoretical_basis") or finite(public.get("window_amount", 0), "window_amount") <= 0:
                raise ValueError("Same-market theoretical baseline and measured window amount required")
            excess = probability(public["share"], "share") - probability(public["theoretical_share"], "theoretical_share")
            result["Public_Heat_Excess"] = round(excess, 4)
            if excess <= .05 + 1e-12:
                return {**result, "Move_Status": "PUBLIC_HEAT_NOT_ESTABLISHED", "Move_Reason": "Excess must be strictly greater than 5pp"}
        elif kind == "public_consensus":
            if len(set(public["sources"])) < 2:
                raise ValueError("Qualitative public consensus needs two independent sources")
        else:
            raise ValueError("Odds-implied shares and raw tickets are not measured money shares")
        result.update(Public_Evidence_Kind=kind, Public_Team_ID=public["team_id"],
                      Public_Evidence_ID=public["evidence_id"], Move_Status="RESISTANCE_PENDING")
        resistance = resistance or {}
        _evidence(resistance, current, cutoff)
        if resistance["evidence_id"] == public["evidence_id"]:
            raise ValueError("Resistance cannot reuse the same public evidence")
        if resistance.get("public_team_id") != public["team_id"]:
            raise ValueError("Resistance targets a different public side")
        assessment = resistance.get("assessment")
        if assessment == "passive_public_adjustment":
            return {**result, "Move_Status": "PASSIVE_PUBLIC_MOVE", "Move_Reason": resistance["fact_summary"]}
        if assessment != "counter_public_resistance":
            return {**result, "Move_Status": "RESISTANCE_UNCONFIRMED", "Move_Reason": resistance["fact_summary"]}
        if resistance.get("basis") not in {"cross_market_response", "verified_flow_response", "executable_depth_response"}:
            raise ValueError("Single AH water move is insufficient resistance evidence")
        if resistance.get("supports_team_id") not in teams or not resistance.get("independent_evidence_ids"):
            raise ValueError("Supported team and independent corroboration required")
        corroboration = resistance["independent_evidence_ids"]
        if not isinstance(corroboration, list) or any(not isinstance(i, str) or not i.strip() for i in corroboration):
            raise ValueError("Invalid corroboration references")
        if set(corroboration) & {public["evidence_id"], resistance["evidence_id"], current["snapshot_id"]}:
            raise ValueError("Self-referencing corroboration is not independent")
        return {**result, "Move_Status": "COUNTER_PUBLIC_CONFIRMED",
                "Supports_Team_ID": resistance["supports_team_id"],
                "Resistance_Evidence_ID": resistance["evidence_id"],
                "Move_Reason": resistance["fact_summary"]}
    except (KeyError, TypeError, ValueError) as exc:
        return {**result, "Move_Reason": str(exc)}


def run_market_reassessment(previous_decision: Mapping, previous_snapshot: Mapping,
                            current_snapshot: Mapping, *, decision_at: str,
                            kickoff_at: str, build_proposal: Callable[[Mapping], Mapping],
                            public: Mapping | None = None, resistance: Mapping | None = None) -> dict:
    """Callback runs cup/fundamentals -> Delta -> full funnel -> original sizing.

    Previous_Decision is always preserved. Rejected changes do not authorize
    execution of either the new side or an expired previous plan.
    """
    output = {"Previous_Decision": deepcopy(dict(previous_decision)),
              "Accepted_New_Decision": None, "Current_Execution_Status": "DATA_PENDING"}
    try:
        now = aware_time(decision_at)
        if now >= aware_time(kickoff_at) or current_snapshot.get("state") in {"live", "closed", "finished"}:
            return {**output, "Current_Execution_Status": "HISTORICAL_LOCK"}
        if not previous_decision.get("decision_id") or previous_decision.get("match_id") != current_snapshot.get("match_id"):
            raise ValueError("Previous decision identity missing or mismatched")
        if previous_decision.get("snapshot_id") != previous_snapshot.get("snapshot_id"):
            raise ValueError("Previous decision must use its original snapshot")
        if aware_time(previous_decision["decision_at"]) >= now:
            raise ValueError("Decision sequence must move forward")
        review = assess_market_move(previous_snapshot, current_snapshot, decision_at=decision_at,
                                    public=public, resistance=resistance)
        output["Move_Review"] = review
        if review["Move_Status"] == "DATA_PENDING":
            return output
        proposed = deepcopy(dict(build_proposal(deepcopy(review))))
        output["Current_Evaluation"] = proposed
        if not proposed.get("decision_id") or proposed["decision_id"] == previous_decision["decision_id"]:
            raise ValueError("New decision ID required")
        if (proposed.get("match_id") != previous_decision["match_id"]
                or proposed.get("list_date") != previous_decision.get("list_date")
                or proposed.get("snapshot_id") != current_snapshot["snapshot_id"]
                or aware_time(proposed["decision_at"]) != now):
            raise ValueError("New decision identity/date/clock mismatch")
        status = proposed.get("Execution_Status")
        if not status:
            raise ValueError("Full-funnel execution status missing")
        stake = finite(proposed.get("Stake", -1), "Stake")
        if stake < 0 or (status == "READY" and stake <= 0) or (status != "READY" and stake != 0):
            raise ValueError("Execution status and stake are inconsistent")
        side_changed = proposed.get("team_id") != previous_decision.get("team_id")
        for key in ("direction", "verified_intent"):
            if key in previous_decision and key not in proposed:
                raise ValueError("New decision omitted its prior conclusion field: " + key)
            if key in previous_decision and previous_decision[key] != proposed[key]:
                side_changed = True
        if status == "READY":
            if proposed.get("team_id") not in {current_snapshot["home_team_id"], current_snapshot["away_team_id"]}:
                raise ValueError("Proposed side is not a match team")
            if side_changed and (review["Move_Status"] != "COUNTER_PUBLIC_CONFIRMED"
                                 or review["Supports_Team_ID"] != proposed["team_id"]):
                return {**output, "Current_Execution_Status": "DIRECTION_CHANGE_BLOCKED"}
        proposed.update(review)
        proposed.update(previous_decision_id=previous_decision["decision_id"], Current_Execution_Status=status)
        return {**output, "Accepted_New_Decision": proposed, "Current_Execution_Status": status}
    except (KeyError, TypeError, ValueError) as exc:
        return {**output, "Current_Execution_Status": "DATA_PENDING", "Error": str(exc)}
