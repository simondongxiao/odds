"""V4.1 独立静态页面；只读取 V4.1 报告与冻结记录。"""

import html
import json
import shutil

from .common import *


STYLE = r'''
:root{color-scheme:light;--page:#d9e8f6;--line:#8eb1d0;--soft:#c8d9e8;--head:#1767a5;--head2:#2f7fbd;--sub:#eaf4fc;--panel:#fff;--text:#17324d;--muted:#607a93;--red:#b91c1c;--green:#138a48;--blue:#095fa6;--amber:#a86100}
*{box-sizing:border-box}body{font:14px/1.6 Arial,"Microsoft YaHei","PingFang SC",sans-serif;margin:0;background:var(--page);color:var(--text)}
.wrap{max-width:1600px;margin:0 auto;padding:18px}.hero{background:linear-gradient(180deg,var(--head2),var(--head));color:#fff;padding:16px 20px;border-bottom:2px solid #174e7e}.hero h1{margin:0 0 6px;font-size:25px}.hero-sub{color:#d8ecff}.badges{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px}.badge{display:inline-block;padding:2px 8px;border:1px solid rgba(255,255,255,.75);border-radius:3px;font-size:12px;font-weight:700}.nav{display:flex;gap:15px;flex-wrap:wrap;padding:10px 0}.nav a{color:var(--blue);font-weight:700}
.notice,.definitions{background:#fff;border:1px solid var(--soft);padding:11px 15px;margin-bottom:10px}.notice{border-left:5px solid #d99824;background:#fffaf0}.definitions{line-height:1.8}.definitions b{color:#174e7e}
.metrics{display:grid;grid-template-columns:repeat(6,minmax(145px,1fr));gap:8px;margin:10px 0}.metric{background:#fff;border:1px solid var(--soft);padding:9px 11px;min-width:0}.metric span{display:block;color:var(--muted);font-size:12px}.metric b{display:block;color:var(--blue);font-size:20px;line-height:1.3;overflow-wrap:anywhere}
.controls{display:flex;gap:10px;align-items:end;flex-wrap:wrap;background:var(--sub);padding:11px;border:1px solid var(--soft);margin-top:10px}.controls label{font-weight:700}.controls input,.controls select{display:block;min-width:150px;padding:7px;border:1px solid var(--line);background:#fff;color:var(--text)}.controls input{min-width:250px}.pager{display:flex;align-items:center;gap:8px;margin-left:auto}.pager button{padding:7px 12px;border:1px solid var(--line);background:#fff;color:var(--blue);font-weight:700;cursor:pointer}.pager button:hover{background:#f2f8fe}
.section-title{margin:14px 0 0;padding:8px 11px;background:var(--head);color:#fff;font-size:15px}.section-note{padding:8px 11px;background:#fff;border:1px solid var(--soft);border-top:0;color:var(--muted)}
.table-wrap{overflow:auto;background:#fff;border:1px solid var(--soft)}table{border-collapse:collapse;width:100%;min-width:1450px}th{background:#dcecf8;color:#174e7e;text-align:left;position:sticky;top:0;z-index:1}td,th{padding:8px;border:1px solid #d4e0ea;vertical-align:top;white-space:nowrap}tbody tr:hover{background:#f6fbff}.match{font-weight:700;color:#17324d}.meta{font-size:12px;color:var(--muted);line-height:1.45}.grade{font-weight:800;font-size:16px}.grade-A{color:#138a48}.grade-B{color:#a86100}.grade-C{color:#2563eb}.grade-N{color:#b91c1c}.status{font-weight:700;color:#526b7d}.status-frozen{color:#138a48;font-weight:700}.decision-no{color:#b91c1c;font-weight:700}.decision-yes{color:#138a48;font-weight:700}.num-positive{color:#138a48;font-weight:700}.num-negative{color:#b91c1c;font-weight:700}.empty{padding:28px!important;text-align:center;color:var(--muted)}
details{background:#fff;border:1px solid var(--soft);margin-top:10px}details summary{cursor:pointer;padding:8px 11px;background:#f2f8fe;color:var(--blue);font-weight:700}details .detail-body{padding:10px;overflow:auto}details table{min-width:1050px}.inline-detail{border:0;margin:0;background:transparent}.inline-detail summary{padding:0;background:transparent;white-space:nowrap}.detail-grid{display:grid;grid-template-columns:repeat(2,minmax(280px,1fr));gap:7px;margin-top:8px;min-width:620px}.detail-item{white-space:normal;border:1px solid #d4e0ea;background:#f8fbfe;padding:6px}.detail-item b{display:block;color:#174e7e}.raw{margin-top:8px;white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.5 Consolas,monospace;color:#40576a;background:#f5f8fb;padding:8px;border:1px solid #d4e0ea}
.compare-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.model-card{background:#fff;border:1px solid var(--soft)}.model-card h2{margin:0;padding:8px 11px;background:var(--head);color:#fff;font-size:15px}.model-card .metrics{padding:0 10px}.model-card .metric b{font-size:18px}.compact table{min-width:1200px}.download{display:inline-block;margin:10px 0;padding:7px 11px;background:var(--head);color:#fff;text-decoration:none;font-weight:700}
h2{font-size:17px;margin:20px 0 8px;color:#174e7e}a{color:var(--blue)}footer{margin:24px 0 4px;padding:10px 12px;border-top:1px solid var(--line);color:var(--muted);background:rgba(255,255,255,.55)}
@media(max-width:900px){.wrap{padding:8px}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.compare-grid{grid-template-columns:1fr}.pager{width:100%;margin-left:0}.detail-grid{grid-template-columns:1fr}.hero h1{font-size:21px}}
'''


WINDOW_CN = {
    'FROZEN_PRIMARY_T30': '已冻结（T-30）', 'WAIT_PRIMARY_WINDOW': '等待主冻结窗口',
    'PRIMARY_T30': '处于主冻结窗口', 'MISSED_PRIMARY_WINDOW': '已错过主冻结窗口',
    'MISSING_OR_NON_PREMATCH': '缺少有效赛前快照',
}
ACTION_CN = {'NO BET': '不投', 'BET': '候选', 'WATCH': '观察'}
SIDE_CN = {'giving': '让球方', 'receiving': '受让方', 'home': '主队', 'away': '客队'}
RESULT_CN = {'W': '红', 'HW': '红半', 'P': '走', 'HL': '黑半', 'L': '黑'}
REASON_CN = {
    'NO_VALID_PREMATCH_SNAPSHOT': '没有有效赛前快照', 'NOT_PRIMARY_T30_WINDOW': '尚未进入主冻结窗口',
    'MULTI_GATE_NOT_PASSED': '多重门槛未全部通过',
    'INSUFFICIENT_T30_CALIBRATION_SUPPORT': 'T-30 校准样本不足',
    'NEUTRAL_PK': '平手盘无可验证方向', 'MISSING_MARKET': '盘口数据缺失',
}
HEALTH_CN = {
    'probability': '概率分布', 'direction': '方向平衡', 'intent': '盘口意图',
    'grade': '等级分布', 'snapshot': '快照完整性', 'feature': '特征完整性',
    'calibration': '概率校准', 'ev': '期望收益', 'grade_performance': '等级表现',
}
GROUP_CN = {
    'A_V4_ONLY': '仅 V4 入选', 'B_V41_ONLY': '仅 V4.1 入选',
    'C_SAME_SIDE': '两者同向入选', 'D_OPPOSITE_SIDE': '两者反向入选',
    'NEITHER': '两者均未入选', 'v4': '原 V4', 'v41': 'V4.1',
    'giving': '让球方', 'receiving': '受让方', 'UNKNOWN': '未知',
    'MIXED': '混合信号', 'NEUTRAL': '中性', 'None': '无等级',
}
KEY_CN = {
    'group': '分组', 'model': '模型', 'candidates': '候选', 'settled': '已结算',
    'pending': '待结算', 'win_rate': '有效胜率', 'PnL': '盈亏', 'ROI': '收益率',
    'max_drawdown': '最大回撤', 'Brier': '布里尔分数', 'ECE': '校准误差',
    'status': '状态', 'count': '数量', 'n': '样本数', 'sample': '样本',
    'value': '数值', 'rate': '比例', 'note': '说明', 'alarm': '预警',
    'metric': '指标', 'bucket': '分组', 'grade': '等级', 'result': '赛果',
    'date': '日期', 'region': '区域', 'handicap': '盘口', 'intent': '盘口意图',
    'time_bucket': '时间窗口', 'v41_side': 'V4.1方向', 'v41_grade': 'V4.1等级',
    'v4_grade': 'V4等级',
}


def esc(value):
    if value is None or value == '':
        return '—'
    return html.escape(str(value))


def num(value):
    if value is None:
        return '—'
    return f'{value:.3f}' if isinstance(value, (float, int)) else esc(value)


def pct(value):
    return '—' if value is None else f'{100 * value:.2f}%'


def time_cn(value):
    if not value:
        return '—'
    return esc(str(value).replace('T', ' ').replace('+08:00', '')) + '<br><span class="meta">北京时间</span>'


def reason_cn(reasons):
    return '—' if not reasons else '；'.join(REASON_CN.get(x, x) for x in reasons)


def group_cn(value):
    return GROUP_CN.get(str(value), str(value))


def table(rows, columns, css=''):
    if not rows:
        return '<p class="empty">暂无样本。空白不代表零收益，也不代表已经验证。</p>'
    head = ''.join('<th>' + esc(label) + '</th>' for key, label in columns)
    body = ''.join('<tr>' + ''.join('<td>' + esc(group_cn(row.get(key))) + '</td>' for key, _ in columns) + '</tr>' for row in rows)
    return f'<div class="table-wrap {css}"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def shell(title, body):
    footer = ('<footer>V3 是唯一正式决策。原 V4 对照组与 V4.1 挑战组都只做影子观察，'
              '不执行真实投注。候选至少积累 200 场、理想 500 场以上后才具备评估意义，禁止自动晋级。</footer>')
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><style>{STYLE}</style></head><body><div class="wrap">{body}{footer}</div></body></html>')


def _metric(label, value):
    return f'<div class="metric"><span>{esc(label)}</span><b>{esc(value)}</b></div>'


def _detail_item(label, value):
    return f'<div class="detail-item"><b>{esc(label)}</b>{esc(value)}</div>'


def _health_table(items):
    if not items:
        return '<p class="empty">暂无记录。</p>'
    keys = list(items[0])
    return table(items[:30], [(key, KEY_CN.get(key, key)) for key in keys], 'compact')


def render(report, rows):
    folder = ROOT / 'dashboard'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'compare').mkdir(exist_ok=True)
    summary, model, day = report['summary'], report['model'], report['list_date']
    comp = report['comparison']
    settlements = {row['match_id']: row for row in rows if row['date'] == day}

    body = ('<section class="hero"><h1>V4.1 影子模型看板</h1>'
            '<div class="hero-sub">独立挑战模型 · 仅用于前瞻观察，不构成真实下注建议</div>'
            '<div class="badges"><span class="badge">仅影子观察</span><span class="badge">禁止实盘</span>'
            '<span class="badge">real_money=false</span></div></section>')
    body += ('<nav class="nav"><a href="compare/">V4 与 V4.1 同场对照</a>'
             '<a href="../v4/">原 V4 影子看板</a><a href="../v3-legacy/">V3 正式决策页</a>'
             '<a href="V41_BUILD_REPORT.md">V4.1 构建报告</a></nav>')
    body += ('<section class="definitions"><b>等级定义：</b> A、B、C 为依次降低的正期望候选等级；'
             'N 表示完成计算但未通过候选门槛。<b>页面口径：</b> 顶部 A/B/C/N 只统计本列表日已经冻结的赛前记录；'
             '“预览计算”不等于冻结，更不等于候选。</section>')
    body += ('<section class="notice">独立验证集已经完成温度校准，但 T-30 验证样本目前只有 5 场，'
             '不足以证明临场优势。因此 R1 的候选闸门保持关闭，“不投”是当前模型的有效结论。'
             '历史测试不冒充前瞻结果；缺少可靠初始时间的开盘数据明确标为“缺失”。</section>')
    metrics = [
        ('列表日', day), ('总赛事', summary['total']), ('预览计算', summary['computed_preview']),
        ('冻结记录', summary['frozen']), ('A / B / C / N', ' / '.join(str(summary['grades'][g]) for g in 'ABCN')),
        ('候选 / 不投', f"{summary['candidates']} / {summary['grades']['N']}"),
        ('让球方 / 受让方', f"{summary['giving']} / {summary['receiving']}"),
        ('最近冻结时间', (summary['latest_freeze'] or '尚无冻结').replace('T', ' ').replace('+08:00', '')),
    ]
    body += '<div class="metrics">' + ''.join(_metric(k, v) for k, v in metrics) + '</div>'
    previous_dates = [value for value in comp.get('n_observation_by_date', {}) if value < day]
    if previous_dates:
        previous_day = max(previous_dates)
        n_perf = comp['n_observation_by_date'][previous_day]['v41']
        body += ('<h2 class="section-title">上一冻结列表日 N 不投观察结算</h2>'
                 '<div class="section-note">N 仍为不投；以下只按冻结方向与原盘口记录纸面红黑，不改变等级，也不代表真实投注。</div>'
                 '<div class="metrics">' + _metric('列表日', previous_day) + _metric('N 冻结样本', n_perf['candidates']) +
                 _metric('已结算 / 待核', f"{n_perf['settled']} / {n_perf['pending']}") +
                 _metric('红 / 红半 / 走 / 黑半 / 黑', f"{n_perf['W']} / {n_perf['HW']} / {n_perf['P']} / {n_perf['HL']} / {n_perf['L']}") +
                 _metric('有效胜率', pct(n_perf['effective_win_rate'])) + _metric('纸面盈亏', f"{n_perf['PnL']:+.2f}u") +
                 _metric('纸面收益率', pct(n_perf['ROI'])) + '</div>')
    body += ('<section class="definitions"><b>模型版本：</b> ' + esc(model['model_version']) +
             '　<b>概率模型：</b> 分桶先验偏置的掩码多项逻辑回归'
             '　<b>校准：</b> 独立验证集温度校准（温度 ' + num(model['temperature']) + '）<br>'
             '<b>主冻结窗口：</b> 开赛前 25–40 分钟内首次真实运行且报价合格的 T-30 快照；'
             '报价时间是本地收到价格的时间。　<b>页面生成：</b> ' + esc(report['generated_at'].replace('T', ' ').replace('+08:00', '')) + '</section>')
    if report.get('control_error'):
        body += '<section class="notice">原 V4 隔离对照运行异常：' + esc(report['control_error']) + '；未能配对的比赛不会冻结。</section>'

    body += ('<h2 class="section-title">今日赛事与冻结决策</h2>'
             '<div class="section-note">冻结记录优先排列。非 T-30 行只用于检查数据质量，不能视为候选名单。</div>'
             '<div class="controls"><label>搜索<input id="search" placeholder="球队、联赛或比赛编号" oninput="showCards(0)"></label>'
             '<label>等级<select id="grade" onchange="showCards(0)"><option value="全部">全部等级</option>'
             '<option>A</option><option>B</option><option>C</option><option>N</option></select></label>'
             '<label>状态<select id="window" onchange="showCards(0)"><option value="全部">全部状态</option>'
             '<option value="FROZEN_PRIMARY_T30">已冻结（T-30）</option><option value="WAIT_PRIMARY_WINDOW">等待主冻结窗口</option>'
             '<option value="PRIMARY_T30">处于主冻结窗口</option><option value="MISSED_PRIMARY_WINDOW">已错过主冻结窗口</option>'
             '<option value="MISSING_OR_NON_PREMATCH">缺少有效赛前快照</option></select></label>'
             '<div class="pager"><button onclick="showCards(page-1)">上一页</button><span id="pageinfo"></span>'
             '<button onclick="showCards(page+1)">下一页</button></div></div>')

    cards = []
    ordered = sorted(report['cards'], key=lambda c: (not bool(c.get('frozen_at')), not bool(c.get('probability')), c['match_id']))
    for card in ordered:
        snapshot, features, probability = card.get('snapshot') or {}, card.get('features') or {}, card.get('probability') or {}
        decision, roster = card['decision'], card.get('roster') or {}
        result = settlements.get(card['match_id'], {})
        home = snapshot.get('home') or roster.get('home_cn') or roster.get('home_team') or card['match_id']
        away = snapshot.get('away') or roster.get('away_cn') or roster.get('away_team') or '缺失'
        league = snapshot.get('league') or roster.get('league_cn') or '未标注'
        match, grade = f'{home} vs {away}', decision.get('grade') or '—'
        action = ACTION_CN.get(decision.get('action'), decision.get('action') or '—')
        side = SIDE_CN.get(decision.get('candidate_side'), decision.get('candidate_side') or '—')
        status = WINDOW_CN.get(card['window_status'], card['window_status'])
        candidate = decision.get('candidate_team') or '—'
        giving, receiving = snapshot.get('giving_team') or '—', snapshot.get('receiving_team') or '—'
        market_intent = group_cn((features.get('market_interpretation') or {}).get('intent') or '—')
        settled_code = result.get('v41_result')
        settled_text = RESULT_CN.get(settled_code, settled_code or '待结算')
        pnl_value = result.get('v41_pnl') if grade in 'ABC' else result.get('v41_hypothetical_unit_pnl')
        pnl_text = '—' if pnl_value is None else f'{pnl_value:+.2f}u'
        p_giving, p_receiving, ev_mean = decision.get('P_giving_cover'), decision.get('P_receiving_cover'), decision.get('EV_mean')
        ev_class = 'num-positive' if isinstance(ev_mean, (int, float)) and ev_mean > 0 else 'num-negative' if isinstance(ev_mean, (int, float)) and ev_mean < 0 else ''
        status_class = 'status-frozen' if card['window_status'] == 'FROZEN_PRIMARY_T30' else 'status'
        action_class = 'decision-yes' if grade in 'ABC' else 'decision-no'
        trace = {
            '正向驱动因素': probability.get('top_positive_drivers'), '负向驱动因素': probability.get('top_negative_drivers'),
            '缺失特征': features.get('missing_features'), '盘口路径': features.get('path'),
            '数据来源': features.get('provenance'), '原 V4 隔离对照': card.get('control'),
        }
        detail = '<details class="inline-detail"><summary>查看详情</summary><div class="detail-grid">'
        detail += _detail_item('开盘盘口', snapshot.get('opening_handicap'))
        detail += _detail_item('盘口意图', market_intent)
        detail += _detail_item('意图置信度', num((features.get('market_interpretation') or {}).get('intent_confidence')))
        detail += _detail_item('原始 W/HW/P/HL/L 概率', probability.get('raw_probability'))
        detail += _detail_item('校准后 W/HW/P/HL/L 概率（让球方）', probability.get('calibrated_probability'))
        detail += _detail_item('必需特征 / 全部特征完整度', pct(features.get('feature_completeness')) + ' / ' + pct(features.get('all_feature_completeness')))
        detail += _detail_item('全部 / T-30 校准支持样本', str(probability.get('calibration_support')) + ' / ' + str(probability.get('window_calibration_support')))
        detail += _detail_item('决策原因', reason_cn(decision.get('decision_reason')))
        detail += '</div><pre class="raw">' + esc(json.dumps(trace, ensure_ascii=False, indent=2)) + '</pre></details>'
        row_html = ('<tr><td>' + time_cn(snapshot.get('kickoff_at')) + '</td>'
                    '<td>' + esc(league) + '<br><span class="meta">编号 ' + esc(card['match_id']) + '</span></td>'
                    '<td><span class="match">' + esc(match) + '</span><br><span class="meta">让球方 ' + esc(giving) + ' / 受让方 ' + esc(receiving) + '</span></td>'
                    '<td class="' + status_class + '">' + esc(status) + '</td>'
                    '<td class="grade grade-' + esc(grade) + '">' + esc(grade) + '<br><span class="' + action_class + '">' + esc(action) + '</span></td>'
                    '<td>' + esc(candidate) + '<br><span class="meta">' + esc(side) + ' · ' + esc(market_intent) + '</span></td>'
                    '<td>' + esc(decision.get('candidate_handicap')) + ' / ' + esc(decision.get('water')) + '</td>'
                    '<td>' + pct(p_giving) + ' / ' + pct(p_receiving) + '</td>'
                    '<td class="' + ev_class + '">' + pct(ev_mean) + '<br><span class="meta">P10 ' + pct(decision.get('EV_p10')) + ' · P25 ' + pct(decision.get('EV_p25')) + '<br>P(EV&gt;0) ' + pct(decision.get('P_EV_positive')) + '</span></td>'
                    '<td>' + time_cn(snapshot.get('quote_at')) + '<span class="meta">冻结：' + esc((card.get('frozen_at') or '未冻结').replace('T', ' ').replace('+08:00', '')) + '</span></td>'
                    '<td>' + esc(settled_text) + ' / ' + esc(pnl_text) + '</td><td>' + detail + '</td></tr>')
        search = f'{match} {league} {card["match_id"]} {status} {market_intent}'
        cards.append({'search': search, 'grade': grade, 'window': card['window_status'], 'html': row_html})

    write(folder / 'cards.json', cards)
    body += ('<div class="table-wrap"><table><thead><tr><th>北京时间</th><th>联赛/杯赛</th><th>比赛</th><th>状态</th>'
             '<th>等级/结论</th><th>候选球队/方向</th><th>盘口/水位</th><th>让球/受让覆盖率</th><th>EV指标</th>'
             '<th>报价/冻结</th><th>赛果/模拟盈亏</th><th>明细</th></tr></thead><tbody id="cards">')
    body += ''.join(x['html'] for x in cards[:20]) + '</tbody></table></div>'
    body += r'''<script>
let page=0,allCards=null;const pageSize=20;
async function showCards(next){try{if(!allCards){const r=await fetch('cards.json?ts='+Date.now());if(!r.ok)throw Error(r.status);allCards=await r.json()}
const q=document.getElementById('search').value.toLowerCase(),g=document.getElementById('grade').value,w=document.getElementById('window').value;
const filtered=allCards.filter(x=>x.search.toLowerCase().includes(q)&&(g==='全部'||x.grade===g)&&(w==='全部'||x.window===w));
page=Math.max(0,Math.min(next,Math.max(0,Math.ceil(filtered.length/pageSize)-1)));
document.getElementById('cards').innerHTML=filtered.slice(page*pageSize,page*pageSize+pageSize).map(x=>x.html).join('')||'<tr><td colspan="12" class="empty">没有符合筛选条件的赛事</td></tr>';
document.getElementById('pageinfo').textContent=`第 ${page+1} / ${Math.max(1,Math.ceil(filtered.length/pageSize))} 页 · ${filtered.length} 场`}
catch(e){document.getElementById('pageinfo').textContent='读取失败，请刷新：'+e.message}}
document.getElementById('pageinfo').textContent=`第 1 / ${Math.max(1,Math.ceil(''' + str(len(cards)) + r'''/pageSize))} 页 · ''' + str(len(cards)) + r''' 场`;
</script>'''
    body += '<h2 class="section-title">系统健康检查</h2><div class="section-note">短样本标记为“样本不足/小样本”，不视为健康通过；单日集中度预警也不等于已经证实长期失效。</div>'
    for key, items in report['health'].items():
        body += ('<details><summary>' + esc(HEALTH_CN.get(key, key)) + '（' + str(len(items)) + ' 项）</summary><div class="detail-body">' +
                 _health_table(items) + '<p class="meta">页面最多展示 30 行；<a href="diagnostics/' + esc(key) + '_health.csv">下载完整检查表</a></p></div></details>')
    (folder / 'index.html').write_text(shell('V4.1 影子模型看板', body), encoding='utf-8')

    body = ('<section class="hero"><h1>原 V4 与 V4.1 同场前瞻对照</h1>'
            '<div class="hero-sub">统一报价、统一 T-30 窗口、不可变赛前决策</div>'
            '<div class="badges"><span class="badge">仅影子观察</span><span class="badge">禁止实盘</span>'
            '<span class="badge">real_money=false</span></div></section>'
            '<nav class="nav"><a href="../">返回 V4.1 今日看板</a><a href="../../v4/">原 V4 影子看板</a>'
            '<a href="../../v3-legacy/">V3 正式决策页</a></nav>'
            '<section class="notice">本页只比较同一场比赛、同一份报价、同一轮 T-30 运行生成的不可变前瞻记录。'
            '原 V4 使用逐字节隔离副本运行，规则保持不变，原 V4 页面和历史记录没有被改写。'
            '统一时间窗口的对照结果不等于原 V4 页面上的全部历史成绩。</section>')

    def model_metrics(name, perf, population='候选'):
        return ('<section class="model-card"><h2>' + esc(name) + '</h2><div class="metrics">' +
                _metric(population, perf['candidates']) + _metric('已结算 / 待结算', f"{perf['settled']} / {perf['pending']}") +
                _metric('红 / 红半 / 走 / 黑半 / 黑', f"{perf['W']} / {perf['HW']} / {perf['P']} / {perf['HL']} / {perf['L']}") +
                _metric('有效胜率', pct(perf['effective_win_rate'])) + _metric('盈亏', f"{perf['PnL']:+.2f}u") +
                _metric('收益率', pct(perf['ROI'])) + '</div></section>')

    body += '<div class="compare-grid">' + model_metrics('原 V4 对照组', comp['overall']['v4']) + model_metrics('V4.1 挑战组', comp['overall']['v41']) + '</div>'
    body += ('<h2 class="section-title">N 不投观察组红黑</h2>'
             '<div class="section-note">N 仍然是不投，不改变赛前等级；这里按冻结候选方向和原盘口计算纸面红黑与模拟盈亏，用于检验模型拒绝是否合理。</div>'
             '<div class="compare-grid">' + model_metrics('原 V4 · N 不投观察', comp['n_observation']['v4'], 'N 样本') +
             model_metrics('V4.1 · N 不投观察', comp['n_observation']['v41'], 'N 样本') + '</div>')
    body += ('<section class="definitions"><b>结算口径：</b> 每个候选按 1 单位计算；收益率分母只包括已经结算的候选；'
             '走盘计入本金，红半/黑半在有效胜率中各按 0.5 场计算。没有已结算样本时，收益率显示为空白。'
             '<br><b>校准指标：</b> 布里尔分数和校准误差越低越好，但小样本阶段不做优劣结论。</section>')

    def perf_table(groups):
        records = []
        for group, models in groups.items():
            for name, perf in models.items():
                records.append({
                    'group': group_cn(group), 'model': group_cn(name), 'candidates': perf['candidates'],
                    'settled': perf['settled'], 'pending': perf['pending'], 'W': perf['W'], 'HW': perf['HW'],
                    'P': perf['P'], 'HL': perf['HL'], 'L': perf['L'], 'win_rate': pct(perf['effective_win_rate']),
                    'PnL': num(perf['PnL']), 'ROI': pct(perf['ROI']), 'max_drawdown': num(perf['max_drawdown']),
                    'Brier': num(perf['calibration']['brier']), 'ECE': pct(perf['calibration']['ece']),
                })
        columns = [('group', '分组'), ('model', '模型'), ('candidates', '候选'), ('settled', '已结算'), ('pending', '待结算'),
                   ('W', '红'), ('HW', '红半'), ('P', '走'), ('HL', '黑半'), ('L', '黑'), ('win_rate', '有效胜率'),
                   ('PnL', '盈亏'), ('ROI', '收益率'), ('max_drawdown', '最大回撤'), ('Brier', '布里尔分数'), ('ECE', '校准误差')]
        return table(records, columns, 'compact')

    body += '<h2 class="section-title">总体对比</h2>' + perf_table({'全部配对': comp['overall']})
    comparison_groups = comp['groups'].get('comparison_group', {})
    body += '<h2 class="section-title">同场入选关系</h2>'
    body += perf_table({group_cn(k): comparison_groups.get(k, {}) for k in ['A_V4_ONLY', 'B_V41_ONLY', 'C_SAME_SIDE', 'D_OPPOSITE_SIDE']})
    dimensions = [
        ('date', '按列表日'), ('handicap', '按盘口'), ('v41_grade', '按 V4.1 等级'), ('v4_grade', '按原 V4 等级'),
        ('time_bucket', '按冻结时间窗口'), ('intent', '按盘口意图'), ('v41_side', '按 V4.1 方向'),
    ]
    for key, label in dimensions:
        groups = comp['groups'].get(key, {})
        body += ('<details><summary>' + esc(label) + '（' + str(len(groups)) + ' 个分组）</summary><div class="detail-body">' +
                 perf_table({group_cn(k): v for k, v in groups.items()}) + '</div></details>')
    body += ('<a class="download" href="../forward_comparison.csv">下载不可变前瞻对照 CSV</a>'
             '<section class="notice">至少积累 200 个 A/B/C 候选，最好达到 500 个以上，并覆盖多个周末、联赛、时段和两个方向，'
             '才适合评估模型差异。当前阶段不能判断 V4.1 优于原 V4。</section>')
    (folder / 'compare/index.html').write_text(shell('原 V4 与 V4.1 同场前瞻对照', body), encoding='utf-8')

    shutil.copy2(ROOT / 'forward/forward_comparison.csv', folder / 'forward_comparison.csv')
    write(folder / 'data.json', report)
    (folder / 'diagnostics').mkdir(exist_ok=True)
    for path in (ROOT / 'diagnostics').glob('*_health.csv'):
        shutil.copy2(path, folder / 'diagnostics' / path.name)
    if (ROOT / 'diagnostics/V41_BUILD_REPORT.md').exists():
        shutil.copy2(ROOT / 'diagnostics/V41_BUILD_REPORT.md', folder / 'V41_BUILD_REPORT.md')
