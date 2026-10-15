"""Top strip for the main dashboard: Paper/Live mode, market mood and every index with its move from today's OPEN and from
YESTERDAY'S CLOSE. Read-only (one cached Dhan quote call for all indices).

    /api/indices      JSON: rows for the main indices and the sector / broad indices

Yesterday's close comes from Dhan's daily history (cached once per day in data/cache/index_prev_close.json) because the quote's
own "close" is only yesterday's close during market hours: after 15:30 it already holds today's close.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")
SEGMENT = "IDX_I"

MAIN = [(13, "NIFTY 50"), (25, "BANK NIFTY"), (27, "FIN NIFTY"), (442, "MIDCAP SELECT"), (51, "SENSEX"), (38, "NIFTY NEXT 50"),
        (21, "INDIA VIX")]
SECTORS = [(29, "NIFTY IT"), (14, "NIFTY AUTO"), (32, "PHARMA"), (28, "FMCG"), (31, "METAL"), (33, "PSU BANK"), (34, "REALTY"),
           (42, "ENERGY"), (37, "MIDCAP 100"), (22, "SMALLCAP 50"), (19, "NIFTY 500")]
ALL = MAIN + SECTORS
NAMES = dict(ALL)
_QUOTE_TTL = 6.0
_state: dict[str, Any] = {"quote": None, "quote_at": 0.0, "prev": None, "prev_day": "", "prev_thread": None, "error": ""}
_lock = threading.Lock()


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def _headers(root: Path) -> dict[str, str]:
    from dotenv import load_dotenv

    load_dotenv(root / ".env")
    from dhan_auth import resolve_access_token

    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    token = resolve_access_token(project_root=root, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    return {"access-token": token, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"}


def _fetch_quotes(root: Path) -> dict[int, dict[str, float]]:
    import requests

    r = requests.post("https://api.dhan.co/v2/marketfeed/quote", headers=_headers(root), json={SEGMENT: [i for i, _ in ALL]}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"quote HTTP {r.status_code}")
    data = ((r.json() or {}).get("data") or {}).get(SEGMENT) or {}
    out: dict[int, dict[str, float]] = {}
    for key, v in data.items():
        o = (v or {}).get("ohlc") or {}
        out[int(key)] = {"ltp": _f(v.get("last_price")), "open": _f(o.get("open")), "close": _f(o.get("close"))}
    return out


def _fetch_prev_closes(root: Path) -> dict[int, float]:
    """Close of the last session BEFORE today for every index, from daily history."""
    import requests

    headers = _headers(root)
    today = datetime.now(IST).date()
    out: dict[int, float] = {}
    for sid, _ in ALL:
        try:
            r = requests.post("https://api.dhan.co/v2/charts/historical", headers=headers, timeout=20, json={
                "securityId": str(sid), "exchangeSegment": SEGMENT, "instrument": "INDEX", "expiryCode": 0, "oi": False,
                "fromDate": (today - timedelta(days=12)).isoformat(), "toDate": (today + timedelta(days=1)).isoformat()})
            d = r.json() if r.status_code == 200 else {}
            best = 0.0
            for ts, c in zip(d.get("timestamp") or [], d.get("close") or []):
                if datetime.fromtimestamp(int(ts), IST).date() < today:
                    best = _f(c)
            if best > 0:
                out[sid] = best
        except Exception:                                   # noqa: BLE001 - one index failing must not stop the rest
            continue
        time.sleep(0.4)
    return out


def _prev_cache_path(root: Path) -> Path:
    return root / "data" / "cache" / "index_prev_close.json"


def _load_prev(root: Path, today: str) -> dict[int, float] | None:
    try:
        d = json.loads(_prev_cache_path(root).read_text(encoding="utf-8"))
        if d.get("day") == today and d.get("closes"):
            return {int(k): float(v) for k, v in d["closes"].items()}
    except (OSError, ValueError):
        pass
    return None


def _ensure_prev(root: Path, today: str, fetch: Callable[[Path], dict[int, float]] = _fetch_prev_closes) -> dict[int, float] | None:
    """Return today's cached previous closes, or start a background fetch and return None until it finishes."""
    with _lock:
        if _state["prev"] is not None and _state["prev_day"] == today:
            return _state["prev"]
        cached = _load_prev(root, today)
        if cached:
            _state["prev"], _state["prev_day"] = cached, today
            return cached
        th = _state.get("prev_thread")
        if th is not None and th.is_alive():
            return None

        def work() -> None:
            try:
                closes = fetch(root)
                if len(closes) >= 5:
                    p = _prev_cache_path(root)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(json.dumps({"day": today, "closes": {str(k): v for k, v in closes.items()}}), encoding="utf-8")
                    with _lock:
                        _state["prev"], _state["prev_day"] = closes, today
            except Exception:                               # noqa: BLE001
                pass

        t = threading.Thread(target=work, daemon=True)
        _state["prev_thread"] = t
        t.start()
    return None


def build_rows(quotes: Mapping[int, Mapping[str, float]], prev: Mapping[int, float] | None, market_open: bool) -> list[dict[str, Any]]:
    rows = []
    for sid, name in ALL:
        q = quotes.get(sid) or {}
        ltp, op = _f(q.get("ltp")), _f(q.get("open"))
        pc = _f((prev or {}).get(sid))
        if pc <= 0 and market_open:                         # intraday the quote's close IS yesterday's close
            pc = _f(q.get("close"))
        rows.append({"id": sid, "name": name, "group": "main" if sid in dict(MAIN) else "sector", "ltp": ltp, "open": op, "prev_close": pc,
                     "pct_open": round((ltp / op - 1) * 100, 2) if ltp > 0 and op > 0 else None,
                     "pct_prev": round((ltp / pc - 1) * 100, 2) if ltp > 0 and pc > 0 else None,
                     "change": round(ltp - pc, 2) if ltp > 0 and pc > 0 else None})
    return rows


def payload(root: Path = ROOT, fetch_quotes: Callable[[Path], dict] = _fetch_quotes, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(IST)
    today = now.date().isoformat()
    market_open = now.weekday() < 5 and 9 * 60 + 15 <= now.hour * 60 + now.minute <= 15 * 60 + 30
    err = ""
    with _lock:
        fresh = _state["quote"] is not None and time.time() - _state["quote_at"] < _QUOTE_TTL
    if not fresh:
        try:
            q = fetch_quotes(root)
            with _lock:
                _state["quote"], _state["quote_at"], _state["error"] = q, time.time(), ""
        except Exception as exc:                            # noqa: BLE001
            err = f"{type(exc).__name__}: {str(exc)[:80]}"
            with _lock:
                _state["error"] = err
    with _lock:
        quotes, at = _state["quote"], _state["quote_at"]
    if not quotes:
        return {"ok": False, "error": err or "no quote yet", "rows": []}
    prev = _ensure_prev(root, today)
    rows = build_rows(quotes, prev, market_open)
    return {"ok": True, "error": err, "stale": bool(err), "updated": datetime.fromtimestamp(at, IST).strftime("%H:%M:%S"),
            "market_open": market_open, "prev_ready": prev is not None, "rows": rows}


STRIP_HTML = r"""
<style>
#aplus-index-strip{background:#0e1527;border-bottom:1px solid #27334d;padding:8px 14px;font-family:Segoe UI,Arial,sans-serif;color:#e7eefc}
#aplus-index-strip .ais-top{display:flex;gap:12px;align-items:stretch;flex-wrap:wrap}
#ais-left{display:flex;gap:10px;align-items:stretch;flex-wrap:wrap}
#ais-left #aplus-mode-bar,#ais-left #aplus-mood{position:static!important;max-width:none!important;box-shadow:none!important;margin:0!important;z-index:auto!important}
#ais-tiles,#ais-sectors{display:flex;gap:8px;flex-wrap:wrap}
#ais-verdict{margin:8px 0 2px;border:1px solid #27334d;border-left:4px solid #17c964;background:#121a2d;border-radius:8px;padding:7px 12px;font-size:13px}
#ais-verdict.warn{border-left-color:#f5b942}#ais-verdict.bad{border-left-color:#f31260}#ais-verdict a{color:#7dd3fc;font-weight:800;margin-left:10px;text-decoration:none}
#ais-entries{background:#121a2d;border:1px solid #27334d;border-radius:10px;padding:8px 12px;min-width:250px;font-size:12px}
#ais-entries.paused{border-color:#f31260;background:#2a1019}
.ae-title{font-size:10px;letter-spacing:.08em;color:#8ea0bd}.ae-state{font-weight:800;font-size:15px;margin:2px 0}
.ae-state.on{color:#17c964}.ae-state.off{color:#ff6b8f}.ae-pnl{color:#8ea0bd;margin-bottom:6px}
.ae-row{display:flex;gap:6px;align-items:center;margin-top:5px;color:#8ea0bd}
#ais-entries button{background:#0f1729;color:#e7eefc;border:1px solid #27334d;border-radius:8px;padding:5px 10px;font-weight:700;cursor:pointer}
#ae-toggle{width:100%}#ais-entries.paused #ae-toggle{border-color:#17c964;color:#9ff0bd}
#ae-target{width:58px;background:#0f1729;color:#e7eefc;border:1px solid #27334d;border-radius:6px;padding:4px}
#ais-sectors{margin-top:8px}
.ais-tile{background:#121a2d;border:1px solid #27334d;border-radius:10px;padding:6px 10px;min-width:150px}
.ais-tile.small{min-width:118px;padding:4px 8px}
.ais-name{font-size:11px;color:#8ea0bd;font-weight:700;letter-spacing:.3px}
.ais-ltp{font-size:16px;font-weight:800;margin:1px 0}.ais-tile.small .ais-ltp{font-size:13px}
.ais-pcts{display:flex;gap:10px;font-size:11.5px;font-weight:700}.ais-pcts span em{font-style:normal;color:#8ea0bd;font-weight:600;margin-right:3px}
.ais-up{color:#17c964}.ais-dn{color:#f31260}.ais-na{color:#8ea0bd}
.ais-meta{font-size:11px;color:#8ea0bd;margin-top:6px}
@media(max-width:760px){.ais-tile{min-width:46%}.ais-tile.small{min-width:30%}}
</style>
<div id="aplus-index-strip">
 <div class="ais-top"><div id="ais-left"></div><div id="ais-entries"><div class="ae-title">NEW ENTRIES</div>
  <div id="ae-state" class="ae-state">...</div><div id="ae-pnl" class="ae-pnl"></div>
  <div class="ae-row"><button id="ae-toggle" type="button">Pause new entries</button></div>
  <div class="ae-row"><span>Auto-pause at +</span><input id="ae-target" type="number" min="0.5" max="100" step="0.5" placeholder="7">
   <span>% of capital</span><button id="ae-set" type="button">Set</button></div></div><div id="ais-tiles"></div></div>
 <div id="ais-verdict" style="display:none"></div>
 <div id="ais-sectors"></div>
 <div class="ais-meta" id="ais-meta">Indices: change from today's open and from yesterday's close</div>
</div>
<script>
(function(){
function pc(v,inv){if(v==null)return '<span class="ais-na">-</span>';var up=v>=0;if(inv)up=!up;return '<span class="'+(up?"ais-up":"ais-dn")+'">'+(v>=0?"+":"")+v.toFixed(2)+'%</span>'}
function tile(r,small){var n=r.ltp>=1000?r.ltp.toLocaleString("en-IN",{maximumFractionDigits:2}):r.ltp.toFixed(2),inv=r.name==="INDIA VIX";
 return '<div class="ais-tile'+(small?' small':'')+'"><div class="ais-name">'+r.name+'</div><div class="ais-ltp">'+n+'</div>'
  +'<div class="ais-pcts"><span><em>open</em>'+pc(r.pct_open,inv)+'</span><span><em>prev</em>'+pc(r.pct_prev,inv)+'</span></div></div>'}
function draw(d){if(!d||!d.ok){document.getElementById("ais-meta").textContent="Indices unavailable"+(d&&d.error?" ("+d.error+")":"");return}
 document.getElementById("ais-tiles").innerHTML=d.rows.filter(function(r){return r.group==="main"}).map(function(r){return tile(r,false)}).join("");
 document.getElementById("ais-sectors").innerHTML=d.rows.filter(function(r){return r.group==="sector"}).map(function(r){return tile(r,true)}).join("");
 document.getElementById("ais-meta").textContent="Indices: change from today's open and from yesterday's close - updated "+d.updated+(d.market_open?"":" (market closed)")+(d.prev_ready?"":" - loading yesterday's closes")+(d.stale?" - STALE":"")}
function load(){fetch("/api/indices",{cache:"no-store"}).then(function(r){return r.json()}).then(draw).catch(function(){})}
function relocate(){var left=document.getElementById("ais-left");if(!left)return;
 ["aplus-mode-bar","aplus-mood"].forEach(function(id){var el=document.getElementById(id);if(el&&el.parentNode!==left)left.appendChild(el)})}
var aeState=null;
function aeDraw(s){aeState=s;var box=document.getElementById("ais-entries");if(!box||!s)return;
 var off=s.blocked;box.className=off?"paused":"";
 var st=document.getElementById("ae-state");st.className="ae-state "+(off?"off":"on");
 st.textContent=off?(s.reason==="PAUSED_BY_USER"?"PAUSED - no new trades":"STOPPED - day target reached"):"ON - taking new trades";
 var pct=s.day_pct==null?"":" ("+(s.day_pct>=0?"+":"")+s.day_pct.toFixed(2)+"% of "+Math.round(s.capital/1000)+"k capital)";
 var warn=s.scanner_ready===false?" | WARNING: the running scanner has not loaded this switch yet (needs a restart) - pausing will NOT stop it":"";
 document.getElementById("ae-pnl").textContent="Day P&L "+(s.day_pnl==null?"-":Math.round(s.day_pnl).toLocaleString("en-IN"))+pct+(s.target_pct?" | auto-pause at +"+s.target_pct+"%":"")+warn;
 var b=document.getElementById("ae-toggle");b.textContent=s.paused?"Resume new entries":"Pause new entries"}
function aeLoad(){fetch("/api/entries-pause",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){if(d.ok)aeDraw(d.state)}).catch(function(){})}
function aePost(body){return fetch("/api/entries-pause",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})
 .then(function(r){return r.json()}).then(function(d){if(d.ok)aeDraw(d.state);else alert(d.message||"Could not change it")}).catch(function(){alert("Could not reach the dashboard")})}
document.addEventListener("click",function(e){var id=e.target&&e.target.id;
 if(id==="ae-toggle"){var pausing=!(aeState&&aeState.paused);
  if(!pausing||confirm("Stop the scanner from taking NEW paper trades for the rest of today? Open trades keep being managed."))aePost({paused:pausing})}
 if(id==="ae-set"){var v=document.getElementById("ae-target").value;aePost({target_pct:v===""?0:parseFloat(v)})}});
function vdLoad(){fetch("/api/day-verdict",{cache:"no-store"}).then(function(r){return r.json()}).then(function(b){var el=document.getElementById("ais-verdict");
 if(!el||!b||!b.headline)return;el.style.display="block";el.className=b.ok?"":(b.verdict==="NO_TRADE"||b.entries==="PAUSED"?"bad":"warn");
 el.innerHTML="<b>"+b.headline+"</b> &middot; "+b.detail+" &middot; entries <b>"+b.entries+"</b> &middot; "+b.message+' <a href="/pipeline">Signal pipeline &amp; decision tape &rsaquo;</a>'}).catch(function(){})}
vdLoad();setInterval(vdLoad,10000);
aeLoad();setInterval(aeLoad,5000);
load();setInterval(load,5000);relocate();window.addEventListener("load",relocate);setInterval(relocate,2000);
})();
</script>
"""


def inject(page: str) -> str:
    """Put the strip right above the main page's header (once)."""
    marker = '<div class="header"><div><div class="brandrow">'
    if 'id="aplus-index-strip"' in page or marker not in page:
        return page
    return page.replace(marker, STRIP_HTML + marker, 1)
