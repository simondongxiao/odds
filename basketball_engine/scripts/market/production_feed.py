from __future__ import annotations
import json,time,urllib.request,urllib.error
from datetime import datetime,timezone
from pathlib import Path

SOURCES=[('oddschecker','SEARCH_DISCOVERY','oddschecker','https://www.oddschecker.com/us/basketball/fiba-world-cup-womens/usa-women-at-spain-women'),('caliente','HTML','caliente','https://sports.caliente.mx/es_MX/e/33119456/Espa%C3%B1a-Mujeres-vs-EE.UU-Mujeres'),('betmgm','HTML','betmgm','https://www.betmgm.com/en/sports/events/2026-fiba-world-cup-women-19811365')]
def run(root):
    root=Path(root);raw=root/'markets'/'raw';raw.mkdir(parents=True,exist_ok=True);health=[]
    for name,kind,upstream,url in SOURCES:
        start=time.time(); item={'source_name':name,'source_type':kind,'upstream_provider':upstream,'attempted':True,'url':url,'captured_at':datetime.now(timezone.utc).isoformat(),'quote_count':0,'executable_quote_count':0}
        try:
            q=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}); data=urllib.request.urlopen(q,timeout=20); body=data.read(); item.update({'reachable':True,'http_status':data.status,'parsed':False,'error':'no_verified_quote_parser','latency':round(time.time()-start,3)});(raw/(name+'.html')).write_bytes(body)
        except urllib.error.HTTPError as e: item.update({'reachable':False,'http_status':e.code,'parsed':False,'error':'403' if e.code==403 else 'http_error','latency':round(time.time()-start,3)})
        except Exception as e: item.update({'reachable':False,'parsed':False,'error':type(e).__name__,'latency':round(time.time()-start,3)})
        health.append(item)
    root.joinpath('markets').mkdir(exist_ok=True);(root/'markets'/'source_health_2026-09-13.json').write_text(json.dumps(health,ensure_ascii=False,indent=2),encoding='utf8');return health
if __name__=='__main__':
 import sys;print(json.dumps(run(Path(sys.argv[1])),ensure_ascii=False))
