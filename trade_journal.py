"""Trade Journal: every paper trade with the reasons it was taken, how it played out, what it taught, and your own notes.

One place that joins what the system already records:
  * the trade itself and its path (entry/exit, high and low with times, MFE/MAE, targets hit, costs)  - paper_trade_history.csv, the live journal
  * why it was taken (setup, stage, tier, scores, pivot state, safety decision, market regime at entry, breadth and order-block tags)
  * how it ended and a plain-language lesson (gave back a gain, never in profit, deep drawdown, ...)
  * the exit rules that were tested in shadow and what each would have done (ladder, trail60, half-at-+10%, peak-drop)
  * YOUR notes, tags and a 1-5 execution rating per trade (data/journal/notes.json)
plus period statistics (win rate, profit factor, expectancy, drawdown, streaks) and breakdowns by setup, hour, side and exit reason.
Read-only on trading data; only the notes file is written.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import trade_review

ROOT = Path(__file__).resolve().parent
NOTES_LOCK = threading.Lock()
MAX_NOTE = 4000
TAG_CHOICES = ["good entry", "bad entry", "good exit", "exit too early", "gave back profit", "stopped out", "chased", "against market", "news", "lesson learned"]


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def _hm(v: Any) -> str:
    s = str(v or "")
    return s[11:16] if len(s) >= 16 else ""


def _day(t: dict[str, Any]) -> str:
    pid = str(t.get("paper_trade_id", ""))
    if pid[3:11].isdigit():
        return f"{pid[3:7]}-{pid[7:9]}-{pid[9:11]}"
    return str(t.get("entry_time") or t.get("generated_at") or "")[:10]


def _read_csv(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def load_trades(root: Path = ROOT) -> list[dict[str, Any]]:
    """Union of the history file, today's report and the live journal (richest record wins per trade id)."""
    by_id: dict[str, dict[str, Any]] = {}
    for rows in (_read_csv(root / "data" / "reports" / "paper_trade_history.csv"), _read_csv(root / "data" / "reports" / "paper_trades.csv")):
        for r in rows:
            if r.get("paper_trade_id"):
                by_id[r["paper_trade_id"]] = {**by_id.get(r["paper_trade_id"], {}), **{k: v for k, v in r.items() if v not in ("", None)}}
    try:
        data = json.loads((root / "data" / "intraday_movement" / "paper_trade_journal.json").read_text(encoding="utf-8"))
        for r in data.get("trades", []):
            if r.get("paper_trade_id"):
                by_id[r["paper_trade_id"]] = {**by_id.get(r["paper_trade_id"], {}), **{k: v for k, v in r.items() if v not in ("", None)}}
    except (OSError, ValueError):
        pass
    return sorted(by_id.values(), key=lambda t: str(t.get("entry_time") or t.get("generated_at") or ""))


def regime_lookup(root: Path, day: str) -> list[tuple[str, str, str]]:
    rows = _read_csv(root / "data" / "market_context" / f"{day}.csv")
    return [(str(r.get("time", ""))[11:16], r.get("regime", ""), r.get("nifty_pct_prev", "")) for r in rows]


def lessons(r: dict[str, Any]) -> list[str]:
    """Plain-language observations from the numbers (never a prediction)."""
    out: list[str] = []
    mfe, mae, ret, kept = r["mfe_pct"], r["mae_pct"], r["return_pct"], r["captured_pct"]
    closed = r["status"] == "CLOSED"
    if mfe >= 15 and ret <= mfe * 0.5:
        out.append(f"Peaked at {mfe:+.0f}% ({r['high_time'] or '?'}) but {'exited' if closed else 'is'} at {ret:+.0f}% - gave back {mfe - ret:.0f} points of the move (kept {kept}% of the peak).")
    if closed and mfe <= 3 and ret < 0:
        out.append(f"Never got into profit (best {mfe:+.0f}%) - the entry went straight against us.")
    if mae <= -15 and ret > 0:
        out.append(f"Survived a {mae:+.0f}% drawdown ({r['low_time'] or '?'}) before recovering - the stop was close to being hit.")
    if closed and r["exit_reason"] in ("SESSION_END_LAST_MARK", "SESSION_END", "PRIOR_SESSION_UNRESOLVED"):
        out.append("Closed by the session-end rule, not by a stop or target.")
    if r["exit_reason"] == "OPTION_STOP_LOSS" and mfe >= 10:
        out.append(f"Was up {mfe:+.0f}% at its best, then fell to the stop - no profit lock took effect.")
    if r.get("hold_min") is not None and r["hold_min"] <= 10 and ret < 0:
        out.append(f"Lost within {r['hold_min']} minutes of entry.")
    best = max(((k[2:], v) for k, v in r.items() if k.startswith("d_") and isinstance(v, (int, float))), key=lambda kv: kv[1], default=None)
    if best and best[1] >= 500:
        out.append(f"Shadow exit '{best[0]}' would have made Rs {best[1]:+,.0f} more than the real exit.")
    return out


def entry_row(t: dict[str, Any], regimes: dict[str, list[tuple[str, str, str]]], root: Path) -> dict[str, Any]:
    r = trade_review.review_row(t)
    day = _day(t)
    et = r["entry_time"]
    if day not in regimes:
        regimes[day] = regime_lookup(root, day)
    regime = next((rg for tm, rg, _n in reversed(regimes[day]) if tm and et and tm <= et), "")
    entered, exited = trade_review._f(0), None
    try:
        a = datetime.fromisoformat(str(t.get("entry_time")))
        b = datetime.fromisoformat(str(t.get("exit_time"))) if t.get("exit_time") else None
        hold = int((b - a).total_seconds() // 60) if b else None
    except ValueError:
        hold = None
    hits = [f"T{i}@{_hm(t.get(f'target{i}_hit_at'))}" for i in (1, 2, 3) if t.get(f"target{i}_hit_at")]
    row = {
        "id": t.get("paper_trade_id"), "day": day, "symbol": r["symbol"], "side": "CE" if str(t.get("direction")).upper() == "BULLISH" else "PE",
        "direction": r["direction"], "contract": t.get("trading_symbol") or "", "lot_qty": int(_f(t.get("quantity"))),
        "setup": r["setup"], "stage": t.get("stage") or "", "tier": t.get("selection_tier") or "", "pivot_state": t.get("pivot_state") or "",
        "momentum": round(_f(t.get("momentum_score")), 1), "trend_alignment": round(_f(t.get("trend_alignment_score")), 1),
        "clean_trend": round(_f(t.get("clean_trend_score")), 1), "chase_risk": round(_f(t.get("chase_risk_score")), 1),
        "underlying_entry": _f(t.get("underlying_entry")), "underlying_stop": _f(t.get("underlying_stop")),
        "safety": t.get("safety_decision") or "", "regime": regime, "entry_reason": t.get("entry_reason") or "",
        "targets_hit": ", ".join(hits), "hold_min": hold, "breadth": r["breadth"], "ob": r["ob"],
        **{k: r[k] for k in ("entry_time", "entry_price", "high", "high_time", "low", "low_time", "exit_price", "exit_time", "status", "exit_reason",
                              "stop_pct", "mfe_pct", "mae_pct", "return_pct", "captured_pct", "capital", "spread_pct", "gross", "costs", "net")},
    }
    row.update({k: v for k, v in r.items() if k.startswith("d_") or k.startswith("hit_")})
    row["lessons"] = lessons({**row, **r})
    return row


# ----------------------------------------------------------------------------- notes
def _notes_path(root: Path) -> Path:
    return root / "data" / "journal" / "notes.json"


def load_notes(root: Path = ROOT) -> dict[str, Any]:
    try:
        return json.loads(_notes_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_note(trade_id: str, note: str, tags: list[str], rating: int, root: Path = ROOT) -> dict[str, Any]:
    trade_id = str(trade_id or "").strip()
    if not trade_id or len(trade_id) > 80:
        raise ValueError("bad trade id")
    entry = {"note": str(note or "")[:MAX_NOTE], "tags": [str(x)[:40] for x in (tags or [])][:12],
             "rating": max(0, min(5, int(rating or 0))), "updated": datetime.now().isoformat(timespec="seconds")}
    with NOTES_LOCK:
        notes = load_notes(root)
        if entry["note"] or entry["tags"] or entry["rating"]:
            notes[trade_id] = entry
        else:
            notes.pop(trade_id, None)
        path = _notes_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(notes, handle, indent=1)
        os.replace(tmp, path)
    return entry


# ----------------------------------------------------------------------------- statistics
def stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [r for r in rows if r["status"] == "CLOSED"]
    if not closed:
        return {"trades": len(rows), "closed": 0, "open": sum(1 for r in rows if r["status"] == "OPEN"), "unresolved": sum(1 for r in rows if r["status"] == "UNRESOLVED")}
    wins = [r for r in closed if r["net"] > 0]
    losses = [r for r in closed if r["net"] <= 0]
    gw, gl = sum(r["net"] for r in wins), -sum(r["net"] for r in losses)
    equity, peak, dd, cur = 0.0, 0.0, 0.0, 0
    streak = 0
    for r in closed:
        equity += r["net"]
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
        cur = cur + 1 if r["net"] <= 0 else 0
        streak = max(streak, cur)
    holds = [r["hold_min"] for r in closed if r.get("hold_min") is not None]
    return {
        "trades": len(rows), "closed": len(closed), "open": sum(1 for r in rows if r["status"] == "OPEN"),
        "unresolved": sum(1 for r in rows if r["status"] == "UNRESOLVED"), "wins": len(wins), "win_rate": round(len(wins) / len(closed) * 100, 1),
        "net": round(sum(r["net"] for r in closed)), "gross": round(sum(r["gross"] for r in closed)), "costs": round(sum(r["costs"] for r in closed)),
        "avg_win": round(gw / len(wins)) if wins else 0, "avg_loss": round(-gl / len(losses)) if losses else 0,
        "profit_factor": round(gw / gl, 2) if gl > 0 else None, "expectancy": round(sum(r["net"] for r in closed) / len(closed)),
        "best": max(closed, key=lambda r: r["net"])["net"], "worst": min(closed, key=lambda r: r["net"])["net"],
        "max_drawdown": round(dd), "max_losing_streak": streak, "avg_hold_min": round(sum(holds) / len(holds)) if holds else None,
        "avg_mfe": round(sum(r["mfe_pct"] for r in closed) / len(closed), 1), "avg_mae": round(sum(r["mae_pct"] for r in closed) / len(closed), 1),
        "avg_kept_of_peak_winners": round(sum(r["captured_pct"] for r in wins) / len(wins)) if wins else None,
        "gave_back": sum(1 for r in closed if r["mfe_pct"] >= 15 and r["return_pct"] <= r["mfe_pct"] * 0.5),
    }


def breakdown(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["status"] != "CLOSED":
            continue
        k = r["entry_time"][:2] + ":00" if key == "hour" else str(r.get(key) or "-")
        groups[k].append(r)
    return sorted(({"group": k, "trades": len(v), "wins": sum(1 for x in v if x["net"] > 0), "net": round(sum(x["net"] for x in v)),
                    "avg": round(sum(x["net"] for x in v) / len(v))} for k, v in groups.items()), key=lambda d: -d["net"])


def payload(day_from: str = "", day_to: str = "", root: Path = ROOT) -> dict[str, Any]:
    regimes: dict[str, list[tuple[str, str, str]]] = {}
    rows = []
    for t in load_trades(root):
        d = _day(t)
        if (day_from and d < day_from) or (day_to and d > day_to):
            continue
        try:
            rows.append(entry_row(t, regimes, root))
        except Exception:                                      # noqa: BLE001 - one odd record must not hide the rest
            continue
    notes = load_notes(root)
    today = datetime.now().date().isoformat()
    for r in rows:
        r["journal"] = notes.get(r["id"]) or {"note": "", "tags": [], "rating": 0}
        if r["status"] == "OPEN" and r["day"] < today:         # an older trade the system never closed: do not count it as P&L
            r["status"] = "UNRESOLVED"
    by_day: dict[str, float] = defaultdict(float)
    for r in rows:
        if r["status"] == "CLOSED":
            by_day[r["day"]] += r["net"]
    cum, curve = 0.0, []
    for d in sorted(by_day):
        cum += by_day[d]
        curve.append({"day": d, "net": round(by_day[d]), "cum": round(cum)})
    days = sorted({r["day"] for r in rows})
    return {"ok": True, "from": days[0] if days else "", "to": days[-1] if days else "", "days": days, "stats": stats(rows), "curve": curve,
            "by_setup": breakdown(rows, "setup"), "by_hour": breakdown(rows, "hour"), "by_side": breakdown(rows, "side"),
            "by_exit": breakdown(rows, "exit_reason"), "tags": TAG_CHOICES, "trades": list(reversed(rows))}


def export_csv(day_from: str = "", day_to: str = "", root: Path = ROOT) -> str:
    data = payload(day_from, day_to, root)
    cols = ["day", "id", "symbol", "side", "contract", "setup", "stage", "tier", "regime", "entry_time", "entry_price", "exit_time", "exit_price", "status",
            "exit_reason", "hold_min", "mfe_pct", "mae_pct", "return_pct", "captured_pct", "gross", "costs", "net", "targets_hit", "rating", "tags", "note", "lessons"]
    import io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in reversed(data["trades"]):
        j = r["journal"]
        w.writerow([r.get(c, "") if c not in ("rating", "tags", "note", "lessons") else
                    {"rating": j["rating"], "tags": ";".join(j["tags"]), "note": j["note"], "lessons": " | ".join(r["lessons"])}[c] for c in cols])
    return buf.getvalue()


JOURNAL_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Trade Journal</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--green:#2ecc71;--red:#ff6363;--amber:#f5b942;--blue:#4c8dff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.4 -apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1300px;margin:0 auto;padding:14px}h1{font-size:22px;margin:6px 0 2px}h2{font-size:15px;margin:18px 0 8px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.sub{color:var(--muted);font-size:12.5px}a.nav{color:var(--blue);text-decoration:none;font-weight:700;margin-right:12px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin:12px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px}
.card .l{color:var(--muted);font-size:11.5px}.card .v{font-size:20px;font-weight:800;margin-top:2px}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0}select,input,textarea,button{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:7px 10px;font:inherit}
button{cursor:pointer;font-weight:700}button.on{background:var(--blue);border-color:var(--blue)}
.up{color:var(--green);font-weight:700}.dn{color:var(--red);font-weight:700}.am{color:var(--amber);font-weight:700}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:12px}table{border-collapse:collapse;width:100%;background:var(--panel)}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{background:#18223a;color:var(--muted);font-size:12px}
td.n,th.n{text-align:right}tr.t{cursor:pointer}tr.t:hover{background:#16213b}.detail td{white-space:normal;background:#0e1730}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}.box{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px}
.chip{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:2px 9px;margin:2px;font-size:12px;cursor:pointer;color:var(--muted)}.chip.on{background:var(--blue);border-color:var(--blue);color:#fff}
#curve{height:200px}.lesson{color:var(--amber);margin:3px 0}.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:4px 14px;margin:6px 0}.kv span{color:var(--muted)}
</style></head><body><div class="wrap">
<div><a class="nav" href="/">Dashboard</a><a class="nav" href="/positions">Positions</a><a class="nav" href="/decision-desk">Decision desk</a><a class="nav" href="/live-scanner">Live scanner</a></div>
<h1>Trade Journal</h1><div class="sub" id="asof">loading...</div>
<div class="bar"><span class="sub">From</span><select id="from"></select><span class="sub">To</span><select id="to"></select>
<select id="fside"><option value="">CE + PE</option><option>CE</option><option>PE</option></select>
<select id="fres"><option value="">All results</option><option value="W">Winners</option><option value="L">Losers</option></select>
<input id="q" placeholder="Search stock / setup / note..."><button id="exp">Export CSV</button></div>
<div class="cards" id="cards"></div>
<h2>Equity curve (net Rs, closed trades, by day)</h2><div class="box"><div id="curve"></div></div>
<h2>Where the money is made and lost</h2><div class="grid" id="brk"></div>
<h2>Trades <span class="sub">(click a row for the full story, lessons and your notes)</span></h2>
<div class="scroll"><table><thead><tr><th>Date</th><th>Stock</th><th>Side</th><th>Setup</th><th>In</th><th class="n">Entry</th><th>Out</th><th class="n">Exit</th><th class="n">Hold</th><th class="n">Peak%</th><th class="n">Low%</th><th class="n">Ret%</th><th class="n">Net Rs</th><th>Exit reason</th><th>Rating</th></tr></thead><tbody id="rows"></tbody></table></div>
<div class="sub" style="margin-top:10px">All figures are paper trades after estimated costs. Lessons are plain observations from the numbers, not predictions. Your notes are saved in data/journal/notes.json.</div>
</div><script src="/static/lightweight-charts.js"></script><script>
var D=null,open_id=null,chart=null;
function m(n){return (n<0?"-":"")+"₹"+Math.abs(Math.round(n)).toLocaleString("en-IN")}
function c(n){return n>0?"up":n<0?"dn":""}
function card(l,v,cls){return '<div class="card"><div class="l">'+l+'</div><div class="v '+(cls||"")+'">'+v+'</div></div>'}
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,function(x){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[x]})}
function stars(n){return n?"★".repeat(n)+"☆".repeat(5-n):'<span class="sub">-</span>'}
function filt(){var q=document.getElementById("q").value.trim().toLowerCase(),sd=document.getElementById("fside").value,rs=document.getElementById("fres").value;
 return D.trades.filter(function(t){if(sd&&t.side!==sd)return false;if(rs==="W"&&!(t.net>0))return false;if(rs==="L"&&!(t.net<=0&&t.status==="CLOSED"))return false;
  if(q&&(t.symbol+" "+t.setup+" "+t.journal.note+" "+t.journal.tags.join(" ")).toLowerCase().indexOf(q)<0)return false;return true})}
function render(){if(!D)return;var s=D.stats;
 document.getElementById("asof").textContent=D.from+" to "+D.to+" - "+s.trades+" trades ("+s.closed+" closed"+(s.open?", "+s.open+" open":"")+(s.unresolved?", "+s.unresolved+" never closed (not counted)":"")+")";
 document.getElementById("cards").innerHTML=s.closed?[card("Net P&L",m(s.net),c(s.net)),card("Win rate",s.win_rate+"%  ("+s.wins+"/"+s.closed+")"),card("Profit factor",s.profit_factor==null?"-":s.profit_factor),
  card("Expectancy / trade",m(s.expectancy),c(s.expectancy)),card("Avg win",m(s.avg_win),"up"),card("Avg loss",m(s.avg_loss),"dn"),card("Best / worst",m(s.best)+" / "+m(s.worst)),
  card("Max drawdown",m(-s.max_drawdown),"dn"),card("Longest losing streak",s.max_losing_streak),card("Avg hold",s.avg_hold_min==null?"-":s.avg_hold_min+" min"),
  card("Avg peak / low",s.avg_mfe+"% / "+s.avg_mae+"%"),card("Kept of peak (winners)",s.avg_kept_of_peak_winners==null?"-":s.avg_kept_of_peak_winners+"%"),card("Gave back a gain",s.gave_back+" trades")].join(""):"";
 var cv=document.getElementById("curve");cv.innerHTML="";if(D.curve.length&&window.LightweightCharts){chart=LightweightCharts.createChart(cv,{autoSize:true,layout:{background:{color:"#121a2d"},textColor:"#8ea0bd"},grid:{vertLines:{color:"#1d2842"},horzLines:{color:"#1d2842"}}});
  var ser=chart.addLineSeries({color:"#4c8dff",lineWidth:2});ser.setData(D.curve.map(function(p){return{time:p.day,value:p.cum}}));
  var bars=chart.addHistogramSeries({priceScaleId:"d",priceFormat:{type:"volume"}});chart.priceScale("d").applyOptions({scaleMargins:{top:.75,bottom:0}});
  bars.setData(D.curve.map(function(p){return{time:p.day,value:p.net,color:p.net>=0?"#2ecc7188":"#ff636388"}}));chart.timeScale().fitContent()}
 var blocks=[["By setup",D.by_setup],["By entry hour",D.by_hour],["By side",D.by_side],["By exit reason",D.by_exit]];
 document.getElementById("brk").innerHTML=blocks.map(function(b){return '<div class="box"><b>'+b[0]+'</b><table>'+b[1].map(function(x){return '<tr><td>'+esc(x.group)+'</td><td class="n">'+x.wins+"/"+x.trades+'</td><td class="n '+c(x.net)+'">'+m(x.net)+'</td></tr>'}).join("")+'</table></div>'}).join("");
 var rows=filt();document.getElementById("rows").innerHTML=rows.map(function(t){var det=open_id===t.id?detail(t):"";
  return '<tr class="t" data-id="'+t.id+'"><td>'+t.day+'</td><td><b>'+t.symbol+'</b></td><td>'+t.side+'</td><td>'+esc((t.setup||"").replace(/_/g," ").toLowerCase())+'</td><td>'+t.entry_time+'</td><td class="n">'+t.entry_price.toFixed(2)+'</td><td>'+(t.status==="UNRESOLVED"?"no exit":(t.exit_time||"open"))+'</td><td class="n">'+t.exit_price.toFixed(2)+'</td><td class="n">'+(t.hold_min==null?"-":t.hold_min+"m")+'</td><td class="n up">'+t.mfe_pct+'</td><td class="n dn">'+t.mae_pct+'</td><td class="n '+c(t.return_pct)+'">'+t.return_pct+'</td><td class="n '+c(t.net)+'">'+m(t.net)+'</td><td>'+esc((t.exit_reason||t.status).replace(/_/g," ").toLowerCase())+'</td><td>'+stars(t.journal.rating)+'</td></tr>'+det}).join("")||'<tr><td colspan="15" class="sub" style="padding:20px;text-align:center">No trades match</td></tr>'}
function detail(t){var j=t.journal,sh=Object.keys(t).filter(function(k){return k.indexOf("d_")===0&&t[k]!==0}).map(function(k){return esc(k.slice(2))+": "+m(t[k])}).join(" | ");
 var tags=D.tags.map(function(x){return '<span class="chip'+(j.tags.indexOf(x)>=0?" on":"")+'" data-tag="'+x+'">'+x+'</span>'}).join("");
 return '<tr class="detail"><td colspan="15"><div class="kv"><div><span>Contract</span> '+esc(t.contract)+'</div><div><span>Quantity</span> '+t.lot_qty+'</div><div><span>Stage / tier</span> '+esc(t.stage)+' / '+esc(t.tier)+'</div><div><span>Pivot state</span> '+esc(t.pivot_state)+'</div>'
  +'<div><span>Momentum / trend / clean / chase</span> '+t.momentum+' / '+t.trend_alignment+' / '+t.clean_trend+' / '+t.chase_risk+'</div><div><span>Safety</span> '+esc(t.safety)+'</div><div><span>Market regime at entry</span> '+esc(t.regime||"-")+'</div><div><span>Breadth tag</span> '+esc(t.breadth||"-")+'</div>'
  +'<div><span>High</span> '+t.high+' @ '+(t.high_time||"-")+'</div><div><span>Low</span> '+t.low+' @ '+(t.low_time||"-")+'</div><div><span>Targets hit</span> '+esc(t.targets_hit||"none")+'</div><div><span>Stop distance</span> '+t.stop_pct+'%</div>'
  +'<div><span>Gross / costs / net</span> '+m(t.gross)+' / '+m(t.costs)+' / '+m(t.net)+'</div><div><span>Kept of peak</span> '+(t.return_pct>0?t.captured_pct+'%':'n/a (not a winner)')+'</div></div>'
  +(t.lessons.length?t.lessons.map(function(x){return '<div class="lesson">&#9679; '+esc(x)+'</div>'}).join(""):'<div class="sub">No automatic lesson for this trade.</div>')
  +(sh?'<div class="sub" style="margin:6px 0">Shadow exits vs real (Rs): '+sh+'</div>':'')
  +'<div style="margin:8px 0">'+tags+'</div><div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start"><textarea id="note" rows="3" style="flex:1;min-width:260px" placeholder="What did you see? What would you do differently?">'+esc(j.note)+'</textarea>'
  +'<select id="rate">'+[0,1,2,3,4,5].map(function(i){return '<option value="'+i+'"'+(i===j.rating?" selected":"")+'>'+(i?i+" star"+(i>1?"s":"")+" execution":"No rating")+'</option>'}).join("")+'</select><button id="save">Save note</button> <a class="nav" href="/trade?id='+encodeURIComponent(t.id)+'">Open trade chart</a><span id="saved" class="sub"></span></div></td></tr>'}
function load(){var f=document.getElementById("from").value,t=document.getElementById("to").value;
 fetch("/api/journal?from="+f+"&to="+t,{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){var first=!D;D=d;
  if(first||!document.getElementById("from").options.length){var o=d.days.map(function(x){return '<option>'+x+'</option>'}).join("");document.getElementById("from").innerHTML=o;document.getElementById("to").innerHTML=o;
   document.getElementById("from").value=d.days[0]||"";document.getElementById("to").value=d.days[d.days.length-1]||""}render()})}
document.getElementById("from").onchange=load;document.getElementById("to").onchange=load;["fside","fres"].forEach(function(i){document.getElementById(i).onchange=render});document.getElementById("q").oninput=render;
document.getElementById("exp").onclick=function(){location.href="/api/journal.csv?from="+document.getElementById("from").value+"&to="+document.getElementById("to").value};
document.getElementById("rows").addEventListener("click",function(e){var chip=e.target.closest(".chip");
 if(chip){var t=D.trades.filter(function(x){return x.id===open_id})[0];var tag=chip.getAttribute("data-tag"),i=t.journal.tags.indexOf(tag);if(i>=0)t.journal.tags.splice(i,1);else t.journal.tags.push(tag);chip.classList.toggle("on");return}
 if(e.target.id==="save"){var t2=D.trades.filter(function(x){return x.id===open_id})[0];t2.journal.note=document.getElementById("note").value;t2.journal.rating=parseInt(document.getElementById("rate").value,10);
  fetch("/api/journal-note",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:t2.id,note:t2.journal.note,tags:t2.journal.tags,rating:t2.journal.rating})}).then(function(r){return r.json()}).then(function(j){document.getElementById("saved").textContent=j.ok?" saved":" not saved: "+(j.message||"error")}).catch(function(){document.getElementById("saved").textContent=" not saved"});return}
 if(e.target.closest(".detail")||e.target.closest("a")||e.target.closest("textarea")||e.target.closest("select"))return;
 var tr=e.target.closest("tr.t");if(!tr)return;var id=tr.getAttribute("data-id");open_id=open_id===id?null:id;render()});
load();
</script></body></html>
"""
