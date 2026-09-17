"""Read-only decision/settlement audit for an existing daily run."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
from pathlib import Path

ROOT = Path(r"D:\codex")
OUT = ROOT / "outputs/football_odds_trader"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    manifest = read(args.run_dir / "run_manifest.json")
    now = dt.datetime.fromisoformat(manifest["run_at"])
    errors = []
    checks = {}
    fields = {
        "V3": ["action", "selected_team", "selected_side", "line", "water", "probability", "threshold", "decision_at"],
        "V4": ["grade", "selected_team", "selected_side", "selected_handicap_signed", "selected_water_hk", "probabilities", "ev_mean", "ev_p10", "p_ev_positive", "decision_at"],
    }
    backup = read(Path(manifest["backup"]) / "manifest.json")
    for version, path in [("V3", manifest["artifacts"]["bridge"]), ("V4", manifest["artifacts"]["v4"])]:
        current = read(path)
        rows = current["matches"]
        ids = [str(r["match_id"]) for r in rows]
        assert len(ids) == len(set(ids)), f"{version}: duplicate ids"
        old_path = next((x["backup"] for x in backup["files"] if Path(x["source"]) == Path(path)), None)
        locked = 0
        if old_path:
            prior = read(old_path)["matches"]
            index = {str(r["match_id"]): r for r in rows}
            for old in prior:
                mid = str(old["match_id"])
                if mid not in index:
                    errors.append(f"{version}: missing roster id {mid}")
                    continue
                kickoff = old.get("kickoff_at") or old.get("kickoff")
                try:
                    started = dt.datetime.fromisoformat(kickoff) <= now
                except (TypeError, ValueError):
                    continue
                if started:
                    locked += 1
                    for key in fields[version]:
                        if old.get(key) != index[mid].get(key):
                            errors.append(f"{version}: started {mid} changed {key}")
        checks[version] = {"roster": len(rows), "started_compared": locked}
        if version == "V3":
            html_path = ROOT / "v3_legacy/outputs/football_odds_trader/dashboard/index.html"
            text = html_path.read_text(encoding="utf-8")
            card_match = re.search(
                r"const cardsData = (.*?);\r?\n(?:cardsData\.forEach|const stats)",
                text,
                re.S,
            )
            if not card_match:
                errors.append("V3: dashboard cards payload missing")
            else:
                cards = json.loads(card_match.group(1))
                today_cards = [card for card in cards if str(card.get("date", "")) == manifest["list_date"]]
                frozen_cards = [card for card in today_cards if card.get("frozen_bettable")]
                bridge_picks = [row for row in rows if row.get("action") in {"可投", "半仓可投"}]
                if len(frozen_cards) != len(bridge_picks):
                    errors.append(
                        f"V3: dashboard frozen count {len(frozen_cards)} != bridge picks {len(bridge_picks)}"
                    )
                if any(not card.get("frozen_bettable_team") for card in frozen_cards):
                    errors.append("V3: frozen dashboard pick missing selected team")
                checks[version].update({
                    "dashboard_rows": len(today_cards),
                    "dashboard_frozen_bettable": len(frozen_cards),
                })
        if version == "V4":
            counts = {g: sum(r.get("grade") == g for r in rows) for g in "ABCN"}
            assert sum(counts.values()) == current["summary"]["computed"]
            checks[version].update(counts)
    perf = manifest["steps"]["yesterday_performance"]["stdout"]
    payload = json.loads(perf.strip().splitlines()[-1])
    with Path(payload["csv"]).open(encoding="utf-8-sig", newline="") as f:
        settled = list(csv.DictReader(f))
    checked = 0
    # Independent quarter-line arithmetic using the selected team's signed line.
    for row in settled:
        if row["version"] != "V4_SHADOW" or row["result"] not in {"W", "HW", "P", "HL", "L"}:
            continue
        home, away = row["match"].split(" vs ", 1)
        hs, aws = map(int, row["score"].split("-"))
        margin = hs - aws if row["selected_team"] == home else aws - hs
        q = round(float(row["line"]) * 4)
        components = [q / 4, q / 4] if q % 2 == 0 else [(q - 1) / 4, (q + 1) / 4]
        tally = sum(1 if margin + h > 0 else -1 if margin + h < 0 else 0 for h in components)
        expected = {2: "W", 1: "HW", 0: "P", -1: "HL", -2: "L"}[tally]
        amount = {"W": float(row["water"]), "HW": float(row["water"]) / 2, "P": 0, "HL": -.5, "L": -1}[expected]
        if expected != row["result"] or abs(amount - float(row["pnl_1u"])) > 1e-6:
            errors.append(f"settlement mismatch {row['match_id']}: {row['result']} vs {expected}")
        checked += 1
    checks["settlements_checked"] = checked
    checks["yesterday"] = payload
    checks["errors"] = errors
    required_steps = ("v3_daily", "v3_freeze", "v4_shadow", "yesterday_performance")
    if "v3_apply_freeze" in manifest["steps"]:
        required_steps += ("v3_apply_freeze",)
    checks["pass"] = not errors and all(manifest["steps"][k]["returncode"] == 0 for k in required_steps) and manifest["fetch"].get("returncode") == 0
    path = args.run_dir / "delivery_verification.json"
    path.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False))
    return 0 if checks["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
