from __future__ import annotations
from statistics import median
def consensus(rows):
    valid=[r for r in rows if r.get('market_status')=='OPEN' and not r.get('stale',False)]
    groups={}
    for r in valid: groups.setdefault(r.get('upstream_provider',r.get('source_name')),[]).append(r)
    reps=[max(v,key=lambda x:x.get('captured_at','')) for v in groups.values()]
    vals=[float(r['line']) for r in reps if r.get('line') is not None]
    return {'consensus_line':median(vals) if vals else None,'provider_count':len(reps),'dispersion':(max(vals)-min(vals)) if vals else None,'min_line':min(vals) if vals else None,'max_line':max(vals) if vals else None,'median_line':median(vals) if vals else None,'independent_providers':sorted(groups)}
