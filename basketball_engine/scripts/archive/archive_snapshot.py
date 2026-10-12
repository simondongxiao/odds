from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

def save_immutable(root, archive_type, event_id, payload):
    if archive_type not in {'RECONSTRUCTED_BACKFILL','FORWARD_NATIVE'}: raise ValueError(archive_type)
    stamp=datetime.now().strftime('%Y%m%dT%H%M%S%fZ')
    path=Path(root)/('reconstructed' if archive_type=='RECONSTRUCTED_BACKFILL' else 'forward_native')/f'{event_id}_{stamp}.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    payload=dict(payload,archive_type=archive_type,archived_at=stamp,immutable=True)
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    return str(path)

def eligible_input(record, cutoff):
    evidence=record.get('evidence_quality','D')
    if evidence not in {'A','B'}: return False
    published=record.get('source_published_at') or record.get('captured_at')
    return bool(published and published<=cutoff)
