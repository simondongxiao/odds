"""Build the lightweight, cache-safe GitHub Pages mobile dashboard.

The desktop V3/V4 pages are frozen compatibility views and intentionally keep
their historical payloads.  This builder creates a separate mobile route that
loads a compact, date-scoped projection instead of downloading those 30-50 MB
HTML files.  It never computes or changes a V3/V4 decision.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
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
        # The compact root payload exposes the published V4 grade. A/B is the
        # actionable V4 view; C/N remain research or neutral rows.
        "v4_actionable": v4_grade in {"A", "B"},
    }


def compact_payload(source: dict[str, Any]) -> dict[str, Any]:
    rows = [compact_match(row) for row in source.get("matches", [])]
    grades: dict[str, int] = {}
    for row in rows:
        grade = row["v4"].get("grade") or "缺失"
        grades[grade] = grades.get(grade, 0) + 1
    return {
        "schema_version": "football-mobile-v1",
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


MOBILE_HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><link rel="icon" href="data:,">
<meta name="format-detection" content="telephone=no"><meta http-equiv="Cache-Control" content="no-cache">
<title>足球 V3/V4 手机轻量看板</title>
<style>
:root{color-scheme:light;--blue:#1268a5;--line:#d7e3ec;--muted:#647789;--green:#087a40;--red:#b42318}
*{box-sizing:border-box}body{margin:0;background:#f3f7fb;color:#17324d;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;z-index:5;padding:12px 14px;background:linear-gradient(135deg,#145f98,#1977b4);color:#fff;box-shadow:0 2px 8px #17324d26}
h1{margin:0 0 5px;font-size:19px}.sub{font-size:12px;opacity:.9}.wrap{max-width:760px;margin:auto;padding:9px}
.toolbar,.summary,.card{background:#fff;border:1px solid var(--line);border-radius:10px}.toolbar{padding:9px;display:grid;gap:8px;margin-bottom:8px}.toolbar-row{display:flex;gap:6px;align-items:center}.toolbar input,.toolbar select,.toolbar button{min-height:36px;border:1px solid #b9ccda;border-radius:7px;background:#fff;padding:6px 8px;font:inherit}.toolbar input{flex:1;min-width:0}.toolbar select{flex:1;min-width:0}.toolbar button{color:var(--blue);font-weight:700}.toolbar button.active{color:#fff;background:var(--blue);border-color:var(--blue)}
.summary{padding:9px;margin-bottom:8px;font-size:13px}.summary b{color:var(--blue)}.notice{color:var(--muted);font-size:11px;margin-top:3px}
.card{padding:10px;margin:7px 0}.card-head{display:flex;gap:8px;align-items:flex-start}.teams{font-size:16px;font-weight:750;line-height:1.3;flex:1}.time,.meta{color:var(--muted);font-size:11px}.badge{white-space:nowrap;border-radius:5px;padding:3px 6px;background:#edf2f6;color:#50687a;font-size:11px;font-weight:700}.badge.bet{background:#e4f5ea;color:var(--green)}.badge.warn{background:#fff0ed;color:var(--red)}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin:7px 0}.chip{background:#f1f6fa;border-radius:5px;padding:3px 6px;font-size:11px}.chip.bet{background:#e4f5ea;color:var(--green)}.chip.red{background:#fff0ed;color:var(--red)}.kv{display:grid;grid-template-columns:1fr 1fr;gap:4px 10px;color:#3e5668;font-size:12px}.kv span{overflow-wrap:anywhere}.detail{margin-top:7px;border-top:1px dashed var(--line);padding-top:6px}.detail summary{color:var(--blue);font-weight:700;cursor:pointer}.detail p{margin:5px 0;overflow-wrap:anywhere}.pager{display:flex;gap:7px;align-items:center;justify-content:center;padding:9px 0}.pager button{min-height:34px;border:1px solid #b9ccda;background:#fff;border-radius:7px;padding:5px 11px}.empty,.loading{padding:25px;text-align:center;color:var(--muted)}a{color:#eaf6ff}
@media(min-width:600px){.toolbar{grid-template-columns:1fr 1fr}.toolbar-row{grid-column:1/-1}.card{padding:12px}.kv{grid-template-columns:repeat(3,1fr)}}
</style></head><body><header><div class="wrap"><h1>足球 V3/V4 手机轻量看板</h1><div class="sub" id="updated">正在读取最新版本…</div></div></header>
<main class="wrap"><section class="toolbar"><div class="toolbar-row"><select id="date"></select><input id="search" placeholder="搜索球队、赛事或比赛 ID" autocomplete="off"></div><div class="toolbar-row"><button data-view="all" class="active">全部</button><button data-view="v3">V3 可投</button><button data-view="v4">V4 A/B</button><button data-view="market">有盘口</button></div></section><section class="summary" id="summary">加载中…</section><section id="list"><div class="loading">正在加载赛事…</div></section><div class="pager"><button id="prev">上一页</button><span id="pageinfo"></span><button id="next">下一页</button></div><div class="notice">轻量页只加载当前日期的精简 JSON；历史完整统计、盘口详情和原桌面页仍保留。若手机显示旧内容，请下拉刷新。</div></main>
<script>
const $=s=>document.querySelector(s), q=new URLSearchParams(location.search), defaultView=q.get('view')||'all';
const state={view:defaultView,date:q.get('date')||'',page:0,size:30,rows:[],manifest:{},current:{}};
const esc=x=>String(x??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
async function getJson(path,version){const sep=path.includes('?')?'&':'?';const r=await fetch(path+sep+'v='+encodeURIComponent(version||Date.now()),{cache:'no-store'});if(!r.ok)throw Error(r.status);return r.json()}
function label(v){return v||'待核'}
function filtered(){const s=$('#search').value.trim().toLowerCase();return state.rows.filter(x=>{const hay=[x.id,x.competition,x.home,x.away].join(' ').toLowerCase();if(s&&!hay.includes(s))return false;if(state.view==='v3'&&!x.v3_actionable)return false;if(state.view==='v4'&&!x.v4_actionable)return false;if(state.view==='market'&&!((x.market.line||'')||(x.market.euro||'')))return false;return true})}
function card(x){const v3=x.v3,v4=x.v4,m=x.market;const bet=x.v3_actionable||x.v4_actionable;const status=x.state||'待核';return `<article class="card"><div class="card-head"><div class="teams">${esc(x.home)} <span class="meta">vs</span> ${esc(x.away)}<div class="time">${esc(x.time)} · ${esc(x.competition)}</div></div><span class="badge ${bet?'bet':''}">${bet?'有候选':esc(status)}</span></div><div class="chips"><span class="chip ${x.v3_actionable?'bet':''}">V3：${esc(label(v3.action))}</span><span class="chip ${x.v4_actionable?'bet':''}">V4：${esc(label(v4.grade||v4.status))}</span>${x.settlement.result?`<span class="chip">赛果：${esc(x.settlement.result)}</span>`:''}${x.settlement.pnl!==''&&x.settlement.pnl!=null?`<span class="chip">PnL：${esc(x.settlement.pnl)}U</span>`:''}</div><div class="kv"><span>盘口：${esc(label(m.line))}</span><span>水位：${esc(label(m.water))}</span><span>欧赔：${esc(label(m.euro))}</span><span>V3方向：${esc(label(v3.team||v3.side))}</span><span>V4方向：${esc(label(v4.team||v4.side))}</span><span>数据：${esc(label(x.data_status))}</span></div><details class="detail"><summary>展开决策原因</summary><p><b>V3：</b>${esc(label(v3.reason))}</p><p><b>V4：</b>${esc(label(v4.status))}；EV ${esc(label(v4.ev))}；P(EV&gt;0) ${esc(label(v4.p_ev))}</p><p class="meta">match_id：${esc(x.id)} · run：${esc(state.current.run_id||'')}</p></details></article>`}
function render(){const a=filtered(),pages=Math.max(1,Math.ceil(a.length/state.size));state.page=Math.min(state.page,pages-1);const slice=a.slice(state.page*state.size,(state.page+1)*state.size);$('#list').innerHTML=slice.length?slice.map(card).join(''):'<div class="empty">没有符合条件的比赛</div>';$('#pageinfo').textContent=`${state.page+1}/${pages} · ${a.length} 场`;$('#prev').disabled=state.page<=0;$('#next').disabled=state.page>=pages-1}
async function loadDate(date){const meta=state.manifest[date];if(!meta)throw Error('日期数据不存在');state.date=date;state.rows=(await getJson('./mobile-data/'+date+'.json',meta.version)).matches||[];$('#date').value=date;state.page=0;render();const s=meta.summary||{};$('#summary').innerHTML=`列表日 <b>${esc(date)}</b>　总计 <b>${s.total||state.rows.length}</b> 场　V3可投 <b>${s.v3_bettable||0}</b>　V4 A/B <b>${s.v4_bettable||0}</b>　有盘口 <b>${s.with_market||0}</b>`}
async function start(){const current=await getJson('./data/current.json');state.current=current;const manifest=await getJson('./mobile-data/manifest.json');state.manifest=manifest.dates||{};const dates=Object.keys(state.manifest).sort().reverse();$('#date').innerHTML=dates.map(d=>`<option value="${esc(d)}">${esc(d)}</option>`).join('');const date=state.date&&state.manifest[state.date]?state.date:(current.list_date||dates[0]);$('#updated').textContent=`版本：${current.run_id||'未知'} · 更新：${current.generated_at||'未知'} · 手机缓存已按版本刷新`;document.querySelectorAll('[data-view]').forEach(b=>{b.classList.toggle('active',b.dataset.view===state.view);b.onclick=()=>{state.view=b.dataset.view;state.page=0;document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('active',x===b));render()}});$('#date').onchange=e=>loadDate(e.target.value).catch(err=>$('#list').innerHTML=`<div class="empty">加载失败：${esc(err)}</div>`);$('#search').oninput=()=>{state.page=0;render()};$('#prev').onclick=()=>{if(state.page>0){state.page--;render()}};$('#next').onclick=()=>{state.page++;render()};await loadDate(date)}start().catch(e=>{$('#updated').textContent='数据加载失败，请刷新';$('#list').innerHTML=`<div class="empty">${esc(e)}</div>`});
</script></body></html>'''


REDIRECT_HTML = r'''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>手机轻量看板</title><script>const q=location.search.replace(/^\?/,"");location.replace("../mobile.html?view=__VIEW__"+(q?"&"+q:""));</script><p>正在打开手机轻量看板…</p>'''


def build(publish_root: Path) -> dict[str, Any]:
    source_dir = publish_root / "data" / "dates"
    mobile_dir = publish_root / "mobile-data"
    mobile_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {}
    for source in sorted(source_dir.glob("*.json")):
        if source.stem in {"index", "current"}:
            continue
        try:
            payload = compact_payload(read_json(source))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        target = mobile_dir / source.name
        atomic_json(target, payload)
        manifest[payload["list_date"]] = {
            "file": f"./mobile-data/{target.name}",
            "version": payload.get("run_id") or payload.get("generated_at") or payload["list_date"],
            "summary": payload["summary"],
            "bytes": target.stat().st_size,
        }
    atomic_json(mobile_dir / "manifest.json", {
        "schema_version": "football-mobile-v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "dates": manifest,
    })
    (publish_root / "mobile.html").write_text(MOBILE_HTML, encoding="utf-8")
    for folder, view in (("v3-legacy", "v3"), ("v4", "v4")):
        path = publish_root / folder / "mobile.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(REDIRECT_HTML.replace("__VIEW__", view), encoding="utf-8")
    return {"dates": len(manifest), "mobile_bytes": sum(int(v["bytes"]) for v in manifest.values()), "entry_bytes": (publish_root / "mobile.html").stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish-root", required=True, type=Path)
    args = parser.parse_args()
    result = build(args.publish_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
