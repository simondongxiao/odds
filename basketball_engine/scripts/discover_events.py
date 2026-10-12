#!/usr/bin/env python3
"""Independent multi-source basketball event discovery for Step 2.

This module is deliberately data-source agnostic: adapters return raw event
dicts, then the same UNION/normalization path is used for live and test data.
"""
from __future__ import annotations
import hashlib, json, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

BJ = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc
STATUS = {"reconciled", "verified_no_games", "source_unavailable_with_secondary_check", "incomplete", "conflict"}
KNOWN = {"NBA","WNBA","NBA_SUMMER","G_LEAGUE","NCAAB","WNCAAB","EUROLEAGUE","CBA_REGULAR","CBA_PLAYOFF","CBA_PRESEASON","CBA_SUMMER","CBA_CLUB_CUP","CHINA_CLUB_WARMUP","FIBA_MEN","FIBA_WOMEN","FIBA_QUALIFIER","FIBA_YOUTH","B_LEAGUE","KBL","NBL_AU","CHINA_CBA","CHINA_WCBA","CHINA_NBL","CHINA_CUBA","CHINA_UNIVERSITY_OTHER","CHINA_YOUTH","CHINA_CLUB_CUP","CHINA_FRIENDLY","FIBA_CONTINENTAL","FIBA_FRIENDLY","JAPAN_BLEAGUE","JAPAN_WOMEN","JAPAN_CUP","KOREA_KBL","KOREA_WOMEN","KOREA_CUP","AUSTRALIA_NBL","AUSTRALIA_WNBL","NEW_ZEALAND","OCEANIA_OTHER","EUROCUP","EUROPE_DOMESTIC","ADRIATIC","EASTERN_EUROPE","NORTHERN_EUROPE","OTHER_EUROPE","NORTH_AMERICA_CLUB","AMERICAS_OTHER","GULF","MIDDLE_EAST","SOUTHEAST_ASIA","PHILIPPINES","TAIWAN_REGION","OTHER_ASIA","CZECH_NBL","SWEDEN_BASKETETTAN","FINLAND_DIVISION_1","VTB_UNITED","ENBL","ICELAND_WOMEN","ROMANIA_CUP","SWITZERLAND_NBL","SWITZERLAND_WOMEN","HUNGARY_NB1","BELARUS_LEAGUE","SLOVAKIA_LEAGUE","NORWAY_BLNO","GREECE_WOMEN_CUP","TUNISIA_LEAGUE","UAE_CUP","CANADA_WOMEN_ABL","ESTONIA_LATVIA_LEAGUE","UGANDA_WOMEN_LEAGUE","KENYA_WOMEN_LEAGUE","PUERTO_RICO_WOMEN","AMERICAS_WOMEN","COLOMBIA_LEAGUE","BRAZIL_PAULISTA","EL_SALVADOR_LEAGUE","PHILIPPINES_UAAP","PHILIPPINES_MPBL","SINGAPORE_NBL","WEST_ASIA_SUPER_LEAGUE","KOREA_UNIVERSITY_MEN","KOREA_UNIVERSITY_WOMEN","FRIENDLY_CLUB","UNCLASSIFIED_DISCOVERED","OTHER_DISCOVERED"}

def classify_family(value: str) -> str:
    text = str(value or "").upper()
    if text in KNOWN: return text
    if "FIBA" in text or "WORLD CUP" in text: return "FIBA_WOMEN" if "WOMEN" in text or "女" in text else "FIBA_MEN"
    if "CBA" in text or "夏季联赛" in text: return "CBA_SUMMER" if "夏" in text or "SUMMER" in text else "CBA_REGULAR"
    if "NBL" in text or "澳" in text: return "NBL_AU"
    if "B.LEAGUE" in text or "日本" in text: return "B_LEAGUE"
    if "KBL" in text or "韩国" in text: return "KBL"
    if "NBA" in text: return "NBA"
    return "OTHER_DISCOVERED"

def norm_team(name: str, aliases: dict[str, str] | None = None) -> str:
    text = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", (name or "").strip()).lower().strip()
    aliases = aliases or {}
    for key, value in aliases.items():
        if text == re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", key.lower()).strip():
            return value
    return text

def parse_tip(value: Any, source_tz: str = "UTC") -> datetime:
    if isinstance(value, datetime): dt = value
    else:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None: dt = dt.replace(tzinfo=ZoneInfo(source_tz))
    return dt.astimezone(UTC)

def canonical_id(event: dict[str, Any], aliases=None) -> str:
    stable = event.get("official_game_id") or event.get("game_id") or event.get("source_game_id")
    if stable: return f"{event.get('league_family','OTHER_DISCOVERED')}:{stable}"
    # Tournament/bracket identity survives late participant resolution.
    if event.get("tournament_id") and event.get("stage") and event.get("bracket_slot"):
        tip = parse_tip(event["tip_utc"], event.get("source_timezone", "UTC")).replace(second=0, microsecond=0)
        return f"{event.get('league_family','OTHER_DISCOVERED')}:bracket-{event['tournament_id']}|{event['stage']}|{event['bracket_slot']}|{tip.isoformat()}"
    if event.get("tournament_id") and event.get("stage") and event.get("round"):
        tip = parse_tip(event["tip_utc"], event.get("source_timezone", "UTC")).replace(second=0, microsecond=0)
        return f"{event.get('league_family','OTHER_DISCOVERED')}:round-{event['tournament_id']}|{event['stage']}|{event['round']}|{tip.isoformat()}"
    if event.get("venue") and event.get("stage"):
        tip = parse_tip(event["tip_utc"], event.get("source_timezone", "UTC")).replace(second=0, microsecond=0)
        return f"{event.get('league_family','OTHER_DISCOVERED')}:venue-{event.get('venue')}|{event.get('stage')}|{tip.isoformat()}"
    if event.get("competition") and event.get("stage"):
        tip = parse_tip(event["tip_utc"], event.get("source_timezone", "UTC")).replace(second=0, microsecond=0)
        teams = sorted([norm_team(event.get("team_1"), aliases), norm_team(event.get("team_2"), aliases)])
        return f"{event.get('league_family','OTHER_DISCOVERED')}:competition-{event['competition']}|{event['stage']}|{'|'.join(teams)}|{tip.isoformat()}"
    t1 = norm_team(event.get("official_order_team_1") or event.get("home") or event.get("team_1"), aliases)
    t2 = norm_team(event.get("official_order_team_2") or event.get("away") or event.get("team_2"), aliases)
    tip = parse_tip(event["tip_utc"], event.get("source_timezone", "UTC"))
    rounded = tip.replace(second=0, microsecond=0)
    payload = f"{event.get('league_family','OTHER_DISCOVERED')}|{t1}|{t2}|{rounded.isoformat()}".encode()
    return f"{event.get('league_family','OTHER_DISCOVERED')}:hash-{hashlib.sha256(payload).hexdigest()[:20]}"

def normalize(event: dict[str, Any], source: str, aliases=None) -> dict[str, Any]:
    item = dict(event)
    item["source"] = source
    item.setdefault("source_name", source)
    item.setdefault("source_group", "broad")
    item.setdefault("upstream_provider", source)
    item.setdefault("captured_at", datetime.now(BJ).isoformat())
    item.setdefault("source_confidence", "medium")
    item.setdefault("discovered_from_odds_board", item.get("source_group") == "odds_board")
    item.setdefault("scoreboard_verified", item.get("source_group") != "odds_board")
    if item.get("discovered_from_odds_board") and not item.get("scoreboard_verified"):
        item["event_status"] = "discovered_unverified"
    item["league_family"] = classify_family(item.get("league_family"))
    item["tip_utc"] = parse_tip(item["tip_utc"], item.get("source_timezone", "UTC")).isoformat()
    item["tip_bj"] = datetime.fromisoformat(item["tip_utc"]).astimezone(BJ).isoformat()
    item["bj_date"] = item["tip_bj"][:10]
    item["team_1"] = item.get("official_order_team_1") or item.get("home") or item.get("team_1")
    item["team_2"] = item.get("official_order_team_2") or item.get("away") or item.get("team_2")
    item["team_1_normalized"] = norm_team(item["team_1"], aliases)
    item["team_2_normalized"] = norm_team(item["team_2"], aliases)
    item["canonical_event_id"] = canonical_id(item, aliases)
    item["neutral_site"] = bool(item.get("neutral_site", False))
    if item["neutral_site"]:
        item["home"] = None
        item["away"] = None
        item["score_order"] = "official_source_order"
    return item

def discover_independently(adapters: dict[str, Callable[[str], Iterable[dict[str, Any]]]], bj_date: str, aliases=None):
    """Run every adapter even when an earlier adapter succeeds or returns zero."""
    raw, source_status = {}, {}
    for source, adapter in adapters.items():
        try:
            rows = list(adapter(bj_date))
            raw[source] = [normalize(x, source, aliases) for x in rows]
            source_status[source] = "ok" if rows else "source_zero_result"
        except Exception as exc:
            raw[source] = []
            source_status[source] = {"status": "error", "error": str(exc)}
    union = {}
    for rows in raw.values():
        for row in rows: union.setdefault(row["canonical_event_id"], []).append(row)
    return raw, union, source_status

def build_manifest(bj_date, raw, union, source_status, families):
    manifest = {"schema_version": 2, "bj_date": bj_date, "checked_at": datetime.now(BJ).isoformat(), "league_families": []}
    for family in families:
        ids = {eid for eid, rows in union.items() if any(r.get("league_family") == family for r in rows)}
        counts = {s: sum(1 for r in rows if r.get("league_family") == family) for s, rows in raw.items()}
        active = any(counts.values())
        statuses = [source_status[s] for s in raw]
        if ids and sum(counts.values()) == len(ids): state = "reconciled"
        elif ids and any(isinstance(x, dict) for x in statuses): state = "incomplete"
        elif not active and any(x == "source_zero_result" for x in statuses): state = "source_unavailable_with_secondary_check"
        elif not active: state = "incomplete"
        else: state = "conflict" if any(len([r for r in rows if r.get("league_family") == family]) > 1 for rows in union.values()) else "incomplete"
        manifest["league_families"].append({"league_family":family,"expected_active":active,"sources_attempted":list(raw),"source_status":{s:source_status[s] for s in raw},"event_count_by_source":counts,"union_event_count":len(ids),"canonical_event_ids":sorted(ids),"missing_vs_union":{},"extra_vs_union":{},"conflicts":[],"reconciliation_status":state})
    return manifest

def load_json_adapter(path: str, source: str):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("events", data.get("fixtures", []))
    return lambda _date: rows

def _cli_event(row, source):
    """Best-effort adapter for saved scoreboard/fixture snapshots used by dry-runs."""
    if row.get("tip_utc"):
        return row
    date, tm = row.get("date"), row.get("time")
    if not date or not tm: return None
    return {"league_family": row.get("league_family") or row.get("league") or "OTHER_DISCOVERED",
            "team_1": row.get("home") or row.get("official_order_team_1"),
            "team_2": row.get("away") or row.get("official_order_team_2"),
            "tip_utc": f"{date}T{tm}:00+08:00", "official_game_id": row.get("id"),
            "source_timezone": "Asia/Shanghai", "neutral_site": "FIBA" in str(row.get("league", ""))}

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--source-json", action="append", default=[], metavar="SOURCE=PATH")
    parser.add_argument("--output-events", required=True)
    parser.add_argument("--output-manifest", required=True)
    args = parser.parse_args()
    adapters = {}
    for spec in args.source_json:
        source, path = spec.split("=", 1)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else data.get("events", data.get("fixtures", []))
        adapters[source] = lambda target_date, rows=rows, source=source: [x for x in (_cli_event(r, source) for r in rows) if x and x.get("date", x.get("tip_utc", "")[:10]) == target_date]
    for source in ("espn_scoreboard", "sofascore_scheduled_events", "thesportsdb_basketball", "fiba_event_calendar", "fiba_games_results", "nbl_official_schedule", "cba_specific_schedule", "odds_board_discovery"):
        adapters.setdefault(source, lambda _date: [])
    raw, union, statuses = discover_independently(adapters, args.date)
    from reconcile_events import reconcile
    events, conflicts = reconcile(union)
    families = sorted({x.get("league_family", "OTHER_DISCOVERED") for x in events} | {"NBA","WNBA","NBA_SUMMER","G_LEAGUE","NCAAB","WNCAAB","EUROLEAGUE","CBA_REGULAR","CBA_PLAYOFF","CBA_PRESEASON","CBA_SUMMER","CBA_CLUB_CUP","CHINA_CLUB_WARMUP","FIBA_MEN","FIBA_WOMEN","FIBA_QUALIFIER","FIBA_YOUTH","B_LEAGUE","KBL","NBL_AU","OTHER_DISCOVERED"})
    manifest = build_manifest(args.date, raw, union, statuses, families)
    for item in manifest["league_families"]: item["conflicts"] = conflicts if item["league_family"] in {x.get("league_family") for x in events if x.get("reconciliation_status")=="conflict"} else []
    Path(args.output_events).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_events).write_text(json.dumps({"schema_version":2,"bj_date":args.date,"events":events}, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.output_manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"date":args.date,"events":len(events),"sources":statuses,"conflicts":len(conflicts)}, ensure_ascii=False))

if __name__ == "__main__": main()
