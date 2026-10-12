"""Coverage funnel metrics for the dashboard; never changes model decisions."""
from collections import defaultdict

REGION_TOKENS=(
    ('中国',('cba','wcba','cuba','中国','china')),
    ('日本韩国',('日本','japan','b.league','kbl','韩国','korea')),
    ('欧洲',('欧洲','euro','西班牙','德国','意大利','法国','土耳其','希腊','捷克','立陶宛','芬兰','波兰')),
    ('北美',('nba','wnba','ncaa','美国','加拿大','g league')),
    ('拉美',('墨西哥','巴西','阿根廷','智利','乌拉圭','波多黎各','委内瑞拉','哥伦比亚','巴拉圭','america')),
    ('FIBA',('fiba','世界杯','亚运','亚洲杯','国家队','qualif','洲际')),
    ('大洋洲',('澳大利亚','澳洲','nbl','新西兰','australia','new zealand')),
    ('海湾',('沙特','阿联酋','卡塔尔','巴林','科威特','gulf')),
    ('其他亚洲',('菲律宾','台湾','亚洲','日本','韩国')),
)

def region(event):
    text=f"{event.get('league','')} {event.get('competition','')} {event.get('region','')}".casefold()
    for name,tokens in REGION_TOKENS:
        if any(t.casefold() in text for t in tokens): return name
    return '其他'

def _blank(): return {'discovered':0,'market_found':0,'data_ready':0,'priceable':0,'shadow':0,'executable':0}

def build(rows, source_health=None):
    overall=_blank();by_region=defaultdict(_blank);by_league={};uncovered=[]
    for row in rows:
        e=row.get('event',{});q=(row.get('market') or {}).get('quotes') or [];p=row.get('pricing') or {};d=row.get('execution') or {}
        r=region(e);league=e.get('league_family') or e.get('league') or 'UNCLASSIFIED_DISCOVERED'
        market=bool(q);priceable=p.get('pricing_status')!='UNPRICEABLE';shadow=bool(d.get('triggered') or d.get('shadow_action') in ('SHADOW_BET','SHADOW_LIMIT_ONLY'));executable=bool(d.get('real_execution_allowed') and d.get('triggered'))
        entry=by_league.setdefault(league,{'league':league,'region':r,'discovery_source':e.get('source'),'odds_source':'7M' if market else None,'production_status':'MARKET_ACTIVE' if market else 'DISCOVERY_ONLY','today':_blank(),'tier':e.get('tier'),'sample_n':0})
        for target in (overall,by_region[r],entry['today']):
            target['discovered']+=1;target['market_found']+=int(market);target['data_ready']+=int(priceable);target['priceable']+=int(priceable);target['shadow']+=int(shadow);target['executable']+=int(executable)
        item=entry;item['sample_n']+=1
        if not market: uncovered.append({'event_id':row.get('id'),'league':league,'teams':[e.get('team1_name'),e.get('team2_name')],'status':'NO_MARKET','reason':'7M_MARKET_NOT_FOUND' if e.get('source')=='7M' else 'NO_MARKET'})
        elif not priceable: uncovered.append({'event_id':row.get('id'),'league':league,'teams':[e.get('team1_name'),e.get('team2_name')],'status':'INSUFFICIENT_TEAM_DATA','reason':';'.join(p.get('blockers',[]))})
    return {'overall':overall,'by_region':dict(by_region),'by_league':by_league,'uncovered_events':uncovered,'source_health':source_health or []}
