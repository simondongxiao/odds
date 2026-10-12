#!/usr/bin/env python3
from __future__ import annotations
import json, urllib.request
from pathlib import Path
from parsers.fiba_page_parser import parse_fiba_page, parse_fiba_rendered_landing
from parsers.fiba_article_parser import parse_fiba_article

URLS={"event_landing":"https://www.fiba.basketball/en/events/fiba-womens-basketball-world-cup-2026",
      "games_page":"https://www.fiba.basketball/en/events/fiba-womens-basketball-world-cup-2026/games",
      "official_round_article":"https://www.fiba.basketball/en/events/fiba-womens-basketball-world-cup-2026/news/semi-finals-set-at-the-fiba-womens-basketball-world-cup-2026"}
def fetch(u):
    r=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
    return urllib.request.urlopen(r,timeout=30).read().decode('utf-8','ignore')
def run(root):
    root=Path(root); raw=root/'raw'/'step2e_fiba'; raw.mkdir(parents=True,exist_ok=True); rows=[]; counts={}
    for name,url in URLS.items():
        html=fetch(url); (raw/(name+'.html')).write_text(html,encoding='utf8')
        if name=='event_landing': got=parse_fiba_rendered_landing(html,url,'2026-09-01T00:00:00+00:00')
        elif name=='official_round_article': got=parse_fiba_article(html,url,'2026-09-11T10:00:00+00:00')
        else: got=parse_fiba_page(html,url)
        counts[name]=len(got); rows.extend(got)
    union={}
    for row in rows:
        key=(row['tip_utc'],frozenset((row['team_1'].lower(),row['team_2'].lower())))
        union.setdefault(key,row)
    return {'surface_counts':counts,'provider_union_count':len(union),'events':list(union.values()),'duplicates_merged':len(rows)-len(union)}
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=run(a.output);Path(a.output,'manifests').mkdir(parents=True,exist_ok=True);Path(a.output,'manifests','fiba_2026-09-12_step2e.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps({'surface_counts':out['surface_counts'],'union':out['provider_union_count'],'duplicates':out['duplicates_merged']}))
