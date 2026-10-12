import re
def parse(html):
    quotes=[]
    for m in re.finditer(r'bOdds\[\d+\]\[(\d+)\].*?"HB":\{\d+:\[([^\]]+)\].*?"TP":\{\d+:\[([^\]]+)',html):
        def vals(s): return [x.strip().strip('"') for x in s.split(',')]
        hb,tp=vals(m.group(2)),vals(m.group(3)); quotes.append({'source':'7m','source_event_id':m.group(1),'spread_line':hb[3] if len(hb)>3 else None,'spread_raw_prices':hb[:2],'total_line':tp[3] if len(tp)>3 else None,'total_raw_prices':tp[:2],'source_quote_at':hb[2] if len(hb)>2 else None,'raw_price_format':'hong_kong','overtime_rule':'UNKNOWN','executable_verified':False})
    return {'source':'7m','events':[],'markets':quotes,'reason':'market endpoint parsed; event matching required'}
