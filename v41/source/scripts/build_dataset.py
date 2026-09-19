import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from v41.common import *
from v41.snapshots import historical_inventory,window_name
from v41.features import build
histories,finals,rejected=historical_inventory();rows=[];cfg=config('model_config');split=cfg['split']
for mid,path in histories.items():
    if mid not in finals:continue
    final=finals[mid];path=sorted(path,key=lambda s:s['quote_at'])
    # One match one sample; select nearest observed prematch point, never using the result.
    s=min(path,key=lambda x:abs(x['minutes_to_kickoff']-30))
    if (s['home'],s['away'])!=(final['home'],final['away']):continue
    if clock(final['result_available_at'])<=clock(s['quote_at']):continue
    if s['list_date']>split['test_end']:continue
    f=build(s,path,s['quote_at']);hg,ag=map(int,final['score'].split('-'));margin=hg-ag if s['giving_team']==s['home'] else ag-hg
    label=result_for_margin(margin,-abs(s['handicap']))
    partition='train' if s['list_date']<=split['train_end'] else 'validation' if split['validation_start']<=s['list_date']<=split['validation_end'] else 'test'
    cutoff=split['train_label_cutoff'] if partition=='train' else split['calibration_label_cutoff'] if partition=='validation' else now().isoformat()
    valid=clock(final['result_available_at'])<=clock(cutoff) and clock(s['quote_at'])<clock(cutoff)
    row={'match_id':mid,'list_date':s['list_date'],'partition':partition,'eligible':valid,'exclusion':None if valid else 'RESULT_NOT_AVAILABLE_BY_SPLIT_CUTOFF','decision_at':s['quote_at'],'result_available_at':final['result_available_at'],'training_cutoff':cutoff,'snapshot':s,'features':f,'label':label,'result_source':final,'snapshot_window':window_name(s['minutes_to_kickoff']),'use':'HISTORICAL_RESEARCH_NOT_FORWARD'}
    rows.append(row)
rows.sort(key=lambda r:(r['decision_at'],r['match_id']))
write(ROOT/'data/training_dataset.json',rows)
summary={'total':len(rows),'eligible':{p:sum(r['partition']==p and r['eligible'] for r in rows) for p in ['train','validation','test']},'standard_window_counts':{p:{w:sum(r['partition']==p and r['eligible'] and r['snapshot_window']==w for r in rows) for w in ['T-180','T-120','T-60','T-30','T-15','T-5','OUTSIDE_STANDARD_WINDOWS']} for p in ['train','validation','test']},'exclusions':dict(rejected),'strict_as_of':True,'random_split':False}
write(ROOT/'diagnostics/dataset_audit.json',summary);print(canonical(summary))
