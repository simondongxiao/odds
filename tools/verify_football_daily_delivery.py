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


def parse_line(value):
    text = str(value if value is not None else "").strip()
    aliases = {
        "平手": 0.0, "平手/半球": 0.25, "半球": 0.5, "半球/一球": 0.75,
        "一球": 1.0, "一球/球半": 1.25, "球半": 1.5, "球半/两球": 1.75,
        "两球": 2.0, "两球/两球半": 2.25, "两球半": 2.5, "两球半/三球": 2.75,
    }
    if text in aliases:
        return aliases[text]
    try:
        return float(text.removesuffix("球"))
    except ValueError:
        return None


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
            computed_rows = [
                row for row in rows
                if row.get("analysis_status") in {"EVALUATED", "FROZEN_PREMATCH_DECISION"}
            ]
            counts = {g: sum(r.get("grade") == g for r in computed_rows) for g in "ABCN"}
            if sum(counts.values()) != current["summary"]["computed"]:
                errors.append(
                    f"V4: computed grade count {sum(counts.values())} != summary {current['summary']['computed']}"
                )
            new_rows = [row for row in rows if row.get("model_id") == "V4" and row.get("analysis_status") == "EVALUATED"]
            for row in new_rows:
                mid = str(row.get("match_id"))
                if row.get("final_decision") not in {"BET_GIVING", "BET_RECEIVING", "NO_BET"}:
                    errors.append(f"V4: invalid final decision {mid}")
                if row.get("ev_giving") is None or row.get("ev_receiving") is None:
                    errors.append(f"V4: missing two-sided EV {mid}")
                if not row.get("giving_probabilities") or not row.get("receiving_probabilities"):
                    errors.append(f"V4: missing two-sided probabilities {mid}")
                expected_unit = 1.0 if str(row.get("final_decision", "")).startswith("BET_") else 0.0
                if float(row.get("bet_unit", -1)) != expected_unit:
                    errors.append(f"V4: fixed-unit violation {mid}")
                if not (row.get("expert_selector") or {}).get("core_evaluable"):
                    errors.append(f"V4: normal evaluated row not CORE evaluable {mid}")
                if row.get("real_money") is not False:
                    errors.append(f"V4: real_money must remain false {mid}")
            checks[version].update({
                **counts,
                "computed_rows": len(computed_rows),
                "match_specific_rows_checked": len(new_rows),
                "bet_giving": sum(r.get("final_decision") == "BET_GIVING" for r in new_rows),
                "bet_receiving": sum(r.get("final_decision") == "BET_RECEIVING" for r in new_rows),
                "no_bet": sum(r.get("final_decision") == "NO_BET" for r in new_rows),
            })
    perf = manifest["steps"]["yesterday_performance"]["stdout"]
    payload = json.loads(perf.strip().splitlines()[-1])
    with Path(payload["csv"]).open(encoding="utf-8-sig", newline="") as f:
        settled = list(csv.DictReader(f))
    checked = 0
    checked_by_version = {"V3": 0, "V4_SHADOW": 0}
    # Independent quarter-line arithmetic using the selected team's signed line.
    for row in settled:
        if row["version"] not in checked_by_version or row["result"] not in {"W", "HW", "P", "HL", "L"}:
            continue
        home, away = row["match"].split(" vs ", 1)
        hs, aws = map(int, row["score"].split("-"))
        margin = hs - aws if row["selected_team"] == home else aws - hs
        line = parse_line(row["line"])
        if line is None:
            errors.append(f"settlement line missing {row['version']} {row['match_id']}")
            continue
        if row["version"] == "V4_SHADOW":
            signed_line = line
        else:
            side = str(row.get("selected_side", "")).lower()
            if side not in {"upper", "lower"}:
                errors.append(f"settlement side missing V3 {row['match_id']}")
                continue
            signed_line = -abs(line) if side == "upper" else abs(line)
        q = round(signed_line * 4)
        components = [q / 4, q / 4] if q % 2 == 0 else [(q - 1) / 4, (q + 1) / 4]
        tally = sum(1 if margin + h > 0 else -1 if margin + h < 0 else 0 for h in components)
        expected = {2: "W", 1: "HW", 0: "P", -1: "HL", -2: "L"}[tally]
        amount = {"W": float(row["water"]), "HW": float(row["water"]) / 2, "P": 0, "HL": -.5, "L": -1}[expected]
        if expected != row["result"] or abs(amount - float(row["pnl_1u"])) > 1e-6:
            errors.append(f"settlement mismatch {row['version']} {row['match_id']}: {row['result']} vs {expected}")
        checked += 1
        checked_by_version[row["version"]] += 1
    checks["settlements_checked"] = checked
    checks["settlements_checked_by_version"] = checked_by_version
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
