"""Money Flow and Sector Spotlight: where the traded money is going, by stock and by sector, today / last hour / last 15 minutes. Read-only.

Built from the order-book recorder's once-a-minute readings (data/order_book/<date>.csv): last price and day volume per stock.
For every minute the money traded is  new volume x average price.  It is counted as BUYING if the price ticked up versus the previous
reading, as SELLING if it ticked down, and a flat price keeps the previous direction (the standard "tick rule").
    net flow  = buying value - selling value (Rs crore)        flow %  = net flow / total traded value
This is an estimate of aggressor direction, not a record of who bought: the data cannot tell institutions from retail, and a
minute with one price reading can hide trades that went both ways. Use it to see where activity is concentrating, not as a signal.
"""

from __future__ import annotations

import csv
import json
import threading
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CR = 1e7
_LOCK = threading.Lock()
_S: dict[str, Any] = {"key": None, "offset": 0, "header": None, "sym": {}, "last_time": ""}


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def _reset(key: str) -> None:
    _S.update(key=key, offset=0, header=None, sym={}, last_time="")


def step(state: dict[str, Any], symbol: str, t: str, ltp: float, volume: float, imbalance: float) -> None:
    """Process one reading of one stock (pure; unit tested)."""
    s = state.setdefault(symbol, {"lp": 0.0, "lv": 0.0, "cls": 0, "ev": [], "imb": deque(maxlen=10), "first": ltp, "avg": 0.0})
    s["imb"].append(imbalance)
    if s["lp"] > 0 and volume >= s["lv"] and ltp > 0:
        dv = volume - s["lv"]
        value = dv * (ltp + s["lp"]) / 2.0
        cls = 1 if ltp > s["lp"] else -1 if ltp < s["lp"] else s["cls"]
        if value > 0:
            s["ev"].append((t, value if cls >= 0 else 0.0, value if cls < 0 else 0.0))   # (time, buy value, sell value)
        if cls:
            s["cls"] = cls
    elif volume < s["lv"]:
        pass                                              # volume reset / glitch: ignore this delta
    s["lp"], s["lv"] = ltp, max(volume, s["lv"])


def _refresh(root: Path, day: date) -> None:
    path = root / "data" / "order_book" / f"{day.isoformat()}.csv"
    key = f"{root}|{day}"
    if _S["key"] != key:
        _reset(key)
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size < _S["offset"]:
        _reset(key)
    if size == _S["offset"]:
        return
    with path.open("rb") as handle:
        handle.seek(_S["offset"])
        chunk = handle.read()
    end = chunk.rfind(b"\n")
    if end < 0:
        return
    _S["offset"] += end + 1
    lines = chunk[: end + 1].decode("utf-8", errors="replace").splitlines()
    if _S["header"] is None:
        if not lines:
            return
        _S["header"] = next(csv.reader([lines.pop(0)]))
    head = _S["header"]
    for row in csv.reader(lines):
        if len(row) != len(head):
            continue
        r = dict(zip(head, row))
        t, sym, ltp = r.get("time", "")[11:16], r.get("symbol", ""), _f(r.get("ltp"))
        if sym and t and ltp > 0:
            step(_S["sym"], sym, t, ltp, _f(r.get("volume")), _f(r.get("imbalance")))
            if t > _S["last_time"]:
                _S["last_time"] = t


def _sector_map(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        with (root / "data" / "reference" / "fno_sector_map.csv").open(encoding="utf-8-sig", newline="") as handle:
            for r in csv.DictReader(handle):
                out[r["symbol"]] = r["sector"]
    except OSError:
        pass
    return out


def _market_rows(root: Path) -> dict[str, dict[str, Any]]:
    try:
        rows = (json.loads((root / "data" / "reports" / "fno_market_watch_latest.json").read_text(encoding="utf-8"))).get("rows", [])
    except (OSError, ValueError):
        return {}
    return {r["symbol"]: r for r in rows if r.get("symbol")}


def _minus(t: str, minutes: int) -> str:
    h, m = int(t[:2]), int(t[3:5])
    tot = max(0, h * 60 + m - minutes)
    return f"{tot // 60:02d}:{tot % 60:02d}"


def build(state: dict[str, Any], last_time: str, window: int, sectors: dict[str, str], market: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cutoff = _minus(last_time, window) if window > 0 and last_time else "00:00"
    stocks = []
    for sym, s in state.items():
        buy = sum(b for t, b, _x in s["ev"] if t > cutoff)
        sell = sum(x for t, _b, x in s["ev"] if t > cutoff)
        total = buy + sell
        m = market.get(sym, {})
        prev = _f(m.get("previous_close"))
        imb = sum(s["imb"]) / len(s["imb"]) if s["imb"] else 0.0
        stocks.append({"symbol": sym, "sector": m.get("sector") or sectors.get(sym) or "Other", "ltp": round(s["lp"], 2),
                       "chg_pct": round((s["lp"] / prev - 1) * 100, 2) if prev > 0 else None,
                       "buy_cr": round(buy / CR, 2), "sell_cr": round(sell / CR, 2), "net_cr": round((buy - sell) / CR, 2), "traded_cr": round(total / CR, 2),
                       "flow_pct": round((buy - sell) / total * 100, 1) if total > 0 else 0.0, "imbalance": round(imb, 2)})
    groups: dict[str, list[dict[str, Any]]] = {}
    for st in stocks:
        groups.setdefault(st["sector"], []).append(st)
    secs = []
    for name, items in groups.items():
        buy, sell = sum(i["buy_cr"] for i in items), sum(i["sell_cr"] for i in items)
        total = buy + sell
        chg = [i["chg_pct"] for i in items if i["chg_pct"] is not None]
        ranked = sorted(items, key=lambda i: i["net_cr"])
        secs.append({"sector": name, "stocks": len(items), "buy_cr": round(buy, 1), "sell_cr": round(sell, 1), "net_cr": round(buy - sell, 1),
                     "flow_pct": round((buy - sell) / total * 100, 1) if total > 0 else 0.0, "chg_pct": round(sum(chg) / len(chg), 2) if chg else None,
                     "up": sum(1 for c in chg if c > 0), "down": sum(1 for c in chg if c < 0),
                     "top_in": [{"symbol": i["symbol"], "net_cr": i["net_cr"]} for i in ranked[::-1][:3] if i["net_cr"] > 0],
                     "top_out": [{"symbol": i["symbol"], "net_cr": i["net_cr"]} for i in ranked[:3] if i["net_cr"] < 0]})
    secs.sort(key=lambda x: -x["net_cr"])
    stocks.sort(key=lambda x: -x["net_cr"])
    buy_all, sell_all = sum(s["buy_cr"] for s in stocks), sum(s["sell_cr"] for s in stocks)
    tot = buy_all + sell_all
    return {"ok": True, "as_of": last_time, "window": window, "since": cutoff if window else "09:15",
            "market": {"buy_cr": round(buy_all, 1), "sell_cr": round(sell_all, 1), "net_cr": round(buy_all - sell_all, 1),
                       "flow_pct": round((buy_all - sell_all) / tot * 100, 1) if tot > 0 else 0.0,
                       "stocks_in": sum(1 for s in stocks if s["net_cr"] > 0), "stocks_out": sum(1 for s in stocks if s["net_cr"] < 0)},
            "sectors": secs, "stocks": stocks}


def payload(window: int = 0, root: Path = ROOT, today: date | None = None) -> dict[str, Any]:
    window = window if window in (0, 15, 30, 60) else 0
    with _LOCK:
        try:
            _refresh(root, today or date.today())
        except Exception:                                  # noqa: BLE001 - the page must still load
            pass
        if not _S["last_time"]:
            return {"ok": False, "error": "no order-book readings yet today (the recorder runs 09:15-15:30)", "sectors": [], "stocks": []}
        return build(_S["sym"], _S["last_time"], window, _sector_map(root), _market_rows(root))


MONEY_FLOW_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Money Flow</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--green:#2ecc71;--red:#ff6363;--blue:#4c8dff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.4 -apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1250px;margin:0 auto;padding:14px}h1{font-size:22px;margin:6px 0 2px}.sub{color:var(--muted);font-size:12.5px}a.nav{color:var(--blue);text-decoration:none;font-weight:700;margin-right:12px}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0}button,input{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 12px;font:inherit;font-weight:700;cursor:pointer}
button.on{background:var(--blue);border-color:var(--blue)}input{font-weight:500;min-width:170px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:8px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px}.card .l{color:var(--muted);font-size:11.5px}.card .v{font-size:20px;font-weight:800}
.up{color:var(--green);font-weight:700}.dn{color:var(--red);font-weight:700}
.sec{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:8px 0;cursor:pointer}.sec:hover{border-color:var(--blue)}
.row{display:grid;grid-template-columns:200px 1fr 130px;gap:12px;align-items:center}.track{position:relative;height:16px;background:#0f1729;border-radius:6px}.mid{position:absolute;left:50%;top:0;bottom:0;width:1px;background:#3a4968}
.fill{position:absolute;top:1px;bottom:1px;border-radius:5px}.chips{color:var(--muted);font-size:12px;margin-top:4px}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:12px}table{border-collapse:collapse;width:100%;background:var(--panel)}th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{background:#18223a;color:var(--muted);font-size:12px;cursor:pointer}td.n,th.n{text-align:right}.sym{font-weight:800}
@media(max-width:700px){.row{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<div><a class="nav" href="/">Dashboard</a><a class="nav" href="/live-scanner">Live scanner</a><a class="nav" href="/fno-market-watch">Market watch</a><a class="nav" href="/journal">Journal</a></div>
<h1>Money Flow &amp; Sector Spotlight</h1><div class="sub" id="asof">loading...</div>
<div class="bar"><span id="w"><button data-w="0" class="on">Today</button> <button data-w="60">Last 60 min</button> <button data-w="30">Last 30 min</button> <button data-w="15">Last 15 min</button></span>
<span id="t"><button data-t="S" class="on">Sectors</button> <button data-t="K">Stocks</button></span><input id="q" placeholder="Search stock..."></div>
<div class="cards" id="cards"></div><div id="view"></div>
<div class="sub" style="margin-top:12px">Net flow = buying value minus selling value in Rs crore, estimated from minute-by-minute price ticks and volume (up-tick = buying, down-tick = selling). It shows where traded money is concentrating; it cannot tell institutions from retail and is not a trade signal. Read-only.</div>
</div><script>
var w=0,tab="S",D=null,sel=null,sortk="net_cr",sortd=-1;
function c(n){return n>0?"up":n<0?"dn":""}function f(n,d){return (n>0?"+":"")+Number(n).toFixed(d==null?1:d)}
function load(){fetch("/api/money-flow?window="+w,{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){D=d;render()}).catch(function(){document.getElementById("asof").textContent="connection lost - retrying"})}
function render(){if(!D)return;if(!D.ok){document.getElementById("asof").textContent=D.error||"no data";document.getElementById("view").innerHTML="";return}
 var m=D.market;document.getElementById("asof").textContent="Readings to "+D.as_of+" - flow since "+D.since+(w?" (last "+w+" min)":" (whole session)");
 document.getElementById("cards").innerHTML=[["Market net flow",f(m.net_cr)+" cr",c(m.net_cr)],["Buying / selling",m.buy_cr+" / "+m.sell_cr+" cr",""],["Flow %",f(m.flow_pct)+"%",c(m.flow_pct)],["Stocks in / out",m.stocks_in+" / "+m.stocks_out,""]].map(function(x){return '<div class="card"><div class="l">'+x[0]+'</div><div class="v '+x[2]+'">'+x[1]+'</div></div>'}).join("");
 var q=document.getElementById("q").value.trim().toUpperCase(),v=document.getElementById("view");
 if(tab==="S"&&!q){var mx=Math.max.apply(null,D.sectors.map(function(s){return Math.abs(s.flow_pct)}))||1;
  v.innerHTML=D.sectors.map(function(s){var wd=Math.min(50,Math.abs(s.flow_pct)/mx*50),pos=s.flow_pct>=0;
   var ins=s.top_in.map(function(x){return x.symbol+" "+f(x.net_cr)}).join(", "),outs=s.top_out.map(function(x){return x.symbol+" "+f(x.net_cr)}).join(", ");
   return '<div class="sec" data-s="'+s.sector+'"><div class="row"><div><b>'+s.sector+'</b><div class="sub">'+s.stocks+' stocks, '+s.up+' up / '+s.down+' down'+(s.chg_pct==null?"":", avg "+f(s.chg_pct,2)+"%")+'</div></div>'
   +'<div class="track"><div class="mid"></div><div class="fill" style="background:'+(pos?"#2ecc71":"#ff6363")+';'+(pos?"left:50%":"right:50%")+';width:'+wd+'%"></div></div>'
   +'<div style="text-align:right"><span class="'+c(s.net_cr)+'">'+f(s.net_cr)+' cr</span><div class="sub">'+f(s.flow_pct)+'% of '+(s.buy_cr+s.sell_cr).toFixed(0)+' cr</div></div></div>'
   +'<div class="chips">In: <span class="up">'+(ins||"-")+'</span> &nbsp; Out: <span class="dn">'+(outs||"-")+'</span></div></div>'}).join("");return}
 var rows=D.stocks.filter(function(s){return (!sel||s.sector===sel)&&(!q||s.symbol.indexOf(q)>=0)});
 rows.sort(function(a,b){var x=a[sortk],y=b[sortk];if(typeof x==="string")return sortd*x.localeCompare(y);return sortd*((x==null?-1e9:x)-(y==null?-1e9:y))});
 var h=[["symbol","Stock"],["sector","Sector"],["ltp","LTP"],["chg_pct","Chg %"],["net_cr","Net flow cr"],["flow_pct","Flow %"],["buy_cr","Buy cr"],["sell_cr","Sell cr"],["traded_cr","Traded cr"],["imbalance","Order book"]];
 v.innerHTML=(sel?'<div class="sub" style="margin-bottom:6px">Sector: <b>'+sel+'</b> <button id="clr">Show all</button></div>':"")+'<div class="scroll"><table><thead><tr>'+h.map(function(x,i){return '<th class="'+(i>1?"n":"")+'" data-k="'+x[0]+'">'+x[1]+(sortk===x[0]?(sortd<0?" &#9660;":" &#9650;"):"")+'</th>'}).join("")+'</tr></thead><tbody>'
  +rows.map(function(s){return '<tr><td class="sym">'+s.symbol+'</td><td>'+s.sector+'</td><td class="n">'+s.ltp+'</td><td class="n '+c(s.chg_pct)+'">'+(s.chg_pct==null?"-":f(s.chg_pct,2))+'</td><td class="n '+c(s.net_cr)+'">'+f(s.net_cr,2)+'</td><td class="n '+c(s.flow_pct)+'">'+f(s.flow_pct)+'</td><td class="n">'+s.buy_cr+'</td><td class="n">'+s.sell_cr+'</td><td class="n">'+s.traded_cr+'</td><td class="n '+c(s.imbalance)+'">'+f(s.imbalance,2)+'</td></tr>'}).join("")+'</tbody></table></div>'}
document.getElementById("w").addEventListener("click",function(e){var b=e.target.closest("button");if(!b)return;w=parseInt(b.getAttribute("data-w"),10);[].forEach.call(this.querySelectorAll("button"),function(x){x.className=x===b?"on":""});load()});
document.getElementById("t").addEventListener("click",function(e){var b=e.target.closest("button");if(!b)return;tab=b.getAttribute("data-t");sel=null;[].forEach.call(this.querySelectorAll("button"),function(x){x.className=x===b?"on":""});render()});
document.getElementById("q").addEventListener("input",render);
document.getElementById("view").addEventListener("click",function(e){var s=e.target.closest(".sec");if(s){sel=s.getAttribute("data-s");tab="K";[].forEach.call(document.querySelectorAll("#t button"),function(x){x.className=x.getAttribute("data-t")==="K"?"on":""});render();return}
 if(e.target.id==="clr"){sel=null;render();return}var th=e.target.closest("th");if(th){var k=th.getAttribute("data-k");if(sortk===k)sortd=-sortd;else{sortk=k;sortd=k==="symbol"||k==="sector"?1:-1}render()}});
load();setInterval(load,20000);
</script></body></html>
"""
