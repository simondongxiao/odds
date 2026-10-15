"""Titan007 team-history and box-score reference database.

The public team database is JavaScript-backed.  This adapter downloads the
same normal HTTP resources used by the rendered pages, stores immutable raw
snapshots, and normalizes only source facts.  Handicap/total trend summaries
are deliberately excluded from model history and remain market evidence.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
import sqlite3
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urljoin

from repair_v22.common import assignments, competition_key
from odds_shared.http_retry import RetryPolicy, request_with_retry
from providers.titan007_feature_store import (
    ensure_feature_schema, upsert_player_boxscores, rebuild_team_game_features,
    evaluate_source_capabilities, rebuild_player_season_stats, build_matchup,
)

try:
    from curl_cffi import requests as curl_requests
except ImportError:  # pragma: no cover - production image currently includes it
    curl_requests = None


BJ = timezone(timedelta(hours=8))
BASE = "https://nba.titan007.com"
MAX_BYTES = 8_000_000
FOUNDATION_LEAGUES = {
    # NBA TeamInfo also lists synthetic play-in placeholders.  LeagueRank is
    # the current-season source of truth and contains the 30 real clubs only.
    "NBA": {"league_id": "1", "page": f"{BASE}/cn/LeagueRank.aspx?SclassID=1",
            "asset_pattern": r"/jsData/rank/[^\"']+/s1\.js[^\"']*"},
    "WNBA": {"league_id": "2", "page": f"{BASE}/cn/TeamInfo.aspx?SclassID=2",
             "asset_pattern": r"/jsData/teamInfo/ti2\.js[^\"']*"},
    # EuroLeague is represented as a cup competition by Titan. Its TeamInfo
    # file currently contains arrTeam=[], while the current CupMatch asset is
    # the authoritative complete membership list.
    "EUROLEAGUE": {"league_id": "7", "page": f"{BASE}/cn/CupMatch.aspx?SclassID=7",
                   "asset_pattern": r"/jsData/matchResult/[^\"']+/c7\.js[^\"']*"},
}


def _stamp(value=None):
    value = value or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _sha(blob):
    return hashlib.sha256(blob).hexdigest()


def _token(value):
    text = html.unescape(str(value or "")).casefold()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)


def _search_name(value):
    """Remove 7M display-only standings/league suffixes, never team text."""
    text = str(value or "").strip()
    while re.search(r"\[[^\[\]]+\]\s*$", text):
        text = re.sub(r"\s*\[[^\[\]]+\]\s*$", "", text).strip()
    return text


# 7M uses Chinese display names while Titan's team search sometimes exposes
# the English/short sponsor name as the exact alias.  These are reviewed
# spelling variants only; a returned Titan TeamID is still accepted only when
# Titan's own search response contains an exact alias match.  Keeping this
# table explicit prevents a fuzzy name match from joining two different clubs.
TEAM_SEARCH_ALIASES = {
    "塔斯曼尼亚跳蚁": ("塔斯马尼亚跳蚁", "Tasmania JackJumpers", "Tasmania Jack Jumpers"),
    "塔斯马尼亚跳蚁": ("塔斯曼尼亚跳蚁", "Tasmania JackJumpers", "Tasmania Jack Jumpers"),
    "阿德莱德36人": ("阿德莱德三十六人", "Adelaide 36ers"),
    "阿德莱德三十六人": ("阿德莱德36人", "Adelaide 36ers"),
    "悉尼国王": ("Sydney Kings",),
    "墨尔本联": ("Melbourne United",),
    "珀斯野猫": ("Perth Wildcats",),
    "新西兰破坏者": ("New Zealand Breakers", "NZ Breakers"),
    "布里斯班子弹": ("Brisbane Bullets",),
    "凯恩斯大班": ("Cairns Taipans",),
    "伊拉瓦拉老鹰": ("Illawarra Hawks",),
    "东南墨尔本凤凰": ("South East Melbourne Phoenix", "SEM Phoenix"),
    "阿拉巴马": ("Alabama", "Alabama Crimson Tide"),
    "密西西比": ("Mississippi", "Ole Miss", "Mississippi Rebels"),
}


def _team_search_queries(value):
    """Return conservative reviewed queries for one source team name."""
    cleaned = _search_name(value)
    aliases = TEAM_SEARCH_ALIASES.get(cleaned, ())
    return list(dict.fromkeys([cleaned, *aliases]))


def _int(value):
    if isinstance(value, bool):
        return None
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out


def _float(value):
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _strip_score(value):
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    match = re.search(r"(\d+)\s*-\s*(\d+)", text)
    return (int(match.group(1)), int(match.group(2))) if match else (None, None)


def _tech_url(match_id):
    sid = str(match_id)
    if len(sid) < 3 or not sid.isdigit():
        raise ValueError("INVALID_TITAN_MATCH_ID")
    return f"{BASE}/jsData/tech/{sid[0]}/{sid[1:3]}/{sid}.js"


def parse_search_response(text, query):
    """Parse either the legacy autocomplete payload or Search_Team HTML.

    Search_Team is preferred because the autocomplete handler can legally
    return an empty 200 response.  A mapping is accepted only when exactly
    one distinct TeamID contains an alias equal to the canonical query after
    conservative punctuation/case normalization.
    """
    source = str(text or "")
    by_id = {}
    if "TeamID=" in source:
        for block in re.findall(r"<tr\b[^>]*>(.*?)</tr>", source, re.I | re.S):
            ids = re.findall(r"TeamID=(\d+)", block, re.I)
            if not ids:
                continue
            team_id = ids[0]
            cells = re.findall(r"<td\b[^>]*>(.*?)</td>", block, re.I | re.S)
            values = []
            for cell in cells:
                value = html.unescape(re.sub(r"<[^>]+>", "", cell)).strip()
                value = re.sub(r"\s+", " ", value)
                if value:
                    values.append(value)
            aliases = values[1:] if len(values) > 1 else values
            league_ids = re.findall(r"SclassID=(\d+)", block, re.I)
            row = by_id.setdefault(team_id, {"team_id": team_id, "name": aliases[0] if aliases else "",
                                             "aliases": [], "league_id": league_ids[0] if league_ids else None,
                                             "league": values[0] if len(values) > 1 else None})
            row["aliases"] = list(dict.fromkeys(row["aliases"] + aliases))
    else:
        for raw in source.split(","):
            parts = raw.split("^")
            if len(parts) < 2 or _int(parts[0]) is None:
                continue
            team_id = str(int(parts[0]))
            by_id[team_id] = {"team_id": team_id, "name": parts[1].strip(),
                              "aliases": [parts[1].strip()], "league_id": None, "league": None}
    rows = list(by_id.values())
    query_token = _token(query)
    exact = [row for row in rows if query_token and any(_token(alias) == query_token for alias in row["aliases"])]
    return {"query": query, "candidates": rows, "exact": exact[0] if len(exact) == 1 else None,
            "status": "EXACT" if len(exact) == 1 else "AMBIGUOUS" if len(exact) > 1 else "NOT_FOUND"}


def parse_team_detail(text):
    data = assignments(text)
    summary = data.get("teamSummary")
    league = data.get("arrLeague")
    players = data.get("teamPlayers") or []
    if not isinstance(summary, list) or len(summary) < 15:
        raise ValueError("TITAN_TEAM_SUMMARY_SCHEMA")
    aliases = [summary[i] for i in (1, 2, 3, 4, 5, 6) if i < len(summary) and summary[i]]
    roster = []
    for row in players:
        if not isinstance(row, list) or len(row) < 10:
            continue
        roster.append({"player_id": str(row[0]), "name_zh": row[1], "name_tw": row[2],
                       "name_en": row[3], "number": row[7], "position": row[8], "birth_date": row[9],
                       "height_cm": row[10] if len(row) > 10 else None,
                       "weight_kg": row[11] if len(row) > 11 else None})
    return {"team_id": str(summary[0]), "name_zh": summary[1], "name_tw": summary[2],
            "name_en": summary[3], "aliases": list(dict.fromkeys(aliases)),
            "league_id": str(league[0]) if isinstance(league, list) and league else None,
            "league_name": league[1] if isinstance(league, list) and len(league) > 1 else None,
            "season": league[4] if isinstance(league, list) and len(league) > 4 else None,
            "roster": roster, "source_last_update": data.get("teamLastUpdateTime")}


def parse_league_teams(text, league_family=None):
    """Parse an authoritative Titan league asset into a stable membership."""
    data = assignments(text)
    league = data.get("arrLeague")
    teams = data.get("arrTeam")
    if not isinstance(league, list) or len(league) < 5:
        raise ValueError("TITAN_LEAGUE_SCHEMA")
    if not isinstance(teams, list) or not teams:
        raise ValueError("TITAN_LEAGUE_TEAM_LIST_EMPTY")
    result = []
    for row in teams:
        if not isinstance(row, list) or len(row) < 4 or _int(row[0]) is None:
            continue
        aliases = [str(value).strip() for value in row[1:7] if value]
        result.append({
            "league_family": str(league_family or league[7] or league[3]).upper(),
            "league_id": str(league[0]), "league_name_zh": league[1],
            "league_name_en": league[3], "season": str(league[4]),
            "titan_team_id": str(int(row[0])), "name_zh": row[1],
            "name_tw": row[2] if len(row) > 2 else None,
            "name_en": row[3] if len(row) > 3 else None,
            "aliases": list(dict.fromkeys(aliases)),
        })
    if not result:
        raise ValueError("TITAN_LEAGUE_TEAM_LIST_INVALID")
    return result


def _season_for(league_id, tip_at):
    tip = datetime.fromisoformat(str(tip_at).replace("Z", "+00:00")).astimezone(BJ)
    if str(league_id) == "2":
        return str(tip.year)
    start = tip.year if tip.month >= 7 else tip.year - 1
    return f"{start}-{start + 1}"


def _phase_code(league_id, match_kind):
    if str(league_id) in ("1", "2"):
        return {1: "REGULAR_SEASON", 2: "POSTSEASON", 3: "PRESEASON"}.get(
            match_kind, "SOURCE_KIND:" + str(match_kind))
    if str(league_id) == "7" and match_kind == -1:
        return "EUROLEAGUE_ALL_STAGES"
    return "SOURCE_KIND:" + str(match_kind)


def parse_team_schedule(text):
    rows = assignments(text).get("teamPageData")
    if not isinstance(rows, list):
        raise ValueError("TITAN_TEAM_SCHEDULE_SCHEMA")
    result = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 20:
            continue
        home_score, away_score = _strip_score(row[6])
        half_home, half_away = _strip_score(row[7])
        try:
            tip_bj = datetime.strptime(str(row[3]), "%Y/%m/%d %H:%M").replace(tzinfo=BJ)
        except ValueError:
            continue
        state = _int(row[19])
        result.append({"match_id": str(row[0]), "league_id": str(row[1]), "league": row[8],
                       "league_en": row[10], "tip_at": tip_bj.astimezone(timezone.utc).isoformat(),
                       "tip_time_bj": tip_bj.isoformat(), "home_team_id": str(row[4]),
                       "away_team_id": str(row[5]), "home_name": row[11], "home_name_en": row[13],
                       "away_name": row[14], "away_name_en": row[16], "home_score": home_score,
                       "away_score": away_score, "half_home": half_home, "half_away": half_away,
                       "match_kind": _int(row[17]), "has_analysis": bool(row[18]),
                       "source_state": state,
                       "status": "FINAL" if state == -1 and home_score is not None else
                                 "CANCELED" if state == -4 else "SCHEDULED"})
    return result


def parse_period_scores(page_html):
    block = re.search(r'<span[^>]+id=["\']scoreData["\'][^>]*>(.*?)</span>', str(page_html or ""), re.I | re.S)
    if not block:
        return None
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", block.group(1), re.I | re.S)
    numeric = []
    for row in rows[1:]:
        values = [int(x) for x in re.findall(r"<td[^>]*>\s*(\d+)\s*</td>", row, re.I)]
        if values:
            numeric.append(values)
    if len(numeric) < 2 or len(numeric[0]) != len(numeric[1]) or len(numeric[0]) < 6:
        return None
    # Last two columns are half-time and full-time; preceding values are Q1-Q4/OT.
    return {"home_periods": numeric[0][:-2], "away_periods": numeric[1][:-2],
            "half_home": numeric[0][-2], "half_away": numeric[1][-2],
            "home_score": numeric[0][-1], "away_score": numeric[1][-1]}


def _team_box(part):
    rows = str(part or "").split("!")
    if len(rows) < 2:
        return None
    total = rows[-2].split("^")
    if len(total) < 16:
        return None
    fields = {"MIN": _float(total[0]), "FGM": _float(total[1]), "FGA": _float(total[2]),
              "3PM": _float(total[3]), "3PA": _float(total[4]), "FTM": _float(total[5]),
              "FTA": _float(total[6]), "ORB": _float(total[7]), "DRB": _float(total[8]),
              "REB": _float(total[9]), "AST": _float(total[10]), "PF": _float(total[11]),
              "STL": _float(total[12]), "TOV": _float(total[13]), "BLK": _float(total[14]),
              "PTS": _float(total[15])}
    required = ("FGA", "FTA", "ORB", "TOV")
    if all(fields[name] is not None for name in required):
        fields["possessions_estimate"] = fields["FGA"] + 0.44 * fields["FTA"] - fields["ORB"] + fields["TOV"]
    else:
        fields["possessions_estimate"] = None
    return fields


def parse_player_box_rows(part):
    """Parse Titan's player rows from one side of a ``tech`` payload.

    The penultimate ``!`` row is the team total and the final row is a
    percentage summary.  Player rows have a stable 27-field contract in the
    public JavaScript asset.  Short/unknown rows are ignored instead of being
    imputed so a partial league can safely fall back to team-level evidence.
    """
    result = []
    for raw in str(part or "").split("!")[:-2]:
        values = raw.split("^")
        if len(values) < 24 or _int(values[0]) is None:
            continue
        result.append({
            "player_id": str(int(values[0])),
            "name_zh": values[1] or None,
            "name_tw": values[2] or None,
            "name_en": values[3] or None,
            "position": values[5] or None,
            "MIN": _float(values[6]),
            "FGM": _float(values[7]), "FGA": _float(values[8]),
            "3PM": _float(values[9]), "3PA": _float(values[10]),
            "FTM": _float(values[11]), "FTA": _float(values[12]),
            "ORB": _float(values[13]), "DRB": _float(values[14]),
            "REB": _float(values[15]), "AST": _float(values[16]),
            "PF": _float(values[17]), "STL": _float(values[18]),
            "TOV": _float(values[19]), "BLK": _float(values[20]),
            "PTS": _float(values[21]),
            "starter": _int(values[22]),
            "display_name": values[23] or None,
            "plus_minus": _float(values[24]) if len(values) > 24 else None,
            "jersey_number": values[25] if len(values) > 25 and values[25] else None,
            "image_path": values[26] if len(values) > 26 and values[26] else None,
        })
    return result


def parse_box_score_blob(text):
    parts = str(text or "").split("$")
    if len(parts) < 3:
        raise ValueError("TITAN_BOX_SCORE_SCHEMA")
    home, away = _team_box(parts[1]), _team_box(parts[2])
    team_ids = []
    if len(parts) > 3:
        for row in parts[3].split("!")[:2]:
            first = row.split("^")[0]
            if _int(first) is not None:
                team_ids.append(str(int(first)))
    complete = bool(home and away and home.get("possessions_estimate") and away.get("possessions_estimate"))
    return {"home": home, "away": away,
            "home_players": parse_player_box_rows(parts[1]),
            "away_players": parse_player_box_rows(parts[2]),
            "team_ids": team_ids,
            "pace_level": "LEVEL_B" if complete else "LEVEL_D",
            "pace_source": "DERIVED_BOX_SCORE" if complete else "UNAVAILABLE",
            "game_possessions_estimate": ((home["possessions_estimate"] + away["possessions_estimate"]) / 2)
                                         if complete else None,
            "formula": "FGA + 0.44 * FTA - ORB + TOV"}


def merge_reference_history(existing, supplemental, events):
    """Merge Titan facts without multiplying an existing mirrored game.

    The cross-provider event IDs are intentionally different.  Duplicate
    detection therefore uses only a current canonical target team, canonical
    competition, target/opponent final scores, and a six-hour tip window.
    Unconnected or cross-competition rows never enter the model history.
    """
    merged = list(existing or [])
    # A source team can appear in more than one competition over the
    # accumulated store.  Keep the full set instead of letting the last event
    # overwrite the earlier competition label.
    targets = defaultdict(set)
    for event in events or []:
        key = event.get("competition_key") or competition_key(event.get("league"), event.get("gender"))
        for field in ("team1_id", "team2_id"):
            if event.get(field):
                targets[str(event[field])].add(key)
    observations = defaultdict(list)
    for game in merged:
        game_key = game.get("competition_key") or competition_key(game.get("league"), game.get("gender"))
        game_teams = {str(game.get("team1_id")), str(game.get("team2_id"))}
        for target in game_teams.intersection(targets):
            wanted_keys = targets[target]
            if game_key not in wanted_keys:
                continue
            home = str(game.get("team1_id")) == target
            target_score = game.get("score1_full") if home else game.get("score2_full")
            opponent_score = game.get("score2_full") if home else game.get("score1_full")
            try:
                tip = datetime.fromisoformat(str(game.get("tip_at")).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            observations[(target, game_key, target_score, opponent_score)].append(tip)
    audit = Counter(candidates=len(supplemental or []))
    for game in supplemental or []:
        linked = []
        game_key = game.get("competition_key") or competition_key(game.get("league"), game.get("gender"))
        game_teams = {str(game.get("team1_id")), str(game.get("team2_id"))}
        for target in game_teams.intersection(targets):
            if game_key in targets[target]:
                linked.append(target)
            else:
                audit["competition_mismatch"] += 1
        if not linked:
            audit["unconnected_or_mismatched"] += 1
            continue
        try:
            tip = datetime.fromisoformat(str(game.get("tip_at")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            audit["invalid_tip"] += 1
            continue
        duplicate = False
        new_observations = []
        for target in linked:
            home = str(game.get("team1_id")) == target
            target_score = game.get("score1_full") if home else game.get("score2_full")
            opponent_score = game.get("score2_full") if home else game.get("score1_full")
            observation_key = (target, game_key, target_score, opponent_score)
            if any(abs((tip - old_tip).total_seconds()) <= 21600
                   for old_tip in observations.get(observation_key, ())):
                duplicate = True
                break
            new_observations.append((observation_key, tip))
        if duplicate:
            audit["mirrored_duplicate"] += 1
            continue
        merged.append(game)
        for observation_key, observation_tip in new_observations:
            observations[observation_key].append(observation_tip)
        audit["added"] += 1
    return merged, dict(audit)


class TitanHistoryStore:
    def __init__(self, root):
        self.root = Path(root)
        self.raw_root = self.root / "raw"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "titan007_history.sqlite"
        self.db = sqlite3.connect(self.db_path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self._schema()

    def _schema(self):
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS source_snapshot(
          snapshot_id TEXT PRIMARY KEY, url TEXT NOT NULL, captured_at TEXT NOT NULL,
          sha256 TEXT NOT NULL, byte_count INTEGER NOT NULL, content_type TEXT,
          raw_path TEXT NOT NULL, entity_type TEXT, entity_id TEXT);
        CREATE TABLE IF NOT EXISTS team(
          titan_team_id TEXT PRIMARY KEY, name_zh TEXT, name_tw TEXT, name_en TEXT,
          league_id TEXT, league_name TEXT, season TEXT, source_last_update TEXT,
          latest_snapshot_id TEXT, roster_json TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS team_alias(
          titan_team_id TEXT NOT NULL, alias TEXT NOT NULL, normalized_alias TEXT NOT NULL,
          captured_at TEXT NOT NULL, source_snapshot_id TEXT NOT NULL,
          PRIMARY KEY(titan_team_id, normalized_alias, source_snapshot_id));
        CREATE TABLE IF NOT EXISTS team_mapping(
          canonical_team_id TEXT NOT NULL, raw_team_name TEXT NOT NULL,
          titan_team_id TEXT, status TEXT NOT NULL, candidates_json TEXT NOT NULL,
          observed_at TEXT NOT NULL, PRIMARY KEY(canonical_team_id, observed_at));
        CREATE TABLE IF NOT EXISTS match_history(
          titan_match_id TEXT PRIMARY KEY, league_id TEXT, league TEXT, tip_at TEXT,
          home_titan_team_id TEXT, away_titan_team_id TEXT, home_name TEXT, away_name TEXT,
          home_score INTEGER, away_score INTEGER, half_home INTEGER, half_away INTEGER,
          periods_home_json TEXT, periods_away_json TEXT, match_kind INTEGER,
          source_state INTEGER, status TEXT, source_snapshot_id TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS box_score(
          titan_match_id TEXT PRIMARY KEY, home_json TEXT, away_json TEXT,
          pace_level TEXT, pace_source TEXT, possessions REAL, formula TEXT,
          source_snapshot_id TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS capture_run(
          run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, requested_team_count INTEGER,
          mapped_team_count INTEGER, schedule_row_count INTEGER, box_score_count INTEGER,
          history_row_count INTEGER, status TEXT, audit_json TEXT);
        CREATE TABLE IF NOT EXISTS league_team_membership(
          league_family TEXT NOT NULL, league_id TEXT NOT NULL, season TEXT NOT NULL,
          titan_team_id TEXT NOT NULL, name_zh TEXT, name_tw TEXT, name_en TEXT,
          aliases_json TEXT NOT NULL, source_snapshot_id TEXT NOT NULL,
          captured_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
          PRIMARY KEY(league_family, season, titan_team_id));
        CREATE TABLE IF NOT EXISTS team_game_stat(
          titan_match_id TEXT NOT NULL, titan_team_id TEXT NOT NULL,
          opponent_titan_team_id TEXT NOT NULL, league_id TEXT NOT NULL,
          season TEXT NOT NULL, match_kind INTEGER, tip_at TEXT NOT NULL,
          is_home INTEGER NOT NULL, won INTEGER,
          fgm REAL, fga REAL, three_pm REAL, three_pa REAL, ftm REAL, fta REAL,
          orb REAL, drb REAL, reb REAL, ast REAL, pf REAL, stl REAL, tov REAL,
          blk REAL, pts REAL, possessions REAL, opponent_possessions REAL,
          pace_level TEXT NOT NULL, source_snapshot_id TEXT NOT NULL,
          updated_at TEXT NOT NULL, PRIMARY KEY(titan_match_id, titan_team_id));
        CREATE TABLE IF NOT EXISTS team_season_stat(
          league_id TEXT NOT NULL, season TEXT NOT NULL, phase_code TEXT NOT NULL,
          titan_team_id TEXT NOT NULL, games INTEGER NOT NULL,
          distinct_opponents INTEGER NOT NULL, wins INTEGER NOT NULL, losses INTEGER NOT NULL,
          fgm REAL, fga REAL, three_pm REAL, three_pa REAL, ftm REAL, fta REAL,
          orb REAL, drb REAL, reb REAL, ast REAL, pf REAL, stl REAL, tov REAL,
          blk REAL, pts REAL, possessions REAL, possessions_games INTEGER NOT NULL,
          avg_fga REAL, avg_three_pa REAL, avg_fta REAL, avg_orb REAL, avg_tov REAL,
          avg_pts REAL, avg_possessions REAL, three_pa_rate REAL, ft_rate REAL,
          efg_pct REAL, evidence_level TEXT NOT NULL, cutoff_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(league_id, season, phase_code, titan_team_id));
        CREATE INDEX IF NOT EXISTS idx_team_game_stat_team_tip
          ON team_game_stat(titan_team_id, tip_at);
        CREATE INDEX IF NOT EXISTS idx_team_game_stat_lookup
          ON team_game_stat(titan_team_id, league_id, season, match_kind, tip_at DESC);
        CREATE INDEX IF NOT EXISTS idx_team_game_stat_league_tip
          ON team_game_stat(league_id, season, match_kind, tip_at DESC);
        CREATE INDEX IF NOT EXISTS idx_team_season_stat_lookup
          ON team_season_stat(league_id, season, titan_team_id);
        CREATE INDEX IF NOT EXISTS idx_match_history_league_tip_status
          ON match_history(league_id, tip_at DESC, status);
        CREATE INDEX IF NOT EXISTS idx_match_history_home_tip
          ON match_history(home_titan_team_id, tip_at DESC);
        CREATE INDEX IF NOT EXISTS idx_match_history_away_tip
          ON match_history(away_titan_team_id, tip_at DESC);
        CREATE INDEX IF NOT EXISTS idx_team_alias_normalized
          ON team_alias(normalized_alias, titan_team_id);
        CREATE INDEX IF NOT EXISTS idx_team_mapping_latest
          ON team_mapping(canonical_team_id, observed_at DESC, status);
        CREATE INDEX IF NOT EXISTS idx_source_snapshot_entity_time
          ON source_snapshot(entity_type, entity_id, captured_at DESC);
        CREATE INDEX IF NOT EXISTS idx_source_snapshot_url_time
          ON source_snapshot(url, captured_at DESC);
        """)
        ensure_feature_schema(self.db)
        self.db.commit()

    def snapshot(self, url, blob, content_type, entity_type, entity_id, captured_at):
        digest = _sha(blob)
        folder = self.raw_root / captured_at[:10].replace("-", "")
        folder.mkdir(parents=True, exist_ok=True)
        # Entity ids are database identities and may intentionally contain
        # namespace separators such as ``:``.  They are invalid in Windows
        # filenames, so encode only the filename component and keep the exact
        # original id in ``source_snapshot.entity_id`` for provenance.
        file_entity_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(entity_id)).strip("_") or "unknown"
        path = folder / f"{entity_type}_{file_entity_id[:140]}_{digest[:16]}.raw"
        if not path.exists():
            path.write_bytes(blob)
        elif path.read_bytes() != blob:
            raise ValueError("IMMUTABLE_RAW_SNAPSHOT_CONFLICT")
        snapshot_id = digest[:24]
        self.db.execute(
            "INSERT OR IGNORE INTO source_snapshot"
            "(snapshot_id,url,captured_at,sha256,byte_count,content_type,raw_path,entity_type,entity_id,"
            "request_at,response_at,http_status,parser_version,field_contract_version) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (snapshot_id, url, captured_at, digest, len(blob), content_type,
             str(path), entity_type, str(entity_id), captured_at, captured_at, 200,
             "titan-history-adapter-v4", "titan-public-resource-v1"))
        return snapshot_id, str(path), digest

    def close(self):
        self.db.commit()
        self.db.close()


def _fetch(item, timeout=20):
    key, url, referer = item
    captured_at = _stamp()
    if curl_requests is None:
        return {"key": key, "url": url, "ok": False, "captured_at": captured_at,
                "error": "CURL_CFFI_NOT_INSTALLED"}
    policy = RetryPolicy(attempts=4, delays=(2.0, 4.0, 8.0))
    def operation():
            response = curl_requests.get(url, impersonate="chrome", timeout=timeout,
                                         headers={"Referer": referer, "Accept-Language": "zh-CN,zh;q=0.9"})
            blob = bytes(response.content)
            if response.status_code != 200:
                raise ValueError(f"HTTP_{response.status_code}")
            if not blob or len(blob) > MAX_BYTES:
                raise ValueError("EMPTY_OR_OVERSIZE_RESPONSE")
            return {"status": response.status_code, "content_type": response.headers.get("content-type"),
                    "blob": blob, "text": blob.decode("utf-8-sig", "strict")}
    try:
        value, attempts = request_with_retry(
            operation, url=url, policy=policy,
            validate=lambda item: bool(item.get("blob")), status_of=lambda item: item.get("status"))
        return {"key": key, "url": url, "ok": True, "captured_at": captured_at,
                **value, "attempts": attempts, "attempt_count": len(attempts)}
    except Exception as exc:  # exact failure retained in source health
        attempts = getattr(exc, "retry_attempts", [])
        return {"key": key, "url": url, "ok": False, "captured_at": captured_at,
                "error": type(exc).__name__ + ": " + str(exc),
                "attempts": attempts, "attempt_count": len(attempts)}


def _batch(items, workers=6, timeout=20):
    with ThreadPoolExecutor(max_workers=max(1, min(6, int(workers)))) as pool:
        return list(pool.map(lambda item: _fetch(item, timeout), items))


def _cached_response(store, item, ttl_seconds):
    """Reuse a recent immutable raw response instead of refetching it."""
    key, url, referer = item
    row = store.db.execute(
        "SELECT raw_path,captured_at,sha256,content_type FROM source_snapshot "
        "WHERE url=? ORDER BY captured_at DESC LIMIT 1", (url,)
    ).fetchone()
    if not row:
        return None
    raw_path, captured_at, digest, content_type = row
    try:
        observed = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
        if age < 0 or age > float(ttl_seconds):
            return None
        path = Path(raw_path)
        if not path.is_file():
            return None
        blob = path.read_bytes()
        if _sha(blob) != str(digest):
            return None
        return {"key": key, "url": url, "ok": True, "cached": True,
                "captured_at": captured_at, "status": 200,
                "content_type": content_type, "blob": blob,
                "text": blob.decode("utf-8-sig", "strict"),
                "attempts": [], "attempt_count": 0,
                "cache_age_seconds": round(age, 3)}
    except (OSError, UnicodeError, TypeError, ValueError):
        return None


def _batch_with_cache(store, items, workers=6, ttl_seconds=0, timeout=20):
    """Return cached responses plus only stale/missing live requests."""
    cached, pending = [], []
    for item in items:
        hit = _cached_response(store, item, ttl_seconds) if ttl_seconds else None
        if hit is None:
            pending.append(item)
        else:
            cached.append(hit)
    return cached + _batch(pending, workers, timeout) if pending else cached


def _capture_foundation_memberships(store, league_families, health, errors, workers):
    memberships = []
    wanted = [str(value).upper() for value in (league_families or [])]
    unknown = sorted(set(wanted) - set(FOUNDATION_LEAGUES))
    if unknown:
        raise ValueError("UNKNOWN_FOUNDATION_LEAGUES:" + ",".join(unknown))
    for family in wanted:
        config = FOUNDATION_LEAGUES[family]
        page = _fetch((f"league_page:{family}", config["page"], BASE + "/index_cn.htm"))
        health.append({k: v for k, v in page.items() if k not in ("blob", "text")})
        if not page.get("ok"):
            errors.append({"key": page["key"], "error": page.get("error")})
            continue
        store.snapshot(page["url"], page["blob"], page.get("content_type"),
                       "league_page", family, page["captured_at"])
        match = re.search(config["asset_pattern"], page["text"], re.I)
        if not match:
            errors.append({"key": page["key"], "error": "LEAGUE_ASSET_NOT_FOUND"})
            continue
        asset_url = urljoin(BASE, html.unescape(match.group(0)))
        asset = _fetch((f"league_asset:{family}", asset_url, config["page"]))
        health.append({k: v for k, v in asset.items() if k not in ("blob", "text")})
        if not asset.get("ok"):
            errors.append({"key": asset["key"], "error": asset.get("error")})
            continue
        snapshot_id, _, _ = store.snapshot(
            asset["url"], asset["blob"], asset.get("content_type"),
            "league_membership", family, asset["captured_at"])
        try:
            rows = parse_league_teams(asset["text"], family)
        except Exception as exc:
            errors.append({"key": asset["key"], "error": str(exc)})
            continue
        seasons = {row["season"] for row in rows}
        for season in seasons:
            store.db.execute(
                "UPDATE league_team_membership SET active=0 WHERE league_family=? AND season=?",
                (family, season))
        for row in rows:
            row["source_snapshot_id"] = snapshot_id
            row["captured_at"] = asset["captured_at"]
            store.db.execute(
                "INSERT OR REPLACE INTO league_team_membership VALUES(?,?,?,?,?,?,?,?,?,?,1)",
                (row["league_family"], row["league_id"], row["season"], row["titan_team_id"],
                 row["name_zh"], row["name_tw"], row["name_en"],
                 json.dumps(row["aliases"], ensure_ascii=False), snapshot_id, asset["captured_at"]))
        memberships.extend(rows)
    return memberships


def _sum(values):
    valid = [float(value) for value in values if value is not None]
    return sum(valid) if valid else None


def _ratio(numerator, denominator):
    return numerator / denominator if numerator is not None and denominator and denominator > 0 else None


def _upsert_selected_team_game_stats(store, matches, tech_data, tech_snapshots, invalid_periods, updated_at):
    rows = []
    for mid, box in tech_data.items():
        match = matches.get(mid)
        if not match or mid in invalid_periods or match.get("status") != "FINAL":
            continue
        sides = [box.get("home"), box.get("away")]
        if not all(isinstance(side, dict) for side in sides):
            continue
        team_ids = [match["home_team_id"], match["away_team_id"]]
        scores = [match.get("home_score"), match.get("away_score")]
        season = _season_for(match["league_id"], match["tip_at"])
        for index, side in enumerate(sides):
            opponent = sides[1 - index]
            won = None if None in scores or scores[0] == scores[1] else int(scores[index] > scores[1 - index])
            values = [side.get(name) for name in ("FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "ORB",
                                                       "DRB", "REB", "AST", "PF", "STL", "TOV", "BLK", "PTS")]
            snapshot = tech_snapshots.get(mid)
            source_snapshot_id = snapshot[0] if snapshot else "UNKNOWN"
            rows.append((mid, team_ids[index], team_ids[1 - index], match["league_id"], season,
                         match.get("match_kind"), match["tip_at"], int(index == 0), won, *values,
                         side.get("possessions_estimate"), opponent.get("possessions_estimate"),
                         box.get("pace_level") or "LEVEL_D", source_snapshot_id,
                         updated_at))
    store.db.executemany(
        "INSERT OR REPLACE INTO team_game_stat VALUES(" + ",".join("?" for _ in range(29)) + ")", rows)
    return len(rows)


def _event_target_phase(event, league_id):
    label = " ".join(str(event.get(key) or "") for key in
                     ("league", "competition_key", "league_family", "raw_event_name")).casefold()
    if str(league_id) in ("1", "2"):
        if any(token in label for token in ("季前", "preseason", "pre-season")):
            return 3, "PRESEASON"
        if any(token in label for token in ("季后", "playoff", "postseason")):
            return 2, "POSTSEASON"
        return 1, "REGULAR_SEASON"
    if str(league_id) == "7":
        return -1, "EUROLEAGUE_ALL_STAGES"
    return 1, "REGULAR_SEASON"


def _special_league_id(event):
    """Resolve only globally unambiguous league labels.

    ``EUROPE_DOMESTIC`` must never be treated as EuroLeague merely because it
    contains the substring ``EURO``; domestic leagues are resolved through
    both mapped Titan team records instead.
    """
    label = " ".join(str(event.get(key) or "") for key in
                     ("league", "competition_key", "league_family")).upper()
    if "WNBA" in label:
        return "2"
    if "NBA" in label and "WNBA" not in label:
        return "1"
    if ("EUROLEAGUE" in label or "EURO LEAGUE" in label or
            str(event.get("league") or "").strip().casefold() in
            ("euro", "euroleague", "欧洲篮球联赛", "欧洲联赛")):
        return "7"
    return None


def _profile_from_rows(rows):
    if not rows:
        return None
    field_columns = {"FGM": "fgm", "FGA": "fga", "3PM": "three_pm", "3PA": "three_pa",
                     "FTM": "ftm", "FTA": "fta", "ORB": "orb", "DRB": "drb", "REB": "reb",
                     "AST": "ast", "PF": "pf", "STL": "stl", "TOV": "tov", "BLK": "blk", "PTS": "pts"}
    fields = tuple(field_columns)
    profiles = []
    for row in rows:
        item = {name: row[column] for name, column in field_columns.items()}
        item["possessions_estimate"] = row["possessions"]
        item["opponent_possessions_estimate"] = row["opponent_possessions"]
        item["opponent_pts"] = row["opponent_pts"]
        profiles.append(item)
    averages = {name: _ratio(_sum(item.get(name) for item in profiles),
                             sum(item.get(name) is not None for item in profiles)) for name in fields}
    pace_values = [((item["possessions_estimate"] + item["opponent_possessions_estimate"]) / 2)
                   for item in profiles if item["possessions_estimate"] is not None and
                   item["opponent_possessions_estimate"] is not None]
    pace = _ratio(sum(pace_values), len(pace_values)) if pace_values else None
    own_points = _sum(item.get("PTS") for item in profiles)
    opponent_points = _sum(item.get("opponent_pts") for item in profiles)
    pace_sum = sum(pace_values) if pace_values else None
    averages.update({
        "games": len(rows), "distinct_opponents": len({row["opponent_titan_team_id"] for row in rows}),
        "possessions_estimate": pace, "offensive_ppp": _ratio(own_points, pace_sum),
        "defensive_ppp": _ratio(opponent_points, pace_sum),
        "first_tip_at": min(row["tip_at"] for row in rows),
        "last_tip_at": max(row["tip_at"] for row in rows),
    })
    return averages


def load_event_foundation_contexts(root, events, mappings, cutoff=None, recent_limit=10):
    """Build cutoff-safe two-team technical profiles without reading raw files.

    Market fields are deliberately absent.  The result is an independent
    Titan box-score challenger that can be compared with a market only after
    the forecast has been frozen.
    """
    cutoff_dt = cutoff if isinstance(cutoff, datetime) else datetime.fromisoformat(
        str(cutoff).replace("Z", "+00:00")) if cutoff else datetime.now(timezone.utc)
    if cutoff_dt.tzinfo is None:
        cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
    db_path = Path(root) / "titan007_history.sqlite"
    if not db_path.exists():
        return {}
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    contexts = {}
    state_cache = {}
    environment_cache = {}
    try:
        for event in events or []:
            canonical_ids = [str(event.get("team1_id") or ""), str(event.get("team2_id") or "")]
            titan_ids = [mappings.get(canonical) for canonical in canonical_ids]
            if not all(titan_ids):
                continue
            league_id = _special_league_id(event)
            if not league_id:
                primary = [db.execute("SELECT league_id FROM team WHERE titan_team_id=?", (tid,)).fetchone()
                           for tid in titan_ids]
                league_ids = [row[0] for row in primary if row and row[0]]
                league_id = league_ids[0] if len(league_ids) == 2 and len(set(league_ids)) == 1 else None
            if not league_id:
                continue
            match_kind, phase_code = _event_target_phase(event, league_id)
            # NBA/WNBA preseason is a phase, not a new league identity.  The
            # foundation profile must reuse regular/postseason rows as well;
            # phase uncertainty is applied by pricing, not by deleting history.
            all_mainstream_phases = str(league_id) in ("1", "2")
            team_profiles = []
            for titan_id in titan_ids:
                if all_mainstream_phases:
                    rows = db.execute(
                        "SELECT g.*,o.pts opponent_pts FROM team_game_stat g "
                        "LEFT JOIN team_game_stat o ON o.titan_match_id=g.titan_match_id AND o.titan_team_id=g.opponent_titan_team_id "
                        "WHERE g.titan_team_id=? AND g.league_id=? AND g.match_kind IN (1,2,3) AND g.tip_at<? "
                        "ORDER BY g.tip_at DESC LIMIT ?",
                        (titan_id, league_id, cutoff_dt.astimezone(timezone.utc).isoformat(),
                         max(1, int(recent_limit)))).fetchall()
                else:
                    rows = db.execute(
                        "SELECT g.*,o.pts opponent_pts FROM team_game_stat g "
                        "LEFT JOIN team_game_stat o ON o.titan_match_id=g.titan_match_id AND o.titan_team_id=g.opponent_titan_team_id "
                        "WHERE g.titan_team_id=? AND g.league_id=? AND g.match_kind=? AND g.tip_at<? "
                        "ORDER BY g.tip_at DESC LIMIT ?",
                        (titan_id, league_id, match_kind, cutoff_dt.astimezone(timezone.utc).isoformat(),
                         max(1, int(recent_limit)))).fetchall()
                profile = _profile_from_rows(rows)
                if profile:
                    profile.update({"titan_team_id": titan_id, "canonical_team_id": canonical_ids[len(team_profiles)]})
                team_profiles.append(profile)
            if not all(team_profiles):
                continue
            profile1, profile2 = team_profiles
            minimum_games = min(profile1["games"], profile2["games"])
            minimum_opponents = min(profile1["distinct_opponents"], profile2["distinct_opponents"])
            pace_values = [profile1.get("possessions_estimate"), profile2.get("possessions_estimate")]
            complete = all(value is not None and value > 0 for value in pace_values)
            ppp_values = [profile1.get("offensive_ppp"), profile1.get("defensive_ppp"),
                          profile2.get("offensive_ppp"), profile2.get("defensive_ppp")]
            complete = complete and all(value is not None and value > 0 for value in ppp_values)
            pace = sum(pace_values) / 2 if complete else None
            team1_ppp = (profile1["offensive_ppp"] + profile2["defensive_ppp"]) / 2 if complete else None
            team2_ppp = (profile2["offensive_ppp"] + profile1["defensive_ppp"]) / 2 if complete else None
            fair_total = pace * (team1_ppp + team2_ppp) if complete else None
            fair_margin = pace * (team1_ppp - team2_ppp) if complete else None
            paper_history_ready = minimum_games >= 8 and minimum_opponents >= 3
            contexts[event["event_id"]] = {
                "source": "TITAN007_TEAM_GAME_STATS", "source_database": str(db_path),
                "cutoff_at": cutoff_dt.astimezone(timezone.utc).isoformat(), "league_id": league_id,
                "phase_code": phase_code, "match_kind": match_kind, "recent_limit": int(recent_limit),
                "team_profiles": team_profiles, "box_score_teams": team_profiles,
                "available_variables": ["FGA", "FTA", "ORB", "TOV", "3PA", "3PM", "PTS"],
                "possessions_verified": bool(complete and paper_history_ready),
                "possessions_level": "LEVEL_B" if complete and paper_history_ready else "LEVEL_D",
                "pace_source": "DERIVED_BOX_SCORE" if complete else "UNAVAILABLE",
                "basic_offense_verified": bool(complete and paper_history_ready),
                "three_point_verified": bool(paper_history_ready and all(p.get("3PA") is not None and p.get("3PM") is not None for p in team_profiles)),
                "foundation_history_ready": paper_history_ready,
                "minimum_games": minimum_games, "minimum_distinct_opponents": minimum_opponents,
                "technical_fair_total": fair_total, "technical_fair_margin_neutral": fair_margin,
                "technical_expected_team1_points": pace * team1_ppp if complete else None,
                "technical_expected_team2_points": pace * team2_ppp if complete else None,
                "technical_line_status": "RESEARCH_CHALLENGER_NEUTRAL_COURT" if complete else "UNAVAILABLE",
                "home_adjustment": None,
                "market_inputs_used": False,
            }
            try:
                advanced = build_matchup(
                    db, event["event_id"], league_id,
                    _season_for(league_id, event.get("tip_at") or cutoff_dt),
                    match_kind, phase_code, titan_ids[0], titan_ids[1], cutoff_dt,
                    recent_limit=max(20, int(recent_limit)),
                    state_cache=state_cache, environment_cache=environment_cache)
            except Exception as exc:
                advanced = None
                contexts[event["event_id"]]["advanced_feature_error"] = type(exc).__name__ + ": " + str(exc)
            if advanced:
                ensemble = advanced["ensemble"]
                advanced_min_games = min(state.get("games", 0) for state in advanced["team_states"])
                advanced_min_opponents = min(state.get("distinct_opponents", 0) for state in advanced["team_states"])
                advanced_ready = advanced_min_games >= 8 and advanced_min_opponents >= 3
                contexts[event["event_id"]].update({
                    "team1_titan_id": titan_ids[0], "team2_titan_id": titan_ids[1],
                    "technical_fair_total": ensemble["fair_total"],
                    "technical_fair_margin_neutral": ensemble["expected_margin"],
                    "technical_expected_team1_points": ensemble["expected_team1_score"],
                    "technical_expected_team2_points": ensemble["expected_team2_score"],
                    "fair_handicap_team1": ensemble["fair_handicap_team1"],
                    "technical_line_status": "CAPABILITY_WEIGHTED_RESEARCH_CHALLENGER",
                    "minimum_games": advanced_min_games,
                    "minimum_distinct_opponents": advanced_min_opponents,
                    "foundation_history_ready": advanced_ready,
                    "possessions_verified": advanced_ready,
                    "basic_offense_verified": advanced_ready,
                    "feature_hash": advanced["feature_hash"],
                    "source_max_tip_at": advanced["source_max_tip_at"],
                    "team_states": advanced["team_states"],
                    "league_environment": advanced["league_environment"],
                    "model_b": advanced["model_b"], "model_c": advanced["model_c"],
                    "ensemble": advanced["ensemble"], "top_factors": advanced["top_factors"],
                    "market_inputs_used": False,
                })
    finally:
        db.close()
    return contexts


def _rebuild_team_stat_tables(store, cutoff_dt, league_ids):
    """Normalize cached box scores and aggregate in memory once per run.

    This avoids repeated JSON/file reads for every team and keeps foundation
    refresh time bounded even when two seasons of NBA data are present.
    """
    league_ids = {str(value) for value in league_ids}
    placeholders = ",".join("?" for _ in league_ids)
    if not placeholders:
        return {"team_game_stats": 0, "team_season_stats": 0}
    rows = store.db.execute(
        "SELECT m.titan_match_id,m.league_id,m.tip_at,m.match_kind,m.home_titan_team_id,"
        "m.away_titan_team_id,m.home_score,m.away_score,b.home_json,b.away_json,b.pace_level,"
        "b.source_snapshot_id FROM match_history m JOIN box_score b USING(titan_match_id) "
        f"WHERE m.status='FINAL' AND m.tip_at<? AND m.league_id IN ({placeholders})",
        (cutoff_dt.astimezone(timezone.utc).isoformat(), *sorted(league_ids))).fetchall()
    updated_at = _stamp()
    game_rows = []
    for mid, league_id, tip_at, match_kind, home_id, away_id, home_score, away_score, home_json, away_json, pace_level, snapshot_id in rows:
        try:
            sides = [json.loads(home_json), json.loads(away_json)]
        except (TypeError, json.JSONDecodeError):
            continue
        if not all(isinstance(side, dict) for side in sides):
            continue
        season = _season_for(league_id, tip_at)
        for index, side in enumerate(sides):
            opponent = sides[1 - index]
            team_id, opponent_id = (home_id, away_id) if index == 0 else (away_id, home_id)
            score, opponent_score = (home_score, away_score) if index == 0 else (away_score, home_score)
            won = None if score is None or opponent_score is None or score == opponent_score else int(score > opponent_score)
            values = [side.get(name) for name in ("FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "ORB",
                                                       "DRB", "REB", "AST", "PF", "STL", "TOV", "BLK", "PTS")]
            game_rows.append((mid, team_id, opponent_id, league_id, season, match_kind, tip_at,
                              int(index == 0), won, *values, side.get("possessions_estimate"),
                              opponent.get("possessions_estimate"), pace_level, snapshot_id, updated_at))
    store.db.executemany(
        "INSERT OR REPLACE INTO team_game_stat VALUES(" + ",".join("?" for _ in range(29)) + ")",
        game_rows)

    # This is a derived cache, not an immutable fact ledger. Rebuild only the
    # requested leagues so renamed phase buckets cannot leave stale rows.
    store.db.execute(
        f"DELETE FROM team_season_stat WHERE league_id IN ({placeholders})",
        tuple(sorted(league_ids)))
    grouped = {}
    for row in game_rows:
        league_id, season, team_id, match_kind = row[3], row[4], row[1], row[5]
        for phase in ("ALL_PHASES_AUDIT_ONLY", _phase_code(league_id, match_kind)):
            grouped.setdefault((league_id, season, phase, team_id), []).append(row)
    aggregate_rows = []
    for (league_id, season, phase, team_id), items in grouped.items():
        games = len(items)
        wins = sum(item[8] == 1 for item in items)
        losses = sum(item[8] == 0 for item in items)
        totals = [_sum(item[column] for item in items) for column in range(9, 24)]
        fgm, fga, three_pm, three_pa, ftm, fta, orb, drb, reb, ast, pf, stl, tov, blk, pts = totals
        possessions = _sum(item[24] for item in items)
        possessions_games = sum(item[24] is not None for item in items)
        evidence_level = "LEVEL_B" if possessions_games == games and games else "LEVEL_C" if possessions_games else "LEVEL_D"
        aggregate_rows.append((
            league_id, season, phase, team_id, games, len({item[2] for item in items}), wins, losses,
            *totals, possessions, possessions_games,
            _ratio(fga, games), _ratio(three_pa, games), _ratio(fta, games), _ratio(orb, games),
            _ratio(tov, games), _ratio(pts, games), _ratio(possessions, possessions_games),
            _ratio(three_pa, fga), _ratio(fta, fga),
            _ratio((fgm or 0) + 0.5 * (three_pm or 0), fga), evidence_level,
            cutoff_dt.astimezone(timezone.utc).isoformat(), updated_at))
    store.db.executemany(
        "INSERT OR REPLACE INTO team_season_stat VALUES(" + ",".join("?" for _ in range(38)) + ")",
        aggregate_rows)
    return {"team_game_stats": len(game_rows), "team_season_stats": len(aggregate_rows)}


def _write_foundation_manifest(store, root, league_families, cutoff_dt):
    families = sorted({str(value).upper() for value in league_families or []})
    if not families:
        return None
    placeholders = ",".join("?" for _ in families)
    rows = store.db.execute(
        "SELECT m.league_family,m.league_id,m.season,m.titan_team_id,m.name_zh,m.name_tw,m.name_en,"
        "t.roster_json,COUNT(DISTINCT g.titan_match_id) "
        "FROM league_team_membership m LEFT JOIN team t USING(titan_team_id) "
        "LEFT JOIN team_game_stat g ON g.titan_team_id=m.titan_team_id AND g.league_id=m.league_id "
        f"WHERE m.active=1 AND m.league_family IN ({placeholders}) "
        "GROUP BY m.league_family,m.league_id,m.season,m.titan_team_id,m.name_zh,m.name_tw,m.name_en,t.roster_json "
        "ORDER BY m.league_family,m.titan_team_id", tuple(families)).fetchall()
    grouped = {family: [] for family in families}
    for family, league_id, season, team_id, name_zh, name_tw, name_en, roster_json, games in rows:
        try:
            roster_count = len(json.loads(roster_json or "[]"))
        except (TypeError, json.JSONDecodeError):
            roster_count = 0
        grouped[family].append({
            "titan_team_id": team_id, "league_id": league_id, "season": season,
            "name_zh": name_zh, "name_tw": name_tw, "name_en": name_en,
            "roster_count": roster_count, "box_score_games": games,
        })
    document = {
        "generated_at": _stamp(), "cutoff_at": cutoff_dt.astimezone(timezone.utc).isoformat(),
        "database": str(store.db_path),
        "counts": {family: len(teams) for family, teams in grouped.items()},
        "teams": grouped,
        "phase_policy": {
            "NBA_WNBA": ["REGULAR_SEASON", "POSTSEASON", "PRESEASON"],
            "EUROLEAGUE": ["EUROLEAGUE_ALL_STAGES"],
            "ALL_PHASES_AUDIT_ONLY": "审计汇总，禁止直接作为模型同阶段样本",
        },
        "ledger_modified": False,
    }
    path = Path(root) / "foundation_manifest.json"
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def update_history_database(events, root, cutoff=None, years=None, boxscore_limit=10, workers=6,
                            foundation_leagues=None, all_league_boxscores=False):
    """Incrementally capture relevant teams and return verified fallback facts."""
    cutoff_dt = cutoff if isinstance(cutoff, datetime) else datetime.fromisoformat(str(cutoff).replace("Z", "+00:00")) if cutoff else datetime.now(timezone.utc)
    if cutoff_dt.tzinfo is None:
        cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
    years = list(dict.fromkeys(years or [cutoff_dt.astimezone(BJ).year, cutoff_dt.astimezone(BJ).year - 1]))
    store = TitanHistoryStore(root)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:8]
    started = _stamp()
    health, errors = [], []
    teams = {}
    event_teams = {}
    for event in events:
        for side in ("team1", "team2"):
            canonical = str(event.get(side + "_id") or "")
            name = str(event.get(side + "_name") or "").strip()
            if not canonical or not name:
                continue
            teams.setdefault(canonical, {"canonical_team_id": canonical, "name": name,
                                         "league": event.get("league")})
            event_teams.setdefault(event.get("event_id"), {})[side] = canonical
    try:
        memberships = _capture_foundation_memberships(
            store, foundation_leagues, health, errors, workers) if foundation_leagues else []
        for member in memberships:
            canonical = "titan-team:" + member["titan_team_id"]
            teams.setdefault(canonical, {
                "canonical_team_id": canonical,
                "name": member["name_zh"] or member["name_en"],
                "league": member["league_name_zh"],
                "seed_titan_id": member["titan_team_id"],
            })
        # Reuse the latest successful canonical-to-Titan mapping from the
        # existing feature store.  Mapping is identity evidence, not market
        # freshness, so reusing an exact mapping does not weaken any quote or
        # pricing gate; it removes a full team-search crawl on every run.
        cached_mappings = {}
        for cached in store.db.execute(
            "SELECT canonical_team_id,titan_team_id,status FROM team_mapping "
            "WHERE titan_team_id IS NOT NULL ORDER BY observed_at DESC"
        ).fetchall():
            canonical, titan_id, status = cached
            if canonical not in cached_mappings and status == "EXACT":
                cached_mappings[canonical] = str(titan_id)
        mapping_cache_hits = 0
        search_items = []
        search_key_canonical = {}
        for canonical, team in teams.items():
            if team.get("seed_titan_id"):
                continue
            cached_titan_id = cached_mappings.get(canonical)
            if cached_titan_id:
                team["seed_titan_id"] = cached_titan_id
                mapping_cache_hits += 1
                continue
            team["search_names"] = _team_search_queries(team["name"])
            for index, search_name in enumerate(team["search_names"]):
                key = f"search:{canonical}:{index}"
                url = f"{BASE}/cn/aspx/Search_Team.aspx?str1={quote(search_name)}"
                search_items.append((key, url, BASE + "/index_cn.htm"))
                search_key_canonical[key] = canonical
        mappings = {}
        for canonical, team in teams.items():
            if not team.get("seed_titan_id"):
                continue
            mappings[canonical] = team["seed_titan_id"]
            store.db.execute("INSERT OR REPLACE INTO team_mapping VALUES(?,?,?,?,?,?)",
                             (canonical, team["name"], team["seed_titan_id"], "DIRECT_LEAGUE_MEMBERSHIP",
                              "[]", started))
        search_outcomes = defaultdict(list)
        for row in _batch(search_items, workers):
            health.append({k: v for k, v in row.items() if k not in ("blob", "text")})
            canonical = search_key_canonical[row["key"]]
            if not row.get("ok"):
                result = {"query": row["key"], "candidates": [], "exact": None, "status": "FETCH_FAILED"}
            else:
                store.snapshot(row["url"], row["blob"], row.get("content_type"), "team_search", canonical, row["captured_at"])
                query = teams[canonical]["search_names"][int(row["key"].rsplit(":", 1)[1])]
                result = parse_search_response(row["text"], query)
            search_outcomes[canonical].append({"result": result, "captured_at": row["captured_at"]})

        # Multiple reviewed aliases are allowed to hit the same Titan row, but
        # different exact TeamIDs remain ambiguous and are never guessed.
        for canonical, attempts in search_outcomes.items():
            exact_rows = [a["result"]["exact"] for a in attempts if a["result"].get("exact")]
            exact_ids = {str(row["team_id"]) for row in exact_rows}
            if len(exact_ids) == 1:
                titan_id = next(iter(exact_ids))
                status = "EXACT"
            elif len(exact_ids) > 1:
                titan_id = None
                status = "AMBIGUOUS"
            else:
                titan_id = None
                status = ("FETCH_FAILED" if attempts and
                          all(a["result"].get("status") == "FETCH_FAILED" for a in attempts)
                          else "NOT_FOUND")
            candidates = []
            for attempt in attempts:
                candidates.extend(attempt["result"].get("candidates") or [])
            # Keep the full candidate audit, de-duplicated by TeamID/name.
            unique_candidates = {}
            for candidate in candidates:
                key = (str(candidate.get("team_id") or ""), str(candidate.get("name") or ""))
                unique_candidates[key] = candidate
            captured_at = max((a["captured_at"] for a in attempts), default=started)
            mappings[canonical] = titan_id
            store.db.execute("INSERT OR REPLACE INTO team_mapping VALUES(?,?,?,?,?,?)",
                             (canonical, teams[canonical]["name"], titan_id, status,
                              json.dumps(list(unique_candidates.values()), ensure_ascii=False), captured_at))

        titan_to_canonical = {}
        for cid, tid in mappings.items():
            if tid and (tid not in titan_to_canonical or not cid.startswith("titan-team:")):
                titan_to_canonical[tid] = cid
        detail_items = [("detail:" + tid, f"{BASE}/jsData/teamInfo/teamDetail/td{tid}.js",
                         f"{BASE}/cn/Team/Summary.aspx?TeamID={tid}") for tid in sorted(set(titan_to_canonical))]
        details = {}
        # Team metadata changes slowly. Reuse a verified snapshot for one day;
        # a live refresh happens automatically when the TTL expires.
        for row in _batch_with_cache(store, detail_items, workers, ttl_seconds=24 * 3600):
            health.append({k: v for k, v in row.items() if k not in ("blob", "text")})
            if not row.get("ok"):
                continue
            tid = row["key"].split(":", 1)[1]
            snap, _, _ = store.snapshot(row["url"], row["blob"], row.get("content_type"), "team_detail", tid, row["captured_at"])
            try:
                detail = parse_team_detail(row["text"]); details[tid] = detail
                store.db.execute("INSERT OR REPLACE INTO team VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                 (tid, detail["name_zh"], detail["name_tw"], detail["name_en"],
                                  detail["league_id"], detail["league_name"], detail["season"],
                                  detail["source_last_update"], snap,
                                  json.dumps(detail["roster"], ensure_ascii=False), row["captured_at"]))
                for alias in detail["aliases"]:
                    store.db.execute("INSERT OR IGNORE INTO team_alias VALUES(?,?,?,?,?)",
                                     (tid, alias, _token(alias), row["captured_at"], snap))
            except Exception as exc:
                errors.append({"key": row["key"], "error": str(exc)})

        schedule_items = []
        for tid in sorted(set(titan_to_canonical)):
            for year in years:
                url = f"{BASE}/cn/Team/TeamScheAjax.aspx?TeamID={tid}&y={int(year)}"
                schedule_items.append((f"schedule:{tid}:{year}", url,
                                       f"{BASE}/cn/Team/TeamSche.aspx?TeamID={tid}"))
        matches = {}
        match_snapshots = {}
        # Refresh schedules twice daily at most. This catches new fixtures but
        # prevents retries and same-day reruns from repeating the full crawl.
        for row in _batch_with_cache(store, schedule_items, workers, ttl_seconds=10 * 3600):
            health.append({k: v for k, v in row.items() if k not in ("blob", "text")})
            if not row.get("ok"):
                continue
            _, tid, year = row["key"].split(":")
            snap, _, _ = store.snapshot(row["url"], row["blob"], row.get("content_type"), "team_schedule", tid + "_" + year, row["captured_at"])
            try:
                for match in parse_team_schedule(row["text"]):
                    matches[match["match_id"]] = match
                    match_snapshots[match["match_id"]] = snap
            except Exception as exc:
                errors.append({"key": row["key"], "error": str(exc)})

        selected = set()
        foundation_league_ids = {FOUNDATION_LEAGUES[str(value).upper()]["league_id"]
                                 for value in (foundation_leagues or [])}
        if all_league_boxscores and foundation_league_ids:
            selected.update(m["match_id"] for m in matches.values()
                            if m["status"] == "FINAL" and m["league_id"] in foundation_league_ids and
                            datetime.fromisoformat(m["tip_at"]) < cutoff_dt)
        else:
            for tid in titan_to_canonical:
                candidates = [m for m in matches.values() if m["status"] == "FINAL" and
                              tid in (m["home_team_id"], m["away_team_id"]) and
                              datetime.fromisoformat(m["tip_at"]) < cutoff_dt]
                candidates.sort(key=lambda item: item["tip_at"], reverse=True)
                selected.update(m["match_id"] for m in candidates[:max(0, int(boxscore_limit))])
        tech_data, period_data, tech_snapshots, period_snapshots = {}, {}, {}, {}
        cache_hits = {"period": 0, "box_score": 0}
        for mid in sorted(selected):
            cached_match = store.db.execute(
                "SELECT periods_home_json,periods_away_json,half_home,half_away,home_score,away_score "
                "FROM match_history WHERE titan_match_id=?", (mid,)).fetchone()
            if cached_match and cached_match[0] and cached_match[1]:
                cached_home_periods = json.loads(cached_match[0])
                cached_away_periods = json.loads(cached_match[1])
                if isinstance(cached_home_periods, list) and isinstance(cached_away_periods, list):
                    period_data[mid] = {"home_periods": cached_home_periods,
                                        "away_periods": cached_away_periods,
                                        "half_home": cached_match[2], "half_away": cached_match[3],
                                        # Recompute from the period evidence.  Never
                                        # copy the schedule final into the validator.
                                        "home_score": sum(cached_home_periods),
                                        "away_score": sum(cached_away_periods)}
                    cache_hits["period"] += 1
                    snap = store.db.execute(
                        "SELECT snapshot_id,raw_path,sha256,captured_at FROM source_snapshot "
                        "WHERE entity_type='period' AND entity_id=? ORDER BY captured_at DESC LIMIT 1", (mid,)).fetchone()
                    if snap:
                        period_snapshots[mid] = snap
            cached_box = store.db.execute(
                "SELECT home_json,away_json,pace_level,pace_source,possessions,formula,source_snapshot_id,updated_at "
                "FROM box_score WHERE titan_match_id=?", (mid,)).fetchone()
            if cached_box:
                tech_data[mid] = {"home": json.loads(cached_box[0]), "away": json.loads(cached_box[1]),
                                  "team_ids": [], "pace_level": cached_box[2], "pace_source": cached_box[3],
                                  "game_possessions_estimate": cached_box[4], "formula": cached_box[5]}
                snap = store.db.execute(
                    "SELECT snapshot_id,raw_path,sha256,captured_at FROM source_snapshot WHERE snapshot_id=?",
                    (cached_box[6],)).fetchone()
                if snap:
                    tech_snapshots[mid] = snap
                cache_hits["box_score"] += 1
        tech_items = []
        for mid in sorted(selected):
            if mid not in tech_data:
                tech_items.append(("tech:" + mid, _tech_url(mid), f"{BASE}/cn/Tech/TechTxtLive.aspx?matchid={mid}"))
            if mid not in period_data:
                tech_items.append(("period:" + mid, f"{BASE}/cn/Tech/TechTxtLive.aspx?matchid={mid}",
                                   f"{BASE}/analysis/{mid}.htm"))
        for row in _batch(tech_items, workers):
            health.append({k: v for k, v in row.items() if k not in ("blob", "text")})
            if not row.get("ok"):
                continue
            kind, mid = row["key"].split(":")
            snap, path, digest = store.snapshot(row["url"], row["blob"], row.get("content_type"), kind, mid, row["captured_at"])
            try:
                if kind == "tech":
                    tech_data[mid] = parse_box_score_blob(row["text"])
                    tech_snapshots[mid] = (snap, path, digest, row["captured_at"])
                else:
                    period_data[mid] = parse_period_scores(row["text"])
                    period_snapshots[mid] = (snap, path, digest, row["captured_at"])
            except Exception as exc:
                errors.append({"key": row["key"], "error": str(exc)})

        history_rows, box_score_games, invalid_periods = [], [], set()
        for mid, match in matches.items():
            period = period_data.get(mid)
            if match["status"] != "FINAL" or not period:
                continue
            if period["home_score"] != match["home_score"] or period["away_score"] != match["away_score"]:
                errors.append({"key": "match:" + mid, "error": "SCHEDULE_PERIOD_SCORE_CONFLICT"})
                invalid_periods.add(mid)
                continue
            home_periods, away_periods = period["home_periods"], period["away_periods"]
            if len(home_periods) < 4 or len(away_periods) < 4:
                continue
            home_id = titan_to_canonical.get(match["home_team_id"], "titan-team:" + match["home_team_id"])
            away_id = titan_to_canonical.get(match["away_team_id"], "titan-team:" + match["away_team_id"])
            source_snap = period_snapshots.get(mid)
            known_at = source_snap[3] if source_snap else started
            row = {"event_id": "titan:" + mid, "source_event_id": mid, "tip_at": match["tip_at"],
                   "status": "FINAL", "competition_id": None,
                   "competition_key": competition_key(match["league"]),
                   "competition_identity_level": "CANONICAL_SOURCE_LABEL", "league": match["league"],
                   "team1_id": home_id, "team2_id": away_id, "team1_name": match["home_name"],
                   "team2_name": match["away_name"], "gender": "WOMEN" if "女" in match["league"] + match["home_name"] + match["away_name"] else "MEN",
                   "format_id": "BASKETBALL", "period_count": len(home_periods),
                   "period_points_team1": home_periods, "period_points_team2": away_periods,
                   "score1_regulation": sum(home_periods[:4]), "score2_regulation": sum(away_periods[:4]),
                   "score1_full": sum(home_periods), "score2_full": sum(away_periods),
                   "ot_points1": sum(home_periods[4:]), "ot_points2": sum(away_periods[4:]),
                   "score_basis": "TITAN_PERIOD_TABLE", "known_final_at": known_at,
                   "evidence_kind": "TEAM_HISTORY", "source_url": f"{BASE}/cn/Tech/TechTxtLive.aspx?matchid={mid}",
                   "raw_path": source_snap[1] if source_snap else None,
                   "raw_sha256": source_snap[2] if source_snap else None,
                   "source_variable": "teamPageData+scoreData", "source_schema": "TITAN_TEAM_SCHE_TECH_V1",
                   "source_status": match["source_state"], "home_sign": 0,
                   "home_adjustment_assumption": "UNVERIFIED_NO_HOME_ADJUSTMENT"}
            history_rows.append(row)
            box = tech_data.get(mid)
            if box:
                box_snap = tech_snapshots.get(mid)
                box_score_games.append({"event_id": row["event_id"], "tip_at": row["tip_at"],
                                        "team_ids": [home_id, away_id], "teams": [box["home"], box["away"]],
                                        "pace_level": box["pace_level"], "pace_source": box["pace_source"],
                                        "possessions_per_game": box["game_possessions_estimate"],
                                        "source_url": _tech_url(mid),
                                        "known_at": box_snap[3] if box_snap else known_at})

        for mid, match in matches.items():
            period = {} if mid in invalid_periods else (period_data.get(mid) or {})
            store.db.execute("INSERT OR REPLACE INTO match_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (mid, match["league_id"], match["league"], match["tip_at"], match["home_team_id"],
                              match["away_team_id"], match["home_name"], match["away_name"], match["home_score"],
                              match["away_score"], match["half_home"], match["half_away"],
                              json.dumps(period.get("home_periods"), ensure_ascii=False),
                              json.dumps(period.get("away_periods"), ensure_ascii=False), match["match_kind"],
                              match["source_state"], match["status"],
                              (period_snapshots.get(mid) or (match_snapshots.get(mid),))[0], started))
        for mid, box in tech_data.items():
            snap = tech_snapshots[mid][0]
            store.db.execute("INSERT OR REPLACE INTO box_score VALUES(?,?,?,?,?,?,?,?,?)",
                             (mid, json.dumps(box["home"], ensure_ascii=False), json.dumps(box["away"], ensure_ascii=False),
                              box["pace_level"], box["pace_source"], box["game_possessions_estimate"], box["formula"], snap, started))
        selected_team_game_stats = _upsert_selected_team_game_stats(
            store, matches, tech_data, tech_snapshots, invalid_periods, started)
        player_game_boxscores = upsert_player_boxscores(
            store.db, matches, tech_data, tech_snapshots, invalid_periods, started, _season_for)
        aggregate_audit = _rebuild_team_stat_tables(store, cutoff_dt, foundation_league_ids) \
            if foundation_league_ids else {"team_game_stats": 0, "team_season_stats": 0}
        feature_league_ids = foundation_league_ids | {str(match["league_id"]) for match in matches.values()}
        team_game_features = rebuild_team_game_features(store.db, cutoff_dt, feature_league_ids) \
            if feature_league_ids else 0
        player_season_stats = rebuild_player_season_stats(store.db, cutoff_dt)
        source_capabilities = evaluate_source_capabilities(store.db, cutoff_dt)
        manifest_path = _write_foundation_manifest(store, root, foundation_leagues, cutoff_dt)
        mapping_status_counts = Counter()
        for canonical in mappings:
            row = store.db.execute(
                "SELECT status FROM team_mapping WHERE canonical_team_id=? ORDER BY observed_at DESC LIMIT 1",
                (canonical,)).fetchone()
            mapping_status_counts[row[0] if row else "UNKNOWN"] += 1
        pace_levels = Counter(box.get("pace_level") or "UNKNOWN" for box in tech_data.values())
        fetch_failures = Counter(row["key"].split(":", 1)[0] for row in health if not row.get("ok"))
        cache_reuse = Counter(row["key"].split(":", 1)[0]
                              for row in health if row.get("cached"))
        audit = {"run_id": run_id, "requested_teams": len(teams),
                 "mapped_teams": sum(v is not None for v in mappings.values()), "years": years,
                 "mapping_cache_hits": mapping_cache_hits,
                 "mapping_status_counts": dict(mapping_status_counts), "detailed_teams": len(details),
                 "schedule_rows": len(matches), "selected_box_score_matches": len(selected),
                 "box_scores": len(tech_data), "history_rows": len(history_rows), "errors": errors,
                 "pace_level_counts": dict(pace_levels), "cache_hits": cache_hits,
                 "cache_reuse_by_stage": dict(cache_reuse),
                 "foundation_leagues": sorted(str(value).upper() for value in (foundation_leagues or [])),
                 "foundation_membership_counts": dict(Counter(row["league_family"] for row in memberships)),
                 "foundation_manifest_path": manifest_path,
                 "selected_team_game_stats": selected_team_game_stats,
                 "player_game_boxscores": player_game_boxscores,
                 "team_game_features": team_game_features,
                 "player_season_stats": player_season_stats,
                 "source_capability_rows": len(source_capabilities),
                 **aggregate_audit,
                 "network_fetch_failures_by_stage": dict(fetch_failures),
                 "market_history_used_in_model": False,
                 "provisional_or_qualified_ledger_modified": False}
        finished = _stamp()
        store.db.execute("INSERT OR REPLACE INTO capture_run VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (run_id, started, finished, len(teams), audit["mapped_teams"], len(matches),
                          len(tech_data), len(history_rows), "OK" if not errors else "PARTIAL", json.dumps(audit, ensure_ascii=False)))
        store.db.commit()
        audit_path = Path(root) / "latest_audit.json"
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"database": str(store.db_path), "audit_path": str(audit_path), "mappings": mappings,
                "history_rows": history_rows, "box_score_games": box_score_games,
                "team_memberships": memberships, "source_health": health, "audit": audit}
    finally:
        store.close()
