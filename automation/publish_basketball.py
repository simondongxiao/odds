from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path



def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def anchor_key(event):
    """Provider-independent fixture key for immutable decision anchors."""
    event = event or {}
    teams = [event.get('canonical_team1_id') or event.get('team1_name'),
             event.get('canonical_team2_id') or event.get('team2_name')]
    teams = sorted(re.sub(r'[^0-9a-zA-Z\u4e00-\u9fff]+', '', str(x or '').casefold()) for x in teams)
    tip = str(event.get('tip_at') or event.get('tip_time_bj') or '')[:16]
    return '|'.join(teams + [tip])


def anchor_triggered(execution):
    if not isinstance(execution, dict):
        return False
    if execution.get('triggered') is True or execution.get('titan_provisional_status') == 'TITAN_PROVISIONAL_SHADOW':
        return True
    return any(isinstance(item, dict) and
               (item.get('triggered') is True or item.get('status') == 'TITAN_PROVISIONAL_SHADOW')
               for item in (execution.get('market_decisions') or {}).values())


def direction_signature(execution):
    if not isinstance(execution, dict):
        return {}
    out = {}
    for market, item in (execution.get('market_decisions') or {}).items():
        selected = item.get('selected') if isinstance(item, dict) else None
        if isinstance(selected, dict) and selected.get('selection'):
            out[str(market)] = str(selected['selection'])
    selected = execution.get('selected') or {}
    if selected.get('selection'):
        out.setdefault(str(selected.get('market_type') or 'SELECTED'), str(selected['selection']))
    return out


def write_decision_anchor(dst_data, day, current_doc):
    """Append/merge first-write paper decisions for the target date.

    The anchor is a published continuity artifact, not a second source of
    odds.  Existing rows win forever; a later opposite side is recorded as a
    review audit and the original direction remains the displayed decision.
    """
    anchor_dir = dst_data / 'decision_anchors'
    anchor_dir.mkdir(parents=True, exist_ok=True)
    path = anchor_dir / f'{day}.json'
    previous = load(path, {})
    old_rows = [row for row in (previous.get('rows') or []) if isinstance(row, dict)]
    current_rows = [row for row in (current_doc.get('events') or [])
                    if isinstance(row, dict) and isinstance(row.get('event'), dict)
                    and row['event'].get('bj_date') == day
                    and anchor_triggered(row.get('execution') or {})]
    merged = {}
    for row in old_rows:
        event = row.get('event') or {}
        if event.get('bj_date') == day:
            merged[anchor_key(event)] = copy.deepcopy(row)
    for row in current_rows:
        key = anchor_key(row.get('event') or {})
        if key not in merged:
            item = copy.deepcopy(row)
            item['anchor_status'] = 'LOCKED_FIRST_WRITE'
            item['anchor_first_write_asof'] = (row.get('execution') or {}).get('asof') or current_doc.get('asof')
            merged[key] = item
            continue
        item = merged[key]
        old_execution = item.get('execution') or {}
        new_execution = row.get('execution') or {}
        old_sig, new_sig = direction_signature(old_execution), direction_signature(new_execution)
        if old_sig and new_sig and old_sig != new_sig:
            item['direction_change_audit'] = {
                'status': 'REVIEW_REQUIRED', 'direction_reversed': True,
                'first_write': old_sig, 'current_revalidation': new_sig,
                'checked_at': current_doc.get('asof'),
                'display': '模型复核方向与首写方向不同；保留首写方向，单独提出复核',
            }
        item['latest_revalidation'] = {
            'asof': current_doc.get('asof'), 'event': row.get('event'),
            'execution': new_execution, 'market': row.get('market') or {},
        }
        for field in ('settlement', 'post_match_review', 'revisions'):
            if field in row:
                item[field] = row[field]
    payload = {
        'schema_version': 'basketball-decision-anchor-1.0',
        'date_bj': day, 'generated_at': datetime.now(timezone.utc).isoformat(),
        'source_kind': 'PUBLISHED_FIRST_WRITE_PROJECTION',
        'locked_direction_policy': 'FIRST_WRITE_WINS; DIRECTION_CHANGE_REVIEW_ONLY',
        'rows': list(merged.values()), 'locked_rows': len(merged),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return path, payload


def mobile_document(document):
    """Create a small presentation payload without changing the audit JSON.

    The desktop payload is the immutable/auditable contract.  A phone only
    needs the identity, decision, compact price and a few current-board quotes;
    raw provider rows, hashes and model decomposition stay in the desktop
    payload.  Keeping this projection here also means the mobile path cannot
    accidentally change a model gate or a paper-ledger record.
    """
    if not isinstance(document, dict):
        return document

    def pick(value, keys):
        return {key: value[key] for key in keys if isinstance(value, dict) and key in value}

    def compact_event(value):
        return pick(value, (
            "bj_date", "canonical_event_id", "canonical_identity_ambiguous",
            "canonical_team1_id", "canonical_team2_id", "competition_key", "event_id",
            "gender", "identity_verified", "inventory_retained", "league", "league_display",
            "league_family", "market_status", "next_market_retry_at", "pricing_inventory_status",
            "season_phase", "source_event_id", "team1_id", "team1_name", "team2_id",
            "team2_name", "tip_at", "tip_time_bj", "tip_time_utc",
        ))

    def compact_selected(value):
        return pick(value, (
            "market_type", "selection", "line", "decimal_odds", "quote_id", "bookmaker",
            "ev", "adverse_ev", "probability_edge", "conditional_edge",
            "selected_side_line_edge_points", "line_edge_points", "information_risk", "ot_rule",
        ))

    def compact_revalidation(value):
        if not isinstance(value, dict):
            return value
        result = pick(value, (
            "status", "checked_at", "display", "real_execution_allowed",
            "current_revalidation_status", "fresh_observation", "reason",
        ))
        for key in ("original_selection", "current_selected"):
            if isinstance(value.get(key), dict):
                result[key] = compact_selected(value[key])
        if isinstance(value.get("market_difference"), dict):
            result["market_difference"] = pick(value["market_difference"], (
                "material", "line_direction", "odds_direction", "line_delta", "odds_delta",
            ))
        return result

    def compact_decision(value):
        if not isinstance(value, dict):
            return value
        result = pick(value, (
            "triggered", "comparison_ready", "model_state", "ev", "blockers",
            "uncertainty_flags", "market_type", "display_action", "shadow_action",
        ))
        if isinstance(value.get("selected"), dict):
            result["selected"] = compact_selected(value["selected"])
        if isinstance(value.get("market_revalidation"), dict):
            result["market_revalidation"] = compact_revalidation(value["market_revalidation"])
        return result

    def compact_execution(value):
        if not isinstance(value, dict):
            return value
        result = pick(value, (
            "event_id", "prediction_id", "asof", "archive_type", "execution_mode",
            "manual_execution_state", "shadow_action", "triggered", "display_action",
            "comparison_ready", "model_state", "blockers", "titan_provisional_status",
            "signal_layer",
        ))
        if isinstance(value.get("execution_lifecycle"), dict):
            result["execution_lifecycle"] = pick(value["execution_lifecycle"], (
                "entry_phase", "threshold_source", "status", "checked_at", "display",
            ))
        if isinstance(value.get("selected"), dict):
            result["selected"] = compact_selected(value["selected"])
        if isinstance(value.get("market_decisions"), dict):
            result["market_decisions"] = {
                key: compact_decision(item)
                for key, item in value["market_decisions"].items()
                if key in ("SPREAD", "TOTAL") and isinstance(item, dict)
            }
        if isinstance(value.get("market_revalidation"), dict):
            result["market_revalidation"] = compact_revalidation(value["market_revalidation"])
        if isinstance(value.get("titan_provisional_continuity"), dict):
            continuity = pick(value["titan_provisional_continuity"], (
                "status", "current_revalidation_status", "match_method", "event_id",
            ))
            if isinstance(value["titan_provisional_continuity"].get("selected"), dict):
                continuity["selected"] = compact_selected(value["titan_provisional_continuity"]["selected"])
            result["titan_provisional_continuity"] = continuity
        return result

    def compact_pricing(value):
        if not isinstance(value, dict):
            return value
        result = pick(value, (
            "event_id", "mu_raw", "total_raw", "input_games", "pricing_data_quality",
            "pricing_status", "blockers", "model_warnings",
        ))
        diagnostic = value.get("total_diagnostic")
        if isinstance(diagnostic, dict):
            result["total_diagnostic"] = pick(diagnostic, (
                "game_minutes", "recent_total_mean", "recent_total_stdev",
                "close_game_q4_observations", "blowout_q4_observations", "execution_eligible",
                "uncertainty_flags", "pace_level", "pace_evidence_status", "source_status",
            ))
        return result

    def compact_quote(value):
        return pick(value, (
            "bookmaker", "bookmaker_id", "market_type", "quote_id", "raw_line", "line_team1",
            "decimal_prices", "raw_prices", "direction_verified", "main_or_alt", "period",
            "ot_rule", "source_quote_at", "received_at",
        ))

    def compact_state(value):
        result = pick(value, (
            "quote_id", "age_seconds", "fresh_observation", "freshness_basis",
            "last_change_age_seconds", "paper_quote_eligible",
            "reasons", "ttl_seconds", "warnings",
        ))
        for key in ("reasons", "warnings"):
            if isinstance(result.get(key), list):
                result[key] = result[key][:3]
        return result

    def compact_market(value, selected_ids=()):
        if not isinstance(value, dict):
            return value
        quotes = [q for q in value.get("quotes") or [] if isinstance(q, dict)]
        selected_ids = {item for item in selected_ids if item}
        compact_quotes = []
        per_type = {}
        # Keep the selected quote plus a bounded sample of each market.  The
        # full quote array (including raw paths/hashes) remains in desktop JSON.
        for quote in quotes:
            market_type = quote.get("market_type") or "OTHER"
            if quote.get("quote_id") in selected_ids or per_type.get(market_type, 0) < 3:
                compact_quotes.append(compact_quote(quote))
                per_type[market_type] = per_type.get(market_type, 0) + 1
        return {
            "quotes": compact_quotes,
            "quote_states": [compact_state(state) for state in (value.get("quote_states") or [])[:8]
                              if isinstance(state, dict)],
        }

    def selected_quote_ids(value):
        """Collect selected quote ids from either frozen or display decisions."""
        if not isinstance(value, dict):
            return []
        result = []
        selected = value.get("selected")
        if isinstance(selected, dict) and selected.get("quote_id"):
            result.append(selected["quote_id"])
        for decision in (value.get("market_decisions") or {}).values():
            if isinstance(decision, dict) and isinstance(decision.get("selected"), dict):
                quote_id = decision["selected"].get("quote_id")
                if quote_id:
                    result.append(quote_id)
        return result

    def compact_snapshot(value):
        if not isinstance(value, dict):
            return value
        result = pick(value, ("asof", "refresh_status"))
        event = compact_event(value.get("event"))
        if event:
            result["event"] = event
        pricing = compact_pricing(value.get("pricing"))
        if pricing:
            result["pricing"] = pricing
        execution = compact_execution(value.get("execution"))
        if execution:
            selected_ids = selected_quote_ids(execution)
            result["execution"] = execution
            result["market"] = compact_market(value.get("market"), selected_ids)
        elif isinstance(value.get("market"), dict):
            result["market"] = compact_market(value.get("market"))
        return result

    top_keys = (
        "date_bj", "date", "asof", "generated_at", "archive_type", "message",
        "execution_mode", "schema_version", "real_execution_allowed",
        "automated_execution_allowed", "funnel", "daily_paper_funnel",
        "formal_manual_ledger", "paper_ledger_history",
    )
    out = pick(document, top_keys)
    compact_events = []
    for row in document.get("events") or []:
        if not isinstance(row, dict):
            continue
        execution = compact_execution(row.get("execution")) or {}
        selected_ids = selected_quote_ids(execution)
        selected_ids.extend(selected_quote_ids(row.get("display_execution")))
        item = pick(row, (
            "id", "generation", "archive_type", "display", "settlement",
            "first_write_preserved", "continuity_match_method", "display_dedupe",
        ))
        item["event"] = compact_event(row.get("event"))
        item["pricing"] = compact_pricing(row.get("pricing"))
        item["execution"] = execution
        item["market"] = compact_market(row.get("market"), selected_ids) or {"quotes": [], "quote_states": []}
        for key in ("display_event", "display_pricing", "display_execution", "display_market"):
            if key not in row:
                continue
            if key == "display_event":
                item[key] = compact_event(row[key])
            elif key == "display_pricing":
                item[key] = compact_pricing(row[key])
            elif key == "display_execution":
                item[key] = compact_execution(row[key])
            else:
                item[key] = compact_market(row[key], selected_ids)
        if isinstance(row.get("current_snapshot"), dict):
            item["current_snapshot"] = compact_snapshot(row["current_snapshot"])
        compact_events.append(item)
    out["events"] = compact_events
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
    anchor_path, anchor_payload = write_decision_anchor(dst_data, day, current_doc)
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
        "decision_anchor_file": f"decision_anchors/{day}.json",
        "decision_anchor_rows": anchor_payload.get("locked_rows", 0),
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
        "decision_anchor": str(anchor_path),
        "decision_anchor_rows": anchor_payload.get("locked_rows", 0),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
