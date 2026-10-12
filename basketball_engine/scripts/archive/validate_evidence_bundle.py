from __future__ import annotations
import json
from pathlib import Path

REQUIRED=('event.json','evidence_manifest.json','team_strength.json','roster.json','minutes.json','injuries.json','recent_form.json','schedule_context.json','market.json','pricing_input.json','frozen_pricing_output.json','evaluation.json')
def validate(path):
    p=Path(path); issues=[]; manifest={}
    for name in REQUIRED:
        if not (p/name).exists(): issues.append('missing:'+name)
    if (p/'evidence_manifest.json').exists():
        manifest=json.loads((p/'evidence_manifest.json').read_text(encoding='utf8'))
        cutoff=manifest.get('pricing_cutoff','')
        for ev in manifest.get('evidence',[]):
            if ev.get('evidence_quality') not in {'A','B'}: issues.append('quality_rejected:'+str(ev.get('source_name')))
            if not ev.get('raw_snapshot_path') or not Path(ev['raw_snapshot_path']).exists(): issues.append('raw_missing:'+str(ev.get('source_name')))
            if not ev.get('pregame_eligible'): issues.append('not_pregame:'+str(ev.get('source_name')))
            if cutoff and (ev.get('source_published_at') or ev.get('captured_at',''))>cutoff: issues.append('timestamp_leak:'+str(ev.get('source_name')))
    return {'event_id':p.name,'eligible':not issues,'status':'eligible' if not issues else 'audit_only','issues':issues}
