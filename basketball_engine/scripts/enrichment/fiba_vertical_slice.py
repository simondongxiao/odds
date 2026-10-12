from __future__ import annotations
from datetime import datetime,timezone
def evidence_gate(rows, cutoff):
    accepted=[];blocked=[]
    for row in rows or []:
        t=row.get('historical_effective_at') or row.get('source_published_at') or row.get('captured_at','')
        if t and t<=cutoff and row.get('pregame_eligible',False) and row.get('evidence_quality') in {'A','B'}: accepted.append(row)
        else: blocked.append(dict(row,leakage_blocked=True))
    return accepted,blocked
def priceability(inputs):
    required=('national_prior','roster','player_mapping','role_minutes','recent_form','schedule_rest')
    return {'ready':all(inputs.get(k) for k in required),'missing':[k for k in required if not inputs.get(k)],'inputs':required}
