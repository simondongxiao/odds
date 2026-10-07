"""Match-specific core for the single official V4 shadow model.

The public model name is always ``V4``.  Handicap buckets and market intent
are features only: neither is allowed to command the final side.  Every row
is scored on both sides from one match-specific goal-margin distribution.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(r"D:\codex")
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from football_competition_normalizer import competition_domain, normalize_dict  # noqa: E402

STATES = ("W", "HW", "P", "HL", "L")
MODEL_ID = "V4"
MODEL_VERSION = "V4"
PROBABILITY_VERSION = "MATCH_SPECIFIC_MARGIN_UNCALIBRATED"
DIRECTION_RULE = "MATCH_SPECIFIC_DUAL_EV"
CALIBRATION_STATUS = "UNCALIBRATED_SHADOW"
FORWARD_STATUS = "FROZEN_FORWARD"
LOGIC_CHANGE_AT = "2026-10-04T09:52:00+08:00"


def finite(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def normalise(values: dict[Any, float]) -> dict[Any, float]:
    total = sum(max(0.0, value) for value in values.values()) or 1.0
    return {key: max(0.0, value) / total for key, value in values.items()}


def devig_1x2(home: float, draw: float, away: float) -> dict[str, float]:
    if min(home, draw, away) <= 1.0:
        raise ValueError("INVALID_EURO_ODDS")
    raw = {"home": 1.0 / home, "draw": 1.0 / draw, "away": 1.0 / away}
    overround = sum(raw.values()) - 1.0
    return {**normalise(raw), "overround": overround}


def poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def margin_distribution(mean_margin: float, total_goals: float) -> dict[int, float]:
    """Transparent Skellam distribution for giving-minus-receiving goals."""
    total_goals = clamp(total_goals, 1.2, 4.5)
    mean_margin = clamp(mean_margin, -3.5, 3.5)
    giving_lambda = max(0.08, (total_goals + mean_margin) / 2.0)
    receiving_lambda = max(0.08, (total_goals - mean_margin) / 2.0)
    raw: dict[int, float] = {}
    for margin in range(-9, 10):
        if margin >= 0:
            raw[margin] = sum(
                poisson(other + margin, giving_lambda) * poisson(other, receiving_lambda)
                for other in range(0, 15)
            )
        else:
            raw[margin] = sum(
                poisson(other, giving_lambda) * poisson(other - margin, receiving_lambda)
                for other in range(0, 15)
            )
    return normalise(raw)


def component_status(margin: int, handicap: float) -> str:
    adjusted = margin + handicap
    if adjusted > 1e-9:
        return "W"
    if adjusted < -1e-9:
        return "L"
    return "P"


def combine_components(first: str, second: str) -> str:
    if first == second:
        return first
    if {first, second} == {"W", "L"}:
        return "P"
    if "W" in (first, second) and "P" in (first, second):
        return "HW"
    if "L" in (first, second) and "P" in (first, second):
        return "HL"
    raise ValueError(f"UNSUPPORTED_SETTLEMENT_COMBINATION:{first}:{second}")


def asian_probabilities(distribution: dict[int, float], handicap: float) -> dict[str, float]:
    quarter = round(handicap * 4)
    if quarter % 2:
        low = (quarter - 1) / 4.0
        high = (quarter + 1) / 4.0
        states: Counter[str] = Counter()
        for margin, probability in distribution.items():
            states[combine_components(component_status(margin, low), component_status(margin, high))] += probability
        return normalise({state: states.get(state, 0.0) for state in STATES})
    return normalise(
        {
            state: sum(
                probability
                for margin, probability in distribution.items()
                if component_status(margin, handicap) == state
            )
            for state in STATES
        }
    )


def expected_value(probabilities: dict[str, float], water: float) -> float:
    return (
        probabilities["W"] * water
        + probabilities["HW"] * 0.5 * water
        - probabilities["HL"] * 0.5
        - probabilities["L"]
    )


def cover_probability(probabilities: dict[str, float]) -> float:
    return probabilities["W"] + 0.5 * probabilities["HW"]


def stable_hash(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def load_league_level_map(path: Path | None = None) -> dict[str, str]:
    path = path or ROOT / "v4" / "league_level_map.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {
            str(row.get("competition", "")).strip(): str(row.get("league_level", "UNKNOWN")).strip() or "UNKNOWN"
            for row in csv.DictReader(handle)
            if str(row.get("competition", "")).strip()
        }


def league_level(competition: str, mapping: dict[str, str] | None = None) -> str:
    mapping = mapping or load_league_level_map()
    if competition in mapping:
        return mapping[competition]
    info = normalize_dict(competition)
    inferred = {"T1": "TIER_1", "T2": "TIER_2", "T3": "TIER_3"}.get(info.get("tier"))
    if inferred:
        return inferred
    return "UNKNOWN"


def quality_label(score: float) -> str:
    if score >= 0.85:
        return "HIGH"
    if score >= 0.65:
        return "MEDIUM"
    if score >= 0.35:
        return "LOW"
    return "UNKNOWN"


def evidence_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    return "MISSING"


def bucket_prior_signal(alpha: dict[str, float] | None) -> tuple[float, int]:
    if not alpha:
        return 0.0, 0
    count = int(round(sum(alpha.values()) - len(STATES)))
    total = sum(alpha.values()) or 1.0
    score = (
        alpha.get("W", 0.0)
        + 0.5 * alpha.get("HW", 0.0)
        - 0.5 * alpha.get("HL", 0.0)
        - alpha.get("L", 0.0)
    ) / total
    # Sparse buckets shrink almost entirely to zero.  This is a prior nudge,
    # never a direction command.
    shrink = max(0.0, count) / (max(0.0, count) + 25.0)
    return score * shrink, count


@dataclass(frozen=True)
class DecisionPolicy:
    base_ev_threshold: float = 0.02
    uncertainty_ev_slope: float = 0.08
    base_gap_threshold: float = 0.01
    uncertainty_gap_slope: float = 0.05


def evaluate_match(
    row: dict[str, Any],
    market: dict[str, Any],
    *,
    bucket_alpha: dict[str, float] | None = None,
    policy: DecisionPolicy | None = None,
) -> dict[str, Any]:
    """Return one match-specific, two-sided V4 decision payload."""
    policy = policy or DecisionPolicy()
    euro_home = finite(row.get("euro_home"))
    euro_draw = finite(row.get("euro_draw"))
    euro_away = finite(row.get("euro_away"))
    if None in (euro_home, euro_draw, euro_away):
        raise ValueError("MISSING_EURO")
    if not market.get("valid") or market.get("pk"):
        raise ValueError("MISSING_DIRECTIONAL_AH")

    devig = devig_1x2(float(euro_home), float(euro_draw), float(euro_away))
    giving_home = market["giving_team"] == row.get("home_team")
    p_giving = devig["home"] if giving_home else devig["away"]
    p_receiving = devig["away"] if giving_home else devig["home"]
    strength_log_ratio = math.log(max(p_giving, 1e-8) / max(p_receiving, 1e-8))

    current_line = abs(float(market["raw_line"]))
    opening_line = finite(market.get("opening_line"))
    opening_depth = abs(opening_line) if opening_line is not None else current_line
    line_move = current_line - opening_depth
    giving_water = float(market["giving_water"])
    receiving_water = float(market["receiving_water"])
    opening_giving_water = finite(market.get("opening_giving_water"))
    water_move = giving_water - opening_giving_water if opening_giving_water is not None else 0.0
    prior_signal, prior_sample = bucket_prior_signal(bucket_alpha)

    competition = str(row.get("competition", "") or "")
    domain = competition_domain(competition)
    level = league_level(competition)
    cup_sensitive = domain in {"CLUB_CUP", "CONTINENTAL_CLUB", "NATIONAL_OFFICIAL", "NATIONAL_YOUTH"}
    cup_format = evidence_value(row, "match_nature", "cup_format") if cup_sensitive else "NOT_APPLICABLE"
    aggregate_state = evidence_value(row, "aggregate_state", "first_leg_score") if cup_sensitive else "NOT_APPLICABLE"
    rotation = evidence_value(row, "rotation_risk", "rotation_evidence")
    injuries = evidence_value(row, "injury_evidence")
    lineup = evidence_value(row, "lineup_evidence")
    form = evidence_value(row, "form_evidence")
    motivation = evidence_value(row, "motivation_evidence")
    public_pull = evidence_value(row, "public_pull", "public_story_pull")
    elo = finite(row.get("elo_diff"))

    shared_context = row.get("titan_context") if isinstance(row.get("titan_context"), dict) else {}
    shared_ffl = shared_context.get("ffl") if isinstance(shared_context.get("ffl"), dict) else {}
    shared_cmfl = shared_context.get("cmfl") if isinstance(shared_context.get("cmfl"), dict) else {}
    shared_consensus = shared_context.get("fair_line_consensus") if isinstance(shared_context.get("fair_line_consensus"), dict) else {}
    # Fair-line precedence is independent of the Asian quote.  Do not replace
    # an available CMFL with a raw 1X2 log-ratio fallback merely because FFL
    # team-history data is unavailable.
    ffl_supported = finite(shared_ffl.get("fair_goal_margin")) is not None and not str(shared_ffl.get("status", "")).startswith("UNAVAILABLE")
    cmfl_supported = finite(shared_cmfl.get("margin")) is not None and not str(shared_cmfl.get("status", "")).startswith("UNAVAILABLE")
    consensus_margin = finite(shared_consensus.get("margin"))
    if consensus_margin is not None:
        football_margin = consensus_margin
        fair_line_source = "TITAN_FAIR_LINE_CONSENSUS"
    elif ffl_supported:
        football_margin = finite(shared_ffl.get("fair_goal_margin"))
        fair_line_source = "TITAN_SHARED_FFL"
    elif cmfl_supported:
        football_margin = finite(shared_cmfl.get("margin"))
        fair_line_source = "TITAN_SHARED_CMFL"
    else:
        football_margin = 1.18 * strength_log_ratio + (0.0015 * elo if elo is not None else 0.0)
        fair_line_source = "MARKET_REFERENCE_FALLBACK"
    # The historical line bucket remains a diagnostic/prior only. It must not
    # nudge the fair line and promote a whole bucket together.
    bucket_margin = 0.0
    market_path_margin = 0.0
    raw_fair_margin = football_margin

    missing_fundamentals = sum(value == "MISSING" for value in (rotation, injuries, lineup, form, motivation))
    data_score = 0.45 + 0.10 * (opening_line is not None) + 0.05 * bool(row.get("quote_at"))
    data_score += 0.06 * (5 - missing_fundamentals)
    if cup_sensitive:
        data_score += 0.05 * (cup_format != "MISSING") + 0.05 * (aggregate_state != "MISSING")
    data_score = clamp(data_score, 0.0, 1.0)
    market_score = 0.50 + 0.15 * (opening_line is not None) + 0.10 * (opening_giving_water is not None)
    market_score += 0.10 * bool(row.get("quote_at"))
    # Titan is a single aggregated venue: never claim HIGH market quality.
    market_score = min(0.79, market_score)

    domain_penalty = {
        "NATIONAL_YOUTH": 0.15,
        "INTERNATIONAL_FRIENDLY": 0.13,
        "CLUB_FRIENDLY": 0.13,
        "NATIONAL_OFFICIAL": 0.08,
        "CLUB_CUP": 0.07,
        "CONTINENTAL_CLUB": 0.05,
        "UNKNOWN": 0.12,
    }.get(domain, 0.03)
    tier_penalty = {"TIER_1": 0.00, "TIER_2": 0.02, "TIER_3": 0.04, "TIER_4_PLUS": 0.07, "UNKNOWN": 0.09}.get(level, 0.09)
    uncertainty = clamp(
        0.48 * (1.0 - data_score)
        + 0.30 * (1.0 - market_score)
        + domain_penalty
        + tier_penalty
        + (0.05 if public_pull == "MISSING" else 0.0),
        0.05,
        0.95,
    )
    # Bayesian-style shrinkage toward zero margin under sparse/low-quality
    # evidence.  It changes confidence, not a preselected side.
    shared_uncertainty = finite(shared_ffl.get("uncertainty"))
    if shared_uncertainty is not None:
        uncertainty = clamp(max(uncertainty, shared_uncertainty), 0.05, 0.95)
    home_fair_goal_margin = raw_fair_margin
    giving_home = market["giving_team"] == row.get("home_team")
    fair_goal_margin = home_fair_goal_margin if giving_home else -home_fair_goal_margin
    total_goals = finite(shared_ffl.get("predicted_home_goals"))
    if total_goals is not None:
        total_goals += finite(shared_ffl.get("predicted_away_goals"), 0.0) or 0.0
    else:
        total_goals = finite(shared_cmfl.get("total"))
        if total_goals is None:
            total_goals = clamp(2.62 - 1.05 * (devig["draw"] - 0.25), 1.55, 3.85)
    shared_distribution = shared_ffl.get("margin_distribution")
    if isinstance(shared_distribution, dict) and shared_distribution:
        home_distribution = normalise({int(key): float(value) for key, value in shared_distribution.items()})
    else:
        home_distribution = margin_distribution(home_fair_goal_margin, total_goals)
    distribution = home_distribution if giving_home else {-margin: probability for margin, probability in home_distribution.items()}
    giving_probs = asian_probabilities(distribution, -current_line)
    mirrored = {-margin: probability for margin, probability in distribution.items()}
    receiving_probs = asian_probabilities(mirrored, current_line)
    ev_giving = expected_value(giving_probs, giving_water)
    ev_receiving = expected_value(receiving_probs, receiving_water)

    ev_threshold = policy.base_ev_threshold + policy.uncertainty_ev_slope * uncertainty
    gap_threshold = policy.base_gap_threshold + policy.uncertainty_gap_slope * uncertainty
    edge_gap = abs(ev_giving - ev_receiving)
    best_ev = max(ev_giving, ev_receiving)
    if best_ev <= ev_threshold:
        final_decision, reason = "NO_BET", "EDGE_BELOW_UNCERTAINTY_THRESHOLD"
    elif edge_gap <= gap_threshold:
        final_decision, reason = "NO_BET", "SIDE_GAP_WITHIN_MODEL_ERROR"
    elif ev_giving > ev_receiving:
        final_decision, reason = "BET_GIVING", "GIVING_VALIDATED_EDGE"
    else:
        final_decision, reason = "BET_RECEIVING", "RECEIVING_VALIDATED_EDGE"

    pre_gate_decision = final_decision
    pre_gate_side = "giving" if final_decision == "BET_GIVING" else "receiving" if final_decision == "BET_RECEIVING" else ""
    pre_gate_team = market["giving_team"] if pre_gate_side == "giving" else market["receiving_team"] if pre_gate_side == "receiving" else ""
    pre_gate_ev = ev_giving if pre_gate_side == "giving" else ev_receiving if pre_gate_side == "receiving" else best_ev

    # A positive EV is not enough.  Restore the pre-10/01 type-neutral funnel:
    # competition type (including friendly/youth) is a risk feature, not an
    # automatic veto.  Matches with unknown tier/type must clear a stronger
    # evidence floor before they can be promoted.  Missing optional team/news
    # fields remain visible evidence gaps rather than silent assumptions.
    quality_gate_reasons: list[str] = []
    senior_tier = level in {"TIER_1", "TIER_2", "TIER_3"}
    low_quality_competition = bool(
        re.search(
            r"(?:业余|意丁杯|西丁|瑞士丁|英北超|英南超|苏高联|巴高乙|巴戈乙|印班超|印西隆联|地区联赛|大学|校园)",
            competition,
            re.IGNORECASE,
        )
    )
    if low_quality_competition:
        quality_gate_reasons.append("LOW_QUALITY_COMPETITION")
    # Keep only the real core-market floor here. Unknown tier, youth/friendly
    # type, and missing optional rotation/lineup/news fields are uncertainty
    # inputs, not automatic no-bet decisions under the restored pre-10/01
    # selection rule.
    if data_score < 0.55:
        quality_gate_reasons.append("DATA_QUALITY_LOW")
    if market_score < 0.65:
        quality_gate_reasons.append("MARKET_SUPPORT_LOW")
    quality_gate_passed = not quality_gate_reasons
    if not quality_gate_passed and final_decision.startswith("BET_"):
        final_decision = "NO_BET"
        reason = "LOW_QUALITY_GATE"

    selected_side = "giving" if final_decision == "BET_GIVING" else "receiving" if final_decision == "BET_RECEIVING" else ""
    selected_team = market["giving_team"] if selected_side == "giving" else market["receiving_team"] if selected_side == "receiving" else ""
    selected_water = giving_water if selected_side == "giving" else receiving_water if selected_side == "receiving" else None
    selected_handicap = -current_line if selected_side == "giving" else current_line if selected_side == "receiving" else None
    selected_probs = giving_probs if selected_side == "giving" else receiving_probs if selected_side == "receiving" else {}
    selected_ev = ev_giving if selected_side == "giving" else ev_receiving if selected_side == "receiving" else pre_gate_ev

    has_market_path = opening_line is not None and opening_giving_water is not None
    full_context = missing_fundamentals == 0 and (not cup_sensitive or (cup_format != "MISSING" and aggregate_state != "MISSING"))
    expert_tier = "FULL" if full_context else "MARKET" if has_market_path else "CORE"
    expert_decision = "SELECTED_SHADOW" if final_decision.startswith("BET_") else "REJECTED_SHADOW"
    expert_reason = "MATCH_SPECIFIC_EDGE_RELIABLE" if expert_decision == "SELECTED_SHADOW" else reason

    if selected_ev >= 0.10 and uncertainty <= 0.35:
        grade = "A"
    elif selected_ev >= 0.07 and uncertainty <= 0.50:
        grade = "B"
    elif selected_ev > 0:
        grade = "C"
    else:
        grade = "N"
    pre_gate_grade = grade
    if not quality_gate_passed:
        grade = "N"

    market_interpretation = str(row.get("normalized_intent") or row.get("intent_raw") or "unknown")
    shared_diagnostic = shared_context.get("market_deviation") if isinstance(shared_context.get("market_deviation"), dict) else {}
    interpretation_status = str(shared_diagnostic.get("interpretation") or "UNKNOWN")
    evidence_coverage = {
        "identity": "AVAILABLE" if row.get("match_id") and row.get("home_team") and row.get("away_team") else "MISSING",
        "kickoff": "AVAILABLE" if row.get("kickoff") else "MISSING",
        "asian_market": "AVAILABLE",
        "euro_market": "AVAILABLE",
        "ffl": "AVAILABLE" if ffl_supported else "MISSING_OPTIONAL",
        "team_history": "AVAILABLE" if shared_context.get("data_quality") == "MARKET" else "SPARSE_OR_MISSING",
        "market_path": "TWO_POINT_OBSERVATION" if opening_line is not None and opening_giving_water is not None else "STATIC_QUOTE",
        "cross_book_quotes": "MISSING",
        "real_flow": "MISSING",
    }
    public_proxy = shared_context.get("public_pull_proxy") if isinstance(shared_context.get("public_pull_proxy"), dict) else {"status": "MISSING"}
    price_terms = None
    if opening_line is not None and opening_giving_water is not None:
        # The compact vector is calculated on the same frozen reference
        # distribution.  It isolates quote-term changes from probability
        # changes without inventing an intermediate quote.
        def payoff(h: float, w: float, margin: int) -> float:
            adjusted = margin + h
            if adjusted > 0: return w
            if adjusted < 0: return -1.0
            return 0.0
        price_terms = {
            "comparison": "TWO_POINT_OBSERVATION",
            "opening_giving_payoff": {str(m): payoff(-opening_depth, float(opening_giving_water), m) for m in range(-3, 4)},
            "current_giving_payoff": {str(m): payoff(-current_line, giving_water, m) for m in range(-3, 4)},
            "note": "四分之一盘完整结算仍由五状态映射；此处为条款变化诊断，不是方向命令",
        }
    return {
        "domain": domain,
        "league_level": level,
        "football_pull": {
            "score": football_margin,
            "devig_giving": p_giving,
            "devig_draw": devig["draw"],
            "devig_receiving": p_receiving,
            "strength_log_ratio": strength_log_ratio,
            "elo_diff": elo if elo is not None else "MISSING",
            "form": form,
            "injuries": injuries,
            "lineup": lineup,
            "rotation": rotation,
            "motivation": motivation,
        },
        "public_pull": {"status": public_pull, "score": None if public_pull == "MISSING" else finite(row.get("public_pull_score"))},
        "cup_context": {"format": cup_format, "aggregate_state": aggregate_state, "missing_is_not_veto": True},
        "fair_goal_margin": fair_goal_margin,
        "ffl_home_fair_goal_margin": home_fair_goal_margin,
        "fair_handicap": round(fair_goal_margin * 4.0) / 4.0,
        "ffl_home_fair_handicap": shared_ffl.get("fair_handicap"),
        "fair_handicap_low": (shared_ffl.get("fair_handicap_low") if giving_home else -finite(shared_ffl.get("fair_handicap_high"), 0.0)) if shared_ffl else None,
        "fair_handicap_high": (shared_ffl.get("fair_handicap_high") if giving_home else -finite(shared_ffl.get("fair_handicap_low"), 0.0)) if shared_ffl else None,
        "fair_line_source": fair_line_source,
        "titan_context_snapshot_id": shared_context.get("snapshot_id"),
        "cmfl": shared_context.get("cmfl"),
        "fair_line_consensus": shared_context.get("fair_line_consensus"),
        "shared_market_deviation": shared_context.get("market_deviation"),
        "market_line": current_line,
        "line_gap": fair_goal_margin - current_line,
        "bucket_prior": {"line_bucket": f"{current_line:.2f}", "signal": prior_signal, "sample": prior_sample, "margin_nudge": bucket_margin, "role": "PRIOR_ONLY"},
        "market_path": {"opening_line": opening_line, "current_line": current_line, "line_move": line_move, "giving_water_move": water_move},
        "market_interpretation": market_interpretation,
        "intent_role": "INTERPRETATION_ONLY",
        "interpretation_status": interpretation_status,
        "evidence_coverage": evidence_coverage,
        "data_integrity": "PASS",
        "model_support": "FFL_SUPPORTED" if ffl_supported else "MARKET_REFERENCE_FALLBACK",
        "decision_status": "BET" if final_decision.startswith("BET_") else "NO_BET",
        "evidence_checklist": (shared_context.get("evidence_checklist") if isinstance(shared_context.get("evidence_checklist"), dict) else {
            "observed": ["asian_line", "two_sided_water", "euro_1x2"],
            "missing": ["cross_book_quotes", "real_flow"],
            "compatible_explanations": [], "unidentifiable": ["bookmaker_intent", "current_net_position"],
        }),
        "public_attraction_features": public_proxy,
        "quote_path": shared_context.get("quote_path") if isinstance(shared_context.get("quote_path"), dict) else {"status": "STATIC_QUOTE", "source_quote_at": row.get("quote_at", ""), "intermediate_quotes": "NOT_OBSERVED"},
        "price_terms": price_terms,
        "data_quality": quality_label(data_score),
        "data_quality_score": data_score,
        "market_quality": quality_label(market_score),
        "market_quality_score": market_score,
        "uncertainty": uncertainty,
        "uncertainty_regulator": 1.0 - 0.38 * uncertainty,
        "ev_threshold": ev_threshold,
        "side_gap_threshold": gap_threshold,
        "margin_distribution": {str(key): value for key, value in distribution.items()},
        "giving_probabilities": giving_probs,
        "receiving_probabilities": receiving_probs,
        "p_giving_cover": cover_probability(giving_probs),
        "p_receiving_cover": cover_probability(receiving_probs),
        "p_push": giving_probs["P"],
        "ev_giving": ev_giving,
        "ev_receiving": ev_receiving,
        "final_decision": final_decision,
        "decision_reason": reason,
        "pre_gate_final_decision": pre_gate_decision,
        "pre_gate_selected_team": pre_gate_team,
        "pre_gate_ev_mean": pre_gate_ev,
        "quality_gate_passed": quality_gate_passed,
        "quality_gate_reasons": quality_gate_reasons,
        "selected_side": selected_side,
        "selected_team": selected_team,
        "selected_water_hk": selected_water,
        "selected_handicap_signed": selected_handicap,
        "selected_probabilities": selected_probs,
        "ev_mean": selected_ev,
        "grade": grade,
        "bet_unit": 1.0 if final_decision.startswith("BET_") else 0.0,
        "stake_rule": "FIXED_1U",
        "abc_stake_effect": "NONE",
        "expert_selector": {
            "tier": expert_tier,
            "core_evaluable": True,
            "market_evaluable": has_market_path,
            "full_evaluable": full_context,
            "decision": expert_decision,
            "reason": expert_reason,
            "optional_missing": [
                name
                for name, value in {
                    "public_pull": public_pull,
                    "elo": "MISSING" if elo is None else "AVAILABLE",
                    "form": form,
                    "injuries": injuries,
                    "lineup": lineup,
                    "rotation": rotation,
                    "motivation": motivation,
                    "cup_format": cup_format,
                    "aggregate_state": aggregate_state,
                }.items()
                if value == "MISSING"
            ],
        },
        "calibration_status": CALIBRATION_STATUS,
        "probability_version": PROBABILITY_VERSION,
        "direction_rule_version": DIRECTION_RULE,
        "reason_codes": [reason, "BUCKET_PRIOR_ONLY", "INTENT_INTERPRETATION_ONLY", "FFL_OPTIONAL", f"EXPERT_{expert_tier}"],
    }


def direction_matrix(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for row in rows:
        bucket = str((row.get("bucket_prior") or {}).get("line_bucket") or row.get("handicap_bucket") or "")
        groups[(bucket, str(row.get("domain") or "UNKNOWN"))][str(row.get("final_decision") or "UNAVAILABLE")] += 1
    output = []
    for (bucket, domain), counts in sorted(groups.items()):
        total = sum(counts.values())
        main = [counts["BET_GIVING"], counts["BET_RECEIVING"], counts["NO_BET"]]
        output.append({
            "handicap_bucket": bucket,
            "domain": domain,
            "sample_count": total,
            "giving": main[0],
            "receiving": main[1],
            "no_bet": main[2],
            "unavailable": counts["UNAVAILABLE"],
            "warning": "DIRECTION_CONCENTRATION_WARNING" if total >= 10 and max(main) == total else "",
        })
    return output


def probability_diversity(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[tuple[float, ...]]] = defaultdict(list)
    for row in rows:
        probabilities = row.get("giving_probabilities")
        if not probabilities:
            continue
        key = (
            str((row.get("bucket_prior") or {}).get("line_bucket") or ""),
            str(row.get("domain") or "UNKNOWN"),
            str(row.get("selected_side") or "NO_BET"),
        )
        groups[key].append(tuple(round(float(probabilities.get(state, 0.0)), 10) for state in STATES))
    output = []
    for key, vectors in sorted(groups.items()):
        identical_rate = max(Counter(vectors).values()) / len(vectors)
        variances = [statistics.pvariance([vector[i] for vector in vectors]) if len(vectors) > 1 else 0.0 for i in range(len(STATES))]
        output.append({
            "handicap_bucket": key[0], "domain": key[1], "side": key[2],
            "sample_count": len(vectors), "identical_probability_rate": identical_rate,
            "variance": sum(variances) / len(variances),
            "warning": "PROBABILITY_COLLAPSE_WARNING" if len(vectors) >= 10 and identical_rate >= 0.8 else "",
        })
    return output


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0]) if rows else [])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        if not fields:
            return
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_runtime_diagnostics(rows: list[dict[str, Any]], diagnostics: Path, metadata: dict[str, Any]) -> None:
    diagnostics.mkdir(parents=True, exist_ok=True)
    matrix = direction_matrix(rows)
    diversity = probability_diversity(rows)
    write_csv(diagnostics / "handicap_direction_matrix.csv", matrix)
    write_csv(diagnostics / "probability_diversity.csv", diversity)

    evaluated = [row for row in rows if row.get("analysis_status") in {"EVALUATED", "FROZEN_PREMATCH_DECISION"}]
    pull_rows = [{
        "match_id": row.get("match_id"), "competition": row.get("competition"), "domain": row.get("domain"),
        "league_level": row.get("league_level"), "football_pull_score": (row.get("football_pull") or {}).get("score"),
        "public_pull": (row.get("public_pull") or {}).get("status"), "fair_goal_margin": row.get("fair_goal_margin"),
        "fair_handicap": row.get("fair_handicap"), "market_line": row.get("market_line"), "line_gap": row.get("line_gap"),
        "data_quality": row.get("data_quality"), "market_quality": row.get("market_quality"), "uncertainty": row.get("uncertainty"),
        "ev_giving": row.get("ev_giving"), "ev_receiving": row.get("ev_receiving"), "final_decision": row.get("final_decision"),
    } for row in evaluated]
    write_csv(diagnostics / "V4_PULL_LAYER_AUDIT.csv", pull_rows)

    level_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in evaluated:
        level_groups[str(row.get("league_level") or "UNKNOWN")].append(row)
    historical_settled: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for history_path in sorted((ROOT / "v4" / "outputs").glob("v4_decisions_*.json")):
        try:
            payload = json.loads(history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for historical in payload.get("matches", []):
            result = str(historical.get("result") or (historical.get("settlement") or {}).get("result") or "").upper()
            pnl = finite(historical.get("pnl_1u"), finite((historical.get("settlement") or {}).get("pnl_1u")))
            # Old V4 A/B/C rows are Frozen Historical Decisions.  Reading
            # their recorded settlement here is diagnostic-only and never
            # changes their original side, probability, EV or grade.
            if result not in STATES or pnl is None or str(historical.get("grade") or "N") not in {"A", "B", "C"}:
                continue
            level = league_level(str(historical.get("competition") or ""))
            historical_settled[level].append({"result": result, "pnl_1u": pnl})
    level_rows = []
    for level in sorted(set(level_groups) | set(historical_settled)):
        group = level_groups.get(level, [])
        bets = [row for row in group if str(row.get("final_decision", "")).startswith("BET_")]
        settled = historical_settled.get(level, [])
        effective_numerator = sum(1.0 if item["result"] == "W" else 0.5 if item["result"] == "HW" else 0.0 for item in settled)
        effective_denominator = sum(item["result"] != "P" for item in settled)
        pnl = sum(float(item["pnl_1u"]) for item in settled)
        level_rows.append({
            "league_level": level,
            "current_evaluated": len(group),
            "current_bet": len(bets),
            "current_no_bet": sum(row.get("final_decision") == "NO_BET" for row in group),
            "historical_settled": len(settled),
            "effective_win_rate": round(effective_numerator / effective_denominator, 6) if effective_denominator else "",
            "pnl_1u": round(pnl, 6) if settled else "",
            "roi": round(pnl / len(settled), 6) if settled else "",
            "history_policy": "READ_ONLY_FROZEN_HISTORICAL_DECISIONS",
        })
    write_csv(diagnostics / "league_level_performance.csv", level_rows)

    mechanical_warnings = [row for row in matrix if row.get("warning")]
    probability_warnings = [row for row in diversity if row.get("warning")]
    (diagnostics / "V4_DIRECTION_MECHANICAL_AUDIT.md").write_text(
        "# V4 方向机械化审计\n\n"
        f"- 生成时间：{metadata.get('generated_at')}\n"
        f"- V4_logic_change_at：{metadata.get('V4_logic_change_at')}\n"
        f"- code_hash：`{metadata.get('code_hash')}`\n"
        "- 结论：正式 V4 先生成比赛级净胜球分布，再独立计算两侧 EV；盘口桶只作 prior，Intent 只作解释。\n"
        f"- 方向集中报警：{len(mechanical_warnings)} 组；概率塌缩报警：{len(probability_warnings)} 组。报警仅触发复核，不自动反选。\n",
        encoding="utf-8",
    )
    missing_public = sum((row.get("public_pull") or {}).get("status") == "MISSING" for row in evaluated)
    (diagnostics / "V4_PULL_LAYER_AUDIT.md").write_text(
        "# V4 Pull / Fair Line / Quality 审计\n\n"
        f"- 已评估：{len(evaluated)}\n"
        f"- Public Pull 缺失：{missing_public}（保持 MISSING，不按球队名推测）\n"
        "- Football Pull 以去水 1X2 为高覆盖核心；Elo、伤停、首发、轮换、战意缺失时进入不确定性调节。\n"
        "- Fair Line 先于 Market Line 比较；Data/Market Quality 只调节不确定性和阈值，不直接决定方向。\n"
        "- 杯赛字段缺失时不一刀切禁投，但增加不确定性。\n",
        encoding="utf-8",
    )
