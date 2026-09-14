from __future__ import annotations

import csv
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(r"D:\codex")
V4_ROOT = ROOT / "v4"
STATES = ("W", "HW", "P", "HL", "L")
MIRROR = {"W": "L", "HW": "HL", "P": "P", "HL": "HW", "L": "W"}


def _v4_helpers():
    path = str(V4_ROOT)
    if path not in sys.path:
        sys.path.insert(0, path)
    import run_daily_v4  # type: ignore
    return run_daily_v4


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _posterior_probability(alpha: dict[str, Any], signed_line: float, water: float, seed: int) -> tuple[float, float, float]:
    """Return EV mean, EV P10 and P(EV>0) for one side using current prior."""
    helper = _v4_helpers()
    allowed = helper.allowed(signed_line)
    effective = {state: float(alpha.get(state, 1.0)) if state in allowed else 0.0 for state in STATES}
    total = sum(effective.values()) or 1.0
    mean_probs = {state: effective[state] / total for state in STATES}
    values: list[float] = []
    rng = random.Random(seed)
    for _ in range(5000):
        draws = {state: (rng.gammavariate(effective[state], 1.0) if effective[state] else 0.0) for state in STATES}
        denom = sum(draws.values()) or 1.0
        p = {state: draws[state] / denom for state in STATES}
        values.append(water * p["W"] + water * 0.5 * p["HW"] - 0.5 * p["HL"] - p["L"])
    values.sort()
    mean = water * mean_probs["W"] + water * 0.5 * mean_probs["HW"] - 0.5 * mean_probs["HL"] - mean_probs["L"]
    return mean, values[499], sum(value > 0 for value in values) / len(values)


def build_two_side_rows(v4_payload: dict[str, Any], prior_payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_alpha = (prior_payload or {}).get("alpha", {})
    side_alpha = (prior_payload or {}).get("side_alpha", {})
    giving_alpha = side_alpha.get("giving", raw_alpha)
    receiving_alpha = side_alpha.get("receiving", {})
    for item in v4_payload.get("matches", []):
        if item.get("analysis_status") not in {"EVALUATED", "FROZEN_PREMATCH_DECISION"}:
            continue
        market = item.get("market") or {}
        home, away = str(market.get("home_team", "")), str(market.get("away_team", ""))
        # New rows carry explicit Titan identity.  The fallback is only for
        # older diagnostic fixtures that predate the contract and is never
        # used by the production V4 runner.
        giving = str(market.get("giving_team") or item.get("giving_team") or item.get("selected_team") or "")
        if not home or not away or giving not in {home, away}:
            continue
        receiving = away if giving == home else home
        giving_water = _num(market.get("giving_water"))
        receiving_water = _num(market.get("receiving_water"))
        if giving_water is None:
            giving_water = _num(market.get("home_water_hk")) if giving == home else _num(market.get("away_water_hk"))
        if receiving_water is None:
            receiving_water = _num(market.get("away_water_hk")) if giving == home else _num(market.get("home_water_hk"))
        raw_signed = _num(market.get("titan_home_handicap_signed", market.get("home_handicap_signed")))
        if raw_signed is None:
            raw_signed = _num(item.get("selected_handicap_signed"))
        signed = abs(raw_signed) if raw_signed is not None else None
        if giving_water is None or receiving_water is None or signed is None:
            rows.append({"match_id": item.get("match_id", ""), "status": "REVERSE_PRICE_MISSING", "giving_team": giving, "receiving_team": receiving})
            continue
        bucket = f"{round(abs(signed) * 4) / 4:.2f}"
        g_alpha = giving_alpha.get(bucket) or giving_alpha.get("GLOBAL") or {state: 1.0 for state in STATES}
        r_alpha = receiving_alpha.get(bucket) or receiving_alpha.get("GLOBAL") or {state: 1.0 for state in STATES}
        giving_post = _posterior_probability(g_alpha, -abs(signed), giving_water, int(hashlib.sha256(f"{item.get('match_id')}|giving".encode()).hexdigest()[:8], 16))
        giving_probs = {state: _num(item.get("diagnostic_giving", {}).get("p" + state)) or 0.0 for state in STATES}
        if not any(giving_probs.values()):
            # Diagnostic probabilities are optional in old rows; use the
            # same side-aware prior rather than candidate identity inference.
            giving_probs = {state: 0.0 for state in STATES}
        receiving_probs = {state: giving_probs[MIRROR[state]] for state in STATES}
        receiving_mean, receiving_p10, receiving_positive = _posterior_probability(r_alpha, abs(signed), receiving_water, int(hashlib.sha256(f"{item.get('match_id')}|receiving".encode()).hexdigest()[:8], 16))
        giving_mean, giving_p10, giving_positive = giving_post
        rows.extend([
            {"match_id": item.get("match_id", ""), "list_date": v4_payload.get("list_date", ""), "side": "giving", "team": giving, "market_side": "让球方/上盘", "signed_handicap": abs(signed), "water": giving_water, "W": giving_probs["W"], "HW": giving_probs["HW"], "P": giving_probs["P"], "HL": giving_probs["HL"], "L": giving_probs["L"], "EV_mean": giving_mean, "EV_p10": giving_p10, "P_EV_gt_0": giving_positive, "mirror_status": "W↔L;HW↔HL;P↔P", "real_money": False, "diagnostic_only": True, "status": "COMPUTED"},
            {"match_id": item.get("match_id", ""), "list_date": v4_payload.get("list_date", ""), "side": "receiving", "team": receiving, "market_side": "受让方/下盘", "signed_handicap": abs(signed), "water": receiving_water, "W": receiving_probs["W"], "HW": receiving_probs["HW"], "P": receiving_probs["P"], "HL": receiving_probs["HL"], "L": receiving_probs["L"], "EV_mean": receiving_mean, "EV_p10": receiving_p10, "P_EV_gt_0": receiving_positive, "mirror_status": "W↔L;HW↔HL;P↔P", "real_money": False, "diagnostic_only": True, "status": "COMPUTED"},
        ])
    return rows


def write_two_side_audit(v4_path: Path, prior_path: Path | None, output_dir: Path, run_id: str) -> tuple[Path, Path, list[dict[str, Any]]]:
    payload = json.loads(v4_path.read_text(encoding="utf-8"))
    prior = json.loads(prior_path.read_text(encoding="utf-8")) if prior_path and prior_path.exists() else None
    rows = build_two_side_rows(payload, prior)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"v4_two_side_audit_{payload.get('list_date', '')}_{run_id}.csv"
    fields = ["match_id", "list_date", "side", "team", "market_side", "signed_handicap", "water", "W", "HW", "P", "HL", "L", "EV_mean", "EV_p10", "P_EV_gt_0", "mirror_status", "real_money", "diagnostic_only", "status"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows({key: row.get(key, "") for key in fields} for row in rows)
    json_path = output_dir / f"v4_two_side_audit_{payload.get('list_date', '')}_{run_id}.json"
    json_path.write_text(json.dumps({"list_date": payload.get("list_date"), "source_v4": str(v4_path), "real_money": False, "diagnostic_only": True, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return csv_path, json_path, rows
