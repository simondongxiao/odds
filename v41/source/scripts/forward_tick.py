"""Scheduled read/collect/freeze/settle only. Never auto-train or change R1."""
import sys,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from v41.common import *
from v41.runner import tick
from v41.forward import reconcile
days={now().date().isoformat(),(now().date()-dt.timedelta(days=1)).isoformat()}
for r in reconcile():
    if r['settlement_status']!='SETTLED':days.add(r['date'])
errors=[]
for day in sorted(days):
    try:tick(day)
    except Exception as e:errors.append({'list_date':day,'error':str(e)});traceback.print_exc()
write(ROOT/'reports/last_scheduled_run.json',{'completed_at':now().isoformat(),'days':sorted(days),'errors':errors})
if errors:raise SystemExit(1)
