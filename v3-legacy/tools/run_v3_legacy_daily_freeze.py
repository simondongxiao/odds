"""Materialize the exact V3 Legacy page decision into a dated freeze.

The JavaScript page remains the semantic source for V3.  This adapter only
executes it and persists the output; it does not reimplement or tune the
decision rules.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path

from v3_legacy_decision_engine import run_legacy_engine


ROOT = Path(r"D:\codex")
V3_ROOT = ROOT / "v3_legacy" / "outputs" / "football_odds_trader"
BRIDGE_DIR = ROOT / "bridge" / "v3_production"


def read_cards(html_path: Path) -> list[dict]:
    text = html_path.read_text(encoding="utf-8")
    match = re.search(r"const cardsData = (.*?);\r?\ncardsData\.forEach", text, re.S)
    if not match:
        match = re.search(r"const cardsData = (.*?);\r?\nconst stats", text, re.S)
    if not match:
        raise RuntimeError(f"cardsData not found in {html_path}")
    return json.loads(match.group(1))


def roster_count(list_date: str) -> int:
    paths = (
        V3_ROOT / "ledger" / "slate_rosters" / f"titan007_roster_{list_date.replace('-', '')}.json",
        ROOT / "outputs" / "football_odds_trader" / "ledger" / "slate_rosters" / f"titan007_roster_{list_date.replace('-', '')}.json",
    )
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        count = len(payload.get("matches") or {})
        if count:
            return count
    return 0


def parse_kickoff(value: object) -> dt.datetime | None:
    text = str(value or "").replace("北京时间（东8区）", "").replace("北京时间", "").strip()
    match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", text)
    if match:
        values = [int(item) for item in match.groups()]
        return dt.datetime(*values, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
    return parsed.astimezone(dt.timezone(dt.timedelta(hours=8)))


def read_csv_rows(path: Path | None) -> dict[str, dict[str, object]]:
    if path is None or not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {str(row.get("match_id", "")): dict(row) for row in csv.DictReader(handle) if row.get("match_id")}


def materialize(list_date: str, html_path: Path) -> tuple[Path, Path, dict]:
    # A dated V3 bridge is a production decision snapshot.  Once the list day
    # is in the past, a later refresh may append settlement data elsewhere but
    # must never regenerate or replace the decision snapshot.
    bridge_path = BRIDGE_DIR / f"{list_date}.json"
    if list_date < dt.date.today().isoformat() and bridge_path.exists():
        payload = json.loads(bridge_path.read_text(encoding="utf-8"))
        freeze_paths = sorted(
            (V3_ROOT / "ledger").glob(f"v3_legacy_decision_freeze_{list_date}_*.csv"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        payload["write_status"] = "HISTORICAL_DECISION_LOCKED"
        payload["write_message"] = (
            "历史V3决策已冻结；本次调用不重算、不覆盖Bridge，赛果/结算必须写入独立回填文件。"
        )
        return (freeze_paths[0] if freeze_paths else bridge_path), bridge_path, payload

    cards = [card for card in read_cards(html_path) if str(card.get("date", "")) == list_date]
    previous_bridge_rows: dict[str, dict[str, object]] = {}
    if bridge_path.exists():
        previous_bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
        previous_bridge_rows = {
            str(row.get("match_id", "")): dict(row)
            for row in previous_bridge.get("matches", []) if row.get("match_id")
        }
    previous_freezes = sorted(
        (V3_ROOT / "ledger").glob(f"v3_legacy_decision_freeze_{list_date}_*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    previous_freeze_rows = read_csv_rows(previous_freezes[0] if previous_freezes else None)
    decisions = run_legacy_engine(html_path, list_date)
    unique_decisions = {}
    decision_fields = ("action", "selected_team", "selected_side", "direction", "line", "water", "probability", "threshold", "risk", "top5_status")
    for decision in decisions:
        mid = str(decision.get("match_id", ""))
        if not mid:
            raise RuntimeError("V3 decision missing match_id")
        previous = unique_decisions.get(mid)
        if previous and any(previous.get(key) != decision.get(key) for key in decision_fields):
            raise RuntimeError(f"V3 conflicting duplicate decision: {mid}")
        unique_decisions.setdefault(mid, decision)
    decisions = list(unique_decisions.values())
    by_id = {str(card.get("match_id", "")): card for card in cards}
    stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    freeze_dir = V3_ROOT / "ledger"
    freeze_dir.mkdir(parents=True, exist_ok=True)
    freeze_path = freeze_dir / f"v3_legacy_decision_freeze_{list_date}_{stamp}.csv"
    fields = [
        "match_id", "match", "list_date", "decision_at", "rule_version", "action",
        "selected_team", "selected_side", "direction", "line", "water",
        "probability", "threshold", "risk", "reason", "top5_status",
        "frozen", "source_card", "competition", "kickoff", "home_team", "away_team",
        "model_id", "side_mapping_version", "run_id", "decision_id", "quote_at", "last_confirmed_at",
        "kickoff_at", "quote_age_at_decision", "hours_from_decision_to_kickoff",
        "hours_from_last_refresh_to_kickoff", "is_morning_baseline", "is_latest_valid_prematch",
        "parent_decision_id", "monitoring_bucket",
        "cup_regression_guard", "Cup_Refactor_Eligible", "Cup_Gateway_Status",
        "Competition_Domain", "Cup_Match_State", "Cup_Qualification_Utility",
        "Cup_Rotation_Risk", "Cup_Rest_Days", "Cup_Context_Missing",
        "Football_Pull_Score", "Public_Pull", "fair_goal_margin", "fair_handicap", "line_gap",
        "Cup_Bayes_Level", "Cup_Bayes_Posterior", "Cup_Bayes_P10", "Cup_Bayes_Weight",
        "Cup_Intent", "Cup_Raw_Intent", "Cup_Intent_Reason",
    ]
    out_rows: list[dict[str, object]] = []
    for decision in decisions:
        match_id = str(decision.get("match_id", ""))
        card = by_id.get(match_id, {})
        decision_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        decision_id = str(decision.get("decision_id") or hashlib.sha256(
            f"V3|{list_date}|{match_id}|{decision.get('action','')}|{decision.get('selected_team','')}|{decision_at}".encode("utf-8")
        ).hexdigest()[:20])
        new_row = {
            **{field: "" for field in fields},
            **decision,
            "match_id": match_id,
            "list_date": list_date,
            "decision_at": decision_at,
            "rule_version": decision.get("rule_version") or "V3_LEGACY_PAGE_PARITY",
            "frozen": True,
            "source_card": str(html_path),
            "competition": card.get("league", ""),
            "kickoff": card.get("display_time") or card.get("time", ""),
            "home_team": str(card.get("match", "")).split(" vs ", 1)[0],
            "away_team": str(card.get("match", "")).split(" vs ", 1)[1] if " vs " in str(card.get("match", "")) else "",
            "model_id": "V3_LEGACY_PRODUCTION",
            "side_mapping_version": "V3_LEGACY_PAGE_PARITY",
            "run_id": os.environ.get("FOOTBALL_RUN_ID", ""),
            "decision_id": decision_id,
            "quote_at": str(card.get("quote_at") or card.get("snapshot_stamp") or ""),
            "last_confirmed_at": str(card.get("last_confirmed_at") or card.get("quote_at") or card.get("snapshot_stamp") or ""),
            "kickoff_at": str(card.get("kickoff_at") or card.get("display_time") or card.get("time") or ""),
            "quote_age_at_decision": "",
            "hours_from_decision_to_kickoff": "",
            "hours_from_last_refresh_to_kickoff": "",
            "is_morning_baseline": False,
            "is_latest_valid_prematch": True,
            "parent_decision_id": "",
            "monitoring_bucket": "",
        }
        now = dt.datetime.now().astimezone()
        kickoff = parse_kickoff(card.get("kickoff_at") or card.get("display_time") or card.get("time"))
        started = str(card.get("state", "")) != "0" or (kickoff is not None and kickoff <= now)
        prior_bridge = previous_bridge_rows.get(match_id)
        prior_freeze = previous_freeze_rows.get(match_id)
        prior = prior_bridge or prior_freeze
        prior_bettable = str((prior_bridge or {}).get("action") or (prior_freeze or {}).get("action") or "") in {"可投", "半仓可投"}
        if prior and (started or prior_bettable):
            # Preserve every prior pre-match field.  New columns remain blank
            # when the older immutable record did not contain them.
            preserved = {field: prior.get(field, "") for field in fields}
            preserved["match_id"] = match_id
            out_rows.append(preserved)
        else:
            out_rows.append(new_row)
    with freeze_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)

    counts = {
        "可投": sum(row["action"] == "可投" for row in out_rows),
        "半仓可投": sum(row["action"] == "半仓可投" for row in out_rows),
        "不投": sum(row["action"] == "不投" for row in out_rows),
    }
    total_roster = roster_count(list_date) or len(cards)
    bridge_payload = {
        "list_date": list_date,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source": "V3_LEGACY",
        "rule_version": (
            "V3_CUP_MATCH_STATE_R1_20260930"
            if any(bool(row.get("Cup_Refactor_Eligible")) for row in out_rows)
            else "V3_LEGACY_PAGE_PARITY"
        ),
        "roster_count": total_roster,
        "computed_count": len(out_rows),
        "bettable_count": counts["可投"],
        "half_bettable_count": counts["半仓可投"],
        "watch_count": 0,
        "no_bet_count": counts["不投"],
        "missing_count": max(0, total_roster - len(out_rows)),
        "matches": out_rows,
        "decision_source": str(html_path),
    }
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    bridge_path.write_text(json.dumps(bridge_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return freeze_path, bridge_path, bridge_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("list_date")
    parser.add_argument("--html", required=True)
    args = parser.parse_args()
    freeze, bridge, payload = materialize(args.list_date, Path(args.html))
    print(json.dumps({
        "freeze": str(freeze),
        "bridge": str(bridge),
        "roster_count": payload["roster_count"],
        "computed_count": payload["computed_count"],
        "bettable_count": payload["bettable_count"],
        "half_bettable_count": payload["half_bettable_count"],
        "no_bet_count": payload["no_bet_count"],
        "missing_count": payload["missing_count"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
