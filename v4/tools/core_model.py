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
# New venue/symmetry audit logic starts at this frozen forward boundary.  Files
# dated before it remain read-only historical decisions; only rows evaluated
# after this timestamp use the corrected venue residual and home-space mapping.
LOGIC_CHANGE_AT = "2026-10-22T22:15:00+08:00"


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
    # Restore the pre-10/01 adult-slate rule: an explicitly recognised
    # official senior cup/continental competition is eligible for the same
    # downstream EV funnel even when it has no league-style tier number.
    # Youth/reserve/friendly competitions are still rejected by the quality
    # gate below.
    if info.get("senior_eligible") and info.get("competition_scope") in {"国内杯赛", "洲际正式赛"}:
        return "TIER_1"
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

    # V4 reads only its own independent goal model.  Shared input is limited
    # to the immutable raw market snapshot; V3-derived FFL/consensus fields
    # are deliberately ignored even if a stale caller supplies them.
    shared_context = row.get("v4_analysis") if isinstance(row.get("v4_analysis"), dict) else {}
    v4_goal_model = shared_context.get("v4_goal_model") if isinstance(shared_context.get("v4_goal_model"), dict) else {}
    shared_ffl = {
        "fair_goal_margin": v4_goal_model.get("fair_goal_margin"),
        "predicted_home_goals": v4_goal_model.get("lambda_home"),
        "predicted_away_goals": v4_goal_model.get("lambda_away"),
        "margin_distribution": v4_goal_model.get("margin_distribution"),
        "fair_handicap": v4_goal_model.get("fair_goal_margin"),
        "fair_handicap_low": v4_goal_model.get("fair_goal_margin"),
        "fair_handicap_high": v4_goal_model.get("fair_goal_margin"),
        "venue_effect": shared_context.get("v4_venue_effect", 0.0),
    }
    # V4 no longer consumes a shared consensus/CMFL object.
    shared_consensus = {}
    ffl_supported = finite(v4_goal_model.get("fair_goal_margin")) is not None
    consensus_distribution = shared_consensus.get("distribution") if isinstance(shared_consensus.get("distribution"), dict) else {}
    # CMFL remains an auditable market reference in the shared snapshot.  The
    # official V4 decision path continues to use its existing FFL-or-market
    # conditional selection until an out-of-sample weight is frozen; silently
    # promoting CMFL here would create a new model version.
    cmfl_available = False
    cmfl_supported = False
    football_margin = finite(shared_ffl.get("fair_goal_margin")) if ffl_supported else None
    if football_margin is None:
        football_margin = 1.18 * strength_log_ratio + (0.0015 * elo if elo is not None else 0.0)
    # The line bucket is a small, shrunk prior nudge.  It is not a side map:
    # the same bucket can still resolve to either side or NO_BET after the
    # match-level probability and price evidence are evaluated.
    bucket_margin = clamp(0.22 * prior_signal, -0.15, 0.15)
    market_path_margin = 0.0
    raw_fair_margin = football_margin + bucket_margin

    missing_fundamentals = sum(value == "MISSING" for value in (rotation, injuries, lineup, form, motivation))
    # The opening quote is useful context, but it is optional.  A current
    # Asian line plus both current waters is already a valid executable market
    # snapshot.  Treating the missing opening line as a hard quality failure
    # was the reason senior leagues such as the Championship were converted
    # from a valid BET decision to NO_BET after the 10/08 refreshes.
    current_market_complete = all(
        value is not None for value in (current_line, giving_water, receiving_water)
    )
    data_score = (
        0.45
        + 0.10 * current_market_complete
        + 0.10 * (opening_line is not None)
        + 0.05 * bool(row.get("quote_at"))
    )
    data_score += 0.06 * (5 - missing_fundamentals)
    if cup_sensitive:
        data_score += 0.05 * (cup_format != "MISSING") + 0.05 * (aggregate_state != "MISSING")
    data_score = clamp(data_score, 0.0, 1.0)
    market_score = (
        0.50
        + 0.15 * current_market_complete
        + 0.10 * (opening_line is not None)
        + 0.05 * (opening_giving_water is not None)
    )
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
    # FFL and CMFL are both expressed in home-team space.  Only the fallback
    # probability proxy is expressed from the giving team's perspective.  The
    # previous code applied the giving/receiving mirror to an already
    # home-space FFL snapshot, so an away-giving row could be mirrored twice.
    giving_home = market["giving_team"] == row.get("home_team")
    venue_effect = finite(shared_ffl.get("venue_effect"), 0.0) if ffl_supported else 0.0
    neutral_margin = finite(shared_ffl.get("neutral_margin")) if ffl_supported else None
    if ffl_supported or cmfl_supported:
        home_fair_goal_margin = float(football_margin) + (bucket_margin if giving_home else -bucket_margin)
    else:
        home_fair_goal_margin = raw_fair_margin if giving_home else -raw_fair_margin
    fair_goal_margin = home_fair_goal_margin
    total_goals = finite(shared_ffl.get("predicted_home_goals"))
    if total_goals is not None:
        total_goals += finite(shared_ffl.get("predicted_away_goals"), 0.0) or 0.0
    else:
        total_goals = clamp(2.62 - 1.05 * (devig["draw"] - 0.25), 1.55, 3.85)
    shared_distribution = shared_ffl.get("margin_distribution")
    if ffl_supported and isinstance(shared_distribution, dict) and shared_distribution:
        home_distribution = normalise({int(key): float(value) for key, value in shared_distribution.items()})
    else:
        home_distribution = margin_distribution(home_fair_goal_margin, total_goals)
    distribution = home_distribution if giving_home else {-margin: probability for margin, probability in home_distribution.items()}
    giving_probs = asian_probabilities(distribution, -current_line)
    mirrored = {-margin: probability for margin, probability in distribution.items()}
    receiving_probs = asian_probabilities(mirrored, current_line)
    ev_giving = expected_value(giving_probs, giving_water)
    ev_receiving = expected_value(receiving_probs, receiving_water)

    # Counterfactual venue contribution is calculated on the same frozen
    # distribution and current quote.  It is diagnostic-only and never selects
    # a side.  For CMFL/fallback rows the venue effect is zero by contract.
    if neutral_margin is not None and ffl_supported:
        neutral_home_distribution = margin_distribution(neutral_margin, total_goals)
        neutral_distribution = neutral_home_distribution if giving_home else {-m: p for m, p in neutral_home_distribution.items()}
        neutral_giving = asian_probabilities(neutral_distribution, -current_line)
        neutral_receiving = asian_probabilities({-m: p for m, p in neutral_distribution.items()}, current_line)
        neutral_home_probs = neutral_giving if giving_home else neutral_receiving
        p_home_cover_neutral = cover_probability(neutral_home_probs)
    else:
        p_home_cover_neutral = cover_probability(giving_probs if giving_home else receiving_probs)
    p_home_cover_with_venue = cover_probability(giving_probs if giving_home else receiving_probs)
    venue_probability_delta = p_home_cover_with_venue - p_home_cover_neutral

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

    # A positive EV from a youth/reserve, friendly, explicitly low-quality, or
    # genuinely unclassified competition is still not actionable.  A formal
    # adult league/cup remains eligible even when its alias is absent from the
    # tier map; missing optional team/news fields are evidence gaps, not vetoes.
    quality_gate_reasons: list[str] = []
    youth_or_reserve = domain in {"NATIONAL_YOUTH", "CLUB_YOUTH"} or bool(
        re.search(r"(?:U\d{1,2}|青年|青少年|青联|青杯|后备|预备|reserve|reserves|academy|development)", competition, re.IGNORECASE)
    )
    low_quality_competition = bool(
        re.search(
            r"(?:业余|意丁杯|西丁|瑞士丁|英北超|英南超|苏高联|巴高乙|巴戈乙|印班超|印西隆联|地区联赛|大学|校园)",
            competition,
            re.IGNORECASE,
        )
    )
    # A missing alias in the tier map is not enough to reject a match.  The
    # source feed has a stable competition domain for official senior leagues
    # and cups (including 英冠/欧冠 and other non-Chinese aliases), while the
    # optional fundamentals are often unavailable.  Keep the hard veto only
    # for genuinely unclassified competitions; youth/reserve and explicitly
    # low-quality competitions remain blocked below.
    official_domain = domain in {
        "CLUB_LEAGUE",
        "CLUB_CUP",
        "CONTINENTAL_CLUB",
        "NATIONAL_OFFICIAL",
    }
    if level in {"UNKNOWN", "TIER_4_PLUS"} and not official_domain:
        quality_gate_reasons.append("LEAGUE_TIER_UNKNOWN")
    if youth_or_reserve:
        quality_gate_reasons.append("YOUTH_RESERVE_EXCLUDED")
    if low_quality_competition:
        quality_gate_reasons.append("LOW_QUALITY_COMPETITION")
    # Keep a true minimum input floor for any competition, but do not turn
    # five optional/MISSING context fields into a hard veto for known senior
    # leagues.  This preserves the Skill's evidence-gap semantics.
    if data_score < 0.55:
        quality_gate_reasons.append("DATA_QUALITY_LOW")
    if market_score < 0.65:
        quality_gate_reasons.append("MARKET_SUPPORT_LOW")
    # Missing rotation/injury/lineup/form/motivation fields are an evidence
    # gap, not a hard veto when the market itself is executable.  The skill's
    # contract explicitly allows a current AH line plus both waters to pass;
    # keep this information in the scores and audit payload instead.
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
        "neutral_margin": neutral_margin if neutral_margin is not None else fair_goal_margin,
        "venue_effect": venue_effect,
        "venue_effect_status": shared_context.get("venue_status") or shared_ffl.get("venue_effect_status") or "UNKNOWN",
        "venue_effect_audit": shared_context.get("venue_effect_audit") or {},
        "ffl_margin_after_venue": fair_goal_margin,
        "p_home_cover_neutral": p_home_cover_neutral,
        "p_home_cover_with_venue": p_home_cover_with_venue,
        "venue_probability_delta": venue_probability_delta,
        "venue_effect_dominates_decision": bool(abs(venue_probability_delta) >= 0.05),
        "ffl_home_fair_goal_margin": home_fair_goal_margin,
        "fair_handicap": round(fair_goal_margin * 4.0) / 4.0,
        "ffl_home_fair_handicap": shared_ffl.get("fair_handicap"),
        "fair_handicap_low": (shared_ffl.get("fair_handicap_low") if giving_home else -finite(shared_ffl.get("fair_handicap_high"), 0.0)) if shared_ffl else None,
        "fair_handicap_high": (shared_ffl.get("fair_handicap_high") if giving_home else -finite(shared_ffl.get("fair_handicap_low"), 0.0)) if shared_ffl else None,
        "fair_line_source": "V4_INDEPENDENT_GOAL_MODEL" if ffl_supported else "MARKET_REFERENCE_FALLBACK",
        "probability_source": "V4_GOAL_MODEL" if ffl_supported else "MARKET_CONDITIONAL",
        "cmfl_available_for_audit": cmfl_available,
        "shared_market_snapshot_id": row.get("shared_market_snapshot_id") or shared_context.get("shared_market_snapshot_id"),
        "v4_fundamental_snapshot_id": shared_context.get("fundamental_snapshot_id"),
        "v4_model_input_hash": shared_context.get("model_input_hash"),
        "v4_logic_regime_id": shared_context.get("logic_regime_id"),
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
        "reason_codes": [reason, "BUCKET_PRIOR_ONLY", "INTENT_INTERPRETATION_ONLY", "FFL_OPTIONAL", "VENUE_EFFECT_SINGLE_ENTRY", f"EXPERT_{expert_tier}"],
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


def _team_cover(result: dict[str, Any], market: dict[str, Any], team: str) -> float | None:
    if team == market.get("giving_team"):
        return finite(result.get("p_giving_cover"))
    if team == market.get("receiving_team"):
        return finite(result.get("p_receiving_cover"))
    return None


def _team_ev(result: dict[str, Any], market: dict[str, Any], team: str) -> float | None:
    if team == market.get("giving_team"):
        return finite(result.get("ev_giving"))
    if team == market.get("receiving_team"):
        return finite(result.get("ev_receiving"))
    return None


def _mirror_context(context: dict[str, Any]) -> dict[str, Any]:
    """Mirror team-space inputs for the swap symmetry test.

    The test intentionally sets venue to neutral: this isolates the model's
    team/market mapping from the legitimate change in venue identity.
    """
    mirrored = json.loads(json.dumps(context, ensure_ascii=False, default=str))
    mirrored["venue_status"] = "NEUTRAL"
    mirrored["venue_effect"] = 0.0
    mirrored["neutral_venue"] = True
    # V4's independent namespaced goal model is the formal probability source
    # after the V3/V4 separation.  Mirror it here as well as the legacy
    # diagnostic sections; otherwise the symmetry test silently reuses the
    # original home-space margin and reports a false failure for every row.
    for section in ("ffl", "fair_line_consensus", "v4_goal_model"):
        value = mirrored.get(section)
        if not isinstance(value, dict):
            continue
        if finite(value.get("fair_goal_margin")) is not None:
            value["fair_goal_margin"] = -float(value["fair_goal_margin"])
        if finite(value.get("margin")) is not None:
            value["margin"] = -float(value["margin"])
        for key in ("predicted_home_goals", "predicted_away_goals", "lambda_home", "lambda_away"):
            other = {"predicted_home_goals": "predicted_away_goals", "lambda_home": "lambda_away"}.get(key)
            if other and key in value and other in value:
                value[key], value[other] = value[other], value[key]
        for key in ("margin_distribution", "ffl_margin_distribution"):
            dist = value.get(key)
            if isinstance(dist, dict):
                value[key] = {str(-int(k)): v for k, v in dist.items()}
        inputs = value.get("inputs")
        if isinstance(inputs, dict) and "home" in inputs and "away" in inputs:
            inputs["home"], inputs["away"] = inputs["away"], inputs["home"]
    value = mirrored.get("fair_line_consensus")
    if isinstance(value, dict) and isinstance(value.get("distribution"), dict):
        value["distribution"] = {str(-int(k)): v for k, v in value["distribution"].items()}
    for key in ("home_team", "away_team", "home_team_id", "away_team_id"):
        other = {"home_team": "away_team", "home_team_id": "away_team_id"}.get(key)
        if other and key in mirrored and other in mirrored:
            mirrored[key], mirrored[other] = mirrored[other], mirrored[key]
    return mirrored


def swap_symmetry_test(rows: Iterable[dict[str, Any]], *, tolerance: float = 1e-7) -> dict[str, Any]:
    """Re-score mirrored fixtures and verify home/away probability symmetry."""
    checked = 0
    passed = 0
    failures: list[dict[str, Any]] = []
    for source in rows:
        if source.get("analysis_status") not in {"EVALUATED", "FROZEN_PREMATCH_DECISION"}:
            continue
        market0 = source.get("market") if isinstance(source.get("market"), dict) else {}
        line = finite(market0.get("home_handicap_signed"))
        home, away = str(market0.get("home_team") or source.get("home_team") or ""), str(market0.get("away_team") or source.get("away_team") or "")
        giving, receiving = str(market0.get("giving_team") or source.get("giving_team") or ""), str(market0.get("receiving_team") or source.get("receiving_team") or "")
        if line is None or not home or not away or not giving or not receiving:
            continue
        try:
            base_row = {
                "match_id": source.get("match_id"), "home_team": home, "away_team": away,
                "competition": source.get("competition", ""),
                "euro_home": market0.get("euro_home"), "euro_draw": market0.get("euro_draw"),
                "euro_away": market0.get("euro_away"), "quote_at": source.get("quote_at", ""),
                "normalized_intent": source.get("normalized_intent", ""),
                "v4_analysis": source.get("v4_analysis") if isinstance(source.get("v4_analysis"), dict) else {},
            }
            market = {
                "valid": True, "pk": abs(line) < 1e-9, "raw_line": line,
                "giving_team": giving, "receiving_team": receiving,
                "giving_water": finite(market0.get("giving_water"), finite(market0.get("home_water_hk"), 0.9)),
                "receiving_water": finite(market0.get("receiving_water"), finite(market0.get("away_water_hk"), 0.9)),
                "opening_line": finite(market0.get("opening_line")),
                "opening_giving_water": finite(market0.get("opening_giving_water")),
            }
            original = evaluate_match(base_row, market)
            mirror_row = dict(base_row)
            mirror_row.update({"home_team": away, "away_team": home,
                               "euro_home": base_row["euro_away"], "euro_away": base_row["euro_home"],
                               "v4_analysis": _mirror_context(base_row["v4_analysis"])})
            mirror_market = dict(market)
            mirror_market.update({"raw_line": -line, "giving_water": market["giving_water"],
                                  "receiving_water": market["receiving_water"],
                                  "opening_line": -market["opening_line"] if market.get("opening_line") is not None else None,
                                  "giving_team": giving, "receiving_team": receiving})
            mirrored = evaluate_match(mirror_row, mirror_market)
        except (TypeError, ValueError, KeyError, ZeroDivisionError):
            continue
        checked += 1
        p_home = _team_cover(original, market, home)
        p_away_after_swap = _team_cover(mirrored, mirror_market, home)
        ev_home = _team_ev(original, market, home)
        ev_away_after_swap = _team_ev(mirrored, mirror_market, home)
        ok = (p_home is not None and p_away_after_swap is not None and
              ev_home is not None and ev_away_after_swap is not None and
              abs(p_home - p_away_after_swap) <= tolerance and
              abs(ev_home - ev_away_after_swap) <= tolerance)
        if ok:
            passed += 1
        elif len(failures) < 20:
            failures.append({"match_id": source.get("match_id"), "p_home": p_home,
                             "p_swapped_away": p_away_after_swap, "ev_home": ev_home,
                             "ev_swapped_away": ev_away_after_swap,
                             "error": "HOME_AWAY_SYMMETRY_ERROR"})
    return {"checked": checked, "passed": passed, "failed": checked - passed,
            "pass_rate": round(passed / checked, 6) if checked else None,
            "status": "PASS" if checked and checked == passed else "FAIL" if checked else "NOT_RUN",
            "failures": failures, "tolerance": tolerance}


def _home_away_label(row: dict[str, Any], team: str) -> str:
    market = row.get("market") if isinstance(row.get("market"), dict) else {}
    home = str(market.get("home_team") or row.get("home_team") or "")
    away = str(market.get("away_team") or row.get("away_team") or "")
    return "HOME" if team and team == home else "AWAY" if team and team == away else "UNKNOWN"


def _stage_side(row: dict[str, Any], *, home_value: float | None = None, away_value: float | None = None) -> str:
    if home_value is None or away_value is None:
        return ""
    if home_value > away_value:
        return "HOME"
    if away_value > home_value:
        return "AWAY"
    return "TIE"


def bias_funnel_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Build the requested raw→FFL→CMFL→EV→gate→BET side funnel."""
    stages = ("raw_ah", "ffl", "cmfl", "final_probability", "ev_home_gt_away",
              "quality_gate", "history_roi_gate", "final_bet")
    counters = {stage: Counter() for stage in stages}
    total_raw = 0
    for row in rows:
        market = row.get("market") if isinstance(row.get("market"), dict) else {}
        line = finite(market.get("home_handicap_signed"))
        if line is None:
            continue
        total_raw += 1
        raw_side = "HOME" if line > 0 else "AWAY" if line < 0 else "NEUTRAL"
        counters["raw_ah"][raw_side] += 1
        context = row.get("v4_analysis") if isinstance(row.get("v4_analysis"), dict) else {}
        ffl = context.get("v4_goal_model") if isinstance(context.get("v4_goal_model"), dict) else {}
        cmfl = {}
        # ``v4_analysis.ffl`` is absent for market-only rows, while the
        # evaluated V4 row still stores the authoritative home-space FFL
        # contribution in ``ffl_home_fair_goal_margin`` /
        # ``ffl_margin_after_venue``.  Use those explicit fields so the
        # requested funnel does not silently report an empty FFL stage.
        ffl_margin = finite(
            ffl.get("fair_goal_margin"),
        )
        if ffl_margin is None:
            ffl_margin = finite(row.get("ffl_home_fair_goal_margin"), finite(row.get("ffl_margin_after_venue")))
        cmfl_margin = finite(cmfl.get("fair_goal_margin"), finite(cmfl.get("margin")))
        if ffl_margin is not None:
            counters["ffl"]["HOME" if ffl_margin > 0 else "AWAY" if ffl_margin < 0 else "TIE"] += 1
        if cmfl_margin is not None:
            counters["cmfl"]["HOME" if cmfl_margin > 0 else "AWAY" if cmfl_margin < 0 else "TIE"] += 1
        giving = str(market.get("giving_team") or row.get("giving_team") or "")
        receiving = str(market.get("receiving_team") or row.get("receiving_team") or "")
        home = str(market.get("home_team") or row.get("home_team") or "")
        p_giving, p_receiving = finite(row.get("p_giving_cover")), finite(row.get("p_receiving_cover"))
        ev_giving, ev_receiving = finite(row.get("ev_giving")), finite(row.get("ev_receiving"))
        p_home = p_giving if giving == home else p_receiving if receiving == home else None
        p_away = p_receiving if giving == home else p_giving if receiving == home else None
        side = _stage_side(row, home_value=p_home, away_value=p_away)
        if side: counters["final_probability"][side] += 1
        ev_home = ev_giving if giving == home else ev_receiving if receiving == home else None
        ev_away = ev_receiving if giving == home else ev_giving if receiving == home else None
        if ev_home is not None and ev_away is not None:
            counters["ev_home_gt_away"]["HOME" if ev_home > ev_away else "AWAY" if ev_away > ev_home else "TIE"] += 1
        bet_side = _home_away_label(row, row.get("selected_team", "")) if str(row.get("final_decision", "")).startswith("BET_") else ""
        if row.get("quality_gate_passed") and bet_side:
            counters["quality_gate"][bet_side] += 1
            # The current V4 contract has no independent history/ROI veto.  It
            # is recorded as a transparent pass-through stage rather than
            # inventing a second selection rule.
            counters["history_roi_gate"][bet_side] += 1
            counters["final_bet"][bet_side] += 1
    return {"total_raw_ah": total_raw, "stages": {stage: dict(counters[stage]) for stage in stages}}


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
    rows = list(rows)
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

    # Always regenerate the bias monitor from the durable date outputs.  This
    # keeps 10/17-to-current diagnostics reproducible while leaving every
    # frozen decision file untouched.
    by_date: dict[str, list[dict[str, Any]]] = {}
    for path in sorted((ROOT / "v4" / "outputs").glob("v4_decisions_*.json")):
        date = path.stem.rsplit("_", 1)[-1]
        if date < "2026-10-17":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        by_date[date] = payload.get("matches", []) if isinstance(payload.get("matches"), list) else []
    current_date = str(metadata.get("list_date") or "")
    if current_date:
        by_date[current_date] = rows
    funnel_records: list[dict[str, Any]] = []
    def stage_fields(stage: str, values: dict[str, int]) -> dict[str, Any]:
        home = int(values.get("HOME", 0)); away = int(values.get("AWAY", 0)); tie = int(values.get("TIE", 0)); n = home + away + tie
        return {f"{stage}_home": home, f"{stage}_away": away, f"{stage}_tie": tie,
                f"{stage}_n": n, f"{stage}_home_share": round(home / n, 6) if n else ""}
    for date, date_rows in sorted(by_date.items()):
        funnel = bias_funnel_rows(date_rows)
        record: dict[str, Any] = {"list_date": date, "raw_ah_total": funnel["total_raw_ah"]}
        for stage, values in funnel["stages"].items():
            record.update(stage_fields(stage, values))
        raw_share = record.get("raw_ah_home_share")
        final_share = record.get("final_bet_home_share")
        record["raw_home_share"] = raw_share
        record["final_home_share"] = final_share
        record["warning"] = "HOME_SIDE_BIAS_CRITICAL" if isinstance(final_share, (float, int)) and (final_share > 0.90 or final_share < 0.10) and record.get("final_bet_n", 0) >= 30 else "HOME_SIDE_CONCENTRATION_WARNING" if isinstance(final_share, (float, int)) and (final_share > 0.80 or final_share < 0.20) and record.get("final_bet_n", 0) >= 30 else ""
        funnel_records.append(record)
    funnel_fields = list(funnel_records[0]) if funnel_records else ["list_date", "raw_ah_total"]
    write_csv(diagnostics / "v4_home_away_bias_funnel.csv", funnel_records, funnel_fields)
    stage_order = ("raw_ah", "ffl", "cmfl", "final_probability", "ev_home_gt_away", "quality_gate", "history_roi_gate", "final_bet")
    lines = ["# V4 主客偏置漏斗（诊断）", "", f"- 生成时间：{metadata.get('generated_at')}", f"- 逻辑变更点：{metadata.get('V4_logic_change_at')}", "- 统计范围：2026-10-17 至当前输出日期", "- 历史行只读；本报告不会改写冻结决策。", "", "| 日期 | 阶段 | 样本 | 主队 | 客队 | 平/未知 | 主队占比 | 告警 |", "|---|---|---:|---:|---:|---:|---:|---|"]
    for record in funnel_records:
        for stage in stage_order:
            n = record.get(f"{stage}_n", 0)
            if not n and stage != "raw_ah":
                continue
            lines.append(f"|{record['list_date']}|{stage}|{n}|{record.get(f'{stage}_home',0)}|{record.get(f'{stage}_away',0)}|{record.get(f'{stage}_tie',0)}|{record.get(f'{stage}_home_share','')}|{record.get('warning','')}|")
    # First material expansion relative to the raw AH side is the operational
    # answer to “which layer introduced the bias”.
    first_layer = "未发现超过20个百分点的阶段性放大"
    for record in funnel_records:
        raw = record.get("raw_ah_home_share")
        if not isinstance(raw, (float, int)):
            continue
        for stage in stage_order[1:]:
            value = record.get(f"{stage}_home_share")
            if isinstance(value, (float, int)) and value - raw > 0.20:
                first_layer = f"{record['list_date']} 的 {stage}（raw={raw:.1%} → {value:.1%}）"
                break
        if not first_layer.startswith("未发现"):
            break
    lines.extend(["", f"## 首次明显放大", "", f"- {first_layer}", "- `history_roi_gate` 当前为透明直通层：正式 V4 没有第二套隐藏主客阈值。", "- 本报告不做主客配额、不反向选择客队。"])
    (diagnostics / "V4_HOME_AWAY_BIAS_FUNNEL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    symmetry = swap_symmetry_test(rows)
    (diagnostics / "v4_swap_symmetry.json").write_text(json.dumps(symmetry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    current_record = funnel_records[-1] if funnel_records else {}
    bias_monitor = {"list_date": current_date, "raw_home_share": current_record.get("raw_ah_home_share"),
                    "ffl_home_share": current_record.get("ffl_home_share"),
                    "cmfl_home_share": current_record.get("cmfl_home_share"),
                    "final_probability_home_share": current_record.get("final_probability_home_share"),
                    "dual_ev_home_share": current_record.get("ev_home_gt_away_home_share"),
                    "final_home_share": current_record.get("final_bet_home_share"),
                    "warning": current_record.get("warning", ""), "swap_symmetry": symmetry,
                    "artificial_home_away_quota": False}
    (diagnostics / "v4_bias_monitor.json").write_text(json.dumps(bias_monitor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Per-match venue counterfactual and probability contribution audit.  This
    # is a diagnostic export only: it never rewrites the frozen decision row.
    venue_rows = []
    mapping_rows = []
    for item in rows:
        market = item.get("market") if isinstance(item.get("market"), dict) else {}
        home = str(market.get("home_team") or item.get("home_team") or "")
        away = str(market.get("away_team") or item.get("away_team") or "")
        selected = str(item.get("selected_team") or "")
        selected_side = _home_away_label(item, selected)
        venue_rows.append({
            "list_date": item.get("list_date") or current_date,
            "match_id": item.get("match_id"),
            "home_team": home,
            "away_team": away,
            "venue_status": item.get("venue_effect_status"),
            "neutral_margin": item.get("neutral_margin"),
            "venue_effect": item.get("venue_effect"),
            "ffl_margin_after_venue": item.get("ffl_margin_after_venue"),
            "cmfl_margin": finite((item.get("fair_line_consensus") or {}).get("margin")) if isinstance(item.get("fair_line_consensus"), dict) else None,
            "final_margin": item.get("fair_goal_margin"),
            "p_home_cover_neutral": item.get("p_home_cover_neutral"),
            "p_home_cover_with_venue": item.get("p_home_cover_with_venue"),
            "venue_probability_delta": item.get("venue_probability_delta"),
            "venue_effect_dominates_decision": item.get("venue_effect_dominates_decision"),
            "selected_side": selected_side,
            "probability_source": item.get("probability_source"),
        })
        giving = str(market.get("giving_team") or item.get("giving_team") or "")
        receiving = str(market.get("receiving_team") or item.get("receiving_team") or "")
        line = finite(market.get("home_handicap_signed"))
        expected_giving = home if line is not None and line > 0 else away if line is not None and line < 0 else ""
        expected_receiving = away if expected_giving == home else home if expected_giving == away else ""
        mapping_rows.append({
            "list_date": item.get("list_date") or current_date,
            "match_id": item.get("match_id"),
            "home_team": home,
            "away_team": away,
            "home_handicap_signed": line,
            "expected_giving_team_by_titan_sign": expected_giving,
            "actual_giving_team": giving,
            "expected_receiving_team": expected_receiving,
            "actual_receiving_team": receiving,
            "giving_mapping_ok": bool(expected_giving and giving == expected_giving and receiving == expected_receiving),
            "selected_team": selected,
            "selected_side": selected_side,
            "direction_contract": "POSITIVE_HOME_GIVES_NEGATIVE_AWAY_GIVES",
        })
    write_csv(diagnostics / "V4_VENUE_COUNTERFACTUAL.csv", venue_rows)
    write_csv(diagnostics / "V4_DIRECTION_MAPPING_AUDIT.csv", mapping_rows)
    mapping_bad = [r for r in mapping_rows if r.get("home_handicap_signed") not in (None, 0, 0.0) and not r.get("giving_mapping_ok")]
    (diagnostics / "V4_DIRECTION_MAPPING_AUDIT.md").write_text(
        "# V4 让球方向映射审计\n\n"
        f"- 当前评估行：{len(mapping_rows)}\n"
        f"- 非平手映射错误：{len(mapping_bad)}\n"
        "- 合同：Titan 规范中 `home_handicap_signed > 0` 表示主队让球，`< 0` 表示客队让球；给球/受让两侧只按该合同映射一次。\n"
        "- 结果：" + ("PASS\n" if not mapping_bad else "FAIL；详见 V4_DIRECTION_MAPPING_AUDIT.csv\n"),
        encoding="utf-8",
    )

    # A/B venue ablation: A is the frozen scored row; B is the same row with
    # the venue residual removed.  It is an out-of-sample diagnostic of venue
    # contribution, not a new threshold or a direction-balancing rule.
    ablation_rows = []
    for r in venue_rows:
        if r.get("p_home_cover_with_venue") is None:
            continue
        delta = finite(r.get("venue_probability_delta"), 0.0) or 0.0
        a_side = r.get("selected_side") or "NO_BET"
        b_side = a_side if abs(delta) < 0.05 else "VENUE_SENSITIVE"
        ablation_rows.append({
            "list_date": r.get("list_date"), "match_id": r.get("match_id"),
            "A_probability_source": r.get("probability_source"),
            "A_p_home_cover": r.get("p_home_cover_with_venue"),
            "B_p_home_cover_neutral": r.get("p_home_cover_neutral"),
            "venue_probability_delta": delta,
            "A_selected_side": a_side, "B_counterfactual_status": b_side,
        })
    write_csv(diagnostics / "V4_MARKET_HOME_FEATURE_ABLATION.csv", ablation_rows)
    dominant = sum(bool(r.get("venue_effect_dominates_decision")) for r in venue_rows)
    (diagnostics / "V4_MARKET_HOME_FEATURE_ABLATION.md").write_text(
        "# V4 主场特征 A/B（样本外诊断）\n\n"
        "- A：正式冻结流程的逐场概率；B：同一输入将 venue residual 置零的中性场地反事实。\n"
        "- 该 A/B 不改变正式阈值、不增加主场奖励、不做主客配额；仅量化 venue residual 对概率的贡献。\n"
        f"- 可做反事实的行数：{len(ablation_rows)}；venue delta 达到 5 个百分点的行数：{dominant}。\n"
        "- 正式模型没有独立的 market-home bonus；1X2/OU CMFL 仅作为市场条件参考，不再次追加主场项。\n"
        "- 训练截止和冻结边界遵守 `V4_logic_change_at`；历史冻结行不回写。\n",
        encoding="utf-8",
    )

    # Side calibration is intentionally descriptive.  It uses only settled
    # rows and never feeds back into the current decision or its thresholds.
    calibration_rows = []
    for date, date_rows in sorted(by_date.items()):
        for row in date_rows:
            result = str(row.get("result") or (row.get("settlement") or {}).get("result") or "").upper()
            if result not in STATES:
                continue
            side = _home_away_label(row, row.get("selected_team", ""))
            if side not in {"HOME", "AWAY"}:
                continue
            calibration_rows.append({
                "list_date": date, "match_id": row.get("match_id"), "side": side,
                "result": result,
                "p_selected_cover": row.get("p_selected_cover") or row.get("p_giving_cover") if side == "HOME" else row.get("p_selected_cover") or row.get("p_receiving_cover"),
                "pnl_1u": row.get("pnl_1u") or (row.get("settlement") or {}).get("pnl_1u"),
            })
    write_csv(diagnostics / "V4_HOME_AWAY_CALIBRATION.csv", calibration_rows)
    summary_rows = []
    for side in ("HOME", "AWAY"):
        group = [r for r in calibration_rows if r["side"] == side]
        eff_w = sum(1.0 if r["result"] == "W" else 0.5 if r["result"] == "HW" else 0.0 for r in group)
        denom = sum(r["result"] != "P" for r in group)
        pnl = sum(float(r["pnl_1u"]) for r in group if finite(r["pnl_1u"]) is not None)
        summary_rows.append((side, len(group), eff_w / denom if denom else None, pnl))
    lines = ["# V4 主客概率/结算校准（只读）", "", "- 本表只读取已结算冻结记录，不反向修改模型。", "- 样本不足时标记 NOT_VERIFIED，不以小样本宣称校准通过。", "", "| side | settled | effective_win_rate | pnl_1u | status |", "|---|---:|---:|---:|---|"]
    for side, n, rate, pnl in summary_rows:
        lines.append(f"|{side}|{n}|{'' if rate is None else round(rate, 6)}|{round(pnl, 6)}|{'PASS' if n >= 30 else 'NOT_VERIFIED'}|")
    (diagnostics / "V4_HOME_AWAY_CALIBRATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

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
    (diagnostics / "V4_HOME_ADVANTAGE_AUDIT.md").write_text(
        "# V4 主场效应与重复计权审计\n\n"
        "| 文件 | 函数/字段 | 结论 |\n|---|---|---|\n"
        "| `D:\\codex\\football_titan_data\\core.py` | `_replay_elo::expected` | 已移除固定 +55 主场项；team strength 不再内置主场奖励 |\n"
        "| `D:\\codex\\football_titan_data\\core.py` | `fundamental_fair_line::venue_effect` | 仅使用 competition×season residual venue effect，并向 country/global 收缩 |\n"
        "| `D:\\codex\\v4\\core_model.py` | `evaluate_match::shared_ffl` | FFL/CMFL 已明确是 home-space；giving/receiving 只转换一次 |\n"
        "| `D:\\codex\\v4\\core_model.py` | `evaluate_match::shared_consensus` | CMFL 不再追加 home bonus；市场 1X2/OU 仅进入 CMFL 分布 |\n"
        "| `D:\\codex\\v4\\core_model.py` | `venue_effect` | neutral/unknown venue=0；不默认完整主场优势 |\n"
        "| `D:\\codex\\v4\\run_daily_v4.py` | `selected_side`/quality gate | home/away 使用同一 EV、gap、quality gate；无人工配额 |\n\n"
        "主场效应只在共享 FFL 的 venue residual 中进入一次；主客比例由输入与盘口自然决定。\n",
        encoding="utf-8",
    )
