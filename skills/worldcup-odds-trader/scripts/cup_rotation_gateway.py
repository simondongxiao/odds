"""Pre-Delta cup/rotation gateway. Pure functions; no scraping or order submission."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Callable, Mapping

from asian_risk_v3 import aware_time, finite, fundamental_gate, split_line

VERSION = "cup-rotation-v1-20260907"
NATURES = {"联赛", "单场杯赛", "两回合首回合", "两回合次回合"}
DENSITIES = {"正常", "一周双赛", "一周三赛"}
ROTATIONS = {"低", "中", "高"}
MOTIVATIONS = {"正常", "战意成疑", "必须全力争胜"}
STRATEGIC_FACTOR = {"正常": 1.0, "战意成疑": .85, "必须全力争胜": 1.0}
ROTATION_FACTOR = {"低": 1.0, "中": .90, "高": .75}
FATIGUE_FACTOR = {
    "主场": {"正常": 1.0, "一周双赛": .95, "一周三赛": .90},
    "客场": {"正常": 1.0, "一周双赛": .90, "一周三赛": .85},
    "中立": {"正常": 1.0, "一周双赛": .925, "一周三赛": .875},
}


@dataclass(frozen=True)
class GatewayPolicy:
    dense_deep_action: str = "skip"
    minimum_confidence: float = 60.0

    def __post_init__(self):
        if self.dense_deep_action not in {"skip", "quarter"}:
            raise ValueError("dense_deep_action must be skip or quarter")
        if not 0 <= finite(self.minimum_confidence, "minimum_confidence") <= 100:
            raise ValueError("minimum_confidence must be in [0,100]")


def _evidence(value: Mapping, cutoff, label: str) -> None:
    if not value.get("Source") or aware_time(value["Available_At"]) > cutoff:
        raise ValueError(label + ": missing source or future evidence")


def _goal(value) -> int:
    number = finite(value, "first_leg_goal")
    if isinstance(value, bool) or number < 0 or int(number) != number:
        raise ValueError("First-leg goals must be nonnegative integers")
    return int(number)


def schedule_density(prior_fixture_ids: list[str]) -> str:
    """Input: known, unique-team fixtures in [kickoff-7d,kickoff), excluding this match."""
    if any(not isinstance(item, str) or not item.strip() for item in prior_fixture_ids):
        raise ValueError("Prior fixtures require stable nonempty IDs")
    count = len(set(prior_fixture_ids)) + 1
    return "一周三赛" if count >= 3 else "一周双赛" if count == 2 else "正常"


def confidence_adjustment(base: float, team: Mapping, venue: str) -> dict:
    base = finite(base, "base_confidence")
    if not 0 <= base <= 100:
        raise ValueError("Confidence is a score in [0,100], not a win probability")
    factors = {"Strategic_Factor": STRATEGIC_FACTOR[team["Strategic_Intent"]],
               "Fatigue_Factor": FATIGUE_FACTOR[venue][team["Schedule_Density"]],
               "Rotation_Factor": ROTATION_FACTOR[team["Rotation_Risk"]]}
    factor = math.prod(factors.values())
    return {"Base_Confidence": base, "Confidence_Factor": factor,
            "Adjusted_Confidence": round(base * factor, 4), **factors}


def cup_rotation_gate(context: Mapping, policy: GatewayPolicy | None = None) -> dict:
    policy = policy or GatewayPolicy()
    result = {"Guardrail_Version": VERSION, "Gateway_Status": "DATA_PENDING",
              "Execution_Code": "CUP_CONTEXT_PENDING", "Execution_Status": "待核（赛制/轮换资料缺失）",
              "Failed_Gate": "", "Stake_Cap_Units": 0.0,
              "Delta_Conv": None, "Stake": 0.0,
              "Match_Nature": context.get("Match_Nature")}

    def stop(code: str, label: str, reason: str) -> dict:
        result.update(Gateway_Status="SKIP", Execution_Code=code,
                      Execution_Status=label, Failed_Gate=reason, Stake_Cap_Units=0.0)
        return result

    try:
        cutoff, kickoff = aware_time(context["Decision_At"]), aware_time(context["Kickoff_At"])
        if not context.get("Match_ID"):
            raise ValueError("Missing current match ID")
        if cutoff >= kickoff:
            return stop("MATCH_STARTED", "不新增赛前计划（已开赛）", "decision_at >= kickoff")
        nature = context["Match_Nature"]
        if nature not in NATURES:
            raise ValueError("Unknown Match_Nature; do not infer it from a cup name")
        _evidence(context["Nature_Evidence"], cutoff, "match_nature")
        home, away, selected = context["Home_Team_ID"], context["Away_Team_ID"], context["Selected_Team_ID"]
        if not home or not away or home == away or selected not in {home, away}:
            raise ValueError("Current teams/selected team are not aligned")
        result["Selected_Team_ID"] = selected

        # Join the first leg by team identity, never by current home/away position.
        if nature == "两回合次回合":
            leg = context["First_Leg"]
            _evidence(leg, cutoff, "first_leg")
            if not context.get("Tie_ID") or leg.get("Tie_ID") != context["Tie_ID"]:
                raise ValueError("First leg belongs to a different or unknown tie")
            if not leg.get("Match_ID") or leg["Match_ID"] == context["Match_ID"]:
                raise ValueError("Invalid first-leg match id")
            if aware_time(leg["Finished_At"]) > aware_time(leg["Available_At"]):
                raise ValueError("First-leg result was not available at decision time")
            if {leg["Home_Team_ID"], leg["Away_Team_ID"]} != {home, away}:
                raise ValueError("First-leg team IDs do not match this tie")
            hg, ag = _goal(leg["Home_Goals"]), _goal(leg["Away_Goals"])
            lead = hg - ag
            leader = leg["Home_Team_ID"] if lead > 0 else leg["Away_Team_ID"] if lead < 0 else None
            result.update(First_Leg_Leader_ID=leader, First_Leg_Lead=abs(lead))
            if abs(lead) >= 2:
                result["Assessment_Team_ID"] = leader
                return stop("SKIP_SECOND_LEG_LEAD", "强制跳过（警惕轮换与功利控盘）",
                            "两回合次回合：首回合优势方领先至少2球；整场跳过，不自动反投")

        line = finite(context["Home_Handicap"], "home_handicap")
        split_line(line)
        favorite = home if line < 0 else away if line > 0 else None
        result.update(Favorite_Team_ID=favorite, Assessment_Team_ID=favorite or selected, Home_Handicap=line)
        teams = context["Teams"]
        for team_id in (home, away):
            team = teams[team_id]
            _evidence(team, cutoff, str(team_id))
            if team.get("Schedule_Density") not in DENSITIES or team.get("Rotation_Risk") not in ROTATIONS or team.get("Strategic_Intent") not in MOTIVATIONS:
                raise ValueError(str(team_id) + ": unknown density/rotation/motivation")
        fundamentals = fundamental_gate(context.get("Fundamental_Evidence", {}), context["Decision_At"],
                                        "home" if selected == home else "away")
        result["Fundamental_Status"] = fundamentals["Fundamental_Status"]
        if fundamentals["Fundamental_Status"] == "veto":
            return stop("FUNDAMENTALS_VETO", "强制跳过（核心基本面否决）",
                        ", ".join(fundamentals["Fundamental_Failed_Gates"]))
        if fundamentals["Fundamental_Status"] == "pending":
            raise ValueError("Core fundamentals pending: " + ", ".join(fundamentals["Fundamental_Failed_Gates"]))
        assessed = teams[favorite or selected]
        result.update({key: assessed[key] for key in ("Schedule_Density", "Rotation_Risk", "Strategic_Intent")})
        neutral = context["Neutral_Venue"]
        if type(neutral) is not bool:
            raise ValueError("Neutral_Venue must be verified true/false")
        _evidence(context["Venue_Evidence"], cutoff, "venue")
        venue = "中立" if neutral else "主场" if selected == home else "客场"
        result.update(Selected_Venue=venue,
                      Selected_Schedule_Density=teams[selected]["Schedule_Density"],
                      Selected_Rotation_Risk=teams[selected]["Rotation_Risk"],
                      Selected_Strategic_Intent=teams[selected]["Strategic_Intent"])
        if context.get("Confidence_Basis") != "before_context_adjustment":
            raise ValueError("Base_Confidence must not already include these context deductions")
        adjustment = confidence_adjustment(context["Base_Confidence"], teams[selected], venue)
        result.update(adjustment)
        dense_deep = (favorite is not None and .75 <= abs(line) <= 1.0
                      and assessed["Schedule_Density"] in {"一周双赛", "一周三赛"}
                      and assessed["Rotation_Risk"] == "高")
        if dense_deep and policy.dense_deep_action == "skip":
            return stop("SKIP_DENSE_DEEP_ROTATION", "强制跳过（密集赛程深盘高轮换）",
                        "让0.75-1.0且让球方一周双赛/三赛、高轮换风险")
        if adjustment["Base_Confidence"] * adjustment["Confidence_Factor"] < policy.minimum_confidence:
            return stop("CONTEXT_CONFIDENCE_LOW", "不投（赛制/轮换信心不足）",
                        f"调整后信心{adjustment['Adjusted_Confidence']:.2f} < {policy.minimum_confidence:.2f}")
        result.update(Gateway_Status="QUARTER_CAP" if dense_deep else "PASS",
                      Execution_Code="GATEWAY_PASSED", Execution_Status="待后续Delta及原策略校验",
                      Stake_Cap_Units=.25 if dense_deep else None, Failed_Gate="")
        return result
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        result.update(Gateway_Status="DATA_PENDING", Execution_Code="CUP_CONTEXT_PENDING",
                      Execution_Status="待核（赛制/轮换资料缺失）", Failed_Gate=str(exc), Stake_Cap_Units=0.0)
        return result


def run_guarded_analysis(context: Mapping, *, calculate_delta: Callable[[], Mapping],
                         existing_funnel: Callable[[Mapping], Mapping], bankroll: float,
                         unit_rate: float = .05, minimum_stake: float = 20,
                         policy: GatewayPolicy | None = None) -> dict:
    """Gate -> Delta callback -> original full strategy -> hard stake cap. No orders."""
    if context.get("Frozen_Decision") is not None:
        return deepcopy(context["Frozen_Decision"])
    gate = cup_rotation_gate(context, policy)
    if gate["Gateway_Status"] not in {"PASS", "QUARTER_CAP"}:
        return gate
    if finite(bankroll, "bankroll") <= 0 or not 0 < finite(unit_rate, "unit_rate") <= 1 or finite(minimum_stake, "minimum_stake") <= 0:
        raise ValueError("Positive bankroll/unit/minimum required")
    delta = dict(calculate_delta())
    try:
        finite(delta["Delta_Conv"], "Delta_Conv")
    except (KeyError, TypeError, ValueError):
        return {**gate, "Execution_Code": "DELTA_DATA_PENDING", "Execution_Status": "待核（Delta缺失或无效）",
                "Failed_Gate": "独立欧亚转换结果缺失/无效", "Stake": 0.0}
    # The original funnel still owns quote/fundamental/EV/calibration/cooling checks.
    previous = dict(existing_funnel({**delta, "Context_Gateway": deepcopy(gate)}))
    result = dict(previous)
    for key, value in gate.items():
        if key not in {"Execution_Status", "Execution_Code", "Stake", "Delta_Conv", "Failed_Gate"}:
            result[key] = value
    result["Delta_Conv"] = delta.get("Delta_Conv")
    result["Gateway_Failed_Gate"] = gate["Failed_Gate"]
    result["Execution_Code"] = previous.get("Execution_Code") or previous.get("Execution_Status", "ORIGINAL_FUNNEL_PENDING")
    if previous.get("Execution_Status") != "READY":
        result["Stake"] = 0.0
        return result
    before = finite(previous["Stake"], "original_stake")
    if before < 0:
        raise ValueError("Original stake cannot be negative")
    cap = gate["Stake_Cap_Units"]
    stake = min(before, bankroll * unit_rate * cap) if cap is not None else before
    result["Stake_Before_Context_Cap"] = before
    result["Stake"] = math.floor(stake * 100 + 1e-9) / 100
    if result["Stake"] < minimum_stake:
        result.update(Stake=0.0, Execution_Status="BELOW_MIN_STAKE", Execution_Code="BELOW_MIN_STAKE",
                      Failed_Gate="前置降仓后金额低于最低投注额，不向上凑仓")
    return result
