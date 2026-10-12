from __future__ import annotations
import json,glob
from pathlib import Path
try:
    from .price_game import price_game
except ImportError:
    from price_game import price_game

def run(raw_root,out):
    rows=[]
    for path in glob.glob(str(Path(raw_root)/'thesportsdb_*.json')):
        try: data=json.load(open(path,encoding='utf-16'))
        except Exception: continue
        for e in data.get('events',[]):
            if not (str(e.get('home_score','')).isdigit() and str(e.get('away_score','')).isdigit()): continue
            fam='WNBA' if 'WNBA' in str(e.get('league','')).upper() else 'NBA'
            # The local snapshots contain final scores but no timestamped pregame
            # efficiency/roster inputs; refuse to fabricate them.
            result=price_game({'league_family':fam,'canonical_event_id':e.get('event_id')},{},{},{})
            rows.append({'event_id':e.get('event_id'),'date':e.get('date'),'league':e.get('league'),'home':e.get('home'),'away':e.get('away'),'final_home':e.get('home_score'),'final_away':e.get('away_score'),'pricing_cutoff':e.get('date')+'T00:00:00','pricing':result,'post_tip_evaluation_only':True})
    Path(out).parent.mkdir(parents=True,exist_ok=True);Path(out).write_text(json.dumps({'sample_count':len(rows),'rows':rows[:30]},ensure_ascii=False,indent=2),encoding='utf8');return len(rows)
if __name__=='__main__':
 import sys;print(run(sys.argv[1],sys.argv[2]))
