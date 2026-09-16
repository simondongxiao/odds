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
    raw_path = Path(manifest["raw_snapshot"])
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
    audit = {"run_id": manifest["run_id"], "dates": {}, "real_money": False}
    all_results = []
    for target in (yesterday, date):
        raw = raw_result_map(raw_path, target)
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
            "prematch_hash": before, "prematch_unchanged": True}
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
    daily.write_json(run_dir / "result_overlay_acceptance.json", audit)
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
