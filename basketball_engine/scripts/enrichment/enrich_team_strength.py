def enrich(event, stats, cutoff):
    valid={k:v for k,v in (stats or {}).items() if not v.get('captured_at') or v['captured_at']<=cutoff}
    return {'team_strength':valid,'leakage_blocked':len(valid)!=len(stats or {}),'input_captured_at':cutoff}
