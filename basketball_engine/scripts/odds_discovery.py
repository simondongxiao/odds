"""Odds routing for canonical events.

This router consumes canonical identities and existing quote adapters. A
schedule source is never treated as an odds source, and an absent quote is
reported per event instead of deleting the event.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

BJ=ZoneInfo("Asia/Shanghai")

def _norm(value):
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").casefold())

def _time(value):
    try:return datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(BJ)
    except Exception:return None

def exact_team_time(event, quote_event, tolerance_minutes=30):
    a={_norm(event.get("team1_name")),_norm(event.get("team2_name"))}
    b={_norm(quote_event.get("team1_name")),_norm(quote_event.get("team2_name"))}
    ta,tb=_time(event.get("tip_at")),_time(quote_event.get("tip_at"))
    return bool(a and a==b and ta and tb and abs((ta-tb).total_seconds())<=tolerance_minutes*60)

def route(events, quotes):
    by_event={}
    for q in quotes: by_event.setdefault(q.get("event_id"),[]).append(q)
    result=[]
    for event in events:
        direct=by_event.get(event.get("event_id"),[])
        if direct:
            result.append({"event_id":event.get("event_id"),"market_status":"MARKET_FOUND","market_match_method":"DIRECT_ID","quotes":direct})
            continue
        result.append({"event_id":event.get("event_id"),"market_status":"NO_MARKET","market_match_method":"NO_MATCH","quotes":[],"odds_attempted":True})
    return result

