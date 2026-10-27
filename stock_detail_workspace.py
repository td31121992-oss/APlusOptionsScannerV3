"""Unified per-stock workspace: chart, technical/stock analysis, and contextual panels."""
from __future__ import annotations
from html import escape
from urllib.parse import parse_qs

def parse_query(raw: str) -> dict[str, str]:
    if "?" not in raw: return {}
    return {k:(v[0] if v else "") for k,v in parse_qs(raw.split("?",1)[1]).items()}

STOCK_DETAIL_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>APlus Stock Workspace</title>
<style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--green:#17c964;--cyan:#22d3ee}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px Segoe UI,Arial,sans-serif}
header{position:sticky;top:0;z-index:5;background:#10182a;border-bottom:1px solid var(--line);padding:12px 18px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
h1{font-size:22px;margin:0}.muted{color:var(--muted);font-size:12px}.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
input,button,a.pill{background:var(--panel);border:1px solid var(--line);color:var(--text);border-radius:8px;padding:8px 11px;text-decoration:none}
button{cursor:pointer;font-weight:700}.layout{padding:12px;display:grid;grid-template-columns:minmax(0,1.5fr) minmax(360px,1fr);gap:12px}
.panel{min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.panel h2{font-size:14px;margin:0;padding:11px 13px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between}
iframe{width:100%;border:0;background:var(--bg);display:block}.chartFrame{height:690px}.analysisFrame{height:690px}
.lower{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;padding:0 12px 12px}
.widget{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px;min-height:130px}
.widget h3{font-size:13px;margin:0 0 8px}.data{white-space:pre-wrap;color:var(--muted);font-size:12px;line-height:1.5;overflow-wrap:anywhere}
.status{color:var(--muted);font-size:12px}
@media(max-width:1000px){.layout{grid-template-columns:1fr}.chartFrame{height:500px}.analysisFrame{height:650px}.lower{grid-template-columns:1fr}}
</style></head><body>
<header><div><h1 id="heading">Stock Workspace</h1><div class="muted">Unified view • chart + stock analysis + supporting context • read-only</div></div>
<div class="toolbar"><input id="symbol" placeholder="Stock symbol" value="MANKIND"><button id="open">Open stock</button><a class="pill" href="/">Dashboard</a><a class="pill" href="/orderflow-profile">Order Flow / Volume Profile</a><span class="status" id="status">Loading…</span></div></header>
<main class="layout">
<section class="panel"><h2><span>Intraday chart & levels</span><span class="muted">existing chart engine</span></h2><iframe id="chart" class="chartFrame" title="Stock intraday chart"></iframe></section>
<section class="panel"><h2><span>Stock analysis</span><span class="muted">technical • order flow • why moving</span></h2><iframe id="analysis" class="analysisFrame" title="Stock analysis"></iframe></section>
</main>
<section class="lower">
<div class="widget"><h3>Stock trend</h3><div class="data" id="trend">Loading…</div></div>
<div class="widget"><h3>Why is it moving?</h3><div class="data" id="why">Loading…</div></div>
<div class="widget"><h3>Catalyst / event context</h3><div class="data" id="catalyst">Loading…</div></div>
</section>
<script>
const $=s=>document.querySelector(s);
function symbolNow(){return ($('#symbol').value||'').trim().toUpperCase().replace(/[^A-Z0-9&_-]/g,'')}
function showData(id,obj){$(id).textContent=JSON.stringify(obj,null,2)}
async function loadPanel(url,id){try{let r=await fetch(url+'&ts='+Date.now(),{cache:'no-store'});let j=await r.json();showData(id,j)}catch(e){showData(id,{ok:false,error:'Data unavailable',detail:String(e)})}}
function openStock(){let s=symbolNow();if(!s)return;history.replaceState(null,'','/stock-detail?symbol='+encodeURIComponent(s));$('#heading').textContent=s+' — Stock Workspace';$('#status').textContent='Loading '+s+'…';$('#chart').src='/stock-chart?symbol='+encodeURIComponent(s);$('#analysis').src='/stock-analysis?symbol='+encodeURIComponent(s);loadPanel('/api/stock-trend?symbol='+encodeURIComponent(s),'#trend');loadPanel('/api/why-moving?symbol='+encodeURIComponent(s),'#why');loadPanel('/api/catalyst?symbol='+encodeURIComponent(s),'#catalyst');$('#status').textContent='Loaded '+s}
$('#open').addEventListener('click',openStock);$('#symbol').addEventListener('keydown',e=>{if(e.key==='Enter')openStock()});
const initial=new URLSearchParams(location.search).get('symbol');if(initial)$('#symbol').value=initial;openStock();
</script></body></html>"""
