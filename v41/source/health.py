from collections import Counter,defaultdict
import numpy as np
from .common import *
from .forward import calibration_metrics,performance

def probability_health(cards):
    groups=defaultdict(list)
    for c in cards:
        if c.get('probability',{}).get('calibrated_probability') is not None:groups[str(abs(c['snapshot']['handicap']))].append(c)
    rows=[]
    for h,cs in groups.items():
        counts=Counter(canonical(c['probability']['calibrated_probability']) for c in cs);share=max(counts.values())/len(cs)
        rows.append({'handicap':h,'n':len(cs),'distinct_vectors':len(counts),'dominant_vector_share':share,'status':'PROBABILITY_COLLAPSE_CRITICAL' if len(cs)>=10 and share>.95 else 'PROBABILITY_COLLAPSE_WARNING' if len(cs)>=10 and share>.8 else 'SMALL_SAMPLE' if len(cs)<10 else 'OK'})
    return rows
def health(cards,forward_rows):
    p=probability_health(cards);directions=Counter(c.get('decision',{}).get('candidate_side') for c in cards if c.get('decision',{}).get('candidate_side'));intents=Counter(c['features']['categorical']['intent'] for c in cards if c.get('features'));grades=Counter(c.get('decision',{}).get('grade') for c in cards if c.get('frozen_at'));abc=sum(grades[g] for g in 'ABC');n=sum(directions.values())
    direction=[{'side':k,'n':v,'share':v/n,'status':'DIRECTION_COLLAPSE_WARNING' if n>=30 and v/n>.85 else 'MONITOR'} for k,v in directions.items()]
    intent=[{'intent':k,'n':v,'share':v/sum(intents.values()),'status':'INTENT_COLLAPSE_WARNING' if sum(intents.values())>=30 and v/sum(intents.values())>.8 else 'MONITOR'} for k,v in intents.items()]
    grade=[{'grade':k,'n':grades[k],'abc':abc,'status':'GRADE_COLLAPSE_WARNING' if k=='C' and abc>=30 and grades[k]/abc>.8 else 'SMALL_SAMPLE' if abc<30 else 'MONITOR'} for k in 'ABCN']
    snapshot=[{'match_id':c['match_id'],'quote_at':c.get('snapshot',{}).get('quote_at'),'minutes_to_kickoff':c.get('snapshot',{}).get('minutes_to_kickoff'),'freeze':bool(c.get('frozen_at')),'primary_status':c.get('window_status'),'status':'MISSING' if not c.get('snapshot') else 'T30_FROZEN' if c.get('frozen_at') else 'PREVIEW_NOT_DECISION'} for c in cards]
    features=[{'match_id':c['match_id'],'required_completeness':c['features']['feature_completeness'],'all_completeness':c['features']['all_feature_completeness'],'missing':c['features']['missing_features']} for c in cards if c.get('features')]
    calibration=[]
    for key in ['overall','date','handicap','v41_side','region','intent','time_bucket']:
        groups=defaultdict(list)
        for r in forward_rows:groups['ALL' if key=='overall' else str(r.get(key))].append(r)
        if not groups and key=='overall':groups['ALL']=[]
        for value,rs in groups.items():
            m=calibration_metrics([r.get('v41_probability') for r in rs],[r.get('v41_result') for r in rs]);calibration.append({'group_by':key,'group':value,**m,'status':'CALIBRATION_DRIFT_WARNING' if m['n']>=100 and m['ece']>.08 else 'INSUFFICIENT_FORWARD' if m['n']<100 else 'MONITOR'})
    ev=[]
    for low,high in [(-100,0),(0,.02),(.02,.04),(.04,.08),(.08,100)]:
        rs=[r for r in forward_rows if r.get('v41_ev') is not None and low<=r['v41_ev']<high];m=performance(rs,'v41');ev.append({'bin':f'[{low},{high})','n':m['settled'],'ROI':m['ROI'],'status':'INSUFFICIENT_FORWARD' if m['settled']<30 else 'MONITOR'})
    supported=[r for r in ev if r['n']>=30]
    if any(b['ROI']<a['ROI'] for a,b in zip(supported,supported[1:])):
        for r in ev:r['status']='EV_MONOTONICITY_WARNING'
    grade_performance=[{'grade':g,**performance([r for r in forward_rows if r['v41_grade']==g],'v41')} for g in 'ABC'];supportedgrades=[r for r in grade_performance if r['settled']>=30];grade_alarm=any(b['ROI']>a['ROI'] for a,b in zip(supportedgrades,supportedgrades[1:]))
    if grade_alarm:
        for r in grade:r['status']='GRADE_MONOTONICITY_WARNING'
    data={'probability':p,'direction':direction,'intent':intent,'grade':grade,'snapshot':snapshot,'feature':features,'calibration':calibration,'ev':ev,'grade_performance':grade_performance}
    for key,rows in data.items():csvwrite(ROOT/'diagnostics'/f'{key}_health.csv',rows)
    return data
