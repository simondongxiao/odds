"""V4 direction contract.

This module is deliberately small and deterministic.  It makes Titan's signed
Asian line the only source of team identity, and keeps intent-side mapping
separate from the posterior/grade calculation.
"""
from __future__ import annotations

import re
from typing import Any

MAPPING_VERSION = "V4_DIRECTION_FIXED_R1"
STATES = ("W", "HW", "P", "HL", "L")
KNOWN_SIDES = {"giving", "receiving", "neutral", "unknown"}

INTENT_TO_SIDE = {
    "阻上/诱下": "giving",
    "降温保护/诱下": "giving",
    "真实示强/阻上": "giving",
    "诱下/上盘降温": "giving",
    "阻上/降温保护": "giving",
    "诱上/阻下": "receiving",
    "真实示弱/阻下": "receiving",
    "阻下/下盘保护": "receiving",
    "平衡盘/等待临场确认": "neutral",
    "平衡": "neutral",
}


def normalize_intent(value: Any) -> str:
    text = str(value or "").strip().replace(" ", "")
    if "亚盘意图候选：" in text:
        text = text.split("亚盘意图候选：", 1)[1]
    text = text.split("（", 1)[0].split("；", 1)[0]
    for tag in INTENT_TO_SIDE:
        if text == tag or tag in text:
            return tag
    if not text or any(x in text for x in ("未接入", "待核", "缺失", "无法判断")):
        return "unknown"
    return text if text in INTENT_TO_SIDE else "unknown"


def map_intent(value: Any, *, pk: bool = False) -> dict[str, Any]:
    normalized = normalize_intent(value)
    side = "neutral" if pk else INTENT_TO_SIDE.get(normalized, "unknown")
    return {
        "normalized_intent": normalized,
        "candidate_side": side,
        "mapping_rule_version": MAPPING_VERSION,
        "mapping_reason": "authoritative canonical intent mapping" if side != "unknown" else "intent unavailable or not recognized",
    }


def _float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _first(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = str(row.get(name, "") or "").strip()
        if value:
            return value
    return ""


def _line(row: dict[str, Any], current: bool = True) -> float | None:
    names = (
        ("ah_full_current_line_or_draw", "xml_ah_line", "future_ah_line_hint")
        if current else
        ("ah_full_open_line_or_draw", "initial_ah_hint")
    )
    text = _first(row, *names)
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
    return _float(nums[-1]) if nums else None


def parse_titan_market(row: dict[str, Any]) -> dict[str, Any]:
    """Parse Titan's signed line without consulting European favorite odds.

    Contract: positive home line means home gives; negative home line means
    away gives.  The two water fields remain home/away prices, never side-
    swapped by the candidate mapper.
    """
    home = _first(row, "home_team", "home_cn")
    away = _first(row, "away_team", "away_cn")
    raw_line = _line(row, current=True)
    home_water = _float(_first(row, "ah_full_current_home_or_over", "xml_ah_home_water"))
    away_water = _float(_first(row, "ah_full_current_away_or_under", "xml_ah_away_water"))
    opening_line = _line(row, current=False)
    opening_home_water = _float(_first(row, "ah_full_open_home_or_over"))
    opening_away_water = _float(_first(row, "ah_full_open_away_or_under"))
    if raw_line is None or not home or not away or home_water is None or away_water is None:
        return {"valid": False, "pk": False, "reason": "AH_LINE_OR_WATER_MISSING"}
    if abs(raw_line) < 1e-9:
        return {
            "valid": True, "pk": True, "raw_line": raw_line, "opening_line": opening_line,
            "home_team": home, "away_team": away, "home_water": home_water, "away_water": away_water,
            "giving_team": "", "receiving_team": "", "giving_water": None, "receiving_water": None,
            "giving_handicap": 0.0, "receiving_handicap": 0.0,
        }
    giving_home = raw_line > 0
    giving_team = home if giving_home else away
    receiving_team = away if giving_home else home
    giving_water = home_water if giving_home else away_water
    receiving_water = away_water if giving_home else home_water
    assert giving_team != receiving_team
    return {
        "valid": True, "pk": False, "raw_line": raw_line, "opening_line": opening_line,
        "home_team": home, "away_team": away, "home_water": home_water, "away_water": away_water,
        "giving_team": giving_team, "receiving_team": receiving_team,
        "giving_water": giving_water, "receiving_water": receiving_water,
        "giving_handicap": abs(raw_line), "receiving_handicap": abs(raw_line),
        "opening_home_water": opening_home_water, "opening_away_water": opening_away_water,
        "opening_giving_water": (opening_home_water if giving_home else opening_away_water),
        "opening_receiving_water": (opening_away_water if giving_home else opening_home_water),
        "identity_status": "VALID_TITAN_SIGN_CONTRACT",
    }


def derive_market_intent(row: dict[str, Any], market: dict[str, Any]) -> tuple[str, str]:
    """Return a reproducible market-only intent when raw intent is absent.

    This is a label hypothesis for Shadow, not a fundamentals claim.  Rows
    without an opening/current comparison remain unknown and never default to
    giving.  The thresholds are qualitative sign checks, not model thresholds.
    """
    explicit = _first(row, "intent_canonical", "intent_tag", "intent_raw", "asian_intent")
    if explicit:
        return normalize_intent(explicit), "EXPLICIT_SOURCE"
    if market.get("pk") or market.get("opening_line") is None:
        return "unknown", "NO_OPENING_INTENT_INPUT"
    current = abs(float(market["raw_line"]))
    opening = abs(float(market["opening_line"]))
    line_delta = current - opening
    gw = market.get("giving_water")
    ogw = market.get("opening_giving_water")
    if gw is None or ogw is None:
        return "unknown", "NO_OPENING_WATER_INTENT_INPUT"
    water_delta = float(gw) - float(ogw)
    eps = 0.005
    if line_delta > eps and water_delta <= eps:
        return "真实示强/阻上", "MARKET_MOVE_LINE_STRENGTH_WITH_GIVING_RESISTANCE"
    if line_delta > eps and water_delta > eps:
        return "阻上/诱下", "MARKET_MOVE_DEEPER_WITH_GIVING_WATER_RISE"
    if line_delta < -eps and water_delta < -eps:
        return "降温保护/诱下", "MARKET_MOVE_SHALLOWER_WITH_GIVING_WATER_DROP"
    if line_delta < -eps and water_delta >= -eps:
        return "诱上/阻下", "MARKET_MOVE_SHALLOWER_WITH_GIVING_WATER_RESISTANCE"
    if water_delta < -eps:
        return "真实示弱/阻下", "FLAT_LINE_GIVING_WATER_DROP"
    if water_delta > eps:
        return "阻下/下盘保护", "FLAT_LINE_GIVING_WATER_RISE"
    return "平衡盘/等待临场确认", "MARKET_MOVE_BALANCED"


def candidate_fields(market: dict[str, Any], side: str) -> dict[str, Any]:
    if market.get("pk"):
        side = "neutral"
    if side == "giving":
        team, water = market.get("giving_team", ""), market.get("giving_water")
        reverse_team, reverse_water = market.get("receiving_team", ""), market.get("receiving_water")
    elif side == "receiving":
        team, water = market.get("receiving_team", ""), market.get("receiving_water")
        reverse_team, reverse_water = market.get("giving_team", ""), market.get("giving_water")
    else:
        team = water = reverse_team = reverse_water = ""
    return {
        "candidate_team": team,
        "candidate_side": side,
        "candidate_water": water,
        "candidate_handicap": market.get("giving_handicap") if side == "giving" else market.get("receiving_handicap") if side == "receiving" else None,
        "reverse_team": reverse_team,
        "reverse_side": "receiving" if side == "giving" else "giving" if side == "receiving" else "neutral",
        "reverse_water": reverse_water,
        "reverse_handicap": market.get("receiving_handicap") if side == "giving" else market.get("giving_handicap") if side == "receiving" else None,
    }


def assert_side_identity(market: dict[str, Any], candidate: dict[str, Any]) -> tuple[bool, str]:
    if not market.get("valid"):
        return False, "SIDE_IDENTITY_ERROR:invalid_market"
    if market.get("pk"):
        return candidate.get("candidate_side") == "neutral", "PK_NEUTRAL"
    side = candidate.get("candidate_side")
    expected = market.get("giving_team") if side == "giving" else market.get("receiving_team") if side == "receiving" else ""
    if side not in {"giving", "receiving"} or candidate.get("candidate_team") != expected:
        return False, "SIDE_IDENTITY_ERROR:candidate_team"
    actual_water = market.get("giving_water") if side == "giving" else market.get("receiving_water")
    if candidate.get("candidate_water") != actual_water:
        return False, "SIDE_IDENTITY_ERROR:candidate_water"
    if candidate.get("reverse_team") != (market.get("receiving_team") if side == "giving" else market.get("giving_team")):
        return False, "SIDE_IDENTITY_ERROR:reverse_team"
    return True, "SIDE_IDENTITY_VALID"


def mirror_probs(probs: dict[str, float]) -> dict[str, float]:
    return {"W": probs.get("L", 0.0), "HW": probs.get("HL", 0.0), "P": probs.get("P", 0.0), "HL": probs.get("HW", 0.0), "L": probs.get("W", 0.0)}

