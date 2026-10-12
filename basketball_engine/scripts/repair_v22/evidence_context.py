from __future__ import annotations

"""Cutoff-safe evidence helpers for Tier-3 roster stability.

The helpers consume already captured, source-referenced records. They do not
scrape, infer player identities from scores, or treat a missing lineup as a
healthy roster.
"""

from datetime import timedelta
from pathlib import Path

import yaml

from .common import iso


def _policy():
    path = Path(__file__).resolve().parents[2] / "config" / "tier3_roster_policy.yaml"
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _player_id(player):
    return str((player or {}).get("player_id") or (player or {}).get("name") or "").strip()


def _cutoff_valid(record, cutoff, window_days):
    published = record.get("published_at") or record.get("captured_at")
    occurred = record.get("game_at") or published
    if not published or not occurred:
        return False
    try:
        c, p, o = iso(cutoff), iso(published), iso(occurred)
    except (TypeError, ValueError):
        return False
    if p > c or o > c or o < c - timedelta(days=window_days):
        return False
    return bool(record.get("source_url") or record.get("raw_path"))


def _box_score_team(team_id, rows, cutoff, spec, window_days):
    valid = []
    min_players = int(spec.get("minimum_players_with_minutes_per_game", 5))
    min_total = float(spec.get("minimum_total_player_minutes_per_game", 100))
    floor = float(spec.get("rotation_minutes_floor", 8))
    for row in rows:
        if str(row.get("team_id")) != str(team_id) or not _cutoff_valid(row, cutoff, window_days):
            continue
        players = []
        for player in row.get("players") or []:
            pid, minutes = _player_id(player), player.get("minutes")
            if not pid or not isinstance(minutes, (int, float)) or minutes < 0:
                continue
            players.append((pid, float(minutes)))
        if len(players) < min_players or sum(x[1] for x in players) < min_total:
            continue
        valid.append({"game_at": row.get("game_at"), "published_at": row.get("published_at") or row.get("captured_at"),
                      "source_url": row.get("source_url"), "raw_path": row.get("raw_path"),
                      "rotation": sorted(pid for pid, minutes in players if minutes >= floor)})
    minimum_games = int(spec.get("minimum_games_per_team", 3))
    stable_min = int(spec.get("minimum_stable_rotation_players", 4))
    intersection = set(valid[0]["rotation"]) if valid else set()
    for row in valid[1:]:
        intersection.intersection_update(row["rotation"])
    return {"method": "BOX_SCORE_MINUTES_30D", "valid_snapshots": len(valid),
            "stable_players": sorted(intersection), "stable_player_count": len(intersection),
            "verified": len(valid) >= minimum_games and len(intersection) >= stable_min,
            "evidence": valid}


def _lineup_team(team_id, rows, cutoff, spec, window_days):
    valid = []
    min_players = int(spec.get("minimum_players_per_snapshot", 5))
    for row in rows:
        if str(row.get("team_id")) != str(team_id) or not _cutoff_valid(row, cutoff, window_days):
            continue
        players = sorted({_player_id(x) for x in (row.get("players") or []) if _player_id(x)})
        if len(players) < min_players:
            continue
        valid.append({"published_at": row.get("published_at") or row.get("captured_at"),
                      "source_url": row.get("source_url"), "raw_path": row.get("raw_path"),
                      "players": players})
    minimum = int(spec.get("minimum_snapshots_per_team", 2))
    stable_min = int(spec.get("minimum_stable_players", 4))
    intersection = set(valid[0]["players"]) if valid else set()
    for row in valid[1:]:
        intersection.intersection_update(row["players"])
    return {"method": "PREGAME_LINEUP_PUBLICATIONS_30D", "valid_snapshots": len(valid),
            "stable_players": sorted(intersection), "stable_player_count": len(intersection),
            "verified": len(valid) >= minimum and len(intersection) >= stable_min,
            "evidence": valid}


def evaluate_tier3_roster_stability(event, context, cutoff):
    policy = _policy()
    window_days = int(policy.get("window_days", 30))
    targets = (event.get("team1_id"), event.get("team2_id"))
    box_rows = list(context.get("box_score_minutes") or [])
    lineup_rows = list(context.get("pregame_lineup_snapshots") or [])
    teams = {}
    for team_id in targets:
        box = _box_score_team(team_id, box_rows, cutoff, policy.get("box_score_minutes") or {}, window_days)
        lineup = _lineup_team(team_id, lineup_rows, cutoff, policy.get("pregame_lineups") or {}, window_days)
        chosen = box if box.get("verified") else lineup
        teams[str(team_id)] = {"verified": bool(box.get("verified") or lineup.get("verified")),
                               "selected_method": chosen.get("method"), "box_score": box, "pregame_lineup": lineup}
    verified = bool(targets[0] and targets[1] and all(teams[str(t)]["verified"] for t in targets))
    return {"status": "VERIFIED" if verified else "MISSING", "verified": verified,
            "window_days": window_days, "teams": teams,
            "policy_source": str(Path(__file__).resolve().parents[2] / "config" / "tier3_roster_policy.yaml")}
