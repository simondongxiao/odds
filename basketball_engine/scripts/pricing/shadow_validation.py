from __future__ import annotations
import json
from pathlib import Path
from .price_game import price_game

def run(out_dir):
    mature={'pace':100,'ortg':115,'drtg':108,'team_strength_quality':90,'roster_quality':90,'minutes_quality':85,'injury_quality':85,'schedule_quality':85,'market_anchor_quality':90,'historical_sample_quality':90}
    cases=[('nba_mature',{'league_family':'NBA'},mature,dict(mature,ortg=110),{'margin':5}),
           ('fiba_sparse',{'league_family':'FIBA_WOMEN'},dict(prior=8,roster_value=2),dict(prior=0,roster_value=0),{'margin':4}),
           ('cba_summer',{'league_family':'CBA_SUMMER'},dict(prior_margin=3),dict(prior_margin=0),{'margin':2}),
           ('no_inputs',{'league_family':'NBA'},{},{},{})]
    result=[]
    for name,e,h,a,m in cases:
        r=price_game(e,h,a,m); result.append({'case':name,'pricing_status':r['pricing_status'],'model_family':r.get('model_family'),'finite':all(v is None or isinstance(v,(int,float)) for v in r.values() if not isinstance(v,(dict,list))),'model_weight':r.get('model_weight'),'uncertainty':r.get('uncertainty')})
    p=Path(out_dir);p.mkdir(parents=True,exist_ok=True);(p/'shadow_results.json').write_text(json.dumps(result,indent=2),encoding='utf8');return result
if __name__=='__main__':
 import sys;print(json.dumps(run(sys.argv[1]),ensure_ascii=False))
