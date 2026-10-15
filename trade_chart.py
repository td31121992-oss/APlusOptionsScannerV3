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
from datetime import datetime, timezone
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
    # Start the window at 09:00, before the open: Dhan drops the first minute when it starts exactly at the open, and the first candle then loses the real open and low.
    r = requests.post("https://api.dhan.co/v2/charts/intraday", timeout=25, json={
        "securityId": str(int(security_id)), "exchangeSegment": segment, "instrument": instrument, "interval": "5", "oi": False,
        "fromDate": f"{day} 09:00:00", "toDate": f"{day} 15:30:00"},
        headers={"access-token": token, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"})
    if r.status_code != 200:
        return []
    d = r.json()
    return [{"t": int(ts) + 19800, "o": float(o), "h": float(h), "l": float(l), "c": float(c)}      # +5:30 so the chart axis shows IST
            for ts, o, h, l, c in zip(d.get("timestamp") or [], d.get("open") or [], d.get("high") or [], d.get("low") or [], d.get("close") or [])]


_HIST: dict[str, tuple[float, Any]] = {}


def _headers() -> dict[str, str]:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from dhan_auth import resolve_access_token

    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    token = resolve_access_token(project_root=ROOT, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    return {"access-token": token, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"}


def _five_history(security_id: int, day: str, timeout: float = 25) -> tuple[dict[str, list[float]], int]:
    """About six sessions of 5-minute stock candles up to `day`, and the index where `day` starts. Cached for 45 seconds."""
    import requests
    from datetime import date, timedelta

    key = f"5m|{security_id}|{day}"
    hit = _HIST.get(key)
    if hit and time.time() - hit[0] < 45:
        return hit[1]
    frm = (date.fromisoformat(day) - timedelta(days=9)).isoformat()
    r = requests.post("https://api.dhan.co/v2/charts/intraday", headers=_headers(), timeout=timeout, json={
        "securityId": str(int(security_id)), "exchangeSegment": "NSE_EQ", "instrument": "EQUITY", "interval": "5", "oi": False,
        "fromDate": f"{frm} 09:00:00", "toDate": f"{day} 15:30:00"})
    out: dict[str, list[float]] = {"o": [], "h": [], "l": [], "c": [], "v": [], "m": []}
    start = 0
    if r.status_code == 200:
        d = r.json() or {}
        for i, ts in enumerate(d.get("timestamp") or []):
            when = datetime.fromtimestamp(int(ts), IST)
            if when.date().isoformat() == day and start == 0 and out["c"]:
                start = len(out["c"])
            out["o"].append(float(d["open"][i]))
            out["h"].append(float(d["high"][i]))
            out["l"].append(float(d["low"][i]))
            out["c"].append(float(d["close"][i]))
            out["v"].append(float((d.get("volume") or [0] * len(d["close"]))[i] or 0))
            out["m"].append(when.hour * 60 + when.minute)
    res = (out, start)
    _HIST[key] = (time.time(), res)
    return res


def _daily_history(security_id: int, day: str, timeout: float = 25) -> dict[str, list[float]]:
    """About eight months of daily candles up to (and excluding) `day`. Cached for an hour."""
    import requests
    from datetime import date, timedelta

    key = f"1d|{security_id}|{day}"
    hit = _HIST.get(key)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    r = requests.post("https://api.dhan.co/v2/charts/historical", headers=_headers(), timeout=timeout, json={
        "securityId": str(int(security_id)), "exchangeSegment": "NSE_EQ", "instrument": "EQUITY", "expiryCode": 0, "oi": False,
        "fromDate": (date.fromisoformat(day) - timedelta(days=260)).isoformat(), "toDate": day})
    out: dict[str, list[float]] = {"o": [], "h": [], "l": [], "c": [], "v": []}
    if r.status_code == 200:
        d = r.json() or {}
        for i, ts in enumerate(d.get("timestamp") or []):
            if datetime.fromtimestamp(int(ts), IST).date().isoformat() >= day:
                continue
            out["o"].append(float(d["open"][i]))
            out["h"].append(float(d["high"][i]))
            out["l"].append(float(d["low"][i]))
            out["c"].append(float(d["close"][i]))
            out["v"].append(float((d.get("volume") or [0] * len(d["close"]))[i] or 0))
    _HIST[key] = (time.time(), out)
    return out


def trade_extreme(candles: list[dict[str, Any]], start: int, end: int, high: bool = True) -> dict[str, Any] | None:
    """Highest high (or lowest low) of the candles from the entry candle to the exit (or now). {price, time, hm} or None."""
    best = None
    for c in candles or []:
        t = int(c.get("t") or 0)
        if t < start - 299 or (end and t > end):
            continue
        v = float(c.get("h" if high else "l") or 0)
        if v <= 0:
            continue
        if best is None or (v > best[0] if high else v < best[0]):
            best = (v, t)
    if best is None:
        return None
    hm = datetime.fromtimestamp(best[1], timezone.utc).strftime("%H:%M")        # candle times carry the +05:30 shift already
    return {"price": round(best[0], 2), "time": best[1], "hm": hm}


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
        try:
            import smc_levels

            stock_marks = stock_marks + smc_levels.marks(stock)
        except Exception:                                  # noqa: BLE001
            pass
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
           "setup": t.get("setup_family") or "", "entry_hm": entry_t[11:16] if len(entry_t) >= 16 else ""}
    try:
        bull = str(t.get("direction") or "").upper() == "BULLISH"
        out["trade_marks"] = {"option": trade_extreme(option, entry_epoch, exit_epoch, True),
                              "stock": trade_extreme(stock, entry_epoch, exit_epoch, bull), "stock_is_high": bull}
    except Exception:                                       # noqa: BLE001 - chart extras must never break the page
        out["trade_marks"] = {}
    try:                                                    # stock trend gauge, indicators and scans (see stock_trend.py)
        import stock_trend

        if symbol in _UNIVERSE:
            sid = _UNIVERSE[symbol]
            five, start = _five_history(sid, day)
            daily = _daily_history(sid, day)
            ind = json.loads((root / "data" / "reports" / "daily_indicators.json").read_text(encoding="utf-8")).get("symbols", {}).get(symbol)
            prev_close = daily["c"][-1] if daily.get("c") else _f((ind or {}).get("last_close"))
            out["trend"] = stock_trend.build(five, start, daily, ind, prev_close, str(t.get("direction") or "").upper() == "BULLISH")
    except Exception:                                       # noqa: BLE001 - the extras must never break the page
        out["trend"] = {}
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
.grid3{display:grid;grid-template-columns:1fr 1.2fr 1fr;gap:12px;margin-top:12px}@media(max-width:1000px){.grid3{grid-template-columns:1fr}}
.tabs{display:flex;gap:6px;margin-bottom:6px}.tabs button{flex:1;background:#0f1729;color:var(--muted);border:1px solid var(--line);border-radius:8px;padding:6px;font-weight:800;cursor:pointer}
.tabs button.on{background:#12351f;color:var(--green);border-color:var(--green)}
.glbl{text-align:center;font-weight:900;font-size:18px;margin-top:-6px}.counts{display:flex;gap:6px;margin-top:10px}
.counts span{flex:1;text-align:center;border-radius:8px;padding:6px 4px;font-weight:700;font-size:12.5px}
.counts .b{background:#12351f;color:var(--green)}.counts .n{background:#232b3f;color:var(--muted)}.counts .r{background:#3a1620;color:var(--red)}
table.ind{width:100%;border-collapse:collapse;font-size:13px}table.ind td{padding:7px 4px;border-bottom:1px solid var(--line)}
table.ind td:last-child{text-align:right;font-weight:700}.bull{color:var(--green)}.bear{color:var(--red)}.neutral{color:var(--muted)}
.sc{border-radius:8px;padding:8px 10px;margin-bottom:6px;font-weight:700;font-size:13px}.sc .t{float:right;opacity:.75;font-weight:600;font-size:12px}.sc.bull{background:#12351f;color:#b9f5cf}.sc.bear{background:#3a1620;color:#ffb9c8}
</style></head><body><div class="wrap">
<div><a href="/positions">&larr; Positions</a> &nbsp; <a href="/">Dashboard</a></div>
<div class="head"><div><h1 id="title">Trade</h1><div class="sub" id="meta">loading...</div></div><div style="text-align:right"><div id="pnl" style="font-size:24px;font-weight:800"></div><div class="sub" id="state"></div></div></div>
<div class="grid"><div class="card"><h2 id="optTitle">Option (5-minute)</h2><div class="chart" id="optChart"></div><div class="lv" id="optLv"></div></div>
<div class="card"><h2 id="stkTitle">Stock (5-minute)</h2><div class="chart" id="stkChart"></div><div class="lv" id="stkLv"></div></div></div>
<div class="grid3" id="trendRow" style="display:none">
<div class="card"><h2>Stock trend</h2><div class="tabs" id="trTabs"></div><div id="gauge"></div><div id="gaugeLbl" class="glbl"></div><div class="counts" id="trCounts"></div></div>
<div class="card"><h2>Tech indicators <span class="sub" id="trTf"></span></h2><table class="ind" id="indTbl"></table></div>
<div class="card"><h2>Intraday scans</h2><div id="scans"></div></div>
</div>
<div class="note">Lines: yellow = entry, red = stop loss, green = targets 1-3, gold dotted = the trade's own high (best point since entry) with its time. The marker shows the entry candle and entry time. Paper trade; read-only. Charts refresh every 15 seconds.</div>
</div><script>
var id=new URLSearchParams(location.search).get("id")||"",charts={};
function mk(el){var c=LightweightCharts.createChart(document.getElementById(el),{layout:{background:{color:"#121a2d"},textColor:"#8ea0bd"},grid:{vertLines:{color:"#1d2842"},horzLines:{color:"#1d2842"}},timeScale:{timeVisible:true,secondsVisible:false,borderColor:"#27334d"},rightPriceScale:{borderColor:"#27334d"},autoSize:true});
 var s=c.addCandlestickSeries({upColor:"#2ecc71",downColor:"#ff6363",borderUpColor:"#2ecc71",borderDownColor:"#ff6363",wickUpColor:"#2ecc71",wickDownColor:"#ff6363"});return{chart:c,series:s,lines:[]}}
function fill(k,el,candles,lv,entry,xm,tm,entryHm,isHigh){if(!charts[k])charts[k]=mk(el);var o=charts[k];xm=(xm||[]).slice();
 o.series.setData((candles||[]).map(function(x){return{time:x.t,open:x.o,high:x.h,low:x.l,close:x.c}}));
 o.lines.forEach(function(l){o.series.removePriceLine(l)});o.lines=[];var ps=[],mkr=[];
 (lv||[]).forEach(function(l){ps.push(l.price);var col=l.name==="SL"?"#ff6363":l.name==="Entry"?"#f5b942":"#2ecc71";
  o.lines.push(o.series.createPriceLine({price:l.price,color:col,lineWidth:2,lineStyle:l.name==="Entry"?0:2,axisLabelVisible:true,title:l.name+" "+l.price.toFixed(2)}))});
 var XC={pdh:"#4c8dff",pdl:"#b86bff",dayhigh:"#2ecc71",daylow:"#ff6363",tradehigh:"#ffd166",ob_top:"#2ecc71",ob_bottom:"#2ecc71",liq:"#f5b942"};
 var xcol=function(m){return (m.key.indexOf("ob_")===0&&String(m.name).indexOf("Bear")===0)?"#ff6363":XC[m.key]};
 if(tm&&tm.price){var dup=xm.filter(function(m){return(m.key==="dayhigh"||m.key==="daylow")&&Math.abs(m.price-tm.price)<0.006});
  if(dup.length){dup[0].name="Day & trade "+(isHigh?"high":"low")}else{xm.push({key:"tradehigh",name:"Trade "+(isHigh?"high":"low"),price:tm.price,hm:tm.hm,time:tm.time})}}
 (xm||[]).forEach(function(m){ps.push(m.price);var day=m.key.indexOf("day")===0;
  o.lines.push(o.series.createPriceLine({price:m.price,color:xcol(m),lineWidth:day?1:1,lineStyle:m.key==="liq"?2:3,axisLabelVisible:true,title:m.name+" "+m.price.toFixed(2)+(m.hm?" @ "+m.hm:"")}));
  if(m.time){mkr.push({time:m.time,position:m.key==="dayhigh"?"aboveBar":"belowBar",color:XC[m.key],shape:(m.key==="dayhigh"||(m.key==="tradehigh"&&isHigh))?"arrowDown":"arrowUp",text:m.name+" "+m.hm})}});
 if(ps.length){var lo=Math.min.apply(null,ps),hi=Math.max.apply(null,ps);
  o.series.applyOptions({autoscaleInfoProvider:function(orig){var r=orig();if(!r)return{priceRange:{minValue:lo,maxValue:hi}};return{priceRange:{minValue:Math.min(r.priceRange.minValue,lo),maxValue:Math.max(r.priceRange.maxValue,hi)},margins:r.margins}}})}
 if(entry&&(candles||[]).length){var t=0;for(var i=0;i<candles.length;i++){if(candles[i].t<=entry)t=candles[i].t}if(t)mkr.push({time:t,position:"belowBar",color:"#f5b942",shape:"arrowUp",text:"Entry"+(entryHm?" "+entryHm:"")})}
 mkr.sort(function(a,b){return a.time-b.time});o.series.setMarkers(mkr)}
function chips(el,lv){document.getElementById(el).innerHTML=(lv||[]).map(function(l){var c=l.name==="SL"?"sl":l.name==="Entry"?"e":"t";return'<span class="'+c+'">'+l.name+' <b>'+l.price.toFixed(2)+'</b></span>'}).join("")}
var TREND=null,TF="5M";
function gaugeSvg(score){var a=Math.max(-1,Math.min(1,score))*90,cx=110,cy=100,r=84,segs=24,h="";
 for(var i=0;i<segs;i++){var t=i/(segs-1),ang=Math.PI*(1-i/segs),a2=Math.PI*(1-(i+0.7)/segs);
  var col="hsl("+Math.round(t*165)+",60%,50%)";
  var x1=cx+r*Math.cos(ang),y1=cy-r*Math.sin(ang),x2=cx+(r-16)*Math.cos(ang),y2=cy-(r-16)*Math.sin(ang),x3=cx+(r-16)*Math.cos(a2),y3=cy-(r-16)*Math.sin(a2),x4=cx+r*Math.cos(a2),y4=cy-r*Math.sin(a2);
  h+='<path d="M'+x1+','+y1+' L'+x2+','+y2+' L'+x3+','+y3+' L'+x4+','+y4+'Z" fill="'+col+'"/>'}
 var rad=(90-a)*Math.PI/180,nx=cx+(r-6)*Math.cos(rad),ny=cy-(r-6)*Math.sin(rad);
 return '<svg viewBox="0 0 220 112" style="width:100%;max-width:300px;display:block;margin:0 auto">'+h+'<line x1="'+cx+'" y1="'+cy+'" x2="'+nx+'" y2="'+ny+'" stroke="#e7eefc" stroke-width="2.5"/><circle cx="'+cx+'" cy="'+cy+'" r="5" fill="#e7eefc"/></svg>'}
function drawTrend(){var row=document.getElementById("trendRow");if(!TREND||!TREND.trend||!Object.keys(TREND.trend).length){row.style.display="none";return}
 var tr=TREND.trend;row.style.display="grid";
 document.getElementById("trTabs").innerHTML=["5M","15M","DAILY"].filter(function(k){return tr[k]}).map(function(k){return'<button class="'+(k===TF?"on":"")+'" data-tf="'+k+'">'+k+'</button>'}).join("");
 document.querySelectorAll("#trTabs button").forEach(function(b){b.onclick=function(){TF=b.dataset.tf;drawTrend()}});
 var cur=tr[TF]||tr["5M"]||tr["DAILY"];if(!cur)return;
 document.getElementById("gauge").innerHTML=gaugeSvg(cur.score);
 var s=cur.score,lbl=s>=0.6?"STRONG BULLISH":s>=0.2?"BULLISH":s<=-0.6?"STRONG BEARISH":s<=-0.2?"BEARISH":"NEUTRAL";
 var g=document.getElementById("gaugeLbl");g.textContent=lbl;g.style.color=s>=0.2?"#2ecc71":s<=-0.2?"#ff6363":"#8ea0bd";
 document.getElementById("trCounts").innerHTML='<span class="r">Bearish '+cur.bearish+'</span><span class="n">Neutral '+cur.neutral+'</span><span class="b">Bullish '+cur.bullish+'</span>';
 document.getElementById("trTf").textContent=(TF==="5M"?"SHORT TERM (5M TF)":TF==="15M"?"(15M TF)":"(DAILY TF)");
 document.getElementById("indTbl").innerHTML='<tr><td class="neutral">NAME</td><td class="neutral">VALUE</td><td class="neutral" style="text-align:right">INTERPRETATION</td></tr>'
  +(cur.table||[]).map(function(r){return'<tr><td>'+r.name+'</td><td>'+r.value+'</td><td class="'+r.tone+'">'+r.text+'</td></tr>'}).join("");
 var chb=tr.chop?'<div class="sc '+(tr.chop.chop_state==="CHOPPY"?"bear":tr.chop.chop_state==="TRENDING"?"bull":"")+'" style="background:'+(tr.chop.chop_state==="CHOPPY"?"#3a1620":tr.chop.chop_state==="TRENDING"?"#12351f":"#232b3f")+'">'+tr.chop.text+'</div>':"";
 document.getElementById("scans").innerHTML=chb+((tr.scans||[]).length?(tr.scans).map(function(x){return'<div class="sc '+x.tone+'">'+x.text+(x.time?'<span class="t">@ '+x.time+'</span>':'')+'</div>'}).join(""):'<div class="sub">No scan matches right now.</div>')}
function load(){fetch("/api/trade-chart?id="+encodeURIComponent(id),{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){
 if(!d.ok){document.getElementById("meta").textContent=d.error||"not found";return}
 document.getElementById("title").innerHTML=d.option_label+' <span class="pill '+(d.status==="OPEN"?"open":"closed")+'">'+d.status+'</span>';
 document.getElementById("meta").textContent=(d.direction||"")+" - "+d.setup+" - expiry "+d.expiry+" - qty "+d.qty+(d.exit_reason?" - "+d.exit_reason:"");
 var p=document.getElementById("pnl");p.textContent=(d.pnl<0?"-":"")+"₹"+Math.abs(d.pnl).toLocaleString("en-IN",{maximumFractionDigits:2});p.className=d.pnl>=0?"pos":"neg";
 document.getElementById("state").textContent=(d.status==="OPEN"?"Last ":"Exit ")+d.last.toFixed(2)+(d.error?" - chart data issue: "+d.error:"");
 document.getElementById("optTitle").textContent="Option - "+d.option_label+" (5-minute)";document.getElementById("stkTitle").textContent="Stock - "+d.symbol+" (5-minute)";
 TREND=d;drawTrend();var tmk=d.trade_marks||{};fill("opt","optChart",d.option,d.levels.option,d.entry_epoch,[],tmk.option,d.entry_hm,true);fill("stk","stkChart",d.stock,d.levels.stock,d.entry_epoch,d.stock_marks,tmk.stock,d.entry_hm,tmk.stock_is_high!==false);chips("optLv",d.levels.option);chips("stkLv",d.levels.stock);
 if(!d.option.length&&!d.stock.length)document.getElementById("meta").textContent+=" - no candles yet";
 }).catch(function(){document.getElementById("meta").textContent="connection lost - retrying"})}
load();setInterval(load,15000);
</script></body></html>
"""
