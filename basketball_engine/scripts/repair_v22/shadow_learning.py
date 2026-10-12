"""Four-layer shadow learning with physically isolated provisional ledgers."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path

from .common import atomic, exclusive, fingerprint, iso, load, stamp


HARD_BLOCK = {
    "TEAM_MAPPING_UNRESOLVED", "IDENTITY_CONFLICT", "LEAGUE_RULE_UNKNOWN", "GAME_RULE_UNKNOWN",
    "MARKET_RULE_AMBIGUOUS", "MARKET_DIRECTION_AMBIGUOUS", "SELECTION_DIRECTION_UNVERIFIED",
    "NO_REAL_MARKET", "NO_MARKET", "NO_INDEPENDENT_FAIR_PRICE", "SOURCE_CONFLICT_SEVERE",
    "FUTURE_DATA_LEAKAGE_RISK", "MODEL_CORE_INPUT_MISSING", "PACE_EVIDENCE_MISSING",
    "POSSESSIONS_EVIDENCE_MISSING", "BASIC_OFFENSE_EVIDENCE_MISSING", "PIPELINE_EXCEPTION",
}
DATA_PIPELINE_FAILURE = {"TEAM_HISTORY_FEED_NOT_CAPTURED", "LIVE_SOURCE_FAILED", "HISTORY_SOURCE_FAILED"}
SOFT_ALIASES = {
    "INSUFFICIENT_HISTORY": "HISTORY_ESS_TOO_LOW",
    "INSUFFICIENT_OPPONENT_DIVERSITY": "OPPONENT_DIVERSITY_TOO_LOW",
    "CURRENT_ROSTER_UNVERIFIED": "LINEUP_UNKNOWN",
    "ROSTER_STABILITY_MISSING": "ROSTER_STABILITY_UNKNOWN",
    "ROTATION_UNKNOWN": "LINEUP_UNKNOWN",
    "THREE_POINT_PROFILE_UNKNOWN": "PARTIAL_3P_DATA",
    "LATE_FOUL_ENVIRONMENT_UNKNOWN": "LATE_GAME_FOUL_EVIDENCE_MISSING",
    "OT_PREMIUM_UNAVAILABLE": "OT_EVIDENCE_UNCERTAIN",
    "SPREAD_CONTEXT_INCOMPLETE": "LINEUP_UNKNOWN",
    "COLD_START_SHADOW_GATE_NOT_MET": "COLD_START",
}
SOFT_MISSING = {
    "HISTORY_ESS_TOO_LOW", "OPPONENT_DIVERSITY_TOO_LOW", "LIMITED_CURRENT_SEASON_HISTORY",
    "LOW_OPPONENT_DIVERSITY", "ROSTER_STABILITY_UNKNOWN", "LINEUP_UNKNOWN", "INJURY_UNKNOWN",
    "COLD_START", "PARTIAL_3P_DATA", "LATE_GAME_FOUL_EVIDENCE_MISSING", "OT_EVIDENCE_UNCERTAIN",
    "CLOSE_GAME_Q4_SAMPLE_INSUFFICIENT", "GARBAGE_TIME_Q4_SAMPLE_INSUFFICIENT",
}


def _canonical_reason(reason):
    reason = str(reason or "UNKNOWN_EVIDENCE_REASON").split(":", 1)[0]
    if reason == "TOTAL_CONTEXT_INCOMPLETE":
        return "PACE_EVIDENCE_MISSING"
    return SOFT_ALIASES.get(reason, reason)


def _reason_class(reason):
    if reason in DATA_PIPELINE_FAILURE:
        return "DATA_PIPELINE_FAILURE"
    if reason in HARD_BLOCK or reason.startswith("SOURCE_CONFLICT"):
        return "HARD_BLOCK"
    return "SOFT_MISSING" if reason in SOFT_MISSING else "HARD_BLOCK"


def classify_market(event, pricing, market_type, market_decision, duplicate_qualified=False):
    selected = (market_decision or {}).get("selected") or {}
    state = (market_decision or {}).get("model_state") or "UNASSESSED"
    raw = list((market_decision or {}).get("blockers") or [])
    raw += list((market_decision or {}).get("uncertainty_flags") or [])
    if market_type == "TOTAL":
        raw += list((pricing.get("total_diagnostic") or {}).get("hard_blockers") or [])
        raw += list((pricing.get("total_diagnostic") or {}).get("soft_missing") or [])
    reasons = list(dict.fromkeys(_canonical_reason(x) for x in raw if x and x != "MODEL_EVIDENCE_NOT_PAPER_ELIGIBLE"))
    classified = [{"reason": reason, "class": _reason_class(reason)} for reason in reasons]
    has_hard = any(x["class"] == "HARD_BLOCK" for x in classified)
    has_pipeline_failure = any(x["class"] == "DATA_PIPELINE_FAILURE" for x in classified)
    comparable = bool((market_decision or {}).get("comparison_ready") and selected)
    edge = state == "EDGE" and bool(selected.get("research_edge_pass"))
    if not comparable:
        level = "DIAGNOSTIC_ONLY"
    elif edge and (market_decision or {}).get("triggered"):
        level = "QUALIFIED_SHADOW"
    elif edge and not has_hard and not has_pipeline_failure:
        level = "PROVISIONAL_SHADOW"
    else:
        level = "RESEARCH_SIGNAL"
    if market_type == "TOTAL" and (pricing.get("total_diagnostic") or {}).get("evidence_level") == "LEVEL_D":
        level = "RESEARCH_SIGNAL" if comparable else "DIAGNOSTIC_ONLY"
    soft_count = sum(x["class"] == "SOFT_MISSING" for x in classified)
    multiplier = min(1.50, 1.0 + 0.08 * soft_count) if level == "PROVISIONAL_SHADOW" else 1.0
    p_win, p_loss = selected.get("p_win"), selected.get("p_loss")
    conditional = (p_win / (p_win + p_loss)) if isinstance(p_win, (int, float)) and isinstance(p_loss, (int, float)) and p_win + p_loss > 0 else None
    penalized = 0.5 + (conditional - 0.5) / multiplier if conditional is not None else None
    return {
        "market_type": market_type, "shadow_level": level, "model_state": state,
        "comparable": comparable, "edge": edge, "selected": selected or None,
        "evidence_reasons": classified, "hard_blocked": has_hard,
        "data_pipeline_failure": has_pipeline_failure,
        "uncertainty_penalty": multiplier - 1.0,
        "provisional_residual_scale_multiplier": multiplier,
        "confidence_penalty": 1.0 - 1.0 / multiplier,
        "raw_probability": conditional, "final_probability": penalized,
        "edge_thresholds_unchanged": True, "real_execution_allowed": False,
        "strategy_return_eligible": level == "QUALIFIED_SHADOW",
        "existing_qualified_first_write": bool(duplicate_qualified and level == "QUALIFIED_SHADOW"),
    }


def annotate_decision(event, pricing, decision):
    duplicate = "EXISTING_PAPER_ENTRY_NO_DUPLICATE" in (decision.get("blockers") or [])
    markets = {name: classify_market(event, pricing, name, item, duplicate)
               for name, item in (decision.get("market_decisions") or {}).items()}
    rank = {"QUALIFIED_SHADOW": 4, "PROVISIONAL_SHADOW": 3, "RESEARCH_SIGNAL": 2, "DIAGNOSTIC_ONLY": 1}
    strongest = max(markets.values(), key=lambda x: rank[x["shadow_level"]], default=None)
    decision["learning_classification"] = {
        "schema_version": "shadow-learning-1.0", "markets": markets,
        "event_shadow_level": strongest["shadow_level"] if strongest else "DIAGNOSTIC_ONLY",
        "qualified_definition": "UNCHANGED_CHAMPION_EVIDENCE_GATE",
        "real_execution_allowed": False,
    }
    return decision["learning_classification"]


def freeze_learning_records(root, run_id, event, pricing, decision):
    """Write only Provisional/Research records; Qualified remains in its existing ledger."""
    if decision.get("archive_type") != "FORWARD_NATIVE":
        return []
    records = []
    for market_type, classification in (decision.get("learning_classification") or {}).get("markets", {}).items():
        level = classification.get("shadow_level")
        if level not in ("PROVISIONAL_SHADOW", "RESEARCH_SIGNAL") or not classification.get("comparable"):
            continue
        selected = classification.get("selected") or {}
        record_id = fingerprint({"prediction_id": decision.get("prediction_id"), "market_type": market_type,
                                 "level": level, "first_write_at": decision.get("asof")})[:32]
        fair = pricing.get("mu_raw") if market_type == "SPREAD" else pricing.get("total_raw")
        record = {
            "schema_version": "shadow-learning-record-1.0", "record_id": record_id,
            "prediction_id": decision.get("prediction_id"), "event_id": event.get("event_id"),
            "event": event, "first_write_at": decision.get("asof"), "archive_type": "FORWARD_NATIVE",
            "shadow_level": level, "market_type": market_type, "model_state": classification.get("model_state"),
            "market_line": selected.get("line"), "fair_line": fair, "selected_side": selected.get("selection"),
            "decimal_odds": selected.get("decimal_odds"), "bookmaker": selected.get("bookmaker"),
            "ot_rule": selected.get("ot_rule"), "quote_id": selected.get("quote_id"),
            "raw_probability": classification.get("raw_probability"),
            "final_probability": classification.get("final_probability"), "ev": selected.get("ev"),
            "adverse_ev": selected.get("adverse_ev"), "evidence_status": classification.get("evidence_reasons"),
            "blocked_reason": [x["reason"] for x in classification.get("evidence_reasons", [])],
            "uncertainty_penalty": classification.get("uncertainty_penalty"),
            "provisional_residual_scale_multiplier": classification.get("provisional_residual_scale_multiplier"),
            "confidence_penalty": classification.get("confidence_penalty"),
            "history_ess": pricing.get("history_ess"),
            "effective_opponent_diversity": pricing.get("effective_opponent_diversity"),
            "pace_source": (pricing.get("total_diagnostic") or {}).get("pace_source"),
            "possessions_level": (pricing.get("total_diagnostic") or {}).get("evidence_level"),
            "forecast_fingerprint": decision.get("forecast_fingerprint"),
            "immutable_first_write": True, "edge_thresholds_unchanged": True,
            "strategy_return_eligible": False, "real_execution_allowed": False,
        }
        folder = "repair_v22_provisional" if level == "PROVISIONAL_SHADOW" else "repair_v22_research"
        path = Path(root) / "ledger" / folder / run_id / (record_id + ".json")
        exclusive(path, record); records.append(record)
    return records


def freeze_titan_provisional_records(root, run_id, event, pricing, decision):
    """Freeze Titan challenger picks in a physically separate learning ledger."""
    if decision.get("archive_type") != "FORWARD_NATIVE":
        return []
    records = []
    for market_type, item in (decision.get("titan_market_decisions") or {}).items():
        if item.get("status") != "TITAN_PROVISIONAL_SHADOW" or not item.get("comparison_ready"):
            continue
        selected = item.get("selected") or {}
        record_id = fingerprint({"prediction_id": decision.get("prediction_id"), "market_type": market_type,
                                 "level": "TITAN_PROVISIONAL_SHADOW",
                                 "first_write_at": decision.get("asof")})[:32]
        record = {
            "schema_version": "titan-provisional-record-1.0", "record_id": record_id,
            "prediction_id": decision.get("prediction_id"), "event_id": event.get("event_id"),
            "event": event, "first_write_at": decision.get("asof"), "archive_type": "FORWARD_NATIVE",
            "shadow_level": "TITAN_PROVISIONAL_SHADOW", "market_type": market_type,
            "model_state": "EDGE", "market_line": selected.get("line"),
            "fair_line": item.get("fair_line"), "selected_side": selected.get("selection"),
            "decimal_odds": selected.get("decimal_odds"), "bookmaker": selected.get("bookmaker"),
            "ot_rule": selected.get("ot_rule"), "quote_id": selected.get("quote_id"),
            "raw_probability": (selected.get("p_win") / (selected.get("p_win") + selected.get("p_loss"))
                                if isinstance(selected.get("p_win"), (int, float)) and
                                isinstance(selected.get("p_loss"), (int, float)) and
                                selected.get("p_win") + selected.get("p_loss") > 0 else None),
            "final_probability": (selected.get("p_win") / (selected.get("p_win") + selected.get("p_loss"))
                                  if isinstance(selected.get("p_win"), (int, float)) and
                                  isinstance(selected.get("p_loss"), (int, float)) and
                                  selected.get("p_win") + selected.get("p_loss") > 0 else None),
            "ev": selected.get("ev"), "adverse_ev": selected.get("adverse_ev"),
            "blocked_reason": item.get("soft_missing") or [],
            "evidence_status": {"hard_blockers": item.get("hard_blockers") or [],
                                "soft_missing": item.get("soft_missing") or []},
            "provisional_residual_scale_multiplier": selected.get("provisional_uncertainty_multiplier"),
            "pregame_evidence_bundle": decision.get("pregame_evidence_bundle"),
            "forecast_fingerprint": decision.get("forecast_fingerprint"),
            "immutable_first_write": True, "edge_thresholds_unchanged": True,
            "model_not_champion_validated": True, "strategy_return_eligible": False,
            "real_execution_allowed": False,
        }
        path = Path(root) / "ledger" / "titan_provisional" / run_id / (record_id + ".json")
        exclusive(path, record); records.append(record)
    return records


def _evidence_index(root, current_history):
    facts = {g.get("event_id"): g for g in current_history if g.get("status") == "FINAL" and g.get("event_id")}
    tapes = defaultdict(list)
    for path in (Path(root) / "raw" / "repair_v22").glob("*/capture.json"):
        capture = load(path, {})
        for game in capture.get("history", []):
            if game.get("status") == "FINAL" and game.get("event_id"):
                facts.setdefault(game["event_id"], game)
        for quote in capture.get("quotes", []):
            key = (quote.get("event_id"), quote.get("bookmaker"), quote.get("market_type"), quote.get("ot_rule"))
            if None not in key and quote.get("main_or_alt") == "MAIN":
                tapes[key].append(quote)
    for rows in tapes.values():
        rows.sort(key=lambda x: str(x.get("received_at") or ""))
    return facts, tapes


def _settle(record, fact, asof, tape=None):
    event = record.get("event") or {}; selection = record.get("selected_side")
    ids, fact_ids = (event.get("team1_id"), event.get("team2_id")), (fact.get("team1_id"), fact.get("team2_id"))
    if None in ids or set(ids) != set(fact_ids):
        return None
    suffix = "regulation" if record.get("ot_rule") == "REGULATION_ONLY" else "full"
    try:
        a, b = fact["score1_" + suffix], fact["score2_" + suffix]
    except KeyError:
        return None
    if ids == fact_ids[::-1]:
        a, b = b, a
    line = record.get("market_line")
    if record.get("market_type") == "SPREAD":
        delta = (a - b if selection == "TEAM1" else b - a) + float(line)
        actual, predicted = a - b, record.get("fair_line")
    else:
        delta = (a + b - float(line)) * (1 if selection == "OVER" else -1)
        actual, predicted = a + b, record.get("fair_line")
    outcome = "WIN" if delta > 0 else "LOSS" if delta < 0 else "PUSH"
    pnl = float(record.get("decimal_odds") or 0) - 1 if outcome == "WIN" else -1 if outcome == "LOSS" else 0
    probability = record.get("final_probability")
    closing_line = None
    for quote in tape or []:
        try:
            if iso(quote.get("received_at")) >= iso(event.get("tip_at")):
                continue
        except Exception:
            continue
        candidate = quote.get("raw_line") if record.get("market_type") == "TOTAL" else quote.get("line_team1")
        if not isinstance(candidate, (int, float)):
            continue
        closing_line = (-float(candidate) if record.get("market_type") == "SPREAD" and selection == "TEAM2" else float(candidate))
    clv = None
    if closing_line is not None and isinstance(line, (int, float)):
        if record.get("market_type") == "SPREAD": clv = closing_line - float(line)
        elif selection == "OVER": clv = float(line) - closing_line
        else: clv = closing_line - float(line)
    return {
        "record_id": record.get("record_id"), "prediction_id": record.get("prediction_id"),
        "event_id": record.get("event_id"), "shadow_level": record.get("shadow_level"),
        "settled_at": asof, "outcome": outcome, "score1": a, "score2": b,
        "actual_value": actual, "prediction_error": actual - predicted if isinstance(predicted, (int, float)) else None,
        "closing_line": closing_line, "clv": clv,
        "brier": (probability - (1 if outcome == "WIN" else 0)) ** 2 if outcome != "PUSH" and isinstance(probability, (int, float)) else None,
        "provisional_pnl": pnl if record.get("shadow_level") in
                           ("PROVISIONAL_SHADOW", "TITAN_PROVISIONAL_SHADOW") else None,
        "counterfactual_pnl": pnl if record.get("shadow_level") == "RESEARCH_SIGNAL" else None,
        "paper_pnl": None, "strategy_return_eligible": False, "real_execution_allowed": False,
        "result_raw_sha256": fact.get("raw_sha256"),
    }


def settle_learning_records(root, current_history, asof):
    facts, tapes = _evidence_index(root, current_history); counts = Counter()
    for folder, settlement_folder in (("repair_v22_provisional", "repair_v22_provisional_settlements"),
                                      ("repair_v22_research", "repair_v22_research_settlements"),
                                      ("titan_provisional", "titan_provisional_settlements")):
        for path in (Path(root) / "ledger" / folder).glob("*/*.json"):
            record = load(path, {}); target = Path(root) / "ledger" / settlement_folder / (record.get("record_id", "") + ".json")
            if not record.get("record_id") or target.exists():
                continue
            fact = facts.get(record.get("event_id"))
            if not fact or (fact.get("known_final_at") and iso(fact["known_final_at"]) > iso(asof)):
                continue
            tape_key = (record.get("event_id"), record.get("bookmaker"), record.get("market_type"), record.get("ot_rule"))
            settled = _settle(record, fact, asof, tapes.get(tape_key))
            if settled:
                exclusive(target, settled); counts[record.get("shadow_level")] += 1
    return dict(counts)


def _load_layer(root, folder, settlement_folder):
    settlements = {p.stem: load(p, {}) for p in (Path(root) / "ledger" / settlement_folder).glob("*.json")}
    records = []
    for path in sorted((Path(root) / "ledger" / folder).glob("*/*.json")):
        record = load(path, {}); record["settlement"] = settlements.get(record.get("record_id")); records.append(record)
    chosen = {}
    for record in sorted(records, key=lambda x: (x.get("first_write_at", ""), x.get("record_id", ""))):
        chosen.setdefault((record.get("event_id"), record.get("market_type")), record)
    return list(chosen.values())


def _metrics(records, pnl_field):
    settled = [r for r in records if r.get("settlement")]
    outcomes = Counter((r.get("settlement") or {}).get("outcome") for r in settled)
    pnl_values = [float((r["settlement"] or {}).get(pnl_field) or 0) for r in settled]
    errors = [float(r["settlement"]["prediction_error"]) for r in settled if isinstance(r["settlement"].get("prediction_error"), (int, float))]
    briers = [float(r["settlement"]["brier"]) for r in settled if isinstance(r["settlement"].get("brier"), (int, float))]
    clvs = [float(r["settlement"]["clv"]) for r in settled if isinstance(r["settlement"].get("clv"), (int, float))]
    probs = [float(r.get("final_probability")) for r in settled if (r["settlement"].get("outcome") != "PUSH" and isinstance(r.get("final_probability"), (int, float)))]
    binary = [1 if r["settlement"].get("outcome") == "WIN" else 0 for r in settled if r["settlement"].get("outcome") != "PUSH" and isinstance(r.get("final_probability"), (int, float))]
    running = peak = drawdown = 0.0
    for value in pnl_values:
        running += value; peak = max(peak, running); drawdown = max(drawdown, peak - running)
    return {
        "N": len(records), "settled_N": len(settled), "W": outcomes["WIN"], "L": outcomes["LOSS"], "P": outcomes["PUSH"],
        "PnL": sum(pnl_values), "ROI": sum(pnl_values) / len(settled) if settled else None,
        "CLV": sum(clvs) / len(clvs) if clvs else None, "MAE": sum(abs(x) for x in errors) / len(errors) if errors else None,
        "RMSE": math.sqrt(sum(x * x for x in errors) / len(errors)) if errors else None,
        "Brier": sum(briers) / len(briers) if briers else None,
        "Calibration": {"mean_probability": sum(probs) / len(probs) if probs else None,
                        "observed_win_rate": sum(binary) / len(binary) if binary else None, "N": len(probs)},
        "Max_Drawdown": drawdown,
    }


def _qualified_records(main_analytics):
    rows = []
    for item in (main_analytics or {}).get("execution_records", []):
        settlement = dict(item.get("evaluation") or {}) or None
        if settlement is not None:
            close = (item.get("market_tape") or {}).get("close_line")
            entry = item.get("line")
            selection = item.get("selection")
            if isinstance(close, (int, float)) and isinstance(entry, (int, float)):
                if item.get("market_type") == "SPREAD": settlement["clv"] = close - entry
                elif selection == "OVER": settlement["clv"] = entry - close
                else: settlement["clv"] = close - entry
        rows.append({"event_id": item.get("event_id"), "market_type": item.get("market_type"),
                     "final_probability": None, "settlement": settlement})
    return rows


def build_shadow_learning_analytics(root, asof, main_analytics):
    provisional = _load_layer(root, "repair_v22_provisional", "repair_v22_provisional_settlements")
    titan_provisional = _load_layer(root, "titan_provisional", "titan_provisional_settlements")
    research = _load_layer(root, "repair_v22_research", "repair_v22_research_settlements")
    qualified = _qualified_records(main_analytics)
    qualified_keys = {(row.get("event_id"), row.get("market_type")) for row in qualified}
    provisional_overlap = [row for row in provisional if (row.get("event_id"), row.get("market_type")) in qualified_keys]
    titan_provisional_overlap = [row for row in titan_provisional if
                                 (row.get("event_id"), row.get("market_type")) in qualified_keys]
    research_overlap = [row for row in research if (row.get("event_id"), row.get("market_type")) in qualified_keys]
    provisional = [row for row in provisional if (row.get("event_id"), row.get("market_type")) not in qualified_keys]
    titan_provisional = [row for row in titan_provisional if
                         (row.get("event_id"), row.get("market_type")) not in qualified_keys]
    research = [row for row in research if (row.get("event_id"), row.get("market_type")) not in qualified_keys]
    # Strong physical-isolation invariant: provisional files cannot expose a
    # paper_pnl value and the existing official ledger cannot carry this level.
    violations = []
    for row in provisional:
        if (row.get("settlement") or {}).get("paper_pnl") is not None or row.get("strategy_return_eligible"):
            violations.append(row.get("record_id"))
    for row in titan_provisional:
        if (row.get("settlement") or {}).get("paper_pnl") is not None or row.get("strategy_return_eligible"):
            violations.append(row.get("record_id"))
    for path in (Path(root) / "ledger" / "repair_v22_settlements").glob("*.json"):
        item = load(path, {})
        if item.get("shadow_level") in ("PROVISIONAL_SHADOW", "TITAN_PROVISIONAL_SHADOW") or item.get("provisional_pnl") is not None:
            violations.append(path.stem)
    if violations:
        raise AssertionError("PROVISIONAL_LEDGER_POLLUTION:" + ",".join(str(x) for x in violations[:10]))
    reason_groups = defaultdict(list)
    for row in provisional + research:
        if row.get("model_state") != "EDGE":
            continue
        for item in row.get("evidence_status") or []:
            reason_groups[item.get("reason")].append(row)
    gate_rows = {}
    for reason, rows in reason_groups.items():
        metrics = _metrics(rows, "provisional_pnl" if any(r.get("shadow_level") == "PROVISIONAL_SHADOW" for r in rows) else "counterfactual_pnl")
        gate_rows[reason] = {"blocked_N": len(rows), "counterfactual_W": metrics["W"], "counterfactual_L": metrics["L"],
                             "counterfactual_PnL": metrics["PnL"], "counterfactual_CLV": metrics["CLV"],
                             "prediction_MAE": metrics["MAE"]}
    gate_validation = {
        "schema_version": "gate-validation-1.0", "generated_at": stamp(), "asof": asof,
        "by_evidence_reason": gate_rows,
        "challengers": {
            "A_TIER3_ROSTER_HARD_TO_SOFT": {"minimum_N": 50, "status": "EVALUATING"},
            "B_RAW_COUNT_TO_ESS": {"minimum_N": 50, "status": "EVALUATING"},
            "C_RAW_OPPONENTS_TO_WEIGHTED_DIVERSITY": {"minimum_N": 50, "status": "EVALUATING"},
        },
        "champion_unchanged": True, "auto_promotion_allowed": False,
    }
    result = {
        "schema_version": "shadow-learning-1.0", "generated_at": stamp(), "asof": asof,
        "QUALIFIED_SHADOW": _metrics(qualified, "paper_pnl"),
        "PROVISIONAL_SHADOW": _metrics(provisional, "provisional_pnl"),
        "TITAN_PROVISIONAL_SHADOW": _metrics(titan_provisional, "provisional_pnl"),
        "RESEARCH_SIGNAL": _metrics(research, "counterfactual_pnl"),
        "ledger_isolation": {"passed": True, "qualified_ledger": "ledger/repair_v22_settlements",
                             "provisional_ledger": "ledger/repair_v22_provisional_settlements",
                             "titan_provisional_ledger": "ledger/titan_provisional_settlements",
                             "research_ledger": "ledger/repair_v22_research_settlements",
                             "provisional_in_main_strategy_returns": False,
                             "cross_layer_overlap_excluded_from_provisional_statistics": len(provisional_overlap),
                             "cross_layer_overlap_excluded_from_titan_provisional_statistics": len(titan_provisional_overlap),
                             "cross_layer_overlap_excluded_from_research_statistics": len(research_overlap)},
        "gate_validation": gate_validation, "real_execution_allowed": False,
    }
    atomic(Path(root) / "calibration" / "shadow_learning_analytics.json", result)
    atomic(Path(root) / "calibration" / "gate_validation.json", gate_validation)
    return result


def daily_paper_funnel(rows, day):
    counts = Counter(); reasons = Counter(); tier3 = Counter(); total = Counter()
    non_wnba = 0
    for row in rows:
        event, frozen = row.get("event") or {}, row.get("execution") or {}
        current = row.get("current_snapshot") or {}
        decision = (current.get("execution") or frozen) if not frozen.get("triggered") else frozen
        pricing = current.get("pricing") or row.get("pricing") or {}
        if (event.get("competition_key") or "").upper() != "WNBA": non_wnba += 1
        markets = (decision.get("learning_classification") or {}).get("markets") or {}
        if not markets:
            markets = {name: classify_market(event, pricing, name, item)
                       for name, item in (decision.get("market_decisions") or {}).items()}
        decision_markets = decision.get("market_decisions") or {}
        titan_markets = decision.get("titan_market_decisions") or {}
        # One fixture remains one display card, but SPREAD and TOTAL are
        # independent signal/accounting records and must be counted separately.
        market_names = tuple(dict.fromkeys(list(decision_markets) + list(markets) + list(titan_markets)))
        event_counts = Counter()
        for name in market_names:
            m = markets.get(name) or {}
            md = decision_markets.get(name) or {}
            td = titan_markets.get(name) or {}
            frozen_market_decisions = frozen.get("market_decisions") or {}
            frozen_market = bool((frozen_market_decisions.get(name) or {}).get("triggered"))
            # Legacy/single-market rows have no isolated market map.  Keep
            # their original event-level fallback, but never let it suppress
            # the second market when both SPREAD and TOTAL were triggered.
            if not frozen_market and not frozen_market_decisions:
                frozen_market = bool(frozen.get("triggered") and
                                     (frozen.get("selected") or {}).get("market_type") == name)
            qualified_market = frozen_market or m.get("shadow_level") == "QUALIFIED_SHADOW"
            titan_market = td.get("status") == "TITAN_PROVISIONAL_SHADOW"
            provisional_market = m.get("shadow_level") == "PROVISIONAL_SHADOW"
            comparable_market = bool(m.get("comparable") or md.get("comparison_ready"))
            if qualified_market:
                counts["qualified_shadow"] += 1; event_counts["qualified"] += 1
            elif titan_market:
                counts["titan_provisional"] += 1; event_counts["titan"] += 1
            elif provisional_market:
                counts["provisional_shadow"] += 1; event_counts["provisional"] += 1
            elif m.get("edge"):
                counts["research_only_edge"] += 1
            if frozen_market or md.get("model_state") == "EDGE" or m.get("model_state") == "EDGE":
                counts["edge"] += 1
            elif md.get("model_state") == "LEAN" or m.get("model_state") == "LEAN":
                counts["lean"] += 1
            elif md.get("model_state") == "NO_EDGE" or m.get("model_state") == "NO_EDGE":
                counts["no_edge"] += 1
            if comparable_market:
                counts["comparable"] += 1; event_counts["comparable"] += 1
            if m.get("shadow_level") == "PROVISIONAL_SHADOW":
                reasons.update(x.get("reason") for x in m.get("evidence_reasons") or [])
            if name == "TOTAL":
                total["market_records"] += int(comparable_market); total[m.get("shadow_level")] += 1
            if (row.get("pricing") or {}).get("league_tier") == "TIER_3" and m.get("edge"):
                tier3[m.get("shadow_level")] += 1
        counts["event_qualified"] += int(event_counts["qualified"] > 0)
        counts["event_titan_provisional"] += int(event_counts["titan"] > 0)
        counts["event_provisional"] += int(event_counts["provisional"] > 0)
        counts["event_comparable"] += int(event_counts["comparable"] > 0)
    required = {key: counts.get(key, 0) for key in ("comparable", "edge", "qualified_shadow", "titan_provisional",
                "provisional_shadow", "research_only_edge", "lean", "no_edge")}
    return {"schema_version": "daily-paper-funnel-1.0", "date_bj": day, "non_wnba_events": non_wnba,
            **required, "event_counts": {key: counts.get(key, 0) for key in
                ("event_comparable", "event_qualified", "event_titan_provisional", "event_provisional")},
            "market_counts": {"market_records": sum(len((row.get("execution") or {}).get("market_decisions") or {})
                for row in rows), "qualified_shadow": counts.get("qualified_shadow", 0),
                "titan_provisional": counts.get("titan_provisional", 0),
                "provisional_shadow": counts.get("provisional_shadow", 0)},
            "provisional_reason_counts": dict(reasons), "tier3_edge": dict(tier3),
            "total": dict(total), "real_execution_allowed": False}
