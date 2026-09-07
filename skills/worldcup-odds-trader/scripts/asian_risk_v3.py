"""Pure v3 conversion/risk functions. No network, orders, or ledger mutation."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Mapping

VERSION = "asian-risk-v3.2.1-20260908"
OUTCOMES = ("win", "half_win", "push", "half_loss", "loss")


def finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def probability(value: float, name: str) -> float:
    value = finite(value, name)
    if not 0 <= value <= 1:
        raise ValueError(f"{name} outside [0,1]")
    return value


def aware_time(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("Timezone-aware timestamps required")
    return result


def de_vig_1x2(home: float, draw: float, away: float) -> dict[str, float]:
    odds = [finite(x, "decimal_odds") for x in (home, draw, away)]
    if min(odds) <= 1:
        raise ValueError("Decimal odds must exceed one")
    raw = [1 / x for x in odds]
    total = sum(raw)
    return dict(zip(("home", "draw", "away", "overround"),
                    [x / total for x in raw] + [total - 1]))


def quote_alignment(quotes: list[Mapping], decision_at: str, *,
                    max_age_seconds: int = 600, max_skew_seconds: int = 120) -> dict:
    """Check one bookmaker's current 90-minute panel, not its opening prices."""
    cutoff = aware_time(decision_at)
    errors, times = [], []
    if len(quotes) != 3 or {q.get("kind") for q in quotes} != {"1x2", "ah", "total"}:
        errors.append("missing_or_duplicate_market")
    for field in ("match_id", "bookmaker_id"):
        if len({q.get(field) for q in quotes}) != 1 or any(not q.get(field) for q in quotes):
            errors.append(field + "_mismatch")
    for q in quotes:
        label = str(q.get("kind", "unknown"))
        if q.get("period") != "90m" or q.get("state") != "pre":
            errors.append(label + ".market_not_pre_90m")
        try:
            event, observed, available = (aware_time(q[k]) for k in ("quoted_at", "observed_at", "available_at"))
            times.append(event)
            if not event <= observed <= available <= cutoff:
                errors.append(label + ".clock_or_future_data")
            if (cutoff - event).total_seconds() > max_age_seconds:
                errors.append(label + ".stale_quote")
        except (KeyError, TypeError, ValueError):
            errors.append(label + ".timestamp_missing")
    if times and (max(times) - min(times)).total_seconds() > max_skew_seconds:
        errors.append("cross_market_skew")
    return {"Quote_Status": "PASS" if not errors else "DATA_PENDING", "Quote_Failed_Gates": errors}


def split_line(line: float) -> tuple[float, float]:
    line = finite(line, "handicap")
    if abs(line * 4 - round(line * 4)) > 1e-8:
        raise ValueError("Handicap must be a quarter-goal multiple")
    if round(line * 4) % 2:
        return math.floor(line * 2) / 2, math.ceil(line * 2) / 2
    return line, line


def result_units(goal_difference: int, signed_handicap: float) -> float:
    """Selected-team margin plus handicap; return +1,+.5,0,-.5,-1."""
    if int(goal_difference) != goal_difference:
        raise ValueError("Goal difference must be an integer")
    return sum((goal_difference + h > 0) - (goal_difference + h < 0)
               for h in split_line(signed_handicap)) / 2


def settlement_distribution(margins: Mapping[int, float], signed_handicap: float) -> dict[str, float]:
    masses = {k: 0.0 for k in OUTCOMES}
    names = {1.0: "win", .5: "half_win", 0.0: "push", -.5: "half_loss", -1.0: "loss"}
    for margin, p in margins.items():
        masses[names[result_units(margin, signed_handicap)]] += probability(p, "mass")
    if not math.isclose(sum(masses.values()), 1.0, abs_tol=1e-7):
        raise ValueError("Unconditional goal-difference masses must sum to one")
    return masses


def validate_masses(masses: Mapping[str, float]) -> None:
    if set(masses) != set(OUTCOMES):
        raise ValueError("All five settlement probabilities required")
    if not math.isclose(sum(probability(masses[k], k) for k in OUTCOMES), 1.0, abs_tol=1e-7):
        raise ValueError("Settlement probabilities must sum to one")


def conversion_metrics(masses: Mapping[str, float], water: float, opposite_water: float,
                       costs: float = 0.0) -> dict[str, float]:
    validate_masses(masses)
    water, opposite_water = finite(water, "water"), finite(opposite_water, "opposite_water")
    costs = finite(costs, "costs")
    if min(water, opposite_water) <= 0 or costs < 0:
        raise ValueError("Positive HK water and nonnegative costs required")
    a = masses["win"] + .5 * masses["half_win"]
    b = masses["loss"] + .5 * masses["half_loss"]
    if a <= 0 or a + b <= 0:
        raise ValueError("No winning exposure; fair water unavailable")
    q_euro = a / (a + b)
    q_ah = (1 / (1 + water)) / (1 / (1 + water) + 1 / (1 + opposite_water))
    return {"Theo_Water": b / a, "P_Euro_AH": q_euro, "P_AH": q_ah,
            "Delta_Conv": q_ah - q_euro, "Delta_Water": water - b / a,
            "EV_Current": a * water - b - costs}


def effective_history(counts: Mapping[str, int], water: float) -> dict[str, float | None]:
    values = {k: finite(counts.get(k, 0), k) for k in OUTCOMES}
    if any(v < 0 or int(v) != v for v in values.values()):
        raise ValueError("Counts must be nonnegative integers")
    if finite(water, "water") <= 0:
        raise ValueError("Positive HK water required")
    a = values["win"] + .5 * values["half_win"]
    b = values["loss"] + .5 * values["half_loss"]
    n = sum(values.values())
    return {"sample": n, "effective_rate": a / (a + b) if a + b else None,
            "pnl_at_current_water": a * water - b,
            "roi_at_current_water": (a * water - b) / n if n else None}


def combined_rate(local_rate: float, local_n: int, global_rate: float, global_n: int) -> float:
    if min(local_n, global_n) <= 0 or int(local_n) != local_n or int(global_n) != global_n:
        raise ValueError("Positive integer sample sizes required")
    return (local_n * probability(local_rate, "local_rate")
            + global_n * probability(global_rate, "global_rate")) / (local_n + global_n)


def conservative_masses(masses: Mapping[str, float], history_rate: float) -> dict[str, float]:
    """Cap model effective probability by history; preserve pushes and within-side half/full mix."""
    validate_masses(masses)
    p = probability(history_rate, "history_rate")
    a = masses["win"] + .5 * masses["half_win"]
    b = masses["loss"] + .5 * masses["half_loss"]
    if a + b == 0:
        raise ValueError("Push-only distribution has no effective rate")
    if p >= a / (a + b):
        return dict(masses)
    winning = masses["win"] + masses["half_win"]
    losing = masses["loss"] + masses["half_loss"]
    if winning == 0 or losing == 0:
        raise ValueError("Cannot infer unseen settlement states from a degenerate model")
    win_weight, loss_weight = a / winning, b / losing
    win_share = p * loss_weight / (win_weight * (1 - p) + p * loss_weight)
    active = 1 - masses["push"]
    return {"win": active * win_share * masses["win"] / winning,
            "half_win": active * win_share * masses["half_win"] / winning,
            "push": masses["push"],
            "half_loss": active * (1 - win_share) * masses["half_loss"] / losing,
            "loss": active * (1 - win_share) * masses["loss"] / losing}


def fundamental_gate(teams: Mapping[str, Mapping], decision_at: str, selected_team: str | None = None) -> dict:
    if selected_team not in {None, "home", "away"}:
        raise ValueError("selected_team must be home or away")
    cutoff = aware_time(decision_at)
    missing, veto, reduced = [], [], []
    for side in ("home", "away"):
        for field in ("schedule", "absences", "rotation_depth", "motivation"):
            entry = teams.get(side, {}).get(field, {})
            key = f"{side}.{field}"
            if entry.get("status") not in {"clear", "reduced", "adverse"} or not entry.get("source"):
                missing.append(key)
                continue
            try:
                timestamp = aware_time(entry["available_at"])
            except (KeyError, TypeError, ValueError):
                missing.append(key + ".available_at")
                continue
            if timestamp > cutoff:
                missing.append(key + ".future_evidence")
            elif entry["status"] == "adverse":
                veto.append(key)
            elif entry["status"] == "reduced":
                reduced.append(key)
    selected_veto = [key for key in veto if selected_team and key.startswith(selected_team + ".")]
    status = "veto" if selected_veto else "pending" if missing else "reduced" if reduced or veto else "pass"
    return {"Fundamental_Status": status, "Fundamental_Failed_Gates": selected_veto + missing,
            "Side_Adverse_Flags": veto,
            "Fundamental_Reductions": reduced}


def intent_crosscheck(delta_upper: float, *, fundamental_status: str, snapshots: int,
                      bookmakers: int, minimum_spacing_minutes: float,
                      resistance_verified: bool, heat_verified: bool,
                      inducement_verified: bool) -> str:
    delta_upper = finite(delta_upper, "delta_upper")
    if abs(delta_upper) > .10:
        return "DATA_OR_MODEL_CONFLICT"
    if fundamental_status not in {"pass", "reduced"}:
        return "FUNDAMENTALS_PENDING"
    # Keep old call arguments, but remove the two-snapshot/five-minute delay.
    if snapshots < 1 or bookmakers < 2 or minimum_spacing_minutes < 0:
        return "QUOTE_CONFIRMATION_PENDING"
    if -.08 <= delta_upper <= -.03 and resistance_verified and not heat_verified:
        return "BLOCK_UPPER_VALIDATION_CANDIDATE"
    if delta_upper >= .03 and heat_verified and inducement_verified:
        return "INDUCE_UPPER_ALERT"
    return "UNCONFIRMED"


def upper_veto(*, heat_verified: bool, resistance_failed: bool = False,
               inducement_verified: bool = False, fatigue_and_thin_squad: bool = False) -> bool:
    return heat_verified and (resistance_failed or inducement_verified or fatigue_and_thin_squad)


def exposure_gate(upper: int, lower: int, *, active_days: int,
                  upper_stake: float = 0.0, lower_stake: float = 0.0) -> dict:
    if min(upper, lower, active_days, upper_stake, lower_stake) < 0:
        raise ValueError("Exposure inputs cannot be negative")
    n = upper + lower
    ratio = upper / n if n else 0.0
    amount = upper_stake + lower_stake
    stake_ratio = upper_stake / amount if amount else 0.0
    long_alert = n >= 30 and active_days >= 3 and (ratio > .8 or (amount > 0 and stake_ratio > .8))
    batch_alert = n >= 8 and ratio > .8
    alert = long_alert or batch_alert
    return {"Upper_Count_Share": ratio, "Upper_Stake_Share": stake_ratio if amount else None,
            "Exposure_Status": "LONG_ALERT" if long_alert else "BATCH_ALERT" if batch_alert else "SMALL_SAMPLE" if n < 8 else "NORMAL",
            "Upper_Safety_Buffer": .04 if alert else .02, "Upper_Multiplier": .5 if alert else 1.0}


def next_day_risk(previous_state: str, daily_roi: list[float], loss_equivalents: float,
                  recovery_shadow_n: int = 0, recovery_shadow_roi: float | None = None) -> dict:
    """Caller supplies only completed active days known at the previous close."""
    if loss_equivalents < 0:
        raise ValueError("Loss equivalents cannot be negative")
    if previous_state in {"COOLDOWN", "HALF"} and recovery_shadow_n >= 3 and recovery_shadow_roi is not None and recovery_shadow_roi > 0:
        return {"Risk_State": "NORMAL", "Day_Multiplier": 1.0}
    if previous_state == "COOLDOWN" or loss_equivalents >= 5 or (len(daily_roi) >= 2 and daily_roi[-1] < 0 and daily_roi[-2] < 0):
        return {"Risk_State": "COOLDOWN", "Day_Multiplier": 0.0}
    if previous_state == "HALF" or loss_equivalents >= 3 or (daily_roi and daily_roi[-1] < 0):
        return {"Risk_State": "HALF", "Day_Multiplier": .5}
    return {"Risk_State": "NORMAL", "Day_Multiplier": 1.0}


def generalized_kelly(masses: Mapping[str, float], water: float, costs: float = 0.0) -> float:
    validate_masses(masses)
    water, costs = finite(water, "water"), finite(costs, "costs")
    if water <= 0 or costs < 0:
        raise ValueError("Invalid water or costs")
    returns = (water - costs, water / 2 - costs, -costs, -.5 - costs, -1 - costs)
    probs = tuple(masses[k] for k in OUTCOMES)
    def derivative(f: float) -> float:
        return sum(p * r / (1 + f * r) for p, r in zip(probs, returns) if p)
    if derivative(0) <= 0:
        return 0.0
    low, high = 0.0, min(.999, .999 / (1 + costs))
    if derivative(high) >= 0:
        return high
    for _ in range(80):
        mid = (low + high) / 2
        if derivative(mid) > 0:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def execution_plan(*, masses: Mapping[str, float], water: float, effective_rate: float,
                   bankroll: float, signed_handicap: float, fundamental_status: str,
                   conversion_passed: bool, calibration_passed: bool,
                   blind_validated: bool = False, high_confidence: bool = False,
                   day_multiplier: float = 1.0, upper_multiplier: float = 1.0,
                   safety_buffer: float = .02, unit_rate: float = .05,
                   single_cap: float = .05, minimum: float = 20.0,
                   remaining_capacity: float = 100.0, costs: float = 0.0,
                   upper_vetoed: bool = False, same_line_vetoed: bool = False,
                   kickoff_at: str | None = None) -> dict:
    validate_masses(masses)
    split_line(signed_handicap)
    effective_rate = probability(effective_rate, "effective_rate")
    for name, value in (("water", water), ("bankroll", bankroll), ("minimum", minimum)):
        if finite(value, name) <= 0:
            raise ValueError(f"{name} must be positive")
    for name, value in (("day_multiplier", day_multiplier), ("upper_multiplier", upper_multiplier), ("safety_buffer", safety_buffer), ("unit_rate", unit_rate), ("single_cap", single_cap)):
        probability(value, name)
    if finite(remaining_capacity, "remaining_capacity") < 0 or finite(costs, "costs") < 0:
        raise ValueError("Capacity and costs cannot be negative")
    threshold = 1 / (1 + water) + safety_buffer
    calendar = {}
    if kickoff_at is not None:
        kickoff = aware_time(kickoff_at).astimezone(timezone(timedelta(hours=8)))
        calendar = {"Is_Weekend": kickoff.weekday() >= 5, "Kickoff_Date_BJ": kickoff.date().isoformat(),
                    "Weekend_Policy": "AUDIT_ONLY"}
    sizing_masses = conservative_masses(masses, effective_rate)
    a = sizing_masses["win"] + .5 * sizing_masses["half_win"]
    b = sizing_masses["loss"] + .5 * sizing_masses["half_loss"]
    sizing_rate = a / (a + b)
    ev = a * water - b - costs
    blind = .75 <= abs(signed_handicap) <= 1.0
    reason = ("FUNDAMENTALS_VETO" if fundamental_status == "veto"
              else "FUNDAMENTALS_PENDING" if fundamental_status not in {"pass", "reduced"}
              else "VETO_UPPER" if upper_vetoed else "SAME_LINE_VETO" if same_line_vetoed
              else "CONV_CONFLICT" if not conversion_passed
              else "SHADOW_UNVALIDATED" if not calibration_passed
              else "COOLDOWN" if day_multiplier == 0
              else "BLIND_SPOT_UNVALIDATED" if blind and not blind_validated
              else "PRICE_EDGE_FAILED" if sizing_rate <= threshold or ev <= 0 else "")
    kelly = generalized_kelly(sizing_masses, water, costs)
    blind_mult = .25 if blind and blind_validated else 0.0 if blind else 1.0
    signal_mult = 1.5 if high_confidence and fundamental_status == "pass" else 1.0
    fundamental_mult = .5 if fundamental_status == "reduced" else 1.0
    desired = bankroll * unit_rate * signal_mult * blind_mult * day_multiplier * upper_multiplier * fundamental_mult
    stake = 0.0 if reason else min(desired, bankroll * .25 * kelly, bankroll * single_cap, remaining_capacity)
    stake = math.floor(stake * 100 + 1e-9) / 100
    if not reason and stake < minimum:
        reason, stake = "BELOW_MIN_STAKE", 0.0
    return {"rule_version": VERSION, "Execution_Status": reason or "READY",
            **calendar, "Stake": stake, "Threshold": round(threshold, 4), "EV_Current": round(ev, 4),
            "Kelly_Full": round(kelly, 4), "Blind_Multiplier": blind_mult,
            "Signal_Multiplier": signal_mult, "Fundamental_Multiplier": fundamental_mult,
            "Sizing_Effective_Rate": round(sizing_rate, 4)}


def execution_recheck(plan: Mapping, quote: Mapping, now: str, *,
                      receipt_states: tuple[str, ...] = (), authorized: bool = False) -> str:
    """Read-only preflight. Never sends an order or mutates a frozen plan."""
    clock = aware_time(now)
    if plan.get("Execution_Status") != "READY" or not plan.get("decision_id"):
        return "PLAN_NOT_READY"
    if any(state in {"PENDING", "UNKNOWN", "FILLED", "PARTIAL"} for state in receipt_states):
        return "DUPLICATE_OR_UNCERTAIN_EXECUTION"
    if clock >= aware_time(plan["kickoff_at"]) or quote.get("state") != "pre":
        return "MATCH_STARTED"
    if clock > aware_time(plan["valid_until"]):
        return "EXPIRED"
    for key in ("match_id", "bookmaker_id", "team_id", "signed_handicap", "period"):
        if key not in plan or key not in quote or quote[key] != plan[key]:
            return "MARKET_CHANGED_NEW_DECISION_REQUIRED"
    try:
        quoted, available = aware_time(quote["quoted_at"]), aware_time(quote["available_at"])
        if not quoted <= available <= clock or (clock - quoted).total_seconds() > 120:
            return "QUOTE_STALE_OR_FUTURE"
        if finite(quote["water"], "water") < finite(plan["minimum_water"], "minimum_water"):
            return "PRICE_BELOW_LIMIT"
        if finite(plan["Stake"], "Stake") <= 0:
            return "INVALID_STAKE"
    except (KeyError, TypeError, ValueError):
        return "EXECUTION_DATA_PENDING"
    return "READY_FOR_AUTHORIZED_EXECUTOR" if authorized else "AUTHORIZATION_REQUIRED"
