"""Trade detail page: the stock chart and the option's chart side by side with entry, stop and targets 1-3 written on them.

    /trade?id=<paper_trade_id>        page (two 5-minute candle charts + a levels table)
    /api/trade-chart?id=<id>          JSON: levels for the option and the stock plus today's 5-minute candles of both

Read-only: one quote-history request per chart (cached 15 seconds). Candles come from Dhan's intraday history for the
stock and for the traded option contract; levels come from the paper-trade record.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_UNIVERSE: dict[str, int] = {}


def _f(value: Any) -> float:
    try:
        out = float(value)
        return out if out == out else 0.0
    except (TypeError, ValueError):
        return 0.0


def find_trade(trade_id: str, root: Path = ROOT) -> dict[str, Any] | None:
    for path in (root / "data" / "intraday_movement" / "paper_trade_journal.json",):
        try:
            for t in json.loads(path.read_text(encoding="utf-8")).get("trades", []):
                if str(t.get("paper_trade_id")) == trade_id:
                    return t
        except (OSError, ValueError):
            pass
    try:                                                    # earlier days: the history file
        import csv

        with (root / "data" / "reports" / "paper_trade_history.csv").open(encoding="utf-8-sig", newline="") as handle:
            for r in csv.DictReader(handle):
                if r.get("paper_trade_id") == trade_id:
                    return r
    except OSError:
        pass
    return None


def levels(t: dict[str, Any]) -> dict[str, Any]:
    opt = [("Entry", _f(t.get("entry_price"))), ("SL", _f(t.get("option_stop"))), ("T1", _f(t.get("option_target1"))),
           ("T2", _f(t.get("option_target2"))), ("T3", _f(t.get("option_target3")))]
    stk = [("Entry", _f(t.get("underlying_entry"))), ("SL", _f(t.get("underlying_stop"))), ("T1", _f(t.get("underlying_target1"))),
           ("T2", _f(t.get("underlying_target2"))), ("T3", _f(t.get("underlying_target3")))]
    return {"option": [{"name": n, "price": p} for n, p in opt if p > 0], "stock": [{"name": n, "price": p} for n, p in stk if p > 0]}


def _candles(security_id: int, segment: str, instrument: str, day: str) -> list[dict[str, Any]]:
    import requests
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from dhan_auth import resolve_access_token

    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    token = resolve_access_token(project_root=ROOT, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    r = requests.post("https://api.dhan.co/v2/charts/intraday", timeout=25, json={
        "securityId": str(int(security_id)), "exchangeSegment": segment, "instrument": instrument, "interval": "5", "oi": False,
        "fromDate": f"{day} 09:15:00", "toDate": f"{day} 15:30:00"},
        headers={"access-token": token, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"})
    if r.status_code != 200:
        return []
    d = r.json()
    return [{"t": int(ts) + 19800, "o": float(o), "h": float(h), "l": float(l), "c": float(c)}      # +5:30 so the chart axis shows IST
            for ts, o, h, l, c in zip(d.get("timestamp") or [], d.get("open") or [], d.get("high") or [], d.get("low") or [], d.get("close") or [])]


def payload(trade_id: str, root: Path = ROOT) -> dict[str, Any]:
    cached = _CACHE.get(trade_id)
    if cached and time.time() - cached[0] < 15:
        return cached[1]
    t = find_trade(trade_id, root)
    if not t:
        return {"ok": False, "error": "trade not found"}
    day = str(t.get("entry_time") or "")[:10] or datetime.now(IST).date().isoformat()
    symbol = str(t.get("symbol") or "")
    stock, option, error = [], [], ""
    try:
        if not _UNIVERSE:
            from order_book_recorder import _universe

            _UNIVERSE.update(_universe())
        if symbol in _UNIVERSE:
            stock = _candles(_UNIVERSE[symbol], "NSE_EQ", "EQUITY", day)
        if t.get("option_security_id"):
            option = _candles(int(float(t["option_security_id"])), "NSE_FNO", "OPTSTK", day)
    except Exception as exc:                                # noqa: BLE001
        error = type(exc).__name__
    stock_marks: list[dict[str, Any]] = []
    try:
        import stock_chart

        ind = json.loads((root / "data" / "reports" / "daily_indicators.json").read_text(encoding="utf-8")).get("symbols", {}).get(symbol)
        stock_marks = stock_chart.marks(stock, ind)
    except Exception:                                       # noqa: BLE001
        pass
    entry_t = str(t.get("entry_time") or "")
    try:
        entry_epoch = int(datetime.fromisoformat(entry_t).timestamp()) + 19800
    except ValueError:
        entry_epoch = 0
    exit_epoch = 0
    try:
        if t.get("exit_time"):
            exit_epoch = int(datetime.fromisoformat(str(t["exit_time"])).timestamp()) + 19800
    except ValueError:
        pass
    status = str(t.get("status") or "").upper()
    last = _f(t.get("last_option_price")) if status == "OPEN" else _f(t.get("exit_price"))
    entry, qty = _f(t.get("entry_price")), int(_f(t.get("quantity")))
    out = {"ok": True, "error": error, "id": trade_id, "symbol": symbol, "status": status, "direction": t.get("direction"),
           "option_label": f"{symbol} {int(_f(t.get('strike'))) if _f(t.get('strike')).is_integer() else _f(t.get('strike'))} {t.get('option_type', '')}",
           "expiry": str(t.get("expiry") or ""), "qty": qty, "entry_epoch": entry_epoch, "exit_epoch": exit_epoch,
           "last": last, "pnl": round((last - entry) * qty, 2) if entry > 0 and last > 0 else 0.0,
           "exit_reason": t.get("exit_reason") or "", "levels": levels(t), "stock": stock, "option": option, "stock_marks": stock_marks,
           "setup": t.get("setup_family") or ""}
    _CACHE[trade_id] = (time.time(), out)
    return out


TRADE_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Trade</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="/static/lightweight-charts.js"></script>
<style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--green:#2ecc71;--red:#ff6363;--amber:#f5b942;--blue:#4c8dff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.35 -apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1500px;margin:0 auto;padding:12px 14px 40px}a{color:var(--blue);text-decoration:none;font-weight:700}
.head{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;align-items:baseline;margin:6px 0 10px}h1{font-size:22px;margin:0}
.pill{border-radius:999px;padding:3px 10px;font-size:12px;font-weight:800}.pill.open{background:#12351f;color:var(--green)}.pill.closed{background:#2a3350;color:#9fb3ff}
.pos{color:var(--green)}.neg{color:var(--red)}.sub{color:var(--muted);font-size:12.5px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:900px){.grid{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px}.card h2{font-size:15px;margin:0 0 6px}
.chart{height:420px}.lv{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:8px;font-size:13px}.lv span b{font-weight:800}
.lv .sl b{color:var(--red)}.lv .t b{color:var(--green)}.lv .e b{color:var(--amber)}
.note{color:var(--muted);font-size:12px;margin-top:10px}
</style></head><body><div class="wrap">
<div><a href="/positions">&larr; Positions</a> &nbsp; <a href="/">Dashboard</a></div>
<div class="head"><div><h1 id="title">Trade</h1><div class="sub" id="meta">loading...</div></div><div style="text-align:right"><div id="pnl" style="font-size:24px;font-weight:800"></div><div class="sub" id="state"></div></div></div>
<div class="grid"><div class="card"><h2 id="optTitle">Option (5-minute)</h2><div class="chart" id="optChart"></div><div class="lv" id="optLv"></div></div>
<div class="card"><h2 id="stkTitle">Stock (5-minute)</h2><div class="chart" id="stkChart"></div><div class="lv" id="stkLv"></div></div></div>
<div class="note">Lines: yellow = entry, red = stop loss, green = targets 1-3. The marker shows the entry candle. Paper trade; read-only. Charts refresh every 15 seconds.</div>
</div><script>
var id=new URLSearchParams(location.search).get("id")||"",charts={};
function mk(el){var c=LightweightCharts.createChart(document.getElementById(el),{layout:{background:{color:"#121a2d"},textColor:"#8ea0bd"},grid:{vertLines:{color:"#1d2842"},horzLines:{color:"#1d2842"}},timeScale:{timeVisible:true,secondsVisible:false,borderColor:"#27334d"},rightPriceScale:{borderColor:"#27334d"},autoSize:true});
 var s=c.addCandlestickSeries({upColor:"#2ecc71",downColor:"#ff6363",borderUpColor:"#2ecc71",borderDownColor:"#ff6363",wickUpColor:"#2ecc71",wickDownColor:"#ff6363"});return{chart:c,series:s,lines:[]}}
function fill(k,el,candles,lv,entry,xm){if(!charts[k])charts[k]=mk(el);var o=charts[k];
 o.series.setData((candles||[]).map(function(x){return{time:x.t,open:x.o,high:x.h,low:x.l,close:x.c}}));
 o.lines.forEach(function(l){o.series.removePriceLine(l)});o.lines=[];var ps=[],mkr=[];
 (lv||[]).forEach(function(l){ps.push(l.price);var col=l.name==="SL"?"#ff6363":l.name==="Entry"?"#f5b942":"#2ecc71";
  o.lines.push(o.series.createPriceLine({price:l.price,color:col,lineWidth:2,lineStyle:l.name==="Entry"?0:2,axisLabelVisible:true,title:l.name+" "+l.price.toFixed(2)}))});
 var XC={pdh:"#4c8dff",pdl:"#b86bff",dayhigh:"#2ecc71",daylow:"#ff6363"};
 (xm||[]).forEach(function(m){ps.push(m.price);var day=m.key.indexOf("day")===0;
  o.lines.push(o.series.createPriceLine({price:m.price,color:XC[m.key],lineWidth:day?1:1,lineStyle:3,axisLabelVisible:true,title:m.name+" "+m.price.toFixed(2)+(m.hm?" @ "+m.hm:"")}));
  if(m.time){mkr.push({time:m.time,position:m.key==="dayhigh"?"aboveBar":"belowBar",color:XC[m.key],shape:m.key==="dayhigh"?"arrowDown":"arrowUp",text:m.name+" "+m.hm})}});
 if(ps.length){var lo=Math.min.apply(null,ps),hi=Math.max.apply(null,ps);
  o.series.applyOptions({autoscaleInfoProvider:function(orig){var r=orig();if(!r)return{priceRange:{minValue:lo,maxValue:hi}};return{priceRange:{minValue:Math.min(r.priceRange.minValue,lo),maxValue:Math.max(r.priceRange.maxValue,hi)},margins:r.margins}}})}
 if(entry&&(candles||[]).length){var t=0;for(var i=0;i<candles.length;i++){if(candles[i].t<=entry)t=candles[i].t}if(t)mkr.push({time:t,position:"belowBar",color:"#f5b942",shape:"arrowUp",text:"Entry"})}
 mkr.sort(function(a,b){return a.time-b.time});o.series.setMarkers(mkr)}
function chips(el,lv){document.getElementById(el).innerHTML=(lv||[]).map(function(l){var c=l.name==="SL"?"sl":l.name==="Entry"?"e":"t";return'<span class="'+c+'">'+l.name+' <b>'+l.price.toFixed(2)+'</b></span>'}).join("")}
function load(){fetch("/api/trade-chart?id="+encodeURIComponent(id),{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){
 if(!d.ok){document.getElementById("meta").textContent=d.error||"not found";return}
 document.getElementById("title").innerHTML=d.option_label+' <span class="pill '+(d.status==="OPEN"?"open":"closed")+'">'+d.status+'</span>';
 document.getElementById("meta").textContent=(d.direction||"")+" - "+d.setup+" - expiry "+d.expiry+" - qty "+d.qty+(d.exit_reason?" - "+d.exit_reason:"");
 var p=document.getElementById("pnl");p.textContent=(d.pnl<0?"-":"")+"₹"+Math.abs(d.pnl).toLocaleString("en-IN",{maximumFractionDigits:2});p.className=d.pnl>=0?"pos":"neg";
 document.getElementById("state").textContent=(d.status==="OPEN"?"Last ":"Exit ")+d.last.toFixed(2)+(d.error?" - chart data issue: "+d.error:"");
 document.getElementById("optTitle").textContent="Option - "+d.option_label+" (5-minute)";document.getElementById("stkTitle").textContent="Stock - "+d.symbol+" (5-minute)";
 fill("opt","optChart",d.option,d.levels.option,d.entry_epoch);fill("stk","stkChart",d.stock,d.levels.stock,d.entry_epoch,d.stock_marks);chips("optLv",d.levels.option);chips("stkLv",d.levels.stock);
 if(!d.option.length&&!d.stock.length)document.getElementById("meta").textContent+=" - no candles yet";
 }).catch(function(){document.getElementById("meta").textContent="connection lost - retrying"})}
load();setInterval(load,15000);
</script></body></html>
"""
