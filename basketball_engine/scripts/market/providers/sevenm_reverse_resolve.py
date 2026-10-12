from __future__ import annotations
import json, re, urllib.request
from datetime import datetime, timezone
from pathlib import Path

def _get(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://basket.7m.com.cn/free_gb.aspx"})
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.status, response.read()

def _var(text: str, name: str) -> str | None:
    m = re.search(r"var\s+" + re.escape(name) + r"\s*=\s*'([^']*)'", text)
    return m.group(1) if m else None

def resolve(session_dir: str | Path, mappings_path: str | Path) -> dict:
    session = Path(session_dir)
    meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
    out_dir = session / "reverse"; out_dir.mkdir(exist_ok=True)
    rows = []
    for odds_id in meta.get("odds_ids_union", []):
        url = f"https://bdata.7m.com.cn/analyse/gb/{odds_id}.shtml"
        row = {"odds_id": odds_id, "url_attempted": url, "mapping_method": "ODDS_ID_DETAIL_PAGE", "mapping_confidence": "UNRESOLVED"}
        try:
            status, page = _get(url); row["http_status"] = status
            (out_dir / f"{odds_id}.html").write_bytes(page)
            html = page.decode("utf-8-sig", errors="replace")
            title = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
            row["page_title"] = re.sub(r"<[^>]+>", " ", title.group(1)).strip() if title else None
            js_url = f"https://bdata.7m.com.cn/analyse/gb/js/{str(odds_id)[:-3]}/{odds_id}.js"
            js_status, js = _get(js_url); row["identity_js_status"] = js_status
            (out_dir / f"{odds_id}.js").write_bytes(js)
            text = js.decode("utf-8-sig", errors="replace")
            row.update({"league": _var(text, "a_mn"), "team_1": _var(text, "a_hn"), "team_2": _var(text, "a_an"), "tip_time_raw": _var(text, "a_tm"), "detail_id": odds_id, "live_event_id": odds_id})
            if row.get("team_1") and row.get("team_2") and row.get("tip_time_raw"):
                tip = datetime.strptime(row["tip_time_raw"], "%Y,%m,%d,%H,%M,%S").replace(tzinfo=timezone.utc)
                row["tip_time_utc"] = tip.isoformat()
                row["canonical_event_id"] = f"7M:{odds_id}:{tip.isoformat()}"
                row["mapping_confidence"] = "HIGH"
        except Exception as exc:
            row["error"] = type(exc).__name__ + ": " + str(exc)
        rows.append(row)
    mp = Path(mappings_path); mp.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else []
    by_id = {str(x.get("odds_id")): x for x in old}
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        if row.get("mapping_confidence") == "HIGH":
            row["first_seen_at"] = by_id.get(row["odds_id"], {}).get("first_seen_at", now)
            row["last_verified_at"] = now
            by_id[row["odds_id"]] = row
    mp.write_text(json.dumps(list(by_id.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    (session / "reverse_resolution.json").write_text(json.dumps({"session": meta, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"rows": rows, "resolved": sum(x.get("mapping_confidence") == "HIGH" for x in rows), "mapping_path": str(mp)}

