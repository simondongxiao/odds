"""V4.2 independent shadow pipeline.

Only raw fixture/market/evidence fields are accepted as input.  No V3
decision, freeze, tag statistic, risk state, Kelly or bettable list is read.
"""
from __future__ import annotations

import json
import re
import csv
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(r"D:\codex")
LEGACY_HTML = ROOT / "v3_legacy" / "dashboard" / "index.html"
from direction_contract import parse_titan_market


def load_raw(list_date: str) -> list[dict[str, Any]]:
    text = LEGACY_HTML.read_text(encoding="utf-8")
    match = re.search(r"const cardsData = (.*?);\s*\n", text, re.S)
    if not match:
        raise RuntimeError("cardsData not found")
    cards = json.loads(match.group(1).rstrip(";"))
    rows: list[dict[str, Any]] = []
    for card in cards:
        if card.get("date") != list_date:
            continue
        rows.append({
            "match_id": str(card.get("match_id", "")),
            "list_date": list_date,
            "competition": card.get("league", ""),
            "match": card.get("match", ""),
            "kickoff": card.get("time", ""),
            "state": card.get("state", ""),
            "home_team": str(card.get("match", "")).split(" vs ", 1)[0],
            "away_team": str(card.get("match", "")).split(" vs ", 1)[-1],
            "asian_raw": card.get("ah", ""),
            "euro_raw": card.get("euro", ""),
            "totals_raw": card.get("total", ""),
            "ah_ok": bool(card.get("ah_ok")),
            "euro_ok": bool(card.get("euro_ok")),
            "totals_ok": bool(card.get("total_ok")),
            "price_source": card.get("price_source", ""),
            "form_evidence": card.get("form_source", ""),
            "h2h_evidence": card.get("h2h_source", ""),
            "injury_evidence": card.get("injury", ""),
            "lineup_evidence": card.get("lineup", ""),
            "motivation_evidence": card.get("motivation_source", ""),
        })
    return rows


def write_raw(rows: list[dict[str, Any]], list_date: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / "raw" / "shared" / list_date / stamp / "snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"list_date": list_date, "snapshot_id": stamp,
                                "source": "LEGACY_RAW_FIELD_EXPORT", "rows": rows},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_v4(rows: list[dict[str, Any]], list_date: str, raw_path: Path) -> dict[str, Any]:
    training = ROOT / "outputs" / "football_odds_trader" / "research" / "v4_market_base_ready.csv"
    prior, prior_rows = build_prior(training)
    out: list[dict[str, Any]] = []
    for row in rows:
        eligible = bool(row.get("ah_ok") and row.get("euro_ok"))
        parsed = parse_market(row)
        post = posterior_ev(prior.get(parsed["bucket"], prior.get("GLOBAL", empty_prior())), parsed["water"])
        directional = eligible and parsed["candidate_team"] and parsed["line_mag"] > 0
        if not directional:
            post = None
        grade = grade_posterior(post) if post else None
        out.append({
            "match_id": row["match_id"],
            "status": "COMPUTED" if eligible else "MISSING",
            "candidate_team": parsed["candidate_team"] if directional else "",
            "candidate_side": parsed["candidate_side"] if directional else "neutral" if eligible else None,
            "line": parsed["line"] if eligible else None,
            "water": parsed["water"] if directional else None,
            "EV_mean": post["ev_mean"] if post else None,
            "EV_p10": post["ev_p10"] if post else None,
            "P_EV_gt_0": post["p_ev_gt_0"] if post else None,
            "grade": grade,
            "daily_rank": None,
            "reverse_status": "INDEPENDENT_GATE_PENDING" if eligible else None,
            "real_money": False,
            "missing_reason": None if eligible else "RAW_MARKET_INPUT_INCOMPLETE",
            "rule_version": "v4.2-independent-shadow",
            "raw_snapshot": str(raw_path),
        })
    computed = [x for x in out if x["status"] == "COMPUTED"]
    result = {
        "list_date": list_date,
        "source": "V4_INDEPENDENT_RAW_PIPELINE",
        "real_money": False,
        "raw_snapshot": str(raw_path),
        "computed_count": len(computed),
        "missing_count": len(out) - len(computed),
        "neutral_count": sum(x["candidate_side"] == "neutral" for x in computed),
        "A_count": sum(x["grade"] == "A" for x in computed),
        "B_count": sum(x["grade"] == "B" for x in computed),
        "C_count": sum(x["grade"] == "C" for x in computed),
        "N_count": sum(x["grade"] == "N" for x in computed),
        "prior_training_rows": prior_rows,
        "matches": out,
    }
    return result


def empty_prior() -> dict[str, list[int]]:
    return {"W": [1, 1], "HW": [1, 1], "P": [1, 1], "HL": [1, 1], "L": [1, 1]}


def build_prior(path: Path) -> tuple[dict[str, dict[str, list[int]]], int]:
    prior: dict[str, dict[str, list[int]]] = {"GLOBAL": empty_prior()}
    n = 0
    if not path.exists():
        return prior, n
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            status = str(row.get("giving_side_result", "")).strip()
            if status not in {"W", "HW", "P", "HL", "L"}:
                continue
            n += 1
            line = abs(float(row.get("giving_handicap", "0") or 0))
            bucket = line_bucket(line)
            prior.setdefault(bucket, empty_prior())[status][0] += 1
            prior["GLOBAL"][status][0] += 1
    return prior, n


def line_bucket(value: float) -> str:
    return f"{round(abs(value) * 4) / 4:.2f}"


def parse_market(row: dict[str, Any]) -> dict[str, Any]:
    # This compatibility helper no longer infers identity from Euro favorite.
    # The refreshed Titan adapter supplies explicit signed fields to the main
    # runner.  Legacy HTML-only rows without that contract are unknown.
    if row.get("ah_full_current_line_or_draw") or row.get("xml_ah_line"):
        parsed = parse_titan_market(row)
        if not parsed.get("valid"):
            return {"candidate_team": "", "candidate_side": "unknown", "line": "", "line_mag": 0, "water": 0, "bucket": "GLOBAL"}
        side = "neutral" if parsed.get("pk") else "unknown"
        return {"candidate_team": "", "candidate_side": side, "line": parsed.get("raw_line", ""), "line_mag": abs(parsed.get("raw_line", 0)), "water": 0, "bucket": line_bucket(abs(parsed.get("raw_line", 0))) if parsed.get("raw_line") else "GLOBAL"}
    return {"candidate_team": "", "candidate_side": "unknown", "line": "", "line_mag": 0, "water": 0, "bucket": "GLOBAL"}


def posterior_ev(prior: dict[str, list[int]], water: float) -> dict[str, float]:
    rng = random.Random(20260913)
    draws = []
    keys = ["W", "HW", "P", "HL", "L"]
    weights = {"W": 1 + water, "HW": water / 2, "P": 0, "HL": -0.5, "L": -1}
    for _ in range(2000):
        vals = [rng.gammavariate(max(1.0, float(prior.get(k, [1, 1])[0])), 1.0) for k in keys]
        total = sum(vals)
        draws.append(sum((vals[i] / total) * weights[keys[i]] for i in range(len(keys))))
    draws.sort()
    return {"ev_mean": sum(draws) / len(draws), "ev_p10": draws[199],
            "p_ev_gt_0": sum(x > 0 for x in draws) / len(draws)}


def grade_posterior(post: dict[str, float]) -> str:
    if post["p_ev_gt_0"] >= 0.80 and post["ev_p10"] > 0:
        return "A"
    if post["p_ev_gt_0"] >= 0.60 and post["ev_mean"] > 0:
        return "B"
    if post["ev_mean"] > 0:
        return "C"
    return "N"


def run(list_date: str = "2026-09-13") -> dict[str, Any]:
    rows = load_raw(list_date)
    raw_path = write_raw(rows, list_date)
    result = run_v4(rows, list_date, raw_path)
    out_path = ROOT / "outputs" / "v4" / f"{list_date}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    import sys
    result = run(sys.argv[1] if len(sys.argv) > 1 else "2026-09-13")
    print(json.dumps({k: result[k] for k in ("list_date", "computed_count", "neutral_count", "A_count", "B_count", "C_count", "N_count", "missing_count")}, ensure_ascii=False))
