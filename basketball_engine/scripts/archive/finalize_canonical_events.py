from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
BJ=ZoneInfo('Asia/Shanghai')
def finalize(provider_manifest, out_dir, run_id='step2e-fiba'):
    src=Path(provider_manifest); data=json.loads(src.read_text(encoding='utf8')); grouped={}
    generated=datetime.now(timezone.utc).isoformat()
    for e in data.get('events',[]):
        tip=datetime.fromisoformat(e['tip_utc'].replace('Z','+00:00')).astimezone(BJ)
        row=dict(e);row.update({'canonical_event_id':e.get('canonical_event_id') or f"FIBA_WOMEN:{e['team_1']}-{e['team_2']}-{e['tip_utc']}",'tip_time_utc':e['tip_utc'],'tip_time_bj':tip.isoformat(),'bj_date':tip.date().isoformat(),'pipeline_version':'step2-final-canonical-v1','generated_at':generated,'discovery_run_id':run_id,'source_run_ids':['step2e_fiba'],'schema_version':3})
        grouped.setdefault(tip.date().isoformat(),[]).append(row)
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    paths=[]
    for date,events in grouped.items():
        p=out/f'canonical_events_{date}.json';p.write_text(json.dumps({'schema_version':3,'pipeline_version':'step2-final-canonical-v1','generated_at':generated,'discovery_run_id':run_id,'events':events},ensure_ascii=False,indent=2),encoding='utf8');paths.append(str(p))
    return paths
if __name__=='__main__':
 import sys;print(finalize(sys.argv[1],sys.argv[2]))
