from __future__ import annotations

"""Read-only history readiness waterfall.

This module explains why a team history did or did not reach the existing
pricing input.  It intentionally calls the existing eligibility contract and
never changes its minimums, filters, aliases, or model output.
"""

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .common import atomic, iso
from .model import (COLD_START, POLICY, _bootstrap_history, _bootstrap_match,
                    _effective_sample_size, _history_weight_profile,
                    competition_match, eligible_history, paper_history_minimum)


FAILURE_CODES = {
    "HISTORY_SOURCE_FAILED", "TEAM_ALIAS_HISTORY_MISMATCH",
    "LEAGUE_ALIAS_HISTORY_MISMATCH", "NO_PRE_CUTOFF_HISTORY",
    "TOO_FEW_PRE_CUTOFF_GAMES", "HISTORY_FILTER_TOO_STRICT",
    "SEASON_TRANSITION_FILTER", "COMPETITION_ID_MISMATCH",
    "DATE_TIMEZONE_FILTER_ERROR", "DUPLICATE_REMOVAL_OVERFILTER",
    "INVALID_SCORE_FILTER", "SOURCE_HISTORY_GENUINELY_ABSENT",
    "INSUFFICIENT_OPPONENT_DIVERSITY", "TEAM_HISTORY_FEED_NOT_CAPTURED",
}


def _num(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _has_score(g):
    return _num(g.get("score1_full")) is not None and _num(g.get("score2_full")) is not None


def _source_id(team_id):
    return str(team_id or "").split(":")[-1]


def _region(event):
    text = " ".join(str(event.get(k) or "") for k in ("region", "league", "league_family")).lower()
    if any(x in text for x in ("中国", "cba", "cuba", "wcba", "亚洲", "china")):
        return "中国/亚洲"
    if any(x in text for x in ("日本", "韩国", "kbl", "b.league", "b league", "japan", "korea")):
        return "日韩"
    if any(x in text for x in ("欧洲", "euro", "fiba", "西班牙", "法国", "德国", "意大利")):
        return "欧洲/FIBA"
    if any(x in text for x in ("nba", "wnba", "美国", "加拿大", "墨西哥", "拉美", "美洲")):
        return "美洲"
    return str(event.get("region") or "未分类")


def _audit_team(event, team_id, team_name, history, page_audit, cutoff, mode):
    family = event.get("model_family") or "CLUB_MATURE"
    research_minimum = int(POLICY.get(family, POLICY["CLUB_MATURE"]).get("min_games", 3))
    paper_minimum = paper_history_minimum(event)
    paper_opponents_minimum = 3
    sid = _source_id(team_id)
    pages = [x for x in (page_audit or []) if str(x.get("team_source_id")) == sid]
    attempted = bool(pages)
    success = any(bool(x.get("http_success")) for x in pages)
    team_games = [g for g in history if team_id in (g.get("team1_id"), g.get("team2_id"))]
    if not team_games and sid:
        team_games = [g for g in history if sid in (_source_id(g.get("team1_id")), _source_id(g.get("team2_id")))]
    # The existing capture has already applied source-level name decoding.  An
    # ID match is the strongest alias match; name-only matching is never used
    # to invent a match here.
    alias_games = [g for g in team_games if team_id in (g.get("team1_id"), g.get("team2_id"))]
    league_games = [g for g in alias_games if competition_match(event, g)]
    competition_relations = Counter()
    resolved_games = []
    for g in alias_games:
        relation = "CANONICAL_SOURCE_LABEL" if competition_match(event, g) else _bootstrap_match(event, g)
        if relation:
            resolved_games.append(g)
            competition_relations[relation] += 1
    before = []
    after = []
    timezone_errors = 0
    for g in resolved_games:
        try:
            if iso(g.get("tip_at")) < iso(cutoff):
                before.append(g)
            else:
                after.append(g)
        except (TypeError, ValueError):
            timezone_errors += 1
    valid = [g for g in before if g.get("gender") == event.get("gender") and g.get("status") == "FINAL" and _has_score(g)]
    valid_ids = {}
    duplicate_count = 0
    for g in valid:
        eid = g.get("event_id")
        if eid in valid_ids:
            duplicate_count += 1
        else:
            valid_ids[eid] = g
    usable, rejection = eligible_history(event, history, cutoff, mode)
    targets = (event.get("team1_id"), event.get("team2_id"))
    native_counts = {t: sum(t in (g.get("team1_id"), g.get("team2_id")) for g in usable) for t in targets}
    relations = {g.get("event_id"): "NATIVE" for g in usable}
    bootstrap_used = False
    if min(native_counts.values(), default=0) < research_minimum:
        usable, relations = _bootstrap_history(event, history, cutoff, mode, usable, rejection)
        bootstrap_used = any(relations.get(g.get("event_id")) not in (None, "NATIVE") for g in usable)
    weight_profile = _history_weight_profile(
        usable, targets, cutoff, POLICY.get(family, POLICY["CLUB_MATURE"]), relations, bootstrap_used)
    effective_sample_size = weight_profile["effective_sample_size"]
    effective_sample_size_by_team = weight_profile["effective_sample_size_by_team"]
    research_ess_min = float((COLD_START.get("thresholds") or {}).get("research_ess_min", 3.0))
    usable_team = [g for g in usable if team_id in (g.get("team1_id"), g.get("team2_id"))]
    usable_count = len(usable_team)
    opponents = {
        g.get("team2_id") if g.get("team1_id") == team_id else g.get("team1_id")
        for g in usable_team
    }
    has_team_history = any(g.get("evidence_kind") == "TEAM_HISTORY" for g in usable_team)
    # A page may not be fetched for this exact fixture because another event
    # in the same run already supplied the team's immutable history rows.  In
    # that case the source is reused, not failed.
    if (not attempted or not success) and not team_games:
        failure = "HISTORY_SOURCE_FAILED"
    elif not team_games:
        failure = "SOURCE_HISTORY_GENUINELY_ABSENT"
    elif not alias_games:
        failure = "TEAM_ALIAS_HISTORY_MISMATCH"
    elif not resolved_games:
        failure = "COMPETITION_ID_MISMATCH" if any(g.get("competition_id") for g in alias_games) else "LEAGUE_ALIAS_HISTORY_MISMATCH"
    elif timezone_errors and not before:
        failure = "DATE_TIMEZONE_FILTER_ERROR"
    elif not before:
        failure = "NO_PRE_CUTOFF_HISTORY"
    elif not valid:
        failure = "INVALID_SCORE_FILTER"
    elif usable_count < research_minimum and duplicate_count and len(valid) - duplicate_count < research_minimum:
        failure = "DUPLICATE_REMOVAL_OVERFILTER"
    elif usable_count < research_minimum and any(k in rejection for k in ("HISTORY_TOO_OLD", "RECONSTRUCTION_24H_AVAILABILITY_BUFFER")):
        failure = "HISTORY_FILTER_TOO_STRICT"
    elif usable_count < paper_minimum:
        failure = "TOO_FEW_PRE_CUTOFF_GAMES"
    elif len(opponents) < paper_opponents_minimum:
        failure = "INSUFFICIENT_OPPONENT_DIVERSITY"
    elif not has_team_history:
        failure = "TEAM_HISTORY_FEED_NOT_CAPTURED"
    else:
        failure = None
    return {
        "canonical_team_id": team_id, "raw_team_name": team_name,
        "league": event.get("league"), "region": _region(event), "source": "7M_TEAM_HISTORY",
        "history_fetch_attempted": attempted, "history_fetch_success": success,
        "raw_games_found": len(team_games), "games_after_team_alias_match": len(alias_games),
        "games_after_league_filter": len(league_games), "games_before_cutoff": len(before),
        "games_after_competition_resolution": len(resolved_games),
        "cross_competition_bootstrap_games": competition_relations.get("CROSS_COMPETITION_ADJUSTED", 0),
        "competition_relation_counts": dict(competition_relations),
        "games_after_cutoff": len(after), "games_after_date_filter": len(before),
        "games_after_validity_filter": len(valid), "games_after_duplicate_filter": max(0, len(valid) - duplicate_count),
        "usable_history_games": usable_count,
        "research_minimum_required_games": research_minimum,
        "minimum_required_games": paper_minimum,
        "minimum_distinct_opponents": paper_opponents_minimum,
        "distinct_opponents": len(opponents),
        "team_history_evidence_present": has_team_history,
        "bootstrap_history_used": bootstrap_used,
        "effective_sample_size": effective_sample_size,
        "effective_sample_size_by_team": effective_sample_size_by_team,
        "history_ess": weight_profile["history_ess"],
        "history_ess_by_team": weight_profile["history_ess_by_team"],
        "effective_opponent_diversity": weight_profile["effective_opponent_diversity"],
        "effective_opponent_diversity_by_team": weight_profile["effective_opponent_diversity_by_team"],
        "history_waterfall": {
            "raw": len(team_games), "alias": len(alias_games), "competition": len(resolved_games),
            "cutoff": len(before), "valid": len(valid), "usable": usable_count,
        },
        "research_history_ready": bool(usable_count >= research_minimum and (not bootstrap_used or effective_sample_size >= research_ess_min)),
        "history_ready": bool(usable_count >= research_minimum and (not bootstrap_used or effective_sample_size >= research_ess_min)),
        "paper_history_ready": bool(usable_count >= paper_minimum and len(opponents) >= paper_opponents_minimum and has_team_history),
        "primary_history_failure": failure,
        "rejection_counts": dict(rejection), "duplicate_rows_removed": duplicate_count,
        "timezone_parse_errors": timezone_errors,
        "source_urls": list(dict.fromkeys(
            [x.get("url") for x in pages if x.get("url")] +
            [g.get("source_url") for g in team_games if g.get("source_url")]
        )),
        "source_reuse_status": "REUSED_IN_RUN" if team_games and not attempted else "DIRECT_FETCH" if success else "UNAVAILABLE",
    }


def build_history_readiness_diagnostic(rows, capture, root, cutoff, mode="FORWARD_NATIVE"):
    root = Path(root)
    history = (capture or {}).get("history") or []
    pages = (capture or {}).get("history_page_audit") or []
    per_event = []
    teams = []
    for row in rows:
        event = row.get("event") or {}
        event_teams = []
        for key, name_key in (("team1_id", "team1_name"), ("team2_id", "team2_name")):
            audit = _audit_team(event, event.get(key), event.get(name_key), history, pages, cutoff, mode)
            event_teams.append(audit)
            teams.append(audit)
        per_event.append({"event_id": row.get("id") or event.get("event_id"),
                          "canonical_event_id": event.get("canonical_event_id") or event.get("event_id"),
                          "team1": event_teams[0], "team2": event_teams[1]})
    failures = Counter(x["primary_history_failure"] or "READY" for x in teams)
    regions = defaultdict(lambda: {"teams": 0, "ready": 0, "alias_matched": 0, "source_failed": 0})
    for x in teams:
        r = regions[x["region"]]; r["teams"] += 1; r["ready"] += int(x["history_ready"])
        r["alias_matched"] += int(x["games_after_team_alias_match"] > 0); r["source_failed"] += int(not x["history_fetch_success"])
    league_removed = sum(max(0, x["games_after_team_alias_match"] - x["games_after_competition_resolution"]) for x in teams)
    date_rejected = sum(x["games_after_competition_resolution"] - x["games_before_cutoff"] for x in teams)
    duplicate_removed = sum(x["duplicate_rows_removed"] for x in teams)
    source_failed = sum(not x["history_fetch_success"] for x in teams)
    attempted = sum(bool(x["history_fetch_attempted"]) for x in teams)
    success = sum(bool(x["history_fetch_success"]) for x in teams)
    fallback = {"fallback_attempts": 0, "fallback_successes": 0, "fallback_failures": 0,
                "early_return_count": 0, "fallback_invocation_trace": "NOT_INSTRUMENTED",
                "HISTORY_FALLBACK_EARLY_RETURN_BUG": "NOT_PROVEN"}
    summary = {
        "schema_version": "history-readiness-diagnostic-1.0", "generated_at": cutoff,
        "cutoff": cutoff, "mode": mode, "teams": teams, "events": per_event,
        "team_count": len(teams), "history_fetch_attempted": attempted,
        "history_fetch_success": success, "raw_games_parsed": (capture or {}).get("team_history_games_parsed", len(history)),
        "failure_counts": dict(failures), "by_region": dict(regions),
        "waterfall": {"raw_history": sum(x["raw_games_found"] for x in teams),
                      "team_alias_matched": sum(x["games_after_team_alias_match"] for x in teams),
                      "league_matched": sum(x["games_after_competition_resolution"] for x in teams),
                      "league_matched_exact": sum(x["games_after_league_filter"] for x in teams),
                      "competition_resolved": sum(x["games_after_competition_resolution"] for x in teams),
                      "cross_competition_bootstrap": sum(x["cross_competition_bootstrap_games"] for x in teams),
                      "pre_cutoff": sum(x["games_before_cutoff"] for x in teams),
                      "valid": sum(x["games_after_validity_filter"] for x in teams),
                      "deduplicated": sum(x["games_after_duplicate_filter"] for x in teams),
                      "usable": sum(x["usable_history_games"] for x in teams)},
        "raw_history_exists_but_removed_by_league_filter": league_removed,
        "date_filter_rejected": date_rejected, "duplicate_removal_overfilter": duplicate_removed,
        "source_failed_teams": source_failed, "fallback_audit": fallback,
        "categories": {"FIXABLE_DATA_ENGINEERING": failures.get("TEAM_ALIAS_HISTORY_MISMATCH", 0) + failures.get("LEAGUE_ALIAS_HISTORY_MISMATCH", 0) + failures.get("DATE_TIMEZONE_FILTER_ERROR", 0) + failures.get("DUPLICATE_REMOVAL_OVERFILTER", 0),
                        "SOURCE_DEGRADATION": source_failed,
                        "GENUINE_DATA_ABSENCE": failures.get("SOURCE_HISTORY_GENUINELY_ABSENT", 0) + failures.get("NO_PRE_CUTOFF_HISTORY", 0),
                        "MODEL_REQUIREMENT": failures.get("TOO_FEW_PRE_CUTOFF_GAMES", 0) + failures.get("INSUFFICIENT_OPPONENT_DIVERSITY", 0) + failures.get("TEAM_HISTORY_FEED_NOT_CAPTURED", 0) + failures.get("HISTORY_FILTER_TOO_STRICT", 0) + failures.get("INVALID_SCORE_FILTER", 0)},
    }
    out = root / "diagnostics"; out.mkdir(parents=True, exist_ok=True)
    atomic(out / f"history_readiness_{str(cutoff)[:10].replace('-', '')}.json", summary)
    return summary
