#!/usr/bin/env python3
"""Production Step 2B collectors. Discovery only; no pricing or ledger writes."""
from __future__ import annotations
import json, re, ssl, time
from datetime import datetime
from pathlib import Path
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener, urlopen
from urllib.error import HTTPError, URLError
from discover_events import BJ, discover_independently, normalize, classify_family
from reconcile_events import reconcile

ROOT = Path(__file__).parents[3] / "outputs" / "basketball_odds_trader"
_ESPN_DIRECT_OPENER = build_opener(
    ProxyHandler({}),
    HTTPSHandler(context=ssl.create_default_context()),
)

def fetch(url, source, group, provider, timeout=12, direct=False):
    started=time.perf_counter(); captured=datetime.now(BJ).isoformat()
    health={"source_name":source,"source_group":group,"upstream_provider":provider,"attempted":True,"success":False,"http_status":None,"error_type":None,"latency":None,"event_count":0,"last_success_at":None,"raw_snapshot_path":None,"captured_at":captured,"source_url":url}
    try:
        req=Request(url,headers={"User-Agent":"Mozilla/5.0 basketball-odds-trader-step2b","Accept":"application/json"})
        opener = _ESPN_DIRECT_OPENER if direct else None
        response_ctx = opener.open(req, timeout=timeout) if opener else urlopen(req, timeout=timeout)
        with response_ctx as resp:
            health["http_status"]=resp.status; body=resp.read(); health["success"]=True
        health["latency"]=round(time.perf_counter()-started,3); health["last_success_at"]=captured
        rawdir=ROOT/"raw"/"production_step2b"; rawdir.mkdir(parents=True,exist_ok=True)
        path=rawdir/(source+"_"+captured[:10]+".bin"); path.write_bytes(body); health["raw_snapshot_path"]=str(path)
        if not body.strip(): health["error_type"]="empty_valid_response"
        return body,health
    except HTTPError as exc:
        health.update(http_status=exc.code,error_type="403" if exc.code==403 else "http_error",latency=round(time.perf_counter()-started,3)); return b"",health
    except URLError as exc:
        reason=str(exc.reason).lower(); kind="tls_error" if "ssl" in reason or "tls" in reason else "timeout" if "timed out" in reason else "network_error"
        health.update(error_type=kind,latency=round(time.perf_counter()-started,3)); return b"",health
    except TimeoutError:
        health.update(error_type="timeout",latency=round(time.perf_counter()-started,3)); return b"",health
    except Exception as exc:
        health.update(error_type="parse_error",latency=round(time.perf_counter()-started,3),error=str(exc)); return b"",health

def json_events(url, source, group, provider, direct=False):
    body, health=fetch(url,source,group,provider,direct=direct)
    if not body: return [],health
    try:
        obj=json.loads(body); rows=obj.get("events",obj.get("event",[])) if isinstance(obj,dict) else obj
        events=[]
        for x in rows or []:
            comp=str(x.get("league",x.get("name",source))); competitors=x.get("competitions",[{}])[0].get("competitors",[]) if x.get("competitions") else []
            if len(competitors)<2: continue
            events.append({"league_family":classify_family(comp),"official_game_id":x.get("id"),"team_1":competitors[0].get("team",{}).get("displayName"),"team_2":competitors[1].get("team",{}).get("displayName"),"tip_utc":x.get("date"),"source_url":url,"source_group":group,"upstream_provider":provider,"source_confidence":"high"})
        health["event_count"]=len(events); health["error_type"]="source_zero_result" if not events else None; return events,health
    except Exception as exc:
        health.update(error_type="schema_changed",error=str(exc)); return [],health

def html_schedule(url, source, group, provider, family, date):
    body, health=fetch(url,source,group,provider)
    text=body.decode("utf-8","ignore")
    events=[]
    # Official pages often expose names and date but not a stable JSON payload.
    if date in text or date.replace("-", ".") in text or date[5:].replace("-", ".") in text:
        health["error_type"]="parse_error"; health["note"]="page reachable; no stable event schema extracted"
    else: health["error_type"]="source_zero_result"
    health["event_count"]=len(events); return events,health

def build_adapters():
    adapters={}; health_sources={}
    def add_json(name,url,group,provider,direct=False):
        def adapter(date):
            rows,h=json_events(url.replace("{date}",date),name,group,provider,direct=direct); health_sources[name]=h; return rows
        adapters[name]=adapter
    add_json("espn_scoreboard","https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date}","broad","espn",direct=True)
    add_json("sofascore_scheduled_events","https://www.sofascore.com/api/v1/sport/basketball/scheduled-events/{date}","broad","sofascore")
    add_json("thesportsdb_basketball","https://www.thesportsdb.com/api/v1/json/123/eventsday.php?d={date}&s=Basketball","broad","thesportsdb")
    for name,url,group,provider,family in [
        ("fiba_event_calendar","https://www.fiba.basketball/en/events","official","fiba","FIBA_MEN"),
        ("fiba_games_results","https://www.fiba.basketball/en/events/fiba-womens-basketball-world-cup-2026","official","fiba","FIBA_WOMEN"),
        ("cba_specific_schedule","https://m.qiumiwu.com/league/cba/game","league_specific","qiumiwu","CBA_SUMMER"),
        ("nbl_official_schedule","https://www.nbl.com.au/schedule","official","nbl","NBL_AU"),
        ("odds_board_discovery","https://m.dashbet.com.au/Sport/Basketball/Mexican_LNBP/Matches","odds_board","generationweb","OTHER_DISCOVERED")]:
        def adapter(date,n=name,u=url,g=group,p=provider,f=family):
            rows,h=html_schedule(u,n,g,p,f,date); health_sources[n]=h; return rows
        adapters[name]=adapter
    return adapters,health_sources

def run(date):
    adapters, health=build_adapters(); raw,union,status=discover_independently(adapters,date)
    events,conflicts=reconcile(union)
    for source,rows in raw.items():
        if source in health: health[source]["event_count"]=len(rows); health[source]["source_status"]=status.get(source)
        else: health[source]={"source_name":source,"source_group":"unknown","upstream_provider":source,"attempted":True,"success":bool(rows),"error_type":"source_zero_result" if not rows else None,"event_count":len(rows),"captured_at":datetime.now(BJ).isoformat()}
    return events,conflicts,health,status

if __name__ == "__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("--date",required=True); p.add_argument("--output",required=True); args=p.parse_args()
    events,conflicts,health,status=run(args.date)
    out={"schema_version":2,"bj_date":args.date,"run_type":"LIVE","events":events,"conflicts":conflicts,"source_health":health,"source_status":status}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True); Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"live_adapters":len(status),"successful":sum(1 for x in health.values() if x.get("success")),"unavailable":sum(1 for x in health.values() if not x.get("success")),"union_events":len(events),"conflicts":len(conflicts)},ensure_ascii=False))
