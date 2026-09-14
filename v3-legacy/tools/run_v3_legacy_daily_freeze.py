"""Materialize the exact V3 Legacy page decision into a dated freeze.

The JavaScript page remains the semantic source for V3.  This adapter only
executes it and persists the output; it does not reimplement or tune the
decision rules.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
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
    decisions = run_legacy_engine(html_path, list_date)
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
    ]
    out_rows: list[dict[str, object]] = []
    for decision in decisions:
        match_id = str(decision.get("match_id", ""))
        card = by_id.get(match_id, {})
        out_rows.append({
            **{field: "" for field in fields},
            **decision,
            "match_id": match_id,
            "list_date": list_date,
            "decision_at": dt.datetime.now().isoformat(timespec="seconds"),
            "rule_version": "V3_LEGACY_PAGE_PARITY",
            "frozen": True,
            "source_card": str(html_path),
            "competition": card.get("league", ""),
            "kickoff": card.get("display_time") or card.get("time", ""),
            "home_team": str(card.get("match", "")).split(" vs ", 1)[0],
            "away_team": str(card.get("match", "")).split(" vs ", 1)[1] if " vs " in str(card.get("match", "")) else "",
        })
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
        "rule_version": "V3_LEGACY_PAGE_PARITY",
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
