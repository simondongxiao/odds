"""One AS-OF-safe Titan007 data layer shared by the existing V3 and V4.

The fundamental fair line (FFL) deliberately has no Asian-handicap argument.
Current/open Asian prices are read only after FFL and CMFL have been produced.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(r"D:\codex")
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from football_competition_normalizer import competition_domain, normalize_dict  # noqa: E402
DATA_ROOT = ROOT / "data" / "football_titan"
DB_PATH = DATA_ROOT / "titan_football.db"
OUT_ROOT = ROOT / "outputs" / "football_odds_trader" / "titan_data"
TZ = timezone(timedelta(hours=8))
PARSER_VERSION = "titan-shared-v1"
MODEL_VERSION = "FFL_CMFL_DISTRIBUTION_V2"
LOGIC_CHANGE_AT = "2026-10-07T14:06:00+08:00"
CALIBRATION_STATUS = "FAIR_LINE_UNCALIBRATED"
DOMAINS = {
    "CLUB_LEAGUE", "DOMESTIC_CUP", "CONTINENTAL_CLUB", "NATIONAL_OFFICIAL",
    "NATIONAL_YOUTH", "INTERNATIONAL_FRIENDLY", "WOMEN_CLUB", "WOMEN_NATIONAL", "UNKNOWN",
}

# These status values are deliberately orthogonal.  A missing optional input
# must not be collapsed into a model NO_BET or into an unavailable row.
STATUS_FIELDS = (
    "data_integrity", "evidence_coverage", "model_support",
    "calibration_status", "interpretation_status", "decision_status",
)


def clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS raw_ingest(
 snapshot_id TEXT PRIMARY KEY, source TEXT NOT NULL, source_url TEXT, fetch_at TEXT NOT NULL,
 effective_at TEXT NOT NULL, parser_version TEXT NOT NULL, raw_hash TEXT NOT NULL,
 raw_reference TEXT NOT NULL, row_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS competition_master(
 competition_id TEXT PRIMARY KEY, titan_competition_id TEXT, canonical_name TEXT NOT NULL,
 domain TEXT NOT NULL, league_level TEXT NOT NULL, country TEXT, aliases_json TEXT NOT NULL,
 valid_from TEXT NOT NULL, valid_to TEXT
);
CREATE TABLE IF NOT EXISTS season_master(
 season_id TEXT PRIMARY KEY, competition_id TEXT NOT NULL, season_name TEXT, start_date TEXT,
 end_date TEXT, titan_season_id TEXT, FOREIGN KEY(competition_id) REFERENCES competition_master(competition_id)
);
CREATE TABLE IF NOT EXISTS team_master(
 team_id TEXT PRIMARY KEY, titan_team_id TEXT, canonical_name TEXT NOT NULL, country TEXT,
 aliases_json TEXT NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT
);
CREATE TABLE IF NOT EXISTS player_master(
 player_id TEXT PRIMARY KEY, titan_player_id TEXT, team_id TEXT, canonical_name TEXT,
 aliases_json TEXT NOT NULL, valid_from TEXT, valid_to TEXT
);
CREATE TABLE IF NOT EXISTS fixture_master(
 match_id TEXT PRIMARY KEY, titan_match_id TEXT NOT NULL, list_date TEXT NOT NULL,
 competition_id TEXT NOT NULL, season_id TEXT, home_team_id TEXT NOT NULL, away_team_id TEXT NOT NULL,
 kickoff_at TEXT NOT NULL, neutral_venue INTEGER, state TEXT, home_score INTEGER, away_score INTEGER,
 result_available_at TEXT, source_snapshot_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS competition_rules(
 rule_id TEXT PRIMARY KEY, competition_id TEXT NOT NULL, stage TEXT, phase_type TEXT,
 leg_type TEXT, neutral_final INTEGER, extra_time INTEGER, penalties INTEGER,
 qualification_rule TEXT, available_at TEXT NOT NULL, source_snapshot_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS standings_history(
 row_id TEXT PRIMARY KEY, competition_id TEXT NOT NULL, team_id TEXT NOT NULL, as_of_date TEXT,
 available_at TEXT NOT NULL, rank_value TEXT, games INTEGER, wins INTEGER, draws INTEGER, losses INTEGER,
 goals_for INTEGER, goals_against INTEGER, goal_diff INTEGER, points INTEGER,
 home_split_json TEXT, away_split_json TEXT, recent6_json TEXT, source_snapshot_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_match_history(
 row_id TEXT PRIMARY KEY, match_id TEXT NOT NULL, team_id TEXT NOT NULL, opponent_team_id TEXT NOT NULL,
 competition_id TEXT NOT NULL, kickoff_at TEXT NOT NULL, result_available_at TEXT NOT NULL,
 venue TEXT NOT NULL, goals_for INTEGER NOT NULL, goals_against INTEGER NOT NULL, points INTEGER NOT NULL,
 shots INTEGER, shots_on_target INTEGER, possession REAL, corners INTEGER, xg REAL
);
CREATE TABLE IF NOT EXISTS team_strength_history(
 row_id TEXT PRIMARY KEY, team_id TEXT NOT NULL, as_of_at TEXT NOT NULL, elo REAL NOT NULL,
 attack_rating REAL, defense_rating REAL, home_attack REAL, home_defense REAL,
 away_attack REAL, away_defense REAL, sample_count INTEGER NOT NULL, model_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS league_strength_history(
 row_id TEXT PRIMARY KEY, competition_id TEXT NOT NULL, as_of_at TEXT NOT NULL,
 raw_mean_elo REAL, sample_count INTEGER NOT NULL, shrink_target REAL NOT NULL,
 shrink_weight REAL NOT NULL, strength_coefficient REAL NOT NULL, model_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule_history(
 row_id TEXT PRIMARY KEY, match_id TEXT NOT NULL, team_id TEXT NOT NULL, as_of_at TEXT NOT NULL,
 days_since_last REAL, days_until_next REAL, matches_7d INTEGER, matches_14d INTEGER,
 consecutive_away INTEGER, travel_distance_km REAL, congestion_status TEXT
);
CREATE TABLE IF NOT EXISTS cup_match_state(
 row_id TEXT PRIMARY KEY, match_id TEXT NOT NULL, available_at TEXT NOT NULL, stage TEXT,
 leg_type TEXT, aggregate_home INTEGER, aggregate_away INTEGER, qualification_need TEXT,
 source_snapshot_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_snapshots(
 row_id TEXT PRIMARY KEY, match_id TEXT NOT NULL, snapshot_id TEXT NOT NULL, observed_at TEXT NOT NULL,
 bookmaker TEXT, ah_home_line REAL, ah_home_water REAL, ah_away_water REAL,
 ah_open_home_line REAL, ah_open_home_water REAL, ah_open_away_water REAL,
 euro_home REAL, euro_draw REAL, euro_away REAL, euro_open_home REAL, euro_open_draw REAL, euro_open_away REAL,
 total_line REAL, over_water REAL, under_water REAL, total_open_line REAL, total_open_over_water REAL,
 total_open_under_water REAL, source_url TEXT
);
CREATE TABLE IF NOT EXISTS fair_line_snapshots(
 row_id TEXT PRIMARY KEY, match_id TEXT NOT NULL, snapshot_id TEXT NOT NULL, decision_at TEXT NOT NULL,
 ffl_margin REAL, ffl_total REAL, ffl_handicap REAL, ffl_low REAL, ffl_high REAL,
 cmfl_margin REAL, cmfl_total REAL, consensus_margin REAL, disagreement REAL,
 uncertainty REAL, calibration_status TEXT NOT NULL, curve_json TEXT NOT NULL,
 model_version TEXT NOT NULL, input_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_interpretation_snapshots(
 row_id TEXT PRIMARY KEY, match_id TEXT NOT NULL, snapshot_id TEXT NOT NULL, decision_at TEXT NOT NULL,
 h1_fundamental_update REAL, h2_price_discovery REAL, h3_public_bias REAL, h4_liquidity_noise REAL,
 interpretation TEXT NOT NULL, market_quality TEXT NOT NULL, cross_market TEXT,
 cross_book_breadth TEXT, time_order_valid INTEGER, diagnostics_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feature_store_snapshots(
 snapshot_id TEXT PRIMARY KEY, list_date TEXT NOT NULL, decision_at TEXT NOT NULL,
 path TEXT NOT NULL, content_hash TEXT NOT NULL, match_count INTEGER NOT NULL,
 last_team_update TEXT, last_standings_update TEXT, last_schedule_update TEXT, last_odds_update TEXT
);
CREATE INDEX IF NOT EXISTS ix_fixture_kickoff ON fixture_master(kickoff_at);
CREATE INDEX IF NOT EXISTS ix_history_team_time ON team_match_history(team_id,result_available_at);
CREATE INDEX IF NOT EXISTS ix_market_match_time ON market_snapshots(match_id,observed_at);
"""


def _hash(value: Any, n: int = 24) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def _f(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _i(value: Any) -> int | None:
    number = _f(value)
    return int(number) if number is not None else None


def _first(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _dt(value: str, year: int | None = None) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(text)
        return result.astimezone(TZ) if result.tzinfo else result.replace(tzinfo=TZ)
    except ValueError:
        pass
    m = re.search(r"(?:(\d{4})-)?(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", text)
    if not m:
        raise ValueError(f"invalid datetime: {value}")
    return datetime(int(m.group(1) or year or datetime.now().year), *map(int, m.groups()[1:]), tzinfo=TZ)


def _snapshot_at(row: dict[str, Any], path: Path) -> datetime:
    stamp = _first(row, "snapshot_stamp", "latest_snapshot_stamp")
    for fmt in ("%Y%m%d_%H%M%S", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(stamp, fmt).replace(tzinfo=TZ)
        except ValueError:
            pass
    m = re.search(r"(\d{8})_(\d{6})", path.stem)
    return datetime.strptime("".join(m.groups()), "%Y%m%d%H%M%S").replace(tzinfo=TZ) if m else datetime.now(TZ)


def _domain(name: str) -> str:
    info = normalize_dict(name)
    n = name.lower()
    women = any(x in n for x in ("女", "women", "女子"))
    mapped = competition_domain(name)
    if women and mapped in {"NATIONAL_OFFICIAL", "NATIONAL_YOUTH", "INTERNATIONAL_FRIENDLY"}:
        return "WOMEN_NATIONAL"
    if women:
        return "WOMEN_CLUB"
    return {
        "CLUB_CUP": "DOMESTIC_CUP",
        "CLUB_YOUTH": "UNKNOWN",
        "CLUB_FRIENDLY": "INTERNATIONAL_FRIENDLY",
    }.get(mapped, mapped if mapped in DOMAINS else "UNKNOWN")


def _tier(name: str) -> str:
    tier = normalize_dict(name).get("tier")
    return {"T1": "TIER_1", "T2": "TIER_2", "T3": "TIER_3", "T?": "TIER_4_PLUS"}.get(str(tier), "UNKNOWN")


def _poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def margin_distribution(home_lambda: float, away_lambda: float) -> dict[int, float]:
    raw = {}
    for margin in range(-9, 10):
        raw[margin] = sum(
            _poisson(h, home_lambda) * _poisson(a, away_lambda)
            for h in range(15) for a in range(15) if h - a == margin
        )
    total = sum(raw.values()) or 1.0
    return {k: v / total for k, v in raw.items()}


def total_distribution(home_lambda: float, away_lambda: float) -> dict[int, float]:
    """Independent-Poisson total-goal distribution used by the OU fit."""
    raw = {total: sum(_poisson(h, home_lambda) * _poisson(total - h, away_lambda)
                      for h in range(total + 1)) for total in range(0, 19)}
    normalizer = sum(raw.values()) or 1.0
    return {key: value / normalizer for key, value in raw.items()}


def _status(margin: int, handicap: float) -> str:
    value = margin + handicap
    return "W" if value > 1e-9 else "L" if value < -1e-9 else "P"


def asian_states(distribution: dict[int, float], handicap: float) -> dict[str, float]:
    states = {s: 0.0 for s in ("W", "HW", "P", "HL", "L")}
    q = round(handicap * 4)
    parts = [q / 4.0] if q % 2 == 0 else [(q - 1) / 4.0, (q + 1) / 4.0]
    for margin, probability in distribution.items():
        outcome = [_status(margin, part) for part in parts]
        if len(outcome) == 1 or outcome[0] == outcome[-1]:
            state = outcome[0]
        elif set(outcome) == {"W", "P"}:
            state = "HW"
        elif set(outcome) == {"L", "P"}:
            state = "HL"
        elif set(outcome) == {"W", "L"}:
            state = "P"
        else:
            raise AssertionError(outcome)
        states[state] += probability
    return states


def ou_states(distribution: dict[int, float], line: float) -> dict[str, float]:
    """Five-state settlement probabilities for the Over side of an OU line."""
    states = {s: 0.0 for s in ("W", "HW", "P", "HL", "L")}
    q = round(float(line) * 4)
    parts = [q / 4.0] if q % 2 == 0 else [(q - 1) / 4.0, (q + 1) / 4.0]
    for total, probability in distribution.items():
        outcomes = []
        for part in parts:
            adjusted = float(total) - part
            outcomes.append("W" if adjusted > 1e-9 else "L" if adjusted < -1e-9 else "P")
        if len(outcomes) == 1 or outcomes[0] == outcomes[-1]:
            state = outcomes[0]
        elif set(outcomes) == {"W", "P"}:
            state = "HW"
        elif set(outcomes) == {"L", "P"}:
            state = "HL"
        elif set(outcomes) == {"W", "L"}:
            state = "P"
        else:
            raise AssertionError(outcomes)
        states[state] += probability
    return states


def fair_water(states: dict[str, float]) -> float | None:
    win = states["W"] + 0.5 * states["HW"]
    lose = states["L"] + 0.5 * states["HL"]
    return lose / win if win > 1e-12 else None


def fair_curve(distribution: dict[int, float]) -> list[dict[str, Any]]:
    result = []
    for q in range(-18, 19):
        line = q / 4.0
        home = asian_states(distribution, line)
        away_dist = {-m: p for m, p in distribution.items()}
        away = asian_states(away_dist, -line)
        result.append({
            "home_bet_handicap": line, "away_bet_handicap": -line,
            "titan_home_line": -line,
            "home": home, "away": away,
            "home_fair_water_hk": fair_water(home), "away_fair_water_hk": fair_water(away),
        })
    return result


def fair_handicap_summary(distribution: dict[int, float]) -> float | None:
    """Return a display-only curve summary, never a rounded mean margin."""
    curve = fair_curve(distribution)
    candidates = [item for item in curve if item.get("home_fair_water_hk") is not None]
    if not candidates:
        return None
    selected = min(candidates, key=lambda item: abs(math.log(max(float(item["home_fair_water_hk"]), 1e-9))))
    return float(selected["home_bet_handicap"])


def settlement_payoff_vector(handicap: float, water: float, margins: range | list[int] | tuple[int, ...] = range(-9, 10)) -> dict[str, float]:
    """Return the 1U Asian settlement payoff for each integer goal margin.

    The vector is used to compare price terms without inventing a conversion
    such as “0.25 goal equals 0.15 water”.  It is intentionally independent
    of any direction label or team name.
    """
    if water is None or not math.isfinite(float(water)) or float(water) <= 0:
        raise ValueError("water must be a positive finite HK price")
    out: dict[str, float] = {}
    q = round(float(handicap) * 4)
    parts = [q / 4.0] if q % 2 == 0 else [(q - 1) / 4.0, (q + 1) / 4.0]
    for margin in margins:
        results = [_status(int(margin), part) for part in parts]
        if len(results) == 1 or results[0] == results[-1]:
            payoff = {"W": float(water), "P": 0.0, "L": -1.0}[results[0]]
        elif set(results) == {"W", "P"}:
            payoff = 0.5 * float(water)
        elif set(results) == {"L", "P"}:
            payoff = -0.5
        elif set(results) == {"W", "L"}:
            payoff = 0.0
        else:
            raise AssertionError(results)
        out[str(int(margin))] = payoff
    return out


def compare_price_terms(old_handicap: float, old_water: float, new_handicap: float, new_water: float) -> dict[str, Any]:
    """Compare two AH quotes using observable 1U payoff vectors only."""
    old = settlement_payoff_vector(old_handicap, old_water)
    new = settlement_payoff_vector(new_handicap, new_water)
    delta = {margin: round(new[margin] - old[margin], 8) for margin in old}
    if all(value >= -1e-9 for value in delta.values()):
        ordering = "NEW_QUOTE_WEAKLY_BETTER"
    elif all(value <= 1e-9 for value in delta.values()):
        ordering = "OLD_QUOTE_WEAKLY_BETTER"
    else:
        ordering = "TRADEOFF_REQUIRES_PROBABILITY"
    return {"old_payoff": old, "new_payoff": new, "delta": delta, "ordering": ordering}


def _devig_1x2(home: float, draw: float, away: float) -> tuple[float, float, float]:
    values = [1 / home, 1 / draw, 1 / away]
    total = sum(values)
    return tuple(v / total for v in values)


def _outcome_probs(distribution: dict[int, float]) -> tuple[float, float, float]:
    return sum(p for m, p in distribution.items() if m > 0), distribution.get(0, 0.0), sum(p for m, p in distribution.items() if m < 0)


def _devig_binary(over_water: float | None, under_water: float | None) -> tuple[float, float] | None:
    if over_water is None or under_water is None or over_water <= -0.99 or under_water <= -0.99:
        return None
    raw = (1.0 / (1.0 + float(over_water)), 1.0 / (1.0 + float(under_water)))
    total = sum(raw)
    return (raw[0] / total, raw[1] / total) if total > 0 else None


def consensus_market_fair_line(
    euro: tuple[float | None, float | None, float | None],
    total_line: float | None,
    ou_prices: tuple[float | None, float | None] | None = None,
) -> dict[str, Any]:
    """Fit home/away lambdas to de-vig 1X2 and, when present, de-vig OU prices.

    Asian handicap is deliberately absent from this function.  The AH quote is
    read only by the caller after this complete distribution has been produced.
    """
    if any(v is None or v <= 1 for v in euro):
        return {"status": "UNAVAILABLE", "margin": None, "total": total_line, "fit_quality": "UNAVAILABLE"}
    target_1x2 = _devig_1x2(float(euro[0]), float(euro[1]), float(euro[2]))
    target_ou = _devig_binary(*(ou_prices or (None, None)))
    if total_line is None or not 1.0 <= float(total_line) <= 5.5:
        target_ou = None
    best: tuple[float, float, float, float, float, float] | None = None
    observed_total_line = float(total_line) if total_line is not None and 1.0 <= float(total_line) <= 5.5 else 2.5
    # A compact, reproducible grid is preferable to a hidden optimiser here.
    # Keep the daily 200-300 match slate tractable while retaining enough
    # resolution to distinguish OU price information from a pure line bucket.
    if target_ou is not None:
        totals = sorted({round(clamp(observed_total_line + offset, 1.2, 4.8), 2) for offset in (-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0)})
    else:
        totals = [1.4 + 0.4 * index for index in range(9)]
    for total in totals:
        for step in range(-50, 51):
            margin = step / 20.0
            home_lam = max(0.08, (total + margin) / 2)
            away_lam = max(0.08, (total - margin) / 2)
            distribution = margin_distribution(home_lam, away_lam)
            observed_1x2 = _outcome_probs(distribution)
            fit_1x2 = sum((observed_1x2[i] - target_1x2[i]) ** 2 for i in range(3))
            fit_ou = None
            total_goal_distribution = total_distribution(home_lam, away_lam)
            if target_ou is not None:
                ou = ou_states(total_goal_distribution, observed_total_line)
                observed_over = ou["W"] + 0.5 * ou["HW"]
                observed_under = ou["L"] + 0.5 * ou["HL"]
                fit_ou = (observed_over - target_ou[0]) ** 2 + (observed_under - target_ou[1]) ** 2
            combined = fit_1x2 + (fit_ou if fit_ou is not None else 0.0)
            candidate = (combined, fit_1x2, fit_ou if fit_ou is not None else 0.0, home_lam, away_lam, total)
            if best is None or candidate < best:
                best = candidate
    assert best
    combined, fit_1x2, fit_ou_value, home_lam, away_lam, fitted_total = best
    fit_ou = fit_ou_value if target_ou is not None else None
    if target_ou is None:
        fit_quality = "FAIR_1X2_ONLY" if fit_1x2 <= 0.02 else "POOR_FIT"
    elif combined <= 0.02 and fit_1x2 <= 0.015 and fit_ou <= 0.015:
        fit_quality = "GOOD"
    elif combined <= 0.06:
        fit_quality = "FAIR"
    else:
        fit_quality = "POOR_FIT"
    distribution = margin_distribution(home_lam, away_lam)
    return {
        "status": "AVAILABLE",
        "margin": home_lam - away_lam,
        "fair_goal_margin": home_lam - away_lam,
        "fair_handicap": fair_handicap_summary(distribution),
        "total": fitted_total,
        "lambda_home": home_lam,
        "lambda_away": away_lam,
        "margin_distribution": {str(k): v for k, v in distribution.items()},
        "fair_ah_curve": fair_curve(distribution),
        "fit_error": combined,
        "fit_error_1x2": fit_1x2,
        "fit_error_ou": fit_ou,
        "fit_quality": fit_quality,
        "devig_1x2": target_1x2,
        "devig_ou": {"over": target_ou[0], "under": target_ou[1]} if target_ou is not None else None,
        "ou_line": observed_total_line if target_ou is not None else None,
        "ou_prices_used": target_ou is not None,
    }


def fundamental_fair_line(home: dict[str, Any], away: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """FFL: no AH/water arguments by design; uses only pre-match football facts."""
    support = int(home.get("sample_count", 0) or 0) + int(away.get("sample_count", 0) or 0)
    if support < 8:
        return {
            "status": "UNAVAILABLE_OPTIONAL", "reason": "INSUFFICIENT_TEAM_HISTORY",
            "model_version": MODEL_VERSION, "predicted_home_goals": None,
            "predicted_away_goals": None, "fair_goal_margin": None,
            "fair_handicap": None, "fair_handicap_low": None, "fair_handicap_high": None,
            "ffl_mean_margin": None, "ffl_margin_distribution": {}, "ffl_uncertainty": None,
            "ffl_support_level": "UNAVAILABLE", "uncertainty": None, "margin_distribution": {}, "fair_ah_curve": [],
            "inputs": {"home": home, "away": away, "context": context},
        }
    h_elo, a_elo = float(home.get("elo", 1500)), float(away.get("elo", 1500))
    h_att, a_att = float(home.get("attack", 1.0)), float(away.get("attack", 1.0))
    h_def, a_def = float(home.get("defense", 1.0)), float(away.get("defense", 1.0))
    neutral = bool(context.get("neutral_venue"))
    home_adv = 0.0 if neutral else 0.20
    elo_margin = (h_elo - a_elo) / 400.0 * 0.72
    form_margin = 0.18 * (float(home.get("form_ppg", 1.35)) - float(away.get("form_ppg", 1.35)))
    rest_margin = 0.0
    if home.get("days_since_last") is not None and away.get("days_since_last") is not None:
        rest_margin = max(-0.15, min(0.15, (float(home["days_since_last"]) - float(away["days_since_last"])) * 0.025))
    cup_margin = float(context.get("cup_margin_adjustment") or 0.0)
    margin = elo_margin + form_margin + rest_margin + home_adv + cup_margin
    league_strength = float(context.get("league_strength_coefficient") or 1.0)
    total = max(1.55, min(3.8, 2.55 + 0.24 * ((h_att + a_att) - (h_def + a_def)) + 0.10 * (league_strength - 1.0)))
    home_lambda = max(0.08, (total + margin) / 2)
    away_lambda = max(0.08, (total - margin) / 2)
    distribution = margin_distribution(home_lambda, away_lambda)
    sample = int(home.get("sample_count", 0)) + int(away.get("sample_count", 0))
    missing = int(home.get("missing_count", 0)) + int(away.get("missing_count", 0))
    uncertainty = min(0.95, max(0.12, 0.62 / math.sqrt(max(1, sample / 4)) + 0.035 * missing))
    support_level = "HIGH" if sample >= 24 and missing <= 2 else "MEDIUM" if sample >= 12 else "LOW"
    curve = fair_curve(distribution)
    # This is deliberately a curve summary.  It is not round(margin*4)/4.
    curve_summary = fair_handicap_summary(distribution)
    return {
        "status": CALIBRATION_STATUS, "reason": "ASOF_TEAM_HISTORY_SUPPORTED", "model_version": MODEL_VERSION,
        "predicted_home_goals": home_lambda, "predicted_away_goals": away_lambda,
        "fair_goal_margin": margin, "ffl_mean_margin": margin,
        "fair_handicap": curve_summary,
        "fair_handicap_low": None, "fair_handicap_high": None,
        "uncertainty": uncertainty, "ffl_uncertainty": uncertainty,
        "ffl_support_level": support_level,
        "margin_distribution": {str(k): v for k, v in distribution.items()},
        "ffl_margin_distribution": {str(k): v for k, v in distribution.items()},
        "fair_ah_curve": curve,
        "inputs": {"home": home, "away": away, "context": context},
    }


def price_adjusted_gap(market_line: float | None, market_water: float | None, fair_states: dict[str, float] | None) -> float | None:
    if market_line is None or market_water is None or not fair_states:
        return None
    return fair_states["W"] * market_water + 0.5 * fair_states["HW"] * market_water - 0.5 * fair_states["HL"] - fair_states["L"]


def _team_features(conn: sqlite3.Connection, team_id: str, decision_at: str, venue: str) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT kickoff_at,venue,goals_for,goals_against,points FROM team_match_history WHERE team_id=? AND result_available_at<=? ORDER BY kickoff_at DESC LIMIT 20",
        (team_id, decision_at),
    ).fetchall()
    recent = rows[:10]
    form = rows[:5]
    gf = sum(r[2] for r in recent) / len(recent) if recent else 1.25
    ga = sum(r[3] for r in recent) / len(recent) if recent else 1.25
    ppg = sum(r[4] for r in form) / len(form) if form else 1.35
    venue_rows = [r for r in recent if r[1] == venue]
    attack = (sum(r[2] for r in venue_rows) / len(venue_rows)) if venue_rows else gf
    defense = (sum(r[3] for r in venue_rows) / len(venue_rows)) if venue_rows else ga
    elo_row = conn.execute("SELECT elo FROM team_strength_history WHERE team_id=? AND as_of_at<=? ORDER BY as_of_at DESC LIMIT 1", (team_id, decision_at)).fetchone()
    last = _dt(rows[0][0]) if rows else None
    decision = _dt(decision_at)
    return {
        "elo": elo_row[0] if elo_row else 1500.0, "attack": attack, "defense": defense,
        "form_ppg": ppg, "form_5": {"ppg": ppg, "gf": sum(r[2] for r in form) / len(form) if form else None, "ga": sum(r[3] for r in form) / len(form) if form else None},
        "form_10": {"ppg": sum(r[4] for r in recent) / len(recent) if recent else None, "gf": gf if recent else None, "ga": ga if recent else None},
        "days_since_last": (decision - last).total_seconds() / 86400 if last else None,
        "sample_count": len(rows), "missing_count": 2 if not rows else 0,
    }


def _market_diagnostic(row: dict[str, Any], ffl: dict[str, Any] | None, cmfl: dict[str, Any]) -> dict[str, Any]:
    current = _f(_first(row, "ah_full_current_line_or_draw", "xml_ah_line"))
    opening = _f(_first(row, "ah_full_open_line_or_draw", "initial_ah_hint"))
    total = _f(_first(row, "total_full_current_line_or_draw", "xml_total_line"))
    cm = cmfl.get("margin")
    fm = ffl.get("fair_goal_margin") if isinstance(ffl, dict) else None
    line_move = None if current is None or opening is None else current - opening
    cross = "UNKNOWN" if cm is None or fm is None else "CONSENSUS" if abs(cm - fm) <= 0.35 else "DISAGREEMENT"
    h1 = None if line_move is None or fm is None else min(1.0, abs(line_move) / 0.5) * (0.75 if cross == "CONSENSUS" else 0.25)
    h2 = 0.0 if cm is None or current is None else max(0.0, 1.0 - abs(current - cm) / 1.0)
    h3 = None if current is None or fm is None else min(1.0, abs(current - fm) / 1.25) * (0.8 if cross == "DISAGREEMENT" else 0.3)
    h4 = None  # an aggregate quote is not a liquidity or real-flow observation
    if current is None or (h1 is None and h3 is None and h2 == 0.0):
        interpretation = "UNKNOWN"
    else:
        interpretation = "PRICE_OBSERVATION" if h2 >= 0.55 else "MIXED_EVIDENCE"
    quality = "UNKNOWN_SINGLE_AGGREGATE_FEED"
    return {
        "h1_fundamental_update": h1, "h2_price_discovery": h2,
        "h3_public_bias": h3, "h4_liquidity_noise": h4,
        "interpretation": interpretation, "market_quality": quality,
        "cross_market": cross, "cross_book_breadth": "UNKNOWN_SINGLE_AGGREGATE_FEED",
        "time_order_valid": True, "total_line": total, "line_move": line_move,
        "hard_direction_rule": False,
        "evidence_checklist": {
            "observed": [x for x in ("current_line" if current is not None else "", "opening_line" if opening is not None else "", "cmfl" if cm is not None else "") if x],
            "missing": [x for x in ("opening_line" if opening is None else "", "ffl" if fm is None else "", "cross_book_quotes", "real_flow") if x],
            "compatible_explanations": [interpretation] if interpretation not in {"UNKNOWN", "MIXED_EVIDENCE"} else [],
            "unidentifiable": ["bookmaker_intent", "current_net_position"],
        },
    }


def _init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _upsert_source(conn: sqlite3.Connection, path: Path, rows: list[dict[str, str]], fetch_at: datetime) -> str:
    raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    snapshot_id = f"{path.stem}_{raw_hash[:12]}"
    url = _first(rows[0], "source_page", "list_source") if rows else ""
    conn.execute("INSERT OR REPLACE INTO raw_ingest VALUES(?,?,?,?,?,?,?,?,?)", (snapshot_id, "Titan007_PUBLIC", url or None, fetch_at.isoformat(), fetch_at.isoformat(), PARSER_VERSION, raw_hash, str(path), len(rows)))
    return snapshot_id


def _identity(prefix: str, name: str) -> str:
    return f"{prefix}_{_hash(name.lower().strip(), 18)}"


def _ingest(conn: sqlite3.Connection, path: Path, rows: list[dict[str, str]], snapshot_id: str, fetch_at: datetime) -> None:
    for row in rows:
        match_id = str(row.get("match_id", "")).strip()
        competition = _first(row, "league_cn", "league_tw") or "UNKNOWN"
        home, away = _first(row, "home_cn", "home_tw"), _first(row, "away_cn", "away_tw")
        if not match_id or not home or not away:
            continue
        competition_info = normalize_dict(competition)
        canonical_competition = str(competition_info.get("competition_canonical") or competition)
        cid, hid, aid = _identity("C", canonical_competition), _identity("T", home), _identity("T", away)
        list_date = str(row.get("list_date", "") or fetch_at.date().isoformat())
        try:
            kickoff = _dt(_first(row, "bj_time"), int(list_date[:4]))
        except ValueError:
            continue
        conn.execute("INSERT OR IGNORE INTO competition_master VALUES(?,?,?,?,?,?,?,?,?)", (cid, None, canonical_competition, _domain(competition), _tier(competition), competition_info.get("country") or None, json.dumps([competition, canonical_competition], ensure_ascii=False), fetch_at.isoformat(), None))
        phase = "KNOCKOUT_OR_MIXED" if _domain(competition) in {"DOMESTIC_CUP", "CONTINENTAL_CLUB", "NATIONAL_OFFICIAL", "NATIONAL_YOUTH"} else "LEAGUE_OR_GROUP"
        rule_id = _hash([cid, fetch_at.date().isoformat(), "rules"])
        conn.execute("INSERT OR IGNORE INTO competition_rules VALUES(?,?,?,?,?,?,?,?,?,?,?)", (rule_id, cid, None, phase, None, None, None, None, None, fetch_at.isoformat(), snapshot_id))
        for tid, name, alias in ((hid, home, _first(row, "home_tw")), (aid, away, _first(row, "away_tw"))):
            aliases = [x for x in {name, alias} if x]
            conn.execute("INSERT OR IGNORE INTO team_master VALUES(?,?,?,?,?,?,?)", (tid, None, name, None, json.dumps(aliases, ensure_ascii=False), fetch_at.isoformat(), None))
        final = str(row.get("state", "")) == "-1"
        hs, aws = _i(row.get("home_score")), _i(row.get("away_score"))
        result_at = fetch_at.isoformat() if final and hs is not None and aws is not None else None
        conn.execute("INSERT OR REPLACE INTO fixture_master VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (match_id, match_id, list_date, cid, None, hid, aid, kickoff.isoformat(), None, str(row.get("state", "")), hs, aws, result_at, snapshot_id))
        for tid, rank in ((hid, row.get("home_rank_or_stage")), (aid, row.get("away_rank_or_stage"))):
            rid = _hash([cid, tid, fetch_at.isoformat(), rank])
            conn.execute("INSERT OR REPLACE INTO standings_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (rid, cid, tid, fetch_at.date().isoformat(), fetch_at.isoformat(), str(rank or "") or None, None, None, None, None, None, None, None, None, None, None, None, snapshot_id))
        if final and hs is not None and aws is not None:
            for tid, opp, venue, gf, ga in ((hid, aid, "HOME", hs, aws), (aid, hid, "AWAY", aws, hs)):
                points = 3 if gf > ga else 1 if gf == ga else 0
                rid = _hash([match_id, tid])
                conn.execute("INSERT OR IGNORE INTO team_match_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (rid, match_id, tid, opp, cid, kickoff.isoformat(), result_at, venue, gf, ga, points, None, None, None, None, None))
        observed = _snapshot_at(row, path).isoformat()
        market_values = (
            _f(_first(row, "ah_full_current_line_or_draw", "xml_ah_line")), _f(_first(row, "ah_full_current_home_or_over", "xml_ah_home_water")), _f(_first(row, "ah_full_current_away_or_under", "xml_ah_away_water")),
            _f(_first(row, "ah_full_open_line_or_draw", "initial_ah_hint")), _f(row.get("ah_full_open_home_or_over")), _f(row.get("ah_full_open_away_or_under")),
            _f(_first(row, "euro_full_current_home_or_over", "xml_euro_home")), _f(_first(row, "euro_full_current_line_or_draw", "xml_euro_draw")), _f(_first(row, "euro_full_current_away_or_under", "xml_euro_away")),
            _f(row.get("euro_full_open_home_or_over")), _f(row.get("euro_full_open_line_or_draw")), _f(row.get("euro_full_open_away_or_under")),
            _f(_first(row, "total_full_current_line_or_draw", "xml_total_line")), _f(_first(row, "total_full_current_home_or_over", "xml_total_over_water")), _f(_first(row, "total_full_current_away_or_under", "xml_total_under_water")),
            _f(row.get("total_full_open_line_or_draw")), _f(row.get("total_full_open_home_or_over")), _f(row.get("total_full_open_away_or_under")),
        )
        rid = _hash([match_id, snapshot_id, observed])
        conn.execute("INSERT OR REPLACE INTO market_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (rid, match_id, snapshot_id, observed, _first(row, "ah_full_company") or None, *market_values, _first(row, "source_page") or None))


def _replay_elo(conn: sqlite3.Connection, cutoff: str) -> None:
    fixtures = conn.execute("SELECT match_id,home_team_id,away_team_id,kickoff_at,home_score,away_score,result_available_at FROM fixture_master WHERE result_available_at IS NOT NULL AND result_available_at<=? ORDER BY kickoff_at", (cutoff,)).fetchall()
    ratings: defaultdict[str, float] = defaultdict(lambda: 1500.0)
    counts: Counter[str] = Counter()
    for match_id, home, away, kickoff, hs, aws, available in fixtures:
        rh, ra = ratings[home], ratings[away]
        expected = 1 / (1 + 10 ** (-(rh + 55 - ra) / 400))
        actual = 1.0 if hs > aws else 0.5 if hs == aws else 0.0
        change = 18 * (actual - expected)
        ratings[home] += change; ratings[away] -= change; counts[home] += 1; counts[away] += 1
        for team in (home, away):
            rid = _hash([team, available, match_id])
            conn.execute("INSERT OR REPLACE INTO team_strength_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (rid, team, available, ratings[team], None, None, None, None, None, None, counts[team], "DYNAMIC_ELO_V1"))

    # Competition strength is learned from participating-team Elo and shrunk
    # to the global mean.  No permanent hand-written league coefficient exists.
    competition_rows = conn.execute(
        "SELECT f.competition_id,s.elo FROM fixture_master f JOIN team_strength_history s ON s.team_id IN (f.home_team_id,f.away_team_id) WHERE s.as_of_at<=?",
        (cutoff,),
    ).fetchall()
    grouped: defaultdict[str, list[float]] = defaultdict(list)
    for competition_id, elo in competition_rows:
        grouped[competition_id].append(float(elo))
    all_elos = [elo for values in grouped.values() for elo in values]
    global_mean = sum(all_elos) / len(all_elos) if all_elos else 1500.0
    for competition_id in {row[0] for row in conn.execute("SELECT competition_id FROM competition_master").fetchall()}:
        values = grouped.get(competition_id, [])
        raw_mean = sum(values) / len(values) if values else None
        weight = len(values) / (len(values) + 40.0)
        shrunk = global_mean if raw_mean is None else weight * raw_mean + (1 - weight) * global_mean
        coefficient = math.exp((shrunk - global_mean) / 400.0)
        conn.execute("INSERT OR REPLACE INTO league_strength_history VALUES(?,?,?,?,?,?,?,?,?)", (_hash([competition_id, cutoff, "league-strength"]), competition_id, cutoff, raw_mean, len(values), global_mean, weight, coefficient, "ELO_PROMOTION_CUP_SHRINK_V1"))


def _source_row(rows: list[dict[str, str]], match_id: str) -> dict[str, str]:
    return next((row for row in rows if str(row.get("match_id", "")) == match_id), {})


def build_shared_snapshot(raw_csv: Path | str, list_date: str, decision_at: datetime | None = None, db_path: Path = DB_PATH) -> dict[str, Any]:
    raw_csv = Path(raw_csv)
    decision_at = (decision_at or datetime.now(TZ)).astimezone(TZ)
    all_rows = _read_rows(raw_csv)
    rows = [row for row in all_rows if str(row.get("list_date", "")) == list_date]
    if not rows:  # scoped daily CSV may not preserve list_date consistently
        rows = all_rows
    fetch_at = _snapshot_at(rows[0], raw_csv) if rows else decision_at
    DATA_ROOT.mkdir(parents=True, exist_ok=True); OUT_ROOT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    _init(conn)
    raw_snapshot_id = _upsert_source(conn, raw_csv, rows, fetch_at)
    feature_snapshot_id = f"{raw_snapshot_id}_asof_{decision_at.strftime('%Y%m%d_%H%M%S')}"
    _ingest(conn, raw_csv, rows, raw_snapshot_id, fetch_at)
    _replay_elo(conn, decision_at.isoformat())
    features: dict[str, Any] = {}
    fixtures = conn.execute("SELECT f.match_id,c.canonical_name,c.domain,c.league_level,f.home_team_id,f.away_team_id,ht.canonical_name,at.canonical_name,f.kickoff_at,f.neutral_venue FROM fixture_master f JOIN competition_master c ON c.competition_id=f.competition_id JOIN team_master ht ON ht.team_id=f.home_team_id JOIN team_master at ON at.team_id=f.away_team_id WHERE f.list_date=?", (list_date,)).fetchall()
    for match_id, comp, domain, tier, hid, aid, home_name, away_name, kickoff, neutral in fixtures:
        row = _source_row(rows, match_id)
        home = _team_features(conn, hid, decision_at.isoformat(), "HOME")
        away = _team_features(conn, aid, decision_at.isoformat(), "AWAY")
        cup_state = {"stage": None, "leg_type": None, "aggregate": None, "qualification_need": None}
        cid_row = conn.execute("SELECT competition_id FROM fixture_master WHERE match_id=?", (match_id,)).fetchone()
        league_strength_row = conn.execute("SELECT strength_coefficient FROM league_strength_history WHERE competition_id=? AND as_of_at<=? ORDER BY as_of_at DESC LIMIT 1", (cid_row[0], decision_at.isoformat())).fetchone() if cid_row else None
        context = {"competition": comp, "domain": domain, "league_level": tier, "league_strength_coefficient": league_strength_row[0] if league_strength_row else 1.0, "neutral_venue": bool(neutral), "cup_state": cup_state, "cup_margin_adjustment": 0.0}
        ffl = fundamental_fair_line(home, away, context)
        ffl_usable = ffl.get("fair_goal_margin") is not None
        euro = (_f(_first(row, "euro_full_current_home_or_over", "xml_euro_home")), _f(_first(row, "euro_full_current_line_or_draw", "xml_euro_draw")), _f(_first(row, "euro_full_current_away_or_under", "xml_euro_away")))
        total_line = _f(_first(row, "total_full_current_line_or_draw", "xml_total_line"))
        ou_prices = (
            _f(_first(row, "total_full_current_home_or_over", "xml_total_over_water")),
            _f(_first(row, "total_full_current_away_or_under", "xml_total_under_water")),
        )
        cmfl = consensus_market_fair_line(euro, total_line, ou_prices)
        cm_margin = cmfl.get("margin")
        cmfl_usable = cm_margin is not None and cmfl.get("fit_quality") not in {"POOR_FIT", "UNAVAILABLE"}
        ffl_dist = ffl.get("margin_distribution") if ffl_usable else {}
        cmfl_dist = cmfl.get("margin_distribution") if cmfl_usable else {}
        ffl_support = str(ffl.get("ffl_support_level") or "UNAVAILABLE")
        # Do not average two unvalidated models.  Until independent walk-forward
        # weights exist, select the supported primary distribution and expose the
        # reason.  This is explicitly not a 50/50 consensus.
        if ffl_usable and cmfl_usable:
            if ffl_support in {"HIGH", "MEDIUM"} and cmfl.get("fit_quality") == "GOOD":
                selected_model = "FFL_PRIMARY"
                selected_dist = ffl_dist
            else:
                selected_model = "CMFL_PRIMARY"
                selected_dist = cmfl_dist
            consensus_state = "FAIR_MODEL_DISAGREEMENT" if abs(float(ffl["fair_goal_margin"]) - float(cm_margin)) > 0.75 else "PRIMARY_SELECTED_NO_OOT_FUSION"
        elif ffl_usable:
            selected_model, selected_dist, consensus_state = "FFL_PRIMARY", ffl_dist, "FFL_ONLY"
        elif cmfl_usable:
            selected_model, selected_dist, consensus_state = "CMFL_PRIMARY", cmfl_dist, "CMFL_ONLY"
        else:
            selected_model, selected_dist, consensus_state = "MARKET_CONDITIONAL", {}, "NO_FAIR_MODEL"
        consensus = None if not selected_dist else sum(int(k) * float(v) for k, v in selected_dist.items())
        disagreement = None if cm_margin is None or not ffl_usable else abs(ffl["fair_goal_margin"] - float(cm_margin))
        diagnostic = _market_diagnostic(row, ffl, cmfl)
        current_line = _f(_first(row, "ah_full_current_line_or_draw", "xml_ah_line"))
        current_hw = _f(_first(row, "ah_full_current_home_or_over", "xml_ah_home_water"))
        opening_line_value = _f(_first(row, "ah_full_open_line_or_draw", "initial_ah_hint"))
        opening_home_water = _f(row.get("ah_full_open_home_or_over"))
        opening_away_water = _f(row.get("ah_full_open_away_or_under"))
        current_away_water = _f(_first(row, "ah_full_current_away_or_under", "xml_ah_away_water"))
        home_states = asian_states({int(k): v for k, v in selected_dist.items()}, current_line) if current_line is not None and selected_dist else None
        price_terms = None
        current_giving_water = current_hw if current_line is not None and current_line > 0 else current_away_water
        opening_giving_water = opening_home_water if opening_line_value is not None and opening_line_value > 0 else opening_away_water
        if opening_line_value is not None and current_line is not None and opening_giving_water is not None and current_giving_water is not None:
            price_terms = compare_price_terms(-abs(opening_line_value), opening_giving_water, -abs(current_line), current_giving_water)
        kickoff_dt = _dt(kickoff)
        for tid, side, team_feature in ((hid, "HOME", home), (aid, "AWAY", away)):
            next_row = conn.execute("SELECT kickoff_at FROM fixture_master WHERE (home_team_id=? OR away_team_id=?) AND kickoff_at>? AND source_snapshot_id=? ORDER BY kickoff_at LIMIT 1", (tid, tid, kickoff, raw_snapshot_id)).fetchone()
            days_until_next = (_dt(next_row[0]) - kickoff_dt).total_seconds() / 86400 if next_row else None
            history = conn.execute("SELECT kickoff_at,venue FROM team_match_history WHERE team_id=? AND result_available_at<=? ORDER BY kickoff_at DESC LIMIT 14", (tid, decision_at.isoformat())).fetchall()
            matches_7d = sum(0 <= (kickoff_dt - _dt(item[0])).total_seconds() <= 7 * 86400 for item in history)
            matches_14d = sum(0 <= (kickoff_dt - _dt(item[0])).total_seconds() <= 14 * 86400 for item in history)
            consecutive_away = 0
            for item in history:
                if item[1] != "AWAY":
                    break
                consecutive_away += 1
            congestion = "HIGH" if matches_7d >= 3 else "MEDIUM" if matches_7d >= 2 else "LOW" if history else "UNKNOWN"
            conn.execute("INSERT OR REPLACE INTO schedule_history VALUES(?,?,?,?,?,?,?,?,?,?,?)", (_hash([match_id, tid, feature_snapshot_id, "schedule"]), match_id, tid, decision_at.isoformat(), team_feature.get("days_since_last"), days_until_next, matches_7d, matches_14d, consecutive_away, None, congestion))
        if domain in {"DOMESTIC_CUP", "CONTINENTAL_CLUB", "NATIONAL_OFFICIAL", "NATIONAL_YOUTH"}:
            conn.execute("INSERT OR REPLACE INTO cup_match_state VALUES(?,?,?,?,?,?,?,?,?)", (_hash([match_id, feature_snapshot_id, "cup"]), match_id, decision_at.isoformat(), None, None, None, None, None, raw_snapshot_id))
        home_rank = _i(row.get("home_rank_or_stage")); away_rank = _i(row.get("away_rank_or_stage"))
        observed = _snapshot_at(row, raw_csv).isoformat()
        motivation = {
            "status": "TABLE_POSITION_CONTEXT" if home_rank is not None or away_rank is not None else "MISSING",
            "home_rank": home_rank, "away_rank": away_rank,
            "home_state": "TITLE_OR_QUALIFICATION_ZONE" if home_rank is not None and home_rank <= 3 else "TABLE_POSITION_ONLY" if home_rank is not None else "MISSING",
            "away_state": "TITLE_OR_QUALIFICATION_ZONE" if away_rank is not None and away_rank <= 3 else "TABLE_POSITION_ONLY" if away_rank is not None else "MISSING",
            "derived_from_standings": True,
        }
        ffl_feature = dict(ffl)
        ffl_feature.pop("fair_ah_curve", None)
        ffl_feature["fair_ah_curve_storage"] = "SQLite:fair_line_snapshots.curve_json + exports/fair_ah_curve_<snapshot>.json.gz"
        feature = {
            "match_id": match_id, "snapshot_id": feature_snapshot_id, "raw_snapshot_id": raw_snapshot_id, "decision_at": decision_at.isoformat(), "kickoff_at": kickoff,
            "competition": comp, "competition_domain": domain, "league_level": tier,
            "home_team": home_name, "away_team": away_name, "home_team_id": hid, "away_team_id": aid,
            "football_pull": {"home_elo": home["elo"], "away_elo": away["elo"], "elo_diff": home["elo"] - away["elo"], "home_form": home["form_5"], "away_form": away["form_5"], "schedule": {"home_days_since_last": home["days_since_last"], "away_days_since_last": away["days_since_last"]}},
            "public_pull_proxy": {"status": "PROXY_ONLY", "score": None, "is_real_flow": False,
                                  "features": {"home_advantage": not bool(neutral),
                                                "rank_gap": None if home_rank is None or away_rank is None else away_rank - home_rank,
                                                "form_gap": round(home["form_ppg"] - away["form_ppg"], 4)},
                                  "real_flow_status": "MISSING"},
            "cup_match_state": context["cup_state"], "motivation": motivation,
            "lineup": None, "injuries": None, "ffl": ffl_feature, "cmfl": cmfl,
            "fair_line_consensus": {"margin": consensus, "distribution": selected_dist, "source": selected_model, "state": consensus_state, "ffl_weight": 1.0 if selected_model == "FFL_PRIMARY" else 0.0, "cmfl_weight": 1.0 if selected_model == "CMFL_PRIMARY" else 0.0, "disagreement": disagreement},
            "market": {"opening_line": opening_line_value, "current_line": current_line, "home_water": current_hw, "away_water": current_away_water, "price_adjusted_home_gap_ev": price_adjusted_gap(current_line, current_hw, home_states), "price_term_comparison": price_terms},
            "market_deviation": diagnostic, "data_quality": "CORE" if home["sample_count"] + away["sample_count"] < 8 else "MARKET",
            "data_integrity": "PASS" if match_id and kickoff else "FAIL",
            "evidence_coverage": {
                "identity": "AVAILABLE", "kickoff": "AVAILABLE", "asian_market": "AVAILABLE" if current_line is not None else "MISSING",
                "euro_market": "AVAILABLE" if cmfl.get("status") == "AVAILABLE" else "MISSING",
                "team_history": "AVAILABLE" if home["sample_count"] + away["sample_count"] >= 8 else "SPARSE",
                "ffl": "AVAILABLE" if ffl_usable else "MISSING_OPTIONAL",
                "market_path": "TWO_POINT_OBSERVATION" if current_line is not None and _f(_first(row, "ah_full_open_line_or_draw", "initial_ah_hint")) is not None else "STATIC_QUOTE",
                "cross_book_quotes": "MISSING",
                "real_flow": "MISSING",
            },
            "model_support": selected_model,
            "interpretation_status": diagnostic.get("interpretation", "UNKNOWN"),
            "decision_status": "PRICE_EVALUATION_AVAILABLE" if current_line is not None and current_hw is not None and (cmfl.get("status") == "AVAILABLE" or ffl_usable) else "CORE_MARKET_INPUT_MISSING",
            "evidence_checklist": diagnostic.get("evidence_checklist", {}),
            "public_attraction_features": {"status": "PROXY_ONLY", "real_flow": "MISSING", "features": {"home_advantage": not bool(neutral), "rank_gap": None if home_rank is None or away_rank is None else away_rank - home_rank, "form_gap": round(home["form_ppg"] - away["form_ppg"], 4)}},
            "quote_path": {"status": "TWO_POINT_OBSERVATION" if current_line is not None and _f(_first(row, "ah_full_open_line_or_draw", "initial_ah_hint")) is not None else "STATIC_QUOTE", "source": _first(row, "ah_full_company") or "Titan007 aggregate", "source_quote_at": observed, "received_at": fetch_at.isoformat(), "intermediate_quotes": "NOT_OBSERVED"},
            "asof_guard": {"feature_available_at_lte_decision_at": True, "history_cutoff": decision_at.isoformat(), "same_match_snapshot_partition": True},
        }
        features[match_id] = feature
        curve_json = json.dumps(ffl.get("fair_ah_curve", []), ensure_ascii=False, separators=(",", ":"))
        ffl_total = None if ffl.get("predicted_home_goals") is None or ffl.get("predicted_away_goals") is None else ffl["predicted_home_goals"] + ffl["predicted_away_goals"]
        conn.execute("INSERT OR REPLACE INTO fair_line_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (_hash([match_id, feature_snapshot_id, "fair"]), match_id, feature_snapshot_id, decision_at.isoformat(), ffl.get("fair_goal_margin"), ffl_total, ffl.get("fair_handicap"), ffl.get("fair_handicap_low"), ffl.get("fair_handicap_high"), cm_margin, cmfl.get("total"), consensus, disagreement, ffl.get("uncertainty"), CALIBRATION_STATUS, curve_json, MODEL_VERSION, _hash(ffl["inputs"], 64)))
        conn.execute("INSERT OR REPLACE INTO market_interpretation_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (_hash([match_id, feature_snapshot_id, "market"]), match_id, feature_snapshot_id, decision_at.isoformat(), diagnostic["h1_fundamental_update"], diagnostic["h2_price_discovery"], diagnostic["h3_public_bias"], diagnostic["h4_liquidity_noise"], diagnostic["interpretation"], diagnostic["market_quality"], diagnostic["cross_market"], diagnostic["cross_book_breadth"], 1, json.dumps(diagnostic, ensure_ascii=False)))
    out_dir = OUT_ROOT / "feature_store" / list_date
    out_dir.mkdir(parents=True, exist_ok=True)
    odds_age_hours = max(0.0, (decision_at - fetch_at).total_seconds() / 3600.0)
    freshness_status = "PASS" if odds_age_hours <= 12.0 else "STALE"
    payload = {"list_date": list_date, "snapshot_id": feature_snapshot_id, "raw_snapshot_id": raw_snapshot_id, "decision_at": decision_at.isoformat(), "logic_change_at": LOGIC_CHANGE_AT, "implementation_contract_version": "SHARED_FACTS_STATUS_SEPARATION_V1", "calibration_status": CALIBRATION_STATUS, "model_version": MODEL_VERSION, "freshness_check": {"status": freshness_status, "odds_age_hours": round(odds_age_hours, 3), "max_age_hours": 12.0, "last_team_update": fetch_at.isoformat(), "last_standings_update": fetch_at.isoformat(), "last_schedule_update": fetch_at.isoformat(), "last_odds_update": fetch_at.isoformat()}, "source": {"name": "Titan007_PUBLIC", "raw_snapshot_id": raw_snapshot_id, "raw_reference": str(raw_csv), "fetch_at": fetch_at.isoformat(), "parser_version": PARSER_VERSION}, "matches": features}
    target = out_dir / f"{feature_snapshot_id}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = out_dir / "latest.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    conn.execute("INSERT OR REPLACE INTO feature_store_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)", (feature_snapshot_id, list_date, decision_at.isoformat(), str(target), digest, len(features), fetch_at.isoformat(), fetch_at.isoformat(), fetch_at.isoformat(), fetch_at.isoformat()))
    conn.commit()
    health = _write_reports(conn, payload, db_path)
    conn.close()
    return {"ok": True, "snapshot_id": feature_snapshot_id, "raw_snapshot_id": raw_snapshot_id, "path": str(target), "latest": str(latest), "db_path": str(db_path), "matches": len(features), "health": health, "freshness_check": payload["freshness_check"], "calibration_status": CALIBRATION_STATUS}


def load_feature_snapshot(path: Path | str | None = None) -> dict[str, Any]:
    value = Path(path or os.environ.get("TITAN_FEATURE_STORE_PATH", "")) if (path or os.environ.get("TITAN_FEATURE_STORE_PATH")) else None
    if not value or not value.exists():
        return {"matches": {}}
    return json.loads(value.read_text(encoding="utf-8"))


def _write_reports(conn: sqlite3.Connection, payload: dict[str, Any], db_path: Path) -> dict[str, Any]:
    diagnostics = OUT_ROOT / "diagnostics"; diagnostics.mkdir(parents=True, exist_ok=True)
    exports = OUT_ROOT / "exports"; exports.mkdir(parents=True, exist_ok=True)
    tables = ["competition_master", "team_master", "fixture_master", "team_strength_history", "league_strength_history", "standings_history", "schedule_history", "cup_match_state", "market_snapshots", "fair_line_snapshots", "market_interpretation_snapshots"]
    counts = {}
    for table in tables:
        all_cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        counts[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        where = ""
        params: tuple[Any, ...] = ()
        if table in {"fair_line_snapshots", "market_interpretation_snapshots"}:
            where, params = " WHERE snapshot_id=?", (payload["snapshot_id"],)
        elif table in {"schedule_history", "league_strength_history"}:
            where, params = " WHERE as_of_at=?", (payload["decision_at"],)
        elif table == "cup_match_state":
            where, params = " WHERE available_at=?", (payload["decision_at"],)
        if table == "fair_line_snapshots":
            selected_cols = [column for column in all_cols if column != "curve_json"]
            query_cols = ",".join(selected_cols + ["curve_json"])
            raw_rows = conn.execute(f"SELECT {query_cols} FROM {table}{where}", params).fetchall()
            curve_file = exports / f"fair_ah_curve_{payload['snapshot_id']}.json.gz"
            curve_payload: dict[str, Any] = {}
            rows = []
            for raw_row in raw_rows:
                values, curve_text = list(raw_row[:-1]), raw_row[-1]
                match_id = str(values[selected_cols.index("match_id")])
                curve = json.loads(curve_text)
                curve_payload[match_id] = curve
                rows.append(tuple(values + [f"{curve_file.name}#{match_id}", len(curve)]))
            with gzip.open(curve_file, "wt", encoding="utf-8") as handle:
                json.dump({"snapshot_id": payload["snapshot_id"], "curves": curve_payload}, handle, ensure_ascii=False, separators=(",", ":"))
            cols = selected_cols + ["curve_json_reference", "curve_point_count"]
        else:
            cols = all_cols
            rows = conn.execute(f"SELECT * FROM {table}{where}", params).fetchall()
        with (exports / f"{table}.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle); writer.writerow(cols); writer.writerows(rows)
    freshness = payload["source"]["fetch_at"]
    freshness_check = payload.get("freshness_check", {})
    health = {"database": str(db_path), "snapshot_id": payload["snapshot_id"], "list_date": payload["list_date"], "match_count": len(payload["matches"]), "last_team_update": freshness, "last_standings_update": freshness, "last_schedule_update": freshness, "last_odds_update": freshness, "odds_age_hours": freshness_check.get("odds_age_hours"), "freshness_status": freshness_check.get("status", "UNKNOWN"), "table_counts": counts, "status": "HEALTHY_DEGRADED_OPTIONAL_FIELDS" if freshness_check.get("status") == "PASS" else "STALE_SOURCE_DEGRADED_OPTIONAL_FIELDS"}
    (diagnostics / "TITAN_DB_HEALTH.md").write_text("# Titan DB Health\n\n" + "\n".join(f"- {k}: `{v}`" for k, v in health.items()) + "\n\n- 伤停、首发、多公司逐笔盘口当前源未可靠提供，保存为 NULL。\n", encoding="utf-8")
    disagreements = [m for m in payload["matches"].values() if (m["fair_line_consensus"].get("disagreement") or 0) > 0.75]
    (diagnostics / "FAIR_LINE_MONITOR.md").write_text(f"# Fair Line Monitor\n\n- calibration: `{CALIBRATION_STATUS}`\n- matches: {len(payload['matches'])}\n- FFL/CMFL large disagreements: {len(disagreements)}\n- FFL Asian-handicap dependency: `NONE`\n- CMFL sources: `de-vig 1X2 + O/U only`\n- Closing line: benchmark only, never a feature.\n", encoding="utf-8")
    return health
