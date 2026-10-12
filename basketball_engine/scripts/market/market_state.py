def state(rows, news=None):
    if any(r.get('market_status')=='SUSPENDED' for r in rows): return 'STALE_BOOK'
    lines=[r.get('line') for r in rows if r.get('line') is not None]
    prices=[r.get('price') for r in rows if r.get('price') is not None]
    if len(set(lines))==1 and len(set(prices))>1: return 'PRICE_ONLY_MOVE'
    if len(set(lines))>1 and len(set(prices))==1: return 'LINE_ONLY_MOVE'
    if len(set(lines))>1: return 'CONSENSUS_MOVE'
    return 'MARKET_STABLE'
