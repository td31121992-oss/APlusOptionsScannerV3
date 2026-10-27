"""Read-only dashboard page/API for volume profile and footprint availability."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from orderflow_profile_readonly import analyze_footprint, build_volume_profile

IST = ZoneInfo("Asia/Kolkata")
_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_CACHE_SECONDS = 20.0


def payload(symbol: str, day: str) -> dict[str, Any]:
    symbol = str(symbol or "").strip().upper()
    try:
        day = datetime.fromisoformat(str(day)).date().isoformat()
    except (TypeError, ValueError):
        day = datetime.now(IST).date().isoformat()
    if not symbol or len(symbol) > 32 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789&_-" for c in symbol):
        return {"ok": False, "error": "invalid_symbol", "analysis_mode": "READ_ONLY"}
    key = (symbol, day)
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _CACHE_SECONDS:
        return cached[1]
    try:
        import trade_chart
        if not trade_chart._UNIVERSE:
            from order_book_recorder import _universe
            trade_chart._UNIVERSE.update(_universe())
        security_id = trade_chart._UNIVERSE.get(symbol)
        if not security_id:
            result = {"ok": False, "error": "symbol_not_in_loaded_universe",
                      "symbol": symbol, "day": day, "analysis_mode": "READ_ONLY"}
        else:
            candles = trade_chart._candles(int(security_id), "NSE_EQ", "EQUITY", day)
            rows = [{"open": c.get("o"), "high": c.get("h"), "low": c.get("l"),
                     "close": c.get("c"), "volume": c.get("v")} for c in candles]
            profile = build_volume_profile(rows)
            footprint = analyze_footprint([])
            result = {
                "ok": bool(profile.get("ok")), "analysis_mode": "READ_ONLY",
                "symbol": symbol, "day": day, "timeframe": "5m",
                "candles_used": len(rows), "volume_profile": profile,
                "footprint": footprint,
                "data_notes": [
                    "Profile uses available 5-minute OHLCV candles and is an estimate, not true trade-at-price volume.",
                    "Footprint delta/imbalance is unavailable until a suitable bid/ask-by-price feed is integrated.",
                    "No trading decision, eligibility change, or order action is produced."
                ]
            }
    except Exception as exc:
        result = {"ok": False, "analysis_mode": "READ_ONLY", "symbol": symbol, "day": day,
                  "error": type(exc).__name__, "message": "Market data unavailable; no estimates generated."}
    _CACHE[key] = (time.monotonic(), result)
    return result


HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>APlus Order Flow & Volume Profile</title>
<style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--green:#17c964;--red:#f31260;--cyan:#22d3ee}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px Segoe UI,Arial,sans-serif}
header{padding:16px 20px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
h1{font-size:21px;margin:0}.muted{color:var(--muted);font-size:12px}.toolbar{display:flex;gap:8px;flex-wrap:wrap}
input,button,a{background:var(--panel);border:1px solid var(--line);color:var(--text);border-radius:8px;padding:9px 12px;text-decoration:none}
button{cursor:pointer;font-weight:700}.layout{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;min-width:0}
h2{font-size:15px;margin:0 0 10px}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.metric{background:#0b1020;border:1px solid var(--line);border-radius:8px;padding:10px}.label{font-size:11px;color:var(--muted)}.value{font-size:20px;font-weight:800;margin-top:4px;overflow-wrap:anywhere}
.note{font-size:12px;color:var(--muted);line-height:1.6}.barrow{display:grid;grid-template-columns:85px 1fr 90px;gap:8px;align-items:center;font-size:12px;margin:6px 0}
.track{height:10px;background:#0b1020;border-radius:6px;overflow:hidden}.bar{height:100%;background:var(--cyan)}
.status{padding:8px 10px;border:1px solid var(--line);border-radius:8px;color:var(--muted);margin:12px 14px}
@media(max-width:760px){.layout{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style></head><body>
<header><div><h1>Order Flow & Volume Profile</h1><div class="muted">Independent read-only analysis • no trade execution controls</div></div>
<div class="toolbar"><input id="symbol" value="MANKIND" aria-label="Symbol"><input id="day" type="date" aria-label="Trading date"><button id="load">Analyze</button><a href="/stock-detail">Stock Workspace</a></div></header>
<div id="status" class="status">Loading market data…</div>
<main class="layout">
<section class="card"><h2>Volume Profile (estimated from 5m OHLCV)</h2><div class="metrics" id="metrics"></div><h2 style="margin-top:14px">Estimated price-volume distribution</h2><div id="profile"></div><p class="note">Volume is spread uniformly across each candle's high-low range. This is not a true trade-at-price profile. POC/VAH/VAL and HVN/LVN are descriptive estimates, not trade signals.</p></section>
<section class="card"><h2>Footprint / Bid-Ask Order Flow</h2><div class="metrics" id="footprint"></div><p class="note" id="footnote"></p><h2 style="margin-top:14px">Data integrity</h2><div class="note" id="notes"></div></section>
</main>
<script>
const $=s=>document.querySelector(s);
const fmt=v=>v==null||v===""?"—":Number(v).toLocaleString("en-IN",{maximumFractionDigits:2});
function metric(label,value){return '<div class="metric"><div class="label">'+label+'</div><div class="value">'+value+'</div></div>'}
async function load(){let symbol=($('#symbol').value||'').trim().toUpperCase();let day=$('#day').value;$('#status').textContent='Loading '+symbol+'…';
try{let r=await fetch('/api/orderflow-profile?symbol='+encodeURIComponent(symbol)+'&day='+encodeURIComponent(day),{cache:'no-store'});let j=await r.json();
if(!j.ok){$('#status').textContent='Data unavailable: '+(j.error||'no valid data');$('#metrics').innerHTML='';$('#profile').innerHTML='';$('#footprint').innerHTML=metric('Footprint','Unavailable');$('#footnote').textContent=j.message||'Check symbol, date, and market-data availability.';$('#notes').textContent='Read-only; no trading decisions are made.';return}
let p=j.volume_profile||{};$('#status').textContent=j.symbol+' • '+j.day+' • '+j.candles_used+' candles • READ-ONLY';
$('#metrics').innerHTML=metric('POC',fmt(p.poc))+metric('VAH',fmt(p.vah))+metric('VAL',fmt(p.val))+metric('Volume allocated',fmt(p.total_volume_allocated))+metric('HVN count',(p.high_volume_nodes||[]).length)+metric('LVN count',(p.low_volume_nodes||[]).length);
let rows=(p.profile||[]).slice().sort((a,b)=>b.estimated_volume-a.estimated_volume).slice(0,12);let max=Math.max(1,...rows.map(x=>x.estimated_volume));
$('#profile').innerHTML=rows.map(x=>'<div class="barrow"><span>'+fmt(x.price)+'</span><div class="track"><div class="bar" style="width:'+Math.max(1,x.estimated_volume/max*100)+'%"></div></div><span>'+fmt(x.estimated_volume)+'</span></div>').join('')||'No profile bins';
let f=j.footprint||{};$('#footprint').innerHTML=metric('Bid/ask delta',f.ok?fmt(f.delta):'Unavailable')+metric('Buyer volume',f.ok?fmt(f.ask_volume):'Not supplied')+metric('Seller volume',f.ok?fmt(f.bid_volume):'Not supplied');
$('#footnote').textContent='True footprint delta and bid/ask imbalance require price-level aggressor data. OHLCV candles alone cannot supply these values.';
$('#notes').textContent=(j.data_notes||[]).join('\n');}catch(e){$('#status').textContent='Request failed: market data could not be loaded.'}}
$('#load').onclick=load;$('#symbol').addEventListener('keydown',e=>{if(e.key==='Enter')load()});$('#day').value=new Date().toLocaleDateString('en-CA');load();
</script></body></html>"""
