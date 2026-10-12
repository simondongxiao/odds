#!/usr/bin/env python3
"""Historical Step 2C replay using public article pages, never betting inputs."""
from __future__ import annotations
import json, sys, urllib.request
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from parsers.cba_article_parser import parse_cba_article

SCHEDULE=("https://www.qiumiwu.com/news/1991329799975", "2026-08-21T14:40:00+08:00")
RESULTS=("https://www.98zhibo.com/cba/", "2026-09-06T23:59:00+08:00")

def fetch(url):
    req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r: return r.read().decode("utf-8", "ignore")

def run(out_dir):
    out_dir=Path(out_dir); raw=out_dir/"raw"/"step2c"; raw.mkdir(parents=True, exist_ok=True)
    all_rows=[]
    for url,published in (SCHEDULE, RESULTS):
        try:
            html=fetch(url); (raw/("schedule.html" if url==SCHEDULE[0] else "results.html")).write_text(html, encoding="utf-8")
            all_rows += parse_cba_article(html,url,published)
        except Exception as e:
            all_rows.append({"source_url":url,"error_type":"fetch_error","error":str(e)})
    return all_rows

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("--output",required=True); a=p.parse_args()
    rows=run(a.output); print(json.dumps({"rows":len(rows),"target_rows":len([x for x in rows if x.get("date")=="2026-09-06"])},ensure_ascii=False))
