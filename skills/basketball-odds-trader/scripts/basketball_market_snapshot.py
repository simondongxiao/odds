#!/usr/bin/env python3
"""Basketball odds utilities for spread, totals, devig, CLV, and source snapshots."""

from __future__ import annotations

import argparse
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any


ODDS_API = "https://api.the-odds-api.com"
GAMMA = "https://gamma-api.polymarket.com"
SOFASCORE_API = "https://api.sofascore.com/api/v1"
NBA_STATS_API = "https://stats.nba.com/stats"
THESPORTSDB_API = "https://www.thesportsdb.com/api/v1/json/3"

ESPN_LEAGUES = {
    "nba": "basketball/nba",
    "wnba": "basketball/wnba",
    "ncaam": "basketball/mens-college-basketball",
    "ncaaw": "basketball/womens-college-basketball",
}

NBA_STATS_LEAGUES = {
    "nba": "00",
    "wnba": "10",
    "summer": "15",
    "gleague": "20",
}


def parse_csv(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def get_json(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
    query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v not in (None, "")}, doseq=True)
    full_url = f"{url}?{query}" if query else url
    req_headers = {
        "User-Agent": "basketball-odds-trader/1.0 Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
    }
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(full_url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Network error: {exc}") from exc


def bj_time_from_unix(start_timestamp: int | float | None) -> str:
    if not start_timestamp:
        return ""
    try:
        value = datetime.fromtimestamp(float(start_timestamp), tz=timezone.utc)
    except Exception:
        return ""
    return value.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")


def bj_time_from_iso(value: str | None, assume_utc: bool = True) -> str:
    if not value:
        return ""
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None and assume_utc:
                parsed = parsed.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None:
            return ""
        return parsed.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def result_sets_to_dicts(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for item in data.get("resultSets", []):
        name = item.get("name", "")
        headers = item.get("headers", [])
        rows = item.get("rowSet", [])
        result[name] = [dict(zip(headers, row)) for row in rows]
    return result


def american_to_decimal(value: float) -> float:
    if value == 0:
        raise ValueError("American odds cannot be 0")
    if value > 0:
        return 1.0 + value / 100.0
    return 1.0 + 100.0 / abs(value)


def to_decimal(value: str, fmt: str) -> float:
    num = float(value)
    if fmt == "decimal":
        return num
    if fmt == "american":
        return american_to_decimal(num)
    if fmt == "hk":
        if num <= 0:
            raise ValueError("HK water should be positive")
        return 1.0 + num
    raise ValueError(f"Unsupported odds format: {fmt}")


def devig(names: list[str], odds: list[float]) -> dict[str, Any]:
    if len(names) != len(odds):
        raise SystemExit("--names and --odds must have the same length")
    raw = [1.0 / odd for odd in odds]
    total = sum(raw)
    outcomes = []
    for name, decimal_odds, raw_prob in zip(names, odds, raw):
        true_prob = raw_prob / total
        outcomes.append(
            {
                "name": name,
                "decimal_odds": round(decimal_odds, 6),
                "raw_implied_pct": round(raw_prob * 100.0, 3),
                "true_prob_pct": round(true_prob * 100.0, 3),
                "fair_odds": round(1.0 / true_prob, 4),
            }
        )
    return {"margin_pct": round((total - 1.0) * 100.0, 3), "outcomes": outcomes}


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def kelly_decimal(prob: float, decimal_odds: float) -> float:
    return (prob * decimal_odds - 1.0) / (decimal_odds - 1.0)


def normalize_probability(value: float) -> float:
    """Accept 0.56 or 56 and return probability from 0 to 1."""
    return value / 100.0 if value > 1.0 else value


def directional_gap_points(market: str, selection: str, pred: float, line: float) -> dict[str, Any]:
    market = market.lower()
    selection = selection.lower()
    if market == "spread":
        market_home_threshold = -line
        if selection == "home":
            gap = pred - market_home_threshold
        elif selection == "away":
            gap = market_home_threshold - pred
        else:
            raise SystemExit("Spread selection must be home or away")
        return {
            "market_home_threshold": round(market_home_threshold, 3),
            "directional_gap_points": round(gap, 3),
            "absolute_line_pred_gap": round(abs(pred - market_home_threshold), 3),
        }
    if market in {"total", "team-total"}:
        if selection == "over":
            gap = pred - line
        elif selection == "under":
            gap = line - pred
        else:
            raise SystemExit("Total selection must be over or under")
        return {
            "directional_gap_points": round(gap, 3),
            "absolute_line_pred_gap": round(abs(pred - line), 3),
        }
    raise SystemExit("Unsupported market for quant gate")


def cmd_quant_gate(args: argparse.Namespace) -> None:
    prob_low = normalize_probability(args.prob_low)
    decimal_odds = to_decimal(str(args.odds), args.format)
    breakeven = 1.0 / decimal_odds
    ev_multiplier = prob_low * decimal_odds
    edge = prob_low - breakeven
    full_kelly = kelly_decimal(prob_low, decimal_odds)
    quarter_kelly = max(0.0, full_kelly) * 0.25
    if args.stake_cap is not None:
        quarter_kelly = min(quarter_kelly, args.stake_cap)

    gap_info = directional_gap_points(args.market, args.selection, args.pred, args.line)
    directional_gap = gap_info["directional_gap_points"]

    blockers: list[str] = []
    if prob_low < args.min_prob:
        blockers.append(f"p_low {prob_low:.3f} below minimum {args.min_prob:.3f}")
    if ev_multiplier <= args.min_ev_multiplier:
        blockers.append(f"EV multiplier {ev_multiplier:.4f} not above {args.min_ev_multiplier:.4f}")
    if directional_gap < args.k_points:
        blockers.append(f"directional Line-Pred gap {directional_gap:.3f} below K {args.k_points:.3f}")

    time_lock_status = "not_checked"
    if args.hours_to_tip is not None:
        if args.hours_to_tip < 0:
            time_lock_status = "post_tip_or_live"
            blockers.append("game is live/post-tip; no pre-game action")
        elif args.line_move_trigger and args.hours_to_tip > 5:
            time_lock_status = "ignore_probe_move"
            blockers.append("line-move trigger is more than 5 hours before tipoff")
        elif args.line_move_trigger and args.hours_to_tip > 2:
            time_lock_status = "wait_for_final_two_hours"
            blockers.append("line-move trigger is outside final 2-hour window")
        elif args.line_move_trigger:
            time_lock_status = "eligible_final_two_hours"
        else:
            time_lock_status = "price_edge_check"
    elif args.line_move_trigger:
        blockers.append("line-move trigger requires --hours-to-tip")

    volatility_fuse = "not_checked"
    if args.volatility_last_hour is not None:
        if args.volatility_last_hour > 5.0:
            volatility_fuse = "tripped"
            blockers.append("final-hour volatility exceeds 5 points")
        else:
            volatility_fuse = "pass"

    steam_alignment = args.steam_aligned.lower()
    if steam_alignment == "no":
        blockers.append("final steam move is against the model side")
    elif steam_alignment == "unknown":
        blockers.append("steam alignment unknown; no real-money action")

    if full_kelly <= 0:
        blockers.append("full Kelly is not positive")

    bet_status = "可投-主单" if not blockers else "不可投"
    count_bucket = "real_money_candidate" if bet_status == "可投-主单" else "no-action"
    print(
        json.dumps(
            {
                "market": args.market,
                "selection": args.selection,
                "prob_low": round(prob_low, 6),
                "decimal_odds": round(decimal_odds, 6),
                "breakeven": round(breakeven, 6),
                "ev_multiplier": round(ev_multiplier, 6),
                "edge": round(edge, 6),
                "min_prob": args.min_prob,
                "min_ev_multiplier": args.min_ev_multiplier,
                "pred": args.pred,
                "line": args.line,
                "k_points": args.k_points,
                **gap_info,
                "time_lock_status": time_lock_status,
                "volatility_fuse": volatility_fuse,
                "steam_alignment": steam_alignment,
                "full_kelly": round(full_kelly, 6),
                "quarter_kelly": round(quarter_kelly, 6),
                "stake_cap": args.stake_cap,
                "bet_status": bet_status,
                "count_bucket": count_bucket,
                "zero_action_reasons": blockers,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def classify_movement(market: str, open_line: float | None, current_line: float | None, close_line: float | None) -> dict[str, Any]:
    if open_line is None or current_line is None:
        return {"status": "missing_open_or_current"}
    latest_delta = current_line - open_line
    close_delta = None if close_line is None else close_line - open_line
    if market == "spread":
        toward_home_latest = -latest_delta
        toward_home_close = None if close_delta is None else -close_delta
        material = abs(toward_home_latest) >= 1.5
        direction = "toward_home" if toward_home_latest > 0 else "toward_away" if toward_home_latest < 0 else "flat"
        return {
            "market": market,
            "line_delta_latest": round(latest_delta, 3),
            "toward_home_points_latest": round(toward_home_latest, 3),
            "toward_home_points_close": None if toward_home_close is None else round(toward_home_close, 3),
            "direction": direction,
            "material_move": material,
        }
    material = abs(latest_delta) >= 2.5
    direction = "up" if latest_delta > 0 else "down" if latest_delta < 0 else "flat"
    return {
        "market": market,
        "line_delta_latest": round(latest_delta, 3),
        "line_delta_close": None if close_delta is None else round(close_delta, 3),
        "direction": direction,
        "material_move": material,
    }


def clv(selection: str, market: str, entry_line: float | None, close_line: float | None) -> float | None:
    if entry_line is None or close_line is None:
        return None
    selection = selection.lower()
    if market == "spread":
        if selection == "home":
            return entry_line - close_line
        if selection == "away":
            return close_line - entry_line
    if market in {"total", "team-total"}:
        if selection == "over":
            return close_line - entry_line
        if selection == "under":
            return entry_line - close_line
    return None


def cmd_devig(args: argparse.Namespace) -> None:
    names = parse_csv(args.names)
    odds = [to_decimal(x, args.format) for x in parse_csv(args.odds)]
    print(json.dumps(devig(names, odds), ensure_ascii=False, indent=2))


def cmd_kelly(args: argparse.Namespace) -> None:
    decimal_odds = to_decimal(str(args.odds), args.format)
    full = kelly_decimal(args.prob, decimal_odds)
    frac = max(0.0, full) * args.fraction
    print(
        json.dumps(
            {
                "prob": args.prob,
                "decimal_odds": round(decimal_odds, 6),
                "full_kelly": round(full, 6),
                "fraction": args.fraction,
                "recommended_fraction": round(frac, 6),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_line_audit(args: argparse.Namespace) -> None:
    movement = classify_movement(args.market, args.open_line, args.current_line, args.close_line)
    result = {
        "market": args.market,
        "selection": args.selection,
        "entry_line": args.entry_line,
        "open_line": args.open_line,
        "current_line": args.current_line,
        "close_line": args.close_line,
        "movement": movement,
        "clv_points": None if args.entry_line is None else clv(args.selection, args.market, args.entry_line, args.close_line),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_estimate_cover(args: argparse.Namespace) -> None:
    threshold = -args.spread
    z = (threshold - args.projected_margin) / args.sigma
    home_cover = 1.0 - normal_cdf(z)
    print(
        json.dumps(
            {
                "projected_home_margin": args.projected_margin,
                "home_spread": args.spread,
                "sigma": args.sigma,
                "home_cover_prob_pct": round(home_cover * 100.0, 3),
                "away_cover_prob_pct": round((1.0 - home_cover) * 100.0, 3),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_estimate_total(args: argparse.Namespace) -> None:
    z = (args.total - args.projected_total) / args.sigma
    over = 1.0 - normal_cdf(z)
    print(
        json.dumps(
            {
                "projected_total": args.projected_total,
                "market_total": args.total,
                "sigma": args.sigma,
                "over_prob_pct": round(over * 100.0, 3),
                "under_prob_pct": round((1.0 - over) * 100.0, 3),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_espn_scoreboard(args: argparse.Namespace) -> None:
    path = ESPN_LEAGUES.get(args.league.lower())
    if not path:
        raise SystemExit(f"Unsupported league. Use one of: {', '.join(sorted(ESPN_LEAGUES))}")
    data = get_json(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard", {"dates": args.date})
    events = []
    for event in data.get("events", []):
        competition = (event.get("competitions") or [{}])[0]
        competitors = competition.get("competitors") or []
        teams = {}
        for item in competitors:
            team = item.get("team") or {}
            teams[item.get("homeAway", "")] = {
                "name": team.get("displayName") or team.get("shortDisplayName") or team.get("name") or "",
                "abbrev": team.get("abbreviation") or "",
                "score": item.get("score") or "",
            }
        status = event.get("status", {}).get("type", {})
        events.append(
            {
                "id": event.get("id"),
                "name": event.get("name"),
                "date": event.get("date"),
                "bj_time": bj_time_from_iso(event.get("date")),
                "home": teams.get("home", {}),
                "away": teams.get("away", {}),
                "status": status.get("description") or status.get("name"),
                "completed": status.get("completed"),
            }
        )
    print(json.dumps({"league": args.league, "date": args.date, "events": events}, ensure_ascii=False, indent=2))


def cmd_sofascore_scoreboard(args: argparse.Namespace) -> None:
    data = get_json(
        f"{SOFASCORE_API}/sport/basketball/scheduled-events/{args.date}",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.sofascore.com/basketball",
            "Origin": "https://www.sofascore.com",
        },
    )
    include_terms = [term.lower() for term in parse_csv(args.include)] if args.include else []
    exclude_terms = [term.lower() for term in parse_csv(args.exclude)] if args.exclude else []
    rows = []
    for event in data.get("events", []):
        tournament = event.get("tournament") or {}
        unique = tournament.get("uniqueTournament") or {}
        category = tournament.get("category") or {}
        home = event.get("homeTeam") or {}
        away = event.get("awayTeam") or {}
        status = event.get("status") or {}
        home_score = event.get("homeScore") or {}
        away_score = event.get("awayScore") or {}
        hay = " ".join(
            str(x or "")
            for x in (
                tournament.get("name"),
                unique.get("name"),
                category.get("name"),
                home.get("name"),
                away.get("name"),
            )
        ).lower()
        if include_terms and not any(term in hay for term in include_terms):
            continue
        if exclude_terms and any(term in hay for term in exclude_terms):
            continue
        rows.append(
            {
                "source": "SofaScore",
                "event_id": event.get("id"),
                "date": args.date,
                "bj_time": bj_time_from_unix(event.get("startTimestamp")),
                "tournament": unique.get("name") or tournament.get("name") or "",
                "round": (event.get("roundInfo") or {}).get("name") or "",
                "category": category.get("name") or "",
                "home": home.get("name") or "",
                "away": away.get("name") or "",
                "home_score": home_score.get("current", ""),
                "away_score": away_score.get("current", ""),
                "status": status.get("description") or status.get("type") or "",
                "home_id": home.get("id"),
                "away_id": away.get("id"),
                "slug": event.get("slug"),
            }
        )
    print(json.dumps({"source": "SofaScore", "date": args.date, "events": rows}, ensure_ascii=False, indent=2))


def cmd_nba_stats_scoreboard(args: argparse.Namespace) -> None:
    league_id = NBA_STATS_LEAGUES.get(args.league.lower())
    if not league_id:
        raise SystemExit(f"Unsupported league. Use one of: {', '.join(sorted(NBA_STATS_LEAGUES))}")
    data = get_json(
        f"{NBA_STATS_API}/scoreboardv2",
        {"GameDate": args.date, "LeagueID": league_id, "DayOffset": "0"},
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.nba.com/",
            "Origin": "https://www.nba.com",
            "x-nba-stats-origin": "stats",
            "x-nba-stats-token": "true",
        },
    )
    sets = result_sets_to_dicts(data)
    games = []
    line_score = sets.get("LineScore", [])
    score_by_team = {}
    name_by_team = {}
    for row in line_score:
        key = str(row.get("GAME_ID")) + ":" + str(row.get("TEAM_ID"))
        score_by_team[key] = row
        name_by_team[key] = " ".join(
            str(part or "").strip()
            for part in (row.get("TEAM_CITY_NAME"), row.get("TEAM_NICKNAME"))
            if str(part or "").strip()
        ) or row.get("TEAM_ABBREVIATION", "")
    for row in sets.get("GameHeader", []):
        game_id = str(row.get("GAME_ID", ""))
        home_team_id = str(row.get("HOME_TEAM_ID", ""))
        visitor_team_id = str(row.get("VISITOR_TEAM_ID", ""))
        games.append(
            {
                "source": "NBA Stats",
                "league": args.league,
                "league_id": league_id,
                "game_id": game_id,
                "game_date_est": row.get("GAME_DATE_EST") or row.get("GAME_DATE") or "",
                "game_status_text": row.get("GAME_STATUS_TEXT") or "",
                "arena": row.get("ARENA_NAME") or "",
                "home_team_id": home_team_id,
                "away_team_id": visitor_team_id,
                "home": name_by_team.get(game_id + ":" + home_team_id, ""),
                "away": name_by_team.get(game_id + ":" + visitor_team_id, ""),
                "home_score": score_by_team.get(game_id + ":" + home_team_id, {}).get("PTS", ""),
                "away_score": score_by_team.get(game_id + ":" + visitor_team_id, {}).get("PTS", ""),
            }
        )
    print(json.dumps({"source": "NBA Stats", "league": args.league, "date": args.date, "events": games}, ensure_ascii=False, indent=2))


def cmd_thesportsdb_scoreboard(args: argparse.Namespace) -> None:
    data = get_json(f"{THESPORTSDB_API}/eventsday.php", {"d": args.date, "s": "Basketball"})
    include_terms = [term.lower() for term in parse_csv(args.include)] if args.include else []
    rows = []
    for event in data.get("events") or []:
        hay = " ".join(
            str(event.get(key) or "")
            for key in ("strLeague", "strEvent", "strEventAlternate", "strHomeTeam", "strAwayTeam", "strCountry")
        ).lower()
        if include_terms and not any(term in hay for term in include_terms):
            continue
        rows.append(
            {
                "source": "TheSportsDB",
                "event_id": event.get("idEvent"),
                "date": args.date,
                "utc_timestamp": event.get("strTimestamp") or "",
                "bj_time": bj_time_from_iso(event.get("strTimestamp")),
                "league": event.get("strLeague") or "",
                "home": event.get("strHomeTeam") or "",
                "away": event.get("strAwayTeam") or "",
                "home_score": event.get("intHomeScore") or "",
                "away_score": event.get("intAwayScore") or "",
                "status": event.get("strStatus") or "",
                "round": event.get("intRound") or "",
                "season": event.get("strSeason") or "",
                "country": event.get("strCountry") or "",
            }
        )
    print(json.dumps({"source": "TheSportsDB", "date": args.date, "events": rows}, ensure_ascii=False, indent=2))


def cmd_the_odds(args: argparse.Namespace) -> None:
    api_key = args.api_key or os.environ.get("THE_ODDS_API_KEY")
    if not api_key:
        raise SystemExit("Missing THE_ODDS_API_KEY or --api-key")
    data = get_json(
        f"{ODDS_API}/v4/sports/{args.sport}/odds",
        {
            "apiKey": api_key,
            "regions": args.regions,
            "bookmakers": args.bookmakers,
            "markets": args.markets,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
            "commenceTimeFrom": args.commence_from,
            "commenceTimeTo": args.commence_to,
        },
    )
    needle = (args.team or "").lower()
    events = []
    for event in data:
        teams = f"{event.get('home_team', '')} {event.get('away_team', '')}".lower()
        if needle and needle not in teams:
            continue
        books = []
        for book in event.get("bookmakers", []):
            markets = []
            for market in book.get("markets", []):
                outcomes = market.get("outcomes", [])
                item: dict[str, Any] = {"key": market.get("key"), "outcomes": outcomes}
                if market.get("key") == "h2h" and len(outcomes) >= 2:
                    names = [o.get("name", "") for o in outcomes]
                    odds = [float(o.get("price")) for o in outcomes]
                    item["devig"] = devig(names, odds)
                markets.append(item)
            books.append({"key": book.get("key"), "title": book.get("title"), "markets": markets})
        events.append(
            {
                "home_team": event.get("home_team"),
                "away_team": event.get("away_team"),
                "commence_time": event.get("commence_time"),
                "bookmakers": books,
            }
        )
    print(json.dumps(events, ensure_ascii=False, indent=2))


def event_matches(event: dict[str, Any], terms: list[str]) -> bool:
    hay = " ".join(str(event.get(key, "")) for key in ("title", "slug")).lower()
    return all(term.lower() in hay for term in terms)


def cmd_polymarket(args: argparse.Namespace) -> None:
    if args.slug:
        event = get_json(f"{GAMMA}/events/slug/{args.slug}")
    else:
        terms = parse_csv(args.query.replace(" vs ", ",").replace(" v ", ","))
        events = get_json(f"{GAMMA}/events", {"active": "true", "closed": "false", "limit": args.limit})
        matches = [event for event in events if event_matches(event, terms)]
        if args.list:
            print(
                json.dumps(
                    [
                        {
                            "title": event.get("title"),
                            "slug": event.get("slug"),
                            "volume": event.get("volume"),
                            "volume24hr": event.get("volume24hr"),
                            "liquidity": event.get("liquidity"),
                        }
                        for event in matches
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        if not matches:
            print(json.dumps({"matches": []}, ensure_ascii=False, indent=2))
            return
        event = get_json(f"{GAMMA}/events/slug/{matches[0]['slug']}")
    rows = []
    for market in event.get("markets", []):
        try:
            prices = json.loads(market.get("outcomePrices", "[]"))
        except json.JSONDecodeError:
            prices = []
        rows.append(
            {
                "question": market.get("question"),
                "outcome_prices": prices,
                "best_bid": market.get("bestBid"),
                "best_ask": market.get("bestAsk"),
                "last_trade_price": market.get("lastTradePrice"),
                "volume": market.get("volume"),
                "liquidity": market.get("liquidity"),
            }
        )
    print(
        json.dumps(
            {
                "title": event.get("title"),
                "slug": event.get("slug"),
                "volume": event.get("volume"),
                "liquidity": event.get("liquidity"),
                "markets": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Basketball odds helper.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("devig", help="De-vig decimal, American, or HK odds.")
    p.add_argument("--names", required=True, help="Comma-separated outcome names.")
    p.add_argument("--odds", required=True, help="Comma-separated odds.")
    p.add_argument("--format", choices=["decimal", "american", "hk"], default="decimal")
    p.set_defaults(func=cmd_devig)

    p = sub.add_parser("kelly", help="Defensive Kelly helper.")
    p.add_argument("--prob", type=float, required=True, help="True probability from 0 to 1.")
    p.add_argument("--odds", required=True, help="Offered odds.")
    p.add_argument("--format", choices=["decimal", "american", "hk"], default="decimal")
    p.add_argument("--fraction", type=float, default=0.25)
    p.set_defaults(func=cmd_kelly)

    p = sub.add_parser("quant-gate", help="Hard 55%/EV/K/time/fuse/steam gate for basketball spread and totals.")
    p.add_argument("--market", choices=["spread", "total", "team-total"], required=True)
    p.add_argument("--selection", choices=["home", "away", "over", "under"], required=True)
    p.add_argument("--prob-low", type=float, required=True, help="Conservative probability, e.g. 0.56 or 56.")
    p.add_argument("--odds", required=True, help="Offered odds.")
    p.add_argument("--format", choices=["decimal", "american", "hk"], default="decimal")
    p.add_argument("--pred", type=float, required=True, help="Projected home margin for spread, projected points for total.")
    p.add_argument("--line", type=float, required=True, help="Home-team spread or total/team-total line.")
    p.add_argument("--k-points", type=float, default=3.0, help="Minimum directional Line-Pred gap.")
    p.add_argument("--min-prob", type=float, default=0.55)
    p.add_argument("--min-ev-multiplier", type=float, default=1.025)
    p.add_argument("--hours-to-tip", type=float)
    p.add_argument("--line-move-trigger", action="store_true", help="Apply the final-two-hour line-move time lock.")
    p.add_argument("--volatility-last-hour", type=float, help="Point range moved inside final hour.")
    p.add_argument("--steam-aligned", choices=["yes", "no", "unknown"], default="unknown")
    p.add_argument("--stake-cap", type=float, help="Optional max bankroll fraction after quarter Kelly.")
    p.set_defaults(func=cmd_quant_gate)

    p = sub.add_parser("line-audit", help="Audit opening/current/closing line movement and CLV.")
    p.add_argument("--market", choices=["spread", "total", "team-total"], required=True)
    p.add_argument("--selection", choices=["home", "away", "over", "under"], required=True)
    p.add_argument("--entry-line", type=float)
    p.add_argument("--open-line", type=float)
    p.add_argument("--current-line", type=float)
    p.add_argument("--close-line", type=float)
    p.set_defaults(func=cmd_line_audit)

    p = sub.add_parser("estimate-cover", help="Approximate spread cover probability.")
    p.add_argument("--projected-margin", type=float, required=True, help="Projected home minus away margin.")
    p.add_argument("--spread", type=float, required=True, help="Home-team spread, negative if home favorite.")
    p.add_argument("--sigma", type=float, default=12.0)
    p.set_defaults(func=cmd_estimate_cover)

    p = sub.add_parser("estimate-total", help="Approximate over/under probability.")
    p.add_argument("--projected-total", type=float, required=True)
    p.add_argument("--total", type=float, required=True)
    p.add_argument("--sigma", type=float, default=17.0)
    p.set_defaults(func=cmd_estimate_total)

    p = sub.add_parser("espn-scoreboard", help="Read ESPN basketball scoreboard.")
    p.add_argument("--league", choices=sorted(ESPN_LEAGUES), required=True)
    p.add_argument("--date", required=True, help="YYYYMMDD")
    p.set_defaults(func=cmd_espn_scoreboard)

    p = sub.add_parser("sofascore-scoreboard", help="Read global SofaScore basketball scheduled events.")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--include", default="", help="Comma-separated filter terms, e.g. NBA,WNBA,CBA,G League,FIBA.")
    p.add_argument("--exclude", default="", help="Comma-separated terms to exclude.")
    p.set_defaults(func=cmd_sofascore_scoreboard)

    p = sub.add_parser("nba-stats-scoreboard", help="Read NBA Stats scoreboard for NBA/WNBA/Summer/G League.")
    p.add_argument("--league", choices=sorted(NBA_STATS_LEAGUES), required=True)
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.set_defaults(func=cmd_nba_stats_scoreboard)

    p = sub.add_parser("thesportsdb-scoreboard", help="Read TheSportsDB public basketball events by date.")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--include", default="", help="Comma-separated filter terms, e.g. NBA,WNBA,CBA,FIBA.")
    p.set_defaults(func=cmd_thesportsdb_scoreboard)

    p = sub.add_parser("the-odds", help="Read The Odds API basketball odds.")
    p.add_argument("--api-key")
    p.add_argument("--sport", default="basketball_nba")
    p.add_argument("--team")
    p.add_argument("--regions", default="us,eu")
    p.add_argument("--bookmakers", default="")
    p.add_argument("--markets", default="h2h,spreads,totals")
    p.add_argument("--commence-from")
    p.add_argument("--commence-to")
    p.set_defaults(func=cmd_the_odds)

    p = sub.add_parser("polymarket", help="Search/read Polymarket basketball-related event prices.")
    p.add_argument("--query", default="", help='Team query, e.g. "Lakers Celtics".')
    p.add_argument("--slug")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--list", action="store_true")
    p.set_defaults(func=cmd_polymarket)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
