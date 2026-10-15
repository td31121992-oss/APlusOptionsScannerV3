"""Premium Tracker: how much option premium (Rs crore) traded in each F&O stock, split call vs put (READ-ONLY, display only).

    /premium                 the page
    /api/premium-tracker     JSON for the page
    python premium_tracker.py [YYYY-MM-DD]     compute now and write the day's history file

Premium traded = volume x average traded price, summed over the two nearest expiries and STRIKES strikes either side of the money for
every F&O stock (about 17,000 contracts, 20 quote calls; the ATM region carries nearly all of the premium). The history file
data/premium_tracker/<day>.csv (written by the 15:40 job and by `python premium_tracker.py`) gives each stock's own 10-day average,
so "3x its normal premium" is visible.
"""

from __future__ import annotations

import csv
import glob
import json
import os
import statistics as st
import threading
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
EXPIRIES = 2
STRIKES = 10
CR = 1e7
REFRESH_SECONDS = 300
FIELDS = ["day", "symbol", "ce_cr", "pe_cr", "total_cr", "ce_share", "stock_pct"]
_STATE: dict[str, Any] = {"data": None, "at": 0.0, "loading": False, "error": ""}


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def aggregate(quotes: dict[int, dict[str, Any]], meta: dict[int, tuple[str, str]], stock_pct: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """quotes: security_id -> quote; meta: security_id -> (symbol, 'CE'|'PE'). One row per stock, sorted by total premium."""
    ce: dict[str, float] = defaultdict(float)
    pe: dict[str, float] = defaultdict(float)
    for sid, q in quotes.items():
        info = meta.get(int(sid))
        if not info or not q:
            continue
        prem = _f(q.get("volume")) * _f(q.get("average_price"))
        (ce if info[1] == "CE" else pe)[info[0]] += prem
    rows = []
    for s in set(ce) | set(pe):
        c, p = ce[s] / CR, pe[s] / CR
        if c + p <= 0:
            continue
        rows.append({"symbol": s, "ce_cr": round(c, 2), "pe_cr": round(p, 2), "total_cr": round(c + p, 2),
                     "ce_share": round(100.0 * c / (c + p), 1), "stock_pct": round((stock_pct or {}).get(s, 0.0), 2)})
    rows.sort(key=lambda r: -r["total_cr"])
    return rows


def overall(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ce = sum(r["ce_cr"] for r in rows)
    pe = sum(r["pe_cr"] for r in rows)
    big = [r for r in rows if r["total_cr"] >= 5.0]
    return {"ce_cr": round(ce, 1), "pe_cr": round(pe, 1), "total_cr": round(ce + pe, 1), "ce_share": round(100.0 * ce / (ce + pe), 1) if ce + pe else 0.0,
            "top": rows[0] if rows else None,
            "ce_heavy": max(big, key=lambda r: r["ce_share"]) if big else None,
            "pe_heavy": min(big, key=lambda r: r["ce_share"]) if big else None}


def compute(day: str | None = None, root: Path = ROOT, quote: Callable[[str, list[int]], dict[str, Any]] | None = None,
            stock_pct_override: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Fetch the quotes and return the rows. `quote(segment, ids)` is injectable for tests."""
    import pandas as pd

    day = day or date.today().isoformat()
    if quote is None:
        import requests
        from dotenv import load_dotenv

        load_dotenv(root / ".env")
        from dhan_auth import resolve_access_token

        cid = os.getenv("DHAN_CLIENT_ID", "").strip()
        token = resolve_access_token(project_root=root, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
        headers = {"access-token": token, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"}

        def quote(segment: str, ids: list[int]) -> dict[str, Any]:                     # noqa: F811
            out: dict[str, Any] = {}
            for i in range(0, len(ids), 900):
                for attempt in range(3):
                    r = requests.post("https://api.dhan.co/v2/marketfeed/quote", headers=headers, timeout=40, json={segment: ids[i:i + 900]})
                    if r.status_code == 200:
                        out.update((r.json().get("data") or {}).get(segment) or {})
                        break
                    time.sleep(1.5 * (attempt + 1))
                time.sleep(0.3)
            return out

    import sys

    sys.path.insert(0, str(root))
    from order_book_recorder import _universe

    universe = _universe()
    by_id = {v: k for k, v in universe.items()}
    eq = quote("NSE_EQ", list(universe.values()))
    px = {by_id.get(int(k)): _f(v.get("last_price")) for k, v in eq.items()}
    stock_pct = dict(stock_pct_override or {})
    for k, v in eq.items():
        s = by_id.get(int(k))
        net, last = _f(v.get("net_change")), _f(v.get("last_price"))
        if s not in stock_pct and last > 0 and last - net > 0:
            stock_pct[s] = net / (last - net) * 100.0
    m = pd.read_csv(root / "data" / "cache" / "api-scrip-master-detailed.csv", low_memory=False,
                    usecols=["SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL", "SM_EXPIRY_DATE", "STRIKE_PRICE", "OPTION_TYPE"])
    m = m[m.INSTRUMENT == "OPTSTK"].copy()
    m["exp"] = m.SM_EXPIRY_DATE.astype(str).str[:10]
    m = m[m.exp >= day]
    meta: dict[int, tuple[str, str]] = {}
    for sym, g in m.groupby("UNDERLYING_SYMBOL"):
        p = px.get(sym) or 0.0
        if p <= 0:
            continue
        for e in sorted(g.exp.unique())[:EXPIRIES]:
            ge = g[g.exp == e]
            ks = sorted({float(x) for x in ge.STRIKE_PRICE})
            if not ks:
                continue
            a = min(range(len(ks)), key=lambda i: abs(ks[i] - p))
            keep = set(ks[max(0, a - STRIKES):a + STRIKES + 1])
            for r in ge.itertuples():
                if float(r.STRIKE_PRICE) in keep:
                    meta[int(r.SECURITY_ID)] = (sym, str(r.OPTION_TYPE))
    data = quote("NSE_FNO", list(meta))
    return aggregate({int(k): v for k, v in data.items()}, meta, stock_pct)


# ----------------------------------------------------------------------------- history
def record(day: str, rows: list[dict[str, Any]], root: Path = ROOT) -> Path:
    folder = root / "data" / "premium_tracker"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.csv"
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({"day": day, **r})
    return path


def history_means(root: Path = ROOT, before: str | None = None, days: int = 10) -> dict[str, tuple[float, int]]:
    """symbol -> (mean total premium Rs Cr over the last `days` recorded days before `before`, number of days)."""
    files = sorted(glob.glob(str(root / "data" / "premium_tracker" / "20*.csv")))
    files = [f for f in files if before is None or Path(f).stem < before][-days:]
    acc: dict[str, list[float]] = defaultdict(list)
    for f in files:
        with open(f, encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                acc[r["symbol"]].append(_f(r.get("total_cr")))
    return {s: (st.mean(v), len(v)) for s, v in acc.items() if v}


def enrich(rows: list[dict[str, Any]], root: Path = ROOT, day: str | None = None) -> list[dict[str, Any]]:
    means = history_means(root, before=day or date.today().isoformat())
    for r in rows:
        m = means.get(r["symbol"])
        if m and m[1] >= 3 and m[0] > 0:
            r["x_avg"] = round(r["total_cr"] / m[0], 1)
            r["avg_days"] = m[1]
    return rows


def telegram_lines(rows: list[dict[str, Any]], top: int = 3) -> list[str]:
    if not rows:
        return []
    o = overall(rows)
    out = ["", "\U0001F4B0 PREMIUM TRACKER (option premium traded)"]
    for i, r in enumerate(rows[:top], 1):
        x = f"  {r['x_avg']:.1f}x avg" if r.get("x_avg") else ""
        out.append(f"{i}. {r['symbol']}  ₹{r['total_cr']:,.0f} Cr  (CE {r['ce_share']:.0f}% / PE {100 - r['ce_share']:.0f}%){x}")
    out.append(f"Market: CE ₹{o['ce_cr']:,.0f} Cr / PE ₹{o['pe_cr']:,.0f} Cr  ({o['ce_share']:.0f}% calls)")
    return out


# ----------------------------------------------------------------------------- page data (computed in a background thread, cached)
def _refresh(root: Path) -> None:
    try:
        rows = compute(None, root)
        today = date.today().isoformat()
        _STATE.update({"data": enrich(rows, root, today), "at": time.time(), "error": "", "day": today})
    except Exception as exc:                               # noqa: BLE001
        _STATE["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        _STATE["loading"] = False


def payload(root: Path = ROOT) -> dict[str, Any]:
    stale = time.time() - _STATE["at"] > REFRESH_SECONDS
    if stale and not _STATE["loading"]:
        _STATE["loading"] = True
        threading.Thread(target=_refresh, args=(root,), daemon=True).start()
        if _STATE["data"] is None:                         # first request: the previous day's file is shown while the live numbers load
            files = sorted(glob.glob(str(root / "data" / "premium_tracker" / "20*.csv")))
            if files:
                with open(files[-1], encoding="utf-8", newline="") as h:
                    rows = [{**r, "ce_cr": _f(r["ce_cr"]), "pe_cr": _f(r["pe_cr"]), "total_cr": _f(r["total_cr"]), "ce_share": _f(r["ce_share"]),
                             "stock_pct": _f(r.get("stock_pct"))} for r in csv.DictReader(h)]
                return {"ok": True, "rows": enrich(rows, root, Path(files[-1]).stem), "overall": overall(rows), "loading": True,
                        "as_of": Path(files[-1]).stem, "stale": True}
    rows = _STATE.get("data")
    if rows is None:
        return {"ok": True, "rows": [], "overall": overall([]), "loading": True, "as_of": "", "error": _STATE.get("error", "")}
    return {"ok": True, "rows": rows, "overall": overall(rows), "loading": bool(_STATE["loading"]), "as_of": _STATE.get("day", ""),
            "updated": datetime.fromtimestamp(_STATE["at"]).strftime("%H:%M:%S"), "error": _STATE.get("error", ""), "stale": False}


PREMIUM_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Premium Tracker</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--green:#19d38a;--red:#ff4d6a;--amber:#f5b942}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.4 -apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1400px;margin:0 auto;padding:12px 14px 40px}a{color:#4c8dff;text-decoration:none;font-weight:700}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:10px 0}@media(max-width:900px){.cards{grid-template-columns:1fr 1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}.card small{color:var(--muted);font-size:11px;letter-spacing:.07em}
.big{font-size:26px;font-weight:900;margin-top:4px}.green{color:var(--green)}.red{color:var(--red)}.muted{color:var(--muted)}
.split{height:16px;border-radius:8px;overflow:hidden;display:flex;margin:6px 0 2px;background:#1d2842}.split i{display:block;height:100%}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);font-size:13px;white-space:nowrap}th{color:var(--muted);text-align:right;cursor:pointer;background:#0f1729;position:sticky;top:0}
th:first-child,td:first-child{text-align:left}td{text-align:right}th.on{color:var(--green)}
.bar{display:inline-block;width:110px;height:8px;border-radius:4px;background:#ff4d6a55;vertical-align:middle;margin-left:8px;overflow:hidden}.bar i{display:block;height:100%;background:var(--green)}
input{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:7px 10px;font-size:13px}
</style></head><body><div class="wrap">
<div><a href="/">&larr; Dashboard</a> &nbsp; <a href="/xray">Market X-Ray</a> &nbsp; <a href="/fno-market-watch">Market Watch</a></div>
<h1 style="margin:10px 0 0;font-size:24px">Premium Tracker</h1>
<div class="muted" id="sub">loading...</div>
<div class="cards">
 <div class="card"><small>TOTAL PREMIUM TRADED</small><div class="big" id="tot">-</div><div class="muted" id="totsub"></div></div>
 <div class="card"><small>TOP PREMIUM STOCK</small><div class="big" id="top">-</div><div class="muted" id="topsub"></div></div>
 <div class="card"><small>MOST CE-HEAVY</small><div class="big green" id="ceh">-</div><div class="muted" id="cehsub"></div></div>
 <div class="card"><small>MOST PE-HEAVY</small><div class="big red" id="peh">-</div><div class="muted" id="pehsub"></div></div>
</div>
<div class="card"><small>OVERALL CE vs PE PREMIUM SPLIT</small><div class="split"><i id="cebar" style="background:#19d38a"></i><i id="pebar" style="background:#ff4d6a"></i></div>
 <div class="muted" id="splitlbl"></div></div>
<div style="margin:10px 0"><input id="q" placeholder="Search stock..." oninput="draw()"> <span class="muted">Click a column header to sort. "x avg" = today's premium over that stock's own 10-day average.</span></div>
<table><thead><tr><th data-k="symbol">Stock</th><th data-k="ce_cr">CE premium (&#8377; Cr)</th><th data-k="pe_cr">PE premium (&#8377; Cr)</th>
<th data-k="total_cr" class="on">Total (&#8377; Cr)</th><th data-k="ce_share">CE share</th><th data-k="x_avg">x avg</th><th data-k="stock_pct">Stock</th></tr></thead><tbody id="rows"></tbody></table>
<div class="muted" style="margin-top:10px;font-size:12px">Premium = volume x average traded price, two nearest expiries, 10 strikes either side of the money. Not investment advice.</div>
</div><script>
var D=null,key="total_cr",dir=-1;
function fmt(v,d){return Number(v).toLocaleString("en-IN",{minimumFractionDigits:d,maximumFractionDigits:d})}
function draw(){if(!D)return;var o=D.overall||{},q=document.getElementById("q").value.trim().toUpperCase();
 document.getElementById("sub").textContent=(D.loading?"Refreshing... ":"")+(D.as_of?"Trading day "+D.as_of+" - ":"")+(D.updated?"updated "+D.updated:"")+(D.stale?" (showing the last saved day while live numbers load)":"")+(D.error?" - "+D.error:"");
 document.getElementById("tot").textContent=o.total_cr?"₹"+fmt(o.total_cr,0)+" Cr":"-";
 document.getElementById("totsub").textContent=o.total_cr?"CE ₹"+fmt(o.ce_cr,0)+" Cr / PE ₹"+fmt(o.pe_cr,0)+" Cr":"";
 var t=o.top;document.getElementById("top").textContent=t?t.symbol:"-";document.getElementById("topsub").textContent=t?"₹"+fmt(t.total_cr,1)+" Cr total":"";
 var c=o.ce_heavy;document.getElementById("ceh").textContent=c?c.symbol:"-";document.getElementById("cehsub").textContent=c?fmt(c.ce_share,1)+"% of premium is CE":"";
 var p=o.pe_heavy;document.getElementById("peh").textContent=p?p.symbol:"-";document.getElementById("pehsub").textContent=p?fmt(100-p.ce_share,1)+"% of premium is PE":"";
 document.getElementById("cebar").style.width=(o.ce_share||0)+"%";document.getElementById("pebar").style.width=(100-(o.ce_share||0))+"%";
 document.getElementById("splitlbl").textContent=o.total_cr?fmt(o.ce_share,1)+"% calls / "+fmt(100-o.ce_share,1)+"% puts":"";
 var a=(D.rows||[]).filter(function(r){return !q||r.symbol.indexOf(q)>=0}).slice();
 a.sort(function(x,y){var u=x[key],v=y[key];if(u==null)u=-1e9;if(v==null)v=-1e9;if(key==="symbol")return dir*(u<v?-1:u>v?1:0);return dir*(u-v)});
 document.getElementById("rows").innerHTML=a.map(function(r){var pc=r.stock_pct;
  return'<tr><td><a href="/stock-analysis?symbol='+encodeURIComponent(r.symbol)+'" style="color:var(--text)">'+r.symbol+'</a></td><td class="green">'+fmt(r.ce_cr,2)+'</td><td class="red">'+fmt(r.pe_cr,2)+'</td><td><b>'+fmt(r.total_cr,2)
   +'</b></td><td>'+fmt(r.ce_share,0)+'%<span class="bar"><i style="width:'+r.ce_share+'%"></i></span></td><td'+(r.x_avg>=2?' style="color:var(--amber);font-weight:800"':'')+'>'+(r.x_avg?r.x_avg.toFixed(1)+'x':'-')
   +'</td><td class="'+(pc>=0?"green":"red")+'">'+(pc>0?"+":"")+fmt(pc,2)+'%</td></tr>'}).join("")}
document.querySelectorAll("th").forEach(function(th){th.onclick=function(){var k=th.dataset.k;if(key===k)dir=-dir;else{key=k;dir=(k==="symbol")?1:-1}
 document.querySelectorAll("th").forEach(function(x){x.classList.toggle("on",x===th)});draw()}});
function load(){fetch("/api/premium-tracker",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){D=d;draw()}).catch(function(){})}
load();setInterval(load,20000);
</script></body></html>
"""


def main() -> int:
    import sys

    day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    rows = compute(day)
    print(record(day, rows))
    o = overall(rows)
    print(f"{len(rows)} stocks | CE {o['ce_cr']:,.0f} Cr | PE {o['pe_cr']:,.0f} Cr | calls {o['ce_share']:.0f}%")
    for line in telegram_lines(enrich(rows, ROOT, day)):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
