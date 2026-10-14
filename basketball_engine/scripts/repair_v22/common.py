from __future__ import annotations
import hashlib, json, os, re, sys, tempfile
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Any
CODEX_ROOT=Path(os.environ.get('CODEX_ROOT', Path(__file__).resolve().parents[3]))
if str(CODEX_ROOT) not in sys.path:sys.path.insert(0,str(CODEX_ROOT))
from odds_shared.canonical_entities import default_registry, normalize_label, canonicalize_event
BJ = timezone(timedelta(hours=8))
UTC = timezone.utc

def now(): return datetime.now(UTC)
def stamp(t=None): return (t or now()).astimezone(UTC).isoformat()
def iso(s):
    d = s if isinstance(s,datetime) else datetime.fromisoformat(str(s).replace('Z','+00:00'))
    if d.tzinfo is None: raise ValueError('timezone is required')
    return d.astimezone(UTC)
def source_time(s, tz=BJ):
    if not s: return None
    s=str(s)
    if re.fullmatch(r'\d{4}(?:,\d{1,2}){5}',s):
        return datetime(*map(int,s.split(',')),tzinfo=tz).astimezone(UTC)
    try: d=datetime.fromisoformat(s.replace('Z','+00:00'))
    except ValueError: return None
    return d.replace(tzinfo=tz).astimezone(UTC) if d.tzinfo is None else d.astimezone(UTC)
def sha(b): return hashlib.sha256(b).hexdigest()
def encode(obj): return json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False).encode('utf-8')
def load(p,default=None):
    p=Path(p)
    return json.loads(p.read_text('utf-8-sig')) if p.is_file() else default

def atomic(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    data=encode(obj)+b'\n'
    fd,tmp=tempfile.mkstemp(prefix=p.name+'.',suffix='.tmp',dir=p.parent)
    try:
        with os.fdopen(fd,'wb') as f: f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,p)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def exclusive(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);data=encode(obj)+b'\n'
    try:
        with p.open('xb') as f:f.write(data)
    except FileExistsError:
        if p.read_bytes()!=data: raise ValueError('immutable record already exists with different bytes: '+str(p))
    return str(p)

def decode(b):
    for enc in ('utf-8-sig','gb18030'):
        try:return b.decode(enc)
        except UnicodeDecodeError:pass
    raise ValueError('unknown encoding; refuse replacement-character identity')

def recent_complete_days(day,n):
    d=date.fromisoformat(day)
    return [(d-timedelta(days=i)).isoformat() for i in range(1,n+1)]

def fingerprint(x):return sha(encode(x))
def safe_id(s): return re.sub(r'[^A-Za-z0-9_.-]','_',str(s))[:140]

def canonical_team_token(value):
    """Return a conservative sponsor/name-stable team token.

    Basketball boards frequently rotate Chinese sponsor names while the club
    identity is unchanged.  Only explicit, reviewed aliases are collapsed;
    unknown names remain exact normalized text and are never fuzzy-matched.
    """
    resolution=default_registry().resolve('basketball',value)
    return (resolution.canonical_team_id if resolution.method=='EXACT_REGISTERED_ALIAS'
            else normalize_label(value))

def attach_canonical_team_ids(event):
    """Attach model-safe team IDs while retaining provider IDs unchanged."""
    return canonicalize_event(event,'basketball')

def competition_phase(name):
    """Keep season phase separate from the durable league identity."""
    text=str(name or '').casefold()
    if any(x in text for x in ('summer','夏季')):return 'SUMMER_LEAGUE'
    if any(x in text for x in ('preseason','pre-season','季前','热身')):return 'PRESEASON'
    if any(x in text for x in ('playoff','季后','季後','淘汰')):return 'PLAYOFF'
    if any(x in text for x in ('regular','常规','常規')):return 'REGULAR'
    if any(x in text for x in ('club cup','俱乐部杯','俱樂部杯')):return 'CLUB_CUP'
    return 'UNKNOWN'

def competition_key(name, gender_hint=None):
    """Return a conservative cross-surface competition identity.

    7M's event/detail feed carries a numeric competition id, while the public
    team-history feed carries only a display label.  This key reconciles only
    documented display aliases; unknown labels remain isolated by their exact
    normalized text.
    """
    raw=str(name or '').strip()
    token=re.sub(r'[\s\-_/·・（）()]+','',raw).casefold()
    women=(gender_hint=='WOMEN' or '女' in raw or 'women' in token or 'wnba' in token)
    # NBA/WNBA preseason labels describe a phase, not a distinct historical
    # competition.  Keep the mature league identity; pricing applies its
    # separate preseason uncertainty multiplier downstream.
    if 'wnba' in token and any(flag in raw.casefold() for flag in ('季前','preseason','pre-season')):
        return 'WNBA'
    if 'nba' in token and 'wnba' not in token and any(flag in raw.casefold() for flag in ('季前','preseason','pre-season')):
        return 'NBA'
    # CBA phase/sponsor labels belong to one league identity.  Tier and model
    # uncertainty continue to use ``season_phase`` rather than this key.
    if token in {'cba','cba常规赛','cba季后赛','cba季前','cba季前赛','cba夏季联赛',
                 '中国男子篮球职业联赛'}:
        return 'CBA'
    aliases=(
        ('WNBA', ('wnba','美国女子职业篮球联赛')),
        ('NBA', ('nba','美国职业篮球联赛','美国男子职业篮球联赛')),
        ('EUROLEAGUE', ('euro','euroleague','euroleague basketball','欧洲篮球联赛','欧洲篮球冠军联赛','欧冠')),
        ('EUROCUP', ('eurocup','欧篮杯','欧洲杯','欧协杯','欧洲篮球联盟杯')),
        ('EUROLEAGUE_WOMEN', ('欧洲女子篮球联赛','欧女联')),
        ('EUROCUP_WOMEN', ('欧女杯',)),
        ('FIBA_EUROPE_CUP', ('欧洲篮球男子俱乐部杯预选赛','欧俱预选','欧俱杯')),
        ('EUROPE_DOMESTIC', ('德甲','西甲','意甲','意杯','意超杯','法甲','土超','希腊联赛','以色列联赛',
                             '拉脱甲','爱拉联','立陶联','英超','爱沙超','罗甲','科索超','匈女篮','立陶女联','bnxt','荷甲')),
        ('AUSTRALIA_NBL', ('nbl','nbl(a)','nbl australia','australian nbl','澳大利亚国家篮球联赛','澳大利亚nbl','澳洲nbl')),
        ('AUSTRALIA_WNBL', ('wnbl','澳大利亚女子篮球联赛')),
        # The 7M team-history feed abbreviates the same Japanese B.League
        # family as 日B1/日B2/日B3.  Keep the division in phase/competition
        # metadata, but use one family key so history remains joinable.
        ('JAPAN_BLEAGUE', ('b.league','日本b联赛','日本男子b联赛甲级联赛','日本男子b联赛超级联赛','日本男子b联赛次级联赛','日b1','日b2','日b3','japanb1','japanb2','japanb3')),
        ('KOREA_KBL', ('kbl','韩国篮球联赛')),
        ('FIBA_CONTINENTAL', ('亚洲运动会女子篮球赛','亚洲运动会男子篮球赛','亚洲杯','亚运会')),
        ('ASIAN_GAMES_WOMEN', ('亚运女篮','亚洲运动会女篮')),
        ('ASIAN_GAMES_MEN', ('亚运男篮','亚洲运动会男篮')),
        ('FRANCE_CUP', ('法国杯','法国篮球杯赛')),
        ('CHILE_LEAGUE', ('智利联','智利篮球联赛')),
        ('MEXICO_LEAGUE', ('墨联','墨西哥篮球联赛')),
        ('PARAGUAY_LEAGUE', ('巴拉联','巴拉圭国家篮球联赛','巴拉圭篮球联赛')),
        ('PUERTO_RICO_WOMEN', ('波多女篮','波多黎各联女篮','波多黎各女篮联赛')),
        ('KOREA_UNIVERSITY_WOMEN', ('韩大学女联','韩国大学女子篮球联赛','韩国大学篮球联赛')),
        ('CZECH_NBL', ('捷克篮球甲联联赛','捷甲','czech nbl')),
        ('GREECE_WOMEN_CUP', ('希女杯','greece women cup')),
        ('TUNISIA_LEAGUE', ('突尼联','tunisia')),
        ('UAE_CUP', ('阿联酋杯','uae cup')),
        ('CANADA_WOMEN_ABL', ('加女篮abl','canada women abl')),
        ('ESTONIA_LATVIA_LEAGUE', ('爱沙尼亚与拉脱维亚篮球联合联赛','estonia latvia')),
        ('UGANDA_WOMEN_LEAGUE', ('乌干女联','uganda women')),
        ('KENYA_WOMEN_LEAGUE', ('肯女篮联','kenya women')),
        ('SWEDEN_BASKETETTAN', ('瑞典甲','sweden basketettan','basketettan')),
        ('VTB_UNITED', ('vtb联','vtb杯','vtb united league')),
        ('SINGAPORE_NBL', ('新加坡nbl','singapore nbl')),
        ('ENBL', ('enbl','european north basketball league','欧洲北部篮球联赛','欧北联')),
        ('FINLAND_DIVISION_1', ('芬兰甲','芬兰篮球甲级联赛')),
        ('PHILIPPINES_UAAP', ('菲uaap','uaap')),
        ('PHILIPPINES_MPBL', ('菲mpbl','菲mpbl季后','mpbl')),
    )
    for key,names in aliases:
        if token in {re.sub(r'[\s\-_/·・（）()]+','',x).casefold() for x in names}:
            if key=='ASIAN_GAMES_MEN' and women:return 'ASIAN_GAMES_WOMEN'
            if key=='KOREA_UNIVERSITY_WOMEN' and not women:return 'KOREA_UNIVERSITY_MEN'
            return key
    return 'LABEL:'+token

# Parse JavaScript DATA literals, never execute downloaded scripts.
class JSLiteral:
    def __init__(self,s,start=0):self.s=s;self.i=start
    def ws(self):
        while self.i<len(self.s):
            if self.s[self.i].isspace():self.i+=1
            elif self.s.startswith('//',self.i):
                e=self.s.find('\n',self.i);self.i=len(self.s) if e<0 else e+1
            elif self.s.startswith('/*',self.i):
                e=self.s.find('*/',self.i+2)
                if e<0:raise ValueError('unterminated comment')
                self.i=e+2
            else:break
    def value(self):
        self.ws()
        if self.i>=len(self.s):raise ValueError('end of data')
        c=self.s[self.i]
        if c in "\"'":return self.string()
        if c=='[':
            self.i+=1;out=[];self.ws()
            while self.i<len(self.s) and self.s[self.i]!=']':
                if self.s[self.i]==',':out.append(None);self.i+=1;self.ws();continue
                out.append(self.value());self.ws()
                if self.s[self.i]==',':self.i+=1;self.ws()
                elif self.s[self.i]!=']':raise ValueError('array separator')
            if self.i>=len(self.s):raise ValueError('unterminated array')
            self.i+=1;return out
        if c=='{':
            self.i+=1;out={};self.ws()
            while self.i<len(self.s) and self.s[self.i]!='}':
                if self.s[self.i] in "\"'":k=self.string()
                else:
                    m=re.match(r'[A-Za-z_$\d][\w$.-]*',self.s[self.i:])
                    if not m:raise ValueError('object key')
                    k=m.group();self.i+=len(k)
                self.ws()
                if self.s[self.i]!=':':raise ValueError('object colon')
                self.i+=1;out[str(k)]=self.value();self.ws()
                if self.s[self.i]==',':self.i+=1;self.ws()
                elif self.s[self.i]!='}':raise ValueError('object separator')
            if self.i>=len(self.s):raise ValueError('unterminated object')
            self.i+=1;return out
        for token,v in [('true',True),('false',False),('null',None),('undefined',None)]:
            if self.s.startswith(token,self.i) and (self.i+len(token)==len(self.s) or not self.s[self.i+len(token)].isalnum()):self.i+=len(token);return v
        m=re.match(r'-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',self.s[self.i:])
        if not m:raise ValueError('not a safe literal: '+self.s[self.i:self.i+40])
        v=m.group();self.i+=len(v);return float(v) if any(t in v for t in '.eE') else int(v)
    def string(self):
        q=self.s[self.i];self.i+=1;out=[]
        while self.i<len(self.s):
            c=self.s[self.i];self.i+=1
            if c==q:return ''.join(out)
            if c=='\\':
                if self.i>=len(self.s):raise ValueError('escape')
                c=self.s[self.i];self.i+=1
                if c in ('u','x'):
                    n=4 if c=='u' else 2;out.append(chr(int(self.s[self.i:self.i+n],16)));self.i+=n
                else:out.append({'n':'\n','r':'\r','t':'\t','b':'\b','f':'\f'}.get(c,c))
            else:out.append(c)
        raise ValueError('unterminated string')

def assignments(text):
    out={}
    for m in re.finditer(r'(?:\bvar\s+|\blet\s+|\bconst\s+)?(\b[A-Za-z_$][\w$]*(?:\[\s*\d+\s*\])*)\s*=\s*',text):
        try:out[m.group(1).replace(' ','')]=JSLiteral(text,m.end()).value()
        except (ValueError,IndexError):continue
    return out
