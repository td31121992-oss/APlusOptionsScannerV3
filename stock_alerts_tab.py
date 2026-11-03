from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from stock_alerts import evaluate_rows, rule_catalog

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "data" / "reports"


def _load_rows() -> list[dict[str, Any]]:
    path = REPORTS / "fno_market_watch_latest.json"
    if not path.is_file():
        return []
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        rows = obj.get("rows") if isinstance(obj, dict) else []
        rows = [x for x in rows if isinstance(x, dict)]
        try:                      # add the daily-indicator fields (breakouts, averages, supertrend); alerts stay safe without them
            from daily_indicators import enrich_rows, load_indicators

            indicators = load_indicators()
            rows = enrich_rows(rows, indicators)
            from intraday_signals import enrich_intraday, load_book_stats

            rows = enrich_intraday(rows, load_book_stats(), indicators)
        except Exception:         # noqa: BLE001
            pass
        return rows
    except Exception:
        return []


def stock_alerts_payload() -> dict[str, Any]:
    rows = _load_rows()
    return {
        "ok": True,
        "generated_at": datetime.now().isoformat(),
        "rows_count": len(rows),
        "rules": rule_catalog(rows),
        "alerts": evaluate_rows(rows),
        "browser_only": True,
        "telegram_policy": "Trade Taken and Trade Closed only",
        "read_only": True,
        "trading_engine_untouched": True,
    }


STOCK_ALERTS_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>APlus Stock Alerts</title>
<style>
:root{--bg:#fff;--panel:#fff;--soft:#f4f7fb;--line:#d8dee8;--text:#111827;--muted:#667085;--on:#14b8a6;--warn:#f59e0b;--red:#ef4444;--blue:#2563eb}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}
.nav{display:flex;gap:10px;padding:12px 24px;border-bottom:1px solid var(--line);overflow:auto;white-space:nowrap}
.nav a{color:#111827;text-decoration:none;font-weight:700;font-size:13px;padding:7px 12px;border-radius:9px}.nav a.active{background:#14b8a6;color:white}
.header{padding:20px 26px 12px}.title{font-size:24px;font-weight:800}.sub{font-size:12px;color:var(--muted);margin-top:5px}
.banner{margin:0 26px 12px;padding:12px 14px;background:#eef5ff;border:1px solid #cbd9ef;border-radius:8px}
.toolbar{display:flex;gap:9px;align-items:center;flex-wrap:wrap;padding:10px 26px}.toolbar button{border:1px solid var(--line);background:white;border-radius:8px;padding:8px 12px;font-weight:700;cursor:pointer}.toolbar button.active{background:#14b8a6;color:white;border-color:#14b8a6}
.panel{margin:0 26px 12px;border:1px solid var(--line);border-radius:10px;overflow:hidden}.paneltitle{padding:12px 15px;font-size:16px;font-weight:800;background:#fafbfc;border-bottom:1px solid var(--line)}
.rule{display:grid;grid-template-columns:minmax(260px,1fr) 90px 90px 110px;align-items:center;gap:12px;padding:9px 15px;border-bottom:1px solid #edf0f4}.rule:last-child{border-bottom:0}
.category{font-weight:800;margin-top:8px;padding:8px 15px;background:#fbfcfe}.rulelabel{font-size:14px}.unavailable{font-size:11px;color:var(--muted)}
.switch{width:34px;height:20px;border-radius:20px;background:#cbd5e1;position:relative;cursor:pointer;display:inline-block}.switch:after{content:"";position:absolute;width:16px;height:16px;top:2px;left:2px;background:white;border-radius:50%;transition:.15s}.switch.on{background:var(--on)}.switch.on:after{left:16px}
.status{font-size:11px;color:var(--muted)}.sound{font-size:12px}.badge{display:inline-block;padding:3px 7px;border-radius:999px;font-size:10px;font-weight:800;background:#edf2f7;color:#475467}
.alertrow{display:grid;grid-template-columns:95px 130px 1fr 90px 100px;gap:10px;padding:9px 15px;border-bottom:1px solid #edf0f4;align-items:center}.up{color:#059669;font-weight:800}.down{color:#dc2626;font-weight:800}
.tablewrap{overflow:auto}.empty{padding:18px;color:var(--muted)}
@media(max-width:760px){.header,.toolbar{padding-left:12px;padding-right:12px}.panel,.banner{margin-left:12px;margin-right:12px}.rule{grid-template-columns:1fr 55px 55px}.status{grid-column:1/-1}.alertrow{grid-template-columns:80px 110px 1fr}.alertrow>*:nth-child(n+4){display:none}}
</style></head>
<body>
<div class="nav">
<a href="/">LIVE TRADING</a><a href="/fno-market-watch">F&amp;O MARKET WATCH</a><a href="/stock-analysis">STOCK ANALYSIS</a>
<a class="active" href="/alerts">ALERTS</a><a href="/sector-performance">SECTOR PERFORMANCE</a><a href="/opening-structure">OPENING STRUCTURE</a><a href="/stock-charts">STOCK CHARTS</a>
</div>
<div class="header"><div class="title">My Alerts</div><div class="sub" id="updated">Waiting for market data...</div></div>
<div class="banner"><b>Browser alerts only.</b> Stock alerts never go to Telegram. Telegram remains reserved for <b>Trade Taken</b> and <b>Trade Closed</b> events.</div>
<div class="toolbar">
<button id="allAlert" class="active" onclick="setAll(true)">All Alerts ON</button>
<button onclick="setAll(false)">All Alerts OFF</button>
<button id="soundBtn" onclick="toggleSound()">Sound: ON</button>
<button onclick="testSound()">Test Sound</button>
<button onclick="clearHistory()">Clear Alert History</button>
<span class="sub" id="soundHelp">First sound test/click may be required by browser autoplay rules.</span>
</div>
<div class="panel"><div class="paneltitle">Alert Settings</div><div id="rules"></div></div>
<div class="panel"><div class="paneltitle">Triggered Stock Alerts <span class="sub">No Telegram for these alerts</span></div>
<div class="tablewrap"><div id="alerts"></div></div></div>
<script>
const KEY="aplus.stockAlerts.v1",HKEY="aplus.stockAlertHistory.v1";
const defaults={all:true,sound:true,rules:{}};
let cfg=loadCfg(),lastActive=new Set(),audioCtx=null,lastPayload=null;
const esc=v=>String(v??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));
function loadCfg(){try{return {...defaults,...JSON.parse(localStorage.getItem(KEY)||"{}")}}catch{return {...defaults}}}
function saveCfg(){localStorage.setItem(KEY,JSON.stringify(cfg))}
function ruleOn(id){return cfg.all && cfg.rules[id]!==false}
function setAll(v){cfg.all=v;saveCfg();renderRules();process(lastPayload||{alerts:[]})}
function toggleRule(id){cfg.rules[id]=!ruleOn(id);saveCfg();renderRules()}
function toggleSound(){cfg.sound=!cfg.sound;saveCfg();renderControls();if(cfg.sound)testSound()}
function renderControls(){document.getElementById("soundBtn").textContent="Sound: "+(cfg.sound?"ON":"OFF");document.getElementById("allAlert").classList.toggle("active",cfg.all)}
function beep(){if(!cfg.sound)return;try{audioCtx=audioCtx||new (window.AudioContext||window.webkitAudioContext)();const o=audioCtx.createOscillator(),g=audioCtx.createGain();o.frequency.value=880;g.gain.value=.06;o.connect(g);g.connect(audioCtx.destination);o.start();g.gain.exponentialRampToValueAtTime(.001,audioCtx.currentTime+.45);o.stop(audioCtx.currentTime+.5)}catch{}}
function testSound(){if(!audioCtx)try{audioCtx=new (window.AudioContext||window.webkitAudioContext)()}catch{};beep()}
function renderRules(){if(!lastPayload)return;const by={};for(const r of lastPayload.rules||[])(by[r.category]??=[]).push(r);
document.getElementById("rules").innerHTML=Object.entries(by).map(([cat,rs])=>"<div class='category'>"+esc(cat)+"</div>"+rs.map(r=>"<div class='rule'><div class='rulelabel'>"+esc(r.label)+" "+(r.available?"":"<span class='unavailable'>• data not available yet</span>")+"</div><span class='switch "+(ruleOn(r.rule_id)?"on":"")+"' onclick='toggleRule(""+esc(r.rule_id)+"")'></span><span class='sound'>Sound</span><span class='status'>"+(r.available?"Ready":"Waiting for indicator data")+"</span></div>").join("")).join("");
renderControls()}
function history(){try{return JSON.parse(localStorage.getItem(HKEY)||"[]")}catch{return []}}
function saveHistory(items){localStorage.setItem(HKEY,JSON.stringify(items.slice(-250)))}
function clearHistory(){localStorage.removeItem(HKEY);renderAlerts([])}
function process(d){lastPayload=d;renderRules();const current=(d.alerts||[]).filter(a=>ruleOn(a.rule_id));const ids=new Set(current.map(a=>a.alert_id));
let fresh=current.filter(a=>!lastActive.has(a.alert_id));if(fresh.length){beep();const h=history();for(const a of fresh)h.push({...a,triggered_at:new Date().toISOString()});saveHistory(h)}
lastActive=ids;renderAlerts(current)}
function renderAlerts(active){const h=history().slice().reverse();const combined=[...active.map(a=>({...a,live:true})),...h.filter(x=>!active.some(a=>a.alert_id===x.alert_id))];
document.getElementById("alerts").innerHTML=combined.slice(0,100).map(a=>"<div class='alertrow'><div>"+(a.live?"🔔":"")+"</div><div><b>"+esc(a.symbol)+"</b></div><div><b>"+esc(a.label)+"</b><div class='sub'>"+esc(a.category)+" • "+esc(a.triggered_at||a.generated_at||"")+"</div></div><div class='"+(a.direction==="UP"?"up":a.direction==="DOWN"?"down":"")+"'>"+esc(a.direction)+"</div><div><a href='/stock-analysis?symbol="+encodeURIComponent(a.symbol)+"'>Analyze →</a></div></div>").join("")||"<div class='empty'>No stock alerts triggered yet.</div>"}
async function load(){try{const r=await fetch("/api/stock-alerts?ts="+Date.now());const d=await r.json();lastPayload=d;document.getElementById("updated").textContent=(d.rows_count||0)+" stocks monitored • "+new Date().toLocaleTimeString();process(d)}catch(e){document.getElementById("updated").textContent="Alert data unavailable";}}
load();setInterval(load,5000);
</script></body></html>"""


__all__ = ["STOCK_ALERTS_HTML", "stock_alerts_payload"]
