"""Global basketball event discovery, independent from odds collection.

The module only creates event identities. It never invents a quote and never
changes pricing or execution gates. Every adapter is attempted independently;
an unavailable adapter is recorded rather than converted into "no games".
"""
from __future__ import annotations

import hashlib, json, re, ssl, uuid
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from urllib.parse import quote
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener, urlopen
from zoneinfo import ZoneInfo
from repair_v22.common import canonical_team_token, competition_key, competition_phase
from odds_shared.http_retry import RetryPolicy, request_with_retry

BJ = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc
_HTTP_RETRY_LOG=[]

@lru_cache(maxsize=1)
def _registered_league_aliases():
    """Load formal aliases from the Skill registry.

    Exact normalized aliases are resolved before broad keyword rules.  This
    keeps similarly named leagues such as Australia NBL, China NBL and
    Singapore NBL from being collapsed into one family.
    """
    try:
        import yaml
        path = Path(__file__).resolve().parents[1] / "config" / "league_registry.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        aliases = ((payload.get("aliases") or {}).get("leagues") or {})
        families = payload.get("league_families") or {}
        return {
            re.sub(r"[^\w\u4e00-\u9fff]+", "", str(alias).casefold()): (str(family), families.get(str(family), {}))
            for alias, family in aliases.items()
        }
    except (OSError, ValueError, TypeError):
        return {}

def _region_for_registered(family, spec):
    explicit = spec.get("region") if isinstance(spec, dict) else None
    if explicit:
        return str(explicit)
    countries = " ".join(str(x) for x in ((spec or {}).get("countries") or [])).casefold()
    if family.startswith("FIBA_"): return "FIBA"
    if any(x in countries for x in ("europe", "czech", "sweden", "finland", "romania", "switzerland", "hungary", "belarus", "slovakia", "norway")): return "欧洲"
    if any(x in countries for x in ("australia", "new zealand", "oceania")): return "大洋洲"
    if any(x in countries for x in ("korea", "japan")): return "日本韩国"
    if any(x in countries for x in ("usa", "canada")): return "北美"
    if any(x in countries for x in ("americas", "puerto rico", "colombia", "brazil", "el salvador")): return "拉美"
    if any(x in countries for x in ("philippines", "singapore", "asia", "middle east", "gulf")): return "其他亚洲"
    if "china" in countries: return "中国"
    return "其他"

# ESPN is reachable from this host only when the environment proxy is bypassed.
# Keep normal certificate verification; this is not an SSL verification bypass.
_ESPN_DIRECT_OPENER = build_opener(
    ProxyHandler({}),
    HTTPSHandler(context=ssl.create_default_context()),
)

REGION_BY_FAMILY = {
    "CHINA": "中国", "JAPAN_KOREA": "日本韩国", "EUROPE": "欧洲",
    "NORTH_AMERICA": "北美", "AMERICAS": "拉美", "OCEANIA": "大洋洲",
    "FIBA": "FIBA", "GULF": "海湾", "ASIA": "其他亚洲",
}

def stamp(dt=None):
    return (dt or datetime.now(UTC)).astimezone(BJ).isoformat()

def parse_time(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    text = str(value or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)

def norm_team(value):
    text = canonical_team_token(value)
    aliases = {
        "北京北汽": "beijingducks", "北京首钢": "beijingducks", "beijingducks": "beijingducks",
        "广东宏远": "guangdongsoutherntigers", "广东东阳光": "guangdongsoutherntigers",
        "guangdongsoutherntigers": "guangdongsoutherntigers",
        "中国台北": "chinesetaipei", "中华台北": "chinesetaipei", "chinesetaipei": "chinesetaipei",
    }
    return canonical_team_token(aliases.get(text, text))

def _event_team_tokens(event, side):
    values=[event.get(f"{side}_name")]+list(event.get(f"{side}_aliases") or [])
    key=event.get(f"{side}_key")
    if key:values.append(key)
    return {norm_team(value) for value in values if norm_team(value)}

def _same_team_pair(left, right):
    l1,l2=_event_team_tokens(left,'team1'),_event_team_tokens(left,'team2')
    r1,r2=_event_team_tokens(right,'team1'),_event_team_tokens(right,'team2')
    return bool(l1&r1 and l2&r2)

def classify(competition, country=""):
    text = f"{competition} {country}".casefold()
    exact = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(competition or "").casefold())
    registered = _registered_league_aliases().get(exact)
    if registered:
        return registered[0], _region_for_registered(*registered)
    # 7M commonly supplies Chinese competition labels. Keep this mapping
    # explicit so discovered events are not silently downgraded to
    # UNCLASSIFIED_DISCOVERED when a broad upstream source is unavailable.
    if any(x in text for x in ("亚洲运动会", "亚运会", "亚洲杯", "亚锦赛")):
        return "FIBA_CONTINENTAL", "FIBA"
    if any(x in text for x in ("fiba", "world cup", "qualif", "国家队", "national", "olympic")):
        if any(x in text for x in ("youth", "u16", "u17", "u18", "u19", "u20")): return "FIBA_YOUTH", "FIBA"
        if "qualif" in text: return "FIBA_QUALIFIER", "FIBA"
        return ("FIBA_WOMEN" if any(x in text for x in ("women", "女")) else "FIBA_MEN"), "FIBA"
    if any(x in text for x in ("cba", "wcba", "cuba", "中国", "china")):
        if "wcba" in text or "女子" in text: return "CHINA_WCBA", "中国"
        if "cuba" in text or "大学生" in text: return "CHINA_CUBA", "中国"
        if "nbl" in text: return "CHINA_NBL", "中国"
        if any(x in text for x in ('季前','preseason','pre-season')): return "CBA_PRESEASON", "中国"
        if any(x in text for x in ('季后','playoff')): return "CBA_PLAYOFF", "中国"
        return "CBA_REGULAR", "中国"
    if any(x in text for x in ("b.league", "japan", "日本")): return "JAPAN_BLEAGUE", "日本韩国"
    if any(x in text for x in ("kbl", "korea", "韩国")): return "KOREA_KBL", "日本韩国"
    if "wnbl" in text or "澳大利亚女子" in text: return "AUSTRALIA_WNBL", "大洋洲"
    if any(x in text for x in ("australia", "nbl australia", "australian nbl", "澳大利亚国家篮球联赛", "澳洲nbl", "nbl(a)", "nbl")): return "AUSTRALIA_NBL", "大洋洲"
    if any(x in text for x in ("new zealand", "nzbl")): return "NEW_ZEALAND", "大洋洲"
    if any(x in text for x in ("eurocup", "欧篮杯", "欧女杯", "欧洲杯")): return "EUROCUP", "欧洲"
    if any(x in text for x in ("euroleague", "euro", "欧洲篮球联赛", "欧洲篮球冠军联赛", "欧冠")):
        return "EUROLEAGUE", "欧洲"
    if any(x in text for x in ("spain", "acb", "西甲", "德国", "德甲", "germany", "意甲", "italy", "法国", "法甲", "france", "turkey", "土超", "greece", "希腊", "adriatic", "亚得里亚", "欧北联", "欧洲", "以色列联赛")):
        return "EUROPE_DOMESTIC", "欧洲"
    if "wnba" in text or "美国女子职业篮球联赛" in text: return "WNBA", "北美"
    if "nba" in text or "美国职业篮球联赛" in text: return "NBA", "北美"
    # College basketball is a formal coverage family.  It must not fall into
    # NORTH_AMERICA_CLUB: that label has a different history/tier contract and
    # silently breaks the NCAA cross-source bridge.
    if any(x in text for x in ("wncaab", "ncaa women", "women's college", "women college", "女子大学")):
        return "WNCAAB", "北美"
    if any(x in text for x in ("ncaab", "ncaa", "mens college basketball", "men's college", "college basketball", "大学篮球")):
        return "NCAAB", "北美"
    if any(x in text for x in ("mexico", "brazil", "argentina", "puerto rico", "chile", "uruguay", "venezuela", "colombia", "dominican")): return "AMERICAS_OTHER", "拉美"
    if any(x in text for x in ("saudi", "uae", "qatar", "bahrain", "kuwait", "gulf")): return "GULF", "海湾"
    if any(x in text for x in ("philippines", "taiwan", "southeast", "asia")): return "OTHER_ASIA", "其他亚洲"
    return "UNCLASSIFIED_DISCOVERED", "其他"

def canonical_id(family, team1, team2, tip_utc, official_id=None):
    if official_id:
        return f"global:{family}:{official_id}"
    minute = parse_time(tip_utc).replace(second=0, microsecond=0).isoformat()
    return f"global:{family}:{norm_team(team1)}:{norm_team(team2)}:{minute}"

def _fetch_json(url, timeout, direct=False):
    req = Request(url, headers={"User-Agent": "basketball-odds-trader/3.0", "Accept": "application/json"})
    def operation():
        if direct:
            try: response_ctx = _ESPN_DIRECT_OPENER.open(req, timeout=timeout)
            except OSError: response_ctx = urlopen(req, timeout=timeout)
        else: response_ctx = urlopen(req, timeout=timeout)
        with response_ctx as response:
            # Season-wide ESPN history responses can exceed the daily
            # discovery payload. Keep a bounded but sufficient cap so the
            # box-score bridge is not silently downgraded to zero history.
            raw=response.read(20_000_001)
            return {'raw':raw,'status':response.status}
    try:
        result,attempts=request_with_retry(operation,url=url,policy=RetryPolicy(attempts=4,delays=(2,4,8)),
            validate=lambda item:bool(item.get('raw')) and len(item['raw'])<=20_000_000,
            status_of=lambda item:item.get('status'))
        _HTTP_RETRY_LOG.append({'source':'global_discovery_http','url':url,'success':True,'attempts':attempts,'attempt_count':len(attempts)})
        raw=result['raw'];return json.loads(raw.decode("utf-8", "replace")),raw
    except Exception as exc:
        _HTTP_RETRY_LOG.append({'source':'global_discovery_http','url':url,'success':False,'attempts':getattr(exc,'retry_attempts',[]),'error_type':type(exc).__name__,'error':str(exc)})
        raise

def _fetch_html(url, timeout):
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 basketball-odds-trader/3.0"})
    def operation():
        with urlopen(req,timeout=timeout) as response:return {'raw':response.read(8_000_001),'status':response.status}
    try:
        result,attempts=request_with_retry(operation,url=url,policy=RetryPolicy(attempts=4,delays=(2,4,8)),
            validate=lambda item:bool(item.get('raw')) and len(item['raw'])<=8_000_000,
            status_of=lambda item:item.get('status'))
        _HTTP_RETRY_LOG.append({'source':'global_discovery_http','url':url,'success':True,'attempts':attempts,'attempt_count':len(attempts)})
        return result['raw']
    except Exception as exc:
        _HTTP_RETRY_LOG.append({'source':'global_discovery_http','url':url,'success':False,'attempts':getattr(exc,'retry_attempts',[]),'error_type':type(exc).__name__,'error':str(exc)})
        raise

def _event(family, region, team1, team2, tip, source, source_url, official_id, competition,
           raw_path=None, team1_source_id=None, team2_source_id=None):
    dt = parse_time(tip)
    model_family = "NATIONAL_TEAM" if family.startswith("FIBA_") else ("HIGH_UNCERTAINTY" if family in {"UNCLASSIFIED_DISCOVERED","CHINA_CUBA"} else "CLUB_MATURE")
    league_key = competition_key(competition or family,
        "WOMEN" if any(x in str(competition).casefold() for x in ("women", "女", "wnba")) else "MEN")
    regulation_minutes = 48 if league_key in {"NBA", "CBA"} else 40
    # Global discovery is schedule-only, but every event still needs the
    # minimum identity contract so missing markets become NO_MARKET rows
    # instead of crashing the pricing loop.
    team1_id = f"{source}:team:{team1_source_id}" if team1_source_id is not None else f"{source}:team:{norm_team(team1)}"
    team2_id = f"{source}:team:{team2_source_id}" if team2_source_id is not None else f"{source}:team:{norm_team(team2)}"
    return {
        "event_id": canonical_id(family, team1, team2, dt, official_id),
        "canonical_event_id": canonical_id(family, team1, team2, dt, official_id),
        "source_event_id": str(official_id) if official_id is not None else None,
        "source": source, "source_name": source, "source_group": "broad",
        "upstream_provider": source.split(":", 1)[0], "source_url": source_url,
        "raw_path": str(raw_path) if raw_path is not None else None, "source_confidence": "medium",
        "team1_id": team1_id, "team2_id": team2_id,
        "team1_source_id": str(team1_source_id) if team1_source_id is not None else None,
        "team2_source_id": str(team2_source_id) if team2_source_id is not None else None,
        "team1_name": team1, "team2_name": team2,
        "team1_key": norm_team(team1), "team2_key": norm_team(team2),
        "league": competition or family, "league_family": family, "region": region,
        "competition_key": league_key,
        "season_phase": competition_phase(competition or family),
        "competition": competition or family, "competition_type": "CLUB_LEAGUE",
        "gender": "WOMEN" if any(x in str(competition).casefold() for x in ("women", "女", "wnba")) else "MEN",
        "age_group": "SENIOR", "model_family": model_family,
        "tip_at": dt.astimezone(BJ).isoformat(), "tip_time_utc": dt.isoformat(),
        "tip_time_bj": dt.astimezone(BJ).isoformat(), "bj_date": dt.astimezone(BJ).date().isoformat(),
        "source_timezone": "UTC", "identity_verified": True, "discovery_status": "DISCOVERED_ONLY",
        "market_status": "NO_MARKET", "game_minutes": regulation_minutes, "game_minutes_source": "GLOBAL_DISCOVERY_PRIOR",
        "game_minutes_used_in_pricing": False, "home_sign": 0,
        "home_adjustment_assumption": "NEUTRAL_UNLESS_VERIFIED", "venue_status": "UNKNOWN",
    }

def _american_decimal(value):
    """Convert an ESPN American price to decimal without inventing a quote."""
    text = str(value or '').strip().replace('+', '')
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if number > 0:
        return 1.0 + number / 100.0
    if number < 0:
        return 1.0 + 100.0 / abs(number)
    return None


def _espn_market_quotes(item, event, received_at):
    """Normalize a complete current spread/total contract from ESPN.

    ESPN remains schedule-only unless the response contains a line and both
    prices.  This adapter records the public API capture as the current-board
    confirmation; it never fabricates a last-change timestamp.
    """
    quotes = []
    for odds in item.get('odds') or []:
        provider = (odds.get('provider') or {}) if isinstance(odds, dict) else {}
        bookmaker = provider.get('displayName') or provider.get('name') or 'ESPN'
        spread = odds.get('pointSpread') or {}
        home = spread.get('home') or {}; away = spread.get('away') or {}
        home_obj = home.get('close') or home.get('open') or {}
        away_obj = away.get('close') or away.get('open') or {}
        home_line, away_line = home_obj.get('line'), away_obj.get('line')
        home_price, away_price = home_obj.get('odds'), away_obj.get('odds')
        try:
            line_team1 = float(str(away_line).replace('+', ''))
        except (TypeError, ValueError):
            line_team1 = None
        prices = [_american_decimal(away_price), _american_decimal(home_price)]
        if (line_team1 is not None and all(isinstance(x, (int, float)) and x > 1 for x in prices)
                and home_line is not None and away_line is not None):
            quotes.append({
                'quote_id': hashlib.sha256(f"ESPN|{event['event_id']}|SPREAD|{bookmaker}|{received_at}".encode()).hexdigest()[:24],
                'event_id': event['event_id'], 'canonical_event_id': event['event_id'],
                'source_event_id': str(event.get('source_event_id') or ''),
                'feed_provider': 'ESPN', 'upstream_provider': 'espn',
                'bookmaker_id': f"espn:{provider.get('id') or bookmaker}", 'bookmaker': bookmaker,
                'market_type': 'SPREAD', 'raw_market_key': 'pointSpread',
                'parse_status': 'PARSED_AND_NORMALIZED', 'period': 'FULL_GAME',
                'main_or_alt': 'MAIN', 'source_market_key': 'pointSpread',
                'source_array': [away_line, away_price, home_line, home_price],
                'raw_line': line_team1, 'line_team1': line_team1,
                'direction_verified': True, 'raw_prices': [away_price, home_price],
                'decimal_prices': prices, 'price_format': 'AMERICAN',
                'price_format_verified': True, 'source_quote_at': None,
                'source_timestamp_raw': None,
                'source_timestamp_semantics': 'CURRENT_BOARD_CAPTURE_ONLY',
                'received_at': received_at, 'observed_at': received_at,
                'raw_path': event.get('raw_path'), 'raw_sha256': event.get('raw_sha256'),
                'ot_rule': 'UNKNOWN', 'rule_evidence': None,
                'comparison_scope': 'VERIFIED_CURRENT_BOARD_CAPTURE',
                'current_board_contract_verified': True, 'status': 'OPEN',
                'raw_verified': bool(event.get('raw_path')), 'execution_verified': False,
                'source_name': 'ESPN_CURRENT_ODDS_API',
            })
        total = odds.get('total') or {}
        over = total.get('over') or {}; under = total.get('under') or {}
        over_obj = over.get('close') or over.get('open') or {}
        under_obj = under.get('close') or under.get('open') or {}
        over_line, under_line = over_obj.get('line'), under_obj.get('line')
        over_price, under_price = over_obj.get('odds'), under_obj.get('odds')
        try:
            line = float(re.sub(r'^[ou]', '', str(over_line), flags=re.I))
        except (TypeError, ValueError):
            line = None
        prices = [_american_decimal(over_price), _american_decimal(under_price)]
        if (line is not None and over_line is not None and under_line is not None
                and all(isinstance(x, (int, float)) and x > 1 for x in prices)):
            quotes.append({
                'quote_id': hashlib.sha256(f"ESPN|{event['event_id']}|TOTAL|{bookmaker}|{received_at}".encode()).hexdigest()[:24],
                'event_id': event['event_id'], 'canonical_event_id': event['event_id'],
                'source_event_id': str(event.get('source_event_id') or ''),
                'feed_provider': 'ESPN', 'upstream_provider': 'espn',
                'bookmaker_id': f"espn:{provider.get('id') or bookmaker}", 'bookmaker': bookmaker,
                'market_type': 'TOTAL', 'raw_market_key': 'total',
                'parse_status': 'PARSED_AND_NORMALIZED', 'period': 'FULL_GAME',
                'main_or_alt': 'MAIN', 'source_market_key': 'total',
                'source_array': [over_line, over_price, under_line, under_price],
                'raw_line': line, 'line_team1': None, 'direction_verified': True,
                'raw_prices': [over_price, under_price], 'decimal_prices': prices,
                'price_format': 'AMERICAN', 'price_format_verified': True,
                'source_quote_at': None, 'source_timestamp_raw': None,
                'source_timestamp_semantics': 'CURRENT_BOARD_CAPTURE_ONLY',
                'received_at': received_at, 'observed_at': received_at,
                'raw_path': event.get('raw_path'), 'raw_sha256': event.get('raw_sha256'),
                'ot_rule': 'UNKNOWN', 'rule_evidence': None,
                'comparison_scope': 'VERIFIED_CURRENT_BOARD_CAPTURE',
                'current_board_contract_verified': True, 'status': 'OPEN',
                'raw_verified': bool(event.get('raw_path')), 'execution_verified': False,
                'source_name': 'ESPN_CURRENT_ODDS_API',
            })
    return quotes


def _espn(day, sport, family, region, timeout, raw_dir, target_day=None):
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/{quote(sport)}/scoreboard?dates={day.replace('-', '')}"
    data, raw = _fetch_json(url, timeout, direct=True)
    path = raw_dir / f"espn_{sport.replace('/', '_')}_{day}.json"; path.write_bytes(raw)
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    rows=[]; market_quotes=[]; received_at=stamp()
    for item in data.get("events", []):
        comp=(item.get("competitions") or [{}])[0]; competitors=comp.get("competitors") or []
        if len(competitors)<2: continue
        by={x.get("homeAway"):x for x in competitors}; a=by.get("away", competitors[0]); h=by.get("home", competitors[1])
        league=((item.get("league") or {}).get("name") or sport)
        tip=item.get('date')
        try:
            local_day=parse_time(tip).astimezone(BJ).date().isoformat()
        except Exception:
            local_day=None
        if target_day and local_day != target_day:
            continue
        event=_event(family, region, a.get("team",{}).get("displayName", ""), h.get("team",{}).get("displayName", ""), tip, f"espn:{sport}", url, item.get("id"), league, path,
                     a.get("team",{}).get("id"), h.get("team",{}).get("id"))
        event['raw_sha256'] = raw_sha256
        rows.append(event)
        quote_item = dict(item)
        quote_item['odds'] = comp.get('odds') or item.get('odds') or []
        market_quotes.extend(_espn_market_quotes(quote_item,event,received_at))
    for event in rows:
        if any(q.get('event_id') == event.get('event_id') for q in market_quotes):
            event['current_market_source']='ESPN_CURRENT_ODDS_API'
    return rows, market_quotes

def _sofascore(day, timeout, raw_dir):
    url=f"https://www.sofascore.com/api/v1/sport/basketball/scheduled-events/{day}"
    data,raw=_fetch_json(url,timeout);path=raw_dir/f"sofascore_{day}.json";path.write_bytes(raw);rows=[]
    for item in data.get("events", []):
        h=item.get("homeTeam") or {}; a=item.get("awayTeam") or {}; comp=((item.get("tournament") or {}).get("uniqueTournament") or {}).get("name") or ((item.get("tournament") or {}).get("name") or "basketball")
        family,region=classify(comp, (h.get("country") or {}).get("name", ""))
        if not h.get("name") or not a.get("name") or not item.get("startTimestamp"): continue
        rows.append(_event(family,region,a["name"],h["name"],item["startTimestamp"],"sofascore",url,item.get("id"),comp,path,
                           a.get("id"), h.get("id")))
    return rows

def _fiba_calendar(day, timeout, raw_dir):
    # The official surface is attempted separately. It is an event discovery
    # source only; it is never used as a market source.
    from parsers.fiba_page_parser import parse_fiba_page, parse_fiba_rendered_landing
    url="https://www.fiba.basketball/en/games";raw=_fetch_html(url,timeout)
    page=raw.decode('utf-8','replace');(raw_dir/'fiba_games.html').write_bytes(raw)
    rows=parse_fiba_page(page,url,stamp())+parse_fiba_rendered_landing(page,url,stamp())
    out=[]
    for x in rows:
        tip=x.get('tip_utc') or x.get('start_time')
        if not tip: continue
        dt=parse_time(tip)
        if dt.astimezone(BJ).date().isoformat()!=day: continue
        fam='FIBA_WOMEN' if 'WOMEN' in str(x.get('league_family','')).upper() or '女' in str(x.get('competition','')) else 'FIBA_MEN'
        if 'QUAL' in str(x.get('competition','')).upper(): fam='FIBA_QUALIFIER'
        out.append(_event(fam,'FIBA',x.get('team_1'),x.get('team_2'),tip,'fiba_official_calendar',url,x.get('official_game_id'),x.get('competition','FIBA'),raw_dir/'fiba_games.html',
                          x.get('team_1_id'), x.get('team_2_id')))
    return out

def discover(day, output_root, timeout=12, workers=6):
    _HTTP_RETRY_LOG.clear()
    run_id=datetime.now(UTC).strftime("%Y%m%dT%H%M%S")+"_"+uuid.uuid4().hex[:8]
    raw_dir=Path(output_root)/"raw"/"global_discovery"/run_id;raw_dir.mkdir(parents=True,exist_ok=True)
    events=[];market_quotes=[];health=[];errors=[]
    adapters=[]
    target=date.fromisoformat(day)
    query_days=sorted({(target-timedelta(days=1)).isoformat(),target.isoformat()})
    for sport,family,region in (("nba","NBA","北美"),("wnba","WNBA","北美"),("mens-college-basketball","NCAAB","北美"),("womens-college-basketball","WNCAAB","北美")):
        for query_day in query_days:
            # ESPN dates are UTC; target_day is the Beijing business date.
            adapters.append((f"espn:{sport}:{query_day}",lambda sport=sport,family=family,region=region,query_day=query_day:_espn(query_day,sport,family,region,timeout,raw_dir,target_day=day)))
    adapters.append(("sofascore",lambda:_sofascore(day,timeout,raw_dir)))
    adapters.append(("fiba_official_calendar",lambda:_fiba_calendar(day,timeout,raw_dir)))
    def run_adapter(adapter):
        name, fn = adapter
        try:
            return name, fn(), None
        except Exception as exc:
            return name, [], {"error_type": type(exc).__name__, "error": str(exc)}

    # Discovery sources are independent. Bounded parallelism prevents one
    # unavailable provider's retry window from serially delaying every other
    # source while preserving each adapter's raw snapshot and health record.
    with ThreadPoolExecutor(max_workers=min(4, len(adapters))) as pool:
        adapter_results = list(pool.map(run_adapter, adapters))
    for name, rows, failure in adapter_results:
        if failure is None:
            if name.startswith('espn:'):
                espn_rows, espn_quotes = rows if isinstance(rows, tuple) else (rows, [])
                events.extend(espn_rows); market_quotes.extend(espn_quotes)
                count=len(espn_rows)
            else:
                events.extend(rows); count=len(rows)
            health.append({"source":name,"source_group":"broad" if name!="fiba_official_calendar" else "official","upstream_provider":name.split(':',1)[0],"attempted":True,"success":True,"status":"success" if count else "empty_valid_response","event_count":count,"market_quote_count":len([q for q in market_quotes if q.get('event_id')]),"captured_at":stamp(),"raw_snapshot_path":str(raw_dir)})
        else:
            errors.append({"source":name,**failure})
            health.append({"source":name,"source_group":"broad" if name!="fiba_official_calendar" else "official","upstream_provider":name.split(':',1)[0],"attempted":True,"success":False,"status":"source_unavailable",**failure,"event_count":0,"captured_at":stamp(),"raw_snapshot_path":str(raw_dir)})
    unique={}
    for e in events:
        key=(e["team1_key"],e["team2_key"],e["tip_time_utc"][:16])
        current=unique.get(key)
        if current:
            current.setdefault("discovery_sources",[]).append({"source":e["source"],"source_url":e["source_url"],"source_event_id":e.get("source_event_id")})
        else:
            e["discovery_sources"]=[{"source":e["source"],"source_url":e["source_url"],"source_event_id":e.get("source_event_id")}];unique[key]=e
    health.extend(_HTTP_RETRY_LOG)
    # Keep only quotes for de-duplicated event IDs.  If duplicate ESPN UTC
    # buckets expose the same fixture, the first complete capture is retained.
    valid_ids={str(e.get('event_id')) for e in unique.values() if e.get('event_id')}
    market_quotes=[q for q in market_quotes if q.get('event_id') in valid_ids]
    result={"run_id":run_id,"day":day,"events":list(unique.values()),"market_quotes":market_quotes,"source_health":health,"errors":errors,"raw_directory":str(raw_dir),"captured_at":stamp()}
    (raw_dir/"global_discovery.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result

def merge_with_primary(primary, discovered, quotes=None):
    """Merge global schedule identities into the existing 7M canonical pool."""
    quotes=quotes or [];out=list(primary);used=set();
    def close(a,b):
        try:return abs((parse_time(a)-parse_time(b)).total_seconds())<=300
        except Exception:return False
    for p in out:
        p.setdefault("discovery_status","MARKET_FOUND" if any(q.get("event_id")==p.get("event_id") for q in quotes) else "DISCOVERED_ONLY")
        p.setdefault("market_status","MARKET_FOUND" if any(q.get("event_id")==p.get("event_id") for q in quotes) else "NO_MARKET")
        p.setdefault("discovery_sources",[{"source":p.get("source","7M"),"source_url":p.get("source_url")}])
    for g in discovered:
        candidates=[p for p in out if close(p.get("tip_at"),g.get("tip_at")) and _same_team_pair(p,g)]
        if len(candidates)==1:
            p=candidates[0];p.setdefault("discovery_sources",[]).extend(g.get("discovery_sources",[]));p.setdefault("global_source_ids",[]).append(g.get("event_id"));used.add(g.get("event_id"))
            # Current ESPN odds are keyed by the global event ID.  Once the
            # fixture is reconciled onto an existing 7M/Titan row, carry the
            # quote to that canonical event without changing its source audit.
            for quote in quotes:
                if quote.get('event_id') == g.get('event_id'):
                    quote.setdefault('source_event_id_global', quote.get('source_event_id'))
                    quote['event_id'] = p.get('event_id')
                    quote['canonical_event_id'] = p.get('event_id')
                    quote['event_match_method'] = 'TEAM_PAIR_AND_TIP_TIME'
        elif not candidates:
            g.setdefault("discovery_status", "DISCOVERED_ONLY")
            g.setdefault("market_status", "NO_MARKET")
            out.append(g)
    return out
