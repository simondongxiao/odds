from __future__ import annotations

"""Read-only pricing funnel diagnostics.

This module deliberately sits after pricing/decision generation.  It does not
change a forecast, a threshold, a blocker, a quote, or an execution decision.
Its job is to explain where each market stopped and whether the stop was an
engineering/data-availability/model/risk condition.
"""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .common import atomic, stamp
from .source import game_minutes_for


STAGES = [
    "DISCOVERED", "CANONICALIZED", "MARKET_FOUND", "FRESH_MARKET", "LEAGUE_RULE_READY",
    "TEAM_MAPPING_READY", "HISTORY_READY", "BASE_STATS_READY",
    "SPREAD_FEATURES_READY", "TOTAL_FEATURES_READY", "SPREAD_PRICEABLE",
    "TOTAL_PRICEABLE", "EVIDENCE_GATE", "EDGE_GATE", "EXECUTION_GATE",
]

MARKETS = ("SPREAD", "TOTAL")
KNOWN_REGISTRY_FAMILIES = {
    "NBA", "WNBA", "NBA_SUMMER", "G_LEAGUE", "NCAAB", "WNCAAB",
    "EUROLEAGUE", "CBA_REGULAR", "CBA_PLAYOFF", "CBA_PRESEASON",
    "CBA_SUMMER", "CBA_CLUB_CUP", "CHINA_CLUB_WARMUP", "FIBA_MEN",
    "FIBA_WOMEN", "FIBA_QUALIFIER", "FIBA_YOUTH", "B_LEAGUE", "KBL",
    "NBL_AU", "OTHER_DISCOVERED", "UNCLASSIFIED_DISCOVERED",
}

REASON_TEXT = {
    "NO_MARKET": "暂无同场盘口记录",
    "NO_FRESH_MARKET": "有盘口记录，但本轮没有可用新鲜报价",
    "STALE_MARKET": "有盘口记录，但全部报价已过期或未通过本轮时效检查",
    "CANONICAL_GAME_FAILED": "赛事未完成 canonical 归一",
    "LEAGUE_RULE_UNKNOWN": "联赛比赛规则未从注册表确认",
    "FRIENDLY_FORMAT_UNVERIFIED": "友谊赛赛制未获赛事级确认，保留硬风控",
    "TEAM_MAPPING_UNRESOLVED": "两队身份或球队映射未确认",
    "NO_TEAM_HISTORY": "没有可用的截止前球队历史",
    "INSUFFICIENT_TEAM_HISTORY": "截止前球队历史场次不足",
    "TEAM_ALIAS_HISTORY_MISMATCH": "球队别名与历史数据未能安全匹配",
    "NO_BOX_SCORE_HISTORY": "没有可审计的基础比分历史",
    "PACE_UNAVAILABLE": "回合数或可复算回合构成缺失",
    "PACE_MODEL_UNAVAILABLE": "回合数或可复算回合构成缺失，无法形成总分特征",
    "TOTAL_CORE_INPUT_INCOMPLETE": "总分核心输入不完整",
    "SPREAD_MODEL_INPUT_INCOMPLETE": "让分模型输入未形成公平分差",
    "TOTAL_MODEL_INPUT_INCOMPLETE": "总分关键输入未齐全",
    "SPREAD_CONTEXT_INCOMPLETE": "让分所需伤停/轮换/NetRtg上下文缺失",
    "TOTAL_CONTEXT_INCOMPLETE": "总分证据门槛未通过",
    "MODEL_CORE_INPUT_MISSING": "核心模型输入不完整",
    "HISTORY_ESS_TOO_LOW": "历史有效样本量不足",
    "OPPONENT_DIVERSITY_TOO_LOW": "加权对手多样性不足",
    "INSUFFICIENT_HISTORY": "纸面证据历史不足：每队仍需至少8场截止前有效比赛",
    "INSUFFICIENT_OPPONENT_DIVERSITY": "纸面证据对手覆盖不足：每队仍需至少3个不同对手",
    "TEAM_HISTORY_FEED_NOT_CAPTURED": "缺少真正的球队历史数据流",
    "ROSTER_STABILITY_MISSING": "Tier 3近30天阵容稳定性证据缺失",
    "CURRENT_ROSTER_UNVERIFIED": "当前名册未核验",
    "PROVIDER_DISAGREEMENT": "多来源盘口分歧超过既有完整性规则",
    "NO_EDGE": "已完成同场比较，但没有达到既有优势门槛",
    "EDGE_FOUND_EVIDENCE_BLOCKED": "发现优势，但被证据门槛阻止",
    "EDGE_FOUND_EXECUTION_BLOCKED": "发现优势，但被执行门槛阻止",
    "SHADOW_TRIGGERED": "已通过既有纸面触发条件",
    "TARGET_ALREADY_STARTED": "比赛已开始，不能补写赛前定价",
    "PIPELINE_EXCEPTION": "生产流水线出现异常",
    "NO_MATCHING_MARKET": "研究定价没有找到同市场可比盘口",
    "MARKET_TYPE_MISMATCH": "市场类型不匹配",
    "RULE_MISMATCH": "加时/时段规则不一致",
    "INVALID_MARKET": "盘口字段或价格无效",
    "SOURCE_CONFLICT": "多来源盘口冲突",
    "CANONICALIZATION_MISMATCH": "赛事 canonical 身份未能安全对应",
    "RESEARCH_ONLY_NO_MARKET": "仅有研究定价，未找到实时盘口",
    "OTHER": "其他未分类原因",
    "NO_RAW_EDGE": "原始模型与盘口差异未达到诊断阈值",
    "EDGE_REMOVED_BY_CALIBRATION": "原始优势被校准层显著收缩",
    "CALIBRATED_EDGE_BELOW_THRESHOLD": "校准后优势低于既有门槛",
    "PROBABILITY_BELOW_THRESHOLD": "校准后概率低于既有门槛",
    "NEGATIVE_EV": "校准后期望值为负",
    "EVIDENCE_BLOCKED": "证据门槛阻塞",
    "EXECUTION_BLOCKED": "执行门槛阻塞",
    "PRICE_EXHAUSTED": "价格已透支",
    "MARKET_MOVED": "盘口移动后不再满足原方向",
    "LOW_DATA_QUALITY": "数据质量不足",
    "SHADOW_TRIGGERED": "已通过既有纸面触发条件",
}

HISTORY_BLOCKERS = {
    "INSUFFICIENT_PRE_CUTOFF_HISTORY", "NO_EFFECTIVE_HISTORY",
    "NEGLIGIBLE_RECENT_HISTORY", "TEAM_HISTORY_FEED_NOT_CAPTURED",
    "ONLY_H2H_OR_SINGLE_OPPONENT", "COMPETITION_MISMATCH",
}
TOTAL_HARD_BLOCKERS = {
    "GAME_RULE_UNKNOWN", "POSSESSIONS_EVIDENCE_MISSING",
    "BASIC_OFFENSE_EVIDENCE_MISSING", "CLOSE_GAME_PREMIUM_VALUE_INVALID",
    "TOTAL_CONTEXT_INCOMPLETE",
}
ENGINEERING_REASONS = {
    "CANONICAL_GAME_FAILED", "LEAGUE_RULE_UNKNOWN", "TEAM_MAPPING_UNRESOLVED",
    "TEAM_ALIAS_HISTORY_MISMATCH", "PIPELINE_EXCEPTION", "LIVE_SOURCE_FAILED",
}
GENUINE_ABSENCE_REASONS = {
    "NO_MARKET", "NO_FRESH_MARKET", "NO_TEAM_HISTORY",
    "NO_BOX_SCORE_HISTORY", "PACE_UNAVAILABLE",
    "TARGET_ALREADY_STARTED",
}
MODEL_LIMITATION_REASONS = {
    "INSUFFICIENT_TEAM_HISTORY",
    "INSUFFICIENT_HISTORY", "INSUFFICIENT_OPPONENT_DIVERSITY", "TEAM_HISTORY_FEED_NOT_CAPTURED",
    "SPREAD_MODEL_INPUT_INCOMPLETE", "TOTAL_MODEL_INPUT_INCOMPLETE",
    "TOTAL_CORE_INPUT_INCOMPLETE", "PACE_MODEL_UNAVAILABLE",
    "MODEL_CORE_INPUT_MISSING", "HISTORY_ESS_TOO_LOW", "OPPONENT_DIVERSITY_TOO_LOW", "SPREAD_CONTEXT_INCOMPLETE",
    "TOTAL_CONTEXT_INCOMPLETE", "DIAGNOSTIC_ONLY_TIER3_ROSTER_STABILITY_30D_MISSING",
}
RISK_REASONS = {
    "PROVIDER_DISAGREEMENT", "NO_EDGE", "EDGE_FOUND_EVIDENCE_BLOCKED",
    "EDGE_FOUND_EXECUTION_BLOCKED", "PRICE_EXHAUSTED", "STALE_QUOTE",
    "UNKNOWN_OT_RULE", "SELECTION_DIRECTION_UNVERIFIED",
    "ROSTER_STABILITY_MISSING", "CURRENT_ROSTER_UNVERIFIED",
    "FRIENDLY_FORMAT_UNVERIFIED",
}

# This is a read-only diagnostic threshold. It is not an execution threshold
# and cannot create or remove a paper entry.
MIN_DIAGNOSTIC_EDGE_POINTS = 1.0


def _uniq(values):
    return list(dict.fromkeys(str(x) for x in values if x))


def _market_decision(row, market):
    return (row.get("execution") or {}).get("market_decisions", {}).get(market) or {}


def _market_quotes(row, market):
    return [q for q in (row.get("market") or {}).get("quotes", [])
            if q.get("market_type") == market]


def _market_states(row, market):
    quotes = _market_quotes(row, market)
    states = (row.get("market") or {}).get("quote_states", [])
    return [s for q, s in zip(quotes, states)] if len(states) == len((row.get("market") or {}).get("quotes", [])) else states


def _blockers(row, market):
    pricing = row.get("pricing") or {}
    decision = _market_decision(row, market)
    total = pricing.get("total_diagnostic") or {}
    values = list(pricing.get("blockers") or []) + list(decision.get("blockers") or [])
    if market == "TOTAL":
        values += list(total.get("hard_blockers") or []) + list(total.get("soft_missing") or [])
    return _uniq(values)


def _has_fresh_quote(row, market):
    qs = _market_quotes(row, market)
    allq = (row.get("market") or {}).get("quotes", [])
    states = (row.get("market") or {}).get("quote_states", [])
    for q, state in zip(allq, states):
        if q.get("market_type") == market and state.get("fresh_observation"):
            return True
    return bool(qs) and not states


def _has_raw_quote(row, market):
    qs = _market_quotes(row, market)
    allq = (row.get("market") or {}).get("quotes", [])
    states = (row.get("market") or {}).get("quote_states", [])
    return any(q.get("market_type") == market and state.get("raw_observation")
               for q, state in zip(allq, states)) or bool(qs) and not states


def _rule_ready(event):
    family = str(event.get("league_family") or "")
    registered_minutes, registered_source = game_minutes_for(event.get("league"))
    return bool(event.get("game_minutes") or event.get("game_minutes_source") not in (None, "UNKNOWN_NO_MINUTES_ASSUMED")
                or registered_minutes or registered_source != "UNKNOWN_NO_MINUTES_ASSUMED"
                or family in KNOWN_REGISTRY_FAMILIES)


def _history_ready(pricing):
    counts = pricing.get("team_game_counts") or {}
    if counts and min(counts.values()) >= 3:
        return not bool(set(pricing.get("blockers") or []) & HISTORY_BLOCKERS)
    return bool(pricing.get("input_games")) and not bool(set(pricing.get("blockers") or []) & HISTORY_BLOCKERS)


def _base_ready(pricing, market, event=None):
    if market == "TOTAL":
        diag = pricing.get("total_diagnostic") or {}
        hard = set(diag.get("hard_blockers") or [])
        if _rule_ready(event or {}):
            hard.discard("GAME_RULE_UNKNOWN")
        if hard & {"POSSESSIONS_EVIDENCE_MISSING", "BASIC_OFFENSE_EVIDENCE_MISSING", "GAME_RULE_UNKNOWN"}:
            return False
        return pricing.get("input_games", 0) > 0 and pricing.get("total_raw") is not None
    return pricing.get("input_games", 0) > 0 and pricing.get("mu_raw") is not None


def _features_ready(pricing, decision, market):
    if market == "SPREAD":
        return pricing.get("mu_raw") is not None and "SPREAD_CONTEXT_INCOMPLETE" not in (decision.get("blockers") or [])
    diag = pricing.get("total_diagnostic") or {}
    hard = set(diag.get("hard_blockers") or [])
    return pricing.get("total_raw") is not None and not (hard & TOTAL_HARD_BLOCKERS)


def _priceable(pricing, decision, market):
    if market == "SPREAD":
        return bool(pricing.get("mu_raw") is not None and _features_ready(pricing, decision, market))
    return bool(pricing.get("total_raw") is not None and _features_ready(pricing, decision, market))


def _pricing_mode(pricing):
    if pricing.get("prior_only_price"):
        return "PRIOR_ONLY"
    if pricing.get("cold_start_priceable") or pricing.get("bootstrap_history_used"):
        return "COLD_START"
    return "NATIVE"


def _explicit_calibrated_value(pricing, market):
    """Read an explicitly emitted calibrated value; never infer one from market blend."""
    keys = (
        ("calibrated_fair_spread", "fair_spread_calibrated", "mu_calibrated")
        if market == "SPREAD" else
        ("calibrated_fair_total", "fair_total_calibrated", "total_calibrated")
    )
    for key in keys:
        value = pricing.get(key)
        if isinstance(value, (int, float)):
            return float(value), key
    return None, "NOT_EMITTED"


def _market_line(decision):
    selected = decision.get("selected") or {}
    value = selected.get("line")
    return float(value) if isinstance(value, (int, float)) else None


def _comparability_reason(row, market, diag):
    pricing = row.get("pricing") or {}
    decision = _market_decision(row, market)
    blockers = set(diag.get("decision_blockers") or []) | set(pricing.get("blockers") or [])
    if not diag.get("market_found"):
        return "RESEARCH_ONLY_NO_MARKET" if pricing.get("research_priceable") else "NO_MATCHING_MARKET"
    if not diag.get("fresh_market_found"):
        return "STALE_MARKET"
    if "IDENTITY_CONFLICT" in blockers or "EVENT_IDENTITY_UNVERIFIED" in blockers:
        return "CANONICALIZATION_MISMATCH"
    if blockers & {"UNKNOWN_OT_RULE", "PERIOD_UNVERIFIED_OR_UNSUPPORTED", "MAIN_MARKET_UNVERIFIED"}:
        return "RULE_MISMATCH"
    if blockers & {"PROVIDER_DISAGREEMENT", "SOURCE_CONFLICT"}:
        return "SOURCE_CONFLICT"
    quotes = _market_quotes(row, market)
    if not quotes or any(q.get("raw_line") is None for q in quotes):
        return "INVALID_MARKET"
    if not decision.get("comparison_ready"):
        return "NO_MATCHING_MARKET"
    return "OTHER"


def _edge_metrics(row, market, diag):
    pricing = row.get("pricing") or {}
    decision = _market_decision(row, market)
    selected = decision.get("selected") or {}
    raw_key = "mu_raw" if market == "SPREAD" else "total_raw"
    raw_fair = pricing.get(raw_key)
    raw_fair = float(raw_fair) if isinstance(raw_fair, (int, float)) else None
    market_line = _market_line(decision)
    raw_edge = raw_fair - market_line if raw_fair is not None and market_line is not None else None
    calibrated_fair, calibrated_source = _explicit_calibrated_value(pricing, market)
    calibrated_edge = calibrated_fair - market_line if calibrated_fair is not None and market_line is not None else None
    raw_probability = selected.get("p_win") if isinstance(selected.get("p_win"), (int, float)) else None
    adjusted_probability = pricing.get("adjusted_cover_probability")
    if not isinstance(adjusted_probability, (int, float)):
        adjusted_probability = pricing.get("calibrated_probability")
    adjusted_ev = pricing.get("adjusted_ev")
    if not isinstance(adjusted_ev, (int, float)):
        adjusted_ev = pricing.get("calibrated_ev")
    raw_edge_found = bool(diag.get("comparison_ready") and raw_edge is not None and abs(raw_edge) >= MIN_DIAGNOSTIC_EDGE_POINTS)
    calibrated_edge_found = bool(calibrated_edge is not None and abs(calibrated_edge) >= MIN_DIAGNOSTIC_EDGE_POINTS)
    retention = None
    if raw_edge is not None and calibrated_edge is not None and abs(raw_edge) >= MIN_DIAGNOSTIC_EDGE_POINTS:
        retention = round(abs(calibrated_edge) / abs(raw_edge), 6)
    evidence_pass = bool(diag.get("priceable") and diag.get("evidence_gate_pass"))
    execution_pass = bool(diag.get("execution_gate_pass"))
    if execution_pass:
        primary = "SHADOW_TRIGGERED"
    elif not diag.get("comparison_ready"):
        primary = _comparability_reason(row, market, diag)
    elif not raw_edge_found:
        primary = "NO_RAW_EDGE"
    elif calibrated_fair is not None and not calibrated_edge_found:
        primary = "CALIBRATED_EDGE_BELOW_THRESHOLD"
    elif calibrated_fair is not None and retention is not None and retention <= 0.3 and abs(raw_edge) >= MIN_DIAGNOSTIC_EDGE_POINTS:
        primary = "EDGE_REMOVED_BY_CALIBRATION"
    elif adjusted_probability is not None and adjusted_probability < 0.55:
        primary = "PROBABILITY_BELOW_THRESHOLD"
    elif adjusted_ev is not None and adjusted_ev <= 0:
        primary = "NEGATIVE_EV"
    elif not evidence_pass:
        primary = "EVIDENCE_BLOCKED"
    elif "PRICE_EXHAUSTED" in (diag.get("decision_blockers") or []):
        primary = "PRICE_EXHAUSTED"
    elif "MARKET_MOVED" in (diag.get("decision_blockers") or []):
        primary = "MARKET_MOVED"
    else:
        primary = "EXECUTION_BLOCKED"
    secondary = list(diag.get("secondary_warnings") or [])
    if calibrated_source == "NOT_EMITTED":
        secondary.append("CALIBRATION_NOT_EMITTED_READ_ONLY")
    return {
        "pricing_mode": _pricing_mode(pricing),
        "market_line": market_line,
        "raw_fair_line": raw_fair,
        "raw_edge_points": raw_edge,
        "raw_edge_found": raw_edge_found,
        "raw_cover_probability": raw_probability,
        "calibrated_fair_line": calibrated_fair,
        "calibrated_edge_points": calibrated_edge,
        "calibrated_edge_found": calibrated_edge_found,
        "adjusted_probability": adjusted_probability,
        "adjusted_ev": adjusted_ev,
        "calibration_source": calibrated_source,
        "residual_scale": pricing.get("residual_scale_multiplier"),
        "league_residual_multiplier": pricing.get("league_residual_multiplier"),
        "meta_confidence": pricing.get("meta_confidence"),
        "model_weight": pricing.get("model_weight"),
        "market_weight": pricing.get("market_weight"),
        "data_quality": pricing.get("pricing_data_quality"),
        "evidence_status": "PASS" if evidence_pass else (diag.get("primary_block_reason") or "BLOCKED"),
        "execution_score": (decision.get("execution_score") if isinstance(decision.get("execution_score"), (int, float)) else None),
        "edge_retention_ratio": retention,
        "primary_final_reason": primary,
        "secondary_warnings": _uniq(secondary),
        "evidence_pass": evidence_pass,
        "execution_pass": execution_pass,
    }


def _category(reason):
    if reason in ENGINEERING_REASONS:
        return "FIXABLE_DATA_ENGINEERING"
    if reason in {"STALE_MARKET", "NO_FRESH_MARKET", "LIVE_SOURCE_FAILED"}:
        return "SOURCE_DEGRADATION"
    if reason in GENUINE_ABSENCE_REASONS:
        return "GENUINE_DATA_ABSENCE"
    if reason in MODEL_LIMITATION_REASONS:
        return "MODEL_REQUIREMENT"
    if reason in RISK_REASONS:
        return "INTENTIONAL_RISK_BLOCK"
    return "UNCLASSIFIED_REVIEW"


def _reason_for_stage(row, market, stage, blockers):
    pricing = row.get("pricing") or {}
    decision = _market_decision(row, market)
    if stage == "CANONICALIZED":
        return "CANONICAL_GAME_FAILED"
    if stage == "MARKET_FOUND":
        return "NO_MARKET" if not _market_quotes(row, market) else "NO_FRESH_MARKET"
    if stage == "LEAGUE_RULE_READY":
        event = row.get("event") or {}
        if event.get("league_family") == "FRIENDLY_CLUB" or event.get("model_family") == "HIGH_UNCERTAINTY":
            return "FRIENDLY_FORMAT_UNVERIFIED"
        return "LEAGUE_RULE_UNKNOWN"
    if stage == "TEAM_MAPPING_READY":
        return "TEAM_MAPPING_UNRESOLVED"
    if stage == "HISTORY_READY":
        if "NO_EFFECTIVE_HISTORY" in blockers:
            return "NO_TEAM_HISTORY"
        if "INSUFFICIENT_PRE_CUTOFF_HISTORY" in blockers:
            return "INSUFFICIENT_TEAM_HISTORY"
        if "COMPETITION_MISMATCH" in blockers:
            return "TEAM_ALIAS_HISTORY_MISMATCH"
        return "INSUFFICIENT_TEAM_HISTORY"
    if stage == "BASE_STATS_READY":
        diag = pricing.get("total_diagnostic") or {}
        if "POSSESSIONS_EVIDENCE_MISSING" in (diag.get("hard_blockers") or []):
            return "PACE_MODEL_UNAVAILABLE"
        return "NO_BOX_SCORE_HISTORY"
    if stage == "SPREAD_FEATURES_READY":
        return "SPREAD_CONTEXT_INCOMPLETE" if "SPREAD_CONTEXT_INCOMPLETE" in blockers else "SPREAD_MODEL_INPUT_INCOMPLETE"
    if stage == "TOTAL_FEATURES_READY":
        return "TOTAL_CONTEXT_INCOMPLETE" if "TOTAL_CONTEXT_INCOMPLETE" in blockers else "TOTAL_CORE_INPUT_INCOMPLETE"
    if stage in ("SPREAD_PRICEABLE", "TOTAL_PRICEABLE"):
        return "SPREAD_MODEL_INPUT_INCOMPLETE" if market == "SPREAD" else "TOTAL_MODEL_INPUT_INCOMPLETE"
    if stage == "EVIDENCE_GATE":
        priority = (
            "HISTORY_ESS_TOO_LOW", "OPPONENT_DIVERSITY_TOO_LOW",
            "INSUFFICIENT_HISTORY", "INSUFFICIENT_OPPONENT_DIVERSITY",
            "TEAM_HISTORY_FEED_NOT_CAPTURED", "ROSTER_STABILITY_MISSING",
            "CURRENT_ROSTER_UNVERIFIED", "SPREAD_CONTEXT_INCOMPLETE",
            "TOTAL_CONTEXT_INCOMPLETE", "MODEL_CORE_INPUT_MISSING",
        )
        return next((reason for reason in priority if reason in blockers), "MODEL_CORE_INPUT_MISSING")
    if stage == "EDGE_GATE":
        if decision.get("comparison_ready") and (decision.get("model_state") == "NO_EDGE" or (decision.get("ev") is not None and decision.get("ev") <= 0)):
            return "NO_EDGE"
        return "EDGE_FOUND_EVIDENCE_BLOCKED"
    if stage == "EXECUTION_GATE":
        return "SHADOW_TRIGGERED" if decision.get("triggered") else "EDGE_FOUND_EXECUTION_BLOCKED"
    return "UNCLASSIFIED_REVIEW"


def diagnose_market(row, market):
    event = row.get("event") or {}
    pricing = row.get("pricing") or {}
    decision = _market_decision(row, market)
    blockers = _blockers(row, market)
    canonicalized = bool(event.get("canonical_event_id") or event.get("event_id")) and bool(event.get("identity_verified", True))
    market_found = bool(_market_quotes(row, market))
    fresh_market_found = _has_fresh_quote(row, market)
    league_ready = _rule_ready(event)
    team_ready = bool(event.get("team1_id") and event.get("team2_id") and event.get("team1_name") and event.get("team2_name"))
    history_ready = _history_ready(pricing)
    base_ready = _base_ready(pricing, market, event) if history_ready else False
    features_ready = _features_ready(pricing, decision, market) if base_ready else False
    priceable = (_priceable(pricing, decision, market)
                 if (canonicalized and league_ready and team_ready and history_ready and base_ready and features_ready)
                 else False)
    evidence_blocked = bool(set(blockers) & {
        "MODEL_CORE_INPUT_MISSING", "HISTORY_ESS_TOO_LOW", "INSUFFICIENT_HISTORY",
        "OPPONENT_DIVERSITY_TOO_LOW",
        "INSUFFICIENT_OPPONENT_DIVERSITY", "TEAM_HISTORY_FEED_NOT_CAPTURED",
        "ROSTER_STABILITY_MISSING", "CURRENT_ROSTER_UNVERIFIED",
        "SPREAD_CONTEXT_INCOMPLETE", "TOTAL_CONTEXT_INCOMPLETE",
    })
    comparable = bool(decision.get("comparison_ready") and market_found)
    edge = bool(comparable and ((decision.get("model_state") in ("EDGE", "LEAN")) or (decision.get("ev") is not None and decision.get("ev") > 0)))
    # A legacy/aggregate decision can carry a selected market while this
    # branch has no quote. The branch diagnostic must follow its own market.
    triggered = bool(decision.get("triggered") and market_found)
    stages = {
        "DISCOVERED": True,
        "CANONICALIZED": canonicalized,
        "MARKET_FOUND": market_found,
        "FRESH_MARKET": fresh_market_found,
        "LEAGUE_RULE_READY": fresh_market_found and league_ready,
        "TEAM_MAPPING_READY": fresh_market_found and team_ready,
        "HISTORY_READY": fresh_market_found and history_ready,
        "BASE_STATS_READY": fresh_market_found and base_ready,
        "SPREAD_FEATURES_READY" if market == "SPREAD" else "TOTAL_FEATURES_READY": fresh_market_found and features_ready,
        "SPREAD_PRICEABLE" if market == "SPREAD" else "TOTAL_PRICEABLE": fresh_market_found and priceable,
        "EVIDENCE_GATE": fresh_market_found and priceable and not evidence_blocked,
        "EDGE_GATE": fresh_market_found and priceable and comparable and edge,
        "EXECUTION_GATE": fresh_market_found and triggered,
    }
    # A market without a quote or without a fresh quote is terminal before any
    # model/history branch.  This keeps FRESH_MARKET visible in the funnel and
    # prevents stale observations from being misclassified as model failure.
    if not market_found:
        primary_stage = "MARKET_FOUND"
    elif not fresh_market_found:
        primary_stage = "MARKET_FOUND"
    elif not canonicalized:
        primary_stage = "CANONICALIZED"
    elif not league_ready:
        primary_stage = "LEAGUE_RULE_READY"
    elif not team_ready:
        primary_stage = "TEAM_MAPPING_READY"
    elif not history_ready:
        primary_stage = "HISTORY_READY"
    elif not base_ready:
        primary_stage = "BASE_STATS_READY"
    elif not features_ready:
        primary_stage = "SPREAD_FEATURES_READY" if market == "SPREAD" else "TOTAL_FEATURES_READY"
    elif not priceable:
        primary_stage = "SPREAD_PRICEABLE" if market == "SPREAD" else "TOTAL_PRICEABLE"
    elif evidence_blocked:
        primary_stage = "EVIDENCE_GATE"
    elif comparable and not edge:
        primary_stage = "EDGE_GATE"
    elif edge and not triggered:
        primary_stage = "EXECUTION_GATE"
    else:
        primary_stage = "EXECUTION_GATE"
    primary_reason = "SHADOW_TRIGGERED" if triggered else _reason_for_stage(row, market, primary_stage, blockers)
    if market_found and not fresh_market_found:
        primary_reason = "STALE_MARKET"
    if primary_stage == "EDGE_GATE" and comparable and not edge:
        primary_reason = "NO_EDGE"
    if primary_stage == "EXECUTION_GATE" and edge and not triggered:
        primary_reason = "EDGE_FOUND_EXECUTION_BLOCKED"
    secondary = _uniq([b for b in blockers if b != primary_reason])
    status = "SHADOW_TRIGGERED" if triggered else (
        "PRICEABLE_NO_EDGE" if priceable and comparable and not edge else
        "EDGE_FOUND_EVIDENCE_BLOCKED" if edge and evidence_blocked else
        "EDGE_FOUND_EXECUTION_BLOCKED" if edge and not triggered else
        "NOT_PRICEABLE" if not priceable else "NOT_PRICEABLE")
    if not market_found:
        terminal_status = "NO_MARKET"
    elif not fresh_market_found:
        terminal_status = "STALE_MARKET"
    elif not canonicalized:
        terminal_status = "MAPPING_BLOCKED"
    elif not league_ready:
        terminal_status = "RULE_BLOCKED"
    elif not team_ready:
        terminal_status = "MAPPING_BLOCKED"
    elif not history_ready:
        terminal_status = "HISTORY_BLOCKED"
    elif not base_ready:
        terminal_status = "BASE_STATS_BLOCKED"
    elif not features_ready or not priceable:
        terminal_status = "FEATURE_BLOCKED"
    elif evidence_blocked:
        terminal_status = "EVIDENCE_BLOCKED"
    elif comparable and not edge:
        terminal_status = "PRICEABLE_NO_EDGE"
    elif edge and not triggered:
        terminal_status = "EXECUTION_BLOCKED"
    else:
        terminal_status = "SHADOW_TRIGGERED"
    edge_metrics = _edge_metrics(row, market, {
        "market_found": market_found,
        "fresh_market_found": fresh_market_found,
        "priceable": priceable,
        "evidence_gate_pass": bool(priceable and not evidence_blocked),
        "comparison_ready": comparable,
        "edge_found": edge,
        "execution_gate_pass": triggered,
        "primary_block_reason": primary_reason,
        "decision_blockers": blockers,
        "secondary_warnings": secondary,
    })
    return {
        "market_type": market, "stage_reached": primary_stage,
        "stage_status": stages, "market_found": market_found,
        "fresh_market_found": fresh_market_found,
        "raw_market_found": _has_raw_quote(row, market),
        "league_rule_ready": league_ready, "team_mapping_ready": team_ready,
        "history_ready": history_ready, "base_stats_ready": base_ready,
        "features_ready": features_ready, "priceable": priceable,
        "evidence_gate_pass": bool(priceable and not evidence_blocked),
        "comparison_ready": comparable, "edge_found": edge,
        "execution_gate_pass": triggered, "primary_block_stage": primary_stage,
        "primary_block_reason": primary_reason,
        "primary_block_reason_text": REASON_TEXT.get(primary_reason, primary_reason),
        "secondary_warnings": secondary, "status": status,
        "block_category": _category(primary_reason),
        "quality": pricing.get("pricing_data_quality"),
        "fair_value": pricing.get("mu_raw" if market == "SPREAD" else "total_raw"),
        "market_value": (decision.get("selected") or {}).get("line") if market_found else None,
        "edge": (decision.get("selected") or {}).get("ev") if comparable else None,
        "decision_blockers": blockers,
        "terminal_status": terminal_status,
        "edge_metrics": edge_metrics,
    }


def _event_row(row, spread, total, history_event=None):
    event = row.get("event") or {}
    pricing = row.get("pricing") or {}
    execution = row.get("execution") or {}
    return {
        "event_id": row.get("id") or event.get("event_id"),
        "canonical_event_id": event.get("canonical_event_id") or event.get("event_id"),
        "league": event.get("league"), "league_family": event.get("league_family"),
        "region": event.get("region"), "team1": event.get("team1_name"),
        "team2": event.get("team2_name"), "tip_time_bj": event.get("tip_time_bj") or event.get("tip_at"),
        "archive_type": row.get("archive_type"), "pricing_status": pricing.get("pricing_status"),
        "model_family": pricing.get("model_family") or event.get("model_family"),
        "league_tier": pricing.get("league_tier"), "spread": spread, "total": total,
        "primary_block_stage": spread.get("primary_block_stage") if not spread.get("priceable") else total.get("primary_block_stage") if not total.get("priceable") else None,
        "primary_block_reason": spread.get("primary_block_reason") if not spread.get("priceable") else total.get("primary_block_reason") if not total.get("priceable") else None,
        "secondary_warnings": _uniq(spread.get("secondary_warnings", []) + total.get("secondary_warnings", [])),
        "pricing_data_quality": pricing.get("pricing_data_quality"),
        "fair_spread": pricing.get("mu_raw"), "market_spread": (execution.get("selected") or {}).get("line"),
        "spread_edge": spread.get("edge"), "fair_total": pricing.get("total_raw"),
        "market_total": _market_decision(row, "TOTAL").get("selected", {}).get("line") if _market_decision(row, "TOTAL").get("selected") else None,
        "total_edge": total.get("edge"), "final_status": execution.get("shadow_action") or "BLOCKED",
        "canonicalized": bool((event.get("canonical_event_id") or event.get("event_id")) and event.get("identity_verified", True)),
        "league_rule_ready": _rule_ready(event),
        "team_mapping_ready": bool(event.get("team1_id") and event.get("team2_id") and event.get("team1_name") and event.get("team2_name")),
        "history_ready": bool(spread.get("history_ready") or total.get("history_ready")),
        "base_stats_ready": bool(spread.get("base_stats_ready") or total.get("base_stats_ready")),
        "spread_features_ready": spread.get("features_ready"), "total_features_ready": total.get("features_ready"),
        "spread_priceable": spread.get("priceable"), "total_priceable": total.get("priceable"),
        "spread_primary_block_stage": spread.get("primary_block_stage"), "spread_primary_block_reason": spread.get("primary_block_reason"),
        "total_primary_block_stage": total.get("primary_block_stage"), "total_primary_block_reason": total.get("primary_block_reason"),
        "spread_final_status": spread.get("status"), "total_final_status": total.get("status"),
        "spread_terminal_status": spread.get("terminal_status"), "total_terminal_status": total.get("terminal_status"),
        "history_readiness": history_event or {},
    }


def _counts(records):
    terminal_counts = Counter(r.get("terminal_status", "UNKNOWN") for r in records)
    market_found = sum(r["market_found"] for r in records)
    fresh_market = sum(r["fresh_market_found"] for r in records)
    priceable = sum(r["priceable"] for r in records)
    return {
        "events_total": len(records),
        "market_found": market_found,
        "no_market": sum(r.get("terminal_status") == "NO_MARKET" for r in records),
        "fresh_market": fresh_market,
        "stale_market": sum(r.get("terminal_status") == "STALE_MARKET" for r in records),
        "market_found_but_not_priceable": sum(r["market_found"] and not r["priceable"] for r in records),
        "fresh_market_but_not_priceable": sum(r["fresh_market_found"] and not r["priceable"] for r in records),
        "priceable": priceable,
        # Compatibility aliases used by the existing dashboard/tests.
        "events": len(records), "market_events": market_found,
        "fresh_market_events": fresh_market,
        "edge_found": sum(r["edge_found"] for r in records),
        "shadow_triggered": sum(r["status"] == "SHADOW_TRIGGERED" for r in records),
        "priceable_no_edge": sum(r["status"] == "PRICEABLE_NO_EDGE" for r in records),
        "evidence_blocked": sum(r["status"] == "EDGE_FOUND_EVIDENCE_BLOCKED" for r in records),
        "execution_blocked": sum(r["status"] == "EDGE_FOUND_EXECUTION_BLOCKED" for r in records),
        "terminal_counts": dict(terminal_counts),
        "terminal_accounting_expected": len(records),
        "terminal_accounting_actual": sum(terminal_counts.values()),
    }


def _is_comparable_record(record):
    """A comparable sample must be priceable, fresh, and same-market comparable."""
    return bool(
        record.get("priceable")
        and record.get("fresh_market_found")
        and record.get("market_found")
        and record.get("comparison_ready")
    )


def _median(values):
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 6)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 6)


def _retention_groups(records):
    """Group retention without changing any model or gate value."""
    groups = defaultdict(list)
    for record in records:
        if not _is_comparable_record(record):
            continue
        ratio = (record.get("edge_metrics") or {}).get("edge_retention_ratio")
        if ratio is None:
            continue
        market = record.get("market_type")
        league = record.get("league") or record.get("league_family") or "UNCLASSIFIED"
        tier = record.get("league_tier") or "UNKNOWN"
        mode = (record.get("edge_metrics") or {}).get("pricing_mode") or "UNKNOWN"
        keys = [("MARKET", market), ("LEAGUE", league), ("TIER", tier), ("PRICING_MODE", mode)]
        if market == "SPREAD":
            line = (record.get("edge_metrics") or {}).get("market_line")
            depth = "DEEP_SPREAD" if isinstance(line, (int, float)) and abs(line) >= 8 else "NORMAL_SPREAD"
            keys.append(("SPREAD_DEPTH", depth))
        for dimension, value in keys:
            groups[f"{dimension}:{value}"].append(ratio)
    return {
        key: {
            "sample_size": len(values),
            "mean_edge_retention": round(sum(values) / len(values), 6),
            "median_edge_retention": _median(values),
            "possible_over_shrinkage": sum(v <= 0.3 for v in values) / len(values) >= 0.5,
        }
        for key, values in sorted(groups.items())
    }


def _edge_funnel(records):
    """Return a market-separated, read-only Edge Funnel and terminal reasons."""
    result = {}
    for market in MARKETS:
        subset = [r for r in records if r["market_type"] == market]
        metrics = [r.get("edge_metrics") or {} for r in subset]
        comparable = [r for r in subset if _is_comparable_record(r)]
        reasons = Counter((m.get("primary_final_reason") or "OTHER") for r, m in zip(subset, metrics))
        not_comparable_reasons = Counter(
            (r.get("edge_metrics") or {}).get("primary_final_reason", "OTHER")
            for r in subset
            if r.get("priceable") and not _is_comparable_record(r)
        )
        result[market] = {
            "market_found": sum(r.get("market_found", False) for r in subset),
            "fresh_market": sum(r.get("fresh_market_found", False) for r in subset),
            "research_priceable": sum(r.get("priceable", False) for r in subset),
            "market_comparable": len(comparable),
            "not_comparable": sum(r.get("priceable", False) and not r.get("comparison_ready", False) for r in subset),
            "raw_edge_found": sum(m.get("raw_edge_found", False) for r, m in zip(subset, metrics)),
            "calibrated_edge_found": sum(m.get("calibrated_edge_found", False) for r, m in zip(subset, metrics)),
            "evidence_pass": sum(m.get("evidence_pass", False) for r, m in zip(subset, metrics)),
            "execution_pass": sum(m.get("execution_pass", False) for r, m in zip(subset, metrics)),
            "shadow_triggered": sum(r.get("status") == "SHADOW_TRIGGERED" for r in subset),
            "primary_final_reasons": dict(reasons),
            "priceable_not_comparable_reasons": dict(not_comparable_reasons),
            "calibration_not_emitted": sum(m.get("calibration_source") == "NOT_EMITTED" for r, m in zip(subset, metrics) if r.get("comparison_ready")),
        }
    comparable_rows = [r for r in records if _is_comparable_record(r)]
    retentions = [r["edge_metrics"]["edge_retention_ratio"] for r in comparable_rows if r.get("edge_metrics", {}).get("edge_retention_ratio") is not None]
    return {
        "markets": result,
        "comparable_total": len(comparable_rows),
        "primary_final_reasons": dict(Counter((r.get("edge_metrics") or {}).get("primary_final_reason", "OTHER") for r in comparable_rows)),
        "priceable_not_comparable_reasons": dict(Counter(
            (r.get("edge_metrics") or {}).get("primary_final_reason", "OTHER")
            for r in records if r.get("priceable") and not _is_comparable_record(r)
        )),
        "retention": {
            "diagnostic_threshold_points": MIN_DIAGNOSTIC_EDGE_POINTS,
            "sample_size": len(retentions),
            "mean_edge_retention": round(sum(retentions) / len(retentions), 6) if retentions else None,
            "median_edge_retention": _median(retentions),
            "possible_over_shrinkage": bool(retentions and sum(x <= 0.3 for x in retentions) / len(retentions) >= 0.5),
        },
        "retention_by_group": _retention_groups(records),
    }


def _comparable_edge_rows(records):
    rows = []
    for r in records:
        if not _is_comparable_record(r):
            continue
        m = r.get("edge_metrics") or {}
        rows.append({
            "game_id": r.get("canonical_event_id") or r.get("event_id"),
            "league": r.get("league"), "market_type": r.get("market_type"),
            "home_team": r.get("team1"), "away_team": r.get("team2"),
            "start_time": r.get("tip_time_bj"), "pricing_mode": m.get("pricing_mode"),
            "market_line": m.get("market_line"), "raw_fair_line": m.get("raw_fair_line"),
            "raw_edge_points": m.get("raw_edge_points"), "raw_probability": m.get("raw_cover_probability"),
            "calibrated_fair_line": m.get("calibrated_fair_line"),
            "calibrated_edge_points": m.get("calibrated_edge_points"),
            "adjusted_probability": m.get("adjusted_probability"), "adjusted_EV": m.get("adjusted_ev"),
            "residual_scale": m.get("residual_scale"),
            "league_residual_multiplier": m.get("league_residual_multiplier"),
            "meta_confidence": m.get("meta_confidence"), "model_weight": m.get("model_weight"),
            "market_weight": m.get("market_weight"), "data_quality": m.get("data_quality"),
            "evidence_status": m.get("evidence_status"), "execution_score": m.get("execution_score"),
            "edge_retention_ratio": m.get("edge_retention_ratio"),
            "primary_final_reason": m.get("primary_final_reason"),
            "secondary_warnings": json.dumps(m.get("secondary_warnings", []), ensure_ascii=False),
        })
    return rows


def _conversion(records):
    def n(stage, eligible=None):
        return sum(r["stage_status"].get(stage, False) and (eligible is None or eligible(r)) for r in records)
    def rate(numerator, denominator):
        return None if not denominator else round(numerator / denominator, 4)
    market = n("FRESH_MARKET")
    mapping = n("CANONICALIZED", lambda r: r["fresh_market_found"])
    history = n("HISTORY_READY", lambda r: r["fresh_market_found"] and r["stage_status"].get("CANONICALIZED", False))
    base = n("BASE_STATS_READY", lambda r: r["history_ready"] and r["fresh_market_found"])
    spread_features = n("SPREAD_FEATURES_READY", lambda r: r["base_stats_ready"] and r["fresh_market_found"])
    total_features = n("TOTAL_FEATURES_READY", lambda r: r["base_stats_ready"] and r["fresh_market_found"])
    priceable = n("SPREAD_PRICEABLE") + n("TOTAL_PRICEABLE")
    edge = sum(r["edge_found"] for r in records)
    shadow = sum(r["status"] == "SHADOW_TRIGGERED" for r in records)
    return {
        "market_to_mapping": rate(mapping, market),
        "mapping_to_history": rate(history, mapping),
        "history_to_base_stats": rate(base, history),
        "base_to_spread_pricing": rate(spread_features, base),
        "base_to_total_pricing": rate(total_features, base),
        "pricing_to_edge": rate(edge, priceable),
        "edge_to_shadow": rate(shadow, edge),
        "counts": {"market": market, "mapping": mapping, "history": history,
                    "base_stats": base, "spread_features": spread_features,
                    "total_features": total_features, "priceable_markets": priceable,
                    "edge": edge, "shadow": shadow, "records": len(records)},
    }


def build_pricing_funnel_diagnostic(rows, root, day, asof, source_health=None, history_readiness=None):
    """Build and persist the diagnostic without modifying rows."""
    root = Path(root)
    row_dates=[]
    for row in rows:
        event=row.get('event') or {}
        row_dates.append(event.get('bj_date') or str(event.get('tip_time_bj') or event.get('tip_at') or '')[:10] or None)
    mismatched=[{"event_id":row.get("id") or (row.get("event") or {}).get("event_id"),"bj_date":date_value}
                for row,date_value in zip(rows,row_dates) if date_value!=day]
    canonical_ids=[(row.get('event') or {}).get('canonical_event_id') or row.get('id') or (row.get('event') or {}).get('event_id') for row in rows]
    duplicates=[key for key,count in Counter(canonical_ids).items() if key and count>1]
    if mismatched:
        raise AssertionError(f"PRICING_FUNNEL_DATE_SCOPE_ERROR: requested {day}, mismatched={mismatched[:10]}")
    if duplicates:
        raise AssertionError(f"PRICING_FUNNEL_CANONICAL_DUPLICATE_ERROR: {duplicates[:10]}")
    # Imported lazily so the league layer can reuse this module's canonical
    # market diagnostic without creating an import cycle.
    from .league_funnel_diagnostic import _record_from_row, build_league_funnel_diagnostic
    all_records, event_rows = [], []
    for row in rows:
        spread, total = diagnose_market(row, "SPREAD"), diagnose_market(row, "TOTAL")
        pricing = row.get("pricing") or {}
        hmap = {x.get("event_id"): x for x in (history_readiness or {}).get("events", [])}
        event_rows.append(_event_row(row, spread, total, hmap.get(row.get("id") or (row.get("event") or {}).get("event_id"))))
        for rec in (spread, total):
            rec = dict(rec)
            rec.update({"event_id": row.get("id") or (row.get("event") or {}).get("event_id"),
                        "league": (row.get("event") or {}).get("league"),
                        "league_family": (row.get("event") or {}).get("league_family"),
                        "league_tier": pricing.get("league_tier") or (row.get("event") or {}).get("league_tier"),
                        "region": (row.get("event") or {}).get("region"),
                        "tip_time_bj": (row.get("event") or {}).get("tip_time_bj"),
                        "team1": (row.get("event") or {}).get("team1_name"),
                        "team2": (row.get("event") or {}).get("team2_name"),
                        "history_readiness": next((x for x in (history_readiness or {}).get("events", []) if x.get("event_id") == (row.get("id") or (row.get("event") or {}).get("event_id"))), {} )})
            all_records.append(rec)
    by_market = {m: _counts([r for r in all_records if r["market_type"] == m]) for m in MARKETS}
    edge_funnel = _edge_funnel(all_records)
    comparable_edge_rows = _comparable_edge_rows(all_records)
    stage_counts = {stage: sum(r["stage_status"].get(stage, False) for r in all_records) for stage in STAGES}
    terminal_expected = len(rows) * len(MARKETS)
    terminal_actual = sum(sum(v.get("terminal_counts", {}).values()) for v in by_market.values())
    accounting_status = "OK" if terminal_actual == terminal_expected else "FUNNEL_ACCOUNTING_ERROR"
    if accounting_status != "OK":
        raise AssertionError(f"FUNNEL_ACCOUNTING_ERROR: expected {terminal_expected}, got {terminal_actual}")
    primary = Counter(r["primary_block_reason"] for r in all_records if r["status"] != "SHADOW_TRIGGERED")
    categories = Counter(r["block_category"] for r in all_records if r["status"] != "SHADOW_TRIGGERED")
    by_league = defaultdict(lambda: {"events": 0, "markets": 0, "priceable": 0, "shadow_triggered": 0})
    for r in all_records:
        x = by_league[r["league"] or "未分类"]
        x["events"] += 1; x["markets"] += int(r["market_found"]); x["priceable"] += int(r["priceable"]); x["shadow_triggered"] += int(r["status"] == "SHADOW_TRIGGERED")
    by_region = defaultdict(lambda: {"markets": 0, "priceable": 0, "shadow_triggered": 0})
    for r in all_records:
        x = by_region[r["region"] or "未分类"]
        x["markets"] += int(r["market_found"]); x["priceable"] += int(r["priceable"]); x["shadow_triggered"] += int(r["status"] == "SHADOW_TRIGGERED")
    primary_by_market = {m: Counter(r["primary_block_reason"] for r in all_records if r["market_type"] == m and r["status"] != "SHADOW_TRIGGERED") for m in MARKETS}
    conversions = {m: _conversion([r for r in all_records if r["market_type"] == m]) for m in MARKETS}
    league_current_records = [
        _record_from_row(row, market, diagnose_market, _is_comparable_record)
        for row in rows for market in MARKETS
    ]
    league_decision_funnel = build_league_funnel_diagnostic(
        league_current_records, root, day, asof, diagnose_market, _is_comparable_record
    )
    blocked_total = sum(primary.values()) or 1
    top_by_market = {}
    for m, c in primary_by_market.items():
        market_blocked = sum(c.values()) or 1
        top_by_market[m] = [{"reason": reason, "count": count, "percentage_of_all_blocked": round(count / blocked_total, 4), "percentage_of_market_blocked": round(count / market_blocked, 4), "text": REASON_TEXT.get(reason, reason), "category": _category(reason)} for reason, count in c.most_common(20)]
    bottleneck_options = []
    for market, records in ((m, [r for r in all_records if r["market_type"] == m]) for m in MARKETS):
        stages = [
            ("MARKET_FOUND", sum(r["market_found"] for r in records)),
            ("FRESH_MARKET", sum(r["fresh_market_found"] for r in records)),
            ("CANONICALIZED", sum(r["fresh_market_found"] and r["stage_status"].get("CANONICALIZED", False) for r in records)),
            ("HISTORY_READY", sum(r["fresh_market_found"] and r["history_ready"] for r in records)),
            ("BASE_STATS_READY", sum(r["fresh_market_found"] and r["base_stats_ready"] for r in records)),
            ("SPREAD_FEATURES_READY" if market == "SPREAD" else "TOTAL_FEATURES_READY", sum(r["fresh_market_found"] and r["features_ready"] for r in records)),
            ("SPREAD_PRICEABLE" if market == "SPREAD" else "TOTAL_PRICEABLE", sum(r["fresh_market_found"] and r["priceable"] for r in records)),
            ("EVIDENCE_GATE", sum(r["fresh_market_found"] and r["priceable"] and r["evidence_gate_pass"] for r in records)),
            ("EDGE_GATE", sum(r["fresh_market_found"] and r["edge_found"] for r in records)),
            ("EXECUTION_GATE", sum(r["fresh_market_found"] and r["status"] == "SHADOW_TRIGGERED" for r in records)),
        ]
        for (from_stage, before), (to_stage, after) in zip(stages, stages[1:]):
            bottleneck_options.append({"market": market, "from_stage": from_stage, "to_stage": to_stage, "from_count": before, "to_count": after, "lost": before - after})
    bottleneck_detail = max(bottleneck_options, key=lambda x: x["lost"], default={"from_stage": None, "to_stage": None, "lost": 0})
    config_root = Path(__file__).resolve().parents[2] / "config"
    fallback_files = [config_root / "league_tier_registry.yaml", config_root / "game_rule_registry.json", config_root / "market_integrity.json"]
    engineering_event_ids = {r["event_id"] for r in all_records if r["block_category"] == "FIXABLE_DATA_ENGINEERING"}
    non_engineering_event_ids = {r["event_id"] for r in all_records if r["block_category"] in {"GENUINE_DATA_ABSENCE", "MODEL_LIMITATION", "INTENTIONAL_RISK_BLOCK"}}
    total_hard = Counter(
        x for r in rows
        for x in ((r.get("pricing") or {}).get("total_diagnostic") or {}).get("hard_blockers", [])
        if not (x == "GAME_RULE_UNKNOWN" and _rule_ready(r.get("event") or {}))
    )
    total_soft = Counter(x for r in rows for x in ((r.get("pricing") or {}).get("total_diagnostic") or {}).get("soft_missing", []))
    soft_blockers = {s: sum(s in (r.get("execution") or {}).get("blockers", []) for r in rows) for s in total_soft}
    summary = {
        "schema_version": "pricing-funnel-diagnostic-1.2", "generated_at": stamp(), "asof": asof, "date_bj": day,
        "diagnostic_only": True, "real_execution_allowed": False,
        "events": len(rows), "market_records": len(all_records), "markets": by_market,
        "scope_invariant": {"requested_date_bj":day,"row_dates":sorted(set(row_dates)),
                            "dashboard_event_count":len(rows),"diagnostic_event_count":len(event_rows),
                            "canonical_event_count":len(set(canonical_ids)),"date_scope_match":True,
                            "event_count_match":len(rows)==len(event_rows),"canonical_unique":True},
        "edge_funnel": edge_funnel,
        "league_decision_funnel": league_decision_funnel,
        "comparable_edge_rows": comparable_edge_rows,
        "comparable_edge_table_schema": [
            "game_id", "league", "market_type", "home_team", "away_team", "start_time",
            "pricing_mode", "market_line", "raw_fair_line", "raw_edge_points", "raw_probability",
            "calibrated_fair_line", "calibrated_edge_points", "adjusted_probability", "adjusted_EV",
            "residual_scale", "league_residual_multiplier", "meta_confidence", "model_weight", "market_weight",
            "data_quality", "evidence_status", "execution_score", "edge_retention_ratio",
            "primary_final_reason", "secondary_warnings",
        ],
        "stage_counts": stage_counts, "terminal_accounting_status": accounting_status,
        "terminal_accounting_expected": terminal_expected, "terminal_accounting_actual": terminal_actual,
        "bottleneck": [bottleneck_detail.get("to_stage"), bottleneck_detail.get("lost", 0)],
        "bottleneck_detail": bottleneck_detail,
        "conversion_rates": conversions,
        "top_blockers": [{"reason": reason, "count": count, "percentage_of_all_blocked": round(count / blocked_total, 4), "text": REASON_TEXT.get(reason, reason), "category": _category(reason)} for reason, count in primary.most_common(20)],
        "top_blockers_by_market": top_by_market,
        "block_categories": dict(categories), "by_league": dict(by_league), "by_region": dict(by_region),
        "engineering_failures": sum(r["block_category"] == "FIXABLE_DATA_ENGINEERING" for r in all_records),
        "genuine_data_absence": sum(r["block_category"] == "GENUINE_DATA_ABSENCE" for r in all_records),
        "model_limitations": sum(r["block_category"] == "MODEL_LIMITATION" for r in all_records),
        "intentional_risk_blocks": sum(r["block_category"] == "INTENTIONAL_RISK_BLOCK" for r in all_records),
        "engineering_recovery_upper_bound": len(engineering_event_ids),
        "should_remain_unpriceable_now": len(non_engineering_event_ids),
        "fallback_audit": {"registry_files_present": [str(p) for p in fallback_files if p.exists()], "registry_files_missing": [str(p) for p in fallback_files if not p.exists()], "observed_in_this_run": "diagnosed from existing row blockers; no fallback was changed"},
        "source_health": {"attempted": len(source_health or []), "failed": sum(not bool(x.get("ok")) for x in (source_health or []))},
        "hard_soft_missing": {"total_hard_blockers": total_hard, "total_soft_missing": total_soft, "soft_items_also_used_as_execution_blockers": soft_blockers},
        "history_readiness": history_readiness or {},
        "records": event_rows,
        "questions": {
            "1_why_discovered_market_not_priceable": f"分别查看 markets、conversion_rates 和 top_blockers_by_market；本轮最大损耗为 {bottleneck_detail.get('from_stage')} -> {bottleneck_detail.get('to_stage')}，损失 {bottleneck_detail.get('lost', 0)} 条市场记录；让分与大小分分支独立统计。",
            "2_spread_count": by_market["SPREAD"],
            "3_total_count": by_market["TOTAL"],
            "4_largest_loss": bottleneck_detail,
            "5_top_10_primary_reasons": [{"reason": reason, "count": count} for reason, count in primary.most_common(10)],
            "6_engineering": "见 category=FIXABLE_DATA_ENGINEERING；当前仅诊断，不实施修复。",
            "7_genuine_absence": "见 category=GENUINE_DATA_ABSENCE。",
            "8_model_limitations": "见 category=MODEL_LIMITATION。",
            "9_intentional_risk": "见 category=INTENTIONAL_RISK_BLOCK。",
            "10_engineering_recovery_upper_bound": len(engineering_event_ids),
            "11_should_remain_unpriceable": len(non_engineering_event_ids),
            "12_fallback_early_return_bug": "本次完成注册表存在性和当前阻塞审计；没有可由现有行证据直接证明的提前 return，需在修复阶段逐个 source adapter 验证调用链。",
            "13_hard_soft_classification": "见 hard_soft_missing；soft_items_also_used_as_execution_blockers 非空时列为复核项，不自动认定规则错误。",
            "14_registry_configured_but_unused": "注册表文件已在 skill config 中发现；行记录显示规则先验被消费，但不能仅凭结果证明每个 source 都调用了 registry。",
            "15_projected_after_engineering": f"当前独立可定价市场数为 {by_market['SPREAD']['priceable'] + by_market['TOTAL']['priceable']}；工程修复上限是当前数加 {len(engineering_event_ids)} 个受影响赛事，非保证值。",
            "model_change": "否；本诊断不修改公式、阈值、sigma、证据门槛或执行规则。",
        },
        "repair_priorities": {
            "P0": "修复数量最高且会切断漏斗的工程/来源链阻塞；先看 top_blockers 中 category=FIXABLE_DATA_ENGINEERING。",
            "P1": "补齐市场存在但缺失的历史、回合/效率、伤停/轮换和联赛规则证据；仍不降低既有门槛。",
            "P2": "在原生前向样本足够后评估模型限制、按联赛隔离校准和执行风险；当前不自动调参。",
        },
    }
    out = root / "diagnostics"; out.mkdir(parents=True, exist_ok=True)
    csv_fields = ["game_id", "event_id", "canonical_event_id", "league", "region", "home_team", "away_team", "start_time", "archive_type", "pricing_status", "model_family", "league_tier", "spread_market_found", "spread_fresh_market", "spread_terminal_status", "total_market_found", "total_fresh_market", "total_terminal_status", "canonicalized", "league_rule_ready", "team_mapping_ready", "history_ready", "base_stats_ready", "spread_features_ready", "total_features_ready", "spread_priceable", "total_priceable", "spread_primary_block_stage", "spread_primary_block_reason", "total_primary_block_stage", "total_primary_block_reason", "secondary_warnings", "data_quality", "evidence_quality", "raw_fair_spread", "market_spread", "raw_fair_total", "market_total", "spread_edge", "total_edge", "spread_final_status", "total_final_status", "final_status"]
    csv_path = out / f"pricing_funnel_{day.replace('-', '')}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields); writer.writeheader()
        for row, event_record in zip(rows, event_rows):
            s, t = event_record["spread"], event_record["total"]
            values = {"game_id": event_record["canonical_event_id"], "event_id": event_record["event_id"], "canonical_event_id": event_record["canonical_event_id"], "league": event_record["league"], "region": event_record["region"], "home_team": event_record["team1"], "away_team": event_record["team2"], "start_time": event_record["tip_time_bj"], "archive_type": event_record["archive_type"], "pricing_status": event_record["pricing_status"], "model_family": event_record["model_family"], "league_tier": event_record["league_tier"], "spread_market_found": s["market_found"], "spread_fresh_market": s["fresh_market_found"], "spread_terminal_status": s["terminal_status"], "total_market_found": t["market_found"], "total_fresh_market": t["fresh_market_found"], "total_terminal_status": t["terminal_status"], "canonicalized": event_record["canonicalized"], "league_rule_ready": event_record["league_rule_ready"], "team_mapping_ready": event_record["team_mapping_ready"], "history_ready": event_record["history_ready"], "base_stats_ready": event_record["base_stats_ready"], "spread_features_ready": event_record["spread_features_ready"], "total_features_ready": event_record["total_features_ready"], "spread_priceable": event_record["spread_priceable"], "total_priceable": event_record["total_priceable"], "spread_primary_block_stage": s["primary_block_stage"], "spread_primary_block_reason": s["primary_block_reason"], "total_primary_block_stage": t["primary_block_stage"], "total_primary_block_reason": t["primary_block_reason"], "secondary_warnings": json.dumps(event_record["secondary_warnings"], ensure_ascii=False), "data_quality": event_record["pricing_data_quality"], "evidence_quality": event_record["pricing_data_quality"], "raw_fair_spread": event_record["fair_spread"], "market_spread": event_record["market_spread"], "raw_fair_total": event_record["fair_total"], "market_total": event_record["market_total"], "spread_edge": event_record["spread_edge"], "total_edge": event_record["total_edge"], "spread_final_status": event_record["spread_final_status"], "total_final_status": event_record["total_final_status"], "final_status": event_record["final_status"]}
            writer.writerow(values)
    edge_csv = out / f"comparable_edge_{day.replace('-', '')}.csv"
    edge_rows = _comparable_edge_rows(all_records)
    edge_fields = summary["comparable_edge_table_schema"]
    with edge_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=edge_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(edge_rows)
    atomic(out / f"pricing_funnel_summary_{day.replace('-', '')}.json", summary)
    md = render_markdown(summary)
    (out / f"pricing_funnel_summary_{day.replace('-', '')}.md").write_text(md, encoding="utf-8")
    return summary


def render_markdown(summary):
    def lines(counter):
        return "\n".join(f"- `{x['reason']}`：{x['count']}，{x['text']}（{x['category']}）" for x in summary.get("top_blockers", [])) or "- 无"
    q = summary.get("questions", {})
    p = summary.get("repair_priorities", {})
    league = summary.get("league_decision_funnel", {})
    league_sections = []
    for window, payload in league.get("windows", {}).items():
        league_sections.extend([
            f"### League Funnel — {window}", "",
            "|联赛|样本|可比样本|盘口|新鲜|可定价|原始优势|校准优势|证据通过|执行通过|Shadow|主状态|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ])
        for name, item in payload.get("by_league", {}).items():
            c = item.get("counts", {})
            league_sections.append(f"|{name}|{item.get('sample_size', 0)}|{item.get('comparable_sample', 0)}|{c.get('market_found', 0)}|{c.get('fresh_market', 0)}|{c.get('research_priceable', 0)}|{c.get('raw_edge_found', 0)}|{c.get('calibrated_edge_found', 0)}|{c.get('evidence_pass', 0)}|{c.get('execution_pass', 0)}|{c.get('shadow_triggered', 0)}|{item.get('main_state')}|")
        league_sections.append("")
    comparison = league.get("wnba_vs_non_wnba", {})
    attribution = league.get("suppression_attribution", {}).get("overall", {})
    near_miss = league.get("non_wnba_near_miss_top10", [])
    return "\n".join([
        f"# Pricing Funnel Diagnostic — {summary.get('date_bj')}", "",
        "> 本报告只读诊断，不修改 pricing、阈值、Evidence Gate、fallback、纸面决定或真实执行状态。", "",
        f"- 赛事数：{summary.get('events')}；市场记录：{summary.get('market_records')}；生成时间：{summary.get('generated_at')}",
        f"- 总盘口记录：{sum(v.get('market_events', 0) for v in summary.get('markets', {}).values())}；让分盘口：{summary.get('markets', {}).get('SPREAD', {}).get('market_events')}; 大小分盘口：{summary.get('markets', {}).get('TOTAL', {}).get('market_events')}",
        f"- 瓶颈阶段：`{summary.get('bottleneck', [None, None])[0]}`（{summary.get('bottleneck', [None, None])[1]} 条市场记录通过）", "",
        "## 让分 / 大小分漏斗", "",
        "|市场|赛事总数|找到盘口|无盘口|新鲜盘口|过期盘口|可定价|新鲜但未定价|有优势|纸面触发|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *[f"|{m}|{v['events_total']}|{v['market_found']}|{v['no_market']}|{v['fresh_market']}|{v['stale_market']}|{v['priceable']}|{v['fresh_market_but_not_priceable']}|{v['edge_found']}|{v['shadow_triggered']}|" for m, v in summary.get("markets", {}).items()], "",
        "## Edge Funnel", "",
        "|市场|Research Priceable|Market Comparable|Raw Edge|Calibrated Edge|Evidence Pass|Execution Pass|Shadow|", "|---|---:|---:|---:|---:|---:|---:|---:|",
        *[f"|{m}|{v.get('research_priceable', 0)}|{v.get('market_comparable', 0)}|{v.get('raw_edge_found', 0)}|{v.get('calibrated_edge_found', 0)}|{v.get('evidence_pass', 0)}|{v.get('execution_pass', 0)}|{v.get('shadow_triggered', 0)}|" for m, v in summary.get("edge_funnel", {}).get("markets", {}).items()], "",
        f"- 可比样本总数：`{summary.get('edge_funnel', {}).get('comparable_total', 0)}`；最终原因：`{json.dumps(summary.get('edge_funnel', {}).get('primary_final_reasons', {}), ensure_ascii=False)}`",
        f"- Research Priceable → Market Comparable：`{json.dumps(summary.get('edge_funnel', {}).get('priceable_not_comparable_reasons', {}), ensure_ascii=False)}`",
        f"- Edge retention：均值 `{summary.get('edge_funnel', {}).get('retention', {}).get('mean_edge_retention')}`；中位数 `{summary.get('edge_funnel', {}).get('retention', {}).get('median_edge_retention')}`；可能过度收缩：`{summary.get('edge_funnel', {}).get('retention', {}).get('possible_over_shrinkage')}`", "",
        "逐场表：`diagnostics/comparable_edge_YYYYMMDD.csv`。校准字段没有被生产模型明确输出时，诊断保留为 null，不从市场融合值反推。", "",
        "## League Decision Funnel", "",
        *league_sections,
        "## WNBA vs NON_WNBA", "",
        "|组别|样本|可比|盘口|新鲜|可定价|原始优势|校准优势|证据通过|执行通过|Shadow|主状态|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        *[f"|{name}|{item.get('sample_size', 0)}|{item.get('comparable_sample', 0)}|{item.get('counts', {}).get('market_found', 0)}|{item.get('counts', {}).get('fresh_market', 0)}|{item.get('counts', {}).get('research_priceable', 0)}|{item.get('counts', {}).get('raw_edge_found', 0)}|{item.get('counts', {}).get('calibrated_edge_found', 0)}|{item.get('counts', {}).get('evidence_pass', 0)}|{item.get('counts', {}).get('execution_pass', 0)}|{item.get('counts', {}).get('shadow_triggered', 0)}|{item.get('main_state')}|" for name, item in comparison.items()], "",
        "## Suppression Attribution", "",
        f"- `{json.dumps(attribution, ensure_ascii=False)}`", "",
        "## Non-WNBA Near Miss Top 10", "",
        "|赛事|联赛|市场|原始优势|校准优势|EV|归因|", "|---|---|---|---:|---:|---:|---|",
        *([f"|{x.get('event_id')}|{x.get('league_bucket')}|{x.get('market_type')}|{x.get('raw_edge_points')}|{x.get('calibrated_edge_points')}|{x.get('adjusted_EV')}|{x.get('suppression_reason')}|" for x in near_miss] if near_miss else ["|无|—|—|—|—|—|—|" ]), "",
        "## Native / Cold-start / Prior-only 与残差尺度", "",
        f"- 模式统计：`{json.dumps(league.get('native_cold_start_prior', {}), ensure_ascii=False)}`",
        f"- 残差分解：`{json.dumps(league.get('residual_scale_breakdown', {}), ensure_ascii=False)}`",
        f"- 市场拉力：`{json.dumps(league.get('market_pull', {}), ensure_ascii=False)}`", "",
        "## 22 项诊断口径", "",
        *[f"- **{k}**：{v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}" for k, v in league.get("questions", {}).items()], "",
        "## P0 / P1 / P2 修复建议", "",
        *[f"- **{k}**：{v}" for k, v in league.get("repair_suggestions", {}).items()], "",
        "## 转化率", "",
        *[f"- **{m}**：" + "；".join(f"{k}={v}" for k, v in x.items() if k != "counts") for m, x in summary.get('conversion_rates', {}).items()], "",
        "## Top Blocking Reasons", "", lines(summary.get("top_blockers", [])), "",
        "## 分市场 Top Blocking Reasons", "",
        *[f"### {m}\n" + ("\n".join(f"- `{x['reason']}`：{x['count']}（占全部阻塞 {x['percentage_of_all_blocked']:.1%}）" for x in vals) or "- 无") for m, vals in summary.get('top_blockers_by_market', {}).items()], "",
        "## 分类", "",
        f"- 工程失败：{summary.get('engineering_failures')}；真实数据缺失：{summary.get('genuine_data_absence')}；模型限制：{summary.get('model_limitations')}；主动风控：{summary.get('intentional_risk_blocks')}", "",
        "## 15 问题诊断口径", "",
        *[f"- **{k}**：{v}" for k, v in q.items()], "",
        "## 工程优先级（仅建议，不在本阶段实施）", "",
        *[f"- **{k}**：{v}" for k, v in p.items()], "",
        "## 注册表与 fallback 审计", "",
        f"- 已发现配置：{len(summary.get('fallback_audit', {}).get('registry_files_present', []))}；缺失配置：{len(summary.get('fallback_audit', {}).get('registry_files_missing', []))}",
        "- 本轮没有为提高可定价数量而新增 fallback、补默认数据或放宽门槛。", "",
        "## 结论", "",
        "该报告用于定位“市场存在但没有独立定价”的首个阻塞阶段；工程修复上限不等于保证可定价，真实执行仍关闭。", "",
    ])
