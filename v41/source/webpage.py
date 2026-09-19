"""Static, self-contained pages; only independent V41 report/frozen inputs."""
import html,shutil
from .common import *

STYLE='''body{font:15px/1.6 system-ui,"Microsoft YaHei",sans-serif;background:#101824;color:#dfebf5;margin:0}main{max-width:1500px;margin:auto;padding:28px}h1{font-size:32px;margin:0}h2{margin-top:30px}a{color:#76d1ec}p{max-width:1150px}.banner{padding:16px;background:#28334b;border-left:5px solid #ffd178;margin:20px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.metric,article{background:#1a2737;padding:16px;border:1px solid #344357;border-radius:8px;margin-bottom:12px}.metric b{font-size:24px;display:block}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{text-align:left;padding:9px;border-bottom:1px solid #38475a;white-space:nowrap}th{color:#86cddd}small,.muted{color:#9bafc3}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}summary{cursor:pointer;color:#86cddd}.pill{border:1px solid #e6b86b;color:#ffd178;padding:3px 8px;border-radius:6px}.warn{color:#ffd178}input,select{padding:9px;background:#24374a;color:white;border:1px solid #60778d}footer{margin-top:32px;color:#9bafc3}'''
STYLE+=' .metric{min-width:0}.metric b{font-size:22px;overflow-wrap:anywhere}button{padding:9px;background:#24374a;color:white;border:1px solid #60778d;cursor:pointer}article h3{overflow-wrap:anywhere}'
def esc(x):return html.escape(str(x if x is not None else 'MISSING'))
def num(x):return '—' if x is None else f'{x:.3f}' if isinstance(x,(float,int)) else esc(x)
def pct(x):return '—' if x is None else f'{100*x:.2f}%'
def table(rows,columns):
    if not rows:return '<p class="muted">暂无样本。空白不是零收益，也不代表已验证。</p>'
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(label)+'</th>' for key,label in columns)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(r.get(k))+'</td>' for k,l in columns)+'</tr>' for r in rows)+'</tbody></table></div>'
def shell(title,body):return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+'</title><style>'+STYLE+'</style><main>'+body+'<footer>V3 是唯一正式决策。V4 CONTROL 与 V4.1 CHALLENGER 均不执行真实投注。200 候选是最低观察门槛，理想 500+；不得自动晋级。</footer></main></html>'
def render(report,rows):
    folder=ROOT/'dashboard';folder.mkdir(parents=True,exist_ok=True);(folder/'compare').mkdir(exist_ok=True)
    summary=report['summary'];model=report['model'];day=report['list_date'];settlements={r['match_id']:r for r in rows if r['date']==day};metrics=[('列表日',day),('候选 / 冻结',f"{summary['candidates']} / {summary['frozen']}"),('A / B / C / N',' / '.join(str(summary['grades'][g]) for g in 'ABCN')),('Giving / Receiving',f"{summary['giving']} / {summary['receiving']}"),('列表总数 / 预览计算',f"{summary['total']} / {summary['computed_preview']}"),('Freeze Time',summary['latest_freeze'] or '尚无前瞻冻结')]
    body='<h1>V4.1 Shadow</h1><p><span class="pill">SHADOW ONLY</span> <span class="pill">NOT FOR PRODUCTION</span> · real_money=false</p><nav><a href="compare/">V4 vs V4.1 同场比较 →</a> · <a href="../v4/">原 V4 CONTROL</a> · <a href="../v3-legacy/">V3 Production</a> · <a href="V41_BUILD_REPORT.md">构建报告</a></nav>'
    body+='<div class="banner">概率已做独立验证集温度校准，但 T-30 验证仅 5 场，尚不足以支持临场交易优势。R1 候选门槛保持关闭，NO BET 是有效输出。历史测试不是 forward；预览不是冻结。OPEN 没有可靠初始时间则标记 MISSING。</div>'
    body+='<div class="grid">'+''.join('<div class="metric">'+esc(k)+'<b>'+esc(v)+'</b></div>' for k,v in metrics)+'</div>'
    body+='<p>Model: '+esc(model['model_version'])+' · Probability Model: '+esc(model['model_type'])+'<br>Calibration Version: '+esc(model['calibration_version'])+' / '+esc(model['calibration_state'])+' · 温度 '+num(model['temperature'])+'<br>Snapshot Policy: SNAPSHOT_R1，主冻结 T-30 = 开赛前 25–40 分钟，首次真实运行合格报价；观测报价最长 3 分钟。报价时间为本地收到价格的时间，不冒充供应商逐笔时间。<br>生成：'+esc(report['generated_at'])+'</p>'
    if report.get('control_error'):body+='<p class="warn">CONTROL 隔离运行异常：'+esc(report['control_error'])+'；未配对比赛不冻结。</p>'
    body+='<h2>前瞻冻结与盘口预览</h2><p>顶部等级只统计本列表日不可变冻结记录。非 T-30 行仅供数据质量检查，不能视为候选名单。已冻结比赛优先展示，每页5场。</p><input id="search" placeholder="搜索球队 / 联赛 / 窗口状态" oninput="showCards(0)"> <button onclick="showCards(page-1)">上一页</button> <button onclick="showCards(page+1)">下一页</button> <span id="pageinfo"></span>'
    prefix=body;articles=[]
    for c in sorted(report['cards'],key=lambda c:(not bool(c.get('frozen_at')),not bool(c.get('probability')),c['match_id'])):
        body=''
        s=c.get('snapshot') or {};f=c.get('features') or {};p=c.get('probability') or {};d=c['decision'];r=c.get('roster') or {};result=settlements.get(c['match_id'],{});match=(s.get('home') or r.get('home_cn') or r.get('home_team') or c['match_id'])+' vs '+(s.get('away') or r.get('away_cn') or r.get('away_team') or 'MISSING')
        body+='<article><h3>'+esc(match)+' <small>'+esc(s.get('league',r.get('league_cn','')))+' · '+esc(c['match_id'])+'</small></h3><span class="pill">'+esc(d.get('grade'))+' / '+esc(d.get('action'))+'</span> '+esc(c['window_status'])
        fields=[('Kickoff',s.get('kickoff_at')),('Snapshot time',s.get('quote_at')),('Minutes to kickoff',num(s.get('minutes_to_kickoff'))),('Giving / Receiving',str(s.get('giving_team'))+' / '+str(s.get('receiving_team'))),('Opening handicap',s.get('opening_handicap')),('Candidate / handicap / water',f"{d.get('candidate_team')} / {d.get('candidate_handicap')} / {d.get('water')}"),('Market interpretation',f.get('market_interpretation',{}).get('intent')),('Intent confidence',num(f.get('market_interpretation',{}).get('intent_confidence'))),('P giving / receiving cover',pct(d.get('P_giving_cover'))+' / '+pct(d.get('P_receiving_cover'))),('Raw W/HW/P/HL/L',p.get('raw_probability')),('Calibrated W/HW/P/HL/L (giving)',p.get('calibrated_probability')),('EV mean / p10 / p25',pct(d.get('EV_mean'))+' / '+pct(d.get('EV_p10'))+' / '+pct(d.get('EV_p25'))),('P(EV>0) / uncertainty width',pct(d.get('P_EV_positive'))+' / '+pct(d.get('uncertainty'))),('Completeness required / all',pct(f.get('feature_completeness'))+' / '+pct(f.get('all_feature_completeness'))),('Calibration support all / T-30',str(p.get('calibration_support'))+' / '+str(p.get('window_calibration_support'))),('Model / freeze',str(c.get('model_version',model['model_version']))+' / '+str(c.get('frozen_at','NOT FROZEN'))),('Result / PnL',str(result.get('v41_result','PENDING'))+' / '+str(result.get('v41_pnl'))),('Decision reason',d.get('decision_reason'))]
        body+=table([{'field':k,'value':v} for k,v in fields],[('field','字段'),('value','值')])
        trace={'positive_drivers':p.get('top_positive_drivers'),'negative_drivers':p.get('top_negative_drivers'),'driver_basis':'signed logit contribution to giving W minus L, not causal proof','missing_features':f.get('missing_features'),'snapshot_windows':c.get('windows'),'path':f.get('path'),'provenance':f.get('provenance'),'control':c.get('control')}
        body+='<details><summary>展开驱动因素、盘口路径、窗口缺失、来源及 CONTROL</summary><pre>'+esc(json.dumps(trace,ensure_ascii=False,indent=2))+'</pre></details></article>'
        articles.append({'search':match+' '+str(s.get('league',r.get('league_cn','')))+' '+str(c['match_id'])+' '+c['window_status'],'html':body})
    write(folder/'cards.json',articles)
    body=prefix+'<section id="cards">'+''.join(a['html'] for a in articles[:5])+'</section>'
    body+='''<script>let page=0,allCards=null;async function showCards(next){try{if(!allCards){const r=await fetch('cards.json');if(!r.ok)throw Error(r.status);allCards=await r.json()}const q=document.getElementById('search').value.toLowerCase();const filtered=allCards.filter(x=>x.search.toLowerCase().includes(q));page=Math.max(0,Math.min(next,Math.max(0,Math.ceil(filtered.length/5)-1)));document.getElementById('cards').innerHTML=filtered.slice(page*5,page*5+5).map(x=>x.html).join('');document.getElementById('pageinfo').textContent=`第 ${page+1} / ${Math.max(1,Math.ceil(filtered.length/5))} 页 · ${filtered.length} 场`}catch(e){document.getElementById('pageinfo').textContent='读取失败，请刷新：'+e.message}}document.getElementById('pageinfo').textContent='第1页 · 搜索和翻页时加载完整列表';</script>'''
    body+='<h2>系统健康</h2><p>短样本显示 INSUFFICIENT / SMALL_SAMPLE，不当作健康通过。单日集中度报警不等于已证实长期失效。</p>'
    for key,items in report['health'].items():
        body+='<details><summary>'+esc(key)+' ('+str(len(items))+')</summary>'+table(items[:30],[(k,k) for k in (list(items[0]) if items else [])])+'<p>页面最多展示30行；<a href="diagnostics/'+key+'_health.csv">下载完整检查表</a></p></details>'
    (folder/'index.html').write_text(shell('V4.1 Shadow',body),encoding='utf-8')
    comp=report['comparison'];body='<h1>V4 vs V4.1 · Forward Comparison</h1><p>SHADOW ONLY · NOT FOR PRODUCTION · <a href="../">返回 V4.1</a></p><div class="banner">只纳入同场、同报价、T-30 同轮生成的不可变前瞻配对。V4 使用原代码逐字节隔离副本，规则不变；原 V4 页面及历史不改写。时间窗口统一的 CONTROL 不等于旧页面历史全量成绩。</div>'
    def perf_table(groups):
        records=[]
        for group,models in groups.items():
            for name,m in models.items():records.append({'group':group,'model':name,'candidates':m['candidates'],'settled':m['settled'],'win_rate':pct(m['effective_win_rate']),'PnL':num(m['PnL']),'ROI':pct(m['ROI']),'max_drawdown':num(m['max_drawdown']),'Brier':num(m['calibration']['brier']),'ECE':pct(m['calibration']['ece'])})
        return table(records,[(k,k) for k in ['group','model','candidates','settled','win_rate','PnL','ROI','max_drawdown','Brier','ECE']])
    body+='<h2>Overall</h2>'+perf_table({'ALL':comp['overall']})+'<p>1u/候选，ROI 分母仅已结算候选；走盘计入 stake，红半/黑半在有效胜率中各计 0.5。无结算时 ROI 为缺失。</p>'
    for group in ['A_V4_ONLY','B_V41_ONLY','C_SAME_SIDE','D_OPPOSITE_SIDE']:
        body+='<h2>'+group+'</h2>'+perf_table({group:comp['groups'].get('comparison_group',{}).get(group,{})})
    for key in ['date','region','handicap','v41_grade','v4_grade','time_bucket','intent','v41_side']:body+='<h2>By '+key+'</h2>'+perf_table(comp['groups'].get(key,{}))
    body+='<p><a href="../forward_comparison.csv">下载不可变决策的比较视图 CSV</a></p><p>至少 200 ABC 候选、最好 500+，并覆盖多个周末、联赛、时段与两个方向。当前阶段不能判断优于 V4。</p>'
    (folder/'compare/index.html').write_text(shell('V4 vs V4.1 Comparison',body),encoding='utf-8');shutil.copy2(ROOT/'forward/forward_comparison.csv',folder/'forward_comparison.csv');write(folder/'data.json',report)
    (folder/'diagnostics').mkdir(exist_ok=True)
    for p in (ROOT/'diagnostics').glob('*_health.csv'):shutil.copy2(p,folder/'diagnostics'/p.name)
    if (ROOT/'diagnostics/V41_BUILD_REPORT.md').exists():shutil.copy2(ROOT/'diagnostics/V41_BUILD_REPORT.md',folder/'V41_BUILD_REPORT.md')
