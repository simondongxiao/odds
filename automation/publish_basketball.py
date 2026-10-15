from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path



def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def mobile_document(document):
    """Keep the mobile dashboard small without changing the desktop audit payload."""
    if not isinstance(document, dict):
        return document
    top_keys = (
        "date_bj", "date", "asof", "generated_at", "archive_type", "message",
        "execution_mode", "schema_version", "real_execution_allowed",
        "automated_execution_allowed", "funnel", "daily_paper_funnel",
        "formal_manual_ledger", "paper_ledger_history",
    )
    out = {key: document[key] for key in top_keys if key in document}
    # The visible cards use these fields. Large read-only diagnostics remain in
    # the desktop JSON and artifact, where they can be opened on demand.
    event_keys = ("id", "generation", "archive_type", "event", "pricing",
                  "execution", "market", "display", "settlement", "current_snapshot")
    pricing_keep = {
        "archive_type", "asof", "event_id", "mu_raw", "mu_blended", "mu_market",
        "mu_structural", "total_raw", "total_blended", "total_market", "total_structural",
        "input_games", "pricing_data_quality", "pricing_state", "pricing_status",
        "research_priceable", "paper_model_eligible", "executable_eligible",
        "cold_start_priceable", "shadow_eligible", "league_lifecycle_state", "season_regime",
        "history_ess", "current_season_games", "previous_season_games", "older_history_games",
        "blockers", "model_warnings", "uncertainty_source", "spread_data_quality",
        "total_model_status", "total_diagnostic", "titan_foundation_pricing",
    }
    decision_keep = {
        "selected", "triggered", "comparison_ready", "model_state", "ev", "blockers",
        "uncertainty_flags", "market_type", "market_revalidation", "display_action",
    }
    execution_keep = {
        "event_id", "prediction_id", "asof", "archive_type", "execution_mode",
        "manual_execution_state", "shadow_action", "triggered", "display_action",
        "comparison_ready", "model_state", "selected", "market_decisions",
        "blockers", "market_revalidation", "market_revalidation_by_market",
        "titan_provisional_continuity", "titan_provisional_status", "signal_layer",
    }

    def compact_pricing(value):
        if not isinstance(value, dict):
            return value
        return {k: value[k] for k in pricing_keep if k in value}

    def compact_decision(value):
        if not isinstance(value, dict):
            return value
        return {k: value[k] for k in decision_keep if k in value}

    def compact_execution(value):
        if not isinstance(value, dict):
            return value
        out_exec = {k: value[k] for k in execution_keep if k in value}
        if isinstance(value.get("market_decisions"), dict):
            out_exec["market_decisions"] = {
                k: compact_decision(v) for k, v in value["market_decisions"].items()
            }
        if isinstance(value.get("selected"), dict):
            out_exec["selected"] = dict(value["selected"])
        return out_exec

    def compact_snapshot(value):
        if not isinstance(value, dict):
            return value
        out_snapshot = {k: value[k] for k in ("asof", "refresh_status") if k in value}
        if isinstance(value.get("event"), dict):
            out_snapshot["event"] = dict(value["event"])
        if isinstance(value.get("pricing"), dict):
            out_snapshot["pricing"] = compact_pricing(value["pricing"])
        if isinstance(value.get("execution"), dict):
            out_snapshot["execution"] = compact_execution(value["execution"])
        if isinstance(value.get("market"), dict):
            out_snapshot["market"] = value["market"]
        return out_snapshot
    compact_events = []
    for row in document.get("events") or []:
        if not isinstance(row, dict):
            continue
        item = {key: row[key] for key in event_keys if key in row}
        if isinstance(item.get("pricing"), dict):
            item["pricing"] = compact_pricing(item["pricing"])
        if isinstance(item.get("execution"), dict):
            item["execution"] = compact_execution(item["execution"])
        if isinstance(item.get("current_snapshot"), dict):
            item["current_snapshot"] = compact_snapshot(item["current_snapshot"])
        compact_events.append(item)
    out["events"] = compact_events
    funnel = document.get("funnel")
    if isinstance(funnel, dict):
        out["funnel"] = dict(funnel)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish the bounded basketball daily output to gh-pages")
    ap.add_argument("--root", required=True)
    ap.add_argument("--public", required=True)
    args = ap.parse_args()
    root = Path(args.root).resolve()
    public = Path(args.public).resolve()
    src_data = root / "dashboard_v2" / "data"
    dst_data = public / "basketball-data"
    dst_data.mkdir(parents=True, exist_ok=True)
    latest = load(src_data / "latest.json", {})
    day = str(latest.get("date_bj") or latest.get("date") or "")
    if not day:
        raise SystemExit("basketball daily output has no date_bj")
    if latest.get("update_status") == "FAILED":
        raise SystemExit("refusing to publish a payload marked update_status=FAILED")
    current = src_data / f"{day}.json"
    if not current.is_file():
        raise SystemExit(f"missing daily JSON: {current}")
    current_doc = load(current, {})
    if current_doc.get("date_bj") != day or not current_doc.get("events"):
        raise SystemExit("refusing to publish a stale or empty basketball target payload")
    mobile = mobile_document(latest)
    # Publish the target date plus the skill-mandated next-day lookahead.  The
    # latter is kept as a selectable inventory snapshot, while latest.json
    # remains anchored to the target date and is never mixed with it.
    publish_paths = [current]
    try:
        next_day = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        lookahead = src_data / f"{next_day}.json"
        if lookahead.is_file():
            publish_paths.append(lookahead)
    except ValueError:
        next_day = None
    publish_paths.append(src_data / "latest.json")
    for path in publish_paths:
        shutil.copy2(path, dst_data / path.name)
    # A compact payload prevents mobile browsers from repeatedly downloading
    # multi-megabyte audit diagnostics. It is intentionally separate from the
    # full desktop JSON and never replaces the immutable audit artifact.
    (dst_data / f"{day}.mobile.json").write_text(
        json.dumps(mobile, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    if next_day and (src_data / f"{next_day}.json").is_file():
        next_doc = load(src_data / f"{next_day}.json", {})
        (dst_data / f"{next_day}.mobile.json").write_text(
            json.dumps(mobile_document(next_doc), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    (dst_data / "latest.mobile.json").write_text(
        json.dumps(mobile, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    health = root / "dashboard_v2" / "sources" / "health.json"
    if health.is_file():
        target = public / "basketball-sources" / "health.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(health, target)
    for name in ("basketball-v2.html", "basketball.html"):
        path = root / "dashboard_v2" / name
        if path.is_file():
            shutil.copy2(path, public / name)
    index = load(dst_data / "index.json", {})
    entries = {}
    for row in index.get("dates", []) if isinstance(index, dict) else []:
        if isinstance(row, str):
            entries[row] = {"date": row, "file": f"{row}.json"}
        elif isinstance(row, dict) and row.get("date"):
            entries[str(row["date"])] = dict(row)
    entries[day] = {
        "date": day,
        "file": f"{day}.json",
        "mobile_file": f"{day}.mobile.json",
        "event_count": len(latest.get("events") or []),
        "archive_type": latest.get("archive_type", "FORWARD_NATIVE"),
    }
    if next_day and (src_data / f"{next_day}.json").is_file():
        next_doc = load(src_data / f"{next_day}.json", {})
        entries[next_day] = {
            "date": next_day,
            "file": f"{next_day}.json",
            "mobile_file": f"{next_day}.mobile.json",
            "event_count": len(next_doc.get("events") or []),
            "archive_type": next_doc.get("archive_type", "FORWARD_NATIVE"),
        }
    # Never advertise a date whose payload is absent.  A stale index entry
    # used to make the selector request a 404 and leave the previous day's
    # data visible, which looked like a failed date switch on mobile.
    entries = {
        key: value for key, value in entries.items()
        if (dst_data / str(value.get("file") or f"{key}.json")).is_file()
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dates": [entries[key] for key in sorted(entries, reverse=True)],
    }
    (dst_data / "index.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "date_bj": day,
        "paper_bettable": (latest.get("funnel") or {}).get("paper_bettable"),
        "events": len(latest.get("events") or []),
        "published_data": str(dst_data / f"{day}.json"),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
