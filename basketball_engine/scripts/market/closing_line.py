def closing(rows, tip_time):
    valid=[r for r in rows if r.get('market_status')=='OPEN' and r.get('captured_at','')<tip_time and not r.get('stale',False)]
    if not valid:return {'close_line':None,'close_quality':'LOW','close_timestamp':None,'close_provider_count':0}
    last=max(valid,key=lambda x:x.get('captured_at',''))
    return {'close_line':last.get('line'),'close_timestamp':last.get('captured_at'),'close_provider_count':len({x.get('upstream_provider') for x in valid}),'close_quality':'HIGH' if len(valid)>=2 else 'LOW'}
