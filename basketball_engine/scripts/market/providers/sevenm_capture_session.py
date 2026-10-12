from __future__ import annotations
import json, re, uuid, urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://basket.7m.com.cn/free_gb.aspx"})
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read()

def capture(root: str | Path, target_bj: str | None = None) -> dict:
    target = date.fromisoformat(target_bj or datetime.now(timezone(timedelta(hours=8))).date().isoformat())
    buckets = [target - timedelta(days=1), target, target + timedelta(days=1)]
    sid = uuid.uuid4().hex
    captured = datetime.now(timezone.utc).isoformat()
    session = Path(root) / sid
    session.mkdir(parents=True, exist_ok=True)
    urls = {"page": "https://basket.7m.com.cn/free_gb.aspx", "today": "https://js-basket.7m.com.cn/datafile/today.js"}
    # The real selector in free_gb.aspx exposes only these five legal pk values.
    # js_odds.js maps pk=1 (S2) to comlive_4 and pk=4 (威) to comlive_1.
    companies = {"0": "澳", "1": "S2", "2": "易", "3": "12", "4": "威"}
    for company_id in ("0", "1", "2", "3", "4"):
        urls[f"odds_company_{company_id}"] = f"https://js-basket.7m.com.cn/odds/comlive_{4 if company_id == '1' else 1 if company_id == '4' else company_id}.js"
    for bucket in buckets:
        key = bucket.strftime("%Y%m%d")
        urls[f"event_{key}_s2"] = f"https://bdata.7m.com.cn/datafile/{key}/S2_fgb1.js"
        urls[f"event_{key}_f"] = f"https://bdata.7m.com.cn/datafile/{key}/fgb1.js"
    blobs = {key: get(url) for key, url in urls.items()}
    for key, blob in blobs.items(): (session / f"{key}.raw").write_bytes(blob)
    event_blob = b"".join(blob for key, blob in blobs.items() if key.startswith("event_"))
    event_ids = set(re.findall(rb"bDt\[(\d+)\]", event_blob))
    odds_by_company = {}
    for company_id, company_name in companies.items():
        blob = blobs[f"odds_company_{company_id}"]
        ids = set(re.findall(rb"bOdds\[\d+\]\[(\d+)\]", blob))
        odds_by_company[company_id] = {"company_name": company_name, "odds_id_count": len(ids), "odds_ids": sorted(x.decode() for x in ids), "raw_path": str(session / f"odds_company_{company_id}.raw")}
    odds_union = set().union(*(set(x["odds_ids"]) for x in odds_by_company.values()))
    meta = {"capture_session_id": sid, "captured_at": captured, "run_started_at": captured, "target_bj_date": target.isoformat(), "source_buckets": [x.isoformat() for x in buckets], "event_id_count": len(event_ids), "odds_id_count": len(odds_union), "odds_ids_by_company": odds_by_company, "odds_ids_union": sorted(odds_union), "direct_intersection_count": len(event_ids & {x.encode() for x in odds_union}), "event_ids": sorted(x.decode() for x in event_ids), "odds_ids": sorted(odds_union), "direct_intersection_ids": sorted(x.decode() for x in event_ids & {x.encode() for x in odds_union}), "raw_paths": {key: str(session / f"{key}.raw") for key in urls}, "same_session": True, "company_selector_evidence": "page.html: select#odds_tp option values 0-4; js_odds.js curCom mapping"}
    (session / "session.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta

if __name__ == "__main__":
    import sys
    print(json.dumps(capture(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None), ensure_ascii=False))
