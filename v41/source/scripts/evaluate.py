"""Single locked-model test evaluation. Does not choose or change parameters."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from v41.common import *
from v41.probability import predict
from v41.forward import calibration_metrics
from v41.health import probability_health
target=ROOT/'diagnostics/locked_test_evaluation.json'
if target.exists():print(canonical(read(target)));raise SystemExit
m=read(ROOT/'models/V4.1_R1.json');rows=[r for r in read(ROOT/'data/training_dataset.json') if r['eligible'] and r['partition']=='test'];pred=[predict(m,r['features'],r['snapshot']) for r in rows];labels=[r['label'] for r in rows]
out={'model_artifact_id':m['artifact_id'],'test_used_for_selection':False,'historical_research_not_forward':True,'n':len(rows),'metrics':{k:calibration_metrics([p[k] for p in pred],labels) for k in ['bucket_probability','raw_probability','calibrated_probability']},'probability_health':probability_health([{'snapshot':r['snapshot'],'probability':p} for r,p in zip(rows,pred)]),'T30_test':{k:calibration_metrics([p[k] for r,p in zip(rows,pred) if r['snapshot_window']=='T-30'],[r['label'] for r in rows if r['snapshot_window']=='T-30']) for k in ['bucket_probability','raw_probability','calibrated_probability']}}
write(target,out,immutable=True);print(canonical(out))
