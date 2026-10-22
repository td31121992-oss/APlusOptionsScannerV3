"""Chart Lab: a charting page where you add indicators yourself and put each one on any timeframe (read-only; nothing here touches the scanner or any trade).

    /chart-lab?symbol=KALYANKJIL            the page (candles + indicators you add, each on the chart's timeframe or on another one)
    /api/chart-lab?symbol=X&tf=5m           candles for 1m / 5m / 15m / 30m / 1h / 1d  (Upstox candles, resampled from 5-minute bars for 15m / 30m / 1h)
    /api/chart-lab-delta?symbol=X           5-minute buying / selling / delta bars from the recorded ticks (every F&O stock from 22 Oct, ten stocks before)
    /api/chart-lab-symbols                  the F&O symbols

Indicators are calculated in the browser: EMA, SMA, VWAP, Bollinger, SuperTrend, RSI, MACD, ATR, volume and delta. An indicator set to a higher timeframe uses only COMPLETED bars of that
timeframe (no repainting), shown as a step line on the chart you are looking at.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
SHIFT = 19800                      # chart times are UTC seconds; adding the IST offset makes the axis read IST
TFS = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}
_CACHE: dict[tuple, tuple[float, Any]] = {}
_STATE: dict[str, Any] = {"client": None, "uni": None}


def _ttl(key: tuple, seconds: float, fetch):
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < seconds:
        return hit[1]
    val = fetch()
    _CACHE[key] = (time.time(), val)
    return val


def symbols(root: Path = ROOT) -> list[str]:
    if _STATE["uni"] is None:
        import sys

        sys.path.insert(0, str(root))
        from order_book_recorder import _universe

        _STATE["uni"] = _universe()
    return sorted(_STATE["uni"])


def _client(root: Path = ROOT):
    if _STATE["client"] is None:
        import sys

        sys.path.insert(0, str(root))
        from dotenv import load_dotenv

        load_dotenv(root / ".env")
        from core.upstox_client import UpstoxClient

        _STATE["client"] = UpstoxClient()
    return _STATE["client"]


def resample(rows: list[dict[str, Any]], minutes: int) -> list[dict[str, Any]]:
    """rows: ascending 5-minute bars {t (epoch), o, h, l, c, v}. Groups them into `minutes`-minute bars aligned to the 09:15 session open, per trading day."""
    out: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        dt = datetime.fromtimestamp(r["t"], IST)
        mod = dt.hour * 60 + dt.minute
        bucket = (mod - 555) // minutes
        key = (dt.date(), bucket)
        start = int(datetime(dt.year, dt.month, dt.day, tzinfo=IST).timestamp()) + (555 + bucket * minutes) * 60
        b = out.get(key)
        if b is None:
            out[key] = {"t": start, "o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"], "v": r["v"]}
        else:
            b["h"], b["l"], b["c"], b["v"] = max(b["h"], r["h"]), min(b["l"], r["l"]), r["c"], b["v"] + r["v"]
    return [out[k] for k in sorted(out)]


def _rows(d: dict[str, list[Any]]) -> list[dict[str, Any]]:
    keys = ("open", "high", "low", "close", "volume")
    return [{"t": int(d["timestamp"][i]), "o": d["open"][i], "h": d["high"][i], "l": d["low"][i], "c": d["close"][i], "v": d["volume"][i]} for i in range(len(d["timestamp"]))
            if all(d[k][i] is not None for k in keys)]


def _intraday(symbol: str, minutes: int, days: int) -> list[dict[str, Any]]:
    uni = _STATE["uni"] or (symbols() and _STATE["uni"])
    sid = uni[symbol]
    now = datetime.now(IST).replace(tzinfo=None)
    d = _client().get_intraday_candles(security_id=sid, segment="NSE_EQ", interval=minutes, from_datetime=now - timedelta(days=days), to_datetime=now + timedelta(minutes=1))
    return _rows(d)


def _daily(symbol: str) -> list[dict[str, Any]]:
    c = _client()
    sid = _STATE["uni"][symbol]
    key = c.instrument_key("NSE_EQ", sid)
    today = datetime.now(IST).date()
    body = c._get(f"/v3/historical-candle/{key}/days/1/{today.isoformat()}/{(today - timedelta(days=700)).isoformat()}", {}, auth=False)
    rows = []
    for k in (body.get("data") or {}).get("candles") or []:
        ts = datetime.fromisoformat(str(k[0]))
        rows.append({"d": ts.date().isoformat(), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4]), "v": float(k[5])})
    rows.sort(key=lambda r: r["d"])
    return rows


def candles(symbol: str, tf: str) -> dict[str, Any]:
    symbol = str(symbol or "").upper()
    if symbol not in symbols():
        return {"ok": False, "error": f"{symbol or 'symbol'} is not an F&O stock"}
    if tf not in TFS and tf != "1d":
        return {"ok": False, "error": "timeframe must be 1m, 5m, 15m, 30m, 1h or 1d"}
    try:
        if tf == "1d":
            rows = _ttl(("d", symbol), 300, lambda: _daily(symbol))
            return {"ok": True, "symbol": symbol, "tf": tf, "daily": True, "candles": rows[-500:]}
        if tf == "1m":
            rows = _ttl(("1m", symbol), 20, lambda: _intraday(symbol, 1, 4))
        else:
            base = _ttl(("5m", symbol), 20, lambda: _intraday(symbol, 5, 14))
            rows = base if tf == "5m" else resample(base, TFS[tf])
        rows = [{"t": r["t"] + SHIFT, "o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"], "v": r["v"]} for r in rows]
        return {"ok": True, "symbol": symbol, "tf": tf, "daily": False, "candles": rows[-1600:], "updated": datetime.now(IST).strftime("%H:%M:%S")}
    except Exception as exc:                               # noqa: BLE001 - the page shows the message
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def delta_payload(symbol: str, root: Path = ROOT) -> dict[str, Any]:
    """5-minute buy / sell / delta from the recorded ticks for the last days that have this stock's tick file."""
    symbol = str(symbol or "").upper()
    folder = root / "data" / "ticks"
    days = sorted(p.name for p in folder.glob("20*") if (p / f"{symbol}.csv.gz").exists())[-6:] if folder.exists() else []
    if not days:
        return {"ok": True, "symbol": symbol, "bars": [], "note": "no recorded ticks for this stock yet"}
    import csv
    import gzip

    import footprint_lite

    bars: list[dict[str, Any]] = []
    for day in days:
        def build(day=day):
            rows = []
            try:
                with gzip.open(folder / day / f"{symbol}.csv.gz", "rt", encoding="utf-8", newline="") as h:
                    for r in csv.DictReader(h):
                        rows.append(r)
            except (OSError, EOFError):
                pass
            return footprint_lite.candles_from_ticks(rows, day, symbol)

        live = day == datetime.now(IST).date().isoformat()
        for b in (_ttl(("delta", symbol, day), 30, build) if live else _ttl(("delta", symbol, day), 6 * 3600, build)):
            ts = int(datetime(int(day[:4]), int(day[5:7]), int(day[8:10]), tzinfo=IST).timestamp()) + b["minute"] * 60 + SHIFT
            bars.append({"t": ts, "delta": b["delta"], "buy": b["buy_vol"], "sell": b["sell_vol"]})
    return {"ok": True, "symbol": symbol, "bars": bars}


# the page ---------------------------------------------------------------------------------------------------------------------------------------------------------------
CHART_LAB_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Chart Lab</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><script src="/static/lightweight-charts.js"></script>
<style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--blue:#4c8dff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:13px/1.35 -apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--blue);text-decoration:none;font-weight:700}.top{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--line);background:var(--panel)}
button,input,select{background:#0e1527;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:6px 9px;font:inherit}button{cursor:pointer;font-weight:700}button.on{background:var(--blue);border-color:var(--blue)}
input[type=number]{width:62px}#sym{width:130px;text-transform:uppercase;font-weight:800}.bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--line)}
.chip{display:inline-flex;gap:6px;align-items:center;background:#0e1527;border:1px solid var(--line);border-radius:14px;padding:3px 9px;font-size:12px}.chip i{width:10px;height:10px;border-radius:50%;display:inline-block}
.chip b{cursor:pointer;color:#ff8080}.chip em{font-style:normal;cursor:pointer;opacity:.8}.wrap{padding:8px 12px}#main{height:470px;background:var(--panel);border:1px solid var(--line);border-radius:10px}
.pane{height:150px;background:var(--panel);border:1px solid var(--line);border-radius:10px;margin-top:6px;position:relative}.pane .lab{position:absolute;left:8px;top:4px;z-index:5;font-size:11px;color:var(--muted);pointer-events:none}
.sub{color:var(--muted);font-size:12px}#legend{position:absolute;left:10px;top:6px;z-index:6;font-size:12px;pointer-events:none;text-shadow:0 0 3px #000}.rel{position:relative}
</style></head><body>
<div class="top"><a href="/">&larr; Dashboard</a><input id="sym" list="syms" value="" placeholder="symbol"><datalist id="syms"></datalist>
<span id="tfs"></span><span class="sub" id="meta">loading...</span></div>
<div class="bar"><b>Add indicator</b>
<select id="itype"><option>EMA</option><option>SMA</option><option>VWAP</option><option>Bollinger</option><option>SuperTrend</option><option>RSI</option><option>MACD</option><option>ATR</option><option>Volume</option><option>Delta</option></select>
<span id="ip"></span><label class="sub">on timeframe <select id="itf"><option value="chart">same as chart</option><option>1m</option><option>5m</option><option>15m</option><option>30m</option><option>1h</option><option>1d</option></select></label>
<input type="color" id="icol" value="#f5b942" style="padding:0;width:34px;height:28px"><button id="iadd">Add</button><span id="chips"></span></div>
<div class="wrap"><div class="rel"><div id="main"></div><div id="legend"></div></div><div id="panes"></div>
<div class="sub" style="margin-top:8px">Indicators on a higher timeframe use only completed bars (no repainting). Delta comes from the recorded ticks (5-minute bars) and needs a stock with tick data. Everything here is read-only.</div></div>
<script>
var TFL=["1m","5m","15m","30m","1h","1d"],DUR={"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"1d":86400};
var S={sym:"",tf:"5m",inds:[],data:{},delta:null,main:null,candle:null,panes:[],series:{}};
function ls(k,v){try{if(v===undefined)return JSON.parse(localStorage.getItem(k));localStorage.setItem(k,JSON.stringify(v))}catch(e){return null}}
var DEF={EMA:[{k:"len",v:20}],SMA:[{k:"len",v:50}],VWAP:[],Bollinger:[{k:"len",v:20},{k:"mult",v:2}],SuperTrend:[{k:"len",v:10},{k:"mult",v:3}],RSI:[{k:"len",v:14}],MACD:[{k:"fast",v:12},{k:"slow",v:26},{k:"sig",v:9}],ATR:[{k:"len",v:14}],Volume:[],Delta:[]};
var PANE={RSI:1,MACD:1,ATR:1,Volume:1,Delta:1};
function ema(a,n){var o=[],k=2/(n+1),p=null;for(var i=0;i<a.length;i++){var x=a[i];if(x==null){o.push(null);continue}p=p==null?x:x*k+p*(1-k);o.push(i<n-1?null:p)}return o}
function sma(a,n){var o=[],s=0;for(var i=0;i<a.length;i++){s+=a[i];if(i>=n)s-=a[i-n];o.push(i>=n-1?s/n:null)}return o}
function rma(a,n){var o=[],p=null;for(var i=0;i<a.length;i++){var x=a[i];if(x==null){o.push(null);continue}p=p==null?x:(p*(n-1)+x)/n;o.push(i<n-1?null:p)}return o}
function rsi(c,n){var g=[0],l=[0];for(var i=1;i<c.length;i++){var d=c[i]-c[i-1];g.push(Math.max(d,0));l.push(Math.max(-d,0))}var ag=rma(g,n),al=rma(l,n);return ag.map(function(x,i){return x==null||al[i]==null?null:(al[i]===0?100:100-100/(1+x/al[i]))})}
function tr(h,l,c){return h.map(function(x,i){return i?Math.max(x-l[i],Math.abs(x-c[i-1]),Math.abs(l[i]-c[i-1])):x-l[i]})}
function atr(h,l,c,n){return rma(tr(h,l,c),n)}
function supertrend(h,l,c,n,m){var a=atr(h,l,c,n),up=[],dn=[],st=[],dir=1;for(var i=0;i<c.length;i++){if(a[i]==null){up.push(null);dn.push(null);st.push(null);continue}
 var hl=(h[i]+l[i])/2,bu=hl+m*a[i],bl=hl-m*a[i];var pu=up[i-1]==null?bu:up[i-1],pl=dn[i-1]==null?bl:dn[i-1];
 var u=(bu<pu||c[i-1]>pu)?bu:pu,d=(bl>pl||c[i-1]<pl)?bl:pl;up.push(u);dn.push(d);
 if(st[i-1]==null)dir=c[i]>u?1:-1;else if(dir===-1&&c[i]>pu)dir=1;else if(dir===1&&c[i]<pl)dir=-1;st.push(dir===1?d:u);}
 return st.map(function(v,i){return v==null?null:{v:v,up:(i&&st[i]!=null)?(c[i]>=v):true}})}
function day(t){return new Date(t*1000).toISOString().slice(0,10)}
function vwap(cs){var o=[],pv=0,vv=0,d="";cs.forEach(function(x){var dd=x.day||day(x.t);if(dd!==d){d=dd;pv=0;vv=0}var tp=(x.h+x.l+x.c)/3;pv+=tp*x.v;vv+=x.v;o.push(vv?pv/vv:null)});return o}
function boll(c,n,m){var mid=sma(c,n),u=[],lo=[];for(var i=0;i<c.length;i++){if(mid[i]==null){u.push(null);lo.push(null);continue}var s=0;for(var j=i-n+1;j<=i;j++)s+=Math.pow(c[j]-mid[i],2);var sd=Math.sqrt(s/n);u.push(mid[i]+m*sd);lo.push(mid[i]-m*sd)}return {mid:mid,u:u,l:lo}}
function pick(i,k){var p=i.p;for(var j=0;j<p.length;j++)if(p[j].k===k)return +p[j].v;return 0}
function norm(d){return d.daily?d.candles.map(function(r){return {t:r.d,day:r.d,o:r.o,h:r.h,l:r.l,c:r.c,v:r.v}}):d.candles.map(function(r){return {t:r.t,day:day(r.t),o:r.o,h:r.h,l:r.l,c:r.c,v:r.v}})}
function need(tf){return fetch("/api/chart-lab?symbol="+S.sym+"&tf="+tf,{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){if(!d.ok)throw new Error(d.error||"no data");S.data[tf]=norm(d);return S.data[tf]})}
function getTF(tf){return S.data[tf]?Promise.resolve(S.data[tf]):need(tf)}
function tnum(t){return typeof t==="string"?Date.parse(t+"T00:00:00Z")/1000:t}
function mapHTF(vals,htf,chart){ // value of the last COMPLETED higher-timeframe bar for every chart bar (no repaint)
 var ht=htf.map(function(x){return tnum(x.t)}),out=[],j=0;
 for(var i=0;i<chart.length;i++){var T=tnum(chart[i].t);while(j+1<ht.length&&ht[j+1]<=T)j++;var k=j-1;out.push(ht[j]<=T&&k>=0?vals[k]:null)}return out}
function calc(ind,cs){var c=cs.map(function(x){return x.c}),h=cs.map(function(x){return x.h}),l=cs.map(function(x){return x.l}),r={};
 switch(ind.type){case"EMA":r.line=ema(c,pick(ind,"len"));break;case"SMA":r.line=sma(c,pick(ind,"len"));break;case"VWAP":r.line=vwap(cs);break;
 case"Bollinger":var b=boll(c,pick(ind,"len"),pick(ind,"mult"));r.mid=b.mid;r.u=b.u;r.l=b.l;break;
 case"SuperTrend":r.st=supertrend(h,l,c,pick(ind,"len"),pick(ind,"mult"));break;case"RSI":r.line=rsi(c,pick(ind,"len"));break;
 case"MACD":var f=ema(c,pick(ind,"fast")),s=ema(c,pick(ind,"slow")),m=f.map(function(x,i){return x==null||s[i]==null?null:x-s[i]});var sg=ema(m.map(function(x){return x==null?0:x}),pick(ind,"sig"));r.macd=m;r.sig=sg;r.hist=m.map(function(x,i){return x==null?null:x-sg[i]});break;
 case"ATR":r.line=atr(h,l,c,pick(ind,"len"));break;case"Volume":r.vol=cs.map(function(x){return x.v});break}
 return r}
function remap(res,htf,chart){var o={};for(var k in res){var arr=res[k];if(!arr)continue;o[k]=mapHTF(arr,htf,chart)}return o}
function toLine(cs,vals,color,w){return {data:cs.map(function(x,i){return vals[i]==null?{time:x.t}:{time:x.t,value:vals[i]}}),color:color,w:w||1.5}}
function chartOpts(h){return {height:h,layout:{background:{color:"#121a2d"},textColor:"#8ea0bd"},grid:{vertLines:{color:"#1d2842"},horzLines:{color:"#1d2842"}},rightPriceScale:{borderColor:"#27334d",minimumWidth:72},timeScale:{borderColor:"#27334d",timeVisible:true,secondsVisible:false},crosshair:{mode:0}}}
function clearAll(){["main"].concat(S.panes.map(function(_,i){return i})).forEach(function(){});if(S.main){S.main.remove();S.main=null}S.panes.forEach(function(p){p.chart.remove()});S.panes=[];document.getElementById("panes").innerHTML=""}
function newPane(label){var d=document.createElement("div");d.className="pane";d.innerHTML='<div class="lab">'+label+'</div>';document.getElementById("panes").appendChild(d);var ch=LightweightCharts.createChart(d,chartOpts(150));S.panes.push({chart:ch,el:d});return ch}
function sync(){var all=[S.main].concat(S.panes.map(function(p){return p.chart})),busy=false;all.forEach(function(a){a.timeScale().subscribeVisibleLogicalRangeChange(function(r){if(busy||!r)return;busy=true;try{all.forEach(function(b){if(b!==a)b.timeScale().setVisibleLogicalRange(r)})}finally{busy=false}})})}
function render(){var cs=S.data[S.tf];if(!cs||!cs.length)return;clearAll();var gen=S.gen=(S.gen||0)+1;
 S.main=LightweightCharts.createChart(document.getElementById("main"),chartOpts(470));
 S.candle=S.main.addCandlestickSeries({upColor:"#2ecc71",downColor:"#ff6363",borderUpColor:"#2ecc71",borderDownColor:"#ff6363",wickUpColor:"#2ecc71",wickDownColor:"#ff6363"});
 S.candle.setData(cs.map(function(x){return {time:x.t,open:x.o,high:x.h,low:x.l,close:x.c}}));
 var jobs=S.inds.map(function(ind){var tf=ind.tf==="chart"?S.tf:ind.tf;if(ind.type==="Delta")return Promise.resolve({ind:ind,res:null,tf:S.tf});return getTF(tf).then(function(h){var res=calc(ind,h);if(tf!==S.tf)res=remap(res,h,cs);return {ind:ind,res:res,tf:tf}})});
 var legend=[];
 Promise.all(jobs).then(function(list){if(gen!==S.gen)return;list.forEach(function(j){var ind=j.ind;if(!ind.show)return;var r=j.res,tag=ind.type+"("+ind.p.map(function(p){return p.v}).join(",")+")"+(ind.tf==="chart"?"":" "+ind.tf);
  if(ind.type==="Delta"){addDelta(ind,cs,tag);return}
  if(ind.type==="VWAP"||ind.type==="EMA"||ind.type==="SMA"){var l=toLine(cs,r.line,ind.col,2),s=S.main.addLineSeries({color:l.color,lineWidth:2,priceLineVisible:false,lastValueVisible:true,title:tag});s.setData(l.data);legend.push('<span style="color:'+ind.col+'">'+tag+'</span>')}
  else if(ind.type==="Bollinger"){[["mid",ind.col,1],["u",ind.col,1],["l",ind.col,1]].forEach(function(z){var l=toLine(cs,r[z[0]],z[1],1),s=S.main.addLineSeries({color:l.color,lineWidth:1,lineStyle:z[0]==="mid"?2:0,priceLineVisible:false,lastValueVisible:false});s.setData(l.data)});legend.push('<span style="color:'+ind.col+'">'+tag+'</span>')}
  else if(ind.type==="SuperTrend"){var up=S.main.addLineSeries({color:"#2ecc71",lineWidth:2,priceLineVisible:false,lastValueVisible:false}),dn=S.main.addLineSeries({color:"#ff6363",lineWidth:2,priceLineVisible:false,lastValueVisible:false});
   var st=r.st;var ud=[],dd=[];cs.forEach(function(x,i){var v=st[i];if(!v||v.v==null||typeof v!=="object"){ud.push({time:x.t});dd.push({time:x.t});return}if(v.up){ud.push({time:x.t,value:v.v});dd.push({time:x.t})}else{dd.push({time:x.t,value:v.v});ud.push({time:x.t})}});up.setData(ud);dn.setData(dd);legend.push('<span style="color:#2ecc71">'+tag+'</span>')}
  else if(ind.type==="RSI"){var ch=newPane(tag),s=ch.addLineSeries({color:ind.col,lineWidth:2,priceLineVisible:false});s.setData(toLine(cs,r.line,ind.col).data);[30,70].forEach(function(v){s.createPriceLine({price:v,color:"#4a5878",lineWidth:1,lineStyle:2,axisLabelVisible:false})})}
  else if(ind.type==="ATR"){var ch2=newPane(tag),s2=ch2.addLineSeries({color:ind.col,lineWidth:2,priceLineVisible:false});s2.setData(toLine(cs,r.line,ind.col).data)}
  else if(ind.type==="Volume"){var ch3=newPane("Volume"),s3=ch3.addHistogramSeries({priceLineVisible:false});s3.setData(cs.map(function(x){return {time:x.t,value:x.v,color:x.c>=x.o?"#2ecc7199":"#ff636399"}}))}
  else if(ind.type==="MACD"){var ch4=newPane(tag),hs=ch4.addHistogramSeries({priceLineVisible:false}),ml=ch4.addLineSeries({color:"#4c8dff",lineWidth:2,priceLineVisible:false}),sl=ch4.addLineSeries({color:"#f5b942",lineWidth:1,priceLineVisible:false});
   hs.setData(cs.map(function(x,i){return r.hist[i]==null?{time:x.t}:{time:x.t,value:r.hist[i],color:r.hist[i]>=0?"#2ecc7199":"#ff636399"}}));ml.setData(toLine(cs,r.macd,"#4c8dff").data);sl.setData(toLine(cs,r.sig,"#f5b942").data)}});
  document.getElementById("legend").innerHTML=legend.join(" &nbsp; ");sync();var n=cs.length;S.main.timeScale().setVisibleLogicalRange({from:Math.max(0,n-(S.tf==="1d"?160:200)),to:n+4})}).catch(function(e){document.getElementById("meta").textContent=String(e.message||e)})}
function addDelta(ind,cs,tag){var d=S.delta;if(!d||!d.bars.length){var ch0=newPane("Delta - no tick data for this stock yet");return}
 var dur=DUR[S.tf],bk={};d.bars.forEach(function(b){var t=b.t-(b.t%dur);bk[t]=(bk[t]||0)+b.delta});
 var ch=newPane("Delta (buying - selling) "+S.tf),s=ch.addHistogramSeries({priceLineVisible:false});
 s.setData(cs.map(function(x){var v=bk[tnum(x.t)];return v==null?{time:x.t}:{time:x.t,value:v,color:v>=0?"#2ecc7199":"#ff636399"}}))}
function chips(){var h="";S.inds.forEach(function(ind,i){h+='<span class="chip"><i style="background:'+ind.col+'"></i>'+ind.type+"("+ind.p.map(function(p){return p.v}).join(",")+")"+(ind.tf==="chart"?"":" @"+ind.tf)+' <em data-t="'+i+'">'+(ind.show?"hide":"show")+'</em> <b data-x="'+i+'">&times;</b></span>'});document.getElementById("chips").innerHTML=h;
 document.querySelectorAll("#chips b").forEach(function(b){b.onclick=function(){S.inds.splice(+b.dataset.x,1);ls("cl_inds",S.inds);chips();render()}});
 document.querySelectorAll("#chips em").forEach(function(b){b.onclick=function(){var i=S.inds[+b.dataset.t];i.show=!i.show;ls("cl_inds",S.inds);chips();render()}})}
function params(){var t=document.getElementById("itype").value,h="";DEF[t].forEach(function(p){h+='<label class="sub">'+p.k+' <input type="number" step="any" data-k="'+p.k+'" value="'+p.v+'"></label> '});document.getElementById("ip").innerHTML=h}
function load(first){var meta=document.getElementById("meta");meta.textContent="loading "+S.sym+" "+S.tf+"...";
 return Promise.all([need(S.tf),fetch("/api/chart-lab-delta?symbol="+S.sym,{cache:"no-store"}).then(function(r){return r.json()}).catch(function(){return null})]).then(function(a){S.delta=a[1];
  var cs=S.data[S.tf];meta.textContent=S.sym+" - "+S.tf+" - "+cs.length+" bars - last "+(cs.length?(typeof cs[cs.length-1].t==="string"?cs[cs.length-1].t:new Date(cs[cs.length-1].t*1000).toISOString().slice(0,16).replace("T"," ")):"");render()}).catch(function(e){meta.textContent=String(e.message||e)})}
function setTF(tf){S.tf=tf;ls("cl_tf",tf);S.data={};document.querySelectorAll("#tfs button").forEach(function(b){b.className=b.dataset.tf===tf?"on":""});load()}
function go(){var v=document.getElementById("sym").value.trim().toUpperCase();if(!v)return;S.sym=v;ls("cl_sym",v);S.data={};history.replaceState(null,"","?symbol="+encodeURIComponent(v));load()}
(function init(){var q=(new URLSearchParams(location.search).get("symbol")||"").toUpperCase();S.sym=q||ls("cl_sym")||"RELIANCE";S.tf=ls("cl_tf")||"5m";S.inds=ls("cl_inds")||[{type:"EMA",p:[{k:"len",v:20}],tf:"chart",col:"#f5b942",show:true},{type:"VWAP",p:[],tf:"chart",col:"#c084fc",show:true},{type:"SuperTrend",p:[{k:"len",v:10},{k:"mult",v:3}],tf:"chart",col:"#2ecc71",show:true}];
 document.getElementById("sym").value=S.sym;var th="";TFL.forEach(function(t){th+='<button data-tf="'+t+'" class="'+(t===S.tf?"on":"")+'">'+t+"</button> "});document.getElementById("tfs").innerHTML=th;document.querySelectorAll("#tfs button").forEach(function(b){b.onclick=function(){setTF(b.dataset.tf)}});
 document.getElementById("sym").addEventListener("change",go);document.getElementById("itype").onchange=params;params();
 document.getElementById("iadd").onclick=function(){var t=document.getElementById("itype").value,p=[];document.querySelectorAll("#ip input").forEach(function(i){p.push({k:i.dataset.k,v:+i.value})});S.inds.push({type:t,p:p,tf:document.getElementById("itf").value,col:document.getElementById("icol").value,show:true});ls("cl_inds",S.inds);chips();render()};
 fetch("/api/chart-lab-symbols").then(function(r){return r.json()}).then(function(d){document.getElementById("syms").innerHTML=(d.symbols||[]).map(function(s){return '<option value="'+s+'">'}).join("")});
 chips();load();setInterval(function(){if(document.hidden||S.tf==="1d")return;var t=S.tf;need(t).then(function(){render()}).catch(function(){})},30000)})();
</script></body></html>"""
