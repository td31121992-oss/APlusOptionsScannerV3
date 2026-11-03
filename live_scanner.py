"""Live Market Scanner: a running feed of breakout events across the F&O stocks, like a broker's live scanner. Read-only.

Built from the order-book recorder's once-a-minute readings (data/order_book/<date>.csv) plus the previous-day levels in
data/reports/daily_indicators.json. Event types (each stock/event is rate-limited so the feed stays readable):
  DAY_HIGH   new high of the day (bullish)            DAY_LOW    new low of the day (bearish)
  PDH_BREAK  first trade above the previous day high   PDL_BREAK  first trade below the previous day low
  NEAR_HIGH  within 0.15% under the day high           NEAR_LOW   within 0.15% above the day low
  VOLUME     last 5 minutes' volume >= 3x its usual 5-minute pace
  RISE / FALL  up / down 1% or more over the last 5 minutes
Events before 09:20 are ignored (the opening minutes would flood the feed). Describes what happened; it is not a signal to trade.
"""

from __future__ import annotations

import csv
import json
import threading
from collections import deque
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parent
MAX_EVENTS = 30000
LABELS = {"DAY_HIGH": "Day High", "DAY_LOW": "Day Low", "PDH_BREAK": "Above previous day high", "PDL_BREAK": "Below previous day low",
          "NEAR_HIGH": "Nearing day high", "NEAR_LOW": "Nearing day low", "VOLUME": "Volume surge", "RISE": "Rise 1%+ in 5m", "FALL": "Fall 1%+ in 5m"}
GROUPS = {"BULLISH": ("DAY_HIGH", "PDH_BREAK"), "BEARISH": ("DAY_LOW", "PDL_BREAK"), "NEAR_HIGH": ("NEAR_HIGH",), "NEAR_LOW": ("NEAR_LOW",),
          "VOLUME": ("VOLUME",), "RISEFALL": ("RISE", "FALL")}
_LOCK = threading.Lock()
_S: dict[str, Any] = {"key": None, "offset": 0, "header": None, "sym": {}, "events": deque(maxlen=MAX_EVENTS), "indicators": {}}


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def _reset(key: str, root: Path) -> None:
    try:
        ind = json.loads((root / "data" / "reports" / "daily_indicators.json").read_text(encoding="utf-8")).get("symbols", {})
    except (OSError, ValueError):
        ind = {}
    _S.update(key=key, offset=0, header=None, sym={}, events=deque(maxlen=MAX_EVENTS), indicators=ind)


def _step(sym: str, ltp: float, vol: float, t: str, st: dict[str, Any], ind: dict[str, Any], out: deque) -> None:
    s = st.setdefault(sym, {"hi": ltp, "lo": ltp, "n": 0, "ltps": deque(maxlen=6), "vols": deque(maxlen=6), "buckets": [], "last": {},
                            "pdh_done": False, "pdl_done": False})
    s["n"] += 1
    n = s["n"]
    s["ltps"].append(ltp)
    s["vols"].append(vol)
    live = t >= "09:20"

    def emit(kind: str, gap: int = 0) -> None:
        if not live or (gap and n - s["last"].get(kind, -999) < gap):
            return
        s["last"][kind] = n
        out.append({"time": t, "symbol": sym, "kind": kind, "label": LABELS[kind], "ltp": ltp, "volume": vol,
                    "bull": kind in ("DAY_HIGH", "PDH_BREAK", "RISE", "NEAR_HIGH")})

    prev_hi, prev_lo = s["hi"], s["lo"]
    if ltp > prev_hi:
        s["hi"] = ltp
        emit("DAY_HIGH", 1)
    elif ltp < prev_lo:
        s["lo"] = ltp
        emit("DAY_LOW", 1)
    else:
        if prev_hi > 0 and (prev_hi - ltp) / prev_hi <= 0.0015 and prev_hi > prev_lo:
            emit("NEAR_HIGH", 15)
        if prev_lo > 0 and (ltp - prev_lo) / prev_lo <= 0.0015 and prev_hi > prev_lo:
            emit("NEAR_LOW", 15)
    pdh, pdl = _f(ind.get("pdh")), _f(ind.get("pdl"))
    if pdh and not s["pdh_done"] and ltp > pdh:
        s["pdh_done"] = True
        emit("PDH_BREAK")
    if pdl and not s["pdl_done"] and 0 < ltp < pdl:
        s["pdl_done"] = True
        emit("PDL_BREAK")
    if len(s["ltps"]) >= 6 and s["ltps"][0] > 0:
        mv = (ltp / s["ltps"][0] - 1) * 100
        if mv >= 1.0:
            emit("RISE", 10)
        elif mv <= -1.0:
            emit("FALL", 10)
    if n % 5 == 0 and len(s["vols"]) >= 6 and s["vols"][-1] >= s["vols"][0]:
        b = s["vols"][-1] - s["vols"][0]
        past = s["buckets"][-8:]
        if len(past) >= 4 and median(past) > 0 and b >= 3 * median(past):
            emit("VOLUME", 15)
        s["buckets"].append(b)


def _refresh(root: Path, day: date) -> None:
    path = root / "data" / "order_book" / f"{day.isoformat()}.csv"
    key = f"{root}|{day}"
    if _S["key"] != key:
        _reset(key, root)
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size < _S["offset"]:
        _reset(key, root)
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
        ltp = _f(r.get("ltp"))
        sym, t = r.get("symbol", ""), r.get("time", "")[11:16]
        if sym and ltp > 0 and t:
            _step(sym, ltp, _f(r.get("volume")), t, _S["sym"], _S["indicators"].get(sym) or {}, _S["events"])


def payload(group: str = "ALL", limit: int = 200, root: Path = ROOT, today: date | None = None) -> dict[str, Any]:
    with _LOCK:
        try:
            _refresh(root, today or date.today())
        except Exception:                                  # noqa: BLE001 - the page must still load
            pass
        events = list(_S["events"])
    kinds = GROUPS.get(group)
    counts = {g: sum(1 for e in events if e["kind"] in ks) for g, ks in GROUPS.items()}
    shown = [e for e in events if kinds is None or e["kind"] in kinds]
    shown.reverse()
    return {"ok": True, "counts": counts, "total": len(events), "events": shown[: max(1, min(int(limit), 1000))]}


LIVE_SCANNER_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Live Market Scanner</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--green:#2ecc71;--red:#ff6363;--amber:#f5b942;--blue:#4c8dff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.35 -apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1200px;margin:0 auto;padding:14px}h1{font-size:22px;margin:6px 0 2px}.sub{color:var(--muted);font-size:12.5px}
a.nav{color:var(--blue);text-decoration:none;font-weight:700;margin-right:12px}
.bar{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.chip{padding:8px 12px;border:1px solid var(--line);border-radius:10px;background:var(--panel);color:var(--text);font-weight:700;cursor:pointer}
.chip.on{border-color:var(--blue);background:#14264a}.chip b{display:inline-block;margin-left:6px;background:#1d4ed8;color:#fff;border-radius:6px;padding:0 7px;font-size:12px}
input{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:8px 12px;min-width:200px}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:12px}table{border-collapse:collapse;width:100%;background:var(--panel)}
th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{background:#18223a;color:var(--muted);font-size:12px;position:sticky;top:0}
td.n,th.n{text-align:right}.up{color:var(--green);font-weight:700}.dn{color:var(--red);font-weight:700}.am{color:var(--amber);font-weight:700}.sym{font-weight:800}
</style></head><body><div class="wrap">
<div><a class="nav" href="/">Dashboard</a><a class="nav" href="/positions">Positions</a><a class="nav" href="/decision-desk">Decision desk</a><a class="nav" href="/fno-market-watch">Market watch</a></div>
<h1>Live Market Scanner</h1><div class="sub" id="asof">loading...</div>
<div class="bar" id="chips"><span class="chip on" data-g="ALL">All <b id="c_ALL">0</b></span><span class="chip" data-g="BULLISH">Bullish signal <b id="c_BULLISH">0</b></span><span class="chip" data-g="BEARISH">Bearish signal <b id="c_BEARISH">0</b></span><span class="chip" data-g="NEAR_HIGH">Nearing high <b id="c_NEAR_HIGH">0</b></span><span class="chip" data-g="NEAR_LOW">Nearing low <b id="c_NEAR_LOW">0</b></span><span class="chip" data-g="RISEFALL">Rise &amp; fall <b id="c_RISEFALL">0</b></span><span class="chip" data-g="VOLUME">Volume signal <b id="c_VOLUME">0</b></span><input id="q" placeholder="Search stock..."></div>
<div class="scroll"><table><thead><tr><th>Name</th><th>Breakout for</th><th class="n">LTP</th><th class="n">Volume</th><th class="n">Time</th></tr></thead><tbody id="rows"></tbody></table></div>
<div class="sub" style="margin-top:10px">Built from our own once-a-minute price readings for the 213 F&amp;O stocks, so each stock shows at most one event per minute. It describes what just happened; it is not a trade signal. Read-only.</div>
</div><script>
var g="ALL";
function money(n){return Number(n).toLocaleString("en-IN",{maximumFractionDigits:2,minimumFractionDigits:2})}
function load(){fetch("/api/live-scanner?group="+g+"&limit=300",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){
 var q=document.getElementById("q").value.trim().toUpperCase();
 document.getElementById("c_ALL").textContent=d.total;for(var k in d.counts){var e=document.getElementById("c_"+k);if(e)e.textContent=d.counts[k]}
 document.getElementById("asof").textContent="Updated "+new Date().toLocaleTimeString()+" - "+d.total+" events today";
 var ev=d.events.filter(function(x){return !q||x.symbol.indexOf(q)>=0});
 document.getElementById("rows").innerHTML=ev.length?ev.map(function(x){var c=x.kind==="VOLUME"?"am":(x.bull?"up":"dn"),a=x.kind==="VOLUME"?"&#9650;&#9660;":(x.bull?"&#9650;":"&#9660;");
  return '<tr><td class="sym">'+x.symbol+'</td><td class="'+c+'">'+a+' '+x.label+'</td><td class="n">'+money(x.ltp)+'</td><td class="n">'+Number(x.volume).toLocaleString("en-IN")+'</td><td class="n">'+x.time+'</td></tr>'}).join(""):'<tr><td colspan="5" class="sub" style="padding:24px;text-align:center">No events yet</td></tr>'}).catch(function(){document.getElementById("asof").textContent="connection lost - retrying"})}
document.getElementById("chips").addEventListener("click",function(e){var t=e.target.closest(".chip");if(!t)return;g=t.getAttribute("data-g");[].forEach.call(document.querySelectorAll(".chip"),function(c){c.className="chip"+(c===t?" on":"")});load()});
document.getElementById("q").addEventListener("input",load);load();setInterval(load,8000);
</script></body></html>
"""
