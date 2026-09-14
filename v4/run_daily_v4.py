"""One-shot V4.2 daily runtime for the current independent shadow model."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from v4_dual_pipeline import load_raw, write_raw
from direction_contract import (
    MAPPING_VERSION as DIRECTION_VERSION,
    assert_side_identity,
    candidate_fields,
    derive_market_intent,
    map_intent,
    mirror_probs,
    parse_titan_market,
)

ROOT = Path(r"D:\codex")
TARGET_TZ = timezone(timedelta(hours=8))
STATES = ("W", "HW", "P", "HL", "L")
MODEL_ID = "v4-market-dirichlet-20260913"
MODEL_VERSION = "V4_DIRECTION_FIXED_R1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_dt(value: str) -> datetime:
    # Accept both the legacy Beijing-time text and ISO-8601 values emitted by
    # the refreshed Titan adapter.  Keep the model timezone fixed at UTC+8.
    normalized = str(value or "").strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is not None:
            return parsed.astimezone(TARGET_TZ)
        return parsed.replace(tzinfo=TARGET_TZ)
    except ValueError:
        pass
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", normalized)
    if not m:
        raise ValueError(value)
    return datetime(*map(int, m.groups()), tzinfo=TARGET_TZ)


def _first(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    return ""


def load_raw_csv(path: Path, list_date: str) -> list[dict]:
    """Adapt a refreshed Titan CSV into the existing V4 raw contract."""
    rows: list[dict] = []
    year = list_date[:4]
    roster_ids: set[str] = set()
    for roster_path in (
        ROOT / "v3_legacy" / "outputs" / "football_odds_trader" / "ledger" / "slate_rosters" / f"titan007_roster_{list_date.replace('-', '')}.json",
        ROOT / "outputs" / "football_odds_trader" / "ledger" / "slate_rosters" / f"titan007_roster_{list_date.replace('-', '')}.json",
    ):
        if not roster_path.exists():
            continue
        try:
            payload = json.loads(roster_path.read_text(encoding="utf-8"))
            roster_ids = {str(match_id) for match_id in (payload.get("matches") or {}).keys()}
        except (OSError, json.JSONDecodeError):
            roster_ids = set()
        if roster_ids:
            break
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for source in csv.DictReader(handle):
            source_date = str(source.get("list_date", "") or "").strip()
            match_id = str(source.get("match_id", "") or "").strip()
            if roster_ids and match_id not in roster_ids:
                continue
            if not roster_ids and source_date != list_date:
                continue
            home = _first(source, "home_cn", "home_team")
            away = _first(source, "away_cn", "away_team")
            bj_time = _first(source, "bj_time", "kickoff")
            if not home or not away or not bj_time:
                continue
            kickoff = parse_dt(bj_time if re.match(r"^\d{4}-", bj_time) else f"{year}-{bj_time}")
            hw = _first(source, "ah_full_current_home_or_over", "xml_ah_home_water")
            line = _first(source, "ah_full_current_line_or_draw", "xml_ah_line")
            aw = _first(source, "ah_full_current_away_or_under", "xml_ah_away_water")
            open_hw = _first(source, "ah_full_open_home_or_over")
            open_line = _first(source, "ah_full_open_line_or_draw", "initial_ah_hint")
            open_aw = _first(source, "ah_full_open_away_or_under")
            euro_home = _first(source, "euro_full_current_home_or_over", "xml_euro_home")
            euro_draw = _first(source, "euro_full_current_line_or_draw", "xml_euro_draw")
            euro_away = _first(source, "euro_full_current_away_or_under", "xml_euro_away")
            rows.append({
                "match_id": match_id, "list_date": list_date,
                "competition": _first(source, "league_cn", "competition"),
                "match": f"{home} vs {away}", "kickoff": kickoff.isoformat(),
                "state": str(source.get("state", "") or ""), "home_team": home, "away_team": away,
                "asian_raw": "/".join((hw, line, aw)) if hw and line and aw else "",
                "euro_raw": "/".join((euro_home, euro_draw, euro_away)) if euro_home and euro_draw and euro_away else "",
                "ah_full_current_home_or_over": hw, "ah_full_current_line_or_draw": line, "ah_full_current_away_or_under": aw,
                "ah_full_open_home_or_over": open_hw, "ah_full_open_line_or_draw": open_line, "ah_full_open_away_or_under": open_aw,
                "totals_raw": "/".join((_first(source, "total_full_current_line_or_draw"), _first(source, "total_full_current_home_or_over"), _first(source, "total_full_current_away_or_under"))),
                "ah_ok": bool(hw and line and aw), "euro_ok": bool(euro_home and euro_draw and euro_away),
                "totals_ok": bool(_first(source, "total_full_current_line_or_draw")),
                "price_source": "Titan007", "raw_source_path": str(path),
                "quote_at": str(source.get("snapshot_stamp", "") or source.get("latest_snapshot_stamp", "") or ""),
                "form_evidence": "", "h2h_evidence": "", "injury_evidence": "",
                "lineup_evidence": "", "motivation_evidence": "",
                "intent_raw": _first(source, "intent_raw", "intent_tag", "asian_intent"),
            })
    return rows


def line_bucket(value: float) -> str:
    return f"{round(abs(value) * 4) / 4:.2f}"


def allowed(signed: float) -> set[str]:
    q = round(signed * 4)
    halves = [q / 4, q / 4] if q % 2 == 0 else [(q - 1) / 4, (q + 1) / 4]
    radius = int(abs(signed)) + 3
    labels = {2: "W", 1: "HW", 0: "P", -1: "HL", -2: "L"}
    support = set()
    for margin in range(-radius, radius + 1):
        total = sum(1 if margin + h > 0 else -1 if margin + h < 0 else 0 for h in halves)
        support.add(labels[total])
    return support


def parse_market(row: dict) -> dict:
    # The old implementation used European favorite + -abs(line), which
    # silently converted every non-PK row into a giving candidate.  Keep the
    # legacy keys for render compatibility, but populate them from the Titan
    # signed-line contract and leave final side selection to intent mapping.
    parsed = parse_titan_market(row)
    if not parsed.get("valid"):
        return {"ok": False, **parsed}
    if parsed.get("pk"):
        return {"ok": True, **parsed, "bucket": "0.00"}
    return {
        "ok": True,
        **parsed,
        "selected_team": parsed["giving_team"],
        "selected_side": "giving",
        "selected_handicap_signed": parsed["raw_line"],
        "other_handicap_signed": -parsed["raw_line"],
        "water": parsed["giving_water"],
        "home_water": parsed["home_water"],
        "away_water": parsed["away_water"],
        "bucket": line_bucket(abs(parsed["raw_line"])),
    }


def fit_prior(training_path: Path, target_date: str, cutoff: datetime) -> tuple[dict, list[dict]]:
    counts: dict[str, dict[str, float]] = {"GLOBAL": {s: 1.0 for s in STATES}}
    manifest: list[dict] = []
    with training_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if str(row.get("list_date", "")) >= target_date:
                continue
            status = str(row.get("giving_side_result", "")).strip()
            if status not in STATES or str(row.get("verified", "")) not in {"1", "True", "true"}:
                continue
            try:
                line = float(row.get("giving_handicap", "0") or 0)
            except ValueError:
                continue
            bucket = line_bucket(line)
            counts.setdefault(bucket, {s: 1.0 for s in STATES})
            counts[bucket][status] += 1
            counts["GLOBAL"][status] += 1
            manifest.append({"match_id": row.get("match_id", ""), "list_date": row.get("list_date", ""),
                             "bucket": bucket, "status": status})
    return counts, manifest


def receiving_alpha(alpha: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """Mirror one market's giving-side posterior into receiving-side space."""
    return {
        bucket: {"W": values.get("L", 1.0), "HW": values.get("HL", 1.0),
                 "P": values.get("P", 1.0), "HL": values.get("HW", 1.0),
                 "L": values.get("W", 1.0)}
        for bucket, values in alpha.items()
    }


def posterior(alpha: dict[str, float], signed_line: float, water: float, seed: int) -> dict[str, float]:
    valid = allowed(signed_line)
    effective = {s: (alpha.get(s, 1.0) if s in valid else 0.0) for s in STATES}
    total = sum(effective.values())
    probs = {s: (effective[s] / total if total else 1 / len(valid) if s in valid else 0.0) for s in STATES}
    rng = random.Random(seed)
    evs = []
    vals = [s for s in STATES]
    for _ in range(5000):
        draws = {s: (rng.gammavariate(effective[s], 1.0) if effective[s] else 0.0) for s in vals}
        denom = sum(draws.values()) or 1.0
        p = {s: draws[s] / denom for s in vals}
        evs.append(water * p["W"] + water * 0.5 * p["HW"] - 0.5 * p["HL"] - p["L"])
    evs.sort()
    positive = sum(x > 0 for x in evs) / len(evs)
    return {"pW": probs["W"], "pHW": probs["HW"], "pP": probs["P"], "pHL": probs["HL"], "pL": probs["L"],
            "ev_mean": water * probs["W"] + water * 0.5 * probs["HW"] - 0.5 * probs["HL"] - probs["L"],
            "ev_p05": evs[249], "ev_p10": evs[499], "ev_p50": evs[2499], "ev_p90": evs[4499],
            "ev_p95": evs[4749], "p_ev_positive": positive}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-date", default="2026-09-13")
    parser.add_argument("--refresh-raw", action="store_true")
    parser.add_argument("--build-prior-if-missing", action="store_true")
    parser.add_argument("--publish-v4-only", action="store_true")
    parser.add_argument("--raw-csv", default="", help="Use a refreshed Titan CSV instead of the legacy HTML adapter.")
    args = parser.parse_args()
    now = datetime.now(TARGET_TZ)
    raw_rows = load_raw_csv(Path(args.raw_csv), args.list_date) if args.raw_csv else load_raw(args.list_date)
    raw_path = write_raw(raw_rows, args.list_date)
    training = ROOT / "outputs" / "football_odds_trader" / "research" / "v4_market_base_ready.csv"
    cutoff = datetime.fromisoformat(f"{args.list_date}T00:00:00+08:00")
    alpha, manifest = fit_prior(training, args.list_date, cutoff)
    model_dir = ROOT / "v4" / "models" / MODEL_ID
    prior_dir = ROOT / "v4" / "ledger" / "prior" / args.list_date
    model_dir.mkdir(parents=True, exist_ok=True); prior_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = model_dir / "training_manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["match_id", "list_date", "bucket", "status"]); w.writeheader(); w.writerows(manifest)
    prior_id = f"prior-{args.list_date}-v1"
    prior_path = prior_dir / f"{prior_id}.json"
    receiving = receiving_alpha(alpha)
    prior = {"prior_id": prior_id, "list_date": args.list_date, "history_cutoff": cutoff.isoformat(),
             "source": str(training), "source_hash": sha(training), "training_rows": len(manifest),
             "alpha": alpha, "side_alpha": {"giving": alpha, "receiving": receiving},
             "state_order": list(STATES), "direction_basis": "one market outcome; receiving is strict W/HW/P/HL/L mirror",
             "direction_version": DIRECTION_VERSION}
    prior_path.write_text(json.dumps(prior, ensure_ascii=False, indent=2), encoding="utf-8")
    model = {"model_id": MODEL_ID, "model_version": "V4_DIRECTION_FIXED_R1", "feature_schema_version": "v4-raw-market-v1", "kappa": 20,
             "bucket_alpha": {k: list(v.values()) for k, v in alpha.items()},
             "side_bucket_alpha": {"giving": {k: list(v.values()) for k, v in alpha.items()}, "receiving": {k: list(v.values()) for k, v in receiving.items()}},
             "training_rows": len(manifest),
             "training_manifest_sha256": sha(manifest_path), "history_cutoff": cutoff.isoformat(),
             "max_training_result_available_at": "2026-09-12T23:00:00+08:00", "max_training_list_date": max((x["list_date"] for x in manifest), default=""),
             "state_order": list(STATES), "raw_source": str(raw_path)}
    model_path = model_dir / "model.json"; model_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")

    decisions = []
    for row in raw_rows:
        kickoff = parse_dt(row["kickoff"])
        base = {"match_id": row["match_id"], "list_date": args.list_date, "kickoff": kickoff.isoformat(), "model_id": MODEL_ID,
                "prior_snapshot_id": prior_id, "decision_at": now.isoformat(), "market": {"snapshot_id": raw_path.stem, "source": "LEGACY_RAW_FIELD_EXPORT", "observed_at": now.isoformat(),
                "home_team": row["home_team"], "away_team": row["away_team"], "competition": row.get("competition", ""), "home_handicap_signed": None, "away_handicap_signed": None, "home_water_hk": None, "away_water_hk": None}}
        m = parse_market(row)
        if str(row.get("state", "0")) != "0" or kickoff <= now:
            base.update(competition=row.get("competition", ""), analysis_status="NOT_PREMATCH", grade=None, rank=None, reason_codes=["MATCH_NOT_PREMATCH"])
        elif not m.get("ok") or not row.get("ah_ok") or not row.get("euro_ok"):
            base.update(competition=row.get("competition", ""), analysis_status="MISSING_DATA", grade=None, rank=None, reason_codes=["REQUIRED_MARKET_INPUT_MISSING"])
        elif m.get("pk"):
            base.update(competition=row.get("competition", ""), analysis_status="NEUTRAL", grade=None, rank=None, reason_codes=["PK_NEUTRAL_NO_GIVING_SIDE"])
        else:
            raw_intent, intent_source = derive_market_intent(row, m)
            intent = map_intent(raw_intent, pk=False)
            side = intent["candidate_side"]
            if side == "unknown":
                base.update(competition=row.get("competition", ""), analysis_status="MISSING_DATA", grade=None, rank=None,
                            normalized_intent=intent["normalized_intent"], candidate_side="unknown",
                            reason_codes=["MISSING_INTENT", intent_source])
            elif side == "neutral":
                base.update(competition=row.get("competition", ""), analysis_status="NEUTRAL", grade=None, rank=None,
                            normalized_intent=intent["normalized_intent"], candidate_side="neutral",
                            reason_codes=["NEUTRAL_INTENT", intent_source])
            else:
                candidate = candidate_fields(m, side)
                valid_identity, identity_reason = assert_side_identity(m, candidate)
                if not valid_identity:
                    base.update(competition=row.get("competition", ""), analysis_status="ERROR", grade=None, rank=None,
                                normalized_intent=intent["normalized_intent"], candidate_side=side,
                                reason_codes=[identity_reason])
                else:
                    bucket = m["bucket"] if m["bucket"] in alpha else "GLOBAL"
                    side_prior = alpha[bucket] if side == "giving" else receiving[bucket]
                    selected_line = -abs(float(m["raw_line"])) if side == "giving" else abs(float(m["raw_line"]))
                    ev = posterior(side_prior, selected_line, float(candidate["candidate_water"]), int(row["match_id"]))
                    grade = "A" if ev["ev_mean"] > 0 and ev["ev_p10"] > 0 and ev["p_ev_positive"] >= .95 else "B" if ev["ev_mean"] > 0 and ev["p_ev_positive"] >= .85 else "C" if ev["ev_mean"] > 0 else "N"
                    decision_id = hashlib.sha256(f"{args.list_date}|{row['match_id']}|{prior_id}|{MODEL_ID}|{side}".encode()).hexdigest()[:20]
                    giving_ev = posterior(alpha[bucket], -abs(float(m["raw_line"])), float(m["giving_water"]), int(row["match_id"]) + 17)
                    receiving_ev = posterior(receiving[bucket], abs(float(m["raw_line"])), float(m["receiving_water"]), int(row["match_id"]) + 29)
                    base.update(competition=row.get("competition", ""), analysis_status="EVALUATED", grade=grade, rank=None, decision_id=decision_id,
                                normalized_intent=intent["normalized_intent"], intent_source=intent_source,
                                candidate_side=side, candidate_team=candidate["candidate_team"], candidate_water=candidate["candidate_water"],
                                candidate_handicap=candidate["candidate_handicap"], reverse_team=candidate["reverse_team"], reverse_side=candidate["reverse_side"], reverse_water=candidate["reverse_water"],
                                selected_team=candidate["candidate_team"], selected_side=side, selected_handicap_signed=selected_line, selected_water_hk=candidate["candidate_water"],
                                probabilities={s: ev["p"+s] for s in STATES}, ev_mean=ev["ev_mean"], ev_p05=ev["ev_p05"], ev_p10=ev["ev_p10"], ev_p50=ev["ev_p50"], ev_p90=ev["ev_p90"], ev_p95=ev["ev_p95"], p_ev_positive=ev["p_ev_positive"],
                                diagnostic_giving={"team": m["giving_team"], "water": m["giving_water"], "EV_mean": giving_ev["ev_mean"], "EV_p10": giving_ev["ev_p10"], "P_EV_gt_0": giving_ev["p_ev_positive"], "status": "DIAGNOSTIC_ONLY"},
                                diagnostic_receiving={"team": m["receiving_team"], "water": m["receiving_water"], "EV_mean": receiving_ev["ev_mean"], "EV_p10": receiving_ev["ev_p10"], "P_EV_gt_0": receiving_ev["p_ev_positive"], "status": "DIAGNOSTIC_ONLY"},
                                market={**base["market"], "home_handicap_signed": m["raw_line"], "away_handicap_signed": -m["raw_line"],
                                        "titan_home_handicap_signed": m["raw_line"], "titan_away_handicap_signed": -m["raw_line"], "home_water_hk": m["home_water"], "away_water_hk": m["away_water"],
                                        "giving_team": m["giving_team"], "receiving_team": m["receiving_team"], "giving_water": m["giving_water"], "receiving_water": m["receiving_water"], "side_identity": "Titan signed AH"},
                                direction_rule_version=DIRECTION_VERSION, reason_codes=[f"BUCKET_{bucket}", identity_reason, intent_source])
        decisions.append(base)
    computed_statuses = {"EVALUATED", "FROZEN_PREMATCH_DECISION"}
    summary = {"total": len(decisions), "computed": sum(x["analysis_status"] in computed_statuses for x in decisions), "A": sum(x.get("grade") == "A" and x["analysis_status"] in computed_statuses for x in decisions), "B": sum(x.get("grade") == "B" and x["analysis_status"] in computed_statuses for x in decisions), "C": sum(x.get("grade") == "C" and x["analysis_status"] in computed_statuses for x in decisions), "N": sum(x.get("grade") == "N" and x["analysis_status"] in computed_statuses for x in decisions), "neutral": sum(x["analysis_status"] == "NEUTRAL" for x in decisions), "missing_data": sum(x["analysis_status"] == "MISSING_DATA" for x in decisions), "insufficient_training": sum(x["analysis_status"] == "INSUFFICIENT_TRAINING" for x in decisions), "not_prematch": sum(x["analysis_status"] == "NOT_PREMATCH" and x.get("grade") is None for x in decisions), "errors": sum(x["analysis_status"] == "ERROR" for x in decisions)}
    out = {"list_date": args.list_date, "model_id": MODEL_ID, "prior_snapshot_id": prior_id, "real_money": False, "generated_at": now.isoformat(), "summary": summary, "matches": decisions}
    out_dir = ROOT / "v4" / "outputs"; out_dir.mkdir(parents=True, exist_ok=True)
    daily = out_dir / f"v4_decisions_{args.list_date}.json"; daily.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"v4_selected_{args.list_date}.csv").write_text("match_id,selected_team,selected_handicap_signed,selected_water_hk,grade,ev_mean,ev_p10,p_ev_positive\n" + "\n".join(",".join(str(x.get(k, "")) for k in ["match_id","selected_team","selected_handicap_signed","selected_water_hk","grade","ev_mean","ev_p10","p_ev_positive"]) for x in decisions if x.get("grade") in {"A","B"}), encoding="utf-8")
    print(json.dumps({"raw_total":len(raw_rows), "prior_training_rows":len(manifest), **summary, "daily":str(daily), "model":str(model_path), "prior":str(prior_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
