from __future__ import annotations
import json
from datetime import datetime,timezone
from pathlib import Path
def enroll(final_file, archive_root):
    data=json.loads(Path(final_file).read_text(encoding='utf8')); root=Path(archive_root);root.mkdir(parents=True,exist_ok=True); rows=[]
    for e in data.get('events',[]):
        safe=e['canonical_event_id'].replace(':','_').replace('/','_')
        p=root/'forward_native'/safe;p.mkdir(parents=True,exist_ok=True)
        manifest={'canonical_event_id':e['canonical_event_id'],'archive_type':'FORWARD_NATIVE','tip_time_bj':e['tip_time_bj'],'pipeline_version':e['pipeline_version'],'input_generated_at':data['generated_at'],'captured_at':datetime.now(timezone.utc).isoformat(),'checkpoints':[]}
        for checkpoint in ('discovery','T-24h','T-6h','T-90m','T-30m','T-5m'):
            manifest['checkpoints'].append({'name':checkpoint,'attempted':True,'unavailable':True,'checkpoint_missed':checkpoint!='discovery'})
        (p/'archive_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8');rows.append(manifest)
    return rows
if __name__=='__main__':
 import sys;print(len(enroll(sys.argv[1],sys.argv[2])))
