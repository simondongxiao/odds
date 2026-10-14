"""Bridge cutoff-safe Titan007 facts into the source-agnostic evidence contract.

The module deliberately contains no pricing or market-derived features.  It
normalizes already captured SQLite facts once per run, then exposes the same
history and evidence bundle to Champion and Challenger models.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from repair_v22.common import iso, load, durable_competition_key


SOURCE = "TITAN007"


def _json(value, fallback):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return parsed if isinstance(parsed, type(fallback)) else fallback
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _field(value, source, timestamp, cutoff, quality, raw_ref=None):
    if isinstance(value, datetime):
        value = value.astimezone(timezone.utc).isoformat()
    if isinstance(timestamp, datetime):
        timestamp = timestamp.astimezone(timezone.utc).isoformat()
    if isinstance(raw_ref, Path):
        raw_ref = str(raw_ref)
    valid = False
    if timestamp:
        try:
            valid = iso(timestamp) <= iso(cutoff)
        except (TypeError, ValueError):
            valid = False
    return {
        "value": value, "source": source, "source_timestamp": timestamp,
        "cutoff_valid": valid, "quality": quality, "raw_ref": raw_ref,
    }


def _safe_mean(values):
    values = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(float(v))]
    return sum(values) / len(values) if values else None


def _ensure_schema(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS normalized_history(
          normalized_history_id TEXT PRIMARY KEY, source TEXT NOT NULL,
          source_event_id TEXT NOT NULL, league_id TEXT NOT NULL,
          competition_key TEXT NOT NULL, home_team_id TEXT NOT NULL,
          away_team_id TEXT NOT NULL, tip_at TEXT NOT NULL,
          source_timestamp TEXT NOT NULL, cutoff_valid INTEGER NOT NULL,
          final_score_valid INTEGER NOT NULL, deduplicated INTEGER NOT NULL,
          quality TEXT NOT NULL, raw_ref TEXT, payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL)
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_normalized_history_comp_tip ON normalized_history(competition_key,tip_at DESC,cutoff_valid,final_score_valid)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_normalized_history_home_tip ON normalized_history(home_team_id,tip_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_normalized_history_away_tip ON normalized_history(away_team_id,tip_at DESC)")


def _event_specs(events, mappings, foundation_contexts):
    specs = {}
    for event in events or []:
        context = (foundation_contexts or {}).get(event.get("event_id")) or {}
        league_id = context.get("league_id")
        home_titan = context.get("team1_titan_id") or mappings.get(str(event.get("team1_id") or ""))
        away_titan = context.get("team2_titan_id") or mappings.get(str(event.get("team2_id") or ""))
        if not (league_id and home_titan and away_titan):
            continue
        specs[event["event_id"]] = {
            "event": event, "context": context, "league_id": str(league_id),
            "home_titan": str(home_titan), "away_titan": str(away_titan),
        }
    return specs


def load_normalized_history_store(root, events, mappings, foundation_contexts, cutoff):
    """Return all stored, source-referenced same-competition facts before cutoff."""
    db_path = Path(root) / "titan007_history.sqlite"
    if not db_path.exists():
        return [], {}, {"status": "DATABASE_MISSING", "rows": 0}
    specs = _event_specs(events, mappings, foundation_contexts)
    reverse = {str(titan): str(canonical) for canonical, titan in (mappings or {}).items() if titan}
    # Mapping is run-global.  Adding exact event pairs once removes the former
    # need to remap the same league history separately for every fixture.
    for spec in specs.values():
        event = spec["event"]
        reverse[str(spec["home_titan"])] = str(event.get("team1_id"))
        reverse[str(spec["away_titan"])] = str(event.get("team2_id"))
    by_key, event_ids = {}, defaultdict(set)
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    _ensure_schema(db)
    cutoff_utc = iso(cutoff).astimezone(timezone.utc).isoformat()
    raw_rows_by_league = {}
    games_by_scope = {}
    try:
        for event_id, spec in specs.items():
            event, league_id = spec["event"], spec["league_id"]
            competition = event.get("competition_key") or event.get("league_family") or event.get("league")
            scope_key = (str(league_id), str(competition), str(event.get("gender") or ""))
            games = games_by_scope.get(scope_key)
            if games is None:
                rows = raw_rows_by_league.get(str(league_id))
                if rows is None:
                    rows = db.execute(
                        "SELECT m.*,s.captured_at,s.raw_path,s.sha256 FROM match_history m "
                        "LEFT JOIN source_snapshot s ON s.snapshot_id=m.source_snapshot_id "
                        "WHERE m.league_id=? AND m.status='FINAL' AND m.tip_at<? ORDER BY m.tip_at",
                        (league_id, cutoff_utc),
                    ).fetchall()
                    raw_rows_by_league[str(league_id)] = rows
                games = []
                for row in rows:
                    source_timestamp = row["captured_at"] or row["updated_at"]
                    raw_ref = row["raw_path"]
                    try:
                        cutoff_valid = bool(source_timestamp and iso(source_timestamp) <= iso(cutoff))
                    except (TypeError, ValueError):
                        cutoff_valid = False
                    home_periods = _json(row["periods_home_json"], [])
                    away_periods = _json(row["periods_away_json"], [])
                    score_valid = (len(home_periods) >= 4 and len(away_periods) >= 4 and
                                   row["home_score"] is not None and row["away_score"] is not None and
                                   sum(home_periods) == int(row["home_score"]) and
                                   sum(away_periods) == int(row["away_score"]))
                    if not (cutoff_valid and score_valid and raw_ref):
                        continue
                    home_id = reverse.get(str(row["home_titan_team_id"]),
                                          "titan-team:" + str(row["home_titan_team_id"]))
                    away_id = reverse.get(str(row["away_titan_team_id"]),
                                          "titan-team:" + str(row["away_titan_team_id"]))
                    game = {
                        "event_id": "titan:" + str(row["titan_match_id"]),
                        "source_event_id": str(row["titan_match_id"]), "tip_at": row["tip_at"],
                        "status": "FINAL", "competition_id": None,
                        "source_competition_id_titan": league_id,
                        "competition_key": competition, "competition_identity_level": "TITAN_LEAGUE_ID_EXACT",
                        "league": row["league"] or event.get("league"),
                        "team1_id": home_id, "team2_id": away_id,
                        "team1_name": row["home_name"], "team2_name": row["away_name"],
                        "gender": event.get("gender"), "format_id": "BASKETBALL",
                        "period_count": len(home_periods), "period_points_team1": home_periods,
                        "period_points_team2": away_periods,
                        "score1_regulation": sum(home_periods[:4]), "score2_regulation": sum(away_periods[:4]),
                        "score1_full": sum(home_periods), "score2_full": sum(away_periods),
                        "ot_points1": sum(home_periods[4:]), "ot_points2": sum(away_periods[4:]),
                        "score_basis": "TITAN_NORMALIZED_HISTORY_STORE", "known_final_at": source_timestamp,
                        "evidence_kind": "TEAM_HISTORY", "source": SOURCE,
                        "source_url": "https://nba.titan007.com/analysis/%s.htm" % row["titan_match_id"],
                        "raw_path": raw_ref, "raw_sha256": row["sha256"],
                        "source_variable": "match_history+period_score", "source_schema": "NORMALIZED_HISTORY_V1",
                        "history_quality": "VERIFIED_FINAL_PERIOD_SCORE", "market_inputs_used": False,
                    }
                    key = (game["event_id"], str(competition), home_id, away_id)
                    by_key[key] = game
                    games.append(game)
                    payload = json.dumps(game, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    normalized_id = hashlib.sha256(("|".join(map(str, key))).encode("utf-8")).hexdigest()
                    db.execute(
                        "INSERT OR REPLACE INTO normalized_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (normalized_id, SOURCE, str(row["titan_match_id"]), league_id, str(competition),
                         home_id, away_id, row["tip_at"], source_timestamp, 1, 1, 1,
                         "VERIFIED_FINAL_PERIOD_SCORE", raw_ref, payload,
                         datetime.now(timezone.utc).isoformat()),
                    )
                games_by_scope[scope_key] = games
            event_ids[event_id].update(game["event_id"] for game in games)
        db.commit()
    finally:
        db.close()
    rows = sorted(by_key.values(), key=lambda item: (item["tip_at"], item["event_id"]))
    return rows, {key: sorted(value) for key, value in event_ids.items()}, {
        "status": "OK", "database": str(db_path), "rows": len(rows),
        "events_with_history": sum(bool(value) for value in event_ids.values()),
        "league_queries": len(raw_rows_by_league),
        "normalized_scopes": len(games_by_scope),
        "one_pass_reuse": True,
        "market_inputs_used": False,
    }


def _rotation_evidence(db, spec, cutoff):
    cutoff_dt = iso(cutoff)
    floor = cutoff_dt - timedelta(days=30)
    teams = {}
    records = []
    for canonical, titan in ((spec["event"].get("team1_id"), spec["home_titan"]),
                             (spec["event"].get("team2_id"), spec["away_titan"])):
        rows = db.execute(
            "SELECT p.*,s.captured_at,s.raw_path,s.url FROM player_game_boxscore p "
            "LEFT JOIN source_snapshot s ON s.snapshot_id=p.source_snapshot_id "
            "WHERE p.titan_team_id=? AND p.league_id=? AND p.tip_at>=? AND p.tip_at<? "
            "ORDER BY p.tip_at DESC,p.titan_match_id,p.minutes DESC",
            (titan, spec["league_id"], floor.astimezone(timezone.utc).isoformat(),
             cutoff_dt.astimezone(timezone.utc).isoformat()),
        ).fetchall()
        games = defaultdict(list); metadata = {}
        for row in rows:
            if not isinstance(row["minutes"], (int, float)) or float(row["minutes"]) < 0:
                continue
            games[str(row["titan_match_id"])].append({
                "player_id": str(row["titan_player_id"]), "minutes": float(row["minutes"]),
                "starter": bool(row["starter"]) if row["starter"] is not None else None,
            })
            metadata[str(row["titan_match_id"])] = row
        snapshots = []
        for match_id, players in games.items():
            meta = metadata[match_id]
            captured = meta["captured_at"] or meta["updated_at"]
            raw_ref = meta["raw_path"]
            if not raw_ref or not captured or iso(captured) > cutoff_dt:
                continue
            snapshots.append({
                "team_id": canonical, "game_at": meta["tip_at"], "published_at": captured,
                "source_url": meta["url"], "raw_path": raw_ref, "players": players,
            })
        snapshots.sort(key=lambda item: item["game_at"], reverse=True)
        records.extend(snapshots)
        windows = {}
        for n in (3, 5, 10):
            sample = snapshots[:n]
            top5, top8, starter_sets, all_players = [], [], [], set()
            for game in sample:
                players = sorted(game["players"], key=lambda item: item["minutes"], reverse=True)
                total = sum(item["minutes"] for item in players)
                if total > 0:
                    top5.append(sum(item["minutes"] for item in players[:5]) / total)
                    top8.append(sum(item["minutes"] for item in players[:8]) / total)
                starters = {item["player_id"] for item in players if item.get("starter")}
                if starters:
                    starter_sets.append(starters)
                all_players.update(item["player_id"] for item in players)
            starter_continuity = None
            if len(starter_sets) >= 2:
                pairs = [len(a & b) / len(a | b) for a, b in zip(starter_sets, starter_sets[1:]) if a | b]
                starter_continuity = _safe_mean(pairs)
            windows[str(n)] = {
                "games": len(sample), "starter_continuity": starter_continuity,
                "top5_minutes_share": _safe_mean(top5), "top8_minutes_share": _safe_mean(top8),
                "player_appearances": len(all_players), "minutes_concentration": _safe_mean(top8),
            }
        latest, previous = (snapshots + [None, None])[:2]
        returning_minutes = None
        if latest and previous:
            prior = {item["player_id"] for item in previous["players"]}
            total = sum(item["minutes"] for item in latest["players"])
            returning_minutes = (sum(item["minutes"] for item in latest["players"] if item["player_id"] in prior) / total
                                 if total > 0 else None)
        stable = set()
        if snapshots:
            stable = {item["player_id"] for item in snapshots[0]["players"] if item["minutes"] >= 8}
            for game in snapshots[1:3]:
                stable &= {item["player_id"] for item in game["players"] if item["minutes"] >= 8}
        teams[str(canonical)] = {
            "verified": len(snapshots) >= 3 and len(stable) >= 4,
            "valid_games_30d": len(snapshots), "stable_rotation_players": len(stable),
            "returning_minutes": returning_minutes, "windows": windows,
            "current_availability": "UNKNOWN", "source": "TITAN007_PLAYER_GAME_BOXSCORE",
        }
    verified = len(teams) == 2 and all(item["verified"] for item in teams.values())
    return {
        "status": "VERIFIED" if verified else "MISSING", "verified": verified,
        "window_days": 30, "teams": teams, "box_score_minutes": records,
        "current_availability": "UNKNOWN",
    }


class _HistoryEvidenceIndex:
    """Cutoff-safe history buckets reused by every event in one run."""

    def __init__(self, history, cutoff):
        self.by_team_competition = defaultdict(dict)
        self.by_team_titan_league = defaultdict(dict)
        cutoff_at = iso(cutoff)
        for game in history or []:
            if game.get("status") != "FINAL":
                continue
            try:
                if iso(game.get("tip_at")) >= cutoff_at or iso(game.get("known_final_at")) > cutoff_at:
                    continue
            except (TypeError, ValueError):
                continue
            event_id = str(game.get("event_id") or "")
            if not event_id:
                continue
            competition = str(durable_competition_key(game) or "")
            titan_league = str(game.get("source_competition_id_titan") or "")
            for target in {str(game.get("team1_id") or ""), str(game.get("team2_id") or "")}:
                if not target:
                    continue
                self.by_team_competition[(target, competition)][event_id] = game
                if titan_league:
                    self.by_team_titan_league[(target, titan_league)][event_id] = game

    def counts(self, event, source_competition_id_titan=None):
        targets = (str(event.get("team1_id")), str(event.get("team2_id")))
        competition = str(event.get("competition_key") or "")
        titan_league = str(source_competition_id_titan or "")
        counts, opponents, sources, max_timestamp = {}, {}, set(), None
        for target in targets:
            valid = dict(self.by_team_competition.get((target, competition), {}))
            if titan_league:
                valid.update(self.by_team_titan_league.get((target, titan_league), {}))
            games = list(valid.values())
            counts[target] = len(games)
            opponents[target] = len({
                str(item.get("team2_id")) if str(item.get("team1_id")) == target
                else str(item.get("team1_id")) for item in games
            })
            sources.update(str(item.get("source") or item.get("source_schema") or "OTHER") for item in games)
            timestamps = [item.get("known_final_at") for item in games if item.get("known_final_at")]
            if timestamps:
                candidate = max(timestamps)
                max_timestamp = max(max_timestamp, candidate) if max_timestamp else candidate
        return targets, counts, opponents, sorted(sources), max_timestamp


def _history_counts(event, history, cutoff, source_competition_id_titan=None):
    index = history if isinstance(history, _HistoryEvidenceIndex) else _HistoryEvidenceIndex(history, cutoff)
    return index.counts(event, source_competition_id_titan)


def _metric_pair(states, name):
    values = []
    for state in states or []:
        values.append((state.get("metrics") or {}).get(name))
    return values if values else [None, None]


def build_pregame_evidence_bundles(root, events, history, mappings, foundation_contexts,
                                    cutoff, pre_bridge_history=None):
    """Build field-provenance bundles and model contexts after history merging."""
    db_path = Path(root) / "titan007_history.sqlite"
    specs = _event_specs(events, mappings, foundation_contexts)
    db = sqlite3.connect(db_path) if db_path.exists() else None
    if db:
        db.row_factory = sqlite3.Row
    contexts, audit_rows = {}, []
    history_index = _HistoryEvidenceIndex(history, cutoff)
    pre_bridge_history_index = _HistoryEvidenceIndex(pre_bridge_history or [], cutoff)
    try:
        for event_id, spec in specs.items():
            event, foundation = spec["event"], dict(spec["context"])
            targets, counts, opponents, sources, timestamp = _history_counts(
                event, history_index, cutoff, spec["league_id"])
            _, old_counts, _, _, _ = _history_counts(
                event, pre_bridge_history_index, cutoff, spec["league_id"])
            rotation = _rotation_evidence(db, spec, cutoff) if db else {
                "status": "MISSING", "verified": False, "teams": {}, "box_score_minutes": [],
                "current_availability": "UNKNOWN"}
            quality = "VERIFIED_SAME_COMP_PRE_CUTOFF" if min(counts.values(), default=0) >= 8 else "INSUFFICIENT"
            history_ready = min(counts.values(), default=0) >= 8 and min(opponents.values(), default=0) >= 3
            rule = game_rule_for(event)
            team_states = foundation.get("team_states") or []
            team_profiles = foundation.get("team_profiles") or []
            field_ts = foundation.get("source_max_tip_at") or timestamp
            raw_ref = foundation.get("source_database") or str(db_path)
            pace_value = ((foundation.get("model_b") or {}).get("expected_pace") or
                          _safe_mean([item.get("possessions_estimate") for item in team_profiles]))
            three_pa = [item.get("3PA") for item in team_profiles]
            three_pm = [item.get("3PM") for item in team_profiles]
            three_pct = [(made / attempted if isinstance(made, (int, float)) and
                          isinstance(attempted, (int, float)) and attempted > 0 else None)
                         for made, attempted in zip(three_pm, three_pa)]
            net_rating_values = _metric_pair(team_states, "netrtg")
            net_rating_derived = all(isinstance(value, (int, float)) for value in net_rating_values)
            efficiency_source = "DERIVED_TITAN" if net_rating_derived else SOURCE
            bundle = {
                "schema_version": "pregame-evidence-bundle-1.0",
                "canonical_event_id": event_id,
                "IDENTITY": {
                    "league_id": _field(spec["league_id"], SOURCE, field_ts, cutoff, "EXACT_LEAGUE_ID", raw_ref),
                    "season": _field((team_states[0].get("season") if team_states else None), SOURCE, field_ts, cutoff, "SOURCE_SEASON", raw_ref),
                    "competition": _field(event.get("competition_key"), "CANONICAL_EVENT", cutoff, cutoff, "CANONICAL", None),
                    "home_team_id": _field(event.get("team1_id"), "CANONICAL_EVENT", cutoff, cutoff, "CANONICAL", None),
                    "away_team_id": _field(event.get("team2_id"), "CANONICAL_EVENT", cutoff, cutoff, "CANONICAL", None),
                    "tip_time": _field(event.get("tip_at"), "CANONICAL_EVENT", cutoff, cutoff, "CANONICAL", None),
                    "cutoff_time": _field(cutoff, "RUN_CUTOFF", cutoff, cutoff, "FROZEN", None),
                },
                "HISTORY": {
                    "home_raw_games": _field(counts.get(targets[0], 0), sources, timestamp, cutoff, quality, raw_ref),
                    "away_raw_games": _field(counts.get(targets[1], 0), sources, timestamp, cutoff, quality, raw_ref),
                    "home_same_comp_games": _field(counts.get(targets[0], 0), sources, timestamp, cutoff, quality, raw_ref),
                    "away_same_comp_games": _field(counts.get(targets[1], 0), sources, timestamp, cutoff, quality, raw_ref),
                    "home_unique_opponents": _field(opponents.get(targets[0], 0), sources, timestamp, cutoff, quality, raw_ref),
                    "away_unique_opponents": _field(opponents.get(targets[1], 0), sources, timestamp, cutoff, quality, raw_ref),
                    "history_ess": _field(min((state.get("ess", 0) for state in team_states), default=0), SOURCE, field_ts, cutoff, "TIME_DECAYED", raw_ref),
                    "effective_opponent_diversity": _field(min(opponents.values(), default=0), sources, timestamp, cutoff, quality, raw_ref),
                    "history_sources": _field(sources, "NORMALIZED_HISTORY_STORE", timestamp, cutoff, quality, str(db_path)),
                    "history_source_quality": _field(quality, "NORMALIZED_HISTORY_STORE", timestamp, cutoff, quality, str(db_path)),
                    "verified_same_comp_pre_cutoff_history": _field(history_ready, "NORMALIZED_HISTORY_STORE", timestamp, cutoff, quality, str(db_path)),
                    "pre_bridge_home_games": _field(old_counts.get(targets[0], 0), "PRE_BRIDGE_AUDIT", cutoff, cutoff, "AUDIT", None),
                    "pre_bridge_away_games": _field(old_counts.get(targets[1], 0), "PRE_BRIDGE_AUDIT", cutoff, cutoff, "AUDIT", None),
                },
                "PACE": {
                    "pace_level": _field(foundation.get("possessions_level"), SOURCE, field_ts, cutoff, "BOX_SCORE_DERIVED", raw_ref),
                    "direct_pace": _field(None, SOURCE, field_ts, cutoff, "NOT_AVAILABLE", raw_ref),
                    "derived_possessions": _field(pace_value, SOURCE, field_ts, cutoff, "DERIVED_BOX_SCORE", raw_ref),
                },
                "EFFICIENCY": {
                    "ORtg": _field(_metric_pair(team_states, "ortg"), efficiency_source, field_ts, cutoff, "OPPONENT_ADJUSTED_TEAM_STATE", raw_ref),
                    "DRtg": _field(_metric_pair(team_states, "drtg"), efficiency_source, field_ts, cutoff, "OPPONENT_ADJUSTED_TEAM_STATE", raw_ref),
                    "NetRtg": _field(net_rating_values, efficiency_source, field_ts, cutoff, "DERIVED_TITAN" if net_rating_derived else "OPPONENT_ADJUSTED_TEAM_STATE", raw_ref),
                },
                "FOUR_FACTORS": {
                    "eFG": _field(_metric_pair(team_states, "efg_pct"), SOURCE, field_ts, cutoff, "BOX_SCORE_DERIVED", raw_ref),
                    "TOV_rate": _field(_metric_pair(team_states, "tov_pct"), SOURCE, field_ts, cutoff, "BOX_SCORE_DERIVED", raw_ref),
                    "ORB_rate": _field(_metric_pair(team_states, "orb_pct"), SOURCE, field_ts, cutoff, "BOX_SCORE_DERIVED", raw_ref),
                    "FTr": _field(_metric_pair(team_states, "ft_rate"), SOURCE, field_ts, cutoff, "BOX_SCORE_DERIVED", raw_ref),
                    "3PA_rate": _field(three_pa, SOURCE, field_ts, cutoff, "BOX_SCORE_DERIVED", raw_ref),
                    "3P_pct": _field(three_pct, SOURCE, field_ts, cutoff, "BOX_SCORE_DERIVED", raw_ref),
                    "3P_variance": _field(None, SOURCE, field_ts, cutoff, "INSUFFICIENT_GAME_LEVEL_SERIES", raw_ref),
                    "PF_per_100": _field(_metric_pair(team_states, "pf_per_100"), SOURCE, field_ts, cutoff, "BOX_SCORE_DERIVED", raw_ref),
                    "opponent_FTA": _field(_metric_pair(team_states, "opponent_fta_per_100"), SOURCE, field_ts, cutoff, "BOX_SCORE_DERIVED", raw_ref),
                    "FTr_allowed": _field(_metric_pair(team_states, "opponent_ft_rate"), SOURCE, field_ts, cutoff, "BOX_SCORE_DERIVED", raw_ref),
                },
                "ROTATION": _field(rotation, "TITAN007_PLAYER_GAME_BOXSCORE", field_ts, cutoff,
                                   "VERIFIED_30D" if rotation.get("verified") else "INSUFFICIENT", raw_ref),
                "RULE": {key: _field(value, rule.get("source"), cutoff, cutoff,
                                      "REGISTRY_VERIFIED" if rule.get("verified") else "UNKNOWN",
                                      rule.get("source_url")) for key, value in rule.items()
                         if key in ("regulation_minutes", "period_count", "period_minutes", "overtime_minutes")},
                "MARKET": {key: _field(None, None, None, cutoff, "NOT_LOADED_BEFORE_FAIR_FREEZE", None)
                           for key in ("spread", "spread_odds", "total", "over_odds", "under_odds",
                                       "provider", "market_timestamp", "market_contract")},
                "DATA_QUALITY": {
                    "history_ready": history_ready, "rule_ready": bool(rule.get("verified")),
                    "rotation_continuity_verified": bool(rotation.get("verified")),
                    "current_availability": rotation.get("current_availability", "UNKNOWN"),
                    "net_rating_context_verified": net_rating_derived,
                    "net_rating_source": efficiency_source,
                    "market_inputs_used_in_fair_price": False,
                },
            }
            context = dict(foundation)
            context.update({
                "pregame_evidence_bundle": bundle,
                "box_score_minutes": rotation.get("box_score_minutes", []),
                "rotation_continuity": rotation,
                "rotation_continuity_verified": bool(rotation.get("verified")),
                "roster_stability_30d_verified": bool(rotation.get("verified")),
                "roster_verified": bool(rotation.get("verified")),
                "current_availability": rotation.get("current_availability", "UNKNOWN"),
                "net_rating_context_verified": net_rating_derived,
                "net_rating_source": efficiency_source,
                "rotation_continuity_metrics": rotation.get("teams", {}),
            })
            contexts[event_id] = context
            audit_rows.append({
                "event_id": event_id, "league": event.get("league"),
                "titan_theoretical_price": isinstance(foundation.get("technical_fair_margin_neutral"), (int, float)) or
                                           isinstance(foundation.get("technical_fair_total"), (int, float)),
                "history_ready_from_titan": bool(foundation.get("foundation_history_ready")),
                "unified_history_ready": history_ready,
                "pre_bridge_min_games": min(old_counts.values(), default=0),
                "post_bridge_min_games": min(counts.values(), default=0),
                "minimum_unique_opponents": min(opponents.values(), default=0),
                "rotation_continuity_verified": bool(rotation.get("verified")),
                "game_rule_ready": bool(rule.get("verified")),
            })
    finally:
        if db:
            db.close()
    return contexts, audit_rows


def game_rule_for(event):
    registry = load(Path(__file__).resolve().parents[1] / "config" / "game_rule_registry.json", {})
    text = " ".join(str(event.get(key) or "") for key in ("league", "competition_key", "league_family"))
    for rule in registry.get("rules", []):
        if str(rule.get("match") or "").casefold() in text.casefold():
            minutes = rule.get("minutes")
            periods = int(rule.get("period_count") or 4) if minutes else None
            return {
                "verified": bool(minutes), "regulation_minutes": minutes,
                "period_count": periods,
                "period_minutes": (float(minutes) / periods if minutes and periods else None),
                "overtime_minutes": rule.get("overtime_minutes", 5 if minutes else None),
                "source": rule.get("source"), "source_url": rule.get("source_url"),
            }
    return {"verified": False, "regulation_minutes": None, "period_count": None,
            "period_minutes": None, "overtime_minutes": None,
            "source": "UNKNOWN_NO_MINUTES_ASSUMED", "source_url": None}


def attach_market_evidence(bundle, quotes, quote_states, cutoff):
    """Attach real market facts only after the independent fair price is frozen."""
    out = json.loads(json.dumps(bundle or {}))
    market = out.setdefault("MARKET", {})
    paired = list(zip(quotes or [], quote_states or []))
    eligible = [(quote, state) for quote, state in paired if state.get("paper_quote_eligible")]
    spread = next(((q, s) for q, s in eligible if q.get("market_type") == "SPREAD"), None)
    total = next(((q, s) for q, s in eligible if q.get("market_type") == "TOTAL"), None)
    def put(name, value, quote, quality="VERIFIED_MARKET_CONTRACT"):
        market[name] = _field(value, quote.get("feed_provider") or quote.get("source") or quote.get("bookmaker"),
                              quote.get("source_quote_at") or quote.get("received_at"), cutoff, quality,
                              quote.get("raw_path"))
    if spread:
        q, _ = spread
        put("spread", q.get("line_team1"), q); put("spread_odds", q.get("decimal_prices"), q)
    if total:
        q, _ = total
        put("total", q.get("raw_line"), q); put("over_odds", (q.get("decimal_prices") or [None])[0], q)
        put("under_odds", (q.get("decimal_prices") or [None, None])[-1], q)
    chosen = (spread or total)
    if chosen:
        q, _ = chosen
        put("provider", q.get("bookmaker"), q); put("market_timestamp", q.get("source_quote_at") or q.get("received_at"), q)
        put("market_contract", {"period": q.get("period"), "ot_rule": q.get("ot_rule"),
                                "direction_verified": q.get("direction_verified"),
                                "both_side_odds": bool(q.get("decimal_prices") and len(q.get("decimal_prices")) == 2)}, q)
    out.setdefault("DATA_QUALITY", {})["market_inputs_used_in_fair_price"] = False
    out["DATA_QUALITY"]["market_loaded_after_fair_freeze"] = True
    return out
