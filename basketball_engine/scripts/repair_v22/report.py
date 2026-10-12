from __future__ import annotations
from pathlib import Path
import json, csv, html
from collections import Counter
from .common import atomic, canonical_team_token, iso, load, stamp, safe_id

REASONS={
'QUOTE_EVENT_MISMATCH':'盘口不属于该场比赛','BOOKMAKER_UNKNOWN':'盘口公司未核验','PERIOD_UNVERIFIED_OR_UNSUPPORTED':'时段未核验或暂不支持','MARKET_NOT_OPEN':'盘口并未开放','OPEN_STATUS_UNVERIFIED':'当前仍挂牌状态未核验','EXISTING_PAPER_ENTRY_NO_DUPLICATE':'本场已有纸面单，不重复计入','TARGET_ALREADY_STARTED':'比赛已开始，不能补写赛前预测','EVENT_ALREADY_STARTED':'比赛已开始','NO_MARKET':'暂无同场可验证盘口',
'INSUFFICIENT_PRE_CUTOFF_HISTORY':'截止前同赛事历史不足','MODEL_EVIDENCE_NOT_PAPER_ELIGIBLE':'比分研究基线证据不足以触发纸面单',
'RAW_ODDS_NOT_INCLUDED_IN_DEBUG_BUNDLE':'诊断包未包含盘口原始响应','LEGACY_LOST_SECOND_SIDE_AND_DIRECTION':'旧标准化丢失另一侧水位及方向',
'RAW_QUOTE_NOT_VERIFIED':'盘口原文未核验','SELECTION_DIRECTION_UNVERIFIED':'盘口对应球队/方向待核验',
'PRICE_FORMAT_UNVERIFIED':'赔率格式尚未核验','UNKNOWN_OT_RULE':'加时结算规则未确认','OT_POLICY_MISMATCH':'该盘口明确为常规时间结算，与全场含加时策略不一致','STALE_QUOTE':'盘口已过期',
'QUOTE_TIME_UNKNOWN':'盘口时间不明确','QUOTE_TIME_IN_FUTURE':'盘口时间异常：晚于截止时间','CAPTURE_AFTER_CUTOFF':'抓取晚于截止时间',
'ONLY_H2H_OR_SINGLE_OPPONENT':'仅有交锋/单一对手样本','SMALL_SAMPLE':'历史样本偏少','TEAM_HISTORY_FEED_NOT_CAPTURED':'未取得完整球队近期战绩流',
'CURRENT_ROSTER_UNVERIFIED':'当前名单尚未核验','INJURY_UNKNOWN':'伤停未知','UNVALIDATED_SCORE_BASELINE':'未校准的比分研究基线',
'MAIN_MARKET_UNVERIFIED':'主盘/替代盘待核验','IDENTITY_CONFLICT':'赛事身份冲突','LIVE_SOURCE_FAILED':'本轮实时数据获取失败',
'HISTORY_ESS_TOO_LOW':'历史有效样本量不足','OPPONENT_DIVERSITY_TOO_LOW':'加权对手多样性不足',
'ROSTER_STABILITY_UNKNOWN':'近30日阵容稳定性未知','LINEUP_UNKNOWN':'轮换/预期出场时间未知',
'PACE_EVIDENCE_MISSING':'回合数核心证据缺失','MODEL_CORE_INPUT_MISSING':'核心模型输入不完整',
'TEAM_HISTORY_FEED_NOT_CAPTURED':'球队历史数据链未捕获（数据管道故障）'}

def explain(s): return REASONS.get(s,s)
def csvwrite(path,rows,fields):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader()
        for r in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()})

def project_row(event,pricing,quotes,decision,states,mode):
    return {'id':event['event_id'],'event':event,'pricing':pricing,'market':{'quotes':quotes,'quote_states':states},
      'execution':decision,'generation':'REPAIR_V22','archive_type':mode,
      'display':{'status':decision['display_action'],'reasons':[explain(x) for x in decision.get('blockers',[])],
                 'warnings':[explain(x) for x in pricing.get('model_warnings',[])]}}

def _market_decisions(execution):
    """Return isolated market decisions, with a legacy single-market fallback."""
    execution = execution or {}
    decisions = execution.get('market_decisions')
    if isinstance(decisions, dict) and decisions:
        return {name: value for name, value in decisions.items()
                if name in ('SPREAD', 'TOTAL') and isinstance(value, dict)}
    selected = execution.get('selected')
    if isinstance(selected, dict) and selected.get('market_type') in ('SPREAD', 'TOTAL'):
        name = selected['market_type']
        return {name: dict(execution, market_type=name, selected=selected)}
    return {}

def funnel(rows):
    source_rows = list(rows)
    def view_execution(row):
        merged = row.get('display_execution') or {}
        # ``display_execution`` is normally only a current refresh snapshot.
        # Use it for funnel accounting only when the display pass explicitly
        # marked it as a market-level merge; otherwise the immutable frozen
        # execution remains authoritative.
        return merged if merged.get('display_merged_market_view') else (row.get('execution') or {})
    paper_count = sum(bool(view_execution(r).get('triggered')) for r in rows)
    rows = [dict(r, **r.get('current_snapshot', {})) for r in rows]
    market_records = [(market, decision, row) for row in source_rows
                      for market, decision in _market_decisions(view_execution(row)).items()]
    paper_markets = [(market, decision, row) for market, decision, row in market_records
                     if decision.get('triggered') is True]
    spread_markets = [x for x in paper_markets if x[0] == 'SPREAD']
    total_markets = [x for x in paper_markets if x[0] == 'TOTAL']
    state_counts = Counter((r.get('pricing') or {}).get('pricing_state', 'UNPRICEABLE') for r in rows)
    return {'events':len(rows),'market_observed_events':sum(bool(r['market']['quotes']) for r in rows),
      'raw_verified_market_events':sum(any(s['raw_observation'] for s in r['market']['quote_states']) for r in rows),
      'fresh_market_events':sum(any(s['fresh_observation'] for s in r['market']['quote_states']) for r in rows),
      'independent_priceable_events':sum(r['pricing']['pricing_status']!='UNPRICEABLE' for r in rows),
      'research_priceable_events':sum(bool(r['pricing'].get('research_priceable')) for r in rows),
      'cold_start_priceable_events':sum(bool(r['pricing'].get('cold_start_priceable')) for r in rows),
      'prior_only_price_events':sum(bool(r['pricing'].get('prior_only_price')) for r in rows),
      'shadow_eligible_events':sum(bool(r['pricing'].get('shadow_eligible')) for r in rows),
      'executable_events':sum(bool(r['pricing'].get('executable_eligible')) for r in rows),
      'pricing_state_counts':dict(state_counts),
      'research_coupled_events':sum(r['pricing']['pricing_status']!='UNPRICEABLE' and any(s['raw_observation'] for s in r['market']['quote_states']) for r in rows),
      'comparable_events':sum(bool(r['execution'].get('comparison_ready')) for r in rows),
      'paper_triggered_events':paper_count,
      'paper_bettable':paper_count if any(r['execution'].get('comparison_ready') for r in rows) else None,
      'blocked_events':sum(r['execution']['shadow_action']=='BLOCKED' for r in rows),
      'market_records':len(market_records),
      'market_observed_markets':sum(any(q.get('market_type') == market for q in r['market'].get('quotes', []))
                                   for market, _decision, r in market_records),
      'comparable_markets':sum(bool(decision.get('comparison_ready')) for _market, decision, _row in market_records),
      'paper_triggered_markets':len(paper_markets),
      'paper_triggered_spread_markets':len(spread_markets),
      'paper_triggered_total_markets':len(total_markets),
      'market_key': 'canonical_event_id + market_type'}


def cold_start_summary(rows):
    """Read-only league lifecycle summary; never changes a decision."""
    grouped = {}
    for r in rows:
        e = r.get('event') or {}
        p = r.get('pricing') or {}
        key = e.get('league_family') or e.get('competition_key') or e.get('league') or 'UNKNOWN'
        item = grouped.setdefault(key, {
            'league_family': key, 'discovered': 0, 'market_found': 0,
            'current_season_history': 0, 'previous_season_history': 0,
            'older_history': 0, 'effective_sample_size_min': None,
            'research_priceable': 0, 'cold_start_priceable': 0,
            'shadow_eligible': 0, 'executable': 0, 'states': Counter(),
            'blockers': Counter(), 'event_ids': []})
        item['discovered'] += 1
        item['market_found'] += int(bool((r.get('market') or {}).get('quotes')))
        item['current_season_history'] += int(p.get('current_season_games') or 0)
        item['previous_season_history'] += int(p.get('previous_season_games') or 0)
        item['older_history'] += int(p.get('older_history_games') or 0)
        ess = p.get('effective_sample_size')
        if isinstance(ess, (int, float)):
            item['effective_sample_size_min'] = ess if item['effective_sample_size_min'] is None else min(item['effective_sample_size_min'], ess)
        item['research_priceable'] += int(bool(p.get('research_priceable')))
        item['cold_start_priceable'] += int(bool(p.get('cold_start_priceable')))
        item['shadow_eligible'] += int(bool(p.get('shadow_eligible')))
        item['executable'] += int(bool(p.get('executable_eligible')))
        item['states'][p.get('pricing_state', 'UNPRICEABLE')] += 1
        for blocker in p.get('blockers') or []:
            item['blockers'][blocker] += 1
        item['event_ids'].append(r.get('id'))
    for item in grouped.values():
        item['states'] = dict(item['states'])
        item['blockers'] = dict(item['blockers'])
    return {'leagues': grouped, 'status_lifecycle': ['DISCOVERY', 'BOOTSTRAP', 'SHADOW', 'PROVISIONAL', 'QUALIFIED']}

HTML = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>篮球量化交易 · 数据核验与纸面模拟</title><style>
:root{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#142e40;background:#f3f6f9}body{margin:0;padding:24px;max-width:1400px;margin:auto}h1{font-size:25px}h2{font-size:20px}h3{font-size:16px}.bar,.card{background:white;border:1px solid #d9e2ec;border-radius:10px;padding:18px;margin-bottom:16px}.topbar{position:sticky;top:0;z-index:20;box-shadow:0 5px 18px rgba(20,46,64,.10)}.paper-focus{border:2px solid #48a77b;background:linear-gradient(135deg,#effbf5,#fff)}.paper-focus h2{margin-top:0}.paper-actions{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}.paper-actions button{cursor:pointer;font-weight:750}.paper-actions .active{background:#147457;color:#fff;border-color:#147457}.paper-picks{display:grid;gap:8px;margin-top:12px}.paper-pick{display:grid;grid-template-columns:minmax(240px,1.3fr) minmax(180px,1fr) minmax(240px,1.4fr);gap:12px;padding:12px 14px;border:1px solid #bfe4d1;border-radius:8px;background:#fff}.paper-pick .pick{color:#136546;font-weight:800}.diagnostic-divider{margin:28px 0 14px;padding-top:18px;border-top:3px solid #d9e2ec}.sub{color:#5b7182;font-size:13px;line-height:1.8}.warn{color:#a95b00}.bad{color:#a42727}.good{color:#147457}.material-drift{color:#a42727;font-weight:800;border-left:4px solid #c33434;padding:10px 12px;background:#fff1f1}.badge{display:inline-block;padding:7px 12px;background:#fbe8e8;border-radius:6px;font-size:19px;font-weight:750}.observe{background:#fff2d6;color:#9b5900}.can{background:#d9f3e7;color:#136546}.metric{display:inline-block;padding:9px 20px 9px 0;font-size:14px}.metric b{display:block;font-size:24px}.controls{display:inline-flex;gap:10px;align-items:center;flex-wrap:wrap}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.grid>div{background:#f6f9fc;border:1px solid #dce5ef;border-radius:6px;padding:14px}.tablewrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:10px;border-bottom:1px solid #dce5ef;white-space:nowrap}th{background:#f3f7fb}details{margin-top:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}select,button{padding:8px 12px;border:1px solid #bccad6;border-radius:5px;background:white}.foot{margin-top:20px}.missing{color:#8b650c}.lifecycle{border-left:4px solid #2878b9;padding-left:12px;margin:12px 0}.experimental{border-left-color:#a95b00}@media(max-width:720px){body{padding:12px}.topbar{position:static}.paper-pick{grid-template-columns:1fr}.grid{grid-template-columns:1fr}.metric{padding-right:12px}h1{font-size:21px}.bar,.card{padding:12px}}</style>
<h1>篮球量化交易 · 纸面模拟</h1><div class="bar topbar"><strong>真实执行：关闭</strong>　模型：未校准研究基线　<div class="controls"><label>北京时间日期 <select id="date"></select></label><label>筛选 <select id="filter"><option value="ALL">全部赛事</option><option value="PAPER_BETTABLE">纸面可投</option></select></label></div><div class="sub" id="meta">正在载入</div></div><div class="bar paper-focus" id="paper-focus"></div><div id="rows"></div><div class="diagnostic-divider"><h2>研究与审计</h2><div class="sub">以下内容用于解释数据覆盖、定价漏斗与模型审计；比赛与纸面可投赛事已优先展示在上方。</div></div><div class="bar" id="funnel"></div><div class="bar" id="analytics"></div><div class="bar" id="pricing-funnel-diagnostic"></div><div class="bar" id="history-readiness-diagnostic"></div><div class="bar" id="coverage"></div><div class="sub foot">原生前向、包内核查、比分重建、旧版记录分开计数。观察/阻塞不是下注。缺少原文、方向或规则不能用近似值凑成可投。</div><script>
const esc=x=>String(x??'未获取').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=x=>x==null?'未获取':Number(x).toFixed(2).replace(/\.00$/,'');
function fair(e,m){if(m==null)return '未获取';return esc(m>=0?e.team1_name:e.team2_name)+' '+(m===0?'平手（0分）':'让 '+num(Math.abs(m))+' 分（-'+num(Math.abs(m))+'）');}
function quoteLabel(e,q){if(q.raw_line==null)return '未获取';if(q.market_type==='TOTAL')return '总分 '+num(q.raw_line)+' 分';if(q.direction_verified&&q.line_team1!=null)return esc(e.team1_name)+' '+(q.line_team1<0?'让 ':'受让 ')+num(Math.abs(q.line_team1))+' 分（'+(q.line_team1>=0?'+':'')+num(q.line_team1)+'）';return '方向未核验（幅度 '+num(Math.abs(q.raw_line))+' 分）';}
function priceLabel(q){return q.decimal_prices?q.decimal_prices.map(num).join(' / '):'原水位 '+(q.raw_prices||[]).map(num).join(' / ')+'；格式/双边待核验';}
 function selectionLabel(e,s){if(!s)return '无可执行方向';if(s.market_type==='TOTAL')return (s.selection==='OVER'?'大于 ':'小于 ')+num(s.line)+'分 @ '+num(s.decimal_odds);let team=s.selection==='TEAM1'?e.team1_name:e.team2_name;return esc(team)+' '+(s.line<0?'让 ':'受让 ')+num(Math.abs(s.line))+' 分 @ '+num(s.decimal_odds);}
function decisionReason(r){let a=r.execution;if(a.comparison_ready){if(a.triggered)return '独立定价与实际盘口比较后，通过纸面执行门槛';if(a.model_state==='LEAN')return '比较方向存在正期望，但未通过保守情景门槛';if(a.model_state==='NO_EDGE')return '独立定价与实际盘口比较后，没有达到正向优势';}return (r.display.reasons||[]).join('；')||'已完成纸面规则判断';}
function comparisonBlock(e,p,a,qs){let md=a.market_decisions||{};let keys=['SPREAD','TOTAL'];let blocks=keys.map(k=>{let d=md[k];if(!d)return '';let s=d.selected;let q=s?qs.find(x=>x.quote_id===s.quote_id):null;let model=k==='SPREAD'?fair(e,p.mu_raw):'模型总分 '+num(p.total_raw)+'分';let market=q?quoteLabel(e,q)+'；双边十进制赔率 '+priceLabel(q):'暂无同市场有效盘口';let state=d.triggered?'纸面可投':d.comparison_ready?'已比较，未通过门槛':(k==='TOTAL'?'总分诊断观察':'不可投');let reason=(d.blockers||[]).join('；')||((d.uncertainty_flags||[]).join('；'));return '<section class="market-decision"><h4>'+ (k==='SPREAD'?'让分判断':'大小分判断') +'：'+state+'</h4><p><strong>独立模型：</strong>'+model+'</p><p><strong>实际盘口：</strong>'+market+'</p><p><strong>模型方向：</strong>'+selectionLabel(e,s)+'</p><p class="sub">模型状态：'+esc(d.model_state||'未确认')+' ｜ 预期收益：'+num((d.ev||0)*100)+'%'+(reason?' ｜ '+esc(reason):'')+'</p></section>';}).join('');if(blocks)return blocks;return '<p class="missing">尚无可进行同场同规则比较的盘口。</p>';}
const dataRoot=new URL('./basketball-data/',location.href);let currentData=null;let currentFilter='PAPER_BETTABLE';
function setDashboardFilter(value){currentFilter=value;const filter=document.querySelector('#filter');if(filter)filter.value=value;if(currentData)render(currentData);window.scrollTo({top:0,behavior:'smooth'});}
function renderPaperFocus(d){const box=document.querySelector('#paper-focus');if(!box)return;const events=d.events||[],paper=events.filter(r=>r.execution&&r.execution.shadow_action==='SHADOW_BET'&&r.execution.triggered===true);const picks=paper.map(r=>{const e=r.event||{},a=r.execution||{};return '<div class="paper-pick"><strong>'+esc(e.team1_name)+' vs '+esc(e.team2_name)+'</strong><span class="pick">'+selectionLabel(e,a.selected)+'</span><span class="sub">'+esc(e.league_display||e.league)+' ｜ '+esc(e.tip_time_bj)+'</span></div>';}).join('');box.innerHTML='<h2>今日纸面可投赛事 '+esc(paper.length)+' 场</h2><div class="paper-actions"><button class="'+(currentFilter==='PAPER_BETTABLE'?'active':'')+'" onclick="setDashboardFilter(\'PAPER_BETTABLE\')">只看纸面可投（'+esc(paper.length)+'）</button><button class="'+(currentFilter==='ALL'?'active':'')+'" onclick="setDashboardFilter(\'ALL\')">查看全部赛事（'+esc(events.length)+'）</button></div>'+(picks||'<p class="missing">当前日期没有通过严格门槛的纸面可投赛事，可切换“全部赛事”查看观察与阻塞记录。</p>')+'<p class="sub">纸面可投是不可变首写资格；是否仍可按当前盘口进入，以每场卡片中的本轮复核状态为准。真实资金执行关闭。</p>';}
async function get(u){const r=await fetch(u,{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status+' '+u);return r.json();}
function legacyRow(r){return '<div class="card"><h2>'+esc(r.match||r.title||r.teams||r.id||'旧版历史记录')+'</h2><div class="sub">旧版迁移记录；不计入修复版验证样本。</div><details><summary>查看原始历史字段</summary><pre>'+esc(JSON.stringify(r,null,2))+'</pre></details></div>';}
function render(d){currentData=d;renderPaperFocus(d);document.querySelector('#meta').textContent='资料类型：'+(d.archive_type||'旧版记录')+' ｜ 数据截止：'+(d.asof||d.generated_at||'未知')+' ｜ 页面生成：'+(d.generated_at||'未知')+' ｜ '+(d.message||'');
 const f=d.funnel||{};const keys=[['赛事','events'],['有盘口记录','market_observed_events'],['新鲜原始盘口','fresh_market_events'],['独立研究定价','independent_priceable_events'],['同场同规则比较','comparable_events'],['纸面触发','paper_triggered_events']];
 document.querySelector('#funnel').innerHTML=keys.map(([n,k])=>'<span class="metric">'+n+'<b>'+esc(f[k]??'—')+'</b></span>').join('')+'<div class="warn">'+(f.comparable_events>0?'已比较样本内纸面可投：'+esc(f.paper_bettable)+'场；不代表全部赛事。':'可投结论：暂不可判断，暂无同场同规则有效比较。')+'</div>';
 document.querySelector('#rows').innerHTML=(d.events||[]).filter(r=>typeof isVisible==='function'?isVisible(r):(currentFilter!=='PAPER_BETTABLE'||(r.execution&&r.execution.shadow_action==='SHADOW_BET'&&r.execution.triggered===true))).map(r=>{if(!r.event||r.generation!=='REPAIR_V22')return legacyRow(r);let e=r.event,p=r.pricing,a=r.execution,qs=r.market.quotes||[];let continuity=a.titan_provisional_continuity||{},historicSelection=continuity.selected;return '<article class="card"><h2>'+esc(e.team1_name)+' vs '+esc(e.team2_name)+'</h2><div class="sub">'+esc(e.league_display||e.league)+' ｜ '+esc(e.tip_time_bj)+' ｜ '+esc(e.event_id)+'</div><p><span class="badge '+(a.shadow_action==='WATCH'?'observe':a.triggered?'can':'')+'">'+esc(a.display_action)+'</span></p><p><strong>'+(a.triggered?'纸面方向：':historicSelection?'历史 Titan 首写方向：':'模型相对盘口方向：')+'</strong>'+selectionLabel(e,a.comparison_ready?a.selected:null||historicSelection)+'</p>'+(continuity.status==='HISTORICAL_FIRST_WRITE_RETAINED'?'<div class="warn"><strong>历史首写已保留：</strong>来源更换赛事 ID，不新建信号或执行；当前行情复核 '+esc(continuity.current_revalidation_status||'UNAVAILABLE')+'。</div>':'')+'<div class="'+(a.triggered?'good':'bad')+'">'+esc(decisionReason(r))+'</div><div class="grid"><div><h3>独立定价</h3>独立比分基线：<b>'+fair(e,p.mu_raw)+'</b><p>模型总分：<b>'+num(p.total_raw)+'分</b>　口径：含加时比分均值</p><div class="sub">有效历史 '+esc(p.input_games??0)+' 场；证据质量 '+esc(p.pricing_data_quality??0)+'/100<br>'+esc((r.display.warnings||[]).join('；'))+'</div></div><div><h3>独立模型 vs 实际盘口</h3>'+comparisonBlock(e,p,a,qs)+'<div class="sub">这里只展示生产流水线在数据截止时冻结的比较结果；真实执行关闭。</div></div></div><details><summary>盘口原文、公司、双方水位与时效</summary><div class="tablewrap"><table><thead><tr><th>公司</th><th>盘口</th><th>价格</th><th>主/替代盘</th><th>源时间</th><th>接收时间</th><th>结算口径</th></tr></thead><tbody>'+qs.map(q=>'<tr><td>'+esc(q.bookmaker||q.bookmaker_id)+'</td><td>'+quoteLabel(e,q)+'</td><td>'+priceLabel(q)+'</td><td>'+esc(q.main_or_alt)+'</td><td>'+esc(q.source_quote_at)+'</td><td>'+esc(q.received_at)+'</td><td>'+(q.ot_rule==='INCLUDING_OT'?'含加时（纸面口径）':esc(q.ot_rule))+'</td></tr>').join('')+'</tbody></table></div></details><details><summary>输入证据与技术审计</summary><pre>'+esc(JSON.stringify({pricing:p,execution:a,identity:e},null,2))+'</pre></details></article>';}).join('')||(currentFilter==='PAPER_BETTABLE'?'<div class="card">当前日期没有纸面可投赛事。</div>':'<div class="card">本日期没有可显示记录。请检查采集错误，不能将此解释为全球没有比赛。</div>');}
 (async()=>{try{const filter=document.querySelector('#filter');filter.value=currentFilter;filter.onchange=()=>{currentFilter=filter.value;if(currentData)render(currentData)};if(window.__AUDIT_DATA__){document.querySelector('#date').innerHTML='<option>包内核查</option>';render(window.__AUDIT_DATA__);return;}const index=await get(new URL('index.json',dataRoot));const entries=(index.dates||[]).map(x=>typeof x==='string'?{date:x,file:x+'.json'}:x);const sel=document.querySelector('#date');sel.innerHTML=entries.map(x=>'<option value="'+esc(x.file||x.date+'.json')+'">'+esc(x.date)+'</option>').join('');sel.onchange=async()=>{try{render(await get(new URL(sel.value,dataRoot)))}catch(e){document.querySelector('#meta').textContent=e.message}};const latest=await get(new URL('latest.json',dataRoot));sel.value=(latest.date_bj||latest.date||'')+'.json';render(latest);}catch(e){document.querySelector('#meta').textContent='数据载入失败：'+e.message+'；本地预览请通过HTTP服务，不要双击在线版HTML。'}})();
 const renderWithCurrentDisplay=render;render=function(d){renderWithCurrentDisplay(d);const visible=(d.events||[]).filter(r=>currentFilter!=='PAPER_BETTABLE'||(r.execution&&r.execution.shadow_action==='SHADOW_BET'&&r.execution.triggered===true));document.querySelectorAll('#rows > .card').forEach((card,i)=>{const r=visible[i],de=r?.display_execution,ev=r?.display_event||r?.event;if(!de||!de.selected||!ev)return;const label=selectionLabel(ev,de.selected);Array.from(card.querySelectorAll('p')).forEach(p=>{const strong=p.querySelector('strong');if(strong&&strong.textContent.includes('方向'))p.innerHTML='<strong>'+esc(strong.textContent)+'</strong>'+label;});const grid=card.querySelector('.grid');const right=grid?.children?.[1];if(right)right.innerHTML='<h3>独立模型 vs 实际盘口</h3>'+comparisonBlock(ev,r.display_pricing||r.pricing,de,r.display_market?.quotes||[])+ '<div class="sub">这里只展示生产流水线在数据截止时冻结的比较结果；真实执行关闭。</div>';});};
 const renderBase=render;
render=function(d){renderBase(d);const visible=(d.events||[]).filter(r=>currentFilter!=='PAPER_BETTABLE'||(r.execution&&r.execution.shadow_action==='SHADOW_BET'&&r.execution.triggered===true));document.querySelectorAll('#rows > .card').forEach((card,i)=>{const r=visible[i];if(!r?.execution?.triggered)return;const s=r.settlement;const node=document.createElement('p');node.className='paper-settlement';node.textContent=s?'纸面结算：'+({WIN:'赢',LOSS:'输',PUSH:'走水'}[s.outcome]||'待核验')+' ｜ '+r.event.team1_name+' '+s.score1+' : '+s.score2+' '+r.event.team2_name+' ｜ 纸面盈亏 '+num(s.paper_pnl)+'U':'纸面结算：待确认终场赛果';card.insertBefore(node,card.querySelector('.grid'));});};
const renderWithSettlement=render;
render=function(d){renderWithSettlement(d);const visible=(d.events||[]).filter(r=>currentFilter!=='PAPER_BETTABLE'||(r.execution&&r.execution.shadow_action==='SHADOW_BET'&&r.execution.triggered===true));document.querySelectorAll('#rows > .card').forEach((card,i)=>{
 const r=visible[i], c=r?.current_snapshot;if(!c)return;
 const grid=card.querySelector('.grid');if(!grid)return;
 const badge=card.querySelector('.badge');if(badge)badge.textContent+='（首写记录）';
 grid.querySelectorAll('h3').forEach(h=>h.textContent='首写纸面记录 · '+h.textContent);
 grid.innerHTML=grid.innerHTML.replace('实际盘口：</strong>','首写盘口：</strong>');
 const old=card.querySelector('details > summary');if(old)old.textContent='首写盘口证据（回测依据，不代表当前盘口）';
 const panel=document.createElement('section');panel.className='current-market';
 const qs=c.market?.quotes||[], states=c.market?.quote_states||[], fresh=states.some(s=>s.fresh_observation);
 const rv=c.execution?.market_revalidation||{};
 const rvText={STILL_QUALIFIES:'原纸面方向仍符合条件',NO_LONGER_QUALIFIES:'原纸面方向本轮不再符合条件',REVALIDATION_UNAVAILABLE:'原纸面方向本轮无法复核',EVENT_STARTED:'比赛已开始，进入结算跟踪'}[rv.status]||'本轮复核状态未提供';
 const drift=rv.market_difference,oldSelection=rv.original_selection||{},currentSelection=rv.current_selected||{};
 const movement={FAVORABLE:'对原方向更有利',ADVERSE:'对原方向不利',UNCHANGED:'无变化',UNKNOWN:'方向待核验'};
 const driftText=drift?'首写 '+selectionLabel(c.event,oldSelection)+' → 当前 '+selectionLabel(c.event,currentSelection)+'；盘口变化：'+(movement[drift.line_direction]||'方向待核验')+'；赔率变化：'+(movement[drift.odds_direction]||'方向待核验'):'';
 const failed=rv.status==='NO_LONGER_QUALIFIES',driftClass=(drift&&drift.material&&failed)?'material-drift':(drift&&drift.material&&drift.line_direction==='FAVORABLE')?'good':(drift&&drift.material)?'warn':'sub';
 const driftLead=(drift&&drift.material&&failed)?'真实盘口差异过大，经重新审核后本轮不投注。':(drift&&drift.material&&drift.line_direction==='FAVORABLE')?'当前盘口对原方向更有利，仍须以本轮门槛复核。':(drift&&drift.material)?'盘口变化较大，已按本轮同规则报价重新审核。':'';
 panel.innerHTML='<h3>本轮实际盘口与纸面复核</h3><p><strong>复核结论：</strong>'+esc(rvText)+'</p>'+(drift?'<p class="'+driftClass+'">'+esc(driftLead+driftText)+'</p>':'')+'<p class="sub">仅比较原纸面单的同公司、同市场、同方向、同加时规则。'+esc(rv.display||'')+' ｜ 本轮截止：'+esc(c.asof)+' ｜ '+(fresh?'存在通过时效检查的报价':'暂无通过时效检查的报价，不使用首写盘口代替')+'</p>'+(rv.current_selected?'<p><strong>原方向本轮报价：</strong>'+selectionLabel(c.event,rv.current_selected)+'</p>':'')+(qs.length?'<div class="tablewrap"><table><thead><tr><th>公司</th><th>当前盘口</th><th>双方赔率</th><th>主/替代盘</th><th>源报价时间</th><th>本轮接收时间</th></tr></thead><tbody>'+qs.map(q=>'<tr><td>'+esc(q.bookmaker||q.bookmaker_id)+'</td><td>'+quoteLabel(c.event,q)+'</td><td>'+priceLabel(q)+'</td><td>'+esc(q.main_or_alt)+'</td><td>'+esc(q.source_quote_at)+'</td><td>'+esc(q.received_at)+'</td></tr>').join('')+'</tbody></table></div>':'<p>本轮未获取同场盘口；首写纸面单继续保留跟踪。</p>');
 card.insertBefore(panel,grid);
 });};
function renderCoverage(c){const box=document.querySelector('#coverage');if(!box)return;if(!c){box.innerHTML='<strong>全球赛事覆盖</strong><p class="sub">本轮未生成全球发现漏斗。</p>';return;}const o=c.overall||{};const labels=[['发现赛事','discovered'],['找到盘口','market_found'],['完成定价','priceable'],['Shadow','shadow'],['Executable','executable']];box.innerHTML='<h2>全球赛事覆盖</h2>'+labels.map(x=>'<span class="metric">'+x[0]+'<b>'+esc(o[x[1]]??0)+'</b></span>').join('')+'<p class="sub">地区：'+Object.entries(c.by_region||{}).map(([k,v])=>esc(k)+' '+esc(v.discovered)+'/'+esc(v.market_found)+'/'+esc(v.priceable)+'/'+esc(v.shadow)+'/'+esc(v.executable)).join(' ｜ ')+'</p><details><summary>未覆盖赛事诊断</summary><pre>'+esc(JSON.stringify(c.uncovered_events||[],null,2))+'</pre></details>';}
const renderWithCurrentMarket=render;
function renderAnalytics(a){const box=document.querySelector('#analytics');if(!box)return;if(!a){box.innerHTML='<strong>信号与执行统计</strong><p class="sub">尚未生成仅基于不可变首写的信号/执行/价格透支审计。</p>';return;}const s=a.spread_signal_layer||{},e=a.spread_execution_layer||{},x=a.price_exhaustion_layer||{},t=a.total_diagnostic_layer||{};box.innerHTML='<h2>首写信号、纸面执行与总分诊断</h2><span class="metric">让分首写方向<b>'+esc(s.signals??0)+'</b></span><span class="metric">让分信号结果<b>'+esc((s.signal_wins??0)+' / '+(s.signal_losses??0)+' / '+(s.signal_pushes??0))+'</b></span><span class="metric">纸面执行<b>'+esc(e.executed??0)+'</b></span><span class="metric">价格透支（已证实）<b>'+esc(x.count??0)+'</b></span><span class="metric">总分已结算诊断<b>'+esc(t.settled_total_observations??0)+'</b></span><p class="sub">信号结果只描述冻结的首写方向，不是策略胜率。纸面盈亏只计触发的纸面条目。价格透支必须有同公司、同市场、同方向、同加时规则的前后复核证据；缺失盘口不会被猜成透支。总分目前仅为实验性诊断，不用于参数、概率、Kelly 或执行门槛。</p>';}
render=function(d){renderWithCurrentMarket(d);renderAnalytics(d.analytics);const records=new Map(((d.analytics||{}).records||[]).map(x=>[x.prediction_id,x]));const failures=new Map((((d.analytics||{}).failure_audit_layer||{}).records||[]).map(x=>[x.prediction_id,x]));const failureSummary=(d.analytics||{}).failure_audit_layer||{};const visible=(d.events||[]).filter(r=>currentFilter!=='PAPER_BETTABLE'||(r.execution&&r.execution.shadow_action==='SHADOW_BET'&&r.execution.triggered===true));const analytics=document.querySelector('#analytics');if(analytics&&failureSummary.count){analytics.insertAdjacentHTML('beforeend','<p class="sub"><strong>结算错因审计：</strong>已追加 '+esc(failureSummary.count)+' 条；'+esc(JSON.stringify(failureSummary.counts||{}))+'。缺少量化证据的失败明确标记为“错因未确认：数据不足”。</p>')}document.querySelectorAll('#rows > .card').forEach((card,i)=>{const row=visible[i],record=records.get(row?.execution?.prediction_id);if(!row?.event)return;const p=row.pricing||{},life=row.execution?.execution_lifecycle||record;const total=(row.current_snapshot?.pricing?.total_diagnostic)||p.total_diagnostic;if(life){const panel=document.createElement('section');panel.className='lifecycle';panel.innerHTML='<h3>信号与纸面执行跟踪</h3><p><strong>首写阶段：</strong>'+esc(life.entry_phase||'历史首写待分类')+' ｜ <strong>阈值来源：</strong>'+esc(life.threshold_source||'INITIAL_PRIOR')+'</p><p class="sub">首写方向和首写价格不可改写。临场只会追加复核记录；若价格移动后不再满足条件，也不会抹去已存在的早盘纸面条目。</p>';card.insertBefore(panel,card.querySelector('.grid'));}if(total){const panel=document.createElement('section');panel.className='lifecycle experimental';const executable=total.execution_eligible?'总分证据齐全，可进入后续纸面比较':'总分证据未齐全，仅观察，不进入纸面执行';panel.innerHTML='<h3>总分证据诊断</h3><p>常规时间：'+esc(total.game_minutes??'未确认')+' 分 ｜ 近期总分均值：'+num(total.recent_total_mean)+' ｜ 胶着局末节样本：'+num(total.close_game_q4_observations)+' ｜ 大分差末节样本：'+num(total.blowout_q4_observations)+'</p><p><strong>'+esc(executable)+'</strong></p><p class="sub">'+esc((total.uncertainty_flags||[]).join('；'))+'。回合数、三分、末节犯规和阵容信息必须来自可核验来源；缺项不会被比分均值替代。</p>';card.appendChild(panel);}const failure=failures.get(row.execution?.prediction_id);if(failure){const panel=document.createElement('section');panel.className='lifecycle experimental';const label=failure.failure_label==='CAUSE_UNKNOWN_INSUFFICIENT_DATA'?'错因未确认：数据不足':failure.failure_label;panel.innerHTML='<h3>结算错因审计</h3><p><strong>'+esc(label)+'</strong></p><p>'+esc(failure.reasoning_chain||'')+'</p><p class="sub">指标：'+esc(failure.hard_evidence?.metric_name)+' = '+esc(failure.hard_evidence?.metric_value)+' ｜ 阈值：'+esc(failure.hard_evidence?.threshold_triggered)+' ｜ 审计：'+(failure.audit_passed?'通过':'未通过')+'</p>';card.appendChild(panel);}});};
function renderPricingFunnelDiagnostic(x){const box=document.querySelector('#pricing-funnel-diagnostic');if(!box)return;if(!x){box.innerHTML='<h2>定价漏斗诊断</h2><p class="sub">本日期没有生成定价漏斗诊断。</p>';return;}const m=x.markets||{},s=x.stage_counts||{},top=x.top_blockers||[];const rows=Object.entries(m).map(([k,v])=>'<tr><td>'+esc(k==='SPREAD'?'让分':'大小分')+'</td><td>'+esc(v.events_total??0)+'</td><td>'+esc(v.market_found??0)+'</td><td>'+esc(v.no_market??0)+'</td><td>'+esc(v.fresh_market??0)+'</td><td>'+esc(v.stale_market??0)+'</td><td>'+esc(v.priceable??0)+'</td><td>'+esc(v.fresh_market_but_not_priceable??0)+'</td></tr>').join('');const blockers=top.length?top.slice(0,8).map(b=>'<li><strong>'+esc(b.reason)+'</strong>：'+esc(b.count)+'，'+esc(b.text)+'（'+esc(b.category)+'）</li>').join(''):'<li>暂无阻塞记录</li>';box.innerHTML='<details open><summary><strong>定价漏斗诊断</strong>　市场记录 '+esc(x.market_records??0)+'　终态核算：'+esc(x.terminal_accounting_status||'未确认')+'　瓶颈：'+esc((x.bottleneck||[])[0]||'未确认')+'</summary><p class="sub">只读诊断：不修改公平盘口、概率、sigma、证据门槛或执行决定。新鲜盘口是进入历史与模型分支的前置条件。</p><div class="tablewrap"><table><thead><tr><th>市场</th><th>赛事总数</th><th>找到盘口</th><th>无盘口</th><th>新鲜盘口</th><th>过期盘口</th><th>可定价</th><th>新鲜但未定价</th></tr></thead><tbody>'+rows+'</tbody></table></div><p><strong>主要瓶颈：</strong>'+esc(JSON.stringify(s))+'</p><p><strong>Top 阻塞原因</strong></p><ul>'+blockers+'</ul><details><summary>查看逐场漏斗终态与历史明细</summary><pre>'+esc(JSON.stringify(x.records||[],null,2))+'</pre></details><details><summary>查看工程分类与修复优先级</summary><p>工程失败：'+esc(x.engineering_failures??0)+'；真实数据缺失：'+esc(x.genuine_data_absence??0)+'；模型限制：'+esc(x.model_limitations??0)+'；主动风控：'+esc(x.intentional_risk_blocks??0)+'</p><pre>'+esc(JSON.stringify(x.repair_priorities||{},null,2))+'</pre></details></details>'}
function renderHistoryReadinessDiagnostic(x){const box=document.querySelector('#history-readiness-diagnostic');if(!box)return;if(!x){box.innerHTML='<h2>历史数据就绪诊断</h2><p class="sub">本日期没有生成球队历史瀑布。</p>';return;}const w=x.waterfall||{};const rows=(x.teams||[]).slice(0,80).map(t=>'<tr><td>'+esc(t.raw_team_name||'未确认')+'</td><td>'+esc(t.league||'')+'</td><td>'+esc(t.raw_games_found??0)+'</td><td>'+esc(t.games_after_league_filter??0)+'</td><td>'+esc(t.games_before_cutoff??0)+'</td><td>'+esc(t.usable_history_games??0)+' / '+esc(t.minimum_required_games??0)+'</td><td>'+esc(t.primary_history_failure||'READY')+'</td></tr>').join('');box.innerHTML='<details><summary><strong>历史数据就绪诊断</strong>　球队 '+esc(x.team_count??0)+'　可用 '+esc(w.usable??0)+'　解析历史 '+esc(x.raw_games_parsed??0)+'</summary><p class="sub">瀑布：原始 '+esc(w.raw_history??0)+' → 别名 '+esc(w.team_alias_matched??0)+' → 联赛 '+esc(w.league_matched??0)+' → 截止前 '+esc(w.pre_cutoff??0)+' → 有效 '+esc(w.valid??0)+' → 去重 '+esc(w.deduplicated??0)+' → 可用 '+esc(w.usable??0)+'。该区域只读，不放宽历史最低场次。</p><div class="tablewrap"><table><thead><tr><th>球队</th><th>联赛</th><th>原始</th><th>联赛过滤后</th><th>截止前</th><th>可用/最低</th><th>首要原因</th></tr></thead><tbody>'+rows+'</tbody></table></div><details><summary>查看逐场球队历史</summary><pre>'+esc(JSON.stringify(x.events||[],null,2))+'</pre></details><p class="sub">来源失败：'+esc(x.source_failed_teams??0)+'；联赛过滤移除：'+esc(x.raw_history_exists_but_removed_by_league_filter??0)+'；日期过滤拒绝：'+esc(x.date_filter_rejected??0)+'；fallback：'+esc(JSON.stringify(x.fallback_audit||{}))+'</p></details>'}
const renderWithCoverage=render;render=function(d){renderWithCoverage(d);renderCoverage(d.coverage);renderPricingFunnelDiagnostic(d.pricing_funnel_diagnostic);renderHistoryReadinessDiagnostic(d.history_readiness_diagnostic||d.pricing_funnel_diagnostic?.history_readiness);};
</script></html>'''
HTML = HTML.replace('篮球量化交易 · 纸面模拟', '篮球量化交易 · 手动实盘候选')
HTML = HTML.replace('真实执行：关闭', '手动实盘：开启（需人工下单）')
HTML = HTML.replace('真实资金执行关闭', '自动下单关闭；符合条件的条目由人工下单')
HTML = HTML.replace('今日纸面可投赛事', '今日手动实盘候选赛事')
HTML = HTML.replace('只看纸面可投', '只看手动实盘候选')
HTML = HTML.replace('纸面可投（', '手动实盘候选（')
HTML = HTML.replace('纸面方向：', '手动实盘方向：')
HTML = HTML.replace('通过纸面执行门槛', '通过手动实盘门槛')
HTML = HTML.replace('真实执行永久关闭', '自动下单永久关闭')
HTML = HTML.replace('真实执行仍关闭', '自动下单仍关闭')
HTML = HTML.replace('真实执行关闭', '自动下单关闭')
HTML = HTML.replace('Qualified Paper', 'Qualified Manual Live')
HTML = HTML.replace('Paper / Learning Funnel', 'Manual Live / Learning Funnel')
HTML += '<!-- 今日纸面可投赛事：兼容旧版筛选字段；当前展示语义为手动实盘候选 -->'

# The cumulative paper ledger is a verified, read-only context layer.  It is
# rendered directly below the decision entry and is deliberately collapsible so
# the current picks remain the first thing visible on a phone-sized screen.
HTML = HTML.replace('<div class="bar paper-focus" id="paper-focus"></div>',
                    '<div class="bar paper-focus" id="paper-focus"></div><div class="bar" id="paper-history"></div>')
HTML = HTML.replace('</html>', r'''
<script>
function _paperLedgerStat(x){if(!x||!x.n)return '无样本';const wr=x.win_rate==null?'—':(Number(x.win_rate)*100).toFixed(1)+'%';const pnl=x.pnl_units==null?'—':Number(x.pnl_units).toFixed(2)+'u';return 'N='+x.n+' ｜ W-L-P '+x.wins+'-'+x.losses+'-'+x.pushes+' ｜ 胜率 '+wr+' ｜ PnL '+pnl;}
function renderPaperLedgerHistory(x){const box=document.querySelector('#paper-history');if(!box)return;const rec=x?.records||{};const rows=Object.values(rec).map(v=>'<tr><td>'+esc(v.team1||'—')+' vs '+esc(v.team2||'—')+'</td><td>'+esc(v.league_family||v.league||'—')+'</td><td>'+esc(_paperLedgerStat(v.league_overall))+'</td><td>'+esc(_paperLedgerStat(v.same_matchup))+'</td><td>'+esc(_paperLedgerStat(v.team1_same_league))+'</td><td>'+esc(_paperLedgerStat(v.team2_same_league))+'</td></tr>').join('');box.innerHTML='<details open><summary><strong>同联赛历史胜率及盈亏（合并季前/常规/季后）</strong>　已结算样本 '+esc(x?.settled_ledger_rows??0)+'</summary><p class="sub">'+esc(x?.display_note||'联赛统计按联赛主名合并各阶段；同市场统计，不混合让分与大小分。')+'</p><div class="tablewrap"><table><thead><tr><th>当前纸面赛事</th><th>联赛主名</th><th>同联赛历史（合并各阶段）</th><th>同对阵历史</th><th>主队同联赛</th><th>客队同联赛</th></tr></thead><tbody>'+(rows||'<tr><td colspan="6">当前没有可展示的纸面赛事历史</td></tr>')+'</tbody></table></div></details>';}
const _renderPaperFocusWithLedger=renderPaperFocus;renderPaperFocus=function(d){_renderPaperFocusWithLedger(d);renderPaperLedgerHistory(d.paper_ledger_history);};
</script></html>''')

# Keep the renderer data-driven: cold-start status is read from the JSON and
# inserted into the existing analytics panel. No client-side pricing is added.
HTML = HTML.replace('<div class="bar" id="funnel"></div>', '<div class="bar" id="funnel"></div><div class="bar" id="cold-start"></div>')
HTML = HTML.replace('const renderWithCoverage=render;render=function(d){renderWithCoverage(d);', "function renderColdStart(x){const box=document.querySelector('#cold-start');if(!box||!x)return;const vals=Object.values(x.leagues||{});const rows=vals.map(v=>'<tr><td>'+esc(v.league_family)+'</td><td>'+esc(v.discovered)+'</td><td>'+esc(v.market_found)+'</td><td>'+esc(v.current_season_history)+'</td><td>'+esc(v.previous_season_history)+'</td><td>'+esc(v.effective_sample_size_min==null?'—':Number(v.effective_sample_size_min).toFixed(2))+'</td><td>'+esc(v.research_priceable)+'</td><td>'+esc(v.cold_start_priceable)+'</td><td>'+esc(v.shadow_eligible)+'</td></tr>').join('');box.innerHTML='<h2>冷启动 / Bootstrap 定价</h2><p class=\"sub\">冷启动仅增加研究覆盖；ESS、阵容连续性和原有证据/Edge门槛未通过时，不进入纸面执行。真实执行永久关闭。</p><div class=\"tablewrap\"><table><thead><tr><th>联赛</th><th>发现</th><th>盘口</th><th>本季历史</th><th>前季历史</th><th>最低ESS</th><th>研究定价</th><th>冷启动定价</th><th>Shadow</th></tr></thead><tbody>'+rows+'</tbody></table></div>';}const renderWithCoverage=render;render=function(d){renderColdStart(d.cold_start_summary);renderWithCoverage(d); ")

# Total-market visibility and filter views are presentation-only.  They are
# applied to the shared template after it is built, leaving pricing and gate
# logic untouched.
HTML = HTML.replace('<div class="bar" id="pricing-funnel-diagnostic"></div>', '<div class="bar" id="pricing-funnel-diagnostic"></div><div class="bar" id="p0-bias-audit"></div><div class="bar" id="league-funnel-diagnostic"></div><div class="bar" id="edge-funnel-diagnostic"></div><div class="bar" id="total-market-pipeline"></div>')
HTML = HTML.replace('function renderHistoryReadinessDiagnostic(x){', r'''function renderEdgeFunnelDiagnostic(x){const box=document.querySelector('#edge-funnel-diagnostic');if(!box)return;if(!x||!x.edge_funnel){box.innerHTML='<h2>Edge 漏斗诊断</h2><p class="sub">本日期没有生成 Edge 漏斗诊断。</p>';return;}const ef=x.edge_funnel||{},ms=ef.markets||{};const val=(v)=>v==null?'—':esc(v);const stageRows=['SPREAD','TOTAL'].map(k=>{const v=ms[k]||{};return '<tr><td><strong>'+esc(k==='SPREAD'?'让分':'大小分')+'</strong></td><td>'+val(v.market_found)+'</td><td>'+val(v.fresh_market)+'</td><td>'+val(v.research_priceable)+'</td><td>'+val(v.market_comparable)+'</td><td>'+val(v.raw_edge_found)+'</td><td>'+val(v.calibrated_edge_found)+'</td><td>'+val(v.evidence_pass)+'</td><td>'+val(v.execution_pass)+'</td><td>'+val(v.shadow_triggered)+'</td></tr>';}).join('');const reasons=Object.entries(ef.primary_final_reasons||{}).sort((a,b)=>b[1]-a[1]).map(([k,v])=>'<tr><td>'+esc(k)+'</td><td>'+esc(v)+'</td><td>'+esc((window.REASON_TEXT&&window.REASON_TEXT[k])||k)+'</td></tr>').join('')||'<tr><td colspan="3">暂无可比较样本</td></tr>';const r=ef.retention||{};const groups=Object.entries(ef.retention_by_group||{}).map(([k,v])=>'<tr><td>'+esc(k)+'</td><td>'+val(v.sample_size)+'</td><td>'+val(v.mean_edge_retention)+'</td><td>'+val(v.median_edge_retention)+'</td><td>'+esc(v.possible_over_shrinkage?'是':'否')+'</td></tr>').join('')||'<tr><td colspan="5">暂无带有明确校准公平线的样本；不会从市场融合值反推校准 Edge。</td></tr>';const details=(x.comparable_edge_rows||[]).map(v=>'<tr><td>'+esc(v.game_id||'')+'</td><td>'+esc(v.league||'')+'</td><td>'+esc(v.market_type==='SPREAD'?'让分':'大小分')+'</td><td>'+val(v.raw_fair_line)+'</td><td>'+val(v.market_line)+'</td><td>'+val(v.raw_edge_points)+'</td><td>'+val(v.calibrated_edge_points)+'</td><td>'+val(v.edge_retention_ratio)+'</td><td>'+esc(v.primary_final_reason||'')+'</td></tr>').join('')||'<tr><td colspan="9">暂无逐场可比较样本</td></tr>';const zero=Number(ef.markets?.SPREAD?.shadow_triggered||0)+Number(ef.markets?.TOTAL?.shadow_triggered||0)===0;box.innerHTML='<details open><summary><strong>Edge 漏斗诊断（只读）</strong>　可比较 '+val(ef.comparable_total)+'　Raw Edge '+val((ms.SPREAD?.raw_edge_found||0)+(ms.TOTAL?.raw_edge_found||0))+'　校准后 Edge '+val((ms.SPREAD?.calibrated_edge_found||0)+(ms.TOTAL?.calibrated_edge_found||0))+'　纸面触发 '+val((ms.SPREAD?.shadow_triggered||0)+(ms.TOTAL?.shadow_triggered||0))+'</summary><p class="sub">该区域只解释真实 pipeline 的损失位置，不修改公平盘口、概率、残差、证据门槛或纸面决定。校准公平线未由生产模型明确输出时保持缺失。</p><div class="tablewrap"><table><thead><tr><th>市场</th><th>有盘口</th><th>新鲜</th><th>独立定价</th><th>同场比较</th><th>Raw Edge</th><th>校准后 Edge</th><th>Evidence</th><th>Execution</th><th>纸面触发</th></tr></thead><tbody>'+stageRows+'</tbody></table></div>'+(zero?'<h3>今日为什么 0 场纸面触发</h3><p>可比较样本：'+val(ef.comparable_total)+'。下面是每个可比较样本的唯一首要终态原因。</p><div class="tablewrap"><table><thead><tr><th>Primary Final Reason</th><th>数量</th><th>说明</th></tr></thead><tbody>'+reasons+'</tbody></table></div>':'')+'<h3>校准收缩诊断</h3><p>样本数 '+val(r.sample_size)+'；Edge retention 均值 '+val(r.mean_edge_retention)+'；中位数 '+val(r.median_edge_retention)+'；可能过度收缩：'+esc(r.possible_over_shrinkage?'是':'否')+'。该结论仅用于审计，不自动调参。</p><div class="tablewrap"><table><thead><tr><th>分组</th><th>样本</th><th>均值</th><th>中位数</th><th>可能过度收缩</th></tr></thead><tbody>'+groups+'</tbody></table></div><details><summary>查看可比较样本 Edge 明细</summary><div class="tablewrap"><table><thead><tr><th>赛事</th><th>联赛</th><th>市场</th><th>Raw公平线</th><th>市场线</th><th>Raw Edge</th><th>校准 Edge</th><th>保留率</th><th>首要原因</th></tr></thead><tbody>'+details+'</tbody></table></div></details></details>';}function renderHistoryReadinessDiagnostic(x){''')
HTML = HTML.replace('renderPricingFunnelDiagnostic(d.pricing_funnel_diagnostic);renderHistoryReadinessDiagnostic', 'renderPricingFunnelDiagnostic(d.pricing_funnel_diagnostic);renderLeagueFunnelDiagnostic(d.pricing_funnel_diagnostic);renderEdgeFunnelDiagnostic(d.pricing_funnel_diagnostic);renderHistoryReadinessDiagnostic')
HTML = HTML.replace('renderLeagueFunnelDiagnostic(d.pricing_funnel_diagnostic);', r'''function renderLeagueFunnelDiagnostic(x){const box=document.querySelector('#league-funnel-diagnostic');if(!box)return;const lf=x&&x.league_decision_funnel;if(!lf){box.innerHTML='<h2>League Decision Funnel</h2><p class="sub">本日期没有生成联赛级决策漏斗。</p>';return;}const names={today:'今日',rolling_3d:'滚动3日',rolling_7d:'滚动7日',all_forward_native:'全部前瞻',last_20_comparable:'最近20个可比',last_50_comparable:'最近50个可比'};const make=(key)=>{const p=(lf.windows||{})[key]||{},rows=Object.entries(p.by_league||{}).map(([n,v])=>{const c=v.counts||{};return '<tr><td>'+esc(n)+'</td><td>'+esc(v.sample_size??0)+'</td><td>'+esc(v.comparable_sample??0)+'</td><td>'+esc(c.market_found??0)+'</td><td>'+esc(c.fresh_market??0)+'</td><td>'+esc(c.research_priceable??0)+'</td><td>'+esc(c.raw_edge_found??0)+'</td><td>'+esc(c.calibrated_edge_found??0)+'</td><td>'+esc(c.evidence_pass??0)+'</td><td>'+esc(c.execution_pass??0)+'</td><td>'+esc(c.shadow_triggered??0)+'</td><td>'+esc(v.main_state||'')+'</td></tr>';}).join('')||'<tr><td colspan="12">暂无数据</td></tr>';return '<h3>'+esc(names[key]||key)+' 联赛决策漏斗</h3><div class="tablewrap"><table><thead><tr><th>联赛</th><th>样本</th><th>可比</th><th>盘口</th><th>新鲜</th><th>可定价</th><th>Raw</th><th>Cal</th><th>Evidence</th><th>Execution</th><th>Shadow</th><th>主状态</th></tr></thead><tbody>'+rows+'</tbody></table></div>';};const options=Object.keys(lf.windows||{}).map(k=>'<option value="'+esc(k)+'">'+esc(names[k]||k)+'</option>').join('');box.innerHTML='<details open><summary><strong>League Decision Funnel（只读）</strong>　不改阈值 / Fair line / Champion / 残差尺度</summary><p class="sub">窗口：<select id="league-funnel-window">'+options+'</select>；未达到诊断最低样本量标记 INSUFFICIENT_SAMPLE。</p><div id="league-funnel-window-body">'+make('today')+'</div></details>';const sel=document.querySelector('#league-funnel-window');if(sel)sel.onchange=()=>{document.querySelector('#league-funnel-window-body').innerHTML=make(sel.value);};}renderLeagueFunnelDiagnostic(d.pricing_funnel_diagnostic);''')
HTML = HTML.replace('function renderHistoryReadinessDiagnostic(x){', r'''function renderEdgeDropoffDiagnostic(x){const box=document.querySelector('#edge-funnel-diagnostic');if(!box||!x||!x.edge_funnel)return;const ms=x.edge_funnel.markets||{};const rows=['SPREAD','TOTAL'].map(k=>{const v=ms[k]||{};const rs=Object.entries(v.priceable_not_comparable_reasons||{}).map(([r,n])=>esc(r)+' '+esc(n)).join('；')||'—';return '<tr><td>'+esc(k==='SPREAD'?'让分':'大小分')+'</td><td>'+esc(v.research_priceable??0)+'</td><td>'+esc(v.market_comparable??0)+'</td><td>'+esc(v.not_comparable??0)+'</td><td>'+rs+'</td></tr>';}).join('');box.insertAdjacentHTML('beforeend','<details><summary><strong>Research Priceable → Market Comparable 逐层去向</strong></summary><p class="sub">这里解释研究定价样本为什么没有进入同场同规则比较；每个 market_type 使用唯一首要原因。</p><div class="tablewrap"><table><thead><tr><th>市场</th><th>独立定价</th><th>可比较</th><th>未比较</th><th>Primary Final Reason</th></tr></thead><tbody>'+rows+'</tbody></table></div></details>');}function renderHistoryReadinessDiagnostic(x){''')
HTML = HTML.replace('renderEdgeFunnelDiagnostic(d.pricing_funnel_diagnostic);renderHistoryReadinessDiagnostic', 'renderEdgeFunnelDiagnostic(d.pricing_funnel_diagnostic);renderEdgeDropoffDiagnostic(d.pricing_funnel_diagnostic);renderHistoryReadinessDiagnostic')
HTML = HTML.replace('const renderWithCoverage=render;render=function(d){renderCoverage(d.coverage);', r'''function renderLeagueFunnelDiagnostic(x){const box=document.querySelector('#league-funnel-diagnostic');if(!box)return;const lf=x&&x.league_decision_funnel;if(!lf){box.innerHTML='<h2>League Decision Funnel</h2><p class="sub">本日期没有生成联赛级决策漏斗。</p>';return;}const names={today:'今日',rolling_3d:'滚动3日',rolling_7d:'滚动7日',all_forward_native:'全部前瞻',last_20_comparable:'最近20个可比',last_50_comparable:'最近50个可比'};const options=Object.keys(lf.windows||{}).map(k=>'<option value="'+esc(k)+'">'+esc(names[k]||k)+'</option>').join('');const renderWindow=(key)=>{const p=(lf.windows||{})[key]||{},rows=Object.entries(p.by_league||{}).map(([name,v])=>{const c=v.counts||{};return '<tr><td>'+esc(name)+'</td><td>'+esc(v.sample_size??0)+'</td><td>'+esc(v.comparable_sample??0)+'</td><td>'+esc(c.market_found??0)+'</td><td>'+esc(c.fresh_market??0)+'</td><td>'+esc(c.research_priceable??0)+'</td><td>'+esc(c.raw_edge_found??0)+'</td><td>'+esc(c.calibrated_edge_found??0)+'</td><td>'+esc(c.evidence_pass??0)+'</td><td>'+esc(c.execution_pass??0)+'</td><td>'+esc(c.shadow_triggered??0)+'</td><td>'+esc(v.main_state||'')+'</td></tr>';}).join('')||'<tr><td colspan="12">暂无该窗口数据</td></tr>';const group=(p.groups||{}),grows=Object.entries(group).map(([name,v])=>{const c=v.counts||{};return '<tr><td>'+esc(name)+'</td><td>'+esc(v.comparable_sample??0)+'</td><td>'+esc(c.raw_edge_found??0)+'</td><td>'+esc(c.calibrated_edge_found??0)+'</td><td>'+esc(c.evidence_pass??0)+'</td><td>'+esc(c.execution_pass??0)+'</td><td>'+esc(c.shadow_triggered??0)+'</td><td>'+esc(v.main_state||'')+'</td></tr>';}).join('');return '<h3>'+esc(names[key]||key)+' 联赛漏斗</h3><div class="tablewrap"><table><thead><tr><th>联赛</th><th>样本</th><th>可比</th><th>盘口</th><th>新鲜</th><th>可定价</th><th>Raw Edge</th><th>Cal Edge</th><th>Evidence</th><th>Execution</th><th>Shadow</th><th>主状态</th></tr></thead><tbody>'+rows+'</tbody></table></div><h3>WNBA vs NON_WNBA</h3><div class="tablewrap"><table><thead><tr><th>组别</th><th>可比</th><th>Raw Edge</th><th>Cal Edge</th><th>Evidence</th><th>Execution</th><th>Shadow</th><th>主状态</th></tr></thead><tbody>'+grows+'</tbody></table></div>';};box.innerHTML='<details open><summary><strong>League Decision Funnel（只读）</strong>　不改阈值 / Fair line / Champion / 残差尺度</summary><p class="sub">窗口：<select id="league-funnel-window">'+options+'</select>；历史窗口只纳入原生前瞻首写样本。未达到诊断最低样本量的联赛标记 INSUFFICIENT_SAMPLE。</p><div id="league-funnel-window-body">'+renderWindow('today')+'</div><h3>抑制归因</h3><pre>'+esc(JSON.stringify((lf.suppression_attribution||{}).overall||{},null,2))+'</pre><h3>NON_WNBA Near Miss Top 10</h3><pre>'+esc(JSON.stringify(lf.non_wnba_near_miss_top10||[],null,2))+'</pre><h3>概率瀑布 / Native-Cold-start-Prior / 市场拉力</h3><p class="sub">概率中间节点未由生产显式输出时保持 null；不会从市场融合值反推。</p><pre>'+esc(JSON.stringify({native_cold_start_prior:lf.native_cold_start_prior,market_pull:lf.market_pull,residual_scale_breakdown:lf.residual_scale_breakdown},null,2))+'</pre></details>';const sel=document.querySelector('#league-funnel-window');if(sel)sel.onchange=()=>{document.querySelector('#league-funnel-window-body').innerHTML=renderWindow(sel.value);};}const renderWithCoverage=render;render=function(d){renderCoverage(d.coverage);''')
HTML = HTML.replace('<option value="PAPER_BETTABLE">纸面可投</option>', '<option value="PAPER_BETTABLE">纸面可投</option><option value="TOTAL_MARKET_FOUND">有总分盘口</option><option value="TOTAL_PRICEABLE">总分可定价</option><option value="TOTAL_EDGE">总分有优势</option>')
old_filter = "currentFilter!=='PAPER_BETTABLE'||(r.execution&&r.execution.shadow_action==='SHADOW_BET'&&r.execution.triggered===true)"
HTML = HTML.replace(old_filter, 'isVisible(r)')
HTML = HTML.replace("function legacyRow(r){", "function isVisible(r){if(currentFilter==='ALL')return true;const qs=r.market?.quotes||[];if(currentFilter==='PAPER_BETTABLE')return !!(r.execution&&r.execution.shadow_action==='SHADOW_BET'&&r.execution.triggered===true);if(currentFilter==='TOTAL_MARKET_FOUND')return qs.some(q=>q.market_type==='TOTAL'&&q.raw_line!=null);if(currentFilter==='TOTAL_PRICEABLE')return r.pricing?.total_raw!=null;if(currentFilter==='TOTAL_EDGE')return r.execution?.market_decisions?.TOTAL?.model_state==='EDGE';return true;}function legacyRow(r){")
start = HTML.index('function comparisonBlock(e,p,a,qs){')
end = HTML.index('const dataRoot', start)
total_comparison = r'''function marketSummary(e,k,qs){const typed=qs.filter(q=>q.market_type===k&&q.raw_line!=null);if(!typed.length)return k==='TOTAL'?'暂无真实总分盘口':'暂无真实让分盘口';return typed.slice(0,8).map(q=>quoteLabel(e,q)+'；双边赔率 '+priceLabel(q)).join(' ｜ ')+(typed.length>8?' ｜ 其余 '+(typed.length-8)+' 条盘口已保留':'');}
function comparisonBlock(e,p,a,qs){let md=a.market_decisions||{},fp=p.titan_foundation_pricing||{},en=fp.ensemble||{};let score=(en.expected_team1_score==null||en.expected_team2_score==null)?'未形成':esc(e.team1_name)+' '+num(en.expected_team1_score)+' - '+num(en.expected_team2_score)+' '+esc(e.team2_name);let factors=(fp.top_factors||[]).slice(0,8).map(x=>esc(x.factor)).join('、')||'未形成';let grade=en.capability_grade||'未评级';let keys=['SPREAD','TOTAL'];let blocks=keys.map(k=>{let d=md[k]||{},s=d.selected,q=s?qs.find(x=>x.quote_id===s.quote_id):null,has=qs.some(x=>x.market_type===k&&x.raw_line!=null);let model=k==='SPREAD'?fair(e,p.mu_raw):'模型总分 '+num(p.total_raw)+'分';let fv=k==='SPREAD'?fp.technical_fair_margin_neutral:fp.technical_fair_total;let foundation=fv==null?'Feature Store理论价：未形成':'能力等级 '+esc(grade)+'；理论比分 '+score+'；预期分差 '+num(en.expected_margin)+'；team1理论让分 '+num(en.fair_handicap_team1)+'；理论总分 '+num(en.fair_total)+'；所选方向相对盘口差 '+num(s?.foundation_edge_points)+'分';let market=marketSummary(e,k,qs);let state=d.triggered?'纸面可投':d.comparison_ready?'已比较，未通过门槛':has?(k==='TOTAL'?'已抓到总分盘口，证据门槛未通过':'已抓到让分盘口，未通过门槛'):(k==='TOTAL'?'暂无总分盘口':'暂无让分盘口');let reason=(d.blockers||[]).join('；')||((d.uncertainty_flags||[]).join('；'));return '<section class="market-decision"><h4>'+ (k==='SPREAD'?'让分判断':'大小分判断') +'：'+state+'</h4><p><strong>独立模型：</strong>'+model+'</p><p><strong>Titan007 Feature Store：</strong>'+foundation+'</p><p class="sub"><strong>主要因子：</strong>'+factors+'；可用历史 '+esc(fp.minimum_games??0)+' 场 / '+esc(fp.minimum_distinct_opponents??0)+' 个对手；市场输入用于理论价：否。</p><p><strong>实际盘口：</strong>'+market+'</p><p><strong>模型方向：</strong>'+selectionLabel(e,s)+'</p><p class="sub">盘口链路：'+(has?(k==='TOTAL'?'TOTAL_MARKET_FOUND':'SPREAD_MARKET_FOUND'):'MARKET_NOT_FOUND')+' ｜ 模型状态：'+esc(d.model_state||'未确认')+' ｜ 预期收益：'+num(d.ev*100)+'%'+(reason?' ｜ '+esc(reason):'')+'</p></section>';}).join('');return blocks||'<p class="missing">尚无可进行同场同规则比较的盘口。</p>';}
'''
HTML = HTML[:start] + total_comparison + HTML[end:]
HTML = HTML.replace('const renderWithCoverage=render;render=function(d){renderWithCoverage(d);', r'''function renderTotalMarketPipeline(x){const box=document.querySelector('#total-market-pipeline');if(!box)return;if(!x){box.innerHTML='<h2>总分盘口全链路审计</h2><p class="sub">本日期没有生成总分盘口审计。</p>';return;}const c=x.counts||{},f=x.failure_counts||{};box.innerHTML='<details open><summary><strong>总分盘口全链路审计</strong>　已抓到 '+esc(c.raw_total_market_found??0)+' 场　新鲜 '+esc(c.fresh_total_market_found??0)+' 场　可定价 '+esc(c.total_priceable??0)+' 场　纸面触发 '+esc(c.total_shadow_eligible??0)+' 场</summary><p class="sub">盘口存在不等于可以投注：总分报价先保留，再分别经过新鲜度、独立定价、证据、优势和纸面执行门槛。没有被选为纸面方向的总分报价不会被隐藏。</p><div class="tablewrap"><table><thead><tr><th>阶段</th><th>赛事数</th><th>含义</th></tr></thead><tbody><tr><td>RAW / PARSED</td><td>'+esc(c.raw_total_market_found??0)+' / '+esc(c.parsed_total_market_found??0)+'</td><td>原始响应与解析后的总分盘口</td></tr><tr><td>NORMALIZED / CANONICAL</td><td>'+esc(c.normalized_total_market_found??0)+' / '+esc(c.canonical_total_market_found??0)+'</td><td>标准化并绑定同场赛事</td></tr><tr><td>FRESH / PRICEABLE</td><td>'+esc(c.fresh_total_market_found??0)+' / '+esc(c.total_priceable??0)+'</td><td>当前有效报价与独立模型可定价</td></tr><tr><td>EVIDENCE / EDGE / SHADOW</td><td>'+esc(c.total_evidence_complete??0)+' / '+esc(c.total_edge_found??0)+' / '+esc(c.total_shadow_eligible??0)+'</td><td>证据、优势与纸面执行分层</td></tr></tbody></table></div><p class="sub">首要阻塞：'+esc(JSON.stringify(f))+'</p><details><summary>查看逐场总分审计</summary><pre>'+esc(JSON.stringify(x.records||[],null,2))+'</pre></details></details>';}const renderWithCoverage=render;render=function(d){renderTotalMarketPipeline(d.total_market_pipeline_diagnostic);renderWithCoverage(d);''')

HTML = HTML.replace("const renderWithCoverage=render;render=function(d){renderColdStart(d.cold_start_summary);renderWithCoverage(d);", r'''function renderTotalMarketPipeline(x){const box=document.querySelector('#total-market-pipeline');if(!box)return;if(!x){box.innerHTML='<h2>总分盘口全链路审计</h2><p class="sub">本日期没有生成总分盘口审计。</p>';return;}const c=x.counts||{},f=x.failure_counts||{};box.innerHTML='<details open><summary><strong>总分盘口全链路审计</strong>　已抓到 '+esc(c.raw_total_market_found??0)+' 场　新鲜 '+esc(c.fresh_total_market_found??0)+' 场　可定价 '+esc(c.total_priceable??0)+' 场　纸面触发 '+esc(c.total_shadow_eligible??0)+' 场</summary><p class="sub">盘口存在不等于可以投注：总分报价先保留，再分别经过新鲜度、独立定价、证据、优势和纸面执行门槛。没有被选为纸面方向的总分报价不会被隐藏。</p><p class="sub">RAW/PARSED：'+esc(c.raw_total_market_found??0)+' / '+esc(c.parsed_total_market_found??0)+'；NORMALIZED/CANONICAL：'+esc(c.normalized_total_market_found??0)+' / '+esc(c.canonical_total_market_found??0)+'；FRESH/PRICEABLE：'+esc(c.fresh_total_market_found??0)+' / '+esc(c.total_priceable??0)+'；EVIDENCE/EDGE/SHADOW：'+esc(c.total_evidence_complete??0)+' / '+esc(c.total_edge_found??0)+' / '+esc(c.total_shadow_eligible??0)+'</p><details><summary>查看逐场总分审计</summary><pre>'+esc(JSON.stringify(x.records||[],null,2))+'</pre></details><p class="sub">首要阻塞：'+esc(JSON.stringify(f))+'</p></details>';}const renderWithCoverage=render;render=function(d){renderTotalMarketPipeline(d.total_market_pipeline_diagnostic);renderWithCoverage(d);''')

# Recent score/period evidence is read-only presentation. It is deliberately
# appended after the decision card so it cannot create a client-side signal.
HTML = HTML.replace('</script></html>', r'''
const _renderWithScoreContext=render;render=function(d){_renderWithScoreContext(d);const visible=(d.events||[]).filter(r=>typeof isVisible==='function'?isVisible(r):true);document.querySelectorAll('#rows > .card').forEach((card,i)=>{const row=visible[i],t=row?.pricing?.total_diagnostic?.recent_score_context;if(!t)return;const teams=Object.values(t.team_context||{}).map(v=>{const w5=v.windows?.last_5||{},w10=v.windows?.last_10||{},q=w5.period_total_points||{};return '<tr><td>'+esc(v.team_name||'球队')+'</td><td>'+esc(w5.games??0)+' / '+esc(w10.games??0)+'</td><td>'+num(w5.total_points?.mean)+' / '+num(w10.total_points?.mean)+'</td><td>'+['Q1','Q2','Q3','Q4'].map(k=>num(q[k]?.mean)).join(' / ')+'</td><td>'+num(w5.score_volatility?.total_stdev)+'</td><td>'+esc(w5.games_in_14_days??0)+'</td></tr>';}).join('');const panel=document.createElement('section');panel.className='lifecycle experimental';panel.innerHTML='<h3>近况、分节与赛程波动（总分证据）</h3><p class="sub">仅使用截止时间前已确认的最近5/10场终场比分和分节比分；胶着局阈值为赛前Q4分差≤8分，大分差阈值为≥15分。回合数、三分率、犯规率、伤停和旅行不从比分倒推。</p><div class="tablewrap"><table><thead><tr><th>球队</th><th>近5/近10场</th><th>总分均值</th><th>Q1/Q2/Q3/Q4总分</th><th>近5总分波动</th><th>14日场次</th></tr></thead><tbody>'+teams+'</tbody></table></div><p class="sub">证据状态：'+esc(t.status||'未确认')+'；来源：'+esc(t.method||'未确认')+'；'+esc(t.schedule_context||'')+'</p>';card.appendChild(panel);});};
</script></html>''')

HTML = HTML.replace('</script></html>', r'''
function renderP0BiasAudit(x){const box=document.querySelector('#p0-bias-audit');if(!box)return;if(!x){box.innerHTML='<h2>P0 结构审计</h2><p class="sub">本日期没有生成 P0 结构审计。</p>';return;}const d=x.direction_bias||{},w=d.windows||{},m=x.margin_calibration||{},g=m.groups||{},p=x.probability_consistency||{},c=x.pnl_concentration||{};const row=k=>{const v=w[k]||{};return '<tr><td>'+esc(k)+'</td><td>'+esc(v.n??0)+'</td><td>'+esc(v.favorite_count??0)+'</td><td>'+esc(v.underdog_count??0)+'</td><td>'+esc(v.underdog_share==null?'—':(Number(v.underdog_share)*100).toFixed(1)+'%')+'</td><td>'+esc((v.alerts||[]).join('、')||'—')+'</td></tr>';};const reg=k=>{const v=g[k]||{};return '<tr><td>'+esc(k)+'</td><td>'+esc(v.n??0)+'</td><td>'+esc(v.intercept==null?'—':Number(v.intercept).toFixed(2))+'</td><td>'+esc(v.slope==null?'—':Number(v.slope).toFixed(3))+'</td><td>'+esc(v.r2==null?'—':Number(v.r2).toFixed(3))+'</td><td>'+esc(v.mae==null?'—':Number(v.mae).toFixed(2))+'</td><td>'+esc(v.mean_bias==null?'—':Number(v.mean_bias).toFixed(2))+'</td></tr>';};box.innerHTML='<details open><summary><strong>P0 结构审计（只读）</strong>　WNBA Spread '+esc(d.wnba?.n??0)+' 场　方向偏置：'+esc((d.wnba?.alerts||[]).join('、')||'未触发')+'</summary><p class="sub">不强制 Favorite/Underdog 平衡，不改历史预测、Fair Spread、阈值、Residual Scale 或 Champion；校准层未实现的字段保持 null。</p><h3>方向偏置</h3><div class="tablewrap"><table><thead><tr><th>窗口</th><th>N</th><th>Favorite</th><th>Underdog</th><th>Underdog Share</th><th>警报</th></tr></thead><tbody>'+row('last_10')+row('last_20')+row('last_50')+row('rolling_7d')+row('all_forward_native')+'</tbody></table></div><h3>Margin Compression</h3><p>状态：'+esc(m.center_bias_status||'未确认')+'；OOS/Walk-forward：'+esc(m.oos_walk_forward_status||'未确认')+'</p><div class="tablewrap"><table><thead><tr><th>分组</th><th>N</th><th>Intercept</th><th>Slope</th><th>R²</th><th>MAE</th><th>Mean Bias</th></tr></thead><tbody>'+reg('WNBA')+reg('NBA')+reg('TIER_1')+reg('NORMAL_SPREAD')+reg('DEEP_SPREAD')+'</tbody></table></div><p>概率一致性：'+esc(p.status||'未确认')+'（检查 '+esc(p.checked??0)+'，失败 '+esc(p.failed??0)+'）；PnL集中度：'+esc(c.flag||'未触发')+'；总PnL '+esc(c.total_pnl??'—')+'，Top3贡献 '+esc(c.top_3_contribution==null?'—':(Number(c.top_3_contribution)*100).toFixed(1)+'%')+'</p><details><summary>查看深盘分桶 / Market Freshness / 诊断详情</summary><pre>'+esc(JSON.stringify({deep_spread_audit:x.deep_spread_audit,market_freshness:x.market_freshness,ridge_audit:x.ridge_audit,challengers:x.challengers},null,2))+'</pre></details></details>';}const _renderWithP0=render;render=function(d){_renderWithP0(d);renderP0BiasAudit(d.p0_bias_audit);};
</script></html>''')
HTML = HTML.replace('total_diagnostic?.recent_score_context;if(!t)', 'total_diagnostic?.recent_score_context||row?.pricing?.recent_score_context;if(!t)')

# Four-layer learning is rendered in its own panel and never replaces the
# existing Qualified Paper analytics panel.
HTML = HTML.replace('<div class="bar" id="analytics"></div>', '<div class="bar" id="analytics"></div><div class="bar" id="shadow-learning"></div>')
HTML = HTML.replace('<div class="bar" id="analytics"></div>', '<div class="bar" id="analytics"></div><div class="bar" id="probability-health"></div>')
HTML = HTML.replace('</script></html>', r'''
function renderProbabilityHealth(d){const box=document.querySelector('#probability-health');if(!box)return;const a=d&&d.analytics&&d.analytics.probability_ev_empirical_validation;if(!a){box.innerHTML='<h2>Probability Health / EV</h2><p class="sub">暂无独立概率与经验收益审计。</p>';return;}const f=v=>v==null?'—':(typeof v==='number'?Number(v).toFixed(3):String(v));const rows=Object.values(a.record_annotations||{}).map((v,i)=>{const e=v.empirical_expected_return||{};return '<tr><td>'+esc(i+1)+'</td><td>'+esc(v.home_court_status||'')+'</td><td>'+esc(v.probability_source||'')+'</td><td>'+f(v.p_win)+' / '+f(v.p_push)+' / '+f(v.p_loss)+'</td><td>'+f(v.model_implied_ev)+'</td><td>'+esc(e.status||'MODEL_ONLY')+' / N='+esc(e.sample_N??0)+'</td><td>'+f(e.mean_return)+'</td><td>'+f(v.selected_side_line_edge_points)+'</td><td>'+esc(v.residual_source||'')+' / N='+esc(v.residual_N??0)+' / df='+esc(v.df??'—')+' / scale='+f(v.scale)+'</td></tr>';}).join('')||'<tr><td colspan="9">当前没有可展示的首写信号</td></tr>';const cal=a.probability_calibration||{};box.innerHTML='<details open><summary><strong>Probability Health / Model vs Empirical（只读）</strong>　样本 '+esc(a.sample_N??0)+'　治理 '+esc(a.governance||'MODEL_ONLY')+'</summary><p class="sub">模型隐含 EV 是入场时按模型概率与赔率计算的理论值；经验实现收益只来自同市场、同前瞻/OOS范围的已结算样本。N&lt;20 不输出经验收益点估计，不根据近期连续红黑调参。主模型当前固定标记：'+esc((Object.values(a.record_annotations||{})[0]||{}).home_court_status||'HOME_COURT_NOT_MODELLED')+'。</p><div class="tablewrap"><table><thead><tr><th>序号</th><th>主场层</th><th>概率来源</th><th>W/P/L 概率</th><th>Model EV</th><th>Empirical</th><th>经验收益</th><th>所选边际</th><th>Residual source/N/df/scale</th></tr></thead><tbody>'+rows+'</tbody></table></div><p class="sub">Spread calibration：'+esc(JSON.stringify(cal.SPREAD||{}))+'；Total calibration：'+esc(JSON.stringify(cal.TOTAL||{}))+'。Fair Center uncertainty 与比赛结果 residual 分开统计。</p></details>';}
const _renderWithProbabilityHealth=render;render=function(d){_renderWithProbabilityHealth(d);renderProbabilityHealth(d);};
</script></html>''')
HTML = HTML.replace('</script></html>', r'''
function renderShadowLearning(d){const box=document.querySelector('#shadow-learning');if(!box)return;const f=d.daily_paper_funnel||{},a=d.shadow_learning||{},q=a.QUALIFIED_SHADOW||{},p=a.PROVISIONAL_SHADOW||{},r=a.RESEARCH_SIGNAL||{},iso=a.ledger_isolation||{};const metric=(name,x)=>'<span class="metric">'+name+'<b>'+esc(x??0)+'</b></span>';box.innerHTML='<h2>四层 Paper / Learning Funnel</h2>'+metric('Comparable',f.comparable)+metric('Edge',f.edge)+metric('Qualified',f.qualified_shadow)+metric('Provisional',f.provisional_shadow)+metric('Research-only Edge',f.research_only_edge)+metric('Lean',f.lean)+metric('No Edge',f.no_edge)+'<p class="sub"><strong>账本隔离：</strong>'+(iso.passed?'通过':'未通过')+'。Provisional PnL/ROI/CLV 不进入正式 Paper 或主策略长期收益；真实执行仍关闭。</p><div class="tablewrap"><table><thead><tr><th>层级</th><th>N</th><th>W-L-P</th><th>PnL</th><th>ROI</th><th>MAE</th><th>RMSE</th><th>Brier</th></tr></thead><tbody>'+[['Qualified',q],['Provisional',p],['Research',r]].map(([n,v])=>'<tr><td>'+n+'</td><td>'+esc(v.N??0)+'</td><td>'+esc((v.W??0)+'-'+(v.L??0)+'-'+(v.P??0))+'</td><td>'+num(v.PnL)+'</td><td>'+num(v.ROI==null?null:v.ROI*100)+(v.ROI==null?'':'%')+'</td><td>'+num(v.MAE)+'</td><td>'+num(v.RMSE)+'</td><td>'+num(v.Brier)+'</td></tr>').join('')+'</tbody></table></div><p class="sub">Provisional 原因：'+esc(JSON.stringify(f.provisional_reason_counts||{}))+'；Tier 3 Edge：'+esc(JSON.stringify(f.tier3_edge||{}))+'</p>';}
const _renderWithShadowLearning=render;render=function(d){_renderWithShadowLearning(d);renderShadowLearning(d);};
</script></html>''')

# Source-agnostic evidence and Titan provisional are visible near the top, but
# remain visually and physically separate from Qualified Paper.
HTML = HTML.replace('<div class="bar" id="analytics"></div>', '<div class="bar" id="analytics"></div><div class="bar" id="unified-evidence"></div>')
HTML = HTML.replace("p=a.PROVISIONAL_SHADOW||{},r=a.RESEARCH_SIGNAL||{}",
                    "p=a.PROVISIONAL_SHADOW||{},tp=a.TITAN_PROVISIONAL_SHADOW||{},r=a.RESEARCH_SIGNAL||{}")
HTML = HTML.replace("[['Qualified',q],['Provisional',p],['Research',r]]",
                    "[['Qualified',q],['Titan Provisional',tp],['Provisional',p],['Research',r]]")
HTML = HTML.replace('<option value="PAPER_BETTABLE">纸面可投</option>', '<option value="PAPER_BETTABLE">纸面可投</option><option value="TITAN_PROVISIONAL">Titan Provisional</option>')
HTML = HTML.replace('<div class="diagnostic-divider"><h2>研究与审计</h2>', '<div class="bar" id="spread-probability"></div><div class="diagnostic-divider"><h2>研究与审计</h2>')
HTML = HTML.replace('</script></html>', r'''
const _paperFocusQualifiedOnly=renderPaperFocus;
renderPaperFocus=function(d){const box=document.querySelector('#paper-focus');if(!box)return;const events=d.events||[],paper=events.filter(r=>r.execution?.triggered===true),titan=events.filter(r=>r.execution?.titan_provisional_status==='TITAN_PROVISIONAL_SHADOW'&&!r.execution?.triggered),f=d.daily_paper_funnel||{};const cards=(rows,cls)=>rows.map(r=>{const e=r.event||{},a=r.execution||{},td=Object.values(a.titan_market_decisions||{}).find(x=>x.status==='TITAN_PROVISIONAL_SHADOW'),continuity=a.titan_provisional_continuity||{},s=cls==='titan'?(td?.selected||continuity.selected):a.selected,note=cls==='titan'&&continuity.status==='HISTORICAL_FIRST_WRITE_RETAINED'?' ｜ 历史首写保留；当前源复核：'+(continuity.current_revalidation_status||'UNAVAILABLE')+'；非新推荐':'';return '<div class="paper-pick" style="border-color:'+(cls==='titan'?'#e0b36b':'#bfe4d1')+'"><strong>'+esc(e.team1_name)+' vs '+esc(e.team2_name)+'</strong><span class="pick" style="color:'+(cls==='titan'?'#9b5900':'#136546')+'">'+selectionLabel(e,s)+'</span><span class="sub">'+esc(e.league)+' ｜ '+esc(e.tip_time_bj)+esc(note)+'</span></div>';}).join('');box.innerHTML='<h2>今日决策入口</h2><span class="metric">Qualified Paper<b>'+esc(paper.length)+'</b></span><span class="metric">Titan Provisional<b>'+esc(titan.length)+'</b></span><span class="metric">Research Edge<b>'+esc(f.research_only_edge??0)+'</b></span><span class="metric">Lean<b>'+esc(f.lean??0)+'</b></span><div class="paper-actions"><button class="'+(currentFilter==='PAPER_BETTABLE'?'active':'')+'" onclick="setDashboardFilter(\'PAPER_BETTABLE\')">Qualified（'+esc(paper.length)+'）</button><button class="'+(currentFilter==='TITAN_PROVISIONAL'?'active':'')+'" onclick="setDashboardFilter(\'TITAN_PROVISIONAL\')">Titan Provisional（'+esc(titan.length)+'）</button><button class="'+(currentFilter==='ALL'?'active':'')+'" onclick="setDashboardFilter(\'ALL\')">全部赛事（'+esc(events.length)+'）</button></div><h3>Qualified Paper</h3>'+(cards(paper,'qualified')||'<p class="missing">当前没有通过正式 Champion 门槛的纸面条目。</p>')+'<h3 style="color:#9b5900">Titan Provisional（独立账本）</h3>'+(cards(titan,'titan')||'<p class="missing">当前没有满足完整证据、真实市场与优势门槛的 Titan Provisional。</p>')+'<p class="sub">Titan Provisional 不计入正式 Paper PnL/ROI/CLV；其唯一模型治理阻塞为尚未通过 Champion 的严格前瞻 OOS 晋升。真实执行关闭。</p>';};
isVisible=function(r){if(currentFilter==='ALL')return true;if(currentFilter==='PAPER_BETTABLE')return !!r.execution?.triggered;if(currentFilter==='TITAN_PROVISIONAL')return r.execution?.titan_provisional_status==='TITAN_PROVISIONAL_SHADOW'&&!r.execution?.triggered;const qs=r.market?.quotes||[];if(currentFilter==='TOTAL_MARKET_FOUND')return qs.some(q=>q.market_type==='TOTAL'&&q.raw_line!=null);if(currentFilter==='TOTAL_PRICEABLE')return r.pricing?.total_raw!=null;if(currentFilter==='TOTAL_EDGE')return r.execution?.market_decisions?.TOTAL?.model_state==='EDGE';return true;};
function renderUnifiedEvidence(x){const box=document.querySelector('#unified-evidence');if(!box)return;if(!x){box.innerHTML='<h2>Unified Evidence</h2><p class="sub">本轮未生成统一证据审计。</p>';return;}const c=x.counts||{},f=x.fixed_vs_previous_dashboard||{};box.innerHTML='<details open><summary><strong>Source-Agnostic Evidence / Titan Ladder</strong>　理论价 '+esc(c.titan_theoretical_price??0)+'　History Gate '+esc(c.titan_history_gate_pass??0)+'　Unified Ready '+esc(c.unified_evidence_ready??0)+'　Champion Priceable '+esc(c.champion_priceable??0)+'</summary><p><span class="metric">Qualified<b>'+esc(c.qualified??0)+'</b></span><span class="metric">Titan Provisional<b>'+esc(c.titan_provisional??0)+'</b></span><span class="metric">Research-only<b>'+esc(c.research_only??0)+'</b></span><span class="metric">No Market<b>'+esc(c.no_market??0)+'</b></span><span class="metric">No Edge<b>'+esc(c.no_edge??0)+'</b></span></p><p class="sub">相对页面旧快照修复：History '+esc(f.history??0)+'；Team History Feed '+esc(f.team_history_feed??0)+'；Possessions '+esc(f.possessions??0)+'；Game Rule '+esc(f.game_rule??0)+'；Roster Stability '+esc(f.roster_stability??0)+'。Source Bridge Failure：'+esc(c.source_bridge_failure??0)+'。</p><details><summary>查看逐场统一证据与未升级原因</summary><pre>'+esc(JSON.stringify(x.records||[],null,2))+'</pre></details></details>';}
const _renderWithUnifiedEvidence=render;render=function(d){_renderWithUnifiedEvidence(d);renderUnifiedEvidence(d.unified_evidence_audit);const visible=(d.events||[]).filter(r=>isVisible(r));document.querySelectorAll('#rows > .card').forEach((card,i)=>{const row=visible[i],a=row?.execution||{},b=a.pregame_evidence_bundle||row?.pricing?.pregame_evidence_bundle,t=Object.values(a.titan_market_decisions||{}).sort((x,y)=>(y.status==='TITAN_PROVISIONAL_SHADOW')-(x.status==='TITAN_PROVISIONAL_SHADOW'))[0];if(!row?.event||!b)return;const h=b.HISTORY||{},dq=b.DATA_QUALITY||{},get=x=>x?.value;const panel=document.createElement('section');panel.className='lifecycle experimental';panel.innerHTML='<h3>Unified Evidence / 为什么没有升级</h3><p>同赛事历史：'+esc(get(h.home_same_comp_games))+' / '+esc(get(h.away_same_comp_games))+'（门槛 8/8）｜ 对手：'+esc(get(h.home_unique_opponents))+' / '+esc(get(h.away_unique_opponents))+'（门槛 3/3）｜ Pace '+esc(get(b.PACE?.pace_level))+' ｜ Rules '+(dq.rule_ready?'PASS':'FAIL')+'</p><p><strong>Titan状态：</strong>'+esc(a.titan_provisional_status||'UNAVAILABLE')+(t?.selected?' ｜ '+selectionLabel(row.event,t.selected):'')+'</p><p class="sub">剩余 Hard Block：'+esc((t?.hard_blockers||[]).join('；')||'无')+' ｜ Soft / 治理：'+esc((t?.soft_missing||[]).join('；')||'无')+'。每个字段的 source/timestamp/raw_ref/quality 保存在输入证据审计中。</p><details><summary>字段级 Evidence Provenance 与 Challenger Fair Lines</summary><pre>'+esc(JSON.stringify({pregame_evidence_bundle:b,challenger_prices:row.pricing?.challenger_prices,titan_market_decisions:a.titan_market_decisions},null,2))+'</pre></details>';card.appendChild(panel);});};
</script></html>''')

# Fair-center uncertainty, game-outcome residuals, and market comparison are
# read-only diagnostics. They are deliberately rendered outside the Paper and
# Provisional ledgers, and never create a client-side bet or alter a gate.
HTML = HTML.replace('</script></html>', r'''
function renderSpreadProbabilityAudit(a){const box=document.querySelector('#spread-probability');if(!box)return;if(!a){box.innerHTML='<h2>Spread Probability / EV</h2><p class="sub">本轮没有生成独立的让分概率审计。</p>';return;}const f=v=>v==null?'—':(typeof v==='number'?Number(v).toFixed(3):String(v));const cards=a.decision_cards||[];const rows=cards.map(c=>'<tr><td>'+esc(c.league||'—')+'</td><td>'+esc(c.team1||'—')+' vs '+esc(c.team2||'—')+'</td><td>'+esc(f(c.raw_fair_spread))+'</td><td>'+esc(f(c.calibrated_fair_spread))+'</td><td>'+esc(f(c.fair_center_standard_error))+'</td><td>'+esc(JSON.stringify(c.fair_center_interval_80||null))+'</td><td>'+esc(JSON.stringify(c.game_outcome_prediction_interval_80||null))+'</td><td>'+esc(f(c.market_threshold))+'</td><td>'+esc((c.wins??'—')+'/'+(c.pushes??'—')+'/'+(c.losses??'—'))+'</td><td>'+esc(f(c.probability_edge))+'</td><td>'+esc(f(c.ev))+'</td><td>'+esc(c.residual_source||'—')+' / '+esc(c.residual_oos_N??0)+'</td></tr>').join('');box.innerHTML='<details open><summary><strong>Spread Probability / EV（只读）</strong>　Cards '+esc(cards.length)+'　OOS residual N '+esc(a.residual_records_N??0)+'</summary><p class="sub">Fair Center 区间描述模型公平价不确定性；Game Outcome 区间描述实际比赛结果残差。市场只在公平价冻结后用于比较，不反向进入公平价。W/P/L、含走盘 break-even、Probability Edge 与 EV 均为诊断字段，不改变正式 Edge/EV 门槛。</p><div class="tablewrap"><table><thead><tr><th>联赛</th><th>比赛</th><th>Raw Fair</th><th>Calibrated</th><th>Center SE</th><th>Center 80%</th><th>Outcome 80%</th><th>Market</th><th>W/P/L</th><th>Prob Edge</th><th>EV</th><th>Residual</th></tr></thead><tbody>'+rows+'</tbody></table></div></details>';}const _renderWithSpreadProbability=render;render=function(d){_renderWithSpreadProbability(d);renderSpreadProbabilityAudit(d.spread_probability_audit);};
</script></html>''')

# Final presentation pass: later diagnostic overlays are appended after the
# legacy template replacements above, so normalize their visible execution
# wording here as well.  Keep one compatibility marker for older consumers.
HTML = HTML.replace('Qualified Paper', 'Qualified Manual Live')
HTML = HTML.replace('纸面可投赛事', '手动实盘候选赛事')
HTML = HTML.replace('纸面可投', '手动实盘候选')
HTML = HTML.replace('纸面执行', '手动实盘候选')
HTML = HTML.replace('纸面方向：', '手动实盘方向：')
HTML = HTML.replace('真实执行永久关闭', '自动下单永久关闭')
HTML = HTML.replace('真实执行仍关闭', '自动下单仍关闭')
HTML = HTML.replace('真实执行关闭', '自动下单关闭')
HTML = HTML.replace('<div class="bar" id="unified-evidence"></div>', '<div class="bar" id="formal-manual-ledger"></div><div class="bar" id="unified-evidence"></div>')
HTML = HTML.replace('</script></html>', r'''
function renderFormalManualLedger(x){const box=document.querySelector('#formal-manual-ledger');if(!box)return;if(!x){box.innerHTML='<h2>正式手动实盘总账</h2><p class="sub">尚未生成统一总账。</p>';return;}const s=x.summary||{},layers=x.by_layer||{},records=x.records||[],f=v=>v==null?'—':Number(v).toFixed(2);const row=(name,v)=>'<tr><td>'+esc(name)+'</td><td>'+esc(v.records??0)+'</td><td>'+esc((v.wins??0)+'-'+(v.losses??0)+'-'+(v.pushes??0))+'</td><td>'+esc(v.pending??0)+'</td><td>'+f(v.formal_manual_pnl_units)+'</td><td>'+f(v.formal_manual_roi==null?null:v.formal_manual_roi*100)+(v.formal_manual_roi==null?'':'%')+'</td></tr>';const direction=r=>r.market_type==='SPREAD'?((r.selection==='TEAM1'?r.team1_name:r.team2_name)+' '+((Number(r.line)>=0?'+':'')+r.line)):(r.selection==='OVER'?'大 ':'小 ')+r.line;const firstWrites=records.length?'<h3>本日已冻结首写（后续更新不删除）</h3><div class="tablewrap"><table><thead><tr><th>联赛</th><th>比赛</th><th>市场</th><th>方向</th><th>赔率</th><th>来源层</th><th>结果</th></tr></thead><tbody>'+records.map(r=>'<tr><td>'+esc(r.league||r.competition_key||'—')+'</td><td>'+esc((r.team1_name||'—')+' vs '+(r.team2_name||'—'))+'</td><td>'+esc(r.market_type==='SPREAD'?'让分':'大小分')+'</td><td>'+esc(direction(r))+'</td><td>'+esc(r.decimal_odds??'—')+'</td><td>'+esc(r.source_layer||'—')+'</td><td>'+esc(r.outcome||'PENDING')+'</td></tr>').join('')+'</tbody></table></div>':'<p class="sub">本日尚无已冻结的正式手动首写。</p>';box.innerHTML='<details open><summary><strong>正式手动实盘总账</strong>　记录 '+esc(s.records??0)+'　已结算 '+esc(s.settled??0)+'　PnL '+f(s.formal_manual_pnl_units)+' 单位</summary><p class="sub">已按用户授权纳入 Qualified、Provisional、Titan Provisional；同场同市场按首写去重。'+esc(x.actual_fill_note||'')+'</p><div class="tablewrap"><table><thead><tr><th>来源层</th><th>记录</th><th>W-L-P</th><th>待结算</th><th>PnL（单位）</th><th>ROI</th></tr></thead><tbody>'+row('合计',s)+Object.entries(layers).map(([k,v])=>row(k,v)).join('')+'</tbody></table></div>'+firstWrites+'<p class="sub">来源账本保持不可变：'+(x.source_ledgers_immutable?'是':'否')+'。研究层不计入正式总账。</p></details>';}
const _renderWithFormalManualLedger=render;render=function(d){_renderWithFormalManualLedger(d);renderFormalManualLedger(d.formal_manual_ledger);};
</script></html>''')

# Final market-level presentation pass.  The original page intentionally keeps
# one event card, but a card may contain two independent records.  This pass
# replaces the legacy single-selected view without touching the immutable
# first-write JSON.
HTML = HTML.replace('</html>', r'''
<script>
function isolatedMarkets(a){a=a||{};let md=a.market_decisions||{};if(Object.keys(md).length)return md;let s=a.selected;if(s&&s.market_type)return {[s.market_type]:Object.assign({},a,{market_type:s.market_type,selected:s})};return {};}
function marketRows(r){let frozen=r?.execution||{}, current=r?.display_execution||r?.current_snapshot?.execution||{};let fm=isolatedMarkets(frozen),cm=isolatedMarkets(current),out=[];['SPREAD','TOTAL'].forEach(k=>{let f=fm[k]||{},c=cm[k]||{},d=(f.selected?f:(c.selected?c:f));if(!d.selected&&!f.selected&&!c.selected)return;out.push({market_type:k,decision:d,frozen:f,current:c,qualified:!!(f.triggered||c.triggered)});});return out;}
function marketTitle(k){return k==='SPREAD'?'让分':'大小分';}
function canonicalSelection(e,s,quotes){if(!s)return s;let out=Object.assign({},s);if(out.line!=null)return out;let q=s.quote_id?(quotes||[]).find(x=>x.quote_id===s.quote_id):null;if(out.market_type==='SPREAD'&&q&&q.line_team1!=null){out.line=out.selection==='TEAM1'?q.line_team1:-q.line_team1;out.direction_source='EXACT_QUOTE_ID';}return out;}
function marketDirectionHtml(e,row,quotes){let d=row.decision||{},s=canonicalSelection(e,d.selected,quotes)||{},q=s.quote_id?(quotes||[]).find(x=>x.quote_id===s.quote_id):null;let status=row.qualified?(row.frozen.triggered?'首写已入账':'本轮手动实盘候选'):(d.comparison_ready?'已比较，未通过门槛':'观察');let source=q?'<span class="sub">同一报价基准：'+quoteLabel(e,q)+'</span>':'<span class="sub">冻结盘口；本轮报价不替代首写合同</span>';return '<section class="market-summary-item"><strong>'+marketTitle(row.market_type)+'｜'+esc(status)+'</strong><span class="pick">'+selectionLabel(e,s)+'</span>'+source+'<span class="sub">'+(d.model_state?'模型状态：'+esc(d.model_state):'')+(d.ev!=null?' ｜ EV '+num(d.ev*100)+'%':'')+'</span></section>';}
function marketSummaryHtml(r){let e=r?.display_event||r?.event||{},m=r?.display_market||r?.current_snapshot?.market||r?.market||{};let rows=marketRows(r);return '<div class="market-summary-current">'+(rows.length?rows.map(x=>marketDirectionHtml(x.decision===x.frozen?(r.event||e):e,x,m.quotes||[])).join(''):'<span class="sub">尚无独立让分/大小分方向</span>')+'</div>';}
function paperMarketRows(events){let out=[];(events||[]).forEach(r=>marketRows(r).forEach(x=>{if(x.qualified)out.push({row:r,market:x});}));return out;}
const _renderMarketAccurate=render;
render=function(d){
  _renderMarketAccurate(d);
  const visible=(d.events||[]).filter(r=>typeof isVisible==='function'?isVisible(r):true);
  document.querySelectorAll('#rows > .card').forEach((card,i)=>{
    const row=visible[i]; if(!row?.event)return;
    const old=Array.from(card.querySelectorAll(':scope > p')).find(p=>(p.textContent||'').includes('方向'));
    const summary=marketSummaryHtml(row);
    if(old)old.outerHTML=summary; else if(!card.querySelector('.market-summary-current'))card.insertAdjacentHTML('afterbegin',summary);
    const a=row.display_execution||row.current_snapshot?.execution||row.execution||{};
    const p=row.display_pricing||row.current_snapshot?.pricing||row.pricing||{};
    const m=row.display_market||row.current_snapshot?.market||row.market||{};
    const grid=card.querySelector('.grid'),right=grid?.children?.[1];
    const started=(a.market_revalidation||{}).status==='EVENT_STARTED'||(a.blockers||[]).some(x=>x==='EVENT_ALREADY_STARTED'||x==='TARGET_ALREADY_STARTED');
    if(right)right.innerHTML='<h3>独立模型 vs 实际盘口</h3>'+(started?'<p class="missing">比赛已开始：以下为开赛后挂牌观察，不能作为赛前首写或当前可入场盘口。</p>':'')+comparisonBlock(row.display_event||row.event,p,a,m.quotes||[])+'<div class="sub">让分与大小分按市场独立核算；同场同时通过时两条均保留。自动下单关闭。</div>';
  });
};
renderPaperFocus=function(d){const box=document.querySelector('#paper-focus');if(!box)return;const events=d.events||[],qualified=paperMarketRows(events),titan=[];events.forEach(r=>{const e=r.event||{},a=r.execution||{},tm=a.titan_market_decisions||{};Object.entries(tm).forEach(([k,v])=>{if(v?.status==='TITAN_PROVISIONAL_SHADOW'&&!a.market_decisions?.[k]?.triggered)titan.push({row:r,market:{market_type:k,decision:v,frozen:{},current:{},qualified:false}});});});const f=d.daily_paper_funnel||{},cards=(items,cls)=>items.map(x=>{const r=x.row,e=r.event||{},m=x.market,d=m.decision||{},s=canonicalSelection(e,d.selected,(r.display_market||r.current_snapshot?.market||r.market||{}).quotes||[]),note=cls==='titan'?' ｜ Titan Provisional 独立账本':' ｜ 市场级记录';return '<div class="paper-pick" style="border-color:'+(cls==='titan'?'#e0b36b':'#bfe4d1')+'"><strong>'+esc(e.team1_name)+' vs '+esc(e.team2_name)+'</strong><span class="pick" style="color:'+(cls==='titan'?'#9b5900':'#136546')+'">'+esc(marketTitle(m.market_type))+'：'+selectionLabel(e,s)+'</span><span class="sub">'+esc(e.league||e.competition_key||'')+' ｜ '+esc(e.tip_time_bj||'')+note+'</span></div>';}).join('');box.innerHTML='<h2>今日决策入口</h2><span class="metric">Qualified Manual Live<b>'+esc(qualified.length)+'</b></span><span class="metric">Titan Provisional<b>'+esc(titan.length)+'</b></span><span class="metric">Research Edge<b>'+esc(f.research_only_edge??0)+'</b></span><span class="metric">Lean<b>'+esc(f.lean??0)+'</b></span><div class="paper-actions"><button class="'+(currentFilter==='PAPER_BETTABLE'?'active':'')+'" onclick="setDashboardFilter(\'PAPER_BETTABLE\')">Qualified（'+esc(qualified.length)+'）</button><button class="'+(currentFilter==='TITAN_PROVISIONAL'?'active':'')+'" onclick="setDashboardFilter(\'TITAN_PROVISIONAL\')">Titan Provisional（'+esc(titan.length)+'）</button><button class="'+(currentFilter==='ALL'?'active':'')+'" onclick="setDashboardFilter(\'ALL\')">全部赛事（'+esc(events.length)+'）</button></div><h3>Qualified Manual Live</h3>'+(cards(qualified,'qualified')||'<p class="missing">当前没有通过正式 Champion 门槛的市场记录。</p>')+'<h3 style="color:#9b5900">Titan Provisional（独立账本）</h3>'+(cards(titan,'titan')||'<p class="missing">当前没有满足完整证据、真实市场与优势门槛的 Titan Provisional。</p>')+'<p class="sub">同一场比赛的让分与大小分分别记账；真实下单仍由用户手动完成，自动下单关闭。</p>';};
isVisible=function(r){if(currentFilter==='ALL')return true;const qs=(r.display_market||r.current_snapshot?.market||r.market||{}).quotes||[];if(currentFilter==='PAPER_BETTABLE')return marketRows(r).some(x=>x.qualified);if(currentFilter==='TITAN_PROVISIONAL')return Object.values((r.execution||{}).titan_market_decisions||{}).some(x=>x.status==='TITAN_PROVISIONAL_SHADOW');if(currentFilter==='TOTAL_MARKET_FOUND')return qs.some(q=>q.market_type==='TOTAL'&&q.raw_line!=null);if(currentFilter==='TOTAL_PRICEABLE')return r.pricing?.total_raw!=null;if(currentFilter==='TOTAL_EDGE')return r.execution?.market_decisions?.TOTAL?.model_state==='EDGE';return true;};
const _renderPaperFocusWithLedgerFinal=renderPaperFocus;renderPaperFocus=function(d){_renderPaperFocusWithLedgerFinal(d);renderPaperLedgerHistory(d.paper_ledger_history);};if(typeof currentData!=='undefined'&&currentData)renderPaperLedgerHistory(currentData.paper_ledger_history);
</script></html>''')
HTML += '<!-- 今日纸面可投赛事：兼容旧版筛选字段；当前展示语义为手动实盘候选 -->'

def _event_continuity_key(event):
    """Identify the same fixture across provider refreshes.

    Source event IDs are not guaranteed to remain stable when a board moves a
    fixture between a regular-season and phase-specific feed.  The verified
    team pair plus tip time is the continuity identity; it is only used to
    preserve an immutable first-write row, never to fabricate a quote.
    """
    event = event or {}
    # This must use the same reviewed alias registry as source-level
    # continuity.  The old display-only normalizer stripped rankings but left
    # sponsor renames as different teams, so a first-write row could be
    # re-added beside its refreshed CBA/NBA alias.
    names = tuple(sorted(filter(None, (canonical_team_token(event.get('team1_name')),
                                       canonical_team_token(event.get('team2_name'))))))
    ids = tuple(sorted(filter(None, (str(event.get('team1_id') or ''), str(event.get('team2_id') or '')))))
    # Names survive a provider-ID regeneration; IDs are preferred only when
    # names are unavailable.  The tip time remains mandatory in both cases.
    teams = names if len(names) == 2 else ids
    tip = event.get('tip_at') or event.get('tip_time_bj')
    try:
        tip_key = iso(tip).replace(second=0, microsecond=0).isoformat()
    except (TypeError, ValueError):
        tip_key = str(tip or '')[:19]
    return teams, tip_key


def _preserve_first_write_paper_rows(path, rows, asof):
    """Keep triggered forward decisions visible after a later refresh/settlement."""
    old = load(path, {})
    old_rows = old.get('events', [])
    if not old_rows:
        return rows
    current = {r.get('id'): r for r in rows}
    current_by_continuity = {}
    for row in rows:
        key = _event_continuity_key(row.get('event'))
        if key[0] and key[1]:
            current_by_continuity.setdefault(key, row)
    matched_current_ids = set()
    for prior in old_rows:
        decision = prior.get('execution') or {}
        market_triggered = any(
            isinstance(item, dict) and item.get('triggered') is True
            for item in (decision.get('market_decisions') or {}).values())
        if not ((decision.get('triggered') is True or market_triggered) and prior.get('id')):
            continue
        refreshed = current.get(prior['id'])
        match_method = 'EVENT_ID'
        if refreshed is None:
            refreshed = current_by_continuity.get(_event_continuity_key(prior.get('event')))
            match_method = 'TEAM_PAIR_AND_TIP_TIME' if refreshed else 'NONE'
        elif _event_continuity_key(refreshed.get('event')) != _event_continuity_key(prior.get('event')):
            # Never let an accidentally reused source ID overwrite a prior
            # fixture's first-write record.
            refreshed = None
            match_method = 'EVENT_ID_CONTINUITY_CONFLICT'
        if refreshed and refreshed.get('id') != prior.get('id'):
            matched_current_ids.add(refreshed.get('id'))
        kept = dict(prior)
        prior_event = prior.get('event') or {}
        started = bool(prior_event.get('tip_at')) and iso(prior_event['tip_at']) <= iso(asof)
        missing_recheck = ({
            'status': 'EVENT_STARTED', 'checked_at': asof,
            'display': '比赛已开始，停止赛前盘口复核，进入赛果结算跟踪',
            'real_execution_allowed': False,
        } if started else {
            'status': 'REVALIDATION_UNAVAILABLE', 'checked_at': asof,
            'display': '本轮未观察到该未开赛赛事，无法取得同公司、同规则的新鲜报价复核',
            'real_execution_allowed': False,
        })
        # Preserve immutable paper evidence separately from this run's observations.
        kept['current_snapshot'] = {
            'asof': asof,
            'event': refreshed['event'] if refreshed else prior['event'],
            'market': refreshed['market'] if refreshed else {'quotes': [], 'quote_states': []},
            'pricing': refreshed['pricing'] if refreshed else {'pricing_status': 'UNPRICEABLE'},
            'execution': refreshed['execution'] if refreshed else {
                'shadow_action': 'BLOCKED', 'comparison_ready': False, 'triggered': False,
                'market_revalidation': missing_recheck},
            'refresh_status': 'OBSERVED' if refreshed else 'NOT_OBSERVED',
        }
        if refreshed:
            # Settlement/review data may be appended, but never replace the frozen decision.
            for key in ('settlement', 'post_match_review', 'revisions'):
                if key in refreshed:
                    kept[key] = refreshed[key]
            kept['last_refresh_asof'] = asof
        kept['first_write_preserved'] = True
        kept['continuity_match_method'] = match_method
        current[prior['id']] = kept
    return [row for row_id, row in current.items() if row_id not in matched_current_ids]


def _display_fixture_family(event):
    """Return a conservative cross-provider competition family for display dedupe."""
    event = event or {}
    text = ' '.join(str(event.get(key) or '') for key in (
        'league_family', 'competition_key', 'league', 'league_display')).casefold()
    if 'wnba' in text or '美国女子' in text:
        return 'WNBA'
    if 'nba' in text or '美国男子' in text:
        return 'NBA'
    if 'cba' in text or '中国男子' in text:
        return 'CBA'
    return ''.join(ch for ch in text if ch.isalnum() or '\u4e00' <= ch <= '\u9fff')


def _same_display_fixture(left, right, tolerance_minutes=45):
    """Match a duplicated fixture without using a provider event id.

    This is intentionally stricter than a team-only match: both normalized
    team tokens, a compatible competition family, and a bounded tip-time drift
    are required.  It is used only to choose one visible row; the original
    first-write records remain attached as audit references.
    """
    left = left or {}; right = right or {}
    def pair(event):
        values = [canonical_team_token(event.get('team1_name')),
                  canonical_team_token(event.get('team2_name'))]
        return tuple(sorted(value for value in values if value))
    left_pair, right_pair = pair(left), pair(right)
    if len(left_pair) != 2 or left_pair != right_pair:
        return False
    left_family, right_family = _display_fixture_family(left), _display_fixture_family(right)
    if left_family and right_family and left_family != right_family:
        return False
    left_tip = left.get('tip_at') or left.get('tip_time_bj')
    right_tip = right.get('tip_at') or right.get('tip_time_bj')
    if not left_tip or not right_tip:
        return False
    try:
        return abs((iso(left_tip) - iso(right_tip)).total_seconds()) <= tolerance_minutes * 60
    except (TypeError, ValueError):
        return False


def _first_write_reference(row):
    """Keep compact immutable evidence when a duplicate is removed from view."""
    event = row.get('event') or {}
    selected = (row.get('execution') or {}).get('selected') or {}
    settlement = row.get('settlement') or {}
    market_decisions = (row.get('execution') or {}).get('market_decisions') or {}
    market_refs = []
    for market_type, decision in market_decisions.items():
        if not isinstance(decision, dict):
            continue
        selected = decision.get('selected') or {}
        market_refs.append({
            'market_type': market_type,
            'triggered': decision.get('triggered') is True,
            'selection': selected.get('selection'),
            'line': selected.get('line'),
            'decimal_odds': selected.get('decimal_odds'),
            'prediction_id': selected.get('prediction_id'),
        })
    return {
        'id': row.get('id'), 'event_id': event.get('event_id'),
        'team1_name': event.get('team1_name'), 'team2_name': event.get('team2_name'),
        'tip_at': event.get('tip_at') or event.get('tip_time_bj'),
        'league': event.get('league_display') or event.get('league'),
        'market_type': selected.get('market_type'), 'selection': selected.get('selection'),
        'line': selected.get('line'), 'decimal_odds': selected.get('decimal_odds'),
        'bookmaker': selected.get('bookmaker'), 'prediction_id': selected.get('prediction_id'),
        'triggered': (row.get('execution') or {}).get('triggered') is True,
        'market_decisions': market_refs,
        'settlement': settlement if settlement else None,
    }


def coalesce_duplicate_display_rows(rows, tolerance_minutes=45):
    """Collapse cross-source/time-drift duplicate cards after first-write merge.

    ``_preserve_first_write_paper_rows`` deliberately keeps frozen decisions.
    That is correct for accounting, but two provider ids can then produce two
    cards.  Select the observed canonical row for display and attach compact
    references to every removed frozen row; no source ledger or settlement is
    deleted.
    """
    rows = [row for row in rows if isinstance(row, dict)]
    parent = list(range(len(rows)))
    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index
    def union(left, right):
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left
    for left in range(len(rows)):
        for right in range(left + 1, len(rows)):
            if _same_display_fixture((rows[left].get('event') or {}),
                                     (rows[right].get('event') or {}),
                                     tolerance_minutes):
                union(left, right)
    clusters = {}
    for index in range(len(rows)):
        clusters.setdefault(find(index), []).append(index)
    result = []
    for indexes in clusters.values():
        if len(indexes) == 1:
            row = rows[indexes[0]]
            snapshot = row.get('current_snapshot') or {}
            if snapshot.get('refresh_status') == 'OBSERVED' and snapshot.get('event'):
                row['display_event'] = snapshot.get('event')
                row['display_pricing'] = snapshot.get('pricing') or {}
                row['display_market'] = snapshot.get('market') or {'quotes': [], 'quote_states': []}
                row['display_execution'] = snapshot.get('execution') or {}
            result.append(row)
            continue
        def row_market_decisions(row, current=False):
            source = (row.get('current_snapshot') or {}).get('execution') if current else row.get('execution')
            source = source or {}
            decisions = source.get('market_decisions')
            if isinstance(decisions, dict) and decisions:
                return {name: item for name, item in decisions.items()
                        if name in ('SPREAD', 'TOTAL') and isinstance(item, dict)}
            selected = source.get('selected')
            if isinstance(selected, dict) and selected.get('market_type') in ('SPREAD', 'TOTAL'):
                name = selected['market_type']
                return {name: dict(source, market_type=name, selected=selected)}
            return {}

        def rank(index):
            row = rows[index]
            snapshot = row.get('current_snapshot') or {}
            observed = snapshot.get('refresh_status') == 'OBSERVED' and snapshot.get('event')
            frozen = row_market_decisions(row)
            triggered_markets = sum(item.get('triggered') is True for item in frozen.values())
            # A Qualified first-write row wins over a Titan/research mirror for
            # the same market.  Observation freshness is only a tie-breaker;
            # it must not replace a valid earlier manual-live direction.
            return (-triggered_markets, 0 if observed else 1, 0 if not row.get('first_write_preserved') else 1,
                    str((row.get('event') or {}).get('tip_at') or ''), str(row.get('id') or ''))
        winner_index = min(indexes, key=rank)
        winner = rows[winner_index]
        references = list(winner.get('first_write_references') or [])
        existing_ids = {item.get('id') for item in references}
        for index in indexes:
            reference = _first_write_reference(rows[index])
            if reference.get('id') not in existing_ids:
                references.append(reference)
                existing_ids.add(reference.get('id'))
        winner['first_write_references'] = references
        winner['display_dedupe'] = {
            'method': 'CANONICAL_TEAM_PAIR_AND_TIP_TIME_TOLERANCE',
            'tolerance_minutes': tolerance_minutes,
            'merged_event_ids': [rows[index].get('id') for index in indexes],
            'merged_count': len(indexes),
        }
        # Merge at market level.  One fixture card may contain one SPREAD and
        # one TOTAL, while duplicate rows for the same market keep only the
        # highest-governance direction (Qualified > Titan/research > watch).
        merged_markets = {}
        market_source_indexes = {}
        for market_type in ('SPREAD', 'TOTAL'):
            candidates = []
            for index in indexes:
                row = rows[index]
                decision = row_market_decisions(row).get(market_type)
                if not decision:
                    continue
                candidates.append((
                    0 if decision.get('triggered') is True else 1,
                    0 if decision.get('comparison_ready') else 1,
                    0 if decision.get('selected') else 1,
                    0 if not row.get('first_write_preserved') else 1,
                    index, decision,
                ))
            if candidates:
                _rank, _cmp, _sel, _preserved, source_index, decision = min(candidates)
                merged_markets[market_type] = decision
                market_source_indexes[market_type] = source_index
        if merged_markets:
            import copy
            display = copy.deepcopy(winner.get('execution') or {})
            display['market_decisions'] = copy.deepcopy(merged_markets)
            display['market_types_with_comparison'] = [name for name, item in merged_markets.items()
                                                       if item.get('comparison_ready')]
            display['market_types_triggered'] = [name for name, item in merged_markets.items()
                                                 if item.get('triggered') is True]
            display['triggered'] = bool(display['market_types_triggered'])
            display['comparison_ready'] = bool(display['market_types_with_comparison'])
            selected = [item.get('selected') for item in merged_markets.values() if item.get('selected')]
            display['selected'] = max(selected, key=lambda item: item.get('adverse_ev', float('-inf')), default=None)
            display['ev'] = display['selected'].get('ev') if display.get('selected') else None
            display['shadow_action'] = 'SHADOW_BET' if display['triggered'] else display.get('shadow_action', 'BLOCKED')
            display['display_action'] = '手动实盘候选' if display['triggered'] else display.get('display_action', '不可投')
            display['display_merged_market_view'] = True
            display['merged_market_source_ids'] = {
                market: rows[index].get('id') for market, index in market_source_indexes.items()
            }
            winner['display_execution'] = display
            winner['display_market'] = {'quotes': [], 'quote_states': []}
            seen_quotes = set()
            for index in indexes:
                market = rows[index].get('market') or {}
                for quote in market.get('quotes') or []:
                    quote_id = quote.get('quote_id') or repr(sorted(quote.items()))
                    if quote_id in seen_quotes:
                        continue
                    seen_quotes.add(quote_id)
                    winner['display_market']['quotes'].append(quote)
                winner['display_market']['quote_states'].extend(market.get('quote_states') or [])
            winner['display_dedupe']['merged_market_types'] = sorted(merged_markets)
            winner['display_dedupe']['merged_market_source_ids'] = display['merged_market_source_ids']
        snapshot = winner.get('current_snapshot') or {}
        if snapshot.get('refresh_status') == 'OBSERVED' and snapshot.get('event'):
            # The frozen top-level execution remains the accounting record. The
            # current snapshot is the only display source, so a repaired
            # Titan sign cannot be rendered using an older source convention.
            winner['display_event'] = snapshot.get('event')
            winner['display_pricing'] = snapshot.get('pricing') or {}
            snapshot_market = snapshot.get('market') or {'quotes': [], 'quote_states': []}
            if not (winner.get('display_execution') or {}).get('display_merged_market_view'):
                winner['display_market'] = snapshot_market
                winner['display_execution'] = snapshot.get('execution') or {}
            else:
                # Keep the merged SPREAD/TOTAL decisions, while adding the
                # latest observed quotes to the display-only market snapshot.
                display_market = winner.setdefault('display_market', {'quotes': [], 'quote_states': []})
                seen_quotes = {quote.get('quote_id') for quote in display_market.get('quotes') or []}
                for quote in snapshot_market.get('quotes') or []:
                    if quote.get('quote_id') not in seen_quotes:
                        display_market.setdefault('quotes', []).append(quote)
                        seen_quotes.add(quote.get('quote_id'))
                display_market.setdefault('quote_states', []).extend(snapshot_market.get('quote_states') or [])
        result.append(winner)
    return result


def write_dashboard(root,rows,day,asof,mode,message='',analytics=None,live_funnel=None,coverage=None,pricing_funnel_diagnostic=None,history_readiness_diagnostic=None,total_market_pipeline_diagnostic=None,p0_bias_audit=None,shadow_learning=None,daily_paper_funnel=None,formal_manual_ledger=None,paper_ledger_history=None):
    root=Path(root);web=root/'dashboard_v2';data=web/'data';data.mkdir(parents=True,exist_ok=True)
    # A transient discovery outage must not erase a previously captured
    # same-day schedule/market snapshot.  Keep the last non-empty native view
    # visible until a later successful refresh supplies a replacement.  The
    # preserved rows are still immutable historical records; this branch does
    # not invent quotes or upgrade their betting status.
    existing_day=load(data/(day+'.json'),{})
    day_rows=[r for r in rows if isinstance(r,dict) and isinstance(r.get('event'),dict) and r['event'].get('bj_date')==day]
    if mode=='FORWARD_NATIVE' and not day_rows and existing_day.get('events'):
        rows=[r for r in rows if not (isinstance(r,dict) and isinstance(r.get('event'),dict) and r['event'].get('bj_date')==day)]
        rows.extend(existing_day.get('events') or [])
        message=(message+' 本轮赛程源暂时无结果，沿用上次已确认的赛事快照；未新增或伪造盘口。').strip()
    grouped={}
    for r in rows:grouped.setdefault(r['event']['bj_date'],[]).append(r)
    if mode == 'FORWARD_NATIVE':
        for dt, rs in list(grouped.items()):
            rs = _preserve_first_write_paper_rows(data/(dt+'.json'), rs, asof)
            grouped[dt] = coalesce_duplicate_display_rows(rs)
    # Do not replace past dates with an audit/replay. Each mode has a separate output root.
    for dt,rs in grouped.items():
        if dt<day and mode=='FORWARD_NATIVE':continue
        rs.sort(key=lambda r:(r['event']['tip_at'],r['id']))
        # Recompute from the rows that are actually written after first-write
        # preservation; a pre-write funnel can otherwise disagree with the
        # paper entries visible on the page.
        effective_funnel = funnel(rs)
        date_diagnostic=pricing_funnel_diagnostic if dt==day else None
        date_history=history_readiness_diagnostic if dt==day else None
        date_total=total_market_pipeline_diagnostic if dt==day else None
        date_p0=p0_bias_audit if dt==day else None
        manual_live_present=any(bool((r.get('execution') or {}).get('real_execution_allowed')) for r in rs)
        if date_diagnostic:
            scope=date_diagnostic.get('scope_invariant') or {}
            if date_diagnostic.get('date_bj')!=dt or date_diagnostic.get('events')!=len(rs) or not scope.get('date_scope_match'):
                # First-write preservation can change the visible row set in
                # this preliminary pass.  Never embed a mismatched diagnostic;
                # the pipeline recomputes it from the final rows immediately.
                date_diagnostic=None;date_history=None;date_total=None;date_p0=None
        d={'schema_version':'basketball-dashboard-2.2','date_bj':dt,'archive_type':mode,'generated_at':stamp(),'asof':asof,
           'message':message,'funnel':effective_funnel,'cold_start_summary':cold_start_summary(rs),'coverage':coverage,'pricing_funnel_diagnostic':date_diagnostic,'total_market_pipeline_diagnostic':date_total,'history_readiness_diagnostic':date_history,'p0_bias_audit':date_p0,
           'events':rs,'analytics':analytics,'shadow_learning':shadow_learning,'formal_manual_ledger':formal_manual_ledger,
           'paper_ledger_history':paper_ledger_history,
           'daily_paper_funnel':daily_paper_funnel if dt==day else None,'execution_mode':'MANUAL_LIVE',
           'automated_execution_allowed':False,'real_execution_allowed':manual_live_present}
        old=load(data/(dt+'.json'),{});oldrows=old.get('events',[])
        # Preserve old records separately for inspection; never count them as repaired native predictions.
        if oldrows and old.get('schema_version')!='basketball-dashboard-2.2':
            archive=data/'legacy_versions';archive.mkdir(exist_ok=True)
            from .common import exclusive,fingerprint
            exclusive(archive/(dt+'_'+fingerprint(old)[:12]+'.json'),old)
        atomic(data/(dt+'.json'),d)
    rs=grouped.get(day,[])
    latest={'schema_version':'basketball-dashboard-2.2','date_bj':day,'archive_type':mode,'generated_at':stamp(),'asof':asof,
            'message':message,'events':rs,'funnel':funnel(rs),'cold_start_summary':cold_start_summary(rs),'coverage':coverage,
            'pricing_funnel_diagnostic':pricing_funnel_diagnostic,'total_market_pipeline_diagnostic':total_market_pipeline_diagnostic,'history_readiness_diagnostic':history_readiness_diagnostic,'p0_bias_audit':p0_bias_audit,'analytics':analytics,
            'shadow_learning':shadow_learning,'daily_paper_funnel':daily_paper_funnel,'formal_manual_ledger':formal_manual_ledger,
            'paper_ledger_history':paper_ledger_history,'execution_mode':'MANUAL_LIVE',
            'automated_execution_allowed':False,'real_execution_allowed':any(bool((r.get('execution') or {}).get('real_execution_allowed')) for r in rs)}
    atomic(data/(day+'.json'),latest);atomic(data/'latest.json',latest)
    entries=[]
    for p in sorted(data.glob('20??-??-??.json'),reverse=True):
        j=load(p,{});entries.append({'date':p.stem,'file':p.name,'event_count':len(j.get('events',[])),'archive_type':j.get('archive_type','LEGACY_MIGRATED')})
    atomic(data/'index.json',{'generated_at':stamp(),'dates':entries})
    # Keep the legacy local/public page on ./data/, but publish v2 with its
    # own basketball-data/ root. The two pages must never share a transformed
    # HTML file: v2 is served as /basketball-v2.html at repository root.
    (web/'basketball.html').write_text(HTML.replace("new URL('./basketball-data/',location.href)","new URL('./data/',location.href)"),encoding='utf-8')
    (web/'basketball-v2.html').write_text(HTML,encoding='utf-8')
    return latest

def standalone_preview(path,document):
    # Static audit preview only, not the historical ledger or a live dashboard.
    data=json.dumps(document,ensure_ascii=False).replace('</','<\\/')
    Path(path).write_text(HTML.replace('<script>','<script>window.__AUDIT_DATA__='+data+';</script><script>',1),encoding='utf-8')
