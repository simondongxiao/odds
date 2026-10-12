from __future__ import annotations
from .enrich_team_strength import enrich as strength
from .enrich_rosters import enrich as roster
from .enrich_minutes import enrich as minutes
from .enrich_injuries import enrich as injuries
from .enrich_recent_form import enrich as recent_form
from .enrich_market_anchor import enrich as market

def enrich_event(event, inputs, pricing_cutoff):
    parts=[strength(event,inputs.get('team_strength'),pricing_cutoff),roster(event,inputs.get('roster'),pricing_cutoff),minutes(event,inputs.get('minutes'),pricing_cutoff),injuries(event,inputs.get('injuries'),pricing_cutoff),recent_form(event,inputs.get('recent_form'),pricing_cutoff),market(event,inputs.get('market'),pricing_cutoff)]
    return {'canonical_event_id':event['canonical_event_id'],'pricing_cutoff':pricing_cutoff,'input_sources':inputs.get('input_sources',[]),'enrichment':parts,'leakage_blocked':any(x.get('leakage_blocked',False) for x in parts)}
