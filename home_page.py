"""The APlus home page: one screen that says whether the software is healthy right now, how today is going and how the shadow tests are doing.   /home   (data: /api/home)

Read-only. Nothing here trades, pauses or changes a setting.

    payload(snapshot_fn)   everything the page shows, built from the dashboard snapshot plus the files the scanner already writes
    health(...)            the data-health checks and the banner sentence (worst check wins)

Data health, in plain words (market hours only; outside them every feed check reads "idle"):
    position prices   how old the newest price of each OPEN paper position is (the tape file written by the 3-second position monitor)
    scanner cycle     minutes since the scanner last finished a cycle
    Upstox allowance  calls used in the last 30 minutes of the shared budget; at 100% every data call is refused and open positions only "retain" their last price
    Upstox errors     UpstoxLimit failures in the last 5 minutes, fast-monitor failures in the last minute
    entries           whether new entries are paused by hand / by the daily target
"""

from __future__ import annotations

import csv
import json
import time
from datetime import date, datetime, time as dtime
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "logs" / "scanner.log"
TAPE = ROOT / "data" / "option_trade_tape"
EXPERIMENTS = ROOT / "ai_supervisor" / "experiments.json"
VARIANTS = ROOT / "data" / "trade_archive" / "exit_variants.csv"
MARKET_OPEN, MARKET_CLOSE = dtime(9, 15), dtime(15, 30)
PRICE_WARN_S, PRICE_BAD_S = 20, 90
CYCLE_WARN_S, CYCLE_BAD_S = 150, 300
BUDGET_WARN, BUDGET_BAD = 0.80, 0.95
_RANK = {"idle": 0, "ok": 0, "warn": 1, "bad": 2}


def market_open(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def _tail(path: Path, size: int = 400_000) -> list[str]:
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            end = fh.tell()
            fh.seek(max(0, end - size))
            data = fh.read()
        return data.decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def _log_time(line: str) -> datetime | None:
    try:
        return datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _age_text(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    s = int(max(0, seconds))
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60} min"
    return f"{s / 3600:.1f} h"


def log_facts(now: datetime, lines: list[str] | None = None) -> dict[str, Any]:
    """Last scanner cycle, and how many UpstoxLimit / fast-monitor failures the log shows recently."""
    lines = _tail(LOG) if lines is None else lines
    last_cycle = None
    limit_5m = 0
    fast_fail_1m = 0
    for ln in reversed(lines):
        ts = _log_time(ln)
        if ts is None:
            continue
        age = (now - ts).total_seconds()
        if last_cycle is None and "Intraday movement cycle phase=" in ln:
            last_cycle = ts
        if age <= 300 and "UpstoxLimit" in ln and "ERROR" in ln:
            limit_5m += 1
        if age <= 60 and "FAST_MONITOR check failed" in ln:
            fast_fail_1m += 1
        if last_cycle is not None and age > 300:
            break
    return {"last_cycle": last_cycle, "limit_errors_5m": limit_5m, "fast_failures_1m": fast_fail_1m}


def budget_facts() -> dict[str, Any]:
    try:
        from core.upstox_client import SHARED_CAPS, _SharedLedger

        u = _SharedLedger().usage()
        cap = int((SHARED_CAPS.get("high") or [1900])[0])
        used = int(u.get("last_30min") or 0)
        procs = sorted(((k, int(v.get("30min") or 0)) for k, v in (u.get("by_process") or {}).items()), key=lambda x: -x[1])[:3]
        return {"used": used, "cap": cap, "top": [{"who": k, "calls": v} for k, v in procs]}
    except Exception:  # noqa: BLE001 - the page must still load
        return {"used": None, "cap": None, "top": []}


def tape_age(trade_id: str, day: str, now: datetime) -> float | None:
    """Seconds since the newest recorded price of an open trade (None when there is no tape yet)."""
    if not trade_id:
        return None
    for f in (TAPE / day).glob(f"*{trade_id}*.csv"):
        line = next((x for x in reversed(_tail(f, 4000)) if x.strip() and not x.startswith("timestamp")), "")
        try:
            ts = datetime.fromisoformat(line.split(",")[0])
            ts = ts.replace(tzinfo=None) if ts.tzinfo is None else ts.astimezone().replace(tzinfo=None)
            return (now - ts).total_seconds()
        except (ValueError, IndexError):
            return None
    return None


def health(now: datetime, open_ages: list[float | None], log: Mapping[str, Any], budget: Mapping[str, Any], entries: Mapping[str, Any] | None) -> dict[str, Any]:
    live = market_open(now)
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    known = [a for a in open_ages if a is not None]
    if not live:
        add("Position prices", "idle", "market closed")
    elif not open_ages:
        add("Position prices", "ok", "no open positions")
    elif not known:
        add("Position prices", "bad", "no price recorded yet for the open positions")
    else:
        worst = max(known)
        st = "bad" if worst > PRICE_BAD_S else "warn" if worst > PRICE_WARN_S else "ok"
        add("Position prices", st, f"oldest open-position price is {_age_text(worst)} old ({len(open_ages)} open)")

    cyc = log.get("last_cycle")
    if not live:
        add("Scanner cycle", "idle", "market closed")
    elif cyc is None:
        add("Scanner cycle", "bad", "no completed cycle found in the log")
    else:
        age = (now - cyc).total_seconds()
        add("Scanner cycle", "bad" if age > CYCLE_BAD_S else "warn" if age > CYCLE_WARN_S else "ok", f"last cycle finished {_age_text(age)} ago")

    used, cap = budget.get("used"), budget.get("cap")
    if used is None or not cap:
        add("Upstox allowance", "warn", "could not read the shared budget")
    else:
        frac = used / cap
        top = ", ".join(f"{t['who'].replace('.py', '')} {t['calls']}" for t in budget.get("top", []))
        add("Upstox allowance", "bad" if frac >= BUDGET_BAD else "warn" if frac >= BUDGET_WARN else "ok",
            f"{used} of {cap} calls in the last 30 min ({frac * 100:.0f}%)" + (f"; biggest users: {top}" if top else ""))

    lim, ff = int(log.get("limit_errors_5m") or 0), int(log.get("fast_failures_1m") or 0)
    if not live:
        add("Upstox errors", "idle", "market closed")
    elif lim or ff:
        add("Upstox errors", "bad" if (lim >= 3 or ff >= 5) else "warn", f"{lim} refused data cycles in the last 5 min, {ff} position-monitor failures in the last minute")
    else:
        add("Upstox errors", "ok", "none in the last 5 minutes")

    paused = bool(entries and entries.get("paused"))
    add("New entries", "warn" if paused else "ok", (str(entries.get("reason") or "paused") if paused else "allowed") if entries is not None else "unknown")

    worst = max(checks, key=lambda c: _RANK[c["status"]])
    level = worst["status"] if worst["status"] in ("warn", "bad") else ("idle" if not live else "ok")
    stale = next((c for c in checks if c["name"] == "Position prices" and c["status"] == "bad"), None)
    full = next((c for c in checks if c["name"] == "Upstox allowance" and c["status"] == "bad"), None)
    if level == "bad":
        if stale and full:
            msg = "DATA STALE: the Upstox allowance is used up, so open-position prices are not updating. Stops and exits cannot fire until it frees up (usually a few minutes). " + stale["detail"] + "."
        elif stale:
            msg = "DATA STALE: open-position prices are not updating, so stops and exits cannot fire. " + stale["detail"] + "."
        elif full:
            msg = "Upstox allowance almost used up (" + full["detail"].split(" calls")[0] + " calls in 30 min). Prices are still updating, but at 100% open-position updates stop and stops/exits cannot fire until it frees up."
        else:
            msg = worst["name"] + ": " + worst["detail"] + "."
    elif level == "warn":
        msg = worst["name"] + ": " + worst["detail"] + "."
    elif level == "idle":
        msg = "Market is closed. Feed checks start at 09:15."
    else:
        msg = "All live: prices, scanner and Upstox allowance are healthy."
    return {"level": level, "message": msg, "checks": checks, "market_open": live}


def shadow_tests(today: str) -> list[dict[str, Any]]:
    """Each registered forward experiment: how many sessions and trades it has seen since registration and what it would have changed."""
    try:
        exps = json.loads(EXPERIMENTS.read_text(encoding="utf-8")).get("experiments") or []
        marks = json.loads(EXPERIMENTS.read_text(encoding="utf-8")).get("pass_marks") or {}
    except (OSError, ValueError):
        return []
    need_days, need_trades = int(marks.get("sessions", 10)), int(marks.get("trades", 100))
    out: list[dict[str, Any]] = []
    gate_trades = None
    var_rows: list[list[str]] | None = None
    for e in exps:
        reg, key, kind = str(e.get("registered") or ""), e.get("key"), e.get("kind")
        row = {"id": e.get("id"), "name": e.get("name"), "kind": kind, "since": reg, "sessions": 0, "trades": 0, "change": None, "pos_days": None, "need_sessions": need_days, "need_trades": need_trades}
        try:
            if kind == "gate":
                import shadow_scoreboard as sb

                if gate_trades is None:
                    gate_trades = sb.load_trades(upto=today)
                fwd = [t for t in gate_trades if t["_day"] > reg]
                if key in sb.GATES:
                    r = sb.gate_rows(fwd, only=[key])[0]
                    row.update(sessions=r["days_with_data"], trades=r["blocked"]["n"], change=round(r["change_if_enforced"]), pos_days=(round(100 * r["days_helped"] / r["days_blocked"]) if r["days_blocked"] else None))
            elif kind == "variant":
                if var_rows is None:
                    with VARIANTS.open(encoding="utf-8") as fh:
                        var_rows = [r for r in csv.reader(fh)][1:]
                mine = [r for r in var_rows if len(r) >= 5 and r[1] == key and r[0] > reg]
                if mine:
                    diffs = [float(r[4]) - float(r[3]) for r in mine]
                    row.update(sessions=len(mine), trades=sum(int(float(r[2])) for r in mine), change=round(sum(diffs)), pos_days=round(100 * sum(1 for d in diffs if d > 0) / len(diffs)))
        except Exception:  # noqa: BLE001 - one broken test must not hide the others
            row["error"] = True
        out.append(row)
    return out


_CACHE: dict[str, Any] = {"t": 0.0, "tests": []}


def payload(snapshot_fn: Callable[[], Mapping[str, Any]], entries_fn: Callable[[], Mapping[str, Any]] | None = None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    today = now.date().isoformat()
    snap = snapshot_fn() or {}
    rows = [r for r in (snap.get("rows") or []) if str(r.get("status")) == "OPEN"]
    positions, ages = [], []
    for r in sorted(rows, key=lambda x: str(x.get("entry_time") or "")):
        age = tape_age(str(r.get("id") or ""), today, now)
        ages.append(age)
        positions.append({"symbol": r.get("symbol"), "side": r.get("side"), "entry_time": r.get("entry_time"), "entry": r.get("entry"), "last": r.get("last"), "pnl": r.get("pnl"),
                          "return_pct": r.get("return_pct"), "stop": r.get("ladder_stop") or r.get("sl"), "age_s": None if age is None else round(age),
                          "age_text": _age_text(age), "stale": bool(age is not None and age > PRICE_BAD_S and market_open(now))})
    try:
        entries = dict(entries_fn()) if entries_fn else None
    except Exception:  # noqa: BLE001
        entries = None
    h = health(now, ages, log_facts(now), budget_facts(), entries)
    if time.time() - _CACHE["t"] > 60:
        _CACHE["tests"], _CACHE["t"] = shadow_tests(today), time.time()
    return {"ok": True, "now": now.strftime("%H:%M:%S"), "date": now.strftime("%a %d %b %Y"), "health": h,
            "today": {k: snap.get(k) for k in ("trade_count", "open_count", "closed_count", "wins", "losses", "win_rate", "total_pnl", "closed_pnl", "open_pnl")},
            "positions": positions, "tests": _CACHE["tests"]}


PAGE_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Home</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{--bg:#05080f;--panel:#0a111d;--line:#17324a;--text:#e6edf9;--muted:#7d8fab;--g:#27e39a;--r:#ff4d5e;--amber:#ffb454;--c:#22e6ff}
*{box-sizing:border-box}html,body{background:var(--bg)!important;color:var(--text);margin:0;font:13px/1.4 "Segoe UI",Arial,sans-serif}
#hm{padding:10px 14px 30px;max-width:1400px;margin:0 auto}
.top{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:6px}h1{font-size:15px;letter-spacing:.2em;margin:6px 0;text-transform:uppercase}
.sub{color:var(--muted);font-size:12px}
#banner{border-radius:8px;padding:12px 14px;margin:8px 0 12px;font-size:14px;font-weight:600;border:1px solid}
#banner.ok{background:#0a2a1d;border-color:#1c7a55;color:var(--g)}#banner.warn{background:#2b2108;border-color:#8a6a1e;color:var(--amber)}
#banner.bad{background:#2d0c12;border-color:#a0283a;color:#ff8a98}#banner.idle{background:#101a2b;border-color:var(--line);color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:0 0 12px}
.card{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px 10px}.card .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}
.card .v{font-size:20px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
h2{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:14px 0 6px}
.box{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px 10px;overflow-x:auto}
table{width:100%;border-collapse:collapse}th,td{padding:5px 8px;border-bottom:1px solid #112238;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase}th:first-child,td:first-child,td.l,th.l{text-align:left}
.g{color:var(--g)}.r{color:var(--r)}.a{color:var(--amber)}.m{color:var(--muted)}
.checks{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:8px}
.chk{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px 10px;display:flex;gap:9px;align-items:flex-start}
.dot{width:10px;height:10px;border-radius:50%;margin-top:4px;flex:none}.dot.ok{background:var(--g)}.dot.warn{background:var(--amber)}.dot.bad{background:var(--r)}.dot.idle{background:#455770}
.chk b{display:block;font-size:12.5px}.chk span{color:var(--muted);font-size:12px}
.bar{height:6px;background:#112238;border-radius:3px;min-width:70px;margin-top:3px}.bar i{display:block;height:100%;border-radius:3px;background:var(--c)}
.links a{color:var(--c);text-decoration:none;margin-right:14px;font-size:12.5px}
.stale td{background:#2d0c12}
</style></head><body><div id="hm">
<div class="top"><h1>APlus home</h1><div class="sub" id="clock">loading...</div></div>
<div id="banner" class="idle">loading...</div>
<div class="cards" id="cards"></div>
<h2>Open positions</h2><div class="box" id="pos"></div>
<h2>Data health</h2><div class="checks" id="checks"></div>
<h2>Shadow tests (forward evidence, nothing enforced)</h2><div class="box" id="tests"></div>
<h2>More</h2><div class="links"><a href="/">Main dashboard</a><a href="/paper-history">Paper history</a><a href="/ask">Ask APlus</a><a href="/manual-paper">Manual paper</a><a href="/alerts">Alerts</a><a href="/breakouts">Breakouts</a><a href="/big-players">Big players</a></div>
</div>
<script>
function rs(n){n=Math.round(Number(n)||0);return (n<0?"-":"")+"₹"+Math.abs(n).toLocaleString("en-IN")}function cl(n){return n>0?"g":n<0?"r":""}
function esc(s){return String(s==null?"":s).replace(/[&<>]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;"}[c]})}
function render(D){
 if(!D||!D.ok){var e=document.getElementById("banner");e.className="bad";e.textContent="The home page could not build its data: "+((D&&D.error)||"no answer");return}
 var H=D.health;document.getElementById("clock").textContent=D.date+"  "+D.now;
 var b=document.getElementById("banner");b.className=H.level;b.textContent=H.message;
 var T=D.today;document.getElementById("cards").innerHTML=[["Today total",rs(T.total_pnl),cl(T.total_pnl)],["Realised",rs(T.closed_pnl),cl(T.closed_pnl)],["Open now",rs(T.open_pnl),cl(T.open_pnl)],
  ["Trades",(T.trade_count||0)+" ("+(T.open_count||0)+" open)",""],["Won / lost",(T.wins||0)+" / "+(T.losses||0),""],["Win rate",(T.win_rate||0)+"%",""]]
  .map(function(c){return '<div class="card"><div class="k">'+c[0]+'</div><div class="v '+c[2]+'">'+c[1]+'</div></div>'}).join("");
 var P=D.positions;document.getElementById("pos").innerHTML=P.length?'<table><thead><tr><th>Stock</th><th>Side</th><th>In</th><th>Entry</th><th>Last</th><th>P&amp;L</th><th>%</th><th>Stop</th><th>Price age</th></tr></thead><tbody>'+
  P.map(function(p){return '<tr class="'+(p.stale?"stale":"")+'"><td><b>'+esc(p.symbol)+'</b></td><td>'+esc(p.side)+'</td><td>'+esc(p.entry_time)+'</td><td>'+Number(p.entry).toFixed(2)+'</td><td>'+Number(p.last).toFixed(2)+'</td><td class="'+cl(p.pnl)+'">'+rs(p.pnl)+
  '</td><td class="'+cl(p.return_pct)+'">'+Number(p.return_pct).toFixed(1)+'%</td><td>'+(p.stop?Number(p.stop).toFixed(2):"-")+'</td><td class="'+(p.stale?"r":(p.age_s!=null&&p.age_s>20?"a":"m"))+'">'+esc(p.age_text)+'</td></tr>'}).join("")+'</tbody></table>':'<span class="m">No open positions.</span>';
 document.getElementById("checks").innerHTML=H.checks.map(function(c){return '<div class="chk"><div class="dot '+c.status+'"></div><div><b>'+esc(c.name)+'</b><span>'+esc(c.detail)+'</span></div></div>'}).join("");
 var X=D.tests;document.getElementById("tests").innerHTML=X.length?'<table><thead><tr><th>ID</th><th class="l">Test</th><th>Since</th><th>Sessions</th><th>Trades</th><th>Change if enforced</th><th>Positive days</th><th>Progress</th></tr></thead><tbody>'+
  X.map(function(x){var pr=Math.min(100,Math.round(100*Math.max(x.sessions/x.need_sessions,x.trades/x.need_trades)));return '<tr><td><b>'+esc(x.id)+'</b></td><td class="l" style="white-space:normal;min-width:260px">'+esc(x.name)+'</td><td>'+esc(x.since)+'</td><td>'+x.sessions+'</td><td>'+x.trades+'</td><td class="'+(x.change==null?"m":cl(x.change))+'">'+(x.change==null?"-":rs(x.change))+
  '</td><td>'+(x.pos_days==null?"-":x.pos_days+"%")+'</td><td><div class="bar"><i style="width:'+pr+'%"></i></div></td></tr>'}).join("")+'</tbody></table><div class="sub" style="margin-top:6px">Pass marks: 10 sessions and 100 trades, change above zero, 60%+ positive days. "Change" is what the rule would have added to the result; the live system has a negative average, so always compare with random blocking before trusting a positive number.</div>':'<span class="m">No registered tests.</span>';
}
function load(){fetch("/api/home",{cache:"no-store"}).then(function(r){return r.json()}).then(render).catch(function(){var b=document.getElementById("banner");b.className="bad";b.textContent="Cannot reach the dashboard server - the page cannot show live data."})}
load();setInterval(load,5000);
</script></body></html>"""
