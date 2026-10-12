"""Titan007 basketball schedule and current-board parser.

The public ``lq3.titan007.com/nba.htm`` page renders its schedule and odds
from two normal HTTP XML endpoints. This module parses those payloads as data;
it never executes downloaded JavaScript and never turns a missing odds row
into a missing event.
"""
from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from repair_v22.common import competition_key, competition_phase

BJ = timezone(timedelta(hours=8))
TITAN_SCHEDULE_URL = "https://lq3.titan007.com/NBA/today2.xml"
TITAN_COMPANIES = {"1": "澳", "2": "易胜", "3": "Crow", "8": "36", "9": "伟"}


def _num(value):
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _date_from_day(raw, day):
    match = re.search(r"(\d{1,2})月(\d{1,2})日", str(raw or ""))
    if not match:
        return None
    return f"{int(str(day)[:4])}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"


def _tip(raw, day):
    match = re.search(r"(\d{1,2})月(\d{1,2})日<br\s*/?>(\d{1,2}:\d{2})", str(raw or ""), re.I)
    if not match:
        return None
    dt = datetime.strptime(
        f"{int(str(day)[:4])}-{int(match.group(1)):02d}-{int(match.group(2)):02d} {match.group(3)}",
        "%Y-%m-%d %H:%M",
    ).replace(tzinfo=BJ)
    return dt.astimezone(timezone.utc)


def _row_text(value):
    parts = str(value or "").split(",")
    return (parts[0] or parts[-1]).strip()


def _row_aliases(value):
    """Preserve every published language/name variant for exact reconciliation."""
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def parse_schedule_xml(text, day, source_path=None, observed_at=None):
    """Return every target-day schedule row from Titan's ``today2.xml``."""
    events, errors = [], []
    rows = re.findall(r"<h[^>]*>\s*<!\[CDATA\[(.*?)\]\]>\s*</h>", str(text or ""), re.I | re.S)
    for index, raw in enumerate(rows):
        fields = raw.split("^")
        try:
            if len(fields) < 11:
                raise ValueError("TITAN_SCHEDULE_ROW_TOO_SHORT")
            source_id = str(fields[0]).strip()
            bj_date = _date_from_day(fields[4], day)
            tip = _tip(fields[4], day)
            if not source_id or not bj_date or tip is None:
                raise ValueError("TITAN_SCHEDULE_TIME_OR_ID_INVALID")
            if bj_date != str(day):
                continue
            team1, team2 = _row_text(fields[8]), _row_text(fields[10])
            if not team1 or not team2:
                raise ValueError("TITAN_TEAM_NAME_MISSING")
            league = _row_text(fields[1])
            mainstream_preseason = any(x in league.upper() for x in ("NBA", "WNBA")) and "季前" in league
            high_uncertainty = (not mainstream_preseason and
                                any(x in league for x in ("友谊", "夏季", "热身", "青年", "U18", "U16", "U19", "U20", "杯赛", "季前")))
            national_team = any(x in league for x in ("世界杯", "世锦赛", "亚运", "亚洲杯", "国家队", "奥运", "欧洲国家"))
            event = {
                "event_id": f"7m:{source_id}",
                "canonical_event_id": f"7m:{source_id}",
                "source_event_id": source_id,
                "source": "TITAN007",
                "source_name": "titan007_nba",
                "source_url": "https://lq3.titan007.com/nba.htm",
                "source_event_url": f"https://nba.titan007.com/analysis/{source_id}.htm",
                "source_timezone": "Asia/Shanghai",
                "time_basis": "Titan007 today2.xml GMT+0800 page time",
                "tip_at": tip.isoformat(),
                "tip_time_utc": tip.isoformat(),
                "tip_time_bj": tip.astimezone(BJ).isoformat(),
                "bj_date": bj_date,
                "league": league,
                "season_phase": competition_phase(league),
                "model_family": "HIGH_UNCERTAINTY" if high_uncertainty else "NATIONAL_TEAM" if national_team else "CLUB_MATURE",
                "age_group": "UNVERIFIED" if high_uncertainty else "SENIOR",
                "competition_id": f"titan-comp:{fields[2]}",
                "competition_key": competition_key(league, "WOMEN" if any(x in league + team1 + team2 for x in ("女", "WNBA", "Women", "women")) else "MEN"),
                # Titan's numeric team IDs are provider-local.  They must not
                # share 7M's namespace: both feeds can legitimately use the
                # same number for different clubs in the same capture.
                "team1_id": f"titan-team:{fields[7]}",
                "team2_id": f"titan-team:{fields[9]}",
                "team1_source_id": str(fields[7]),
                "team2_source_id": str(fields[9]),
                "team1_name": team1,
                "team2_name": team2,
                "team1_aliases": _row_aliases(fields[8]),
                "team2_aliases": _row_aliases(fields[10]),
                "gender": "WOMEN" if any(x in league + team1 + team2 for x in ("女", "WNBA", "Women", "women")) else "MEN",
                "format_id": "BASKETBALL",
                "identity_verified": True,
                "source_status": str(fields[5]).strip(),
                "titan_schedule_row": raw,
                "titan_schedule_row_index": index,
                "identity_raw_path": str(source_path) if source_path else None,
                "observed_at": observed_at,
                "home_sign": 0,
                "home_adjustment_assumption": "NEUTRAL_UNLESS_VERIFIED",
                "venue_status": "UNKNOWN",
            }
            events.append(event)
        except (TypeError, ValueError, IndexError) as exc:
            errors.append({"source": "titan007_nba", "row_index": index, "error": str(exc), "raw_row": raw})
    return events, errors


def parse_odds_xml(text, company_id, source_path=None, received_at=None):
    """Parse Titan's current-board ``nbaGoal{company}.xml`` payload.

    ``goal`` is Titan's team-1 handicap magnitude/sign convention: a positive
    value means team1 gives points and a negative value means team1 receives
    points. The pipeline canonicalizes this to a signed team1 line where a
    negative value means team1 gives points. Prices are positive Hong Kong
    water, so decimal price is water + 1. The endpoint is
    a current-board snapshot and does not publish a per-quote last-change
    timestamp.  The verified current-board listing and capture time are kept
    distinct from a last-change timestamp; downstream freshness may use the
    former only while the event is still listed OPEN in this captured board.
    """
    company_id = str(company_id)
    bookmaker = TITAN_COMPANIES.get(company_id, f"company_{company_id}")
    quotes, errors = [], []
    # Match the literal ``m`` row tag only.  The former ``<m[^>]*>`` pattern
    # also consumed the parent ``<match>`` element and produced source ids such
    # as ``<m>742140``.  Those invalid ids then broke canonical event matching.
    rows = re.findall(r"<m(?:\s[^>]*)?>(.*?)</m>", str(text or ""), re.I | re.S)
    raw_sha = hashlib.sha256(Path(source_path).read_bytes()).hexdigest() if source_path and Path(source_path).is_file() else None
    for index, raw in enumerate(rows):
        fields = raw.strip().split(",")
        if len(fields) < 7:
            errors.append({"source": "titan007_nba", "company_id": company_id, "row_index": index,
                           "market_type": "SPREAD_AND_TOTAL", "error": "TITAN_ODDS_ROW_TOO_SHORT"})
            continue
        sid = str(fields[0]).strip()
        goal, home_price, away_price = (_num(fields[i]) for i in (1, 2, 3))
        total, over_price, under_price = (_num(fields[i]) for i in (4, 5, 6))
        if goal is not None and home_price is not None and away_price is not None:
            quotes.append(_quote(sid, company_id, bookmaker, "SPREAD", goal, [home_price, away_price], source_path, received_at, raw_sha, index))
        elif any(x is not None for x in (goal, home_price, away_price)):
            errors.append({"source": "titan007_nba", "company_id": company_id, "source_event_id": sid,
                           "market_type": "SPREAD", "error": "TITAN_PARTIAL_SPREAD_ROW"})
        if total is not None and over_price is not None and under_price is not None:
            quotes.append(_quote(sid, company_id, bookmaker, "TOTAL", total, [over_price, under_price], source_path, received_at, raw_sha, index))
        elif any(x is not None for x in (total, over_price, under_price)):
            errors.append({"source": "titan007_nba", "company_id": company_id, "source_event_id": sid,
                           "market_type": "TOTAL", "error": "TITAN_PARTIAL_TOTAL_ROW"})
    return quotes, errors


def _quote(sid, company_id, bookmaker, market_type, line, prices, source_path, received_at, raw_sha, row_index):
    received_at = received_at or datetime.now(timezone.utc).isoformat()
    qid = hashlib.sha256((f"TITAN007|{company_id}|{sid}|{market_type}|{line}|{prices}|{received_at}").encode()).hexdigest()[:24]
    return {
        "quote_id": qid, "event_id": f"7m:{sid}", "source_event_id": sid,
        "feed_provider": "TITAN007", "upstream_provider": "titan007_nba",
        "bookmaker_id": f"titan007-company:{company_id}", "bookmaker": bookmaker,
        "company_namespace": company_id, "market_type": market_type,
        "raw_market_key": "goal" if market_type == "SPREAD" else "total",
        "parse_status": "PARSED_AND_NORMALIZED", "period": "FULL_GAME", "main_or_alt": "MAIN",
        "source_market_key": "nbaGoal" + company_id, "source_main_flag": True,
        "source_array": None, "raw_line": line,
        # Titan's ``goal`` is a team-1 giving magnitude when positive. Keep
        # raw_line untouched for audit, but expose the canonical dashboard
        # convention: negative = team1 gives, positive = team1 receives.
        "line_team1": -line if market_type == "SPREAD" else None,
        "source_line_basis": "TITAN_GOAL_TEAM1_GIVES_POSITIVE",
        "canonical_line_basis": "SIGNED_TEAM1_HANDICAP_NEGATIVE_GIVES_POSITIVE_RECEIVES",
        # nbaGoal publishes an ordered pair: team1/team2 for spread and
        # over/under for total.  Direction is therefore known for both market
        # types even though quote time and overtime settlement remain unknown.
        "direction_verified": True,
        "raw_prices": prices, "decimal_prices": [1 + float(prices[0]), 1 + float(prices[1])],
        "price_format": "HK", "price_format_verified": True,
        "source_quote_at": None, "source_timestamp_raw": None,
        "quote_changed_at": None, "last_verified_at": received_at,
        "source_timestamp_semantics": "CURRENT_BOARD_CAPTURE_ONLY",
        "received_at": received_at, "observed_at": received_at,
        "raw_path": str(source_path) if source_path else None, "raw_sha256": raw_sha,
        "ot_rule": "UNKNOWN", "rule_evidence": None,
        "comparison_scope": "VERIFIED_CURRENT_BOARD_CAPTURE",
        "current_board_contract_verified": True, "status": "OPEN",
        "raw_verified": bool(source_path and Path(source_path).is_file()),
        "execution_verified": False,
        "freshness_note": "SOURCE_LAST_CHANGE_NOT_PUBLISHED_CURRENT_LISTING_CAPTURED",
        "titan_row_index": row_index,
    }


def parse(html):
    """Compatibility shim for the provider smoke test."""
    events, errors = parse_schedule_xml(html, datetime.now(BJ).date().isoformat())
    return {"source": "titan007", "events": events, "markets": [], "errors": errors}
