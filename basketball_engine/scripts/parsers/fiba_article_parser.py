from __future__ import annotations
import re
from datetime import datetime, timezone

PAIR = re.compile(r"(?P<a>France|Germany|Spain|USA|United States)\s+v(?:s)?\s+(?P<b>France|Germany|Spain|USA|United States)", re.I)
TIME = re.compile(r"(?P<local>\d{1,2}:\d{2})\s+Local Time\s*\((?P<gmt>\d{1,2}:\d{2})\s+GMT\)", re.I)

def parse_fiba_article(text, source_url="", published_at=None, year=2026):
    rows=[]
    for m in PAIR.finditer(text):
        tail=text[m.end():m.end()+100]
        tm=TIME.search(tail)
        if not tm: continue
        # This article is a schedule release, so the explicit GMT value is authoritative.
        gmt=tm.group('gmt')
        rows.append({'league_family':'FIBA_WOMEN','competition':'FIBA Women Basketball World Cup 2026',
            'stage':'Semi-Finals','team_1':m.group('a'),'team_2':m.group('b'),
            'tip_time_source':gmt+' GMT','source_timezone':'GMT','tip_utc':f'{year}-09-12T{gmt}:00+00:00',
            'tip_time_bj':f'{year}-09-12T{gmt}:00+00:00','source_published_at':published_at,
            'source_url':source_url,'discovery_method':'official_round_article','source_group':'official',
            'upstream_provider':'fiba','neutral_site':True,'official_order_team_1':m.group('a'),
            'official_order_team_2':m.group('b'),'pregame_eligible': not published_at or published_at < f'{year}-09-12T{gmt}:00+00:00',
            'event_status':'discovered','participant_resolution':'resolved'})
    unique=[]; seen=set()
    for row in rows:
        key=(row['tip_utc'], frozenset((row['team_1'].lower(),row['team_2'].lower())))
        if key not in seen: seen.add(key); unique.append(row)
    return unique
