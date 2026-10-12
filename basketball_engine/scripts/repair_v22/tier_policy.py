"""League-tier controls used by the production pricing path.

The registry is deliberately fail-closed: unknown competitions are Tier 3.
"""
from __future__ import annotations

from pathlib import Path
import re

import yaml


DEFAULT = {
    "default_tier": "TIER_3",
    "tiers": {
        "TIER_1": {"residual_scale_multiplier": 1.0, "leagues": ["NBA", "WNBA"]},
        "TIER_2": {"residual_scale_multiplier": 1.15, "leagues": ["EUROLEAGUE", "CBA_REGULAR", "CBA_PLAYOFF"]},
        "TIER_3": {"residual_scale_multiplier": 1.45},
    },
    "model_family_policy": {},
}


def _token(value):
    return re.sub(r"[\s_\-()（）]", "", str(value or "")).casefold()


def registry():
    path = Path(__file__).resolve().parents[2] / "config" / "league_tier_registry.yaml"
    if not path.exists():
        return DEFAULT
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {**DEFAULT, **loaded, "tiers": {**DEFAULT["tiers"], **loaded.get("tiers", {})}}


def tier_for(event):
    data = registry()
    phase_text = " ".join(str(event.get(key) or "") for key in
                          ("league_family", "league", "competition_key", "season_phase")).casefold()
    # CBA preseason is one CBA identity for history joins, but remains Tier 3
    # for execution uncertainty.  Check phase before base-league aliases.
    if ('cba' in phase_text or '中国男子篮球职业联赛' in phase_text) and any(
            marker in phase_text for marker in ('季前','preseason','pre-season')):
        return "TIER_3", data["tiers"]["TIER_3"]
    candidates = {
        _token(event.get("league_family")), _token(event.get("league")),
        _token(event.get("competition_key")), _token(event.get("model_family")),
    }
    for name, spec in data.get("tiers", {}).items():
        names = {_token(item) for item in (spec.get("leagues", []) + spec.get("aliases", []))}
        if candidates.intersection(names):
            return name, spec
    default = data.get("default_tier", "TIER_3")
    return default, data["tiers"][default]


def evaluation_channel(event):
    data = registry()
    keys = [str(event.get("league_family") or ""), str(event.get("league") or ""), str(event.get("competition_key") or "")]
    for key in keys:
        policy = data.get("model_family_policy", {}).get(key)
        if policy:
            return policy.get("evaluation_channel", "LEAGUE_ONLY"), policy
    league = str(event.get("league") or "").upper()
    if "WNBA" in league or "女子职业篮球" in str(event.get("league") or ""):
        return "WNBA_ONLY", data.get("model_family_policy", {}).get("WNBA", {})
    if league == "NBA":
        return "NBA_ONLY", data.get("model_family_policy", {}).get("NBA", {})
    return "LEAGUE_ONLY", {}
