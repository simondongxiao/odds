from __future__ import annotations
from .club_model import structural_margin as club_margin
from .national_team_model import structural_margin as national_margin
from .high_uncertainty_model import structural_margin as uncertain_margin
from .market_shrinkage import shrink, initial_weight
from .distributions import cdf, interval, push_probs
from .possession_model import project_possessions, project_score
from .team_total import team_totals

FAMILIES={'CLUB_MATURE':{'NBA','WNBA','EUROLEAGUE','NCAAB','CBA_REGULAR','B_LEAGUE','KBL','NBL_AU'},'NATIONAL_TEAM':{'FIBA_MEN','FIBA_WOMEN','FIBA_QUALIFIER'},'HIGH_UNCERTAINTY':{'NBA_SUMMER','G_LEAGUE','CBA_SUMMER','CBA_PRESEASON','CBA_CLUB_CUP','CHINA_CLUB_WARMUP','FIBA_YOUTH'}}
def family_for(e):
    return next((k for k,v in FAMILIES.items() if e.get('league_family') in v),'HIGH_UNCERTAINTY')
def _quality(e, home, away):
    keys=['team_strength_quality','roster_quality','minutes_quality','injury_quality','schedule_quality','market_anchor_quality','historical_sample_quality']
    vals=[e.get(k, home.get(k,away.get(k,0))) for k in keys]; return round(sum(float(x) for x in vals)/len(vals)) if vals else 0
def price_game(event, home, away, market=None):
    market=market or {}; fam=family_for(event); q=_quality(event,home,away); missing=[]
    if fam=='CLUB_MATURE':
        required=['ortg','drtg','pace']
        raw=club_margin(home,away) if all(k in home and k in away for k in required) else None
    elif fam=='NATIONAL_TEAM': raw=national_margin(home,away) if 'prior' in home and 'prior' in away else None
    else: raw=uncertain_margin(home,away) if ('prior_margin' in home or 'roster_value' in home) else None
    if raw is None: missing.append('structural_strength_inputs'); return {'pricing_status':'UNPRICEABLE','model_family':fam,'missing_inputs':missing,'pricing_data_quality':q}
    structural=raw
    anchor=market.get('margin')
    if anchor is None: missing.append('market_anchor'); blended=None; mw=initial_weight(fam,q)
    else: mw=initial_weight(fam,q); blended=shrink(structural,anchor,mw)
    if 'pace' not in home or 'pace' not in away or 'ortg' not in home or 'ortg' not in away:
        missing.append('pace_or_efficiency'); hp=ap=None; total=None
    else:
        poss=project_possessions(home,away); hp,ap=project_score(home,away,poss); total=hp+ap
    spread_scale=12*(1.3 if fam=='HIGH_UNCERTAINTY' else 1.0); total_scale=17*(1.3 if fam=='HIGH_UNCERTAINTY' else 1.0)
    status='PRICED' if q>=55 and not missing else ('MARKET_ANCHORED' if anchor is not None else 'PRICED_LOW_CONFIDENCE')
    result={'raw_win_probability':1-cdf(0,raw,spread_scale),'calibrated_win_probability':None,'model_win_probability':1-cdf(0,blended if blended is not None else raw,spread_scale),'probability_calibration_status':'UNVALIDATED','raw_fair_margin':raw,'structural_fair_margin':structural,'blended_fair_margin':blended,'mu_raw':raw,'mu_structural':structural,'mu_market':anchor,'mu_blended':blended,'raw_fair_total':total,'structural_fair_total':total,'blended_fair_total':total,'projected_home_points':hp,'projected_away_points':ap,'margin_distribution':interval(blended if blended is not None else raw,spread_scale),'total_distribution':interval(total,total_scale) if total is not None else None,'uncertainty':{'spread_scale':spread_scale,'total_scale':total_scale,'source':'prior'},'model_weight':mw,'market_weight':1-mw,'model_family':fam,'model_version':'LEGACY_COMPAT_NOT_PRODUCTION','production_eligible':False,'data_quality':q,'pricing_data_quality':q,'pricing_status':status,'missing_inputs':missing,'team_totals':team_totals(hp,ap,market.get('team_total') if market else None) if hp is not None else None}
    return result
