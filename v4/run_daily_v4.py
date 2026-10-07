"""Daily runtime for the single official V4 shadow model."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r"D:\codex")
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from raw_adapter import load_raw, write_raw
from direction_contract import (
    derive_market_intent,
    parse_titan_market,
)
from core_model import (
    CALIBRATION_STATUS,
    DIRECTION_RULE,
    FORWARD_STATUS,
    LOGIC_CHANGE_AT,
    MODEL_ID,
    MODEL_VERSION,
    PROBABILITY_VERSION,
    evaluate_match,
    stable_hash,
    write_runtime_diagnostics,
)

from football_titan_data import load_feature_snapshot

TARGET_TZ = timezone(timedelta(hours=8))
STATES = ("W", "HW", "P", "HL", "L")
V4_LOGIC_CHANGE_AT = LOGIC_CHANGE_AT


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


def quote_timestamp(value: str) -> str:
    """Canonicalize a source quote time; never use file mtime."""
    text = str(value or "").strip()
    if not text:
        return ""
    for candidate in (text, text.replace("_", "T")):
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=TARGET_TZ)
            return parsed.astimezone(TARGET_TZ).isoformat()
        except ValueError:
            pass
    for fmt in ("%Y%m%d_%H%M%S", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=TARGET_TZ).isoformat()
        except ValueError:
            continue
    return ""


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
                "euro_home": euro_home, "euro_draw": euro_draw, "euro_away": euro_away,
                "ah_full_current_home_or_over": hw, "ah_full_current_line_or_draw": line, "ah_full_current_away_or_under": aw,
                "ah_full_open_home_or_over": open_hw, "ah_full_open_line_or_draw": open_line, "ah_full_open_away_or_under": open_aw,
                "totals_raw": "/".join((_first(source, "total_full_current_line_or_draw"), _first(source, "total_full_current_home_or_over"), _first(source, "total_full_current_away_or_under"))),
                "ah_ok": bool(hw and line and aw), "euro_ok": bool(euro_home and euro_draw and euro_away),
                "totals_ok": bool(_first(source, "total_full_current_line_or_draw")),
                "price_source": "Titan007", "raw_source_path": str(path),
                "quote_at": quote_timestamp(str(source.get("snapshot_stamp", "") or source.get("latest_snapshot_stamp", "") or "")),
                "score": (f"{source.get('home_score')}-{source.get('away_score')}" if str(source.get("home_score", "")).strip() and str(source.get("away_score", "")).strip() else ""),
                "form_evidence": "", "h2h_evidence": "", "injury_evidence": "",
                "lineup_evidence": "", "motivation_evidence": "",
                "rotation_evidence": "", "public_pull": "",
                "match_nature": _first(source, "match_nature", "cup_format"),
                "aggregate_state": _first(source, "aggregate_state", "first_leg_score"),
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


def preserve_started_output(decisions: list[dict], daily: Path, now: datetime, list_date: str) -> list[dict]:
    """Keep prior same-date V4 decisions when a refresh emits only future rows."""
    if not daily.exists():
        return decisions
    try:
        previous = json.loads(daily.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return decisions
    if str(previous.get("list_date", "")) != str(list_date):
        return decisions

    old_map = {str(row.get("match_id", "")): row for row in previous.get("matches", [])}
    seen: set[str] = set()
    post_match_fields = (
        "score", "settlement", "settlement_label", "pnl", "status",
        "match_status", "result", "settlement_state", "settlement_status",
    )
    merged: list[dict] = []
    for row in decisions:
        match_id = str(row.get("match_id", ""))
        seen.add(match_id)
        old = old_map.get(match_id)
        kickoff = parse_dt(str(row.get("kickoff", "")))
        if not old or kickoff > now:
            merged.append(row)
            continue
        frozen = dict(old)
        frozen.update({
            key: row.get(key)
            for key in post_match_fields
            if key in row and row.get(key) not in (None, "")
        })
        if old.get("grade") is not None and old.get("ev_mean") is not None:
            frozen["analysis_status"] = "FROZEN_PREMATCH_DECISION"
        frozen["reason_codes"] = ["STARTED_DECISION_LOCKED"]
        frozen["started_lock"] = True
        merged.append(frozen)

    # Later runs are allowed to emit only not-yet-started rows.  Re-attach all
    # omitted started rows, including old A/B/C/N and neutral records.
    for match_id, old in old_map.items():
        if not match_id or match_id in seen:
            continue
        try:
            kickoff = parse_dt(str(old.get("kickoff", "")))
        except ValueError:
            continue
        if kickoff > now:
            continue
        retained = dict(old)
        if old.get("grade") is not None and old.get("ev_mean") is not None:
            retained["analysis_status"] = "FROZEN_PREMATCH_DECISION"
        retained["reason_codes"] = ["STARTED_DECISION_RETAINED"]
        retained["started_lock"] = True
        merged.append(retained)
    return merged


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


def core_code_hash() -> str:
    digest = hashlib.sha256()
    for path in (
        Path(__file__),
        ROOT / "v4" / "core_model.py",
        ROOT / "v4" / "direction_contract.py",
        ROOT / "v4" / "raw_adapter.py",
        ROOT / "v4" / "league_level_map.csv",
    ):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def append_decision_ledger(list_date: str, decision: dict, input_hash: str) -> dict:
    """Append a pre-match decision only when a material input/code hash changed."""
    directory = ROOT / "v4" / "ledger" / "decisions" / list_date
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{decision['match_id']}.jsonl"
    previous = None
    if path.exists():
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if lines:
            try:
                previous = json.loads(lines[-1])
            except json.JSONDecodeError:
                previous = None
    if previous and previous.get("input_hash") == input_hash:
        # Reuse the immutable decision identity on a pure rerun.
        for key in ("decision_id", "decision_at", "parent_decision_id"):
            if previous.get(key) not in (None, ""):
                decision[key] = previous[key]
        return decision
    parent = str(previous.get("decision_id", "")) if previous else ""
    decision["parent_decision_id"] = parent
    decision["input_hash"] = input_hash
    record = dict(decision)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return decision


def write_integrity_audit(decisions: list[dict], generated_at: str, code_hash: str) -> None:
    diagnostics = ROOT / "v4" / "diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)
    required = (
        "model_id", "decision_id", "odds_snapshot_id", "decision_at", "quote_at", "kickoff_at",
        "giving_team", "receiving_team", "normalized_intent", "reason_codes",
        "giving_probabilities", "receiving_probabilities", "ev_giving", "ev_receiving",
        "model_version", "probability_version",
    )
    bet_required = ("selected_team", "selected_side", "selected_handicap_signed", "selected_water_hk", "opposite_water_hk")
    evaluated = [row for row in decisions if row.get("analysis_status") == "EVALUATED"]
    missing = Counter()
    for row in evaluated:
        for field in required:
            if row.get(field) in (None, "", []):
                missing[field] += 1
        if str(row.get("final_decision") or "").startswith("BET_"):
            for field in bet_required:
                if row.get(field) in (None, "", []):
                    missing[field] += 1
    history = sorted((ROOT / "v4" / "outputs").glob("v4_decisions_*.json"))
    historical = [path for path in history if path.name < "v4_decisions_2026-09-30.json"]
    lines = [
        "# V4 Ledger Integrity Audit", "",
        f"- generated_at: {generated_at}",
        f"- V4_logic_change_at: {V4_LOGIC_CHANGE_AT}",
        f"- code_hash: `{code_hash}`",
        f"- evaluated_rows: {len(evaluated)}",
        f"- frozen_historical_files: {len(historical)}",
        "- historical_write_policy: Frozen Historical Decisions；本次运行不读取赛果生成赛前字段，不回写过去日期。",
        "- missing field counts: " + (", ".join(f"{key}={value}" for key, value in sorted(missing.items())) if missing else "0"),
        "",
        "历史行若当时从未生成某字段，保持 `HISTORICAL_FIELD_UNAVAILABLE`；禁止用赛果倒推补值。",
    ]
    (diagnostics / "V4_LEDGER_INTEGRITY_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-date", default="2026-09-13")
    parser.add_argument("--refresh-raw", action="store_true")
    parser.add_argument("--build-prior-if-missing", action="store_true")
    parser.add_argument("--publish-v4-only", action="store_true")
    parser.add_argument("--raw-csv", default="", help="Use a refreshed Titan CSV instead of the legacy HTML adapter.")
    args = parser.parse_args()
    now = datetime.now(TARGET_TZ)
    shared_snapshot = load_feature_snapshot()
    shared_matches = shared_snapshot.get("matches", {}) if isinstance(shared_snapshot, dict) else {}
    raw_rows = load_raw_csv(Path(args.raw_csv), args.list_date) if args.raw_csv else load_raw(args.list_date)
    raw_path = write_raw(raw_rows, args.list_date)
    training = ROOT / "outputs" / "football_odds_trader" / "research" / "v4_market_base_ready.csv"
    cutoff = datetime.fromisoformat(f"{args.list_date}T00:00:00+08:00")
    alpha, manifest = fit_prior(training, args.list_date, cutoff)
    model_dir = ROOT / "v4" / "models" / "V4"
    prior_dir = ROOT / "v4" / "ledger" / "prior" / args.list_date
    model_dir.mkdir(parents=True, exist_ok=True); prior_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = model_dir / "training_manifest.csv"
    prior_id = f"prior-{args.list_date}-v1"
    prior_path = prior_dir / f"{prior_id}.json"
    if prior_path.exists():
        frozen_prior = json.loads(prior_path.read_text(encoding="utf-8"))
        alpha = frozen_prior.get("alpha") or alpha
        manifest = []
    else:
        with manifest_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["match_id", "list_date", "bucket", "status"]); w.writeheader(); w.writerows(manifest)
        receiving = receiving_alpha(alpha)
        prior = {"prior_id": prior_id, "list_date": args.list_date, "history_cutoff": cutoff.isoformat(),
                 "source": str(training), "source_hash": sha(training), "training_rows": len(manifest),
                 "alpha": alpha, "side_alpha": {"giving": alpha, "receiving": receiving},
                 "state_order": list(STATES), "direction_basis": "bucket prior only; final side comes from match-specific dual EV",
                 "direction_version": DIRECTION_RULE}
        prior_path.write_text(json.dumps(prior, ensure_ascii=False, indent=2), encoding="utf-8")
    code_hash = core_code_hash()
    logic_manifest = {
        "model_id": MODEL_ID, "model_version": MODEL_VERSION, "V4_logic_change_at": V4_LOGIC_CHANGE_AT,
        "code_hash": code_hash, "calibration_status": CALIBRATION_STATUS, "forward_status": FORWARD_STATUS,
        "real_money": False, "direction_rule": DIRECTION_RULE,
    }
    (ROOT / "v4" / "V4_logic_change.json").write_text(json.dumps(logic_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    model = {**logic_manifest, "feature_schema_version": "v4-match-specific-market-quality",
             "bucket_role": "PRIOR_ONLY", "intent_role": "INTERPRETATION_ONLY", "stake_rule": "FIXED_1U",
             "training_rows": sum(max(0, int(round(sum(values.values()) - len(STATES)))) for key, values in alpha.items() if key != "GLOBAL"),
             "history_cutoff": cutoff.isoformat(), "state_order": list(STATES), "raw_source": str(raw_path)}
    model_path = model_dir / "model.json"; model_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")

    decisions = []
    for row in raw_rows:
        kickoff = parse_dt(row["kickoff"])
        quote_at = str(row.get("quote_at", "") or "")
        decision_at = now.isoformat()
        quote_dt = parse_dt(quote_at) if quote_at else None
        evidence_snapshot_id = stable_hash({key: row.get(key, "") for key in ("form_evidence", "injury_evidence", "lineup_evidence", "motivation_evidence", "rotation_evidence", "match_nature", "aggregate_state", "public_pull")})[:20]
        base = {"match_id": row["match_id"], "list_date": args.list_date, "kickoff": kickoff.isoformat(), "kickoff_at": kickoff.isoformat(), "model_id": MODEL_ID,
                "model_version": MODEL_VERSION, "side_mapping_version": DIRECTION_RULE, "direction_rule_version": DIRECTION_RULE,
                "V4_logic_change_at": V4_LOGIC_CHANGE_AT, "code_hash": code_hash,
                "probability_version": PROBABILITY_VERSION, "calibration_status": CALIBRATION_STATUS,
                "forward_status": FORWARD_STATUS, "real_money": False, "run_id": os.environ.get("FOOTBALL_RUN_ID", ""),
                "decision_at": decision_at, "quote_at": quote_at, "last_confirmed_at": quote_at,
                "quote_age_at_decision": round((now - quote_dt).total_seconds() / 3600, 3) if quote_dt else None,
                "hours_from_decision_to_kickoff": round((kickoff - now).total_seconds() / 3600, 3),
                "hours_from_last_refresh_to_kickoff": round((kickoff - quote_dt).total_seconds() / 3600, 3) if quote_dt else None,
                "is_morning_baseline": False, "is_latest_valid_prematch": False, "parent_decision_id": "",
                "monitoring_bucket": "MONITORING_BUCKET" if 4 <= kickoff.hour < 10 else "",
                "prior_snapshot_id": prior_id, "odds_snapshot_id": raw_path.stem, "evidence_snapshot_id": evidence_snapshot_id,
                "market": {"snapshot_id": raw_path.stem, "source": "Titan007", "observed_at": quote_at or now.isoformat(),
                "home_team": row["home_team"], "away_team": row["away_team"], "competition": row.get("competition", ""), "home_handicap_signed": None, "away_handicap_signed": None, "home_water_hk": None, "away_water_hk": None,
                "quote_at": quote_at, "last_confirmed_at": quote_at, "run_id": os.environ.get("FOOTBALL_RUN_ID", "")}}
        base.update({
            "data_integrity": "PASS" if row.get("match_id") and row.get("home_team") and row.get("away_team") and row.get("kickoff") else "FAIL",
            "evidence_coverage": {"identity": "AVAILABLE", "kickoff": "AVAILABLE", "asian_market": "MISSING", "euro_market": "MISSING", "ffl": "MISSING_OPTIONAL", "real_flow": "MISSING"},
            "model_support": "NOT_COMPUTED", "interpretation_status": "UNKNOWN", "decision_status": "UNAVAILABLE",
            "evidence_checklist": {"observed": [], "missing": ["asian_market", "euro_market"], "compatible_explanations": [], "unidentifiable": ["bookmaker_intent", "current_net_position"]},
        })
        m = parse_market(row)
        if str(row.get("state", "0")) != "0" or kickoff <= now:
            base.update(competition=row.get("competition", ""), analysis_status="NOT_PREMATCH", grade=None, rank=None,
                        final_decision="UNAVAILABLE", reason_codes=["MATCH_NOT_PREMATCH"], score=row.get("score", ""),
                        decision_status="NOT_PREMATCH", model_support="NOT_COMPUTED")
        elif not m.get("ok") or not row.get("ah_ok") or not row.get("euro_ok"):
            base.update(competition=row.get("competition", ""), analysis_status="MISSING_DATA", grade=None, rank=None,
                        final_decision="UNAVAILABLE", reason_codes=["REQUIRED_MARKET_INPUT_MISSING"],
                        decision_status="UNAVAILABLE_CORE_MARKET_INPUT", model_support="INSUFFICIENT_SUPPORT",
                        evidence_coverage={**base["evidence_coverage"], "asian_market": "AVAILABLE" if row.get("ah_ok") else "MISSING", "euro_market": "AVAILABLE" if row.get("euro_ok") else "MISSING"})
        elif m.get("pk"):
            base.update(competition=row.get("competition", ""), analysis_status="NEUTRAL", grade="N", rank=None,
                        final_decision="NO_BET", bet_unit=0.0, stake_rule="FIXED_1U",
                        reason_codes=["PK_NO_GIVING_RECEIVING_IDENTITY"], decision_status="NO_BET_NEUTRAL", model_support="MARKET_ONLY")
        else:
            raw_intent, intent_source = derive_market_intent(row, m)
            normalized_intent = raw_intent or "unknown"
            titan_context = shared_matches.get(str(row["match_id"]), {})
            model_row = {**row, "normalized_intent": normalized_intent, "titan_context": titan_context}
            bucket = m["bucket"] if m["bucket"] in alpha else "GLOBAL"
            result = evaluate_match(model_row, m, bucket_alpha=alpha.get(bucket))
            input_payload = {
                "code_hash": code_hash, "prior_snapshot_id": prior_id, "odds_snapshot_id": raw_path.stem,
                "match_id": row["match_id"], "line": m.get("raw_line"), "giving_water": m.get("giving_water"),
                "receiving_water": m.get("receiving_water"), "opening_line": m.get("opening_line"),
                "euro": [row.get("euro_home"), row.get("euro_draw"), row.get("euro_away")],
                "evidence_snapshot_id": evidence_snapshot_id, "competition": row.get("competition", ""),
                "titan_context_snapshot_id": shared_snapshot.get("snapshot_id"),
            }
            input_hash = stable_hash(input_payload)
            decision_id = hashlib.sha256(f"{args.list_date}|{row['match_id']}|{input_hash}".encode()).hexdigest()[:20]
            selected_side = result.get("selected_side", "")
            selected_water = result.get("selected_water_hk")
            opposite_water = m["receiving_water"] if selected_side == "giving" else m["giving_water"] if selected_side == "receiving" else None
            base.update(result)
            base.update(
                competition=row.get("competition", ""), analysis_status="EVALUATED", rank=None,
                decision_id=decision_id, normalized_intent=normalized_intent, intent_source=intent_source,
                giving_team=m["giving_team"], receiving_team=m["receiving_team"],
                giving_water_hk=m["giving_water"], receiving_water_hk=m["receiving_water"],
                candidate_side=selected_side, candidate_team=result.get("selected_team", ""),
                selected_team=result.get("selected_team", ""), selected_side=selected_side,
                selected_handicap_signed=result.get("selected_handicap_signed"), selected_water_hk=selected_water,
                opposite_water_hk=opposite_water, probabilities=result.get("selected_probabilities") or result.get("giving_probabilities"),
                ev_p05=None, ev_p10=None, ev_p50=result.get("ev_mean"), ev_p90=None, ev_p95=None, p_ev_positive=None,
                diagnostic_giving={"team": m["giving_team"], "water": m["giving_water"], "EV_mean": result["ev_giving"], "probabilities": result["giving_probabilities"], "status": "MATCH_SPECIFIC"},
                diagnostic_receiving={"team": m["receiving_team"], "water": m["receiving_water"], "EV_mean": result["ev_receiving"], "probabilities": result["receiving_probabilities"], "status": "MATCH_SPECIFIC"},
                titan_context=titan_context,
                market={**base["market"], "home_handicap_signed": m["raw_line"], "away_handicap_signed": -m["raw_line"],
                        "titan_home_handicap_signed": m["raw_line"], "titan_away_handicap_signed": -m["raw_line"],
                        "home_water_hk": m["home_water"], "away_water_hk": m["away_water"],
                        "giving_team": m["giving_team"], "receiving_team": m["receiving_team"],
                        "giving_water": m["giving_water"], "receiving_water": m["receiving_water"], "side_identity": "Titan signed AH"},
            )
            base = append_decision_ledger(args.list_date, base, input_hash)
        base["is_latest_valid_prematch"] = bool(base.get("analysis_status") in {"EVALUATED", "FROZEN_PREMATCH_DECISION"} and kickoff > now)
        decisions.append(base)
    computed_statuses = {"EVALUATED", "FROZEN_PREMATCH_DECISION"}
    summary = {"total": len(decisions), "computed": sum(x["analysis_status"] in computed_statuses for x in decisions), "A": sum(x.get("grade") == "A" and x["analysis_status"] in computed_statuses for x in decisions), "B": sum(x.get("grade") == "B" and x["analysis_status"] in computed_statuses for x in decisions), "C": sum(x.get("grade") == "C" and x["analysis_status"] in computed_statuses for x in decisions), "N": sum(x.get("grade") == "N" and x["analysis_status"] in computed_statuses for x in decisions), "giving": sum(x.get("final_decision") == "BET_GIVING" for x in decisions), "receiving": sum(x.get("final_decision") == "BET_RECEIVING" for x in decisions), "no_bet": sum(x.get("final_decision") == "NO_BET" and x.get("analysis_status") == "EVALUATED" for x in decisions), "neutral": sum(x["analysis_status"] == "NEUTRAL" for x in decisions), "missing_data": sum(x["analysis_status"] == "MISSING_DATA" for x in decisions), "insufficient_training": sum(x["analysis_status"] == "INSUFFICIENT_TRAINING" for x in decisions), "not_prematch": sum(x["analysis_status"] == "NOT_PREMATCH" and x.get("grade") is None for x in decisions), "errors": sum(x["analysis_status"] == "ERROR" for x in decisions), "core_evaluable_rate": round(sum(bool((x.get("expert_selector") or {}).get("core_evaluable")) for x in decisions if x.get("analysis_status") == "EVALUATED") / max(1, sum(x.get("analysis_status") == "EVALUATED" for x in decisions)), 6)}
    out = {"list_date": args.list_date, "model_id": MODEL_ID, "model_version": MODEL_VERSION, "prior_snapshot_id": prior_id, "real_money": False, "generated_at": now.isoformat(), "V4_logic_change_at": V4_LOGIC_CHANGE_AT, "code_hash": code_hash, "calibration_status": CALIBRATION_STATUS, "forward_status": FORWARD_STATUS, "summary": summary, "matches": decisions}
    out_dir = ROOT / "v4" / "outputs"; out_dir.mkdir(parents=True, exist_ok=True)
    daily = out_dir / f"v4_decisions_{args.list_date}.json"
    decisions = preserve_started_output(decisions, daily, now, args.list_date)
    summary = {"total": len(decisions), "computed": sum(x["analysis_status"] in computed_statuses for x in decisions), "A": sum(x.get("grade") == "A" and x["analysis_status"] in computed_statuses for x in decisions), "B": sum(x.get("grade") == "B" and x["analysis_status"] in computed_statuses for x in decisions), "C": sum(x.get("grade") == "C" and x["analysis_status"] in computed_statuses for x in decisions), "N": sum(x.get("grade") == "N" and x["analysis_status"] in computed_statuses for x in decisions), "giving": sum(x.get("final_decision") == "BET_GIVING" for x in decisions), "receiving": sum(x.get("final_decision") == "BET_RECEIVING" for x in decisions), "no_bet": sum(x.get("final_decision") == "NO_BET" and x.get("analysis_status") == "EVALUATED" for x in decisions), "neutral": sum(x["analysis_status"] == "NEUTRAL" for x in decisions), "missing_data": sum(x["analysis_status"] == "MISSING_DATA" for x in decisions), "insufficient_training": sum(x["analysis_status"] == "INSUFFICIENT_TRAINING" for x in decisions), "not_prematch": sum(x["analysis_status"] == "NOT_PREMATCH" and x.get("grade") is None for x in decisions), "errors": sum(x["analysis_status"] == "ERROR" for x in decisions), "core_evaluable_rate": round(sum(bool((x.get("expert_selector") or {}).get("core_evaluable")) for x in decisions if x.get("analysis_status") == "EVALUATED") / max(1, sum(x.get("analysis_status") == "EVALUATED" for x in decisions)), 6)}
    out["summary"] = summary; out["matches"] = decisions
    daily.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"v4_selected_{args.list_date}.csv").write_text("match_id,selected_team,selected_handicap_signed,selected_water_hk,grade,ev_mean,ev_p10,p_ev_positive\n" + "\n".join(",".join(str(x.get(k, "")) for k in ["match_id","selected_team","selected_handicap_signed","selected_water_hk","grade","ev_mean","ev_p10","p_ev_positive"]) for x in decisions if x.get("grade") in {"A","B"}), encoding="utf-8")
    diagnostics = ROOT / "v4" / "diagnostics"
    write_runtime_diagnostics(decisions, diagnostics, out)
    write_integrity_audit(decisions, now.isoformat(), code_hash)
    print(json.dumps({"raw_total":len(raw_rows), "prior_training_rows":model.get("training_rows", 0), **summary, "daily":str(daily), "model":str(model_path), "prior":str(prior_path), "diagnostics":str(diagnostics)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
