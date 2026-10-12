"""Possession evidence normalization with fail-safe box-score derivation.

This module never reads files.  It only normalizes evidence already loaded for
the current event, so a missing box-score field cannot abort the daily run.
"""
from __future__ import annotations

import math


REQUIRED_BOX_FIELDS = ("FGA", "FTA", "ORB", "TOV")


def _number(row, name):
    if not isinstance(row, dict):
        return None
    aliases = {
        "FGA": ("FGA", "fga", "field_goal_attempts"),
        "FTA": ("FTA", "fta", "free_throw_attempts"),
        "ORB": ("ORB", "orb", "offensive_rebounds"),
        "TOV": ("TOV", "tov", "turnovers"),
    }
    for key in aliases[name]:
        value = row.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) >= 0:
            return float(value)
    return None


def derive_possessions_from_box_score(rows, league_pace_prior=None):
    """Return Level B only when both teams have every required source field.

    Missing ORB/TOV (or another formula input) is an explicit downgrade.  A
    verified league prior permits Level C; otherwise the result is Level D.
    No direct dictionary indexing is used, so malformed rows cannot raise a
    KeyError and take down the event pipeline.
    """
    if isinstance(rows, dict):
        rows = [v for v in rows.values() if isinstance(v, dict)]
    rows = rows if isinstance(rows, list) else []
    parsed, missing = [], []
    for index, row in enumerate(rows[:2]):
        values = {name: _number(row, name) for name in REQUIRED_BOX_FIELDS}
        absent = [name for name, value in values.items() if value is None]
        if absent:
            missing.extend(f"TEAM_{index + 1}_{name}_MISSING" for name in absent)
            continue
        parsed.append(values)
    if len(parsed) == 2:
        team_values = [x["FGA"] + 0.44 * x["FTA"] - x["ORB"] + x["TOV"] for x in parsed]
        if all(math.isfinite(value) and value > 0 for value in team_values):
            return {
                "possessions_level": "LEVEL_B", "pace_source": "DERIVED_BOX_SCORE",
                "possessions_verified": True, "possessions_per_game": sum(team_values) / 2,
                "team_possessions_estimates": team_values, "missing_fields": [],
                "formula": "FGA + 0.44 * FTA - ORB + TOV",
            }
        missing.append("DERIVED_POSSESSIONS_INVALID")
    elif len(rows) < 2:
        missing.append("TWO_TEAM_BOX_SCORE_REQUIRED")
    prior = league_pace_prior if isinstance(league_pace_prior, (int, float)) and league_pace_prior > 0 else None
    return {
        "possessions_level": "LEVEL_C" if prior is not None else "LEVEL_D",
        "pace_source": "ESTIMATED" if prior is not None else "UNAVAILABLE",
        "possessions_verified": False, "possessions_per_game": float(prior) if prior is not None else None,
        "team_possessions_estimates": [], "missing_fields": list(dict.fromkeys(missing)),
        "formula": "FGA + 0.44 * FTA - ORB + TOV",
    }


def enrich_possessions_context(context):
    """Normalize direct/derived/fallback pace evidence in a copied mapping."""
    out = dict(context or {})
    direct = out.get("possessions_per_game")
    if out.get("possessions_verified") and isinstance(direct, (int, float)) and direct > 0:
        out.update(possessions_level="LEVEL_A", pace_source="DIRECT")
        return out
    rows = out.get("box_score_teams") or out.get("box_scores") or out.get("box_score")
    if rows is not None or out.get("possessions_level") == "LEVEL_B":
        derived = derive_possessions_from_box_score(rows, out.get("league_pace_prior"))
        out.update(derived)
        return out
    level = str(out.get("possessions_level") or "")
    if level == "LEVEL_C" and isinstance(out.get("league_pace_prior"), (int, float)):
        out.setdefault("pace_source", "ESTIMATED")
    elif level not in ("LEVEL_A", "LEVEL_C"):
        out.update(possessions_level="LEVEL_D", pace_source="UNAVAILABLE", possessions_verified=False)
    return out
