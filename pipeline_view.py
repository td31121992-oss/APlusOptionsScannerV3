"""Signal pipeline board, day-verdict banner and decision tape (READ-ONLY - never changes a trade or a setting).

    /pipeline          the page
    /api/pipeline      JSON for the page
    /api/day-verdict   the small banner payload (also shown at the top of the main dashboard)

Everything is built from files the scanner already writes:
    data/reports/intraday_movement_<day>_<time>.json   one per scan cycle (candidates, gates, V2 blocks)
    data/intraday_movement/paper_trade_journal.json    trades
    data/manual_orders/<day>.jsonl                     manual stops / exits
    data/control/entries_pause.json                    the pause switch

Stages (one chip per stock+direction, from the latest scan cycle):
    WATCH          on the radar (quote shortlist) but no setup yet
    EARLY WARNING  fresh movement / early entry / near miss
    BUILDING       strong trend waiting for a pullback, or a healthy pullback forming
    READY          entry-ready and nothing in the way
    GATED          entry-ready but held back at a gate (A+ rule, V2 top-5, safety, entry rule, pause) - with the reason
    IN TRADE       an open paper trade
    INVALIDATED    extended, low relative volume, VWAP conflict, ...
"""

from __future__ import annotations

import glob
import json
import os
import threading
from collections import defaultdict
from datetime import date, datetime, time as dtime
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent
INVALID_STAGES = {"EXTENDED_NO_ENTRY", "LOW_RELATIVE_VOLUME", "VWAP_CONFLICT", "TREND_CONFLICT", "NO_ENTRY", "CHOPPY", "REVERSAL_RISK"}
STAGE_ORDER = ["WATCH", "EARLY WARNING", "BUILDING", "READY", "IN TRADE"]
CAPITAL_DEFAULT = 500000.0


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def _hm(value: Any) -> str:
    s = str(value or "")
    return s[11:16] if len(s) >= 16 else ""


# ----------------------------------------------------------------------------- stages
def classify(c: Mapping[str, Any]) -> tuple[str, str]:
    """(stage, reason) for one scanner candidate."""
    status = str(c.get("paper_trade_status") or "")
    shortlist = str(c.get("shortlist") or "")
    stage = str(c.get("stage") or "")
    if status == "OPEN" or c.get("paper_trade_id"):
        return "IN TRADE", ""
    if shortlist == "ENTRY_READY" or stage.endswith("ENTRY_READY"):
        if status and status not in ("OPEN",):
            return "GATED", status.replace("A_PLUS_WAIT_", "A+ wait: ").replace("_", " ").lower()
        if c.get("option_error"):
            return "GATED", str(c.get("option_error"))[:60].replace("_", " ").lower()
        if str(c.get("safety_decision") or "").upper() in ("BLOCK", "BLOCKED"):
            return "GATED", "safety gate: " + ", ".join(str(x) for x in (c.get("safety_block_reasons") or [])[:2]).replace("_", " ").lower()
        return "READY", ""
    if stage in INVALID_STAGES:
        return "INVALIDATED", stage.replace("_", " ").lower()
    if shortlist == "STRONG_TREND_WAIT_FOR_PULLBACK" or "PULLBACK" in stage:
        return "BUILDING", stage.replace("_", " ").lower()
    if shortlist in ("FRESH_MOVEMENT", "EARLY_ENTRY", "NEAR_MISS") or "EARLY" in stage or "FRESH" in stage or "NEAR" in shortlist:
        return "EARLY WARNING", stage.replace("_", " ").lower()
    return "WATCH", ""


def chip(c: Mapping[str, Any], reason: str = "") -> dict[str, Any]:
    return {"symbol": c.get("symbol"), "direction": str(c.get("direction") or ""), "score": round(_f(c.get("trade_quality_score") or c.get("score")), 1),
            "move": round(_f(c.get("move_from_open_percent")), 2), "rvol": round(_f(c.get("relative_volume")), 2),
            "reason": reason, "stage": str(c.get("stage") or "")}


def build_stages(report: Mapping[str, Any], open_trades: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in STAGE_ORDER + ["GATED", "INVALIDATED"]}
    seen: set[tuple[str, str]] = set()
    for t in open_trades:
        key = (str(t.get("symbol")), "BULLISH" if str(t.get("option_type") or "").upper().startswith("C") else "BEARISH")
        seen.add(key)
        out["IN TRADE"].append({"symbol": t.get("symbol"), "direction": key[1], "score": round(_f(t.get("trade_quality_score") or t.get("momentum_score")), 1),
                                "move": round(_f(t.get("stock_move_fav_pct")), 2), "rvol": 0.0, "reason": "", "stage": str(t.get("stage") or "")})
    for c in list(report.get("candidates") or []):
        key = (str(c.get("symbol")), str(c.get("direction") or ""))
        if key in seen:
            continue
        seen.add(key)
        st, why = classify(c)
        out[st].append(chip(c, why))
    for blocked in (report.get("stock_selection_v2") or {}).get("blocked") or []:
        key = (str(blocked.get("symbol")), str(blocked.get("direction") or blocked.get("v2_side") or ""))
        if key in seen:
            continue
        seen.add(key)
        why = blocked.get("reasons") or blocked.get("reason") or blocked.get("status") or "V2 gate"
        if isinstance(why, (list, tuple)):
            why = ", ".join(str(x) for x in why[:2])
        out["GATED"].append({"symbol": blocked.get("symbol"), "direction": key[1], "score": round(_f(blocked.get("trade_quality_score")), 1),
                             "move": round(_f(blocked.get("from_open_pct")), 2), "rvol": 0.0,
                             "reason": "V2: " + str(why).replace("_", " ").lower(), "stage": "V2_BLOCKED"})
    for q in list(report.get("quote_shortlist") or []):
        key = (str(q.get("symbol")), str(q.get("direction") or ""))
        if key in seen or any(key[0] == s for s, _ in seen):
            continue
        seen.add(key)
        out["WATCH"].append({"symbol": q.get("symbol"), "direction": key[1], "score": round(_f(q.get("radar_score")), 1),
                             "move": round(_f(q.get("move_from_open_percent")), 2), "rvol": 0.0, "reason": "", "stage": ""})
    for k in out:
        out[k].sort(key=lambda x: -_f(x.get("score")))
    return out


# ----------------------------------------------------------------------------- blocked-signal memory for the tape
_TAPE: dict[str, Any] = {"day": "", "done": set(), "blocked": {}, "lock": threading.Lock(), "thread": None, "loading": False}


def _fold_report(blocked: dict[tuple[str, str, str], dict[str, Any]], rep: Mapping[str, Any]) -> None:
    when = _hm(rep.get("generated_at"))
    for r in (rep.get("aplus_selective_gate") or {}).get("rejected_symbols") or []:
        key = (str(r.get("symbol")), str(r.get("direction")), str(r.get("status")))
        e = blocked.setdefault(key, {"first": when, "last": when, "cycles": 0, "score": r.get("trade_quality_score")})
        e["last"], e["cycles"] = when, e["cycles"] + 1
    for r in (rep.get("stock_selection_v2") or {}).get("blocked") or []:
        why = r.get("reasons") or r.get("reason") or r.get("status") or "V2"
        why = ",".join(str(x) for x in why) if isinstance(why, (list, tuple)) else str(why)
        key = (str(r.get("symbol")), str(r.get("direction") or r.get("v2_side") or ""), "V2: " + why)
        e = blocked.setdefault(key, {"first": when, "last": when, "cycles": 0, "score": r.get("trade_quality_score")})
        e["last"], e["cycles"] = when, e["cycles"] + 1


def _scan_reports(root: Path, day: str) -> None:
    stamp = day.replace("-", "")
    cache = root / "data" / "cache" / f"decision_tape_{day}.json"
    with _TAPE["lock"]:
        if _TAPE["day"] != day:
            _TAPE.update({"day": day, "done": set(), "blocked": {}})
            try:
                saved = json.loads(cache.read_text(encoding="utf-8"))
                _TAPE["done"] = set(saved.get("done") or [])
                _TAPE["blocked"] = {tuple(k.split("|", 2)): v for k, v in (saved.get("blocked") or {}).items()}
            except (OSError, ValueError):
                pass
    files = sorted(glob.glob(str(root / "data" / "reports" / f"intraday_movement_{stamp}_*.json")))
    todo = [f for f in files if Path(f).name not in _TAPE["done"]]
    for f in todo:
        try:
            rep = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        with _TAPE["lock"]:
            _fold_report(_TAPE["blocked"], rep)
            _TAPE["done"].add(Path(f).name)
    if todo:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            with _TAPE["lock"]:
                payload = {"done": sorted(_TAPE["done"]), "blocked": {"|".join(k): v for k, v in _TAPE["blocked"].items()}}
            cache.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass
    _TAPE["loading"] = False


def refresh_tape(root: Path, day: str) -> bool:
    """Kick off an incremental background scan of today's cycle reports; returns True while it is still loading."""
    t = _TAPE.get("thread")
    if t is not None and t.is_alive():
        return True
    pending = [f for f in glob.glob(str(root / "data" / "reports" / f"intraday_movement_{day.replace('-', '')}_*.json"))
               if Path(f).name not in _TAPE["done"]] if _TAPE["day"] == day else True
    if not pending:
        return False
    _TAPE["loading"] = True
    th = threading.Thread(target=_scan_reports, args=(root, day), daemon=True)
    _TAPE["thread"] = th
    th.start()
    return True


# ----------------------------------------------------------------------------- tape + banner
def build_tape(trades: Iterable[Mapping[str, Any]], manual: Iterable[Mapping[str, Any]], blocked: Mapping[tuple, Mapping[str, Any]],
               limit: int = 300) -> list[dict[str, Any]]:
    ev: list[dict[str, Any]] = []
    for t in trades:
        opt = f"{t.get('symbol')} {int(_f(t.get('strike'))) if _f(t.get('strike')).is_integer() else t.get('strike')} {t.get('option_type', '')}"
        tags = []
        if str(t.get("kl_push")).lower() in ("true", "1"):
            tags.append("key-level push")
        if t.get("nt_verdict") and t.get("nt_verdict") != "TRADE":
            tags.append(str(t["nt_verdict"]).replace("_", " ").lower())
        if str(t.get("tr_all_aligned")).lower() in ("true", "1"):
            tags.append("5M+15M aligned")
        ev.append({"time": _hm(t.get("entry_time")), "kind": "ENTRY", "symbol": t.get("symbol"), "text": f"Bought {opt} at {_f(t.get('entry_price')):.2f}",
                   "detail": (str(t.get("stage") or "").replace("_", " ").lower() + (" | " + ", ".join(tags) if tags else "")).strip(" |"), "tone": "bull"})
        if str(t.get("status")).upper() == "CLOSED":
            pnl = _f(t.get("net_pnl") or t.get("total_pnl"))
            ev.append({"time": _hm(t.get("exit_time")), "kind": "EXIT", "symbol": t.get("symbol"),
                       "text": f"Sold {opt} at {_f(t.get('exit_price')):.2f} - {str(t.get('exit_reason') or '').replace('_', ' ').lower()}",
                       "detail": f"{pnl:+,.0f}", "tone": "bull" if pnl >= 0 else "bear"})
    for m in manual:
        ev.append({"time": str(m.get("ts") or "")[11:16], "kind": "MANUAL", "symbol": str(m.get("trade_id") or "").split("-")[-2] if m.get("trade_id") else "",
                   "text": f"You sent: {str(m.get('kind') or '').lower()}" + (f" {m.get('value')}" if m.get("value") else ""), "detail": str(m.get("source") or ""),
                   "tone": "neutral"})
    for (sym, direction, why), e in blocked.items():
        ev.append({"time": e.get("first") or "", "kind": "BLOCKED", "symbol": sym,
                   "text": f"{sym} {direction[:4].lower()} held back: {why.replace('A_PLUS_WAIT_', 'A+ wait ').replace('_', ' ').lower()}",
                   "detail": f"first {e.get('first')}, last {e.get('last')}, {e.get('cycles')} cycles", "tone": "warn"})
    ev = [e for e in ev if e["time"]]
    ev.sort(key=lambda e: e["time"], reverse=True)
    return ev[:limit]


def read_manual(root: Path, day: str) -> list[dict[str, Any]]:
    p = root / "data" / "manual_orders" / f"{day}.jsonl"
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def load_trades(root: Path, day: str) -> list[dict[str, Any]]:
    try:
        data = json.loads((root / "data" / "intraday_movement" / "paper_trade_journal.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [t for t in (data.get("trades") or []) if str(t.get("entry_time") or "")[:10] == day]


def day_verdict(trades: list[Mapping[str, Any]], root: Path, now: datetime | None = None, report_age_s: float | None = None,
                nifty_pct_open: float | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    try:
        import entry_pause
        capital = entry_pause.account_capital()
        pnl = entry_pause.day_pnl(trades, now.date().isoformat())
        pause = entry_pause.status(root, pnl, capital, now.date())
    except Exception:                                      # noqa: BLE001
        capital, pnl, pause = CAPITAL_DEFAULT, 0.0, {}
    pct = pnl / capital * 100.0 if capital else 0.0
    wins = sum(1 for t in trades if str(t.get("status")).upper() == "CLOSED" and _f(t.get("net_pnl")) > 0)
    losses = sum(1 for t in trades if str(t.get("status")).upper() == "CLOSED" and _f(t.get("net_pnl")) < 0)
    open_n = sum(1 for t in trades if str(t.get("status")).upper() == "OPEN")
    verdict, reasons = "TRADE", []
    try:
        import no_trade_day
        # day-level view: use the side that agrees with the index so "against the index" (a per-trade reason) never fires here
        side = "BULLISH" if (nifty_pct_open is None or nifty_pct_open >= 0) else "BEARISH"
        worst = no_trade_day.evaluate(trades, side, now.hour * 60 + now.minute, nifty_pct_open, None, capital)
        if worst:
            verdict, reasons = worst["nt_verdict"], [x for x in str(worst.get("nt_reasons") or "").split("|") if x]
    except Exception:                                      # noqa: BLE001
        pass
    attention: list[str] = []
    market_open = now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)
    if market_open and report_age_s is not None and report_age_s > 240:
        attention.append(f"scanner has not reported for {int(report_age_s // 60)} min - check it is running")
    if pause.get("blocked"):
        attention.append("new entries are " + ("paused by you" if pause.get("reason") == "PAUSED_BY_USER" else "stopped: day target reached"))
    if pause.get("scanner_ready") is False and market_open:
        attention.append("scanner has not loaded the pause switch (needs a restart)")
    if verdict != "TRADE":
        attention.append(f"no-trade verdict {verdict.replace('_', ' ').lower()}: " + ", ".join(r.replace("_", " ").lower() for r in reasons))
    head = ("Up" if pnl >= 0 else "Down") + f" on the day {pnl:+,.0f} ({pct:+.2f}% of capital)"
    tail = f"{wins} won, {losses} lost, {open_n} open"
    return {"headline": head, "detail": tail, "pnl": round(pnl, 2), "pct": round(pct, 2), "capital": capital, "verdict": verdict,
            "reasons": reasons, "entries": "PAUSED" if pause.get("blocked") else "ON", "attention": attention,
            "ok": not attention, "message": "Nothing needs attention right now." if not attention else "; ".join(attention)}


def latest_report(root: Path, day: str) -> tuple[dict[str, Any], float | None]:
    files = sorted(glob.glob(str(root / "data" / "reports" / f"intraday_movement_{day.replace('-', '')}_*.json")))
    if not files:
        return {}, None
    try:
        rep = json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, None
    try:
        age = (datetime.now() - datetime.fromisoformat(str(rep.get("generated_at"))).replace(tzinfo=None)).total_seconds()
    except ValueError:
        age = None
    return rep, age


def _nifty_pct(root: Path) -> float | None:
    try:
        import index_strip

        for r in index_strip.payload(root).get("rows", []):
            if r.get("name") == "NIFTY 50":
                return float(r.get("pct_open"))
    except Exception:                                      # noqa: BLE001
        pass
    return None


def verdict_payload(root: Path = ROOT) -> dict[str, Any]:
    day = date.today().isoformat()
    trades = load_trades(root, day)
    _, age = latest_report(root, day)
    return day_verdict(trades, root, None, age, _nifty_pct(root))


def payload(root: Path = ROOT) -> dict[str, Any]:
    day = date.today().isoformat()
    trades = load_trades(root, day)
    report, age = latest_report(root, day)
    open_trades = [t for t in trades if str(t.get("status")).upper() == "OPEN"]
    loading = refresh_tape(root, day)
    with _TAPE["lock"]:
        blocked = dict(_TAPE["blocked"])
    stages = build_stages(report, open_trades)
    return {"ok": True, "day": day, "updated": datetime.now().strftime("%H:%M:%S"), "cycle_at": _hm(report.get("generated_at")),
            "banner": day_verdict(trades, root, None, age, _nifty_pct(root)), "stages": stages,
            "counts": {k: len(v) for k, v in stages.items()}, "tape": build_tape(trades, read_manual(root, day), blocked),
            "tape_loading": loading, "v2_top": {"up": [x.get("symbol") for x in (report.get("stock_selection_v2") or {}).get("top_up", [])],
                                               "down": [x.get("symbol") for x in (report.get("stock_selection_v2") or {}).get("top_down", [])]}}


PIPELINE_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Pipeline</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--green:#2ecc71;--red:#ff6363;--amber:#f5b942;--blue:#4c8dff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.4 -apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1600px;margin:0 auto;padding:12px 14px 40px}a{color:var(--blue);text-decoration:none;font-weight:700}
.banner{border:1px solid var(--line);border-left:5px solid var(--green);background:var(--panel);border-radius:12px;padding:12px 16px;margin:10px 0}
.banner.warn{border-left-color:var(--amber)}.banner.bad{border-left-color:var(--red)}
.banner h1{font-size:19px;margin:0 0 3px}.banner .sub{color:var(--muted);font-size:13px}
.cols{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}@media(max-width:1100px){.cols{grid-template-columns:1fr 1fr}}
.col{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px;min-height:140px}
.col h2{font-size:12px;letter-spacing:.07em;color:var(--muted);margin:0 0 8px;display:flex;justify-content:space-between}
.chip{display:flex;justify-content:space-between;gap:8px;border-radius:8px;padding:6px 9px;margin-bottom:5px;font-weight:700;font-size:13px}
.chip.bull{background:#12351f;color:#b9f5cf}.chip.bear{background:#3a1620;color:#ffb9c8}.chip small{font-weight:600;opacity:.8}
.two{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}@media(max-width:1000px){.two{grid-template-columns:1fr}}
.row{display:flex;justify-content:space-between;gap:8px;border-bottom:1px solid var(--line);padding:6px 2px;font-size:13px}.row small{color:var(--muted)}
.tabs{display:flex;gap:6px;margin:12px 0 6px}.tabs button{background:#0f1729;color:var(--muted);border:1px solid var(--line);border-radius:8px;padding:6px 12px;font-weight:800;cursor:pointer}
.tabs button.on{background:#12351f;color:var(--green);border-color:var(--green)}
.tape .e{display:grid;grid-template-columns:54px 82px 1fr;gap:8px;padding:7px 4px;border-bottom:1px solid var(--line);font-size:13px}
.k{font-weight:900;font-size:11px;letter-spacing:.05em}.k.ENTRY{color:var(--green)}.k.EXIT{color:var(--blue)}.k.BLOCKED{color:var(--amber)}.k.MANUAL{color:#b88bff}
.bull{color:var(--green)}.bear{color:var(--red)}.warn{color:var(--amber)}.muted{color:var(--muted)}
</style></head><body><div class="wrap">
<div><a href="/">&larr; Dashboard</a> &nbsp; <a href="/positions">Positions</a> &nbsp; <a href="/fno-market-watch">Market Watch</a></div>
<div class="banner" id="banner"><h1>Loading...</h1></div>
<div class="cols" id="cols"></div>
<div class="two"><div class="col"><h2>HELD BACK AT A GATE <span id="gcount"></span></h2><div id="gated"></div></div>
<div class="col"><h2>INVALIDATED <span id="icount"></span></h2><div id="invalid"></div></div></div>
<div class="tabs" id="tabs"></div><div class="col tape" id="tape"></div>
<div class="muted" style="margin-top:10px;font-size:12px" id="foot"></div></div>
<script>
var TAPE_F="ALL",DATA=null;
function chip(c){var cl=/BULL/i.test(c.direction)?"bull":"bear",ar=/BULL/i.test(c.direction)?"&#9650;":"&#9660;";
 return '<div class="chip '+cl+'" title="'+(c.stage||"")+'"><span>'+ar+' '+c.symbol+(c.reason?' <small>'+c.reason+'</small>':'')+'</span><small>'+(c.score?c.score.toFixed(0)+' &middot; ':'')+(c.move>=0?"+":"")+c.move.toFixed(1)+'%</small></div>'}
function draw(){if(!DATA)return;var d=DATA,b=d.banner;
 var el=document.getElementById("banner");el.className="banner"+(b.ok?"":(b.verdict==="NO_TRADE"||b.entries==="PAUSED"?" bad":" warn"));
 el.innerHTML='<h1>'+b.headline+'</h1><div class="sub">'+b.detail+' &middot; entries <b>'+b.entries+'</b> &middot; day verdict <b>'+b.verdict.replace("_"," ")+'</b> &middot; '+b.message+'</div>';
 var names=["WATCH","EARLY WARNING","BUILDING","READY","IN TRADE"];
 document.getElementById("cols").innerHTML=names.map(function(n){var L=d.stages[n]||[];return'<div class="col"><h2>'+n+'<span>'+L.length+'</span></h2>'+(L.slice(0,14).map(chip).join("")||'<div class="muted">none</div>')+(L.length>14?'<div class="muted">+'+(L.length-14)+' more</div>':'')+'</div>'}).join("");
 var G=d.stages["GATED"]||[];document.getElementById("gcount").textContent=G.length;
 document.getElementById("gated").innerHTML=G.map(function(c){return'<div class="row"><span>'+(/BULL/i.test(c.direction)?"&#9650; ":"&#9660; ")+'<b>'+c.symbol+'</b></span><small>'+c.reason+'</small></div>'}).join("")||'<div class="muted">nothing held back right now</div>';
 var I=d.stages["INVALIDATED"]||[];document.getElementById("icount").textContent=I.length;
 document.getElementById("invalid").innerHTML=I.slice(0,20).map(function(c){return'<div class="row"><span>'+(/BULL/i.test(c.direction)?"&#9650; ":"&#9660; ")+'<b>'+c.symbol+'</b></span><small>'+c.reason+'</small></div>'}).join("")||'<div class="muted">none</div>';
 var kinds=["ALL","ENTRY","EXIT","BLOCKED","MANUAL"];
 document.getElementById("tabs").innerHTML=kinds.map(function(k){return'<button class="'+(k===TAPE_F?"on":"")+'" data-k="'+k+'">'+k+'</button>'}).join("");
 document.querySelectorAll("#tabs button").forEach(function(x){x.onclick=function(){TAPE_F=x.dataset.k;draw()}});
 var T=(d.tape||[]).filter(function(e){return TAPE_F==="ALL"||e.kind===TAPE_F});
 document.getElementById("tape").innerHTML='<h2>DECISION TAPE &mdash; every entry, exit, held-back signal and manual order today'+(d.tape_loading?' (loading earlier cycles...)':'')+'</h2>'
  +(T.map(function(e){return'<div class="e"><span class="muted">'+e.time+'</span><span class="k '+e.kind+'">'+e.kind+'</span><span class="'+(e.tone||"")+'">'+e.text+(e.detail?' <small class="muted">'+e.detail+'</small>':'')+'</span></div>'}).join("")||'<div class="muted">nothing yet</div>');
 document.getElementById("foot").textContent="Updated "+d.updated+" - scanner cycle "+(d.cycle_at||"-")+" - V2 top-5 up: "+(d.v2_top.up||[]).join(", ")+" | down: "+(d.v2_top.down||[]).join(", ")}
function load(){fetch("/api/pipeline",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){DATA=d;draw()}).catch(function(){})}
load();setInterval(load,10000);
</script></body></html>
"""
