from __future__ import annotations
import json
from datetime import datetime,timezone
from pathlib import Path
def append(root,record):
    p=Path(root);p.mkdir(parents=True,exist_ok=True); rid=record.get('prediction_id')
    f=p/f'{rid}.json';
    if f.exists(): raise FileExistsError('first-write immutable')
    x=dict(record);x.setdefault('frozen_at',datetime.now(timezone.utc).isoformat());x['kelly_usable']=False;x['real_stake']=0;x['real_bet_flag']=False
    f.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8');return str(f)
def append_settlement(root,prediction_id,settlement):
    p=Path(root)/f'{prediction_id}.settlements.jsonl';p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('a',encoding='utf8') as f:f.write(json.dumps(settlement,ensure_ascii=False)+'\n')
