from __future__ import annotations
import importlib.util,sys
from .common import *

def classifier():
    name='v41_frozen_classifier'
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,ROOT/'data/control_baseline/tools/football_competition_normalizer.py');m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
def devig(values):
    if not values or any(x is None or x<=1 for x in values):return None
    raw=[1/x for x in values];total=sum(raw);return [x/total for x in raw]
def build(snapshot,path,as_of):
    as_of=clock(as_of)
    if clock(snapshot['quote_at'])>as_of or clock(snapshot['quote_at'])>=clock(snapshot['kickoff_at']):raise ValueError('FUTURE_OR_POSTMATCH_FEATURE')
    history=sorted({s['snapshot_id']:s for s in path if s['match_id']==snapshot['match_id'] and clock(s['quote_at'])<=clock(snapshot['quote_at']) and s['prematch'] and s['valid_market']}.values(),key=lambda s:s['quote_at'])
    if not history or snapshot['snapshot_id'] not in {x['snapshot_id'] for x in history}:history.append(snapshot);history.sort(key=lambda s:s['quote_at'])
    sidehistory=[s for s in history if s['giving_team']==snapshot['giving_team']]
    s=snapshot;h=abs(s['handicap']);gh=s['giving_team']==s['home'];opening=s.get('opening_handicap');open_same=opening is not None and opening*s['handicap']>0
    ow=s.get('opening_home_water') if gh else s.get('opening_away_water')
    line_move=h-abs(opening) if open_same else None;wm=s['giving_water']-ow if ow is not None and open_same else None
    euro=devig(s['euro']);oeuro=devig(s['opening_euro']);gidx=0 if gh else 2;ridx=2 if gh else 0
    change=euro[gidx]-oeuro[gidx] if euro and oeuro else None
    lines=[abs(z['handicap']) for z in sidehistory];waters=[z['giving_water'] for z in sidehistory];deltas=[b-a for a,b in zip(lines,lines[1:])]
    nonzero=[d for d in deltas if abs(d)>.005]
    span=(clock(s['quote_at'])-clock(sidehistory[0]['quote_at'])).total_seconds()/60 if sidehistory else 0
    market=(1/(1+s['giving_water']))/(1/(1+s['giving_water'])+1/(1+s['receiving_water']))
    values={k:None for k in config('feature_config')['numeric']}
    info=classifier().normalize(s['league'])
    values.update(handicap_depth=h,opening_handicap=abs(opening) if opening is not None else None,handicap_movement=line_move,giving_water=s['giving_water'],receiving_water=s['receiving_water'],water_movement=wm,market_giving_share=market,
                  euro_giving=euro[gidx] if euro else None,euro_draw=euro[1] if euro else None,euro_receiving=euro[ridx] if euro else None,euro_change=change,
                  euro_asian_gap=(euro[gidx]/(euro[gidx]+euro[ridx])-market) if euro else None,
                  minutes_to_kickoff=s['minutes_to_kickoff'],quote_age_minutes=(as_of-clock(s['quote_at'])).total_seconds()/60,giving_home=int(gh),kickoff_hour=clock(s['kickoff_at']).hour+clock(s['kickoff_at']).minute/60,
                  line_up_count=sum(x>.005 for x in deltas) if len(lines)>1 else None,line_down_count=sum(x<-.005 for x in deltas) if len(lines)>1 else None,
                  reversal_count=sum(x*y<0 for x,y in zip(nonzero,nonzero[1:])) if len(lines)>2 else None,
                  spread_speed=(lines[-1]-lines[0])/span if span else None,water_speed=(waters[-1]-waters[0])/span if span else None,
                  youth=int(info.youth_or_reserve),women=int('女' in s['league']),cup=int(info.competition_type in {'杯赛','洲际杯赛'}))
    for minutes in [30,60]:
        # Require an actual observation around the horizon; no imputed T-500 point.
        targets=[z for z in sidehistory if abs((clock(s['quote_at'])-clock(z['quote_at'])).total_seconds()/60-minutes)<=5]
        values[f'late_{minutes}_line']=h-abs(min(targets,key=lambda z:abs((clock(s['quote_at'])-clock(z['quote_at'])).total_seconds()/60-minutes))['handicap']) if targets else None
    for key in ['neutral_venue','elo_difference','recent_form_difference','bookmaker_dispersion','bookmaker_consensus']:values[key]=s.get(key)
    # Interpretation only. No side dictionary exists in this module.
    evidence=sum(x is not None for x in [line_move,wm,change]);conflict=int(line_move is not None and change is not None and line_move*change<0)
    tag='UNKNOWN'
    if len({z['giving_team'] for z in history})>1 or conflict:tag='MIXED'
    elif line_move is not None and wm is not None:
        if abs(line_move)<=.005 and abs(wm)<=.005:tag='NEUTRAL'
        elif line_move>.005:tag='真实示强/阻上' if wm<=.005 else '阻上/诱下'
        elif line_move<-.005:tag='降温保护/诱下' if wm<-.005 else '诱上/阻下'
        else:tag='真实示弱/阻下' if wm<-.005 else '阻下/下盘保护'
    confidence=0.0 if tag=='UNKNOWN' else min(.5,evidence/6)*(1-.5*conflict)
    values['intent_confidence']=confidence
    categorical={'intent':tag,'league_group':info.micro_region}
    if line_move is not None and change is not None:values['line_resistance']=int(abs(line_move)<=.005 and abs(change)>.01)
    if wm is not None and change is not None:values['water_resistance']=int(wm*change>0)
    provenance=[]
    for name,value in {**values,**categorical}.items():
        provenance.append({'feature_name':name,'feature_value':value,'source':s['source'] if value is not None else 'MISSING','source_timestamp':s['quote_at'] if value is not None else None,'as_of_time':as_of.isoformat(),'missing_flag':value is None,'snapshot_ids':[z['snapshot_id'] for z in history] if value is not None else []})
    required=['handicap_depth','giving_water','receiving_water','euro_giving','euro_draw','euro_receiving','handicap_movement','water_movement','minutes_to_kickoff','giving_home']
    out={'snapshot_id':s['snapshot_id'],'as_of_time':as_of.isoformat(),'match_id':s['match_id'],'values':values,'categorical':categorical,'provenance':provenance,
         'market_interpretation':{'intent':tag,'intent_confidence':confidence,'confidence_kind':'rule_evidence_fraction_not_statistical_probability','intent_evidence_count':evidence,'intent_conflict_count':conflict,'authority':'EXPLANATION_ONLY_NO_DIRECTION_MAPPING'},
         'feature_completeness':sum(values[k] is not None for k in required)/len(required),'all_feature_completeness':sum(v is not None for v in values.values())/len(values),
         'missing_features':[k for k,v in values.items() if v is None],
         'path':{'opening_handicap':opening,'max_handicap':max(lines),'min_handicap':min(lines),'latest_handicap':s['handicap'],'opening_water':ow,'max_water':max(waters),'min_water':min(waters),'latest_water':s['giving_water'],
                 'handicap_path':[{'quote_at':z['quote_at'],'handicap':z['handicap']} for z in history],'water_path':[{'quote_at':z['quote_at'],'giving_water':z['giving_water'],'giving_team':z['giving_team']} for z in history]},'classification':info.to_dict()}
    out['feature_id']=digest(out);return out
