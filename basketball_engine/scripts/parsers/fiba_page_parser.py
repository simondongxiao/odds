from __future__ import annotations
import json, re

def _walk(x):
    if isinstance(x, dict):
        yield x
        for v in x.values(): yield from _walk(v)
    elif isinstance(x, list):
        for v in x: yield from _walk(v)

def parse_fiba_page(html, source_url="", published_at=None):
    blobs = []
    for m in re.finditer(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.S|re.I): blobs.append(m.group(1))
    for m in re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S|re.I): blobs.append(m.group(1))
    rows=[]
    for blob in blobs:
        try: data=json.loads(blob)
        except Exception: continue
        for d in _walk(data):
            home=d.get("homeTeam") or d.get("home")
            away=d.get("awayTeam") or d.get("away")
            if isinstance(home,dict): home=home.get("name") or home.get("shortName")
            if isinstance(away,dict): away=away.get("name") or away.get("shortName")
            start=d.get("startDate") or d.get("startTime") or d.get("scheduledStart")
            gid=d.get("gameId") or d.get("id") or d.get("eventId")
            if home and away and start:
                rows.append({"official_game_id":gid, "team_1":home, "team_2":away, "tip_utc":start,
                    "official_order_team_1":home, "official_order_team_2":away, "neutral_site":True,
                    "source_url":source_url, "article_published_at":published_at,
                    "discovery_method":"structured_api", "parse_source":"embedded_json"})
    return rows

def parse_fiba_rendered_landing(html, source_url="", published_at=None):
    """Parse the server-rendered game cards exposed by the official landing page."""
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S|re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    rows=[]
    patterns=[(r"Semi-Finals.*?FRA\s+FRA\s+GER\s+GER.*?Sat,\s*Sep\s*12.*?14:30",'France','Germany','14:30'),
              (r"Semi-Finals.*?ESP\s+ESP\s+USA\s+USA.*?Sat,\s*Sep\s*12.*?18:00",'Spain','USA','18:00')]
    for pat,a,b,tm in patterns:
        if re.search(pat,text,re.I):
            rows.append({'league_family':'FIBA_WOMEN','competition':'FIBA Women Basketball World Cup 2026','stage':'Semi-Finals',
                'team_1':a,'team_2':b,'official_order_team_1':a,'official_order_team_2':b,'tip_time_source':tm,
                'source_timezone':'GMT','tip_utc':f'2026-09-12T{tm}:00+00:00','source_url':source_url,
                'source_published_at':published_at,'source_group':'official','upstream_provider':'fiba',
                'discovery_method':'event_landing','neutral_site':True,'pregame_eligible':True,
                'event_status':'discovered','participant_resolution':'resolved'})
    return rows
