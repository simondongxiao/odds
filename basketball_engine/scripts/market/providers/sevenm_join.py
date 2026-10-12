from __future__ import annotations
import json, re
from datetime import datetime, timezone
from pathlib import Path
from ..normalize_market import normalize

def _text(blob: bytes) -> str:
    return blob.decode("gb18030", errors="replace")

def _events(session: Path) -> dict[str, dict]:
    found = {}
    for path in session.glob("event_*.raw"):
        text = _text(path.read_bytes())
        for m in re.finditer(r"bDt\[(\d+)\]=\[0,'([^']+)',(\d+),'([^']*)','[^']*',\d+,'([^']*)',\d+,'([^']*)'", text):
            eid, dt, league_id, league, team1, team2 = m.groups()
            found[eid] = {"source_event_id": eid, "date_raw": dt, "league_family": league or "7M_BASKETBALL", "team_1": team1, "team_2": team2, "source_path": str(path)}
    return found

def _quotes(session: Path) -> dict[str, list[dict]]:
    out = {}
    names = {"0": "澳", "1": "S2", "2": "易", "3": "12", "4": "威"}
    for path in session.glob("odds_company_*.raw"):
        company_id = path.stem.split("_")[-1]
        text = _text(path.read_bytes())
        for m in re.finditer(r"bOdds\[(\d+)\]\[(\d+)\]\s*=\s*\{([^;]+)\};", text):
            namespace, eid, body = m.groups()
            records = {}
            for kind in ("HB", "TP"):
                q = re.search(r'"' + kind + r'"\s*:\s*\{\d+:\[([^\]]+)\]', body)
                if q:
                    vals = [x.strip().strip('"') for x in q.group(1).split(',')]
                    if len(vals) >= 4:
                        records[kind] = {"price_hk": float(vals[0]), "quote_timestamp": vals[2], "line": float(vals[3]), "selection_flag": vals[4] if len(vals) > 4 else None}
            if records: out.setdefault(eid, []).append({"company_id": company_id, "company_name": names.get(company_id, company_id), "records": records})
    return out

def join_session(session_dir: str | Path, out_root: str | Path) -> dict:
    p = Path(session_dir); meta = json.loads((p / "session.json").read_text(encoding="utf8"))
    events, quotes = _events(p), _quotes(p)
    reverse = json.loads((p / "reverse_resolution.json").read_text(encoding="utf8")) if (p / "reverse_resolution.json").exists() else {"rows": []}
    resolved = {str(x["odds_id"]): x for x in reverse.get("rows", []) if x.get("mapping_confidence") == "HIGH"}
    intersection = sorted(set(events) & set(quotes))
    root = Path(out_root); (root / "markets" / "normalized").mkdir(parents=True, exist_ok=True)
    results = []
    bound_ids = sorted(set(quotes) & (set(events) | set(resolved)))
    for source_id in bound_ids:
        raw = events.get(source_id) or {"source_event_id": source_id, "date_raw": resolved[source_id]["tip_time_raw"], "league_family": resolved[source_id].get("league") or "7M_BASKETBALL", "team_1": resolved[source_id]["team_1"], "team_2": resolved[source_id]["team_2"], "source_path": str(p / "reverse")}
        tip = datetime.strptime(raw["date_raw"], "%Y,%m,%d,%H,%M,%S").replace(tzinfo=timezone.utc)
        eid = resolved.get(source_id, {}).get("canonical_event_id") or f"7M:{source_id}:{tip.isoformat()}"
        captured = meta["captured_at"]
        event = {"canonical_event_id": eid, **raw, "official_order_team_1": raw["team_1"], "official_order_team_2": raw["team_2"], "tip_time_utc": tip.isoformat(), "source_name": "7m", "source_url": "https://basket.7m.com.cn/free_gb.aspx", "source_group": "score_site", "upstream_provider": "7m", "match_confidence": "HIGH", "match_reason": "DIRECT_ID", "generated_at": captured}
        base = {"canonical_event_id": eid, "feed_provider": "7m", "source_name": "7m", "source_group": "score_site", "upstream_provider": "7m", "bookmaker": "7m_aggregate", "bookmaker_id": "4", "captured_at": captured, "overtime_rule": "UNKNOWN", "market_status": "OPEN", "raw_price_format": "hong_kong", "raw_snapshot_path": str(p / "odds.raw")}
        qs = []
        for quote_source in quotes[source_id]:
            for kind, market_type, selection in (("HB", "SPREAD", "home"), ("TP", "TOTAL", "over_under")):
                q = quote_source["records"].get(kind)
                if not q: continue
                qs.append(normalize(dict(base, company_id=quote_source["company_id"], company_name=quote_source["company_name"], market_type=market_type, period="FULL_GAME", selection_scope="MAIN", selection=selection, line=q["line"], raw_line=q["line"], raw_price=q["price_hk"], price=q["price_hk"] + 1, decimal_odds=q["price_hk"] + 1, source_quote_at=q["quote_timestamp"], executable_verified=False, observation_valid=True, market_observation_status="MARKET_OBSERVATION_VALID")))
        if qs:
            (root / "markets" / "normalized" / f"{eid.replace(':', '_')}.json").write_text(json.dumps({"event": event, "quotes": qs, "capture_session_id": meta["capture_session_id"]}, ensure_ascii=False, indent=2), encoding="utf8")
            results.append({"event": event, "quotes": qs})
    return {"session": meta, "direct_intersection_ids": intersection, "reverse_bound_ids": sorted(set(bound_ids) - set(intersection)), "events": results, "bound_count": len(results), "fresh_market_events": len(results), "market_freshness": "FRESH" if results else "STALE_OR_UNAVAILABLE"}

if __name__ == "__main__":
    import sys
    print(json.dumps(join_session(sys.argv[1], sys.argv[2]), ensure_ascii=False))
