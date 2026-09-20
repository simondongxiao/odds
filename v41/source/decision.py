import numpy as np
from .common import *
from .snapshots import window_name

def decide(pred,s,f,as_of):
    p=pred['calibrated_probability'];cfg=config('model_config');age=(clock(as_of)-clock(s['quote_at'])).total_seconds()/60
    out={'candidate_side':None,'candidate_team':None,'candidate_handicap':None,'water':None,'grade':'N','action':'NO BET','P_giving_cover':None,'P_receiving_cover':None,'direction_edge':None,'direction_confidence':None,'EV_mean':None,'EV_p10':None,'EV_p25':None,'P_EV_positive':None,'uncertainty':None,'decision_reason':[]}
    if p is None:out['decision_reason']=['INSUFFICIENT_CALIBRATION'];return out
    q=effective(p);out.update(P_giving_cover=q,P_receiving_cover=1-q,direction_edge=abs(2*q-1))
    if abs(q-.5)<1e-10:out['decision_reason']=['DIRECTION_TIE'];return out
    side='giving' if q>.5 else 'receiving';ps=p if side=='giving' else mirror(p);water=s[side+'_water'];draws=np.array([x if side=='giving' else mirror(x) for x in pred['ensemble']]);ev=np.array(draws)@payoff(water) if len(draws) else np.array([]);value=float(np.array(ps)@payoff(water));width=float(np.quantile(ev,.9)-np.quantile(ev,.1)) if len(ev) else None
    out.update(candidate_side=side,candidate_team=s[side+'_team'],candidate_handicap=(-1 if side=='giving' else 1)*abs(s['handicap']),water=water,selected_probability=ps,EV_mean=value,EV_p10=float(np.quantile(ev,.1)) if len(ev) else None,EV_p25=float(np.quantile(ev,.25)) if len(ev) else None,P_EV_positive=float(np.mean(ev>0)) if len(ev) else None,uncertainty=width,direction_confidence=float(np.mean([effective(x)>.5 for x in draws])) if len(draws) else None)
    reasons=[]
    if not s['prematch'] or clock(as_of)>=clock(s['kickoff_at']):reasons.append('NON_PREMATCH')
    if window_name(s['minutes_to_kickoff'])!='T-30':reasons.append('NOT_PRIMARY_T30_WINDOW')
    if not 0<=age<=config('snapshot_policy')['max_quote_age_minutes']:reasons.append('STALE_OR_FUTURE_QUOTE')
    if not len(ev):reasons.append('UNCERTAINTY_UNAVAILABLE')
    edge=effective(ps)-1/(1+water);out['calibrated_probability_edge']=edge
    if not reasons:
        for grade,g in cfg['grades'].items():
            if value>g['ev'] and out['EV_p10']>g['p10'] and out['P_EV_positive']>=g['positive'] and pred['train_support']>=g['train_cell'] and pred['calibration_support']>=g['calibration_cell'] and pred['window_calibration_support']>=g['calibration_cell'] and f['feature_completeness']>=g['completeness'] and width<=g['max_width'] and edge>=g['probability_edge']:
                out.update(grade=grade,action='SHADOW CANDIDATE',decision_reason=['ALL_PREREGISTERED_GATES_PASSED']);return out
        reasons=['MULTI_GATE_NOT_PASSED']
        if pred['window_calibration_support']<cfg['grades']['C']['calibration_cell']:reasons.append('INSUFFICIENT_T30_CALIBRATION_SUPPORT')
        out.update(grade='C',action='SHADOW CANDIDATE',strict_grade='N',grade_policy='USER_FORCED_ABC_FALLBACK_20260920',decision_reason=['FORCED_C_OBSERVATION_USER_RULE',*reasons]);return out
    out['decision_reason']=reasons;return out

def freeze(s,f,pred,decision,model,as_of,control=None):
    if clock(as_of)>=clock(s['kickoff_at']):raise ValueError('POST_KICKOFF_FREEZE_FORBIDDEN')
    if clock(as_of)<clock(model['created_at']):raise ValueError('MODEL_NOT_AVAILABLE_AT_DECISION')
    if window_name(s['minutes_to_kickoff'])!='T-30':raise ValueError('PRIMARY_WINDOW_REQUIRED')
    if not 0<=(clock(as_of)-clock(s['quote_at'])).total_seconds()/60<=config('snapshot_policy')['max_quote_age_minutes']:raise ValueError('STALE_FREEZE')
    row={'model_version':model['model_version'],'model_artifact_id':model['artifact_id'],'role':'CHALLENGER','status':'SHADOW ONLY','real_money':False,'frozen_at':clock(as_of).isoformat(),'list_date':s['list_date'],'match_id':s['match_id'],'snapshot':s,'features':f,'probability':{k:v for k,v in pred.items() if k!='ensemble'},'decision':decision,'control':control}
    row['decision_id']=digest(row);write(ROOT/'decisions'/s['list_date']/(s['match_id']+'.json'),row,immutable=True);return row
