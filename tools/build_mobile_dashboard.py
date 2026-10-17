"""Build the shared responsive V3/V4 GitHub Pages dashboard.

The public V3/V4 URLs are the canonical pages. This builder keeps those same
URLs and renders a desktop table or a mobile card list from the same compact,
date-scoped JSON. It does not calculate or alter any V3/V4 decision.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def compact_match(row: dict[str, Any]) -> dict[str, Any]:
    identity = row.get("identity") or {}
    market = row.get("market") or {}
    v3 = row.get("v3_decision") or {}
    v4 = row.get("v4_shadow") or {}
    settlement = row.get("settlement") or {}
    audit = row.get("audit") or {}
    v3_action = str(v3.get("action") or v3.get("status") or "")
    v4_status = str(v4.get("status") or "")
    v4_grade = str(v4.get("grade") or "")
    return {
        "id": str(identity.get("match_id") or row.get("match_id") or ""),
        "time": identity.get("kickoff", ""),
        "competition": identity.get("competition", ""),
        "home": identity.get("home", ""),
        "away": identity.get("away", ""),
        "market": {
            "line": market.get("line_bucket", ""),
            "side": market.get("candidate_side", ""),
            "team": market.get("candidate_team", ""),
            "water": market.get("water", ""),
            "giving": market.get("giving_team", ""),
            "receiving": market.get("receiving_team", ""),
            "giving_water": market.get("giving_water", ""),
            "receiving_water": market.get("receiving_water", ""),
            "euro": market.get("euro_current", ""),
        },
        "v3": {
            "action": v3_action,
            "team": v3.get("team", ""),
            "side": v3.get("side", ""),
            "line": v3.get("line", ""),
            "water": v3.get("water", ""),
            "probability": v3.get("probability", ""),
            "reason": v3.get("reason", ""),
        },
        "v4": {
            "grade": v4_grade,
            "status": v4_status,
            "team": v4.get("team", ""),
            "side": v4.get("side", ""),
            "ev": v4.get("ev_mean", ""),
            "p_ev": v4.get("p_ev_gt_0", ""),
            "real_money": bool(v4.get("real_money", False)),
        },
        "settlement": {
            "result": settlement.get("result", ""),
            "pnl": settlement.get("pnl_1u", ""),
        },
        "state": audit.get("state", ""),
        "data_status": audit.get("data_status", ""),
        "v3_actionable": v3_action in {"可投", "半仓可投", "BET_GIVING", "BET_RECEIVING"},
        "v4_actionable": v4_grade in {"A", "B"},
    }


def compact_payload(source: dict[str, Any]) -> dict[str, Any]:
    rows = [compact_match(row) for row in source.get("matches", [])]
    grades: dict[str, int] = {}
    for row in rows:
        grade = row["v4"].get("grade") or "缺失"
        grades[grade] = grades.get(grade, 0) + 1
    return {
        "schema_version": "football-dashboard-compact-v2",
        "list_date": source.get("list_date", ""),
        "run_id": source.get("run_id", ""),
        "generated_at": source.get("generated_at", ""),
        "summary": {
            "total": len(rows),
            "v3_bettable": sum(row["v3_actionable"] for row in rows),
            "v4_bettable": sum(row["v4_actionable"] for row in rows),
            "with_market": sum(bool(row["market"].get("line") or row["market"].get("euro")) for row in rows),
            "grades": grades,
        },
        "matches": rows,
    }


RESPONSIVE_HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="format-detection" content="telephone=no"><meta http-equiv="Cache-Control" content="no-cache"><link rel="icon" href="data:,"><title>__TITLE__</title>
<style>
:root{color-scheme:light;--blue:#1767a5;--page:#eef5fb;--line:#c8dbe9;--muted:#60778b;--green:#087a40;--red:#b42318;--amber:#995c00}*{box-sizing:border-box}body{margin:0;background:var(--page);color:#17324d;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei","PingFang SC",Arial,sans-serif}.wrap{max-width:1680px;margin:auto;padding:12px}.hero{background:linear-gradient(135deg,#145f98,#1977b4);color:#fff;padding:16px 20px;border-radius:4px}.hero h1{margin:0 0 5px;font-size:24px}.hero .sub{font-size:12px;opacity:.92}.archive{float:right;color:#eaf6ff;font-size:12px}.panel{background:#fff;border:1px solid var(--line);margin-top:9px}.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:9px;background:#eaf3fa}.toolbar select,.toolbar input,.toolbar button{min-height:34px;border:1px solid #a8c3d6;border-radius:5px;background:#fff;padding:6px 9px;font:inherit}.toolbar select{min-width:135px}.toolbar input{flex:1;min-width:180px}.toolbar button{color:var(--blue);font-weight:700;cursor:pointer}.toolbar button.active{color:#fff;background:var(--blue);border-color:var(--blue)}.summary{padding:9px 12px;border-left:4px solid var(--blue);line-height:1.65}.summary b{color:var(--blue)}.notice{padding:7px 12px;color:var(--muted);font-size:12px;border-top:1px solid var(--line)}.table-wrap{overflow:auto;-webkit-overflow-scrolling:touch}.desktop-table{width:100%;min-width:1120px;border-collapse:collapse}.desktop-table th{background:#dcecf8;position:sticky;top:0;z-index:1;text-align:left}.desktop-table th,.desktop-table td{border:1px solid #d3e1eb;padding:7px 8px;vertical-align:top}.desktop-table tr:nth-child(even){background:#f8fbfd}.desktop-table .match{font-weight:700;min-width:195px}.desktop-table .time{white-space:nowrap;color:#315b7e}.desktop-table .market{min-width:180px;white-space:normal}.desktop-table .decision{min-width:160px;white-space:normal}.desktop-table .settle{min-width:90px;white-space:normal}.ok{color:var(--green);font-weight:700}.bad{color:var(--red);font-weight:700}.muted{color:var(--muted)}.warn{color:var(--amber)}small{display:block}.mobile-list{display:none}.card{background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px;margin:7px 0}.card-head{display:flex;gap:8px;align-items:flex-start}.teams{font-size:16px;font-weight:750;line-height:1.3;flex:1}.time,.meta{color:var(--muted);font-size:11px}.badge{white-space:nowrap;border-radius:5px;padding:3px 6px;background:#edf2f6;color:#50687a;font-size:11px;font-weight:700}.badge.bet{background:#e4f5ea;color:var(--green)}.chips{display:flex;flex-wrap:wrap;gap:4px;margin:7px 0}.chip{background:#f1f6fa;border-radius:5px;padding:3px 6px;font-size:11px}.chip.bet{background:#e4f5ea;color:var(--green)}.kv{display:grid;grid-template-columns:1fr 1fr;gap:4px 10px;color:#3e5668;font-size:12px}.kv span{overflow-wrap:anywhere}.detail{margin-top:7px;border-top:1px dashed var(--line);padding-top:6px}.detail summary{color:var(--blue);font-weight:700;cursor:pointer}.detail p{margin:5px 0;overflow-wrap:anywhere}.pager{display:flex;gap:8px;align-items:center;justify-content:center;padding:10px}.pager button{min-height:34px;border:1px solid #a8c3d6;background:#fff;border-radius:5px;padding:5px 11px}.empty,.loading{padding:28px;text-align:center;color:var(--muted)}
@media(max-width:720px){body{font-size:13px}.wrap{padding:6px}.hero{padding:12px}.hero h1{font-size:20px}.archive{float:none;display:block;margin-top:5px}.toolbar{display:grid;grid-template-columns:1fr 1fr;gap:7px}.toolbar select,.toolbar input{width:100%;min-width:0}.toolbar input{grid-column:1/-1}.toolbar button{min-width:0}.summary{font-size:12px;padding:8px}.notice{font-size:11px}.desktop-table{display:none}.mobile-list{display:block}.pager{font-size:12px}}
@media(min-width:721px){.pager{display:none}}
</style></head><body><div class="wrap"><header class="hero"><a class="archive" href="./index-legacy.html">完整旧版/历史统计</a><h1>__TITLE__</h1><div class="sub" id="updated">正在读取最新版本…</div></header><section class="panel"><div class="toolbar"><select id="date"></select><input id="search" placeholder="搜索球队、赛事或比赛 ID" autocomplete="off"><button data-view="all" class="active">全部赛事</button><button data-view="actionable">__ACTION_LABEL__</button><button data-view="market">有盘口</button><button data-view="settled">已结算</button></div><div class="summary" id="summary">加载中…</div><div class="notice">同一地址自适应电脑和手机；数据按列表日和运行版本加载，手机端不会下载原版数十 MB 页面。V3 为 Production，V4 为 Shadow。</div><div id="content"><div class="loading">正在加载赛事…</div></div><div class="pager"><button id="prev">上一页</button><span id="pageinfo"></span><button id="next">下一页</button></div></section></div>
<script>
const MODE='__VIEW__',BASE='__BASE__',q=new URLSearchParams(location.search),$=s=>document.querySelector(s),state={view:q.get('view')||'all',date:q.get('date')||'',page:0,size:40,rows:[],manifest:{},current:{}};
const esc=x=>String(x??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const val=x=>(x===null||x===undefined||x==='')?'待核':x;
async function getJson(path,version){const sep=path.includes('?')?'&':'?';const r=await fetch(path+sep+'v='+encodeURIComponent(version||Date.now()),{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);return r.json()}
function matches(){const s=$('#search').value.trim().toLowerCase();return state.rows.filter(x=>{const hay=[x.id,x.competition,x.home,x.away].join(' ').toLowerCase();if(s&&!hay.includes(s))return false;if(state.view==='actionable'&&!(MODE==='v3'?x.v3_actionable:x.v4_actionable))return false;if(state.view==='market'&&!((x.market.line||'')||(x.market.euro||'')))return false;if(state.view==='settled'){const result=String((x.settlement||{}).result||'');if(!result||['待结算','待核','未结算','进行中'].includes(result))return false}return true})}
function marketText(x){const m=x.market||{};const first=[m.line,m.side,m.team,m.water].filter(v=>v!==''&&v!==null&&v!==undefined).join(' / ');const sides=[m.giving,m.receiving].filter(Boolean).join(' / ');const waters=[m.giving_water,m.receiving_water].filter(v=>v!==''&&v!==null&&v!==undefined).join(' / ');return `<div>盘口：${esc(first||'待核')}</div><div class="muted">让球方：${esc(sides||'待核')}　水位：${esc(waters||m.water||'待核')}</div><div class="muted">欧赔：${esc(m.euro||'待核')}</div>`}
function v3Text(x){const v=x.v3||{},ok=x.v3_actionable;return `<span class="${ok?'ok':'bad'}">${esc(val(v.action))}</span><br><span>${esc(v.team||v.side||'')}</span>${v.reason?`<small class="muted">${esc(v.reason)}</small>`:''}`}
function v4Text(x){const v=x.v4||{},ok=x.v4_actionable;return `<span class="${ok?'ok':'warn'}">${esc(v.grade||v.status||'待核')}</span><br><span>${esc(v.team||v.side||'')}</span>${v.ev!==''&&v.ev!==null&&v.ev!==undefined?`<small class="muted">EV ${esc(v.ev)}；P ${esc(v.p_ev)}</small>`:''}`}
function settleText(x){const s=x.settlement||{};return `<span>${esc(s.result||'待结算')}</span>${s.pnl!==''&&s.pnl!==null&&s.pnl!==undefined?`<br><span class="${Number(s.pnl)>=0?'ok':'bad'}">PnL ${esc(s.pnl)}U</span>`:''}`}
function tableRow(x){return `<tr><td class="time">${esc(x.time)}</td><td>${esc(x.competition||'待核')}<br><span class="muted">${esc(x.state||'待核')}</span></td><td class="match">${esc(x.home)} <span class="muted">vs</span> ${esc(x.away)}<br><span class="muted">ID ${esc(x.id)}</span></td><td class="market">${marketText(x)}</td><td class="decision">${v3Text(x)}</td><td class="decision">${v4Text(x)}</td><td class="settle">${settleText(x)}</td><td>${esc(x.data_status||'待核')}</td></tr>`}
function card(x){const v3=x.v3||{},v4=x.v4||{},m=x.market||{},bet=x.v3_actionable||x.v4_actionable;return `<article class="card"><div class="card-head"><div class="teams">${esc(x.home)} <span class="meta">vs</span> ${esc(x.away)}<div class="time">${esc(x.time)} · ${esc(x.competition||'待核')}</div></div><span class="badge ${bet?'bet':''}">${bet?'可投候选':esc(x.state||'待核')}</span></div><div class="chips"><span class="chip ${x.v3_actionable?'bet':''}">V3：${esc(val(v3.action))}</span><span class="chip ${x.v4_actionable?'bet':''}">V4：${esc(val(v4.grade||v4.status))}</span>${x.settlement&&x.settlement.result?`<span class="chip">赛果：${esc(x.settlement.result)}</span>`:''}${x.settlement&&x.settlement.pnl!==''&&x.settlement.pnl!==null&&x.settlement.pnl!==undefined?`<span class="chip">PnL：${esc(x.settlement.pnl)}U</span>`:''}</div><div class="kv"><span>盘口：${esc(val(m.line))}</span><span>水位：${esc(val(m.water))}</span><span>欧赔：${esc(val(m.euro))}</span><span>V3方向：${esc(val(v3.team||v3.side))}</span><span>V4方向：${esc(val(v4.team||v4.side))}</span><span>数据：${esc(val(x.data_status))}</span></div><details class="detail"><summary>展开决策原因</summary><p><b>V3：</b>${esc(val(v3.reason))}</p><p><b>V4：</b>${esc(val(v4.status))}；EV ${esc(val(v4.ev))}；P(EV&gt;0) ${esc(val(v4.p_ev))}</p><p class="meta">match_id：${esc(x.id)} · run：${esc(state.current.run_id||'')}</p></details></article>`}
function render(){const a=matches(),mobile=innerWidth<=720,size=mobile?state.size:Math.max(a.length,1),pages=Math.max(1,Math.ceil(a.length/size));state.page=Math.min(state.page,pages-1);const slice=mobile?a.slice(state.page*size,(state.page+1)*size):a;$('#content').innerHTML=`<div class="table-wrap"><table class="desktop-table"><thead><tr><th>北京时间</th><th>赛事/状态</th><th>比赛</th><th>盘口与赔率</th><th>V3决策</th><th>V4决策</th><th>赛果/盈亏</th><th>数据状态</th></tr></thead><tbody>${slice.map(tableRow).join('')||'<tr><td colspan="8" class="empty">没有符合条件的比赛</td></tr>'}</tbody></table><div class="mobile-list">${slice.map(card).join('')||'<div class="empty">没有符合条件的比赛</div>'}</div></div>`;$('#pageinfo').textContent=`${state.page+1}/${pages} · ${a.length} 场`;$('#prev').disabled=state.page<=0;$('#next').disabled=state.page>=pages-1}
async function loadDate(date){const meta=state.manifest[date];if(!meta)throw Error('日期数据不存在');state.date=date;state.rows=(await getJson(BASE+'mobile-data/'+date+'.json',meta.version)).matches||[];$('#date').value=date;state.page=0;render();const s=meta.summary||{};$('#summary').innerHTML=`列表日 <b>${esc(date)}</b>　总计 <b>${s.total||state.rows.length}</b> 场　V3可投 <b>${s.v3_bettable||0}</b>　V4 A/B <b>${s.v4_bettable||0}</b>　有盘口 <b>${s.with_market||0}</b>`}
async function start(){state.current=await getJson(BASE+'data/current.json');const m=await getJson(BASE+'mobile-data/manifest.json');state.manifest=m.dates||{};const dates=Object.keys(state.manifest).sort().reverse();$('#date').innerHTML=dates.map(d=>`<option value="${esc(d)}">${esc(d)}</option>`).join('');const date=state.date&&state.manifest[state.date]?state.date:(state.current.list_date||dates[0]);$('#updated').textContent=`版本：${state.current.run_id||'未知'} · 更新：${state.current.generated_at||'未知'} · 数据按版本刷新`;document.querySelectorAll('[data-view]').forEach(b=>{b.classList.toggle('active',b.dataset.view===state.view);b.onclick=()=>{state.view=b.dataset.view;state.page=0;document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('active',x===b));render()}});$('#date').onchange=e=>loadDate(e.target.value).catch(showError);$('#search').oninput=()=>{state.page=0;render()};$('#prev').onclick=()=>{if(state.page>0){state.page--;render()}};$('#next').onclick=()=>{state.page++;render()};await loadDate(date)}
window.addEventListener('resize',()=>{state.page=0;render()});
function showError(e){$('#updated').textContent='数据加载失败，请刷新';$('#content').innerHTML=`<div class="empty">${esc(e)}</div>`}start().catch(showError);
</script></body></html>'''


def render_html(view: str) -> str:
    title = "V3 足球盘口云端看板" if view == "v3" else "V4 足球盘口 Shadow 看板"
    action = "V3 可投" if view == "v3" else "V4 A/B"
    return RESPONSIVE_HTML.replace("__VIEW__", view).replace("__TITLE__", title).replace("__ACTION_LABEL__", action).replace("__BASE__", "../")


def build(publish_root: Path) -> dict[str, Any]:
    source_dir = publish_root / "data" / "dates"
    compact_dir = publish_root / "mobile-data"
    compact_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {}
    for source in sorted(source_dir.glob("*.json")):
        if source.stem in {"index", "current"}:
            continue
        try:
            payload = compact_payload(read_json(source))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        target = compact_dir / source.name
        atomic_json(target, payload)
        manifest[payload["list_date"]] = {"file": f"./mobile-data/{target.name}", "version": payload.get("run_id") or payload.get("generated_at") or payload["list_date"], "summary": payload["summary"], "bytes": target.stat().st_size}
    atomic_json(compact_dir / "manifest.json", {"schema_version": "football-dashboard-compact-v2", "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "dates": manifest})
    archived: dict[str, int] = {}
    for folder, view in (("v3-legacy", "v3"), ("v4", "v4")):
        path = publish_root / folder / "index.html"
        if path.exists() and path.stat().st_size > 1_000_000:
            archive = path.with_name("index-legacy.html")
            shutil.copy2(path, archive)
            archived[folder] = archive.stat().st_size
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_html(view), encoding="utf-8")
    # Old mobile bookmarks remain usable as aliases to the canonical pages.
    (publish_root / "mobile.html").write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><script>location.replace("./v4/"+location.search)</script>', encoding="utf-8")
    for folder in ("v3-legacy", "v4"):
        p = publish_root / folder / "mobile.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('<!doctype html><meta charset="utf-8"><script>location.replace("./"+location.search)</script>', encoding="utf-8")
    return {"dates": len(manifest), "compact_bytes": sum(int(v["bytes"]) for v in manifest.values()), "v3_html_bytes": (publish_root / "v3-legacy" / "index.html").stat().st_size, "v4_html_bytes": (publish_root / "v4" / "index.html").stat().st_size, "archived": archived}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish-root", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.publish_root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




