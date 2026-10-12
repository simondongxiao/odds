"""Derived signal, paper-execution, and total diagnostics.

This module is deliberately read-only with respect to immutable first-write
records and raw source snapshots.  It may create append-only review artefacts,
but never changes a forecast, decision, quote, or settlement already written.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from .common import BJ, atomic, exclusive, iso, load, stamp
from .validation import build_validation, selected_side_edge, write_validation_artifacts


DEFAULT_LIFECYCLE = {
    "early_entry": {"opens_minutes_before_tip": 240, "closes_minutes_before_tip": 90,
                    "threshold_source": "INITIAL_PRIOR"},
    "late_recheck_minutes_before_tip": [30, 10, 5],
}


def lifecycle_config():
    path = Path(__file__).resolve().parents[2] / "config" / "execution_lifecycle.json"
    return load(path, DEFAULT_LIFECYCLE)


def _selection_outcome(event, selection, fact):
    """Settle only a known final fact. Used for descriptive signal audit, not fill creation."""
    if not event or not selection or not fact or fact.get("status") != "FINAL":
        return None
    suffix = "regulation" if selection.get("ot_rule") == "REGULATION_ONLY" else "full"
    try:
        a, b = fact["score1_" + suffix], fact["score2_" + suffix]
    except KeyError:
        return None
    original_ids = (event.get("team1_id"), event.get("team2_id"))
    fact_ids = (fact.get("team1_id"), fact.get("team2_id"))
    if None in original_ids or set(original_ids) != set(fact_ids):
        return None
    if original_ids == fact_ids[::-1]:
        a, b = b, a
    if selection.get("market_type") == "SPREAD":
        delta = (a - b if selection.get("selection") == "TEAM1" else b - a) + float(selection["line"])
    elif selection.get("market_type") == "TOTAL":
        delta = (a + b - float(selection["line"])) * (1 if selection.get("selection") == "OVER" else -1)
    else:
        return None
    return {
        "outcome": "WIN" if delta > 0 else "LOSS" if delta < 0 else "PUSH",
        "score1": a, "score2": b, "actual_margin": a - b, "actual_total": a + b,
        "score_rule": selection.get("ot_rule"),
    }


def _capture_index(root):
    """Read each immutable capture once for final facts and quote tape."""
    latest, tapes = {}, defaultdict(list)
    for p in (Path(root) / "raw" / "repair_v22").glob("*/capture.json"):
        capture = load(p, {})
        captured = capture.get("capture_finished_at")
        for game in capture.get("history", []):
            if game.get("status") != "FINAL" or not game.get("event_id"):
                continue
            old = latest.get(game["event_id"])
            if old is None or str(captured or "") >= str(old.get("_captured_at") or ""):
                row = dict(game); row["_captured_at"] = captured; latest[game["event_id"]] = row
        for quote in capture.get("quotes", []):
            key = (quote.get("event_id"), quote.get("bookmaker"), quote.get("market_type"), quote.get("ot_rule"))
            if None not in key and quote.get("main_or_alt") == "MAIN":
                tapes[key].append(quote)
    for key in tapes:
        tapes[key].sort(key=lambda x: str(x.get("received_at") or ""))
    return latest, tapes


def _settlements(root):
    return {p.stem: load(p, {}) for p in (Path(root) / "ledger" / "repair_v22_settlements").glob("*.json")}


def _records(root, asof, facts=None):
    """Read first-write records. One decision file always remains one signal record."""
    root = Path(root); facts = facts if facts is not None else _capture_index(root)[0]; settlements = _settlements(root); records = []
    for p in sorted((root / "ledger" / "repair_v22").glob("*/decision_*.json")):
        decision = load(p, {})
        if decision.get("archive_type") != "FORWARD_NATIVE":
            continue
        pid = decision.get("prediction_id")
        if not pid:
            continue
        inp = load(p.with_name("input_" + pid + ".json"), {})
        forecast = load(p.with_name("forecast_" + pid + ".json"), {})
        event, selected = inp.get("event", {}), decision.get("selected")
        if not event or not selected or not decision.get("comparison_ready"):
            continue
        try:
            pretip = iso(decision["asof"]) < iso(event["tip_at"])
        except (KeyError, ValueError):
            pretip = False
        if not pretip:
            continue
        settled = settlements.get(pid)
        evaluation = None
        if settled:
            evaluation = {k: settled.get(k) for k in ("outcome", "score1", "score2", "score_rule", "paper_pnl")}
            if evaluation.get("score1") is not None and evaluation.get("score2") is not None:
                evaluation["actual_margin"] = float(evaluation["score1"]) - float(evaluation["score2"])
                evaluation["actual_total"] = float(evaluation["score1"]) + float(evaluation["score2"])
        else:
            evaluation = _selection_outcome(event, selected, facts.get(event.get("event_id")))
            if evaluation:
                evaluation["paper_pnl"] = None
        model_signal = forecast.get("pricing_status") != "UNPRICEABLE"
        records.append({
            "prediction_id": pid, "event_id": event.get("event_id"), "first_write_path": str(p),
            "first_write_at": decision.get("asof"), "tip_at": event.get("tip_at"), "bj_date": event.get("bj_date"),
            "league": event.get("league"), "model_family": event.get("model_family"),
            "team1": event.get("team1_name"), "team2": event.get("team2_name"),
            "market_type": selected.get("market_type"), "selection": selected.get("selection"),
            "line": selected.get("line"), "decimal_odds": selected.get("decimal_odds"),
            "bookmaker": selected.get("bookmaker"), "ot_rule": selected.get("ot_rule"),
            "model_state": decision.get("model_state"), "signal_valid": bool(model_signal),
            "paper_model_eligible": bool(forecast.get("paper_model_eligible")),
            "execution_triggered": bool(decision.get("triggered")),
            # New forward-native rows are manual-live candidates. Keep the
            # legacy shadow action in the immutable decision JSON, while
            # derived analytics expose the user-facing execution state.
            "execution_action": decision.get("manual_execution_state") or decision.get("shadow_action"),
            "execution_mode": decision.get("execution_mode") or "REPLAY_AUDIT",
            "manual_order_required": bool(decision.get("manual_order_required")),
            "automated_execution_allowed": bool(decision.get("automated_execution_allowed")),
            "entry_ev": selected.get("ev"),
            "entry_adverse_ev": selected.get("adverse_ev"),
            "fair_margin": forecast.get("mu_raw"), "fair_total": forecast.get("total_raw"),
            "model_version": forecast.get("model_version") or selected.get("model_version"),
            "season_regime": (forecast.get("season_regime") if forecast.get("season_regime_evidence") == "EXPLICIT_EVENT_PHASE" else event.get("season_phase") or "REGIME_UNKNOWN"),
            "season_regime_evidence": forecast.get("season_regime_evidence") or ("EXPLICIT_EVENT_PHASE" if event.get("season_phase") else "UNVERIFIED_DEFAULT"),
            "data_quality": forecast.get("spread_data_quality") if selected.get("market_type") == "SPREAD" else forecast.get("pricing_data_quality"),
            "probability_source": selected.get("probability_source"), "p_win": selected.get("p_win"),
            "p_push": selected.get("p_push"), "p_loss": selected.get("p_loss"),
            "raw_team1_line_gap": selected.get("raw_team1_line_gap"),
            "selected_side_line_edge_points": selected.get("selected_side_line_edge_points"),
            "residual_source": selected.get("residual_source") or forecast.get("residual_source"),
            "residual_N": selected.get("residual_N") or forecast.get("residual_oos_N"),
            "df": selected.get("df") or forecast.get("student_t_df"),
            "residual_scale": selected.get("residual_scale") or forecast.get("student_t_scale"),
            "fair_center_uncertainty": forecast.get("fair_center_uncertainty"),
            "probability_status": forecast.get("probability_calibration_status", "UNVALIDATED"),
            "home_court_status": "HOME_COURT_NOT_MODELLED",
            "total_model_status": forecast.get("total_model_status", "EXPERIMENTAL" if selected.get("market_type") == "TOTAL" else None),
            "evaluation": evaluation, "record_generation": "FORWARD_NATIVE_FIRST_WRITE",
            "real_execution_allowed": bool(decision.get("real_execution_allowed")),
        })
    for r in records:
        # These are derived annotations for legacy first-write rows only; the
        # immutable decision JSON is intentionally untouched.
        if r.get("market_type") == "SPREAD" and r.get("fair_margin") is not None and r.get("line") is not None:
            r["raw_team1_line_gap"] = r.get("raw_team1_line_gap")
            if r["raw_team1_line_gap"] is None:
                r["raw_team1_line_gap"] = float(r["fair_margin"]) - (float(r["line"]) if r.get("selection") == "TEAM1" else -float(r["line"]))
        if r.get("selected_side_line_edge_points") is None:
            r["selected_side_line_edge_points"] = selected_side_edge(r)
    return records


def _phase(first_write_at, tip_at, config):
    try:
        minutes = (iso(tip_at) - iso(first_write_at)).total_seconds() / 60
    except Exception:
        return "UNKNOWN_ENTRY_TIME", None
    early = config.get("early_entry", {})
    low, high = early.get("closes_minutes_before_tip", 90), early.get("opens_minutes_before_tip", 240)
    if low <= minutes <= high:
        return "EARLY_PAPER_ENTRY", minutes
    if minutes > high:
        return "SIGNAL_BEFORE_EARLY_WINDOW", minutes
    if minutes > 0:
        return "LATE_PAPER_ENTRY", minutes
    return "POST_TIP_INVALID", minutes


def lifecycle_revision(event, original, current, asof, run_id):
    """A compact append-only lifecycle observation for a prior entry."""
    cfg = lifecycle_config(); selection = original.get("selected") or {}
    phase, minutes = _phase(original.get("asof"), event.get("tip_at"), cfg)
    review = (current or {}).get("market_revalidation") or {}
    status = review.get("status", "REVALIDATION_UNAVAILABLE")
    late_state = "LATE_RECHECK_UNAVAILABLE"
    if status == "STILL_QUALIFIES": late_state = "LATE_RECHECK_STILL_QUALIFIES"
    elif status == "NO_LONGER_QUALIFIES": late_state = "LATE_RECHECK_NO_LONGER_QUALIFIES"
    elif status == "EVENT_STARTED": late_state = "EVENT_STARTED_SETTLEMENT_TRACKING"
    return {
        "schema_version": 1, "revision_id": run_id, "prediction_id": original.get("prediction_id"),
        "event_id": event.get("event_id"), "observed_at": asof, "first_write_at": original.get("asof"),
        "entry_phase": phase, "minutes_before_tip_at_entry": minutes,
        "threshold_source": cfg.get("early_entry", {}).get("threshold_source", "INITIAL_PRIOR"),
        "original_selection": selection, "recheck_status": status, "late_state": late_state,
        "price_exhausted": False,
        "price_exhausted_reason": "A triggered first-write paper entry remains an execution record; a later move only changes recheck status.",
        "real_execution_allowed": False,
    }


def append_lifecycle_revision(root, event, original, current, asof, run_id):
    record = lifecycle_revision(event, original, current, asof, run_id)
    pid = record.get("prediction_id")
    if not pid:
        return None
    path = Path(root) / "revisions" / "repair_v22" / pid / (run_id + ".json")
    exclusive(path, record)
    return record


def _tape(tapes, record):
    """Select an already indexed immutable same-contract tape."""
    out = []
    key = (record.get("event_id"), record.get("bookmaker"), record.get("market_type"), record.get("ot_rule"))
    for quote in tapes.get(key, []):
        line = quote.get("raw_line") if record.get("market_type") == "TOTAL" else quote.get("line_team1")
        if line is None:
            continue
        if record.get("market_type") == "SPREAD" and record.get("selection") == "TEAM2":
            line = -float(line)
        out.append({"captured_at": quote.get("received_at"), "source_quote_at": quote.get("source_quote_at"),
                    "line": float(line), "quote_id": quote.get("quote_id"), "raw_path": quote.get("raw_path")})
    return sorted(out, key=lambda x: str(x.get("captured_at") or ""))


def _tape_summary(record, tape):
    if not tape:
        return {"observations": 0, "first_observed_line": None, "entry_line": record.get("line"),
                "t90_line": None, "t30_line": None, "t10_line": None, "close_line": None,
                "movement_status": "INSUFFICIENT_TAPE"}
    try:
        tip = iso(record["tip_at"])
    except Exception:
        tip = None
    out = {"observations": len(tape), "first_observed_line": tape[0]["line"], "entry_line": record.get("line"),
           "last_observed_line": tape[-1]["line"], "close_line": None,
           "first_observed_at": tape[0].get("captured_at"), "last_observed_at": tape[-1].get("captured_at")}
    pretip = []
    if tip:
        for item in tape:
            try:
                if iso(item.get("captured_at")) < tip:
                    pretip.append(item)
            except Exception:
                continue
    if pretip:
        out["close_line"] = pretip[-1]["line"]
        out["close_observed_at"] = pretip[-1].get("captured_at")
    for minutes, key in ((90, "t90_line"), (30, "t30_line"), (10, "t10_line")):
        candidates = [x for x in tape if tip and iso(x["captured_at"]) <= tip - timedelta(minutes=minutes)]
        out[key] = candidates[-1]["line"] if candidates else None
    fair = record.get("fair_total") if record.get("market_type") == "TOTAL" else record.get("fair_margin")
    if fair is None:
        out["movement_status"] = "FAIR_LINE_UNAVAILABLE"
    else:
        # Spread fair margin is team1-team2; selection is already team-relative above.
        target = float(fair) if record.get("market_type") == "TOTAL" else (float(fair) if record.get("selection") == "TEAM1" else -float(fair))
        comparison_line = out["close_line"] if out["close_line"] is not None else tape[-1]["line"]
        first_distance, last_distance = abs(tape[0]["line"] - target), abs(comparison_line - target)
        out.update(fair_line_for_selection=target, first_distance_to_fair=first_distance, last_distance_to_fair=last_distance,
                   movement_status="TOWARD_MODEL" if last_distance < first_distance else "AWAY_FROM_MODEL" if last_distance > first_distance else "UNCHANGED")
    return out


def _earliest_by_event_market(records, predicate=lambda r: True):
    """One frozen first-write signal per canonical event/market for statistics.

    Repeated later captures remain in the immutable ledger, but counting them as
    independent samples would inflate both direction and paper PnL statistics.
    """
    chosen, superseded = {}, []
    for record in sorted((r for r in records if predicate(r)), key=lambda r: (r.get("first_write_at", ""), r.get("prediction_id", ""))):
        key = (record.get("event_id"), record.get("market_type"))
        if key in chosen:
            superseded.append(record)
        else:
            chosen[key] = record
    return list(chosen.values()), superseded


def _summary(signal_records, execution_records, market_type):
    items = [r for r in signal_records if r.get("market_type") == market_type]
    outcomes = Counter((r.get("evaluation") or {}).get("outcome", "PENDING") for r in items)
    settled = outcomes["WIN"] + outcomes["LOSS"] + outcomes["PUSH"]
    executed = [r for r in execution_records if r.get("market_type") == market_type]
    executed_outcomes = Counter((r.get("evaluation") or {}).get("outcome", "PENDING") for r in executed)
    exec_settled = executed_outcomes["WIN"] + executed_outcomes["LOSS"] + executed_outcomes["PUSH"]
    pnl = sum(float((r.get("evaluation") or {}).get("paper_pnl") or 0) for r in executed if (r.get("evaluation") or {}).get("paper_pnl") is not None)
    return {
        "signals": len(items), "signal_wins": outcomes["WIN"], "signal_losses": outcomes["LOSS"],
        "signal_pushes": outcomes["PUSH"], "signal_pending": outcomes["PENDING"],
        "signal_hit_rate_ex_push": outcomes["WIN"] / (outcomes["WIN"] + outcomes["LOSS"]) if outcomes["WIN"] + outcomes["LOSS"] else None,
        "executed": len(executed), "execution_wins": executed_outcomes["WIN"], "execution_losses": executed_outcomes["LOSS"],
        "execution_pushes": executed_outcomes["PUSH"], "execution_pending": executed_outcomes["PENDING"],
        "execution_pnl_units": pnl, "execution_roi": pnl / exec_settled if exec_settled else None,
        "note": "Signal results describe frozen first-write directions; they are not a strategy win rate. Execution PnL includes only triggered paper entries."
    }


def build_analytics(root, asof):
    """Build immutable-derived reporting files and return the dashboard payload."""
    root = Path(root); facts, tapes = _capture_index(root); records = _records(root, asof, facts); cfg = lifecycle_config()
    revisions = {}
    for p in (root / "revisions" / "repair_v22").glob("*/*.json"):
        d = load(p, {}); revisions.setdefault(d.get("prediction_id"), []).append(d)
    for r in records:
        r["entry_phase"], r["minutes_before_tip_at_entry"] = _phase(r["first_write_at"], r["tip_at"], cfg)
        r["market_tape"] = _tape_summary(r, _tape(tapes, r))
        r["revisions"] = sorted(revisions.get(r["prediction_id"], []), key=lambda x: x.get("observed_at", ""))
        # Historical migration does not infer price exhaustion from a missing price.
        r["execution_classification"] = "EXECUTED" if r["execution_triggered"] else "SIGNAL_VALID_EXECUTION_NOT_TRIGGERED"
        r["price_exhausted"] = False
        r["price_exhausted_evidence"] = "NOT_PROVEN_FROM_AVAILABLE_APPEND_ONLY_RECHECKS"
    signal_records, superseded_signal_records = _earliest_by_event_market(records)
    execution_records, superseded_execution_records = _earliest_by_event_market(records, lambda r: r.get("execution_triggered"))
    for r in signal_records:
        r["statistical_inclusion"] = "EARLIEST_VALID_SIGNAL_PER_EVENT_MARKET"
    for r in superseded_signal_records:
        r["statistical_inclusion"] = "SUPERSEDED_REPEAT_CAPTURE_NOT_A_SEPARATE_SAMPLE"
    validation = build_validation(signal_records)
    for r in signal_records:
        ann = (validation.get("record_annotations") or {}).get(r.get("prediction_id"), {})
        r["validation"] = ann
        r["selected_side_line_edge_points"] = ann.get("selected_side_line_edge_points", selected_side_edge(r))
    spread, total = _summary(signal_records, execution_records, "SPREAD"), _summary(signal_records, execution_records, "TOTAL")
    total_rows = []
    for r in signal_records:
        if r.get("market_type") != "TOTAL" or not r.get("evaluation") or r["evaluation"].get("actual_total") is None:
            continue
        actual, predicted, line = r["evaluation"]["actual_total"], r.get("fair_total"), r.get("line")
        if predicted is None:
            continue
        total_rows.append({"prediction_id": r["prediction_id"], "league": r.get("league"), "model_family": r.get("model_family"),
                           "actual_total": actual, "predicted_total": predicted, "market_total": line,
                           "model_residual": actual - predicted, "market_residual": actual - line,
                           "entry_phase": r.get("entry_phase"), "record_generation": r.get("record_generation")})
    def mean(key): return sum(x[key] for x in total_rows) / len(total_rows) if total_rows else None
    total_diagnostic = {"status": "EXPERIMENTAL_DIAGNOSTIC_ONLY", "settled_total_observations": len(total_rows),
                        "mean_model_residual": mean("model_residual"), "mean_market_residual": mean("market_residual"),
                        "bias_conclusion": "INSUFFICIENT_FORWARD_NATIVE_SAMPLE" if len(total_rows) < 20 else "DESCRIPTIVE_ONLY_NOT_USED_FOR_PARAMETERS",
                        "rows": total_rows,
                        "rules": ["Unknown injury/pace/foul context adds diagnostic uncertainty only.",
                                  "It never changes the official total mean, sigma, probability, Kelly, or execution gate.",
                                  "No total conclusion is labelled validated before adequate forward-native samples."]}
    exhausted = [r for r in records if r.get("price_exhausted")]
    failure_audit = load(root / "audits" / "post_mortem.json", {"records": [], "counts": {}})
    result = {"schema_version": 1, "generated_at": stamp(), "asof": asof, "archive_scope": "FORWARD_NATIVE_FIRST_WRITE_ONLY",
              "spread_signal_layer": spread, "spread_execution_layer": spread,
              "price_exhaustion_layer": {"count": len(exhausted), "records": exhausted,
                                         "note": "No price-exhausted classification is inferred without same-contract before/after recheck evidence."},
              "total_diagnostic_layer": total_diagnostic, "records": signal_records,
              "probability_ev_empirical_validation": validation,
              "failure_audit_layer": {"count": len(failure_audit.get("records", [])),
                                      "counts": failure_audit.get("counts", {}),
                                      "new_records": failure_audit.get("new_records", 0),
                                      "records": failure_audit.get("records", []),
                                      "append_only": True},
              "execution_records": execution_records,
              "migration": {"raw_first_write_records_found": len(records),
                            "canonical_signal_records": len(signal_records),
                            "repeat_capture_records_excluded_from_statistics": len(superseded_signal_records),
                            "canonical_execution_records": len(execution_records),
                            "repeat_execution_records_excluded_from_statistics": len(superseded_execution_records),
                            "policy": "Earliest valid first-write per canonical event and market is the only statistical sample; later captures remain audit evidence."},
              "real_execution_allowed": False,
              "model_validation": {"SPREAD_MODEL_VALIDATED": False, "TOTAL_MODEL_VALIDATED": False,
                                   "reason": "Forward-native sample is descriptive and insufficient for calibration claims.",
                                   "probability_calibration": validation.get("probability_calibration"),
                                   "empirical_governance": validation.get("governance"),
                                   "home_court": "HOME_COURT_NOT_MODELLED",
                                   "no_auto_tuning": True}}
    atomic(root / "calibration" / "spread_execution_total_analytics.json", result)
    atomic(root / "audits" / "historical_signal_execution_migration.json", result)
    write_validation_artifacts(root, asof, validation, signal_records)
    return result
