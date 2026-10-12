def lead_lag(rows):
    ordered=sorted(rows,key=lambda x:x.get('captured_at','')); first=ordered[0].get('upstream_provider') if ordered else None
    return {'first_mover_provider':first,'follower_count':max(0,len({r.get('upstream_provider') for r in ordered})-1),'timestamp_ordered':all(ordered[i].get('captured_at','')<=ordered[i+1].get('captured_at','') for i in range(len(ordered)-1))}
