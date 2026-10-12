def effective_weight(recency_weight, roster_overlap): return float(recency_weight)*float(roster_overlap)
def enrich(event, form, cutoff): return {'recent_form':[x for x in form or [] if x.get('captured_at','')<=cutoff],'input_captured_at':cutoff}
