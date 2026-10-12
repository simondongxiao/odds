from __future__ import annotations
import csv,json,glob
from pathlib import Path
from .validate_evidence_bundle import validate

def run(root,shadow):
    root=Path(root); rec=root/'reconstructed'; rec.mkdir(parents=True,exist_ok=True); candidates=[]
    # Existing completed raw records are candidates only. No postgame facts are
    # promoted to inputs; bundles remain audit_only until pregame evidence exists.
    for fp in glob.glob(str(root/'raw'/'thesportsdb_*.json')):
        try: d=json.load(open(fp,encoding='utf-16'))
        except Exception: continue
        for e in d.get('events',[]):
            if not (str(e.get('home_score','')).isdigit() and str(e.get('away_score','')).isdigit()): continue
            eid=f"historical-{e.get('event_id')}"; p=rec/eid;p.mkdir(exist_ok=True)
            event={'canonical_event_id':eid,'league_family':'WNBA' if 'WNBA' in str(e.get('league','')).upper() else 'NBA','tip_time':e.get('utc_timestamp'),'archive_type':'RECONSTRUCTED_BACKFILL'}
            (p/'event.json').write_text(json.dumps(event,indent=2),encoding='utf8')
            for name in ('team_strength','roster','minutes','injuries','recent_form','schedule_context','market','pricing_input','frozen_pricing_output','evaluation'):
                (p/(name+'.json')).write_text('{}',encoding='utf8')
            manifest={'canonical_event_id':eid,'pricing_cutoff':e.get('utc_timestamp'),'archive_type':'RECONSTRUCTED_BACKFILL','evidence':[],'status':'audit_only','reason':'historical snapshot has result but no timestamped pregame evidence'}
            (p/'evidence_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8');candidates.append(validate(p))
    s=Path(shadow);s.mkdir(parents=True,exist_ok=True)
    fields=['event_id','model_family','status','pricing_status','raw_fair_margin','structural_fair_margin','blended_fair_margin','closing_margin','raw_error_to_close','structural_error_to_close','blended_error_to_close','market_baseline_error_to_close']
    for name in ('eligible_games.csv','pricing_outputs.csv','family_summary.csv','evidence_quality.csv','leakage_audit.csv'):
        with (s/name).open('w',newline='',encoding='utf8') as f: csv.DictWriter(f,fieldnames=fields).writeheader()
    (s/'evidence_manifest.json').write_text(json.dumps({'candidates':candidates,'eligible':0,'leakage_violations':0,'circularity_violations':0},indent=2),encoding='utf8')
    return candidates
if __name__=='__main__':
 import sys;print(len(run(sys.argv[1],sys.argv[2])))
