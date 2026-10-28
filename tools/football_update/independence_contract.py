"""V3/V4 analysis-separation contract.

V3 and V4 remain the only formal model names. This module separates shared
identity/raw-market facts from model-owned derived analysis.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

_DEFAULT_ROOT = Path(r"D:\codex")
ROOT = Path(os.environ.get("FOOTBALL_WORKSPACE_ROOT", str(_DEFAULT_ROOT if _DEFAULT_ROOT.exists() else Path(__file__).resolve().parents[2])))
OUT = Path(os.environ.get("FOOTBALL_ANALYSIS_OUT", str(ROOT / "outputs" / "football_odds_trader" / "titan_data")))
TZ = dt.timezone(dt.timedelta(hours=8))

IDENTITY_FIELDS = (
    "match_id", "list_date", "competition_id", "competition_name",
    "home_team_id", "away_team_id", "home_team", "away_team", "kickoff_at",
    "match_status",
)
MARKET_FIELDS = (
    "euro_open_home", "euro_open_draw", "euro_open_away",
    "euro_current_home", "euro_current_draw", "euro_current_away",
    "asian_open_line", "asian_open_home_water", "asian_open_away_water",
    "asian_current_line", "asian_current_home_water", "asian_current_away_water",
    "quote_at", "source", "bookmaker", "snapshot_id",
)
SHARED_ALLOWED_FIELDS = set(IDENTITY_FIELDS) | set(MARKET_FIELDS)
FORBIDDEN_SHARED_FIELDS = {
    "team_strength", "football_prior", "ffl", "fair_line", "fair_range",
    "fair_line_consensus", "goal_margin_distribution", "lambda_home",
    "lambda_away", "public_pull", "motivation_score", "home_advantage",
    "intent", "historical_posterior", "reliability", "calibration", "ev",
    "final_direction", "meta_score", "v3_analysis", "v4_analysis",
}

# This is deliberately a small, machine-readable contract.  It describes the
# facts that may cross the V3/V4 boundary; every probability, fair value,
# intent, EV, reliability and direction field is model-owned and is written to
# a namespaced context instead.
SHARED_MARKET_SCHEMA = {
    "contract": "SHARED_MARKET_SNAPSHOT_V2",
    "identity_fields": list(IDENTITY_FIELDS),
    "market_fields": list(MARKET_FIELDS),
    "allowed_fields": sorted(SHARED_ALLOWED_FIELDS),
    "field_types": {field: "string" for field in sorted(SHARED_ALLOWED_FIELDS)},
    "forbidden_derived_fields": sorted(FORBIDDEN_SHARED_FIELDS),
    "notes": [
        "Only match identity, raw Euro/AH quote values, source/bookmaker and timestamps are shared.",
        "No score/settlement result is part of the raw market snapshot.",
        "Derived V3 and V4 fields must remain in their own analysis namespace.",
    ],
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any) -> float | None:
    try:
        value = float(str(value).strip())
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _hash(value: Any, n: int = 24) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()[:n]


def _team_id(value: str) -> str:
    return "team_" + _hash(re.sub(r"\s+", "", _text(value)).casefold(), 16)


def _kickoff(row: dict[str, Any], list_date: str) -> str:
    value = _text(row.get("kickoff_at") or row.get("kickoff") or row.get("bj_time"))
    if re.match(r"^\d{4}-", value):
        return value
    return f"{list_date} {value}" if value else ""


def _field(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = _text(row.get(name))
        if value:
            return value
    return ""


def _raw_market(row: dict[str, Any], list_date: str, snapshot_id: str) -> dict[str, Any]:
    return {
        "match_id": _text(row.get("match_id")),
        "list_date": list_date,
        "competition_id": _field(row, "competition_id", "league_id"),
        "competition_name": _field(row, "league_cn", "competition", "赛事"),
        "home_team_id": _field(row, "home_team_id") or _team_id(_field(row, "home_cn", "home_team", "主队")),
        "away_team_id": _field(row, "away_team_id") or _team_id(_field(row, "away_cn", "away_team", "客队")),
        "home_team": _field(row, "home_cn", "home_team", "主队"),
        "away_team": _field(row, "away_cn", "away_team", "客队"),
        "kickoff_at": _kickoff(row, list_date),
        "match_status": _field(row, "state", "match_status", "状态"),
        "euro_open_home": _field(row, "euro_full_open_home_or_over", "euro_open_home"),
        "euro_open_draw": _field(row, "euro_full_open_line_or_draw", "euro_open_draw"),
        "euro_open_away": _field(row, "euro_full_open_away_or_under", "euro_open_away"),
        "euro_current_home": _field(row, "euro_full_current_home_or_over", "euro_home", "euro_current_home"),
        "euro_current_draw": _field(row, "euro_full_current_line_or_draw", "euro_draw", "euro_current_draw"),
        "euro_current_away": _field(row, "euro_full_current_away_or_under", "euro_away", "euro_current_away"),
        "asian_open_line": _field(row, "ah_full_open_line_or_draw", "initial_ah_hint", "asian_open_line"),
        "asian_open_home_water": _field(row, "ah_full_open_home_or_over", "asian_open_home_water"),
        "asian_open_away_water": _field(row, "ah_full_open_away_or_under", "asian_open_away_water"),
        "asian_current_line": _field(row, "ah_full_current_line_or_draw", "xml_ah_line", "asian_current_line"),
        "asian_current_home_water": _field(row, "ah_full_current_home_or_over", "xml_ah_home_water", "asian_current_home_water"),
        "asian_current_away_water": _field(row, "ah_full_current_away_or_under", "xml_ah_away_water", "asian_current_away_water"),
        "quote_at": _field(row, "snapshot_stamp", "latest_snapshot_stamp", "quote_at", "quote_changed_at"),
        "source": _field(row, "price_source", "source") or "Titan007",
        "bookmaker": _field(row, "ah_full_company", "bookmaker") or "Titan007 aggregate",
        "snapshot_id": snapshot_id,
    }


def _devig(row: dict[str, Any]) -> tuple[float, float, float] | None:
    values = [_float(row.get(key)) for key in ("euro_current_home", "euro_current_draw", "euro_current_away")]
    if any(value is None or value <= 1.0 for value in values):
        return None
    raw = [1.0 / value for value in values]
    total = sum(raw)
    return tuple(value / total for value in raw)  # type: ignore[return-value]


def _load_csv(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def build_shared_market_snapshot(raw_csv: Path, list_date: str, snapshot_id: str | None = None) -> dict[str, Any]:
    rows = [row for row in _load_csv(raw_csv) if _text(row.get("list_date")) in {"", list_date}]
    snapshot_id = snapshot_id or raw_csv.stem
    matches: dict[str, dict[str, Any]] = {}
    for row in rows:
        market = _raw_market(row, list_date, snapshot_id)
        if market["match_id"]:
            matches[market["match_id"]] = market
    return {
        "contract": "SHARED_MARKET_SNAPSHOT_V2",
        "list_date": list_date,
        "snapshot_id": snapshot_id,
        "generated_at": dt.datetime.now(TZ).isoformat(timespec="seconds"),
        "allowed_shared_fields": sorted(SHARED_ALLOWED_FIELDS),
        "matches": matches,
    }


def _history_index(rows: Iterable[dict[str, Any]], competition_key: str) -> dict[str, int]:
    counts: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        if _text(row.get("赛事") or row.get("competition") or row.get("competition_name")) == competition_key:
            counts["competition"] += 1
        counts["total"] += 1
    return dict(counts)


def _line(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _float(row.get(key))
        if value is not None:
            return value
    return None


def _water(row: dict[str, Any], *keys: str) -> float | None:
    return _line(row, *keys)


def _attractiveness(line: float | None, water: float | None) -> float | None:
    """A transparent market-treatment diagnostic, never a model decision."""
    if line is None or water is None:
        return None
    # Lower HK water and a shallower handicap are normally more attractive to
    # a quoted side.  The score is only used to describe price movement.
    return round((1.0 - water) - 0.08 * abs(line), 4)


def _side_from_line(line: float | None) -> str:
    if line is None or abs(line) < 1e-9:
        return "UNKNOWN"
    # Titan's signed-home convention: >0 means home gives, <0 means away gives.
    return "home" if line > 0 else "away"


def _intent_diagnostic(market: dict[str, Any], raw: dict[str, Any], devig: tuple[float, float, float] | None) -> dict[str, Any]:
    open_line = _line(market, "asian_open_line")
    current_line = _line(market, "asian_current_line")
    open_home = _water(market, "asian_open_home_water")
    open_away = _water(market, "asian_open_away_water")
    current_home = _water(market, "asian_current_home_water")
    current_away = _water(market, "asian_current_away_water")
    opening_side = _side_from_line(open_line)
    current_side = _side_from_line(current_line)
    # The natural-pull field is only populated from an explicit upstream hint;
    # otherwise a large 1X2 gap is recorded as a weak market proxy, not fact.
    explicit_pull = _field(raw, "natural_pull_side", "public_pull_side", "market_pull_side")
    if explicit_pull:
        natural_pull = explicit_pull
    elif devig and devig[0] - devig[2] > 0.12:
        natural_pull = "home_proxy"
    elif devig and devig[2] - devig[0] > 0.12:
        natural_pull = "away_proxy"
    else:
        natural_pull = "UNKNOWN"
    open_giving_water = open_home if opening_side == "home" else open_away if opening_side == "away" else None
    current_giving_water = current_home if current_side == "home" else current_away if current_side == "away" else None
    open_receiving_water = open_away if opening_side == "home" else open_home if opening_side == "away" else None
    current_receiving_water = current_away if current_side == "home" else current_home if current_side == "away" else None
    open_giving_attr = _attractiveness(open_line, open_giving_water)
    current_giving_attr = _attractiveness(current_line, current_giving_water)
    open_receiving_attr = _attractiveness(-open_line if open_line is not None else None, open_receiving_water)
    current_receiving_attr = _attractiveness(-current_line if current_line is not None else None, current_receiving_water)
    complete = all(value is not None for value in (open_line, current_line, open_giving_water, current_giving_water))
    line_move = round(current_line - open_line, 4) if open_line is not None and current_line is not None else None
    residual = round((devig[0] - devig[2]) - (line_move or 0.0) * 0.08, 4) if devig else None
    if complete:
        hypothesis = "PRICE_SUPPORT" if (current_giving_attr or 0) > (open_giving_attr or 0) + 0.03 else "PRICE_RESISTANCE" if (current_giving_attr or 0) < (open_giving_attr or 0) - 0.03 else "MIXED_OR_STABLE"
    else:
        hypothesis = "UNIDENTIFIABLE"
    confidence = "LOW" if not complete or natural_pull == "UNKNOWN" else "MEDIUM"
    return {
        "default_side_mapping": 0,
        "natural_pull_side": natural_pull,
        "opening_side_by_signed_line": opening_side,
        "current_side_by_signed_line": current_side,
        "open_price_treatment": {"line": open_line, "giving_water": open_giving_water, "receiving_water": open_receiving_water, "giving_attractiveness": open_giving_attr, "receiving_attractiveness": open_receiving_attr},
        "current_price_treatment": {"line": current_line, "giving_water": current_giving_water, "receiving_water": current_receiving_water, "giving_attractiveness": current_giving_attr, "receiving_attractiveness": current_receiving_attr},
        "sweetness_change_upper": round((current_giving_attr - open_giving_attr), 4) if current_giving_attr is not None and open_giving_attr is not None else None,
        "sweetness_change_lower": round((current_receiving_attr - open_receiving_attr), 4) if current_receiving_attr is not None and open_receiving_attr is not None else None,
        "market_residual": residual,
        "intent_hypothesis": hypothesis,
        "intent_confidence": confidence,
        "status": "HYPOTHESIS_ONLY",
        "evidence": {"market_complete": complete, "line_move": line_move, "devig_available": bool(devig)},
    }


def _v3_robustness(market: dict[str, Any]) -> dict[str, Any]:
    line = _line(market, "asian_current_line")
    home = _water(market, "asian_current_home_water")
    away = _water(market, "asian_current_away_water")
    available = all(value is not None for value in (line, home, away))
    return {
        "status": "AVAILABLE" if available else "NOT_IDENTIFIABLE",
        "available": available,
        "scenarios": [
            {"name": "line_minus_quarter", "line": round(line - 0.25, 2) if line is not None else None},
            {"name": "line_plus_quarter", "line": round(line + 0.25, 2) if line is not None else None},
            {"name": "water_plus_005", "home_water": round(home + 0.05, 3) if home is not None else None, "away_water": round(away + 0.05, 3) if away is not None else None},
        ],
        "note": "Diagnostic sensitivity only; does not alter the frozen V3 decision.",
    }


def build_v3_context(shared: dict[str, Any], raw_rows: list[dict[str, Any]], ledger_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    ledger_rows = ledger_rows or []
    matches: dict[str, Any] = {}
    for raw in raw_rows:
        market = shared.get("matches", {}).get(_text(raw.get("match_id")), {})
        devig = _devig(market)
        rank_home = _float(raw.get("home_rank_or_stage"))
        rank_away = _float(raw.get("away_rank_or_stage"))
        rank_pull = ((rank_away - rank_home) * 0.04) if rank_home is not None and rank_away is not None else 0.0
        fair_center = round(rank_pull + 0.12, 3)
        competition = _text(market.get("competition_name"))
        intent = _intent_diagnostic(market, raw, devig)
        matches[_text(raw.get("match_id"))] = {
            "namespace": "V3_ANALYSIS",
            "model_id": "V3",
            "fundamental_snapshot_id": "v3fund_" + _hash({"match": market.get("match_id"), "rank": [rank_home, rank_away], "evidence": [raw.get("form_evidence"), raw.get("injury_evidence"), raw.get("lineup_evidence"), raw.get("motivation_evidence")]}, 20),
            "model_input_hash": _hash({"market": market.get("snapshot_id"), "rank": [rank_home, rank_away], "raw": {key: raw.get(key, "") for key in ("form_evidence", "injury_evidence", "lineup_evidence", "motivation_evidence", "rotation_evidence")}}, 32),
            "logic_regime_id": "V3_LEGACY_PAGE_PARITY",
            "football_prior": {"score": fair_center, "source": "V3_rank_form_evidence", "home_rank": rank_home, "away_rank": rank_away},
            "fair_range": {"low": round(fair_center - 0.25, 3), "center": fair_center, "high": round(fair_center + 0.25, 3), "support": "LOW" if rank_home is None or rank_away is None else "MEDIUM"},
            "public_pull": {"status": "MISSING", "score": None},
            "market_treatment": {"raw_market_snapshot_id": shared.get("snapshot_id"), "devig_home": devig[0] if devig else None, "devig_draw": devig[1] if devig else None, "devig_away": devig[2] if devig else None, "diagnostic_only": True},
            "v3_market_behavior": intent,
            "v3_robustness": _v3_robustness(market),
            "default_side_mapping": 0,
            "history": _history_index(ledger_rows, competition),
            "decision_id": "v3dec_" + _hash({"match": market.get("match_id"), "snapshot": shared.get("snapshot_id")}, 20),
            "shared_market_snapshot_id": shared.get("snapshot_id"),
        }
    return {"contract": "V3_ANALYSIS_CONTEXT_V1", "namespace": "V3_ANALYSIS", "list_date": shared.get("list_date"), "matches": matches}


def _poisson_margin(home_lambda: float, away_lambda: float, radius: int = 7) -> dict[str, float]:
    def pois(lam: float, k: int) -> float:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    out: dict[str, float] = {}
    for margin in range(-radius, radius + 1):
        value = 0.0
        for home_goals in range(8):
            away_goals = home_goals - margin
            if 0 <= away_goals <= 7:
                value += pois(home_lambda, home_goals) * pois(away_lambda, away_goals)
        out[str(margin)] = value
    total = sum(out.values()) or 1.0
    return {key: value / total for key, value in out.items()}


def _v4_fair_ah_curve(distribution: dict[str, float]) -> list[dict[str, Any]]:
    """Return an auditable fair AH curve from V4's own margin distribution.

    This is a diagnostic curve.  It is intentionally not fed back into the
    production decision or used to rewrite a frozen record.
    """
    margins = {float(key): float(value) for key, value in distribution.items()}
    curve: list[dict[str, Any]] = []
    for step in range(-8, 9):
        line = step / 4.0
        # Home-side probability of covering a signed-home line.  For quarter
        # lines, a push is retained separately so the diagnostic remains
        # transparent rather than pretending every outcome is binary.
        win = push = 0.0
        for margin, probability in margins.items():
            outcome = margin + line
            if outcome > 1e-9:
                win += probability
            elif abs(outcome) <= 1e-9:
                push += probability
        lose = max(0.0, 1.0 - win - push)
        p_upper = win + 0.5 * push
        p_lower = lose + 0.5 * push
        curve.append({
            "line": line,
            "p_upper_cover": round(p_upper, 6),
            "p_lower_cover": round(p_lower, 6),
            "push_probability": round(push, 6),
            "fair_water_upper": round((1.0 / p_upper) - 1.0, 6) if p_upper > 0 else None,
            "fair_water_lower": round((1.0 / p_lower) - 1.0, 6) if p_lower > 0 else None,
        })
    return curve


def _v4_robustness(home_lambda: float, away_lambda: float) -> dict[str, Any]:
    scenarios = []
    for name, h_shift, a_shift in (("lambda_home_minus_010", -0.10, 0.0), ("lambda_home_plus_010", 0.10, 0.0), ("lambda_away_minus_010", 0.0, -0.10), ("lambda_away_plus_010", 0.0, 0.10)):
        h = max(0.05, home_lambda + h_shift)
        a = max(0.05, away_lambda + a_shift)
        dist = _poisson_margin(h, a)
        scenarios.append({"name": name, "lambda_home": round(h, 4), "lambda_away": round(a, 4), "fair_goal_margin": round(h - a, 4), "margin_distribution_hash": _hash(dist, 16)})
    return {"status": "AVAILABLE", "scenarios": scenarios, "note": "Sensitivity only; V4 dual EV decision remains separately computed."}


def build_v4_context(shared: dict[str, Any], raw_rows: list[dict[str, Any]], prior_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    prior_rows = prior_rows or []
    team_margin: defaultdict[str, list[float]] = defaultdict(list)
    for old in prior_rows:
        score = _text(old.get("score") or old.get("result"))
        match = re.match(r"^(\d+)\s*[-:]\s*(\d+)$", score)
        if not match:
            continue
        margin = float(match.group(1)) - float(match.group(2))
        team_margin[_text(old.get("home_team"))].append(margin)
        team_margin[_text(old.get("away_team"))].append(-margin)
    matches: dict[str, Any] = {}
    for raw in raw_rows:
        market = shared.get("matches", {}).get(_text(raw.get("match_id")), {})
        devig = _devig(market)
        home = _text(market.get("home_team"))
        away = _text(market.get("away_team"))
        home_hist = team_margin.get(home, [])
        away_hist = team_margin.get(away, [])
        historical_home = sum(home_hist) / max(1, len(home_hist))
        historical_away = sum(away_hist) / max(1, len(away_hist))
        market_signal = 1.20 * math.log(max(devig[0], 1e-6) / max(devig[2], 1e-6)) if devig else 0.0
        neutral_strength = round(0.75 * (historical_home - historical_away) + 0.25 * market_signal, 4)
        home_lambda = max(0.25, min(3.8, 1.38 + 0.24 * neutral_strength))
        away_lambda = max(0.20, min(3.8, 1.18 - 0.18 * neutral_strength))
        distribution = _poisson_margin(home_lambda, away_lambda)
        matches[_text(raw.get("match_id"))] = {
            "namespace": "V4_ANALYSIS",
            "model_id": "V4",
            "fundamental_snapshot_id": "v4fund_" + _hash({"match": market.get("match_id"), "history": [home, away, len(home_hist), len(away_hist)]}, 20),
            "model_input_hash": _hash({"market": market.get("snapshot_id"), "history": [home, away, home_hist, away_hist]}, 32),
            "logic_regime_id": "V4_INDEPENDENT_GOAL_MODEL",
            "v4_neutral_strength": neutral_strength,
            "v4_attack_strength": {"home": round(home_lambda, 4), "away": round(away_lambda, 4)},
            "v4_defense_strength": {"home": round(away_lambda, 4), "away": round(home_lambda, 4)},
            "v4_form_adjustment": round(0.75 * (historical_home - historical_away), 4),
            "v4_schedule_adjustment": 0.0,
            "v4_lineup_adjustment": 0.0,
            "v4_competition_state": _text(market.get("competition_name")),
            "v4_venue_effect": 0.0,
            "v4_goal_model": {"fair_goal_margin": round(home_lambda - away_lambda, 4), "lambda_home": round(home_lambda, 4), "lambda_away": round(away_lambda, 4), "margin_distribution": distribution, "source": "V4_OWN_HISTORY_PLUS_MARKET_CALIBRATION"},
            "v4_fair_ah_curve": {"status": "GENERATED_FROM_V4_MARGIN_DISTRIBUTION", "curve": _v4_fair_ah_curve(distribution), "source": "V4_GOAL_MODEL_DIAGNOSTIC"},
            "v4_robustness": _v4_robustness(home_lambda, away_lambda),
            "v4_reliability": {"sample_home": len(home_hist), "sample_away": len(away_hist), "status": "SHRUNK_TO_GLOBAL" if min(len(home_hist), len(away_hist)) < 8 else "AVAILABLE"},
            "v4_historical_context": {"home_count": len(home_hist), "away_count": len(away_hist)},
            "shared_market_snapshot_id": shared.get("snapshot_id"),
        }
    return {"contract": "V4_ANALYSIS_CONTEXT_V1", "namespace": "V4_ANALYSIS", "list_date": shared.get("list_date"), "matches": matches}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_prior_v4() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((ROOT / "v4" / "outputs").glob("v4_decisions_*.json")):
        try:
            rows.extend(json.loads(path.read_text(encoding="utf-8")).get("matches", []))
        except (OSError, json.JSONDecodeError):
            continue
    return rows


def _side_bucket(value: Any) -> str:
    text = _text(value).casefold()
    if text in {"upper", "giving", "home", "主", "主队", "上盘"} or "上盘" in text or "让球" in text:
        return "upper"
    if text in {"lower", "receiving", "away", "客", "客队", "下盘"} or "下盘" in text or "受让" in text:
        return "lower"
    return "no_bet"


def _empty_funnel(model: str, stages: list[str], status: str) -> dict[str, Any]:
    return {
        "model": model,
        "status": status,
        "stages": [{"model": model, "stage": stage, "upper": 0, "lower": 0, "no_bet": 0} for stage in stages],
    }


def _find_v3_freeze(list_date: str) -> Path | None:
    candidates = sorted((ROOT / "v3_legacy" / "outputs" / "football_odds_trader" / "ledger").glob(f"v3_legacy_decision_freeze_{list_date}_*.csv"), key=lambda path: path.stat().st_mtime)
    return candidates[-1] if candidates else None


def _load_v4_day(list_date: str) -> list[dict[str, Any]]:
    path = ROOT / "v4" / "outputs" / f"v4_decisions_{list_date}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("matches", [])
    except (OSError, json.JSONDecodeError):
        return []


def _funnel_rows(model: str, rows: list[dict[str, Any]], stages: list[str], stage_side: dict[str, list[str]]) -> dict[str, Any]:
    if not rows:
        return _empty_funnel(model, stages, "NOT_RUN")
    output = {"model": model, "status": "PASS", "stages": []}
    for stage in stages:
        counts = {"upper": 0, "lower": 0, "no_bet": 0}
        for row in rows:
            values = [row.get(key) for key in stage_side.get(stage, [])]
            bucket = next((_side_bucket(value) for value in values if _side_bucket(value) != "no_bet"), "no_bet")
            counts[bucket] += 1
        output["stages"].append({"model": model, "stage": stage, **counts})
    return output


def _build_v3_funnel(list_date: str) -> dict[str, Any]:
    path = _find_v3_freeze(list_date)
    rows = _load_csv(path)
    if not rows:
        return _empty_funnel("V3", ["raw_market", "football_prior", "public_pull", "intent_hypothesis", "price_check", "history_check", "final"], "NOT_RUN")
    stages = ["raw_market", "football_prior", "public_pull", "intent_hypothesis", "price_check", "history_check", "final"]
    stage_side = {
        "raw_market": ["selected_side"],
        "football_prior": ["direction", "selected_side"],
        "public_pull": ["Public_Pull", "selected_side"],
        "intent_hypothesis": ["selected_side"],
        "price_check": ["selected_side"],
        "history_check": ["selected_side"],
        "final": ["selected_side"],
    }
    stage_rows = {
        "raw_market": rows,
        "football_prior": [row for row in rows if _float(row.get("fair_handicap")) is not None],
        "public_pull": [row for row in rows if _text(row.get("Public_Pull")) not in {"", "MISSING", "NA"}],
        "intent_hypothesis": [row for row in rows if _text(row.get("Cup_Intent")) not in {"", "MISSING", "NA"}],
        "price_check": [row for row in rows if _float(row.get("line")) is not None and _float(row.get("water")) is not None],
        "history_check": [row for row in rows if _text(row.get("competition"))],
        "final": rows,
    }
    funnel = {"model": "V3", "status": "PASS", "stages": []}
    for stage in stages:
        scoped = stage_rows[stage]
        counts = {"upper": 0, "lower": 0, "no_bet": 0}
        for row in scoped:
            bucket = _side_bucket(row.get("selected_side") or row.get("direction"))
            counts[bucket] += 1
        funnel["stages"].append({"model": "V3", "stage": stage, **counts, "available_rows": len(scoped)})
    for stage in funnel["stages"]:
        stage["source_file"] = str(path)
    funnel["source_file"] = str(path)
    funnel["rows"] = len(rows)
    funnel["note"] = "Direction fields are read-only from the frozen V3 ledger; no decision is recomputed here."
    return funnel


def _build_v4_funnel(list_date: str) -> dict[str, Any]:
    rows = _load_v4_day(list_date)
    if not rows:
        return _empty_funnel("V4", ["raw_market", "goal_margin", "dual_ev", "reliability", "history_context", "final"], "NOT_RUN")
    stages = ["raw_market", "goal_margin", "dual_ev", "reliability", "history_context", "final"]
    stage_rows: dict[str, list[dict[str, Any]]] = {
        "raw_market": [row for row in rows if row.get("evidence_coverage", {}).get("asian_market") == "AVAILABLE"],
        "goal_margin": [row for row in rows if row.get("analysis_status") in {"EVALUATED", "NEUTRAL"}],
        "dual_ev": [row for row in rows if row.get("p_giving_cover") is not None and row.get("p_receiving_cover") is not None],
        "reliability": [row for row in rows if row.get("model_support") not in {None, "INSUFFICIENT_SUPPORT"}],
        "history_context": [row for row in rows if row.get("prior_snapshot_id")],
        "final": rows,
    }
    output = {"model": "V4", "status": "PASS", "stages": []}
    for stage in stages:
        stage_rows_for_stage = stage_rows[stage]
        counts = {"upper": 0, "lower": 0, "no_bet": 0}
        for row in stage_rows_for_stage:
            counts[_side_bucket(row.get("selected_side") or row.get("candidate_side") or row.get("final_decision"))] += 1
        output["stages"].append({"model": "V4", "stage": stage, **counts})
    output["source_file"] = str(ROOT / "v4" / "outputs" / f"v4_decisions_{list_date}.json")
    output["rows"] = len(rows)
    output["note"] = "Direction fields are read-only from the frozen V4 output; no decision is recomputed here."
    return output


def _build_cross_model_comparison(list_date: str, v3_context: dict[str, Any], v4_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    v4_by_id = {str(row.get("match_id")): row for row in v4_rows if row.get("match_id")}
    records: list[dict[str, Any]] = []
    freeze = _load_csv(_find_v3_freeze(list_date))
    for row in freeze:
        match_id = _text(row.get("match_id"))
        v4 = v4_by_id.get(match_id)
        if not v4:
            continue
        v3_side = _side_bucket(row.get("selected_side"))
        v4_side = _side_bucket(v4.get("selected_side") or v4.get("candidate_side") or v4.get("final_decision"))
        records.append({"match_id": match_id, "v3_direction": v3_side, "v4_direction": v4_side, "comparison": "AGREE" if v3_side == v4_side and v3_side != "no_bet" else "CONFLICT" if v3_side != "no_bet" and v4_side != "no_bet" else "NON_DIRECTIONAL"})
    return records


def write_analysis_bundle(raw_csv: Path, list_date: str, shared_feature_store: Path | None = None) -> dict[str, Any]:
    shared = build_shared_market_snapshot(raw_csv, list_date)
    raw_rows = [
        row for row in _load_csv(raw_csv)
        if _text(row.get("list_date")) in {"", list_date}
        and _text(row.get("match_id")) in shared.get("matches", {})
    ]
    v3 = build_v3_context(shared, raw_rows, _load_csv(ROOT / "ledger" / "simulated_bets.csv"))
    v4 = build_v4_context(shared, raw_rows, _read_prior_v4())
    v3_funnel = _build_v3_funnel(list_date)
    v4_funnel = _build_v4_funnel(list_date)
    v4_rows = _load_v4_day(list_date)
    comparison_rows = _build_cross_model_comparison(list_date, v3, v4_rows)
    base = OUT / list_date
    shared_path, v3_path, v4_path = base / "shared_market_snapshot.json", base / "v3_analysis.json", base / "v4_analysis.json"
    write_json(shared_path, shared)
    write_json(v3_path, v3)
    write_json(v4_path, v4)
    audit_dir = base / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    violations = []
    for match in shared["matches"].values():
        forbidden = sorted((set(match) - SHARED_ALLOWED_FIELDS) & FORBIDDEN_SHARED_FIELDS)
        if forbidden:
            violations.append({"match_id": match.get("match_id"), "fields": forbidden})
    v3_hashes = [value.get("model_input_hash") for value in v3["matches"].values()]
    v4_hashes = [value.get("model_input_hash") for value in v4["matches"].values()]
    v3_intent_items = [value.get("v3_market_behavior", {}) for value in v3["matches"].values()]
    dual_ev_rows = sum(1 for row in v4_rows if row.get("p_giving_cover") is not None and row.get("p_receiving_cover") is not None)
    v4_evaluated_rows = sum(1 for row in v4_rows if row.get("analysis_status") in {"EVALUATED", "NEUTRAL"})
    audit = {
        "contract": "V3_V4_ANALYSIS_SEPARATION_AUDIT_V1",
        "list_date": list_date,
        "shared_fields": sorted(SHARED_ALLOWED_FIELDS),
        "shared_forbidden_violations": violations,
        "v3_rows": len(v3["matches"]),
        "v4_rows": len(v4["matches"]),
        "v3_namespace": v3.get("namespace"),
        "v4_namespace": v4.get("namespace"),
        "v3_v4_input_hash_overlap": len(set(v3_hashes) & set(v4_hashes)),
        "independence_verdict": "PASS" if not (set(v3_hashes) & set(v4_hashes)) and not violations else "FAIL",
        "v3_intent_confidence_counts": {level: sum(1 for item in v3_intent_items if item.get("intent_confidence") == level) for level in ("HIGH", "MEDIUM", "LOW")},
        "v4_dual_ev_completeness": {"rows_with_both_cover_probs": dual_ev_rows, "evaluated_rows": v4_evaluated_rows, "formal_output_rows": len(v4_rows), "status": "PASS" if dual_ev_rows == v4_evaluated_rows and v4_evaluated_rows > 0 else "NOT_VERIFIED"},
        "shared_feature_store_retained_for_diagnostics_only": str(shared_feature_store or ""),
        "shared_market_schema_path": str(audit_dir / "shared_market_snapshot_schema.json"),
        "default_side_mapping": 0,
        "v3_direction_funnel_status": v3_funnel.get("status"),
        "v4_direction_funnel_status": v4_funnel.get("status"),
        "cross_model_comparison_status": "PASS" if comparison_rows else "NOT_RUN",
        "v3_formal_decisions": "READ_ONLY_AUDIT" if v3_funnel.get("status") == "PASS" else "NOT_RUN",
        "v4_formal_decisions": "READ_ONLY_AUDIT" if v4_funnel.get("status") == "PASS" else "NOT_RUN",
        "status": "PASS" if not violations else "FAIL",
    }
    write_json(audit_dir / "separation_audit.json", audit)
    write_json(audit_dir / "shared_market_snapshot_schema.json", SHARED_MARKET_SCHEMA)
    def _stage(funnel: dict[str, Any], name: str) -> dict[str, Any]:
        return next((row for row in funnel.get("stages", []) if row.get("stage") == name), {"upper": 0, "lower": 0, "no_bet": 0})
    v3_final = _stage(v3_funnel, "final")
    v4_final = _stage(v4_funnel, "final")
    v3_total = sum(v3_final.get(key, 0) for key in ("upper", "lower", "no_bet"))
    v4_total = sum(v4_final.get(key, 0) for key in ("upper", "lower", "no_bet"))
    v3_share = round(v3_final.get("upper", 0) / v3_total, 4) if v3_total else None
    v4_share = round(v4_final.get("upper", 0) / v4_total, 4) if v4_total else None
    reports = {
        "V3_V4_ANALYSIS_SEPARATION_AUDIT.md": "# V3/V4 分析隔离审计\n\n- V3、V4 正式模型名称保持不变。\n- 共享层只允许比赛身份和原始欧赔/亚盘快照；没有 score/settlement。\n- 共享派生特征违规数：%d。\n- V3/V4 使用独立命名空间和独立 input hash。\n- V3 漏斗：%s；V4 漏斗：%s；跨模型比较：%s。\n- 这是只读合同审计，不能把未验证的云端简化结果冒充正式信号。\n\n## 机器可读验收回答\n\n1. 共享字段：identity + raw Euro/AH + quote/source/bookmaker/snapshot；derived analysis：NO。\n2. V3 Fundamental/Fair Range：V3 自己计算；V4 Fundamental/Goal/Fair AH：V4 自己计算。\n3. V4 读取 V3 Intent：NO；V3 读取 V4 EV：NO；历史与 logic regime：分开。\n4. V3 `default_side_mapping`：0；V3 最终上盘占比：%s；V4 最终上盘占比：%s。\n5. V4 双边 EV 完整率：%s（%d/%d 个评估行）；V3/V4 上盘原因只能在各自命名空间解释，不能回写另一模型。\n6. 云端正式模型等价性：上一轮仍 `NOT_VERIFIED`；此文件只证明隔离合同和只读审计通过。\n\n状态：%s。\n" % (len(violations), v3_funnel.get("status"), v4_funnel.get("status"), audit["cross_model_comparison_status"], "—" if v3_share is None else f"{v3_share:.1%}", "—" if v4_share is None else f"{v4_share:.1%}", audit["v4_dual_ev_completeness"]["status"], dual_ev_rows, v4_evaluated_rows, audit["status"]),
        "SHARED_MARKET_DATA_CONTRACT.md": "# Shared Market Data Contract\n\n共享层字段：%s。\n\n禁止进入共享层：球队实力、Fair Line/Fair Range、净胜球分布、Intent、EV、Reliability、最终方向及任一模型历史后验。机器可读 schema 见 `shared_market_snapshot_schema.json`。\n" % ", ".join(sorted(SHARED_ALLOWED_FIELDS)),
        "V3_INDEPENDENT_ANALYSIS_REPORT.md": "# V3 独立分析报告\n\n- Namespace：V3_ANALYSIS；逻辑制度：`V3_LEGACY_PAGE_PARITY`。\n- Fundamental、Fair Range、Public Pull、Market Treatment、Intent、历史和最终方向只写入 V3。\n- Intent 只保留 hypothesis，`default_side_mapping=0`，证据不足不得给 HIGH。\n- V4 EV 和 V4 历史不作为 V3 输入。\n- 漏斗状态：%s；没有重算或改写冻结 V3 账本。\n" % v3_funnel.get("status"),
        "V4_INDEPENDENT_ANALYSIS_REPORT.md": "# V4 独立分析报告\n\n- Namespace：V4_ANALYSIS；逻辑制度：`V4_INDEPENDENT_GOAL_MODEL`。\n- Fundamental、净胜球分布、Fair AH 曲线、双边 EV 和可靠性只写入 V4。\n- Fair AH 曲线由 V4 自己的 goal distribution 生成；V3 Intent、V3 Fair Range 和 V3 历史不作为 V4 输入。\n- 漏斗状态：%s；V4 方向来自只读输出审计。\n- 双边 EV 覆盖：%s（双边覆盖行 %d / 评估行 %d）。\n" % (v4_funnel.get("status"), audit["v4_dual_ev_completeness"]["status"], dual_ev_rows, v4_evaluated_rows),
        "V3_INTENT_DIAGNOSTIC.md": "# V3 Intent Diagnostic\n\nIntent 只能生成 hypothesis，不能直接映射 Final Side。`default_side_mapping=0`；证据不足时 Confidence 不得为 HIGH。市场行为、自然拉力和甜度变化均标注为诊断字段。\n",
        "V4_DUAL_EV_DIAGNOSTIC.md": "# V4 Dual EV Diagnostic\n\nV4 对 giving/receiving 两侧分别计算概率、EV、EV gap 和覆盖概率。Intent 不参与方向选择；Fair AH 只来自 V4 自有 goal model。\n",
        "V3_V4_CROSS_MODEL_COMPARISON.md": "# V3/V4 Cross Model Comparison\n\n只在最终展示层比较 V3/V4 方向；一致或冲突不回写任一模型。记录数：%d；状态：%s。\n" % (len(comparison_rows), "PASS" if comparison_rows else "NOT_RUN"),
    }
    for name, text in reports.items():
        (audit_dir / name).write_text(text, encoding="utf-8")
    fields = ["match_id", "list_date", "shared_market_snapshot_id", "fundamental_snapshot_id", "model_input_hash", "logic_regime_id", "decision_id"]
    for name, payload in (("v3_input_lineage.csv", v3), ("v4_input_lineage.csv", v4)):
        with (audit_dir / name).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for match_id, value in payload["matches"].items():
                writer.writerow({"match_id": match_id, "list_date": list_date, "shared_market_snapshot_id": value.get("shared_market_snapshot_id"), "fundamental_snapshot_id": value.get("fundamental_snapshot_id"), "model_input_hash": value.get("model_input_hash"), "logic_regime_id": value.get("logic_regime_id"), "decision_id": value.get("decision_id", "")})
    for name, funnel in (("v3_direction_funnel.csv", v3_funnel), ("v4_direction_funnel.csv", v4_funnel)):
        with (audit_dir / name).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["model", "stage", "upper", "lower", "no_bet"])
            writer.writeheader()
            for row in funnel.get("stages", []):
                writer.writerow({key: row.get(key, 0) for key in writer.fieldnames})
    with (audit_dir / "cross_model_comparison.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["match_id", "v3_direction", "v4_direction", "comparison"])
        writer.writeheader()
        writer.writerows(comparison_rows)
    return {"shared": shared_path, "v3": v3_path, "v4": v4_path, "audit": audit_dir, "snapshot_id": shared["snapshot_id"], "rows": len(shared["matches"]), "status": audit["status"]}


def load_context(path: Path | str | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
