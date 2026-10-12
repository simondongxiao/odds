def features(rows, tip_time=None):
    rows=sorted(rows,key=lambda x:x.get('captured_at','')); lines=[float(x['line']) for x in rows if x.get('line') is not None]
    prices=[float(x['price']) for x in rows if x.get('price') is not None]
    return {'open_line':lines[0] if lines else None,'current_line':lines[-1] if lines else None,'latest_line':lines[-1] if lines else None,'line_move_points':(lines[-1]-lines[0]) if lines else None,'price_move':(prices[-1]-prices[0]) if prices else None,'max_intraday_range':(max(lines)-min(lines)) if lines else None,'provider_dispersion':(max(lines)-min(lines)) if lines else None}
def move_significance(family, liquidity, minutes, line_move, juice_move=0, provider_count=1, dispersion=0):
    mag=abs(float(line_move or 0)); threshold=1.5 if family in ('NBA','WNBA') else 2.0
    if mag>=threshold*2: return 'EXTREME'
    if mag>=threshold: return 'MATERIAL'
    if mag>=threshold/2: return 'SMALL'
    return 'NOISE'
