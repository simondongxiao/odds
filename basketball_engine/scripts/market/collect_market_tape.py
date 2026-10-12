from pathlib import Path
import json
from .normalize_market import normalize
def save_snapshot(root,row):
    p=Path(root)/'raw';p.mkdir(parents=True,exist_ok=True);name=str(row['canonical_event_id']).replace(':','_')+'_'+str(row.get('captured_at','now')).replace(':','')+'.json';f=p/name;f.write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf8');return str(f)
