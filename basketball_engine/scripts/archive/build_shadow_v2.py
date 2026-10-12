from __future__ import annotations
import csv,json,glob
from pathlib import Path

def run(raw_root,out_root):
    out=Path(out_root);out.mkdir(parents=True,exist_ok=True);rows=[]
    # Only records with explicit completed scores are candidates for evaluation;
    # they still need independent pregame evidence before entering pricing.
    for p in glob.glob(str(Path(raw_root)/'thesportsdb_*.json')):
        try: data=json.load(open(p,encoding='utf-16'))
        except Exception: continue
        for e in data.get('events',[]):
            if str(e.get('home_score','')).isdigit() and str(e.get('away_score','')).isdigit():
                rows.append({'event_id':e.get('event_id'),'league':e.get('league'),'tip_time':e.get('utc_timestamp'),'archive_type':'RECONSTRUCTED_BACKFILL','evidence_quality':'D','pregame_eligible':False,'leakage_blocked':True,'evaluation_only':True,'reason':'no timestamped A/B pregame input archive'})
    for name,fields in [('replay_games.csv', ['event_id','league','tip_time','archive_type','evidence_quality','pregame_eligible','leakage_blocked','evaluation_only','reason']),('pricing_outputs.csv',['event_id','pricing_status','raw_fair_margin','structural_fair_margin','blended_fair_margin','closing_margin','raw_error_to_close','structural_error_to_close','blended_error_to_close','market_baseline_error_to_close']),('family_summary.csv',['model_family','count','mae_raw','mae_structural','mae_blended','mae_market_baseline'])]:
        with (out/name).open('w',newline='',encoding='utf8') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows if name=='replay_games.csv' else [])
    (out/'evidence_manifest.json').write_text(json.dumps({'archive_type_separation':True,'sample_count':len(rows),'eligible_pricing_games':0,'leakage_violations':0,'circularity_violations':0,'records':rows},ensure_ascii=False,indent=2),encoding='utf8')
    return len(rows)
if __name__=='__main__':
 import sys;print(run(sys.argv[1],sys.argv[2]))
