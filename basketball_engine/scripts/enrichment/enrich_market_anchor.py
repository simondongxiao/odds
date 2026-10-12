def enrich(event, market, cutoff):
    if not market or market.get('captured_at','')>cutoff: return {'market_anchor':None,'leakage_blocked':bool(market)}
    return {'market_anchor':market,'leakage_blocked':False,'input_captured_at':market.get('captured_at')}
