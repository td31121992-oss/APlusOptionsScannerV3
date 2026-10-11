"""Stock chart with day high / day low (and their times) and previous-day high / low marked. Read-only.

    /stock-chart?symbol=XXX        page: today's 5-minute candles with PDH, PDL, day high and day low as labelled lines + markers
    /api/stock-day-chart?symbol=XXX    JSON: candles and the marks

Candles come from Dhan's intraday history (same helper as the trade chart); previous-day levels come from the daily
indicators file. `marks()` is also used by the trade page's stock chart.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _hm(epoch_ist: int) -> str:
    return datetime.fromtimestamp(epoch_ist, tz=timezone.utc).strftime("%H:%M")


def marks(candles: list[dict[str, Any]], indicators: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Lines to draw: PDH, PDL (no time) and the day high / low with the time of the candle that made them."""
    out: list[dict[str, Any]] = []
    ind = indicators or {}
    if ind.get("pdh"):
        out.append({"key": "pdh", "name": "PDH", "price": float(ind["pdh"]), "time": None, "label": "previous day high"})
    if ind.get("pdl"):
        out.append({"key": "pdl", "name": "PDL", "price": float(ind["pdl"]), "time": None, "label": "previous day low"})
    if candles:
        hi = max(candles, key=lambda c: c["h"])
        lo = min(candles, key=lambda c: c["l"])
        out.append({"key": "dayhigh", "name": "Day high", "price": hi["h"], "time": hi["t"], "hm": _hm(hi["t"]), "label": "today's high"})
        out.append({"key": "daylow", "name": "Day low", "price": lo["l"], "time": lo["t"], "hm": _hm(lo["t"]), "label": "today's low"})
    return out


def payload(symbol: str, root: Path = ROOT) -> dict[str, Any]:
    symbol = str(symbol or "").strip().upper()
    cached = _CACHE.get(symbol)
    if cached and time.time() - cached[0] < 15:
        return cached[1]
    import trade_chart

    try:
        if not trade_chart._UNIVERSE:
            from order_book_recorder import _universe

            trade_chart._UNIVERSE.update(_universe())
        if symbol not in trade_chart._UNIVERSE:
            return {"ok": False, "error": "symbol not in the F&O universe"}
        candles = trade_chart._candles(trade_chart._UNIVERSE[symbol], "NSE_EQ", "EQUITY", date.today().isoformat())
    except Exception as exc:                                # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__}
    try:
        ind = json.loads((root / "data" / "reports" / "daily_indicators.json").read_text(encoding="utf-8")).get("symbols", {}).get(symbol)
    except (OSError, ValueError):
        ind = None
    last = candles[-1]["c"] if candles else 0.0
    zones: dict[str, Any] = {"zones": [], "vwap": []}
    try:                                                    # zones are an extra: the chart must still load without them
        import chart_zones

        zones = chart_zones.zones_for(symbol, trade_chart._UNIVERSE[symbol], last)
    except Exception:                                      # noqa: BLE001
        pass
    out = {"ok": True, "symbol": symbol, "candles": candles, "marks": marks(candles, ind), "last": last,
           "zones": zones.get("zones", []), "vwap": zones.get("vwap", [])}
    _CACHE[symbol] = (time.time(), out)
    return out


STOCK_CHART_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Stock Chart</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="/static/lightweight-charts.js"></script>
<style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.35 -apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1300px;margin:0 auto;padding:12px 14px 40px}a{color:#4c8dff;text-decoration:none;font-weight:700}h1{font-size:22px;margin:8px 0 2px}
.sub{color:var(--muted);font-size:12.5px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px;margin-top:10px}
#chart{height:480px;position:relative}#chart canvas.zones{position:absolute;left:0;top:0;pointer-events:none;z-index:3}.tg{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:8px;color:var(--muted);font-size:12.5px}.tg label{cursor:pointer}.lg{display:flex;flex-wrap:wrap;gap:8px 18px;margin-top:10px}.lg div{padding:6px 10px;border:1px solid var(--line);border-radius:10px}
.lg b{font-weight:800}.k{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}
</style></head><body><div class="wrap">
<div><a href="/stock-analysis">&larr; Stock analysis</a> &nbsp; <a href="/">Dashboard</a></div>
<h1 id="title">Stock chart</h1><div class="sub" id="meta">loading...</div>
<div class="card"><div id="chart"></div><div class="tg" id="tg"><label><input type="checkbox" id="z_sd" checked> Supply / demand zones</label><label><input type="checkbox" id="z_pv" checked> Pivot lines</label><label><input type="checkbox" id="z_or" checked> Opening range</label><label><input type="checkbox" id="z_gp" checked> Gap</label><label><input type="checkbox" id="z_vw" checked> VWAP</label></div><div class="lg" id="lg"></div></div>
<div class="sub" style="margin-top:8px">Lines: PDH / PDL = previous day's high / low. Day high / low show the time of the candle that set them. Zones: red = supply, green = demand (areas where the stock turned back at least twice in the last 10 sessions; the number is how many turns), dotted = pivot lines, dashed = opening range, purple = gap, yellow line = VWAP. 5-minute candles, today. Read-only.</div>
</div><script>
var sym=(new URLSearchParams(location.search).get("symbol")||"").toUpperCase(),chart=null,series=null,lines=[],ZN=[],vwapSeries=null,cv=null;
var COL={pdh:"#4c8dff",pdl:"#b86bff",dayhigh:"#2ecc71",daylow:"#ff6363"};
function build(){chart=LightweightCharts.createChart(document.getElementById("chart"),{layout:{background:{color:"#121a2d"},textColor:"#8ea0bd"},grid:{vertLines:{color:"#1d2842"},horzLines:{color:"#1d2842"}},timeScale:{timeVisible:true,secondsVisible:false,borderColor:"#27334d"},rightPriceScale:{borderColor:"#27334d"},autoSize:true});
 series=chart.addCandlestickSeries({upColor:"#2ecc71",downColor:"#ff6363",borderUpColor:"#2ecc71",borderDownColor:"#ff6363",wickUpColor:"#2ecc71",wickDownColor:"#ff6363"});
 vwapSeries=chart.addLineSeries({color:"#f5b942",lineWidth:2,priceLineVisible:false,lastValueVisible:false,title:"VWAP"});
 cv=document.createElement("canvas");cv.className="zones";document.getElementById("chart").appendChild(cv);
 chart.timeScale().subscribeVisibleLogicalRangeChange(function(){drawZones()});setInterval(drawZones,300)}
function drawZones(){if(!cv||!series)return;var host=document.getElementById("chart"),w=host.clientWidth,h=host.clientHeight,dpr=window.devicePixelRatio||1;
 if(cv.width!==w*dpr||cv.height!==h*dpr){cv.width=w*dpr;cv.height=h*dpr;cv.style.width=w+"px";cv.style.height=h+"px"}
 var g=cv.getContext("2d");g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,w,h);g.font="11px system-ui,sans-serif";
 var on={sd:document.getElementById("z_sd").checked,pv:document.getElementById("z_pv").checked,or:document.getElementById("z_or").checked,gp:document.getElementById("z_gp").checked};
 if(vwapSeries)vwapSeries.applyOptions({visible:document.getElementById("z_vw").checked});
 ZN.forEach(function(z){var k=z.kind;if(k==="pd")return;if((k==="supply"||k==="demand")&&!on.sd)return;if(k==="pivot"&&!on.pv)return;if(k==="or"&&!on.or)return;if(k==="gap"&&!on.gp)return;
  var y1=series.priceToCoordinate(z.high),y2=series.priceToCoordinate(z.low);if(y1==null||y2==null)return;var top=Math.min(y1,y2),ht=Math.max(Math.abs(y2-y1),1.5);
  if(top>h||top+ht<0)return;
  var col=k==="supply"?"255,99,99":k==="demand"?"46,204,113":k==="gap"?"150,110,255":k==="or"?"245,185,66":"142,160,189";
  if(k==="supply"||k==="demand"||k==="gap"){g.fillStyle="rgba("+col+",.16)";g.fillRect(0,top,w,ht);g.strokeStyle="rgba("+col+",.55)";g.lineWidth=1;g.beginPath();g.moveTo(0,top);g.lineTo(w,top);g.moveTo(0,top+ht);g.lineTo(w,top+ht);g.stroke()}
  else{g.strokeStyle="rgba("+col+",.8)";g.lineWidth=1;g.setLineDash(k==="or"?[6,4]:[2,4]);g.beginPath();g.moveTo(0,top+ht/2);g.lineTo(w,top+ht/2);g.stroke();g.setLineDash([])}
  g.fillStyle="rgba("+col+",1)";g.fillText(z.name+(z.touches?" ("+z.touches+" turns)":""),8,top+(ht>12?12:-3))})}
function load(){fetch("/api/stock-day-chart?symbol="+encodeURIComponent(sym),{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){
 if(!d.ok){document.getElementById("meta").textContent=d.error||"not available";return}
 if(!chart)build();
 document.getElementById("title").textContent=d.symbol+" - day levels";document.getElementById("meta").textContent="Last "+d.last.toFixed(2)+" - "+d.candles.length+" five-minute candles today";
 series.setData(d.candles.map(function(x){return{time:x.t,open:x.o,high:x.h,low:x.l,close:x.c}}));ZN=d.zones||[];vwapSeries.setData((d.vwap||[]).map(function(x){return{time:x.t,value:x.v}}));
 lines.forEach(function(l){series.removePriceLine(l)});lines=[];var mk=[],ps=[];
 d.marks.forEach(function(m){ps.push(m.price);var t=m.name+" "+m.price.toFixed(2)+(m.hm?" @ "+m.hm:"");
  lines.push(series.createPriceLine({price:m.price,color:COL[m.key],lineWidth:m.key.indexOf("day")===0?2:1,lineStyle:m.key.indexOf("day")===0?0:2,axisLabelVisible:true,title:t}));
  if(m.time){mk.push({time:m.time,position:m.key==="dayhigh"?"aboveBar":"belowBar",color:COL[m.key],shape:m.key==="dayhigh"?"arrowDown":"arrowUp",text:m.name+" "+m.hm})}});
 mk.sort(function(a,b){return a.time-b.time});series.setMarkers(mk);
 if(ps.length){var lo=Math.min.apply(null,ps),hi=Math.max.apply(null,ps);series.applyOptions({autoscaleInfoProvider:function(orig){var r=orig();if(!r)return{priceRange:{minValue:lo,maxValue:hi}};return{priceRange:{minValue:Math.min(r.priceRange.minValue,lo),maxValue:Math.max(r.priceRange.maxValue,hi)},margins:r.margins}}})}
 document.getElementById("lg").innerHTML=d.marks.map(function(m){return '<div><span class="k" style="background:'+COL[m.key]+'"></span>'+m.name+' <b>'+m.price.toFixed(2)+'</b>'+(m.hm?' <span class="sub">at '+m.hm+'</span>':' <span class="sub">'+m.label+'</span>')+'</div>'}).join("")
 }).catch(function(){document.getElementById("meta").textContent="connection lost - retrying"})}
["z_sd","z_pv","z_or","z_gp","z_vw"].forEach(function(i){document.getElementById(i).addEventListener("change",drawZones)});
load();setInterval(load,20000);
</script></body></html>
"""
