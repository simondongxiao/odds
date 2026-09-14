"""Build the V4 direction-fix audit and strict blind replay artifacts.

The historical input is prematch-only replay data.  This script never reads
settlement/result columns while building the prediction output; any later
settlement remains a separate operation.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"D:\codex")
sys.path.insert(0, str(ROOT / "v4"))
from direction_contract import (  # noqa: E402
    MAPPING_VERSION,
    assert_side_identity,
    candidate_fields,
    map_intent,
    mirror_probs,
)

OUT = ROOT / "outputs" / "football_odds_trader"
RESEARCH = OUT / "research"
AUDITS = OUT / "audits"
DAYS = [f"2026-09-{d:02d}" for d in range(7, 15)]
STATES = ("W", "HW", "P", "HL", "L")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def f(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def ev(probs: dict[str, float], water: float) -> float:
    return water * probs["W"] + water * 0.5 * probs["HW"] - 0.5 * probs["HL"] - probs["L"]


def grade(row: dict[str, float]) -> str:
    if row["EV_mean"] > 0 and row["EV_P10"] > 0 and row["P_EV_gt_0"] >= 0.95:
        return "A"
    if row["EV_mean"] > 0 and row["P_EV_gt_0"] >= 0.85:
        return "B"
    if row["EV_mean"] > 0:
        return "C"
    return "N"


def transform(row: dict[str, str]) -> dict:
    raw_line = f(row.get("home_handicap"))
    giving = row.get("home_team", "") if raw_line is not None and raw_line > 0 else row.get("away_team", "")
    receiving = row.get("away_team", "") if raw_line is not None and raw_line > 0 else row.get("home_team", "")
    market = {
        "valid": raw_line is not None and abs(raw_line) > 1e-9,
        "pk": raw_line is not None and abs(raw_line) <= 1e-9,
        "raw_line": raw_line,
        "giving_team": giving,
        "receiving_team": receiving,
        "giving_water": f(row.get("giving_water")),
        "receiving_water": f(row.get("receiving_water")),
        "giving_handicap": abs(raw_line or 0),
        "receiving_handicap": abs(raw_line or 0),
    }
    intent = map_intent(row.get("intent_canonical"), pk=market["pk"])
    candidate = candidate_fields(market, intent["candidate_side"])
    valid_identity, identity_reason = assert_side_identity(market, candidate)
    out = {
        "match_id": row.get("match_id", ""), "list_date": row.get("list_date", ""),
        "kickoff": row.get("kickoff", ""), "competition": row.get("competition", ""),
        "match": f"{row.get('home_team', '')} vs {row.get('away_team', '')}",
        "home_team": row.get("home_team", ""), "away_team": row.get("away_team", ""),
        "raw_home_handicap": raw_line, "giving_team": giving, "receiving_team": receiving,
        "giving_water": market["giving_water"], "receiving_water": market["receiving_water"],
        "intent_canonical": row.get("intent_canonical", ""), "normalized_intent": intent["normalized_intent"],
        "candidate_side": intent["candidate_side"], "candidate_team": candidate["candidate_team"],
        "candidate_water": candidate["candidate_water"], "reverse_team": candidate["reverse_team"],
        "mapping_rule_version": MAPPING_VERSION, "side_identity_status": identity_reason,
        "team_water_parity": bool(valid_identity), "source_path": row.get("source_path", ""),
    }
    if not valid_identity or intent["candidate_side"] not in {"giving", "receiving"}:
        out.update({"status": "NEUTRAL" if intent["candidate_side"] == "neutral" else "UNKNOWN_OR_INVALID"})
        return out
    probs_g = {s: f(row.get("p" + s)) or 0.0 for s in STATES}
    probs = probs_g if intent["candidate_side"] == "giving" else mirror_probs(probs_g)
    water = float(candidate["candidate_water"] or 0.0)
    mean_ev = ev(probs, water)
    # Historical replay carries the frozen distribution quantiles for the
    # original market.  Mirror the quantile sign convention for the receiving
    # diagnostic; only the mean/side identity is used for the architecture audit.
    p_positive = f(row.get("p_ev_positive")) or 0.0
    if intent["candidate_side"] == "receiving":
        p_positive = max(0.0, 1.0 - p_positive)
    p10 = f(row.get("ev_p10")) or 0.0
    if intent["candidate_side"] == "receiving":
        p10 = -p10
    metrics = {"EV_mean": mean_ev, "EV_P10": p10, "P_EV_gt_0": p_positive}
    out.update(metrics, grade=grade(metrics), status="COMPUTED")
    return out


def main() -> None:
    source = RESEARCH / "v4_market_replay_predictions_v4.csv"
    rows = read_csv(source)
    selected = [r for r in rows if r.get("list_date") in DAYS]
    fixed = [transform(r) for r in selected]
    fields = list(fixed[0]) if fixed else ["match_id"]
    fixed_path = RESEARCH / "v4_direction_fixed_blind_replay.csv"
    write_csv(fixed_path, fixed, fields)
    # A compact immutable prediction hash is kept separately from any result
    # files; no result/settlement column is copied into this output.
    digest = hashlib.sha256(fixed_path.read_bytes()).hexdigest()
    (RESEARCH / "v4_direction_fixed_blind_replay.sha256").write_text(digest + "  " + fixed_path.name + "\n", encoding="ascii")

    funnel = []
    for date in DAYS:
        part = [r for r in fixed if r["list_date"] == date]
        directional = [r for r in part if r["status"] == "COMPUTED"]
        c = Counter(r["candidate_side"] for r in directional)
        grades = Counter(r.get("grade", "") for r in directional)
        funnel.append({
            "list_date": date, "raw_valid_AH": sum(bool(r.get("raw_home_handicap")) for r in part),
            "neutral": sum(r["status"] == "NEUTRAL" for r in part), "unknown": sum(r["status"] == "UNKNOWN_OR_INVALID" for r in part),
            "directional": len(directional), "giving": c["giving"], "receiving": c["receiving"],
            "A_giving": sum(r.get("grade") == "A" and r["candidate_side"] == "giving" for r in directional),
            "A_receiving": sum(r.get("grade") == "A" and r["candidate_side"] == "receiving" for r in directional),
            "B_giving": sum(r.get("grade") == "B" and r["candidate_side"] == "giving" for r in directional),
            "B_receiving": sum(r.get("grade") == "B" and r["candidate_side"] == "receiving" for r in directional),
            "C_giving": sum(r.get("grade") == "C" and r["candidate_side"] == "giving" for r in directional),
            "C_receiving": sum(r.get("grade") == "C" and r["candidate_side"] == "receiving" for r in directional),
            "N_giving": sum(r.get("grade") == "N" and r["candidate_side"] == "giving" for r in directional),
            "N_receiving": sum(r.get("grade") == "N" and r["candidate_side"] == "receiving" for r in directional),
            "A": grades["A"], "B": grades["B"], "C": grades["C"], "N": grades["N"],
        })
    write_csv(AUDITS / "v4_direction_fix_funnel_20260907_20260914.csv", funnel, list(funnel[0]))

    intent_stats = []
    for date in DAYS:
        part = [r for r in fixed if r["list_date"] == date]
        for tag in sorted({r["normalized_intent"] for r in part}):
            sub = [r for r in part if r["normalized_intent"] == tag]
            intent_stats.append({"list_date": date, "intent": tag, "n": len(sub), "giving": sum(r["candidate_side"] == "giving" for r in sub), "receiving": sum(r["candidate_side"] == "receiving" for r in sub), "neutral": sum(r["status"] == "NEUTRAL" for r in sub), "unknown": sum(r["status"] == "UNKNOWN_OR_INVALID" for r in sub), "ABC": sum(r.get("grade") in {"A", "B", "C"} for r in sub), "N": sum(r.get("grade") == "N" for r in sub)})
    write_csv(AUDITS / "v4_direction_fix_intent.csv", intent_stats, list(intent_stats[0]))

    # Current-day canary uses the actual fixed runner output, after the direct
    # test.  The current output may still contain immutable started rows.
    current_path = ROOT / "v4" / "outputs" / "v4_decisions_2026-09-14.json"
    current = json.loads(current_path.read_text(encoding="utf-8")) if current_path.exists() else {}
    current_rows = current.get("matches", [])
    side_counts = Counter(r.get("candidate_side", "") for r in current_rows if r.get("analysis_status") in {"EVALUATED", "FROZEN_PREMATCH_DECISION"})
    random.seed(20260914)
    samples = [r for r in current_rows if r.get("candidate_side") == "giving"]
    sample_g = random.sample(samples, min(10, len(samples)))
    samples = [r for r in current_rows if r.get("candidate_side") == "receiving"]
    sample_r = random.sample(samples, min(10, len(samples)))
    canary = []
    for r in sample_g + sample_r:
        market = r.get("market", {})
        canary.append({"match_id": r.get("match_id"), "home_team": market.get("home_team"), "away_team": market.get("away_team"), "titan_home_handicap_signed": market.get("titan_home_handicap_signed", market.get("home_handicap_signed")), "giving_team": market.get("giving_team"), "receiving_team": market.get("receiving_team"), "candidate_side": r.get("candidate_side"), "candidate_team": r.get("candidate_team", r.get("selected_team")), "candidate_water": r.get("candidate_water", r.get("selected_water_hk")), "parity": "PASS" if r.get("candidate_team", r.get("selected_team")) in {market.get("giving_team"), market.get("receiving_team")} else "FAIL"})
    write_csv(AUDITS / "v4_direction_fix_canary_samples_20260914.csv", canary, list(canary[0]) if canary else ["match_id"])

    old_directional = 483
    old_giving = 483
    new_directional = [r for r in fixed if r["status"] == "COMPUTED"]
    new_giving = sum(r["candidate_side"] == "giving" for r in new_directional)
    new_receiving = sum(r["candidate_side"] == "receiving" for r in new_directional)
    report = [
        "# V4 Direction Architecture Fix R1", "",
        "- old model: `V4_GIVING_LEGACY`; new model: `V4_DIRECTION_FIXED_R1`.",
        "- scope: structural direction repair only; no ABC/kappa/Kelly/weekend/league tuning.", "",
        "## Root cause", "",
        "1. `v4/run_daily_v4.py:parse_market` used European favorite to choose the team and forced `selected_handicap_signed=-abs(raw_line)`. This erased Titan signed-side identity.",
        "2. The same function hard-coded `selected_side=giving`, so receiving intents could not create receiving candidates.",
        "3. The prior was trained only as a giving-side alpha table and was reused for the selected row; the fixed version mirrors one market outcome into receiving space rather than duplicating the match.",
        "4. Titan identity is now: raw home AH > 0 => home gives; raw home AH < 0 => away gives; PK is neutral.", "",
        "## Blind replay direction", "",
        f"- old strict-blind directional baseline: {old_directional}; giving {old_giving}; receiving 0 (legacy report baseline).",
        f"- new strict-blind rows 2026-09-07..14: {len(new_directional)}; giving {new_giving}; receiving {new_receiving}.",
        f"- mapping parity: {sum(1 for r in fixed if r['status'] == 'COMPUTED' and r['team_water_parity'])}/{len(new_directional)} = {sum(1 for r in new_directional if r['team_water_parity']) / len(new_directional) if new_directional else 0:.1%}.",
        "- historical prediction file is prematch-only and hashed separately; no result/settlement/PnL is used to create this direction output.", "",
        "## Current-day canary", "",
        f"- current list date: 2026-09-14; evaluated/frozen: {sum(side_counts.values())}; giving {side_counts['giving']}; receiving {side_counts['receiving']}; neutral {sum(r.get('analysis_status') == 'NEUTRAL' for r in current_rows)}.",
        f"- A/B/C/N: {Counter(r.get('grade') for r in current_rows if r.get('analysis_status') in {'EVALUATED','FROZEN_PREMATCH_DECISION'})}.",
        f"- sampled giving: {len(sample_g)}; sampled receiving: {len(sample_r)}; team/water parity sample: {'PASS' if all(r['parity'] == 'PASS' for r in canary) else 'FAIL'}.", "",
        "## Status", "",
        "- `real_money=false`; V4 remains Shadow/Research only.",
        "- V3 Production and its history are untouched.",
        "- Old giving-only artifacts remain under `v4/legacy_giving_only/` and are not overwritten by this report.",
    ]
    (AUDITS / "v4_direction_architecture_fix_r1.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"fixed_rows": len(fixed), "old_directional": old_directional, "old_giving": old_giving, "new_directional": len(new_directional), "new_giving": new_giving, "new_receiving": new_receiving, "current_giving": side_counts["giving"], "current_receiving": side_counts["receiving"], "prediction_sha256": digest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
