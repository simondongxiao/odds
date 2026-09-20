"""Independent forward entry point. Never refreshes or writes original V3/V4."""
import argparse,traceback
from .common import *
from .snapshots import collect,paths_for,windows,window_name
from .features import build
from .probability import train,predict
from .decision import decide,freeze
from .control import run as control_run,verify_original as verify_original_baseline
from .forward import reconcile,comparison
from .health import health

def verify_original(allow_daily_outputs=True):return verify_original_baseline(allow_daily_outputs)

def tick(day):
    verify_original(True);model=read(ROOT/'models/V4.1_R1.json')
    for name,sha in model['config_hashes'].items():
        if filehash(ROOT/'config'/f'{name}.yaml')!=sha:raise ValueError('VERSION_CONFIG_CHANGED_REQUIRES_R2')
    roster,snaps,info=collect(day);current=now();runid=current.strftime('%Y%m%d_%H%M%S_%f');control={};control_error=None
    try:control=control_run(day,info['raw_csv'],runid)
    except Exception as e:control_error=type(e).__name__+':'+str(e)
    byid={s['match_id']:s for s in snaps};cards=[]
    for mid,rosterrow in roster.items():
        path=ROOT/'decisions'/day/(str(mid)+'.json')
        if path.exists():
            frozen=read(path);cards.append({**frozen,'window_status':'FROZEN_PRIMARY_T30'});continue
        s=byid.get(str(mid));card={'match_id':str(mid),'list_date':day,'roster':rosterrow,'window_status':'MISSING_OR_NON_PREMATCH','decision':{'grade':'N','action':'NO BET','decision_reason':['NO_VALID_PREMATCH_SNAPSHOT']}}
        if s:
            history=paths_for(day,mid);win=windows(history,current);card.update(snapshot=s,windows={k:{'status':v['status'],'snapshot_id':v['snapshot']['snapshot_id'] if v['snapshot'] else None} for k,v in win.items()},window_status='WAIT_PRIMARY_WINDOW' if s['minutes_to_kickoff']>40 else 'MISSED_PRIMARY_WINDOW' if s['minutes_to_kickoff']<25 else 'PRIMARY_T30')
            if s['valid_market'] and s['handicap'] and s['euro']:
                at=now();f=build(s,history,at);p=predict(model,f,s);d=decide(p,s,f,at);card.update(features=f,probability={k:v for k,v in p.items() if k!='ensemble'},decision=d)
                write(ROOT/'features'/day/str(mid)/(f['feature_id']+'.json'),f,immutable=True)
                if window_name(s['minutes_to_kickoff'])=='T-30' and 0<=(at-clock(s['quote_at'])).total_seconds()/60<=config('snapshot_policy')['max_quote_age_minutes']:
                    c=control.get(str(mid))
                    if c is not None and c.get('quote_at') and abs((clock(c['quote_at'])-clock(s['quote_at'])).total_seconds())<2 and clock(c['decision_at'])<clock(s['kickoff_at']) and d.get('grade') in 'ABC':
                        frozen=freeze(s,f,p,d,model,at,c);card.update(frozen,window_status='FROZEN_PRIMARY_T30')
                    else:card['window_status']='CONTROL_PAIR_UNAVAILABLE_NO_FREEZE' if c is None or not c.get('quote_at') else 'NO_ABC_NO_FREEZE'
            else:card['decision']['decision_reason']=['NEUTRAL_PK' if s['handicap']==0 else 'MISSING_MARKET']
        cards.append(card)
    rows=reconcile();comp=comparison(rows);checks=health(cards,rows);frozen=[c for c in cards if c.get('frozen_at')]
    result={'list_date':day,'generated_at':now().isoformat(),'model':{k:model[k] for k in ['model_version','model_type','calibration_version','calibration_state','temperature','train_count','validation_count','artifact_id']},'status':'SHADOW ONLY / NOT FOR PRODUCTION','real_money':False,'snapshot_policy':config('snapshot_policy'),'summary':{'total':len(cards),'computed_preview':sum(bool(c.get('probability')) for c in cards),'frozen':len(frozen),'candidates':sum(c['decision']['grade'] in 'ABC' for c in frozen),'grades':{g:sum(c['decision']['grade']==g for c in frozen) for g in 'ABCN'},'giving':sum(c['decision'].get('candidate_side')=='giving' for c in frozen),'receiving':sum(c['decision'].get('candidate_side')=='receiving' for c in frozen),'latest_freeze':max((c['frozen_at'] for c in frozen),default=None)},'collection':info,'control_error':control_error,'health':checks,'comparison':comp,'cards':cards,'original_control_verification':verify_original()}
    write(ROOT/'reports'/f'{day}.json',result);write(ROOT/'reports/runs'/f'{runid}.json',result,immutable=True)
    from .webpage import render
    render(result,rows);print(canonical({'list_date':day,**result['summary'],'control_error':control_error,'original_v4_unchanged':True}));return result
def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['train','tick','render','verify']);p.add_argument('--list-date',default=now().date().isoformat());a=p.parse_args()
    if a.command=='train':m=train();print(canonical({'model':m['model_version'],'train':m['train_count'],'validation':m['validation_count']}))
    elif a.command=='tick':tick(a.list_date)
    elif a.command=='verify':print(canonical(verify_original()))
    else:
        from .webpage import render
        render(read(ROOT/'reports'/f'{a.list_date}.json'),reconcile())
if __name__=='__main__':main()
