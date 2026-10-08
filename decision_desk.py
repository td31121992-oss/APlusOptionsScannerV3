"""Decision Desk: for every candidate the scanner analysed, show which gates it passed or failed and the numbers behind it.

Read-only. It reads the scanner's latest report (data/reports/intraday_movement_latest.json) and the market-regime tape, and
explains each candidate in one row: setup, strength numbers, the A+ gate, the V2 gate, the market-regime filter, the safety
gate and the final status, so you can see why a trade was taken or not.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "data" / "reports" / "intraday_movement_latest.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if out == out else default
    except (TypeError, ValueError):
        return default


def _regime(root: Path) -> str:
    path = root / "data" / "market_context" / f"{date.today().isoformat()}.csv"
    try:
        with path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        return rows[-1].get("regime", "UNKNOWN") if rows else "UNKNOWN"
    except OSError:
        return "UNKNOWN"


def _direction_allowed(regime: str, direction: str) -> bool:
    try:
        import market_context

        return bool(market_context.direction_allowed(regime, direction))
    except Exception:                                      # noqa: BLE001
        return True


def build_rows(report: dict[str, Any], regime: str) -> list[dict[str, Any]]:
    selective = {(x.get("symbol"), x.get("direction")): x.get("status", "") for x in
                 (report.get("aplus_selective_gate") or {}).get("rejected_symbols", [])}
    v2 = report.get("stock_selection_v2") or {}
    v2_blocked = {(x.get("symbol"), x.get("direction")): x.get("reasons", []) for x in v2.get("blocked", [])}
    rows = []
    for c in report.get("candidates", []):
        key = (c.get("symbol"), c.get("direction"))
        entry_ready = str(c.get("shortlist", "")).upper() == "ENTRY_READY" or bool(c.get("actionable"))
        if not entry_ready and key not in selective and key not in v2_blocked and not c.get("paper_trade_id"):
            continue
        entry, stop, t1 = _f(c.get("underlying_entry")), _f(c.get("underlying_stop")), _f(c.get("underlying_target1"))
        risk = abs(entry - stop)
        rr = abs(t1 - entry) / risk if risk > 0 and t1 > 0 else 0.0
        a_plus = f"REJECT: {selective[key]}" if key in selective else ("PASS" if entry_ready else "-")
        v2_state = ("BLOCK: " + ", ".join(str(r).split("(")[0] for r in v2_blocked[key])) if key in v2_blocked else (
            "PASS" if entry_ready and key not in selective else "-")
        allowed = _direction_allowed(regime, str(c.get("direction", "")))
        status = str(c.get("paper_trade_status") or "")
        safety = str(c.get("safety_decision") or "")
        traded = bool(c.get("paper_trade_id"))
        rows.append({
            "symbol": c.get("symbol"), "direction": c.get("direction"), "side": "CE" if c.get("direction") == "BULLISH" else "PE",
            "setup": c.get("setup_family") or "", "stage": c.get("stage") or "", "pivot_state": c.get("pivot_state") or "",
            "quality": round(_f(c.get("trade_quality_score")), 1), "move_open": round(_f(c.get("move_from_0915_open_percent")), 2),
            "day_change": round(_f(c.get("day_change_percent")), 2), "rvol": round(_f(c.get("relative_volume")), 2),
            "rvol_15m": round(_f(c.get("recent_relative_volume_15m")), 2), "vwap_dist": round(_f(c.get("vwap_distance_percent")), 2),
            "adx": round(_f(c.get("adx14_5m")), 0), "rsi": round(_f(c.get("rsi14_5m")), 0),
            "atr5_pct": round(_f(c.get("atr_5m")) / _f(c.get("ltp"), 1) * 100, 2) if _f(c.get("ltp")) > 0 else 0.0,
            "risk_pct": round(_f(c.get("underlying_risk_percent")), 2), "rr": round(rr, 1),
            "extension_atr": round(_f(c.get("extension_atr")), 1), "ltp": _f(c.get("ltp")),
            "gate_aplus": a_plus, "gate_v2": v2_state, "gate_regime": "PASS" if allowed else f"BLOCK: {regime} market",
            "gate_safety": safety or "-", "status": "TRADED" if traded else (status or ("READY" if entry_ready else "-")),
            "trade_id": c.get("paper_trade_id") or "",
        })
    order = {"TRADED": 0}
    rows.sort(key=lambda r: (order.get(r["status"], 1), -r["quality"]))
    return rows


def payload(root: Path = ROOT) -> dict[str, Any]:
    try:
        report = json.loads((root / "data" / "reports" / "intraday_movement_latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": "scanner report not available", "rows": []}
    regime = _regime(root)
    rows = build_rows(report, regime)
    return {"ok": True, "generated_at": report.get("generated_at", ""), "phase": report.get("session_phase", ""),
            "regime": regime, "entry_ready": report.get("entry_ready_count", 0), "traded_today": report.get("paper_trades_today", 0),
            "counts": {"traded": sum(r["status"] == "TRADED" for r in rows),
                       "passed_all": sum(r["gate_aplus"] == "PASS" and r["gate_v2"] == "PASS" and r["gate_regime"] == "PASS" for r in rows),
                       "blocked": sum(("BLOCK" in r["gate_v2"] or "REJECT" in r["gate_aplus"] or "BLOCK" in r["gate_regime"]) for r in rows)},
            "rows": rows}


DECISION_DESK_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Decision Desk</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--green:#2ecc71;--red:#ff6363;--amber:#f5b942;--blue:#4c8dff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.35 -apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1500px;margin:0 auto;padding:14px}h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);font-size:12.5px}
.bar{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.chip{padding:7px 12px;border:1px solid var(--line);border-radius:999px;background:var(--panel);color:var(--muted);font-weight:700;cursor:pointer}
.chip.on{background:var(--blue);border-color:var(--blue);color:#fff}.stat{padding:7px 12px;border:1px solid var(--line);border-radius:10px;background:var(--panel)}.stat b{color:var(--text)}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:12px}table{border-collapse:collapse;width:100%;min-width:1180px;background:var(--panel)}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{position:sticky;top:0;background:#18223a;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.3px}
td.n{text-align:right}.ok{color:var(--green);font-weight:700}.no{color:var(--red);font-weight:700}.mid{color:var(--amber);font-weight:700}.sym{font-weight:800}
.pill{border-radius:6px;padding:2px 7px;font-size:12px;font-weight:800}.pill.t{background:#12351f;color:var(--green)}.pill.b{background:#3a1717;color:var(--red)}.pill.w{background:#2a3350;color:#9fb3ff}
.note{color:var(--muted);font-size:12px;margin-top:10px}a.nav{color:var(--blue);text-decoration:none;font-weight:700;margin-right:12px}
</style></head><body><div class="wrap">
<div><a class="nav" href="/">Dashboard</a><a class="nav" href="/positions">Positions</a><a class="nav" href="/control-room">Control room</a><a class="nav" href="/alerts">Alerts</a></div>
<h1>Decision Desk</h1><div class="sub" id="asof">loading...</div>
<div class="bar" id="stats"></div>
<div class="bar" id="chips"><span class="chip on" data-f="ALL">All</span><span class="chip" data-f="TRADED">Traded</span><span class="chip" data-f="PASS">Passed every gate</span><span class="chip" data-f="BLOCKED">Blocked</span><span class="chip" data-f="CE">Calls</span><span class="chip" data-f="PE">Puts</span></div>
<div class="scroll"><table><thead><tr><th>Symbol</th><th>Side</th><th>Setup</th><th class="n">Qual</th><th class="n">From open %</th><th class="n">RVOL / 15m</th><th class="n">VWAP dist %</th><th class="n">ADX / RSI</th><th class="n">ATR5 %</th><th class="n">Stop % / RR</th><th>A+ gate</th><th>V2 gate</th><th>Market</th><th>Status</th></tr></thead><tbody id="rows"></tbody></table></div>
<div class="note">Read-only view of the scanner's latest cycle. "Qual" is the trade-quality score, "ATR5" the 5-minute average range as % of price, "Stop % / RR" the underlying stop distance and reward-to-risk to target 1. A gate shows the first reason it failed. Paper trading only.</div>
</div><script>
var f="ALL",data=null;
function g(s){if(!s||s==="-")return'<span class="sub">-</span>';return s==="PASS"?'<span class="ok">PASS</span>':'<span class="no">'+s.replace(/A_PLUS_WAIT_/,"wait ").replace(/_/g," ").toLowerCase()+'</span>'}
function show(r){if(f==="ALL")return true;if(f==="TRADED")return r.status==="TRADED";if(f==="CE"||f==="PE")return r.side===f;
 var blk=/BLOCK|REJECT/.test(r.gate_aplus+r.gate_v2+r.gate_regime);if(f==="BLOCKED")return blk;return !blk&&r.gate_aplus==="PASS"&&r.gate_v2==="PASS"}
function render(){if(!data)return;var d=data;
 document.getElementById("asof").textContent=(d.phase||"")+" - report "+String(d.generated_at||"").slice(11,19)+" - market regime "+d.regime;
 document.getElementById("stats").innerHTML='<div class="stat">Entry-ready <b>'+d.entry_ready+'</b></div><div class="stat">Passed every gate <b>'+d.counts.passed_all+'</b></div><div class="stat">Blocked <b>'+d.counts.blocked+'</b></div><div class="stat">Traded today <b>'+d.traded_today+'</b></div>';
 var rows=(d.rows||[]).filter(show);
 document.getElementById("rows").innerHTML=rows.length?rows.map(function(r){
  var st=r.status==="TRADED"?'<span class="pill t">TRADED</span>':/BLOCK|REJECT|WAIT/.test(r.status)?'<span class="pill b">'+r.status.replace(/_/g," ").toLowerCase()+'</span>':'<span class="pill w">'+r.status+'</span>';
  return '<tr><td class="sym">'+r.symbol+'</td><td>'+r.side+' <span class="sub">'+(r.direction||"").slice(0,4).toLowerCase()+'</span></td><td>'+(r.setup||"").replace(/_/g," ").toLowerCase()+'</td><td class="n">'+r.quality+'</td>'
  +'<td class="n '+(r.move_open>=0?"ok":"no")+'">'+r.move_open+'</td><td class="n">'+r.rvol+' / '+r.rvol_15m+'</td><td class="n">'+r.vwap_dist+'</td><td class="n">'+r.adx+' / '+r.rsi+'</td><td class="n">'+r.atr5_pct+'</td><td class="n">'+r.risk_pct+' / '+r.rr+'</td>'
  +'<td>'+g(r.gate_aplus)+'</td><td>'+g(r.gate_v2)+'</td><td>'+g(r.gate_regime)+'</td><td>'+st+'</td></tr>'}).join(""):'<tr><td colspan="14" class="sub" style="padding:24px;text-align:center">No candidates match</td></tr>'}
document.getElementById("chips").addEventListener("click",function(e){var t=e.target.getAttribute("data-f");if(!t)return;f=t;[].forEach.call(document.querySelectorAll(".chip"),function(c){c.className="chip"+(c.getAttribute("data-f")===f?" on":"")});render()});
function load(){fetch("/api/decision-desk",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){data=d.ok?d:null;if(!d.ok)document.getElementById("asof").textContent=d.error;render()}).catch(function(){})}
load();setInterval(load,10000);
</script></body></html>
"""
