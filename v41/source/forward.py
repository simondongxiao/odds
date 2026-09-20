from collections import defaultdict
import html
import re
import numpy as np
from scipy.optimize import minimize
from .common import *

def team_identity(value):
    """Compare team identities without Titan's presentation-only HTML tags."""
    return re.sub(r'<[^>]+>', '', html.unescape(str(value or ''))).strip()

def settlement(frozen,result):
    s=frozen['snapshot'];d=frozen['decision'];c=frozen.get('control') or {}
    if tuple(map(team_identity,(result['home'],result['away'])))!=tuple(map(team_identity,(s['home'],s['away']))):raise ValueError('RESULT_IDENTITY_MISMATCH')
    if clock(result['result_available_at'])<clock(s['kickoff_at']):raise ValueError('RESULT_BEFORE_KICKOFF')
    hg,ag=map(int,result['score'].split('-'));out={'decision_id':frozen['decision_id'],'match_id':s['match_id'],'score':result['score'],'result_available_at':result['result_available_at'],'source':result['source'],'result_source_hash':result['source_hash']}
    for prefix,decision in [('v41',d),('v4',c)]:
        side=decision.get('candidate_side');team=decision.get('candidate_team');line=decision.get('candidate_handicap') if prefix=='v41' else decision.get('selected_handicap_signed');water=decision.get('water') if prefix=='v41' else decision.get('selected_water_hk')
        if side not in {'giving','receiving'} or line is None or water is None:out.update({prefix+'_result':None,prefix+'_pnl':None});continue
        expected=s[side+'_team'];expectedline=(-1 if side=='giving' else 1)*abs(s['handicap'])
        if team_identity(team)!=team_identity(expected) or abs(float(line)-expectedline)>1e-8:raise ValueError('SIDE_SIGN_MISMATCH')
        margin=hg-ag if team_identity(team)==team_identity(s['home']) else ag-hg;label=result_for_margin(margin,float(line));pnl=payoff(float(water))[STATES.index(label)]
        out[prefix+'_result']=label;out[prefix+'_pnl']=pnl if decision.get('grade') in ['A','B','C'] else 0.
        out[prefix+'_hypothetical_unit_pnl']=pnl
    return out
def reconcile():
    rows=[]
    for path in sorted((ROOT/'decisions').glob('*/*.json')):
        f=read(path);s=f['snapshot'];d=f['decision'];c=f.get('control') or {};observations=[read(p) for p in (ROOT/'data/results'/s['list_date']/s['match_id']).glob('*.json')];settled={}
        if observations:
            if len({x['score'] for x in observations})>1:settled={'settlement_status':'CONFLICT_PENDING'}
            else:
                result=min(observations,key=lambda x:x['result_available_at']);settled=settlement(f,result);settled['settlement_status']='SETTLED';write(ROOT/'forward/results'/s['list_date']/s['match_id']/(digest(settled)+'.json'),settled,immutable=True)
        a=c.get('grade') in ['A','B','C'];b=d['grade'] in ['A','B','C'];same=bool(a and b and c.get('candidate_side')==d['candidate_side']);different=bool(a and b and not same)
        group='C_SAME_SIDE' if same else 'D_OPPOSITE_SIDE' if different else 'A_V4_ONLY' if a else 'B_V41_ONLY' if b else 'NEITHER'
        row={'date':s['list_date'],'match_id':s['match_id'],'league':s['league'],'region':f['features']['categorical']['league_group'],'kickoff':s['kickoff_at'],'frozen_at':f['frozen_at'],'handicap':abs(s['handicap']),'intent':f['features']['categorical']['intent'],'time_bucket':'T-30','v4_side':c.get('candidate_side'),'v4_grade':c.get('grade'),'v4_ev':c.get('ev_mean'),'v4_result':None,'v4_pnl':None,'v4_probability':list(c['probabilities'].values()) if c.get('probabilities') else None,'v41_side':d['candidate_side'],'v41_grade':d['grade'],'v41_probability':d.get('selected_probability'),'v41_ev':d['EV_mean'],'v41_ev_p10':d['EV_p10'],'v41_result':None,'v41_pnl':None,'same_side':same,'different_side':different,'comparison_group':group,'decision_id':f['decision_id'],'settlement_status':'PENDING',**settled}
        rows.append(row)
    fields=['date','match_id','league','region','kickoff','frozen_at','handicap','intent','time_bucket','v4_side','v4_grade','v4_ev','v4_probability','v4_result','v4_pnl','v4_hypothetical_unit_pnl','v41_side','v41_grade','v41_probability','v41_ev','v41_ev_p10','v41_result','v41_pnl','v41_hypothetical_unit_pnl','same_side','different_side','comparison_group','decision_id','settlement_status']
    csvwrite(ROOT/'forward/forward_comparison.csv',rows,fields);return rows
def calibration_metrics(probabilities,labels):
    pairs=[(p,y) for p,y in zip(probabilities,labels) if p is not None and y in STATES]
    if not pairs:return {'n':0,'effective_n':0,'predicted_effective_win_rate':None,'actual_effective_win_rate':None,'brier':None,'five_state_brier':None,'ece':None,'slope':None,'intercept':None}
    p=np.array([x[0] for x in pairs]);y=np.array([STATES.index(x[1]) for x in pairs]);b5=float(np.mean(np.sum((p-np.eye(5)[y])**2,axis=1)));q=np.array([effective(x) for x in p]);weight=np.array([1,.5,0,.5,1])[y];target=(y<2).astype(float);keep=weight>0;q=q[keep];target=target[keep];weight=weight[keep];den=weight.sum()
    if not den:return {'n':len(pairs),'effective_n':0,'five_state_brier':b5,'predicted_effective_win_rate':None,'actual_effective_win_rate':None,'brier':None,'ece':None,'slope':None,'intercept':None}
    ece=0.
    for lo in np.arange(0,1,.1):
        mask=(q>=lo)&(q<(lo+.1) if lo<.9 else q<=1)
        if mask.any():ece+=abs(np.average(q[mask],weights=weight[mask])-np.average(target[mask],weights=weight[mask]))*weight[mask].sum()/den
    slope=intercept=None
    if len(q)>=30 and len(set(target))==2:
        logit=np.log(np.clip(q,1e-6,1-1e-6)/(1-np.clip(q,1e-6,1-1e-6)))
        def loss(b):
            z=b[0]+b[1]*logit;return np.sum(weight*(np.logaddexp(0,z)-target*z))/den
        result=minimize(loss,[0,1],method='BFGS')
        if result.success:intercept,slope=map(float,result.x)
    return {'n':len(pairs),'effective_n':float(den),'predicted_effective_win_rate':float(np.average(q,weights=weight)),'actual_effective_win_rate':float(np.average(target,weights=weight)),'brier':float(np.average((q-target)**2,weights=weight)),'five_state_brier':b5,'ece':float(ece),'slope':slope,'intercept':intercept}
def performance(rows,prefix,grades=('A','B','C'),pnl_field=None):
    candidates=[r for r in rows if r.get(prefix+'_grade') in grades];settled=sorted([r for r in candidates if r.get(prefix+'_result') in STATES],key=lambda r:(r['kickoff'],r['match_id']));pnl_field=pnl_field or prefix+'_pnl';pnls=[r[pnl_field] for r in settled];outcomes=[r[prefix+'_result'] for r in settled];counts={s:outcomes.count(s) for s in STATES};den=counts['W']+.5*counts['HW']+counts['L']+.5*counts['HL'];curve=np.r_[0,np.cumsum(pnls)];dd=float(np.max(np.maximum.accumulate(curve)-curve))
    return {'candidates':len(candidates),'settled':len(settled),'pending':len(candidates)-len(settled),**counts,'effective_win_rate':(counts['W']+.5*counts['HW'])/den if den else None,'PnL':sum(pnls),'ROI':sum(pnls)/len(settled) if settled else None,'max_drawdown':dd,'drawdown_basis':'1u each settled candidate ordered by kickoff','calibration':calibration_metrics([r.get(prefix+'_probability') for r in settled],outcomes)}
def comparison(rows):
    out={'overall':{p:performance(rows,p) for p in ['v4','v41']},'n_observation':{p:performance(rows,p,('N',),p+'_hypothetical_unit_pnl') for p in ['v4','v41']},'groups':{}}
    for key in ['comparison_group','date','region','handicap','v41_grade','v4_grade','time_bucket','intent','v41_side']:
        grouped=defaultdict(list)
        for r in rows:grouped[str(r.get(key))].append(r)
        out['groups'][key]={k:{p:performance(rs,p) for p in ['v4','v41']} for k,rs in grouped.items()}
    out['minimum_forward_candidates']=200;out['preferred_forward_candidates']=500;out['promotion']='NEVER_AUTOMATIC';return out
