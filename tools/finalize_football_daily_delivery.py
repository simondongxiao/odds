"""Post-result overlays and versioned delivery artifacts; never infer decisions."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_football_update as daily
from write_dual_yesterday_performance import raw_result_map, settle_v3, settle_v4, summarize

ROOT = Path(r"D:\codex")
OUT = ROOT / "outputs/football_odds_trader"
LABEL = {"W": "红", "HW": "红半", "P": "走水", "HL": "黑半", "L": "黑"}


def csv_write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for row in rows for k in row)) or ["match_id"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def frozen_hash(rows):
    post = {"score", "result", "pnl_1u", "settlement", "settlement_status", "result_state", "result_source", "settlement_updated_at"}
    data = [{k: v for k, v in row.items() if k not in post} for row in rows]
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def main():
    run_dir = Path(sys.argv[1])
    manifest = daily.read_json(run_dir / "run_manifest.json", {})
    date = manifest["list_date"]
    yesterday = (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()
    # Decisions stay tied to raw_snapshot; an explicitly newer source may be
    # used only to reconcile post-match status, score, settlement and PnL.
    raw_path = Path(manifest.get("settlement_snapshot") or manifest["raw_snapshot"])
    override_path = OUT / "reviews" / "score_overrides_20260925.json"
    score_overrides = json.loads(override_path.read_text(encoding="utf-8")) if override_path.exists() else {}
    stamp = daily.now_cn().strftime("%Y%m%d_%H%M%S")
    backup = OUT / "backups" / f"delivery_results_{stamp}"
    backup.mkdir(parents=True)
    html_path = ROOT / "v3_legacy/outputs/football_odds_trader/dashboard/index.html"
    shutil.copy2(html_path, backup / "v3_index.html")
    html = html_path.read_text(encoding="utf-8")
    match = re.search(r"const cardsData = (.*?);\r?\n(?:cardsData\.forEach|const stats)", html, re.S)
    if not match:
        raise RuntimeError("V3 cards payload not found")
    cards = json.loads(match.group(1))
    # The legacy builder rebuilds the entire cards payload. For historical
    # list dates this is not an authority for pre-match fields: recover those
    # from the pre-run backup and overlay only result/status fields.
    pre_run_html = Path(manifest["backup"]) / "index.html"
    baseline_cards = []
    if pre_run_html.exists():
        baseline_text = pre_run_html.read_text(encoding="utf-8")
        baseline_match = re.search(r"const cardsData = (.*?);\r?\n(?:cardsData\.forEach|const stats)", baseline_text, re.S)
        if not baseline_match:
            raise RuntimeError("pre-run V3 cards payload not found")
        baseline_cards = json.loads(baseline_match.group(1))
    audit = {"run_id": manifest["run_id"], "dates": {}, "real_money": False}
    all_results = []
    for target in (yesterday, date):
        raw = raw_result_map(raw_path, target, score_overrides)
        bridge = daily.read_json(ROOT / f"bridge/v3_production/{target}.json", {})
        v3_results = {r["match_id"]: r for r in settle_v3(bridge.get("matches", []), raw)}
        for card in cards:
            if card.get("date") != target:
                continue
            result = v3_results.get(str(card.get("match_id")), {})
            observation = raw.get(str(card.get("match_id")), {})
            state = str(observation.get("state", ""))
            if state:
                label = "完场" if state == "-1" else "未开赛" if state == "0" else "进行中" if state in {"1", "2", "3", "4", "5"} else "状态待核"
                card.update(state=state, state_label=label, display_status=label, status=label)
            if result.get("result") in LABEL:
                card.update(score=result["score"], display_score=result["score"], state="-1",
                            state_label="完场", display_status="已结算", status="已结算",
                            result=LABEL[result["result"]], pnl=result["pnl_1u"],
                            result_source=result["result_source"])
                card["frozen_bettable_settlement"] = result["result"]
                card["frozen_bettable_pnl"] = result["pnl_1u"]
            elif state == "-1":
                card["status"] = "完场；未投注或结算待核"
                card["result"] = "未投注或结算待核"
                card["pnl"] = "不计"
            elif target < date and card.get("state") != "-1":
                card["display_status"] = "赛果待核"
                card["status"] = "赛果未匹配待人工核验"
        path = ROOT / f"v4/outputs/v4_decisions_{target}.json"
        payload = daily.read_json(path, {})
        rows = payload.get("matches", [])
        status_corrections = []
        if target == date:
            decision_at = dt.datetime.fromisoformat(manifest["run_at"].replace("Z", "+00:00"))
            for row in rows:
                source = raw.get(str(row.get("match_id", "")), {})
                if (not str(source.get("state", "") or "").strip()
                        and row.get("analysis_status") == "MISSING_DATA"
                        and "PREMATCH_STATUS_UNCONFIRMED" in (row.get("reason_codes") or [])):
                    status_corrections.append(str(row.get("match_id", "")))
                    continue
                if (not source or str(source.get("state", "") or "").strip()
                        or row.get("analysis_status") != "NOT_PREMATCH"
                        or row.get("grade") is not None or row.get("started_lock")):
                    continue
                kickoff = dt.datetime.fromisoformat(str(row.get("kickoff_at") or row.get("kickoff", "")).replace("Z", "+00:00"))
                if kickoff > decision_at:
                    row["analysis_status"] = "MISSING_DATA"
                    row["reason_codes"] = ["PREMATCH_STATUS_UNCONFIRMED"]
                    status_corrections.append(str(row.get("match_id", "")))
            if status_corrections:
                computed_statuses = {"EVALUATED", "FROZEN_PREMATCH_DECISION"}
                payload["summary"] = {
                    "total": len(rows),
                    "computed": sum(row.get("analysis_status") in computed_statuses for row in rows),
                    **{grade: sum(row.get("grade") == grade and row.get("analysis_status") in computed_statuses for row in rows) for grade in "ABCN"},
                    "neutral": sum(row.get("analysis_status") == "NEUTRAL" for row in rows),
                    "missing_data": sum(row.get("analysis_status") == "MISSING_DATA" for row in rows),
                    "insufficient_training": sum(row.get("analysis_status") == "INSUFFICIENT_TRAINING" for row in rows),
                    "not_prematch": sum(row.get("analysis_status") == "NOT_PREMATCH" and row.get("grade") is None for row in rows),
                    "errors": sum(row.get("analysis_status") == "ERROR" for row in rows),
                }
                manifest.setdefault("v4", {}).update({
                    "v4_computed": payload["summary"]["computed"],
                    "v4_A": payload["summary"]["A"], "v4_B": payload["summary"]["B"],
                    "v4_C": payload["summary"]["C"], "v4_N": payload["summary"]["N"],
                    "v4_neutral": payload["summary"]["neutral"],
                    "v4_missing": payload["summary"]["missing_data"],
                    "v4_not_prematch": payload["summary"]["not_prematch"],
                })
        before = frozen_hash(rows)
        shutil.copy2(path, backup / path.name)
        results = {r["match_id"]: r for r in settle_v4(rows, raw)}
        for row in rows:
            result = results.get(str(row.get("match_id")), {})
            if not result.get("score"):
                if target < date and row.get("result") not in LABEL:
                    row["settlement_status"] = "RESULT_PENDING_VERIFICATION"
                continue
            post = {key: result.get(key, "") for key in ("score", "result", "pnl_1u", "settlement_status", "result_state", "result_source")}
            if row.get("result") in LABEL and post["result"] not in LABEL:
                continue
            row.update(post)
            row["settlement_updated_at"] = daily.now_cn().isoformat()
            row["settlement"] = dict(post)
        assert frozen_hash(rows) == before, "Pre-match fields changed"
        daily.write_json(path, payload)
        daily.write_json(ROOT / f"v4/dashboard/data/{target}.json", payload)
        all_results.extend(dict(r, real_money=False) for r in results.values())
        audit["dates"][target] = {"grades": dict(Counter(r.get("grade") for r in rows)),
            "settled_all_grades": sum(r.get("result") in LABEL for r in rows),
            "prematch_hash": before, "prematch_unchanged": True,
            "unconfirmed_future_status_corrected": len(status_corrections)}
    post_match_fields = {
        "score", "display_score", "state", "state_label", "display_status",
        "status", "result", "pnl", "result_source",
        "frozen_bettable_settlement", "frozen_bettable_pnl",
    }
    current_by_key = {
        (str(card.get("date", "")), str(card.get("match_id", ""))): card
        for card in cards if card.get("match_id")
    }
    baseline_keys = set()
    restored_cards = []
    for old_card in baseline_cards:
        key = (str(old_card.get("date", "")), str(old_card.get("match_id", "")))
        baseline_keys.add(key)
        current_card = current_by_key.get(key)
        if not current_card:
            restored_cards.append(old_card)
            continue
        try:
            kickoff = dt.datetime.fromisoformat(str(old_card.get("kickoff_at") or old_card.get("kickoff") or "").replace("Z", "+00:00"))
            started = kickoff <= dt.datetime.fromisoformat(manifest["run_at"])
        except (TypeError, ValueError):
            started = False
        historical = key[0] < date
        # Historical, already-started, and same-list-date frozen selections are
        # immutable.  A later refresh may add a new selection before kickoff,
        # but it cannot delete or downgrade an earlier frozen V3 selection.
        frozen_selection = bool(old_card.get("frozen_bettable"))
        if historical or started or frozen_selection:
            merged_card = dict(old_card)
            for field in post_match_fields:
                value = current_card.get(field)
                if field in current_card and value not in (None, ""):
                    merged_card[field] = value
            restored_cards.append(merged_card)
        else:
            restored_cards.append(current_card)
    for card in cards:
        key = (str(card.get("date", "")), str(card.get("match_id", "")))
        if key in baseline_keys:
            continue
        if key[0] < date:
            # A row discovered only after its list date is retained for roster
            # coverage, but cannot acquire a retroactive pre-match pick.
            card = dict(card)
            card["frozen_bettable"] = False
            card["frozen_bettable_team"] = ""
            card["frozen_bettable_side"] = ""
            card["frozen_bettable_water"] = ""
            card["saved_skill_decision"] = None
            card["prematch_decision_status"] = "NO_FROZEN_PREMATCH_RECORD"
        restored_cards.append(card)
    cards = restored_cards
    audit["v3_prematch_restore"] = {
        "baseline_cards": len(baseline_cards),
        "restored_historical_cards": sum(str(card.get("date", "")) < date for card in cards),
        "historical_prematch_source": str(pre_run_html),
        "result_fields_only_overlay": True,
    }

    unique_cards = []
    seen = {}
    for card in cards:
        key = (card.get("date"), str(card.get("match_id")))
        if key[0] == date and key[1] and key in seen:
            previous = seen[key]
            fields = ("frozen_bettable", "frozen_bettable_action", "frozen_bettable_team", "frozen_bettable_side", "frozen_bettable_water")
            assert all(previous.get(f) == card.get(f) for f in fields), f"Conflicting V3 duplicate {key}"
            continue
        seen[key] = card
        unique_cards.append(card)
    html = html[:match.start(1)] + json.dumps(unique_cards, ensure_ascii=False) + html[match.end(1):]
    html_path.write_text(html, encoding="utf-8")
    family = OUT / "v4_shadow/daily_artifacts" / date / manifest["run_id"]
    current = daily.read_json(ROOT / f"v4/outputs/v4_decisions_{date}.json", {})
    run_at = dt.datetime.fromisoformat(manifest["run_at"].replace("Z", "+00:00"))
    decision_raw = Path(manifest["raw_snapshot"])
    merged = daily.merged_date_json(date, decision_raw, bridge, current, manifest["run_id"], run_at)
    daily.write_json(run_dir / "merged_dashboard_date.json", merged)
    daily.update_root_data(merged, daily.summary(bridge, current, int(manifest.get("roster_total", len(current.get("matches", []))))), manifest["run_id"], run_at)
    flat = [{k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in r.items()} | {"real_money": False} for r in current["matches"]]
    csv_write(family / "simulations.csv", flat)
    csv_write(family / "bettable_event_detail.csv", [r for r in flat if r.get("grade") in {"A", "B", "C"}])
    csv_write(family / "bettable_event_stats.csv", [{"list_date": date, "grade": grade, "n": sum(r.get("grade") == grade for r in flat), "real_money": False} for grade in "ABCN"])
    csv_write(family / "historical_settlement_audit.csv", all_results)
    daily.write_json(family / "frozen_decisions.json", current)
    grouped = []
    for target in (yesterday, date):
        for key in ("competition", "selected_side", "grade", "line"):
            subset = [r for r in all_results if r.get("list_date") == target and r.get("grade") in {"A", "B", "C"}]
            for value in sorted({str(r.get(key, "")) for r in subset}):
                summary = summarize([r for r in subset if str(r.get(key, "")) == value])
                grouped.append({"list_date": target, "group": key, "value": value, **{k: json.dumps(v) if isinstance(v, dict) else v for k, v in summary.items()}, "real_money": False})
    csv_write(family / "grouped_review.csv", grouped)
    (family / "daily_report.md").write_text("# V4 Shadow daily delivery\n\nSHADOW ONLY; real_money=false.\n\n" + json.dumps(manifest["v4"], ensure_ascii=False, indent=2) + "\n\nGrouped review is descriptive frozen-cohort settlement, not a new edge or model rule. Missing fundamentals/lineups/true flow remain unverified. ROI uses frozen 1U population; unresolved results are pending, not losses or pushes.\n", encoding="utf-8")
    audit["artifacts"] = str(family)
    daily.write_json(run_dir / "run_manifest.json", manifest)
    daily.write_json(run_dir / "result_overlay_acceptance.json", audit)
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
