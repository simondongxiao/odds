"""Restore missing NBA preseason rows from immutable first-write artifacts.

This is deliberately an append-only repair.  It does not rerun a model, create
new quotes, or replace an existing dashboard row.  The source capture and the
original decision/forecast files are reused so the restored rows remain
traceable to the original forward snapshot.
"""
from __future__ import annotations

import json
from pathlib import Path

from .common import atomic, load, stamp
from .model import quote_state
from .report import project_row


ROOT = Path(r"D:\codex\outputs\basketball_odds_trader")
FIRST_WRITE_RUN = "20261003T060547_a0bd91372b"
TARGETS = {
    "7m:1349411": {"date": "2026-10-04", "titan_id": "722203"},
    "7m:1360914": {"date": "2026-10-05", "titan_id": "742083"},
    "7m:1363622": {"date": "2026-10-05", "titan_id": "742084"},
}

TITAN_URL = "https://nba.titan007.com/analysis/{titan_id}.htm"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _first_write_decision(run_dir: Path, event_id: str):
    for path in sorted(run_dir.glob("decision_*.json")):
        item = load(path, {})
        if item.get("event_id") == event_id:
            return path, item
    raise FileNotFoundError(f"first-write decision not found: {event_id}")


def _final_history(cap: dict, titan_id: str):
    candidates = [
        h for h in cap.get("history", [])
        if str(h.get("source_event_id")) == titan_id
        and h.get("status") == "FINAL"
        and h.get("score1_full") is not None
        and h.get("score2_full") is not None
    ]
    if not candidates:
        # The 10/5 history capture is the stable fallback for the three
        # fixtures; it is still raw verified period-score evidence.
        fallback = ROOT / "raw" / "repair_v22" / "20261006T004023_6029bac6f7" / "capture.json"
        if fallback.exists():
            data = _json(fallback)
            candidates = [
                h for h in data.get("history", [])
                if str(h.get("source_event_id")) == titan_id
                and h.get("status") == "FINAL"
                and h.get("score1_full") is not None
                and h.get("score2_full") is not None
            ]
    if not candidates:
        return None
    return max(candidates, key=lambda h: str(h.get("known_final_at") or ""))


def _settlement_record(day: str, event_id: str, prediction_id: str):
    # The analytics record is an immutable read-only summary of the already
    # settled first-write ledger entry.  It is used only to restore the row's
    # existing result, never to manufacture a new paper entry.
    for file_day in (day, "2026-10-06", "2026-10-07", "2026-10-08"):
        path = ROOT / "dashboard_v2" / "data" / f"{file_day}.json"
        if not path.exists():
            continue
        doc = load(path, {})
        for record in (doc.get("analytics") or {}).get("records", []):
            if record.get("event_id") == event_id and record.get("prediction_id") == prediction_id:
                evaluation = record.get("evaluation") or {}
                if evaluation.get("outcome") in {"WIN", "LOSS", "PUSH"}:
                    return evaluation
    return None


def _titan_provisional_summary(event_id: str):
    """Return the immutable Titan Provisional directions for a restored event.

    These records are deliberately reported as a separate shadow ledger.  A
    provisional direction is not upgraded to a formal paper entry merely
    because the event later finished or because the current dashboard lost its
    alias.
    """
    root = ROOT / "ledger" / "titan_provisional"
    if not root.exists():
        return None
    records = []
    for path in root.rglob("*.json"):
        item = load(path, {})
        if item.get("event_id") != event_id:
            continue
        records.append(item)
    if not records:
        return None

    directions = []
    for market_type in ("SPREAD", "TOTAL"):
        market = [x for x in records if x.get("market_type") == market_type]
        if not market:
            continue
        first = min(market, key=lambda x: str(x.get("first_write_at") or ""))
        last = max(market, key=lambda x: str(x.get("first_write_at") or ""))
        directions.append({
            "market_type": market_type,
            "first_selected_side": first.get("selected_side"),
            "first_market_line": first.get("market_line"),
            "first_decimal_odds": first.get("decimal_odds"),
            "first_write_at": first.get("first_write_at"),
            "latest_selected_side": last.get("selected_side"),
            "latest_market_line": last.get("market_line"),
            "latest_decimal_odds": last.get("decimal_odds"),
            "latest_write_at": last.get("first_write_at"),
            "shadow_level": first.get("shadow_level"),
            "blocked_reason": list(first.get("blocked_reason") or []),
            "real_execution_allowed": bool(first.get("real_execution_allowed")),
            "strategy_return_eligible": bool(first.get("strategy_return_eligible")),
        })
    return {
        "status": "FOUND_BUT_BLOCKED_FORMAL_PAPER",
        "source": "TITAN_PROVISIONAL_LEDGER",
        "record_count": len(records),
        "directions": directions,
        "formal_paper_entry_created": False,
        "note": "历史方向已恢复展示；不升级为正式纸面单，不重复计入正式纸面P&L。",
    }


def restore():
    cap_path = ROOT / "raw" / "repair_v22" / FIRST_WRITE_RUN / "capture.json"
    cap = _json(cap_path)
    run_dir = ROOT / "ledger" / "repair_v22" / FIRST_WRITE_RUN
    by_event = {event.get("event_id"): event for event in cap.get("events", [])}
    by_quote = {}
    for quote in cap.get("quotes", []):
        by_quote.setdefault(quote.get("event_id"), []).append(quote)

    restored = []
    for event_id, meta in TARGETS.items():
        decision_path, decision = _first_write_decision(run_dir, event_id)
        forecast_path = run_dir / f"forecast_{decision['prediction_id']}.json"
        event = dict(by_event[event_id])
        pricing = _json(forecast_path)
        quotes = by_quote.get(event_id, [])
        states = [quote_state(q, event, cap["capture_finished_at"]) for q in quotes]
        row = project_row(event, pricing, quotes, decision, states, cap["mode"])
        row["historical_restore"] = {
            "status": "RESTORED_FROM_IMMUTABLE_FIRST_WRITE",
            "restored_at": stamp(),
            "source_capture_run_id": FIRST_WRITE_RUN,
            "source_capture_path": str(cap_path),
            "decision_path": str(decision_path),
            "prediction_id": decision.get("prediction_id"),
            "paper_entry_recreated": bool(decision.get("triggered")),
            "new_quote_created": False,
            "historical_first_write_rewritten": False,
        }

        titan_id = meta["titan_id"]
        final = _final_history(cap, titan_id)
        provisional = _titan_provisional_summary(event_id)
        if final:
            event["historical_final_score"] = {
                "score1": final.get("score1_full"),
                "score2": final.get("score2_full"),
                "score_rule": "INCLUDING_OT",
                "status": final.get("status"),
                "source_event_id": titan_id,
                "source_url": final.get("source_url"),
                "raw_path": final.get("raw_path"),
            }
            row["display"]["warnings"].append(
                f"已恢复历史赛果：{event.get('team1_name')} {final.get('score1_full')} - "
                f"{final.get('score2_full')} {event.get('team2_name')}；仅作历史核验，不新增下注。"
            )
        if provisional:
            event["historical_titan_provisional"] = provisional
            row["display"]["warnings"].append(
                "已恢复 Titan Provisional 历史方向；该方向首写时被阻塞，仍不计入正式纸面下注。"
            )

        if decision.get("triggered"):
            evaluation = _settlement_record(meta["date"], event_id, decision.get("prediction_id"))
            if evaluation:
                row["settlement"] = {
                    "archive_type": "FORWARD_NATIVE",
                    "event_id": event_id,
                    "prediction_id": decision.get("prediction_id"),
                    "outcome": evaluation.get("outcome"),
                    "paper_pnl": evaluation.get("paper_pnl"),
                    "paper_units": 1,
                    "score1": evaluation.get("score1"),
                    "score2": evaluation.get("score2"),
                    "score_rule": evaluation.get("score_rule", "INCLUDING_OT"),
                    "settled_at": final.get("known_final_at") if final else None,
                    "historical_restore": True,
                    "result_source_ref": final.get("raw_path") if final else None,
                    "result_source_url": final.get("source_url") if final else None,
                    "outcome_raw_sha256": final.get("raw_sha256") if final else None,
                }
        restored.append((meta["date"], row, meta["titan_id"]))

    audit = {"restored_at": stamp(), "source_capture_run_id": FIRST_WRITE_RUN, "rows": []}
    for day in sorted({day for day, _, _ in restored}):
        path = ROOT / "dashboard_v2" / "data" / f"{day}.json"
        doc = load(path, {})
        rows = list(doc.get("events", []))
        existing = {row.get("id") for row in rows if isinstance(row, dict)}
        added = []
        enriched = []
        for row_day, row, titan_id in restored:
            if row_day != day:
                continue
            if row.get("id") in existing:
                prior = next(item for item in rows if item.get("id") == row.get("id"))
                event = prior.setdefault("event", {})
                event.setdefault("original_first_write_league", event.get("league"))
                event.setdefault("original_first_write_competition_key", event.get("competition_key"))
                event["phase"] = "PRESEASON"
                event["league_display"] = "NBA季前"
                event["historical_titan_source"] = {
                    "source": "TITAN007",
                    "source_event_id": titan_id,
                    "competition_key": "NBA季前",
                    "source_url": TITAN_URL.format(titan_id=titan_id),
                    "continuity_match": "TEAM_PAIR_AND_TIP_TIME",
                }
                if final:
                    event["historical_final_score"] = {
                        "score1": final.get("score1_full"),
                        "score2": final.get("score2_full"),
                        "score_rule": "INCLUDING_OT",
                        "status": final.get("status"),
                        "source_event_id": titan_id,
                        "source_url": final.get("source_url"),
                        "raw_path": final.get("raw_path"),
                    }
                if provisional:
                    event["historical_titan_provisional"] = provisional
                prior["historical_restore"] = {
                    "status": "ALIAS_RESTORED_TO_EXISTING_FIRST_WRITE",
                    "restored_at": stamp(),
                    "source_event_id": titan_id,
                    "new_quote_created": False,
                    "historical_first_write_rewritten": False,
                }
                warning = "已恢复 Titan007 NBA 季前赛别名；沿用原 7M 首写，不新增下注。"
                if warning not in prior.setdefault("display", {}).setdefault("warnings", []):
                    prior["display"]["warnings"].append(warning)
                if final:
                    result_warning = (
                        f"已恢复历史赛果：{event.get('team1_name')} {final.get('score1_full')} - "
                        f"{final.get('score2_full')} {event.get('team2_name')}；仅作历史核验，不新增下注。"
                    )
                    if result_warning not in prior["display"]["warnings"]:
                        prior["display"]["warnings"].append(result_warning)
                if provisional:
                    provisional_warning = (
                        "已恢复 Titan Provisional 历史方向；该方向首写时被阻塞，仍不计入正式纸面下注。"
                    )
                    if provisional_warning not in prior["display"]["warnings"]:
                        prior["display"]["warnings"].append(provisional_warning)
                enriched.append(row["id"])
                continue
            rows.append(row)
            existing.add(row.get("id"))
            added.append(row)
        rows.sort(key=lambda item: ((item.get("event") or {}).get("tip_at") or "", item.get("id") or ""))
        if added or enriched:
            doc["events"] = rows
            doc["message"] = (doc.get("message", "") + " 已恢复历史 NBA 季前赛别名；沿用原首写，不新增信号、不改写预测或红黑。修复行：" + ", ".join(r["id"] for r in added + [next(x for x in rows if x.get("id") == i) for i in enriched])).strip()
            doc["historical_restore_audit"] = {
                "status": "APPENDED_OR_ALIAS_ENRICHED",
                "rows_added": [r["id"] for r in added],
                "rows_enriched": enriched,
                "source_capture_run_id": FIRST_WRITE_RUN,
                "does_not_change_live_funnel": True,
            }
            atomic(path, doc)
        audit["rows"].append({"date": day, "added": [r["id"] for r in added], "enriched": enriched, "already_present": not added and not enriched})

    atomic(ROOT / "audits" / "historical_nba_restore_20261008.json", audit)
    return audit


if __name__ == "__main__":
    print(json.dumps(restore(), ensure_ascii=False, indent=2))
