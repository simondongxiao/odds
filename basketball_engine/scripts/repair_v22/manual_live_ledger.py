"""User-authorized unified formal accounting for manual basketball signals.

Source ledgers stay physically separate and immutable. This module only builds
an auditable formal manual-live index from Qualified, Provisional, and Titan
Provisional frozen first-writes. Until a manual fill is supplied, settlement is
one unit at the frozen signal price, not a broker-confirmed transaction.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .common import atomic, load, stamp


POLICY_ID = "USER_AUTHORIZED_FORMAL_MANUAL_LEDGER_2026-10-08"
INCLUDED_LAYERS = ("QUALIFIED", "PROVISIONAL", "TITAN_PROVISIONAL")
PRIORITY = {"QUALIFIED": 0, "PROVISIONAL": 1, "TITAN_PROVISIONAL": 2}


def _continuity_key(event, market_type):
    event = event or {}
    def clean(value):
        value = re.sub(r"\[[^\]]*\]", "", str(value or ""))
        return re.sub(r"\s+", "", value).casefold()
    teams = tuple(sorted(filter(None, (clean(event.get("team1_name")), clean(event.get("team2_name"))))))
    if len(teams) != 2:
        teams = tuple(sorted(filter(None, (str(event.get("team1_id") or ""), str(event.get("team2_id") or "")))))
    return teams, str(event.get("tip_at") or event.get("tip_time_bj") or "")[:19], market_type


def _settlement(value, pnl_key):
    value = value or {}
    return {"outcome": value.get("outcome", "PENDING"), "formal_manual_pnl": value.get(pnl_key),
            "settled_at": value.get("settled_at"), "score1": value.get("score1"),
            "score2": value.get("score2"), "settlement_source": pnl_key if value else None}


def _qualified_records(root):
    settlements = {path.stem: load(path, {}) for path in (root / "ledger" / "repair_v22_settlements").glob("*.json")}
    for path in sorted((root / "ledger" / "repair_v22").glob("*/decision_*.json")):
        decision = load(path, {}); pid = decision.get("prediction_id")
        if decision.get("archive_type") != "FORWARD_NATIVE" or not decision.get("triggered") or not pid:
            continue
        event = (load(path.with_name("input_" + pid + ".json"), {}).get("event") or {})
        if not event:
            continue
        market_decisions = decision.get("market_decisions") or {}
        # New records are one physical record per canonical event + market.
        # Keep the legacy fallback so historical single-market decisions remain
        # readable and are not rewritten in place.
        if market_decisions:
            candidates = [(market, item) for market, item in market_decisions.items()
                          if isinstance(item, dict) and item.get("triggered") and item.get("selected")]
        else:
            selected = decision.get("selected") or {}
            candidates = [(selected.get("market_type"), decision)] if selected.get("market_type") else []
        for market_type, market_decision in candidates:
            selected = market_decision.get("selected") or {}
            if selected.get("market_type") and selected.get("market_type") != market_type:
                # The market key is authoritative only when it agrees with the
                # normalized selection; mismatches are not silently repaired.
                continue
            settlement_key = f"{pid}__{market_type}"
            settlement = settlements.get(settlement_key) or settlements.get(pid)
            yield {"formal_record_id": f"qualified:{pid}:{market_type}", "source_layer": "QUALIFIED",
                   "source_record_id": f"{pid}:{market_type}", "source_path": str(path), "prediction_id": pid,
                   "market_record_id": settlement_key, "event_id": event.get("event_id"), "event": event,
                   "league": event.get("league"), "competition_key": event.get("competition_key"),
                   "team1_name": event.get("team1_name"), "team2_name": event.get("team2_name"),
                   "tip_time_bj": event.get("tip_time_bj"),
                   "first_write_at": market_decision.get("asof") or decision.get("asof"),
                   "market_type": market_type, "selection": selected.get("selection"),
                   "line": selected.get("line"), "decimal_odds": selected.get("decimal_odds"),
                   "bookmaker": selected.get("bookmaker"), "ot_rule": selected.get("ot_rule"),
                   "settlement": _settlement(settlement, "paper_pnl")}


def _shadow_records(root, folder, settlement_folder, layer):
    settlements = {path.stem: load(path, {}) for path in (root / "ledger" / settlement_folder).glob("*.json")}
    for path in sorted((root / "ledger" / folder).glob("*/*.json")):
        record = load(path, {}); record_id = record.get("record_id")
        if record.get("archive_type") != "FORWARD_NATIVE" or not record_id:
            continue
        event, market_type = record.get("event") or {}, record.get("market_type")
        if not event or market_type not in ("SPREAD", "TOTAL"):
            continue
        yield {"formal_record_id": layer.casefold() + ":" + record_id, "source_layer": layer,
               "source_record_id": record_id, "source_path": str(path),
               "prediction_id": record.get("prediction_id"), "event_id": record.get("event_id"),
               "event": event, "league": event.get("league"), "competition_key": event.get("competition_key"),
               "team1_name": event.get("team1_name"), "team2_name": event.get("team2_name"),
               "tip_time_bj": event.get("tip_time_bj"), "first_write_at": record.get("first_write_at"),
               "market_type": market_type,
               "selection": record.get("selected_side"), "line": record.get("market_line"),
               "decimal_odds": record.get("decimal_odds"), "bookmaker": record.get("bookmaker"),
               "ot_rule": record.get("ot_rule"),
               "settlement": _settlement(settlements.get(record_id), "provisional_pnl")}


def _summary(records):
    outcomes = Counter(record["settlement"]["outcome"] for record in records)
    settled = outcomes["WIN"] + outcomes["LOSS"] + outcomes["PUSH"]
    pnl = sum(float(record["settlement"]["formal_manual_pnl"]) for record in records
              if isinstance(record["settlement"].get("formal_manual_pnl"), (int, float)))
    return {"records": len(records), "wins": outcomes["WIN"], "losses": outcomes["LOSS"],
            "pushes": outcomes["PUSH"], "pending": outcomes["PENDING"], "settled": settled,
            "formal_manual_pnl_units": pnl, "formal_manual_roi": pnl / settled if settled else None,
            "hit_rate_ex_push": outcomes["WIN"] / (outcomes["WIN"] + outcomes["LOSS"])
            if outcomes["WIN"] + outcomes["LOSS"] else None}


def build_formal_manual_live_ledger(root, asof=None):
    """Derive the user-authorized formal manual-live ledger without mutation."""
    root = Path(root)
    candidates = list(_qualified_records(root))
    candidates += list(_shadow_records(root, "repair_v22_provisional", "repair_v22_provisional_settlements", "PROVISIONAL"))
    candidates += list(_shadow_records(root, "titan_provisional", "titan_provisional_settlements", "TITAN_PROVISIONAL"))
    candidates.sort(key=lambda row: (row.get("first_write_at") or "", PRIORITY[row["source_layer"]], row["formal_record_id"]))
    included, excluded = {}, []
    for record in candidates:
        key = _continuity_key(record.get("event"), record.get("market_type")); old = included.get(key)
        if old is None:
            included[key] = record; continue
        kept = min((old, record), key=lambda row: (row.get("first_write_at") or "", PRIORITY[row["source_layer"]], row["formal_record_id"]))
        rejected = record if kept is old else old; included[key] = kept
        excluded.append({"formal_record_id": rejected["formal_record_id"],
                         "reason": "DUPLICATE_EVENT_MARKET_FIRST_WRITE_SUPERSEDED",
                         "kept_formal_record_id": kept["formal_record_id"]})
    records = sorted(included.values(), key=lambda row: (row.get("first_write_at") or "", row["formal_record_id"]))
    for record in records:
        record.update({"formal_manual_accounting": True, "actual_fill_confirmed": False,
                       "settlement_contract": "FROZEN_SIGNAL_ONE_UNIT_UNTIL_MANUAL_FILL_RECORDED",
                       "authorization": POLICY_ID})
    result = {"schema_version": "formal-manual-ledger-1.0", "generated_at": stamp(), "asof": asof,
              "authorization": POLICY_ID, "included_layers": list(INCLUDED_LAYERS),
              "actual_fill_note": "未补录人工成交时，盈亏按冻结信号盘口的一单位正式手动账面结算；不代表券商成交回单。",
              "records": records, "summary": _summary(records),
              "by_layer": {layer: _summary([r for r in records if r["source_layer"] == layer]) for layer in INCLUDED_LAYERS},
              "dedupe": {"key": "canonical team-pair + tip time + market", "excluded": excluded},
              "source_ledgers_immutable": True}
    atomic(root / "ledger" / "formal_manual_live" / "current.json", result)
    atomic(root / "audits" / "formal_manual_ledger_migration.json", result)
    return result


def attach_formal_manual_ledger_to_dashboard(root, ledger):
    """Attach derived accounting only; event and first-write records are untouched."""
    root = Path(root); data = root / "dashboard_v2" / "data"
    summary = {key: ledger[key] for key in ("schema_version", "generated_at", "authorization", "included_layers",
              "actual_fill_note", "summary", "by_layer", "dedupe", "source_ledgers_immutable")}
    updated = []
    for path in list(data.glob("20??-??-??.json")) + [data / "latest.json"]:
        document = load(path, None)
        if not isinstance(document, dict):
            continue
        document["formal_manual_ledger"] = summary; atomic(path, document); updated.append(str(path))
    from .report import HTML
    web = root / "dashboard_v2"
    (web / "basketball.html").write_text(HTML.replace("new URL('./basketball-data/',location.href)", "new URL('./data/',location.href)"), encoding="utf-8")
    (web / "basketball-v2.html").write_text(HTML, encoding="utf-8")
    return {"updated_dashboard_documents": updated}
