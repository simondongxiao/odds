"""ESPN schedule/box-score bridge for NBA and WNBA history.

ESPN is used here only as an auditable fallback when the Titan/7M team page
is unavailable or the provider publishes a different event ID.  The bridge
keeps the same cutoff, exact canonical aliases and source snapshots as the
primary history path.  Possessions are derived only from complete FGA/FTA/
ORB/TOV fields returned in the box score; a missing field never becomes a
guessed value.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from global_discovery import _fetch_json, stamp
from repair_v22.common import canonical_team_token, competition_key, competition_phase


BJ = timezone.utc  # only used for parsing ISO values; output is ISO UTC


def _num(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _pair(value):
    match = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*$", str(value or ""))
    return (float(match.group(1)), float(match.group(2))) if match else (None, None)


def _stat_map(team):
    result = {}
    for row in team.get("statistics") or []:
        if isinstance(row, dict) and row.get("name"):
            result[str(row["name"])] = row.get("displayValue")
    fgm, fga = _pair(result.get("fieldGoalsMade-fieldGoalsAttempted"))
    three_pm, three_pa = _pair(result.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
    ftm, fta = _pair(result.get("freeThrowsMade-freeThrowsAttempted"))
    values = {
        "FGM": fgm, "FGA": fga, "3PM": three_pm, "3PA": three_pa,
        "FTM": ftm, "FTA": fta, "ORB": _num(result.get("offensiveRebounds")),
        "DRB": _num(result.get("defensiveRebounds")), "REB": _num(result.get("totalRebounds")),
        "AST": _num(result.get("assists")), "PF": _num(result.get("fouls")),
        "STL": _num(result.get("steals")), "TOV": _num(result.get("totalTurnovers") or result.get("turnovers")),
        "BLK": _num(result.get("blocks")), "PTS": _num(result.get("points")),
    }
    required = (values.get("FGA"), values.get("FTA"), values.get("ORB"), values.get("TOV"))
    if all(isinstance(x, (int, float)) and x >= 0 for x in required):
        values["possessions_estimate"] = values["FGA"] + 0.44 * values["FTA"] - values["ORB"] + values["TOV"]
    else:
        values["possessions_estimate"] = None
    return values


def _tip(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _final_score_summary(summary, event_id, source_url, raw_path, observed_at):
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    by_side = {str(x.get("homeAway")): x for x in competitors}
    home, away = by_side.get("home"), by_side.get("away")
    if not home or not away:
        return None
    tip = _tip(comp.get("date") or (summary.get("header") or {}).get("date"))
    if not tip:
        return None
    def team_info(row):
        team = row.get("team") or {}
        lines = []
        for item in row.get("linescores") or []:
            # ESPN summary uses ``displayValue`` for completed period scores;
            # a few older payloads use ``value``.  Accept both, but never
            # infer a period from the final total.
            value = _num((item.get("displayValue") or item.get("value")) if isinstance(item, dict) else item)
            if value is not None:
                lines.append(int(value) if float(value).is_integer() else value)
        score = _num(row.get("score"))
        return team, lines, score
    home_team, home_periods, home_score = team_info(home)
    away_team, away_periods, away_score = team_info(away)
    if len(home_periods) < 4 or len(away_periods) < 4 or home_score is None or away_score is None:
        return None
    # Boxscore team rows are keyed by the provider team id and are kept as
    # independent evidence on the history fact.
    boxes = {str((row.get("team") or {}).get("id")): _stat_map(row)
             for row in (summary.get("boxscore") or {}).get("teams") or []}
    home_box = boxes.get(str(home_team.get("id"))) or {}
    away_box = boxes.get(str(away_team.get("id"))) or {}
    return {
        "event_id": f"espn:{event_id}", "source_event_id": str(event_id),
        "tip_at": tip.isoformat(), "status": "FINAL",
        "competition_key": "WNBA" if "wnba" in str((summary.get("header") or {}).get("league", "")).casefold() else None,
        "league": None, "season_phase": "UNKNOWN",
        "team1_id": f"espn-team:{home_team.get('id')}", "team2_id": f"espn-team:{away_team.get('id')}",
        "team1_name": home_team.get("displayName") or home_team.get("name"),
        "team2_name": away_team.get("displayName") or away_team.get("name"),
        "gender": "MEN", "format_id": "BASKETBALL", "period_count": max(len(home_periods), len(away_periods)),
        "period_points_team1": home_periods, "period_points_team2": away_periods,
        "score1_regulation": sum(home_periods[:4]), "score2_regulation": sum(away_periods[:4]),
        "score1_full": int(home_score) if float(home_score).is_integer() else home_score,
        "score2_full": int(away_score) if float(away_score).is_integer() else away_score,
        "ot_points1": sum(home_periods[4:]), "ot_points2": sum(away_periods[4:]),
        "score_basis": "ESPN_SUMMARY_LINESCORES", "known_final_at": observed_at,
        # ESPN's completed team box score is a valid team-history fact.  Keep
        # the provider-specific evidence in a separate field so the common
        # pricing gate can treat it the same way as Titan/7M team history,
        # without pretending it came from a Titan team page.
        "evidence_kind": "TEAM_HISTORY", "source_evidence_kind": "ESPN_BOX_SCORE",
        "source_url": source_url,
        "raw_path": str(raw_path), "source_schema": "ESPN_SUMMARY_V1",
        "home_sign": 0, "box_score_teams": [home_box, away_box],
        "source_status": "STATUS_FINAL",
    }


def _event_family(event):
    text = " ".join(str(event.get(k) or "") for k in ("league_family", "competition_key", "league", "competition")).upper()
    if "WNBA" in text:
        return "WNBA", "WOMEN"
    if "NBA" in text:
        return "NBA", "MEN"
    return None, None


def _profile(rows):
    if not rows:
        return None
    fields = ("FGA", "FTA", "ORB", "TOV", "3PA", "3PM", "PTS", "FGM", "FTM", "REB", "AST", "PF", "STL", "BLK")
    out = {field: None for field in fields}
    for field in fields:
        values = [_num(row.get(field)) for row in rows if _num(row.get(field)) is not None]
        if values:
            out[field] = sum(values) / len(values)
    required = [out.get(field) for field in ("FGA", "FTA", "ORB", "TOV")]
    out["possessions_estimate"] = (required[0] + 0.44 * required[1] - required[2] + required[3]
                                    if all(isinstance(x, (int, float)) for x in required) else None)
    out["games"] = len(rows)
    out["source"] = "ESPN_BOX_SCORE"
    return out


def collect_espn_history(events, root, cutoff=None, workers=6, max_games_per_team=10):
    """Return score/box-score history and pace contexts for NBA/WNBA events."""
    cutoff_dt = cutoff if isinstance(cutoff, datetime) else datetime.now(timezone.utc)
    if cutoff_dt.tzinfo is None:
        cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
    target_events = [event for event in events or [] if _event_family(event)[0]]
    if not target_events:
        return [], {}, {"status": "NOT_APPLICABLE", "target_events": 0}, []
    target_ids = set()
    for event in target_events:
        for side in ("team1", "team2"):
            target_ids.add(canonical_team_token(event.get(side + "_name")))
    session = Path(root) / "raw" / "espn_history" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8])
    session.mkdir(parents=True, exist_ok=True)
    health, errors, candidates = [], [], []
    current_year = cutoff_dt.year
    for sport, family in (("nba", "NBA"), ("wnba", "WNBA")):
        for year in (current_year, current_year - 1):
            url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/{sport}/scoreboard?dates={year}&limit=1000"
            try:
                data, raw = _fetch_json(url, 60, direct=True)
                path = session / f"scoreboard_{sport}_{year}.json"; path.write_bytes(raw)
                rows = data.get("events") or []
                health.append({"source": f"espn:{sport}:history:{year}", "url": url, "success": True,
                               "event_count": len(rows), "raw_path": str(path), "captured_at": stamp()})
                for item in rows:
                    status = ((item.get("status") or {}).get("type") or {})
                    if not status.get("completed") and status.get("name") not in ("STATUS_FINAL", "STATUS_FINAL_OT"):
                        continue
                    tip = _tip(item.get("date"))
                    if not tip or tip >= cutoff_dt:
                        continue
                    comp = ((item.get("competitions") or [{}])[0])
                    comps = comp.get("competitors") or []
                    names = [((x.get("team") or {}).get("displayName") or ((x.get("team") or {}).get("name"))) for x in comps]
                    tokens = {canonical_team_token(x) for x in names if x}
                    if tokens & target_ids:
                        candidates.append({"item": item, "sport": sport, "family": family, "tip": tip,
                                           "tokens": tokens, "source_url": url})
            except Exception as exc:
                errors.append({"source": f"espn:{sport}:history:{year}", "url": url,
                               "error_type": type(exc).__name__, "error": str(exc)})
                health.append({"source": f"espn:{sport}:history:{year}", "url": url, "success": False,
                               "error_type": type(exc).__name__, "error": str(exc), "captured_at": stamp()})
    # Keep the most recent bounded window for each target team.  A single game
    # can satisfy two teams, so the union is fetched once.
    by_team = defaultdict(list)
    for candidate in sorted(candidates, key=lambda x: x["tip"], reverse=True):
        for token in candidate["tokens"] & target_ids:
            if len(by_team[token]) < max_games_per_team:
                by_team[token].append(candidate)
    selected = {}
    for rows in by_team.values():
        for candidate in rows:
            selected[str(candidate["item"].get("id"))] = candidate
    history_rows, team_games = [], defaultdict(list)

    def fetch_summary(item):
        event_id, candidate = item
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/{candidate['sport']}/summary?event={event_id}"
        try:
            data, raw = _fetch_json(url, 60, direct=True)
            path = session / f"summary_{candidate['sport']}_{event_id}.json"; path.write_bytes(raw)
            fact = _final_score_summary(data, event_id, url, path, stamp())
            if not fact:
                return None, {"source": "ESPN_BOX_SCORE", "event_id": event_id, "error": "SUMMARY_SCHEMA_OR_PERIODS_INVALID"}, {"source": "ESPN_BOX_SCORE", "event_id": event_id, "url": url, "success": False, "error": "SUMMARY_SCHEMA_OR_PERIODS_INVALID"}
            family = candidate["family"]
            fact["league"] = family; fact["competition_key"] = family; fact["gender"] = "WOMEN" if family == "WNBA" else "MEN"
            fact["season_phase"] = competition_phase(family)
            fact["box_score_teams"] = fact.get("box_score_teams") or []
            return fact, None, {"source": "ESPN_BOX_SCORE", "event_id": event_id, "url": url,
                                "success": True, "raw_path": str(path), "captured_at": stamp()}
        except Exception as exc:
            err = {"source": "ESPN_BOX_SCORE", "event_id": event_id, "url": url,
                   "error_type": type(exc).__name__, "error": str(exc)}
            return None, err, {"source": "ESPN_BOX_SCORE", "event_id": event_id, "url": url,
                               "success": False, "error_type": type(exc).__name__, "error": str(exc), "captured_at": stamp()}

    # Summary endpoints are independent.  Use the bounded worker budget so a
    # 24-team NBA lookback does not turn into a serial hour-long crawl.
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 6))) as pool:
        fetched = list(pool.map(fetch_summary, sorted(selected.items(), key=lambda x: x[1]["tip"], reverse=True)))
    for fact, error, health_row in fetched:
        if error:
            errors.append(error)
        health.append(health_row)
        if not fact:
            continue
        history_rows.append(fact)
        for side, box in zip(("team1", "team2"), fact["box_score_teams"]):
            token = canonical_team_token(fact.get(side + "_name"))
            if token in target_ids:
                team_games[token].append(box)
    contexts = {}
    for event in target_events:
        family, _ = _event_family(event)
        if not family:
            continue
        p1 = _profile(team_games.get(canonical_team_token(event.get("team1_name")), [])[:max_games_per_team])
        p2 = _profile(team_games.get(canonical_team_token(event.get("team2_name")), [])[:max_games_per_team])
        if not p1 or not p2:
            continue
        boxes = [p1, p2]
        complete = all(isinstance(p.get("possessions_estimate"), (int, float)) and p.get("possessions_estimate") > 0 for p in boxes)
        variables = [field for field in ("FGA", "FTA", "ORB", "TOV", "3PA", "3PM", "PTS")
                     if all(isinstance(p.get(field), (int, float)) for p in boxes)]
        contexts[event.get("event_id")] = {
            "source_urls": ["https://site.api.espn.com/apis/site/v2/sports/basketball/{}/summary".format("wnba" if family == "WNBA" else "nba")],
            "raw_paths": [], "variables": {"ESPN_BOX_SCORE": variables},
            "available_variables": variables, "box_score_teams": boxes,
            "possessions_verified": complete, "possessions_level": "LEVEL_B" if complete else "LEVEL_D",
            "pace_source": "DERIVED_BOX_SCORE" if complete else "UNAVAILABLE",
            "basic_offense_verified": complete, "three_point_verified": all(p.get("3PA") is not None and p.get("3PM") is not None for p in boxes),
            "foundation_history_ready": min(int(p.get("games") or 0) for p in boxes) >= 8,
            "history_source": "ESPN_BOX_SCORE_BRIDGE", "market_inputs_used": False,
        }
    audit = {"status": "CAPTURED" if history_rows else "NO_HISTORY", "target_events": len(target_events),
             "target_teams": len(target_ids), "scoreboard_candidates": len(candidates),
             "summary_selected": len(selected), "history_rows": len(history_rows),
             "teams_with_history": len(team_games), "possessions_contexts": sum(1 for x in contexts.values() if x.get("possessions_verified")),
             "errors": errors, "raw_directory": str(session), "source": "ESPN_BOX_SCORE_BRIDGE"}
    (session / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return history_rows, contexts, audit, health
