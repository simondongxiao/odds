"""Future-only cup context and hierarchical evidence for V3 production.

This module is part of the existing V3 pipeline.  It does not create a second
decision system and never writes historical ledgers.  Competition labels are
features, never direct BET/NO_BET commands.
"""
from __future__ import annotations

import csv
import datetime as dt
import importlib.util
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


WORKSPACE = Path(r"D:\codex")
SHARED_LEDGER = WORKSPACE / "outputs" / "football_odds_trader" / "ledger"
NORMALIZER_PATH = WORKSPACE / "tools" / "football_competition_normalizer.py"
VERSION = "V3_CUP_MATCH_STATE_R1_20260930"
ACTIVATION_AT = dt.datetime.fromisoformat("2026-09-30T15:45:00+08:00")
MISSING = "MISSING"
SETTLED = {"红", "红半", "走水", "黑半", "黑"}


def _load_normalizer():
    spec = importlib.util.spec_from_file_location("canonical_football_competition_normalizer", NORMALIZER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load canonical normalizer: {NORMALIZER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


NORMALIZER = _load_normalizer()


def clean(value: Any) -> str:
    return str(value or "").strip()


def number(value: Any) -> float | None:
    try:
        text = clean(value).replace("%", "")
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def parse_time(value: Any) -> dt.datetime | None:
    text = clean(value)
    if not text:
        return None
    text = text.replace("北京时间（东8区）", "").replace("北京时间", "").strip()
    text = re.sub(r"^(\d{4})-(\d{1,2})-(\d{1,2})", lambda m: f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", text)
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = dt.datetime.strptime(text, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
    return parsed.astimezone(dt.timezone(dt.timedelta(hours=8)))


def canonical_intent(value: Any) -> str:
    text = clean(value).replace(" ", "")
    text = text.replace("阻下/上盘保护", "阻下/下盘保护")
    return text or MISSING


def intended_side(tag: str) -> str:
    tag = canonical_intent(tag)
    if tag in {"阻上/诱下", "阻上/降温保护", "真实示强/阻上", "诱下/上盘降温"}:
        return "GIVING"
    if tag in {"诱上/阻下", "真实示弱/阻下", "降温保护/诱下", "阻下/下盘保护"}:
        return "RECEIVING"
    return MISSING


def is_cup_domain(domain: str, info: Any) -> bool:
    return domain in {"CLUB_CUP", "CONTINENTAL_CLUB", "NATIONAL_OFFICIAL", "NATIONAL_YOUTH"} or info.competition_scope == "国内杯赛"


def _explicit_match_state(*values: Any) -> str:
    text = " ".join(clean(value) for value in values if clean(value))
    if not text:
        return MISSING
    if re.search(r"两回合.*次回合|次回合|第二回合|second\s*leg", text, re.I):
        return "TWO_LEG_SECOND"
    if re.search(r"两回合.*首回合|首回合|第一回合|first\s*leg", text, re.I):
        return "TWO_LEG_FIRST"
    if re.search(r"小组赛|group\s*stage", text, re.I):
        return "GROUP_STAGE"
    if re.search(r"联赛阶段|league\s*phase", text, re.I):
        return "LEAGUE_PHASE"
    if re.search(r"单场淘汰|淘汰赛|1/\d+决赛|半决赛|决赛|single.*knockout", text, re.I):
        return "SINGLE_KNOCKOUT"
    return MISSING


def _aggregate_state(*values: Any) -> tuple[str, int | None, int | None]:
    text = " ".join(clean(value) for value in values if clean(value))
    match = re.search(r"(?:总比分|aggregate)[^0-9]*(\d+)\s*[-:：]\s*(\d+)", text, re.I)
    if not match:
        return MISSING, None, None
    home, away = int(match.group(1)), int(match.group(2))
    if home > away:
        return "HOME_LEADS", home, away
    if away > home:
        return "AWAY_LEADS", home, away
    return "LEVEL", home, away


def _rotation_state(*values: Any) -> str:
    text = " ".join(clean(value) for value in values if clean(value))
    if not text:
        return MISSING
    if re.search(r"大幅轮换|全替补|高轮换|rotation\s*high", text, re.I):
        return "HIGH"
    if re.search(r"部分轮换|中度轮换|rotation\s*medium", text, re.I):
        return "MEDIUM"
    if re.search(r"主力阵容|低轮换|不轮换|rotation\s*low", text, re.I):
        return "LOW"
    return MISSING


def _rest_days(*values: Any) -> int | str:
    text = " ".join(clean(value) for value in values if clean(value))
    match = re.search(r"(?:休息|间隔|rest)\s*(\d+)\s*(?:天|day)", text, re.I)
    return int(match.group(1)) if match else MISSING


def cup_match_state_gateway(
    competition: str,
    ledger_row: dict[str, Any],
    detail: dict[str, Any],
    *,
    decision_at: dt.datetime,
    kickoff_at: dt.datetime | None,
) -> dict[str, Any]:
    info = NORMALIZER.normalize(competition)
    domain = NORMALIZER.competition_domain(info)
    is_cup = is_cup_domain(domain, info)
    stage_values = (
        ledger_row.get("赛制阶段"), ledger_row.get("Match_Nature"),
        detail.get("match_stage"), detail.get("schedule_context"), detail.get("competition_context"),
    )
    state = _explicit_match_state(*stage_values) if is_cup else "NOT_CUP"
    aggregate, aggregate_home, aggregate_away = _aggregate_state(*stage_values)
    rotation = _rotation_state(
        ledger_row.get("Rotation_Risk"), detail.get("rotation_risk"),
        detail.get("lineup_text"), detail.get("schedule_context"),
    ) if is_cup else "NOT_CUP"
    rest = _rest_days(ledger_row.get("rest_days"), detail.get("rest_days"), detail.get("schedule_context")) if is_cup else "NOT_CUP"
    if not is_cup:
        utility = "NOT_CUP"
    elif state == "TWO_LEG_SECOND" and aggregate != MISSING:
        utility = {
            "HOME_LEADS": "HOME_CAN_MANAGE_MARGIN",
            "AWAY_LEADS": "AWAY_CAN_MANAGE_MARGIN",
            "LEVEL": "BOTH_REQUIRE_PROGRESS",
        }[aggregate]
    elif state in {"SINGLE_KNOCKOUT", "TWO_LEG_FIRST"}:
        utility = "ADVANCEMENT_REQUIRED_BUT_MARGIN_UNKNOWN"
    elif state in {"GROUP_STAGE", "LEAGUE_PHASE"}:
        utility = "TABLE_UTILITY_MISSING"
    else:
        utility = MISSING
    missing = []
    if is_cup:
        for name, value in (("match_state", state), ("aggregate_state", aggregate), ("rotation_risk", rotation), ("rest_days", rest)):
            if value == MISSING:
                missing.append(name)
    pre_match = kickoff_at is not None and decision_at < kickoff_at
    future_only = bool(is_cup and pre_match and kickoff_at > ACTIVATION_AT and decision_at >= ACTIVATION_AT)
    return {
        "Cup_Gateway_Version": VERSION,
        "Competition_Canonical": info.competition_canonical,
        "Competition_Domain": domain,
        "Competition_Micro_Region": info.micro_region,
        "Is_Cup_Context": is_cup,
        "Cup_Match_State": state,
        "Cup_Aggregate_State": aggregate,
        "Cup_Aggregate_Home": aggregate_home if aggregate_home is not None else MISSING,
        "Cup_Aggregate_Away": aggregate_away if aggregate_away is not None else MISSING,
        "Cup_Qualification_Utility": utility,
        "Cup_Rotation_Risk": rotation,
        "Cup_Rest_Days": rest,
        "Cup_Schedule_Pressure": MISSING if is_cup else "NOT_CUP",
        "Cup_Context_Missing": ",".join(missing) if missing else "NONE",
        "Cup_Gateway_Status": "PARTIAL_MISSING" if missing else ("PASS" if is_cup else "NOT_APPLICABLE"),
        "Cup_Refactor_Eligible": future_only,
        "Cup_Activation_At": ACTIVATION_AT.isoformat(),
    }


def devig_probabilities(row: dict[str, Any]) -> tuple[float, float, float] | None:
    odds = [number(row.get(key)) for key in (
        "euro_full_current_home_or_over", "euro_full_current_line_or_draw", "euro_full_current_away_or_under"
    )]
    if any(value is None or value <= 1 for value in odds):
        return None
    inverse = [1 / value for value in odds]  # type: ignore[arg-type]
    total = sum(inverse)
    return tuple(value / total for value in inverse)  # type: ignore[return-value]


def pull_and_fair_line(row: dict[str, Any], ledger_row: dict[str, Any], gateway: dict[str, Any]) -> dict[str, Any]:
    probs = devig_probabilities(row)
    actual_line = number(row.get("ah_full_current_line_or_draw"))
    if probs is None:
        return {
            "Football_Pull_Score": MISSING, "Football_Pull_Basis": "MISSING_DEVIG_1X2",
            "Public_Pull": MISSING, "Public_Pull_Basis": "NO_VERIFIED_PUBLIC_FLOW",
            "fair_goal_margin": MISSING, "fair_handicap": MISSING, "line_gap": MISSING,
            "Fair_Line_Status": "MISSING",
        }
    home, draw, away = probs
    # Explicitly an uncalibrated market-implied proxy, not a claimed goal model.
    fair_goal_margin = max(-3.0, min(3.0, math.log(max(home, 1e-6) / max(away, 1e-6)) * 0.72))
    utility = gateway.get("Cup_Qualification_Utility")
    if utility == "HOME_CAN_MANAGE_MARGIN":
        fair_goal_margin -= 0.15
    elif utility == "AWAY_CAN_MANAGE_MARGIN":
        fair_goal_margin += 0.15
    fair_handicap = round(fair_goal_margin * 4) / 4
    pull_score = round((home - away + 1) * 50, 3)
    line_gap = round(actual_line - fair_handicap, 4) if actual_line is not None else MISSING
    public_value = number(ledger_row.get("Public_Pull"))
    public_basis = "VERIFIED_LEDGER_PUBLIC_PULL" if public_value is not None else "NO_VERIFIED_PUBLIC_FLOW"
    return {
        "Football_Pull_Score": pull_score,
        "Football_Pull_Basis": "DEVIG_1X2+VERIFIED_MATCH_UTILITY; UNCALIBRATED_PROXY",
        "Public_Pull": public_value if public_value is not None else MISSING,
        "Public_Pull_Basis": public_basis,
        "fair_goal_margin": round(fair_goal_margin, 4),
        "fair_handicap": fair_handicap,
        "line_gap": line_gap,
        "Fair_Line_Status": "UNCALIBRATED_MARKET_PROXY",
        "Devig_Home": round(home, 6), "Devig_Draw": round(draw, 6), "Devig_Away": round(away, 6),
    }


def refine_intent(raw_tag: str, actual_line: float | None, fair: dict[str, Any]) -> dict[str, Any]:
    tag = canonical_intent(raw_tag)
    raw_side = intended_side(tag)
    fair_line = number(fair.get("fair_handicap"))
    if raw_side == MISSING or actual_line is None or fair_line is None:
        return {"Cup_Raw_Intent": tag, "Cup_Intent": tag, "Cup_Intent_Support": MISSING, "Cup_Intent_Reason": "INDEPENDENT_FAIR_LINE_OR_DIRECTION_MISSING"}
    if actual_line * fair_line < 0 and abs(actual_line - fair_line) >= 0.5:
        support = "CONFLICT"
    elif abs(actual_line) >= abs(fair_line) + 0.5:
        support = "RECEIVING"
    elif abs(fair_line) >= abs(actual_line) + 0.5:
        support = "GIVING"
    else:
        support = "NEUTRAL"
    if support == "CONFLICT" or (support in {"GIVING", "RECEIVING"} and support != raw_side):
        return {
            "Cup_Raw_Intent": tag, "Cup_Intent": "平衡盘/等待临场确认",
            "Cup_Intent_Support": support,
            "Cup_Intent_Reason": "MARKET_INTENT_CONFLICTS_WITH_MATCH_SPECIFIC_FAIR_LINE",
        }
    return {
        "Cup_Raw_Intent": tag, "Cup_Intent": tag, "Cup_Intent_Support": support,
        "Cup_Intent_Reason": "FAIR_LINE_ALIGNS_OR_IS_NEUTRAL",
    }


@dataclass
class Evidence:
    success: float = 0.0
    failure: float = 0.0
    pushes: int = 0
    pnl: float = 0.0

    @property
    def n(self) -> float:
        return self.success + self.failure

    def add(self, label: str, pnl: float | None) -> None:
        if label == "红":
            self.success += 1.0
        elif label == "红半":
            self.success += 0.5
            self.failure += 0.5
        elif label == "黑半":
            self.success += 0.5
            self.failure += 0.5
        elif label == "黑":
            self.failure += 1.0
        elif label == "走水":
            self.pushes += 1
        if pnl is not None:
            self.pnl += pnl


class HierarchicalCupEvidence:
    """L1 competition+intent+state -> L2 domain+intent -> L3 micro+intent -> L4 tag."""

    def __init__(self, rows: Iterable[dict[str, str]]):
        self.levels = [defaultdict(Evidence) for _ in range(4)]
        self.source_count = 0
        for row in rows:
            competition = clean(row.get("赛事"))
            label = clean(row.get("结算标签"))
            if not competition or label not in SETTLED:
                continue
            info = NORMALIZER.normalize(competition)
            domain = NORMALIZER.competition_domain(info)
            if not is_cup_domain(domain, info):
                continue
            intent = canonical_intent(row.get("倾向意图"))
            if intent == MISSING:
                continue
            state = clean(row.get("Cup_Match_State")) or MISSING
            pnl = number(row.get("实际盈亏Unit"))
            keys = (
                (info.competition_canonical, intent, state),
                (domain, intent),
                (info.micro_region, intent),
                (intent,),
            )
            for level, key in zip(self.levels, keys):
                level[key].add(label, pnl)
            self.source_count += 1

    @classmethod
    def latest(cls) -> tuple["HierarchicalCupEvidence", str]:
        paths = sorted(SHARED_LEDGER.glob("bettable_event_detail_*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not paths:
            return cls([]), MISSING
        with paths[0].open(encoding="utf-8-sig", newline="") as handle:
            return cls(csv.DictReader(handle)), str(paths[0])

    @staticmethod
    def _posterior(prior_mean: float, prior_strength: float, evidence: Evidence) -> tuple[float, float, float]:
        alpha = prior_mean * prior_strength + evidence.success
        beta = (1 - prior_mean) * prior_strength + evidence.failure
        mean = alpha / (alpha + beta)
        variance = alpha * beta / (((alpha + beta) ** 2) * (alpha + beta + 1))
        p10 = max(0.0, mean - 1.281552 * math.sqrt(variance))
        return mean, p10, alpha + beta

    def posterior(self, competition: str, intent: str, state: str) -> dict[str, Any]:
        info = NORMALIZER.normalize(competition)
        domain = NORMALIZER.competition_domain(info)
        tag = canonical_intent(intent)
        keys = (
            (info.competition_canonical, tag, state or MISSING),
            (domain, tag),
            (info.micro_region, tag),
            (tag,),
        )
        evidence = [level.get(key, Evidence()) for level, key in zip(self.levels, keys)]
        mean, p10, strength = self._posterior(0.5, 4.0, evidence[3])
        level_used = "L4_GLOBAL_TAG"
        if evidence[2].n:
            mean, p10, strength = self._posterior(mean, min(24.0, max(8.0, strength)), evidence[2])
            level_used = "L3_MICRO_REGION_INTENT"
        if evidence[1].n:
            mean, p10, strength = self._posterior(mean, min(28.0, max(10.0, strength)), evidence[1])
            level_used = "L2_DOMAIN_INTENT"
        if evidence[0].n:
            mean, p10, strength = self._posterior(mean, min(32.0, max(12.0, strength)), evidence[0])
            level_used = "L1_COMPETITION_INTENT_STATE"
        raw_n = evidence[0].n or evidence[1].n or evidence[2].n or evidence[3].n
        weight = min(0.35, 0.10 + raw_n / 200.0) if raw_n else 0.0
        return {
            "Cup_Bayes_Level": level_used,
            "Cup_Bayes_Posterior": round(mean, 6),
            "Cup_Bayes_P10": round(p10, 6),
            "Cup_Bayes_Local_N": round(evidence[0].n, 2),
            "Cup_Bayes_Domain_N": round(evidence[1].n, 2),
            "Cup_Bayes_Micro_N": round(evidence[2].n, 2),
            "Cup_Bayes_Global_N": round(evidence[3].n, 2),
            "Cup_Bayes_Weight": round(weight, 6),
            "Cup_Bayes_Status": "AVAILABLE" if raw_n else "MISSING",
        }


_MODEL: HierarchicalCupEvidence | None = None
_MODEL_SOURCE = MISSING


def model() -> HierarchicalCupEvidence:
    global _MODEL, _MODEL_SOURCE
    if _MODEL is None:
        _MODEL, _MODEL_SOURCE = HierarchicalCupEvidence.latest()
    return _MODEL


def enrich_cup_context(
    competition: str,
    odds_row: dict[str, Any],
    ledger_row: dict[str, Any],
    detail: dict[str, Any],
    raw_intent: str,
    *,
    kickoff_at: Any,
    decision_at: dt.datetime | None = None,
    precomputed_gateway: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision_at = decision_at or dt.datetime.now().astimezone()
    kickoff = parse_time(kickoff_at)
    gateway = precomputed_gateway or cup_match_state_gateway(
        competition, ledger_row, detail, decision_at=decision_at, kickoff_at=kickoff
    )
    if not gateway["Is_Cup_Context"]:
        return gateway
    fair = pull_and_fair_line(odds_row, ledger_row, gateway)
    raw_line = number(odds_row.get("ah_full_current_line_or_draw"))
    intent = refine_intent(raw_intent, raw_line, fair)
    bayes = model().posterior(competition, intent["Cup_Intent"], gateway["Cup_Match_State"])
    return {
        **gateway, **fair, **intent, **bayes,
        "Cup_Bayes_Source": _MODEL_SOURCE,
        "Cup_Decision_Logic": "COMPETITION_IS_FEATURE_NOT_COMMAND",
    }
