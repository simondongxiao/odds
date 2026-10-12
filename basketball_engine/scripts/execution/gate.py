from __future__ import annotations
import math, uuid
BUFFERS={'CLUB_MATURE':.02,'NATIONAL_TEAM':.045,'HIGH_UNCERTAINTY':.08}
def ev(p,odds,push=0,line_is_integer=False):
    """push is PUSH probability, not loss probability. Compatibility API only."""
    if not 0 <= p <= 1 or not 0 <= push <= 1 or p + push > 1 + 1e-9:
        raise ValueError("invalid win/push probabilities")
    return p * (odds - 1) - (1 - p - push) if line_is_integer else p * odds - 1
def sensitivity(p, line, odds, integer=False):
    return [{'line':line+d,'p_cover':None,'EV':None,'reason':'DISTRIBUTION_REQUIRED_NOT_LINEAR_PROBABILITY_SHIFT'} for d in (-1,-.5,0,.5,1)]
def evaluate(pricing, market, quality, family, freshness=True, reprice=False, intent=None):
    blockers=[]; buffer=BUFFERS.get(family,.08); p=float(pricing.get('p_conservative',0)); line=market.get('line'); odds=float(market.get('decimal_odds',market.get('price',0)))
    if 'p_conservative' not in pricing: blockers.append('EXACT_MARKET_PROBABILITY_REQUIRED')
    q=float(quality.get('pricing_data_quality',quality.get('execution_data_quality',0)))
    if not freshness: blockers.append('STALE_OR_UNFRESH_INPUT')
    if reprice: blockers.append('BLOCKED_PENDING_REPRICE')
    if not market or market.get('market_status')!='OPEN': blockers.append('BLOCKED_NO_MARKET')
    if q<50: blockers.append('DATA_QUALITY_LT_50')
    breakeven=1/odds if odds else None; required=(breakeven or 1)+buffer; actual=p-(breakeven or 1); value=ev(p,odds,pricing.get('p_push',0),float(line or 0)%1==0) if odds else None
    state='EDGE' if value is not None and actual>=buffer and not blockers else ('LEAN' if value is not None and actual>0 else 'UNPRICEABLE' if not pricing else 'NO_EDGE')
    action='SHADOW_BET' if state=='EDGE' and q>=85 and not blockers else ('SHADOW_LIMIT_ONLY' if state in ('EDGE','LEAN') and q>=70 and not blockers else 'BLOCKED' if blockers else 'WATCH')
    if odds and market.get('min_acceptable_decimal_odds') is not None and odds<float(market['min_acceptable_decimal_odds']) and state=='EDGE': action='PASS_PRICE_EXHAUSTED'
    manual_live = intent == 'MANUAL_LIVE' and action in ('SHADOW_BET','SHADOW_LIMIT_ONLY') and not blockers
    return {'prediction_id':str(uuid.uuid4()),'model_state':state,'shadow_action':action,'real_execution_state':'MANUAL_LIVE_CANDIDATE' if manual_live else 'DISABLED','real_execution_allowed':manual_live,'automated_execution_allowed':False,'manual_order_required':manual_live,'real_stake':0,'real_bet_flag':False,'p_conservative':p,'breakeven':breakeven,'EV':value,'required_buffer':buffer,'actual_buffer':actual,'data_quality':q,'blockers':blockers,'reprice_required':reprice,'line_sensitivity':sensitivity(p,line or 0,odds or 1.01,float(line or 0)%1==0),'price_sensitivity':[{'decimal_odds':o,'EV':ev(p,o,pricing.get('p_push',0),float(line or 0)%1==0)} for o in (1.8,1.85,1.9,1.91,1.95,2.0)],'display_intent_tag':intent,'theoretical_kelly':0 if not odds else max(0,(p*odds-1)/(odds-1)),'kelly_usable':False}
