def enrich(event, rows, cutoff): return {'injury_status':[x for x in rows or [] if x.get('captured_at','')<=cutoff],'input_captured_at':cutoff}
