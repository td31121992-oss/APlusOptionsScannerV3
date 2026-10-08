"""Market Mood: one 0-100 score (0 = very bearish, 100 = very bullish) built from five transparent parts. Read-only.

  Index trend   35%  NIFTY and BANKNIFTY change vs the previous close (-1.5% .. +1.5% maps to 0..100)
  Breadth       30%  share of F&O stocks that are up (up / (up + down))
  Typical stock 15%  median F&O stock change vs the previous close (-1.5% .. +1.5%)
  Volatility    10%  India VIX change vs the previous close (rising VIX = fear; +10% .. -10% maps to 0..100)
  Order flow    10%  average resting buy minus sell quantity across the stocks (order-book recorder, -0.3 .. +0.3)

If a part has no data its weight is shared out among the others. Labels: Very bearish < 20, Bearish < 40, Neutral < 60,
Bullish < 80, Very bullish. It describes the mood so far today; it is not a prediction.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parent
WEIGHTS = {"index": 35, "breadth": 30, "median": 15, "vix": 10, "flow": 10}


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _scale(value: float, low: float, high: float) -> float:
    return max(0.0, min(100.0, (value - low) / (high - low) * 100.0))


def label(score: float) -> str:
    return ("Very bearish" if score < 20 else "Bearish" if score < 40 else "Neutral" if score < 60
            else "Bullish" if score < 80 else "Very bullish")


def compute(context: dict[str, Any] | None, rows: list[dict[str, Any]], flow: float | None) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    ctx = context or {}
    nifty, bank = _f(ctx.get("nifty_pct_prev")), _f(ctx.get("banknifty_pct_prev"))
    idx = [x for x in (nifty, bank) if x is not None]
    if idx:
        avg = sum(idx) / len(idx)
        parts.append({"key": "index", "name": "Index trend", "text": f"NIFTY {nifty:+.2f}%" + (f", BANKNIFTY {bank:+.2f}%" if bank is not None else ""),
                      "score": _scale(avg, -1.5, 1.5)})
    changes = [c for c in (_f(r.get("from_prev_close_pct")) for r in rows) if c is not None]
    up, down = sum(c > 0 for c in changes), sum(c < 0 for c in changes)
    if up + down > 0:
        parts.append({"key": "breadth", "name": "Breadth", "text": f"{up} up / {down} down", "score": up / (up + down) * 100.0})
    if changes:
        med = median(changes)
        parts.append({"key": "median", "name": "Typical stock", "text": f"median {med:+.2f}%", "score": _scale(med, -1.5, 1.5)})
    vix, vix_chg = _f(ctx.get("vix")), _f(ctx.get("vix_pct_prev"))
    if vix_chg is not None:
        parts.append({"key": "vix", "name": "Volatility (VIX)", "text": f"{vix:.1f} ({vix_chg:+.1f}%)" if vix is not None else f"{vix_chg:+.1f}%",
                      "score": _scale(-vix_chg, -10.0, 10.0)})
    if flow is not None:
        parts.append({"key": "flow", "name": "Order flow", "text": f"net {flow:+.2f}", "score": _scale(flow, -0.3, 0.3)})
    total_w = sum(WEIGHTS[p["key"]] for p in parts)
    if not total_w:
        return {"ok": False, "error": "no market data yet"}
    score = sum(p["score"] * WEIGHTS[p["key"]] for p in parts) / total_w
    for p in parts:
        p["weight"] = round(WEIGHTS[p["key"]] / total_w * 100)
        p["score"] = round(p["score"])
    return {"ok": True, "score": round(score), "label": label(score), "regime": ctx.get("regime", ""), "parts": parts}


def payload(root: Path = ROOT) -> dict[str, Any]:
    context = None
    try:
        with (root / "data" / "market_context" / f"{date.today().isoformat()}.csv").open(encoding="utf-8") as handle:
            all_rows = list(csv.DictReader(handle))
        context = all_rows[-1] if all_rows else None
    except OSError:
        pass
    rows: list[dict[str, Any]] = []
    try:
        report = json.loads((root / "data" / "reports" / "intraday_movement_latest.json").read_text(encoding="utf-8"))
        rows = (report.get("fno_market_watch") or {}).get("rows", [])
    except (OSError, ValueError):
        pass
    flow = None
    try:
        from intraday_signals import load_book_stats

        imb = [float(s["imbalance"]) for s in load_book_stats().values() if s.get("imbalance") is not None]
        flow = sum(imb) / len(imb) if imb else None
    except Exception:                                      # noqa: BLE001
        pass
    out = compute(context, rows, flow)
    out["as_of"] = (context or {}).get("time", "")
    return out


MOOD_WIDGET_HTML = """
<div id="aplus-mood" style="position:fixed;left:12px;bottom:12px;z-index:9998;background:#121a2d;border:1px solid #27334d;border-radius:12px;padding:8px 12px;font:600 13px system-ui,sans-serif;color:#e7eefc;box-shadow:0 4px 18px rgba(0,0,0,.45);max-width:300px;cursor:pointer">
<div style="display:flex;align-items:center;gap:8px"><span style="color:#8ea0bd">Market mood</span><b id="aplus-mood-label">...</b><span id="aplus-mood-score" style="margin-left:auto;font-weight:800">-</span></div>
<div style="height:8px;border-radius:6px;margin-top:6px;background:linear-gradient(90deg,#ff6363,#f5b942 50%,#2ecc71);position:relative"><div id="aplus-mood-pin" style="position:absolute;top:-3px;width:4px;height:14px;background:#fff;border-radius:2px;left:50%"></div></div>
<div id="aplus-mood-detail" style="display:none;margin-top:8px;font-weight:500;font-size:12px;color:#8ea0bd"></div></div>
<script>(function(){var box=document.getElementById('aplus-mood');if(!box)return;
function load(){fetch('/api/market-mood',{cache:'no-store'}).then(function(r){return r.json()}).then(function(d){if(!d.ok){document.getElementById('aplus-mood-label').textContent='no data';return}
document.getElementById('aplus-mood-label').textContent=d.label;document.getElementById('aplus-mood-score').textContent=d.score+'/100';document.getElementById('aplus-mood-pin').style.left='calc('+d.score+'% - 2px)';
document.getElementById('aplus-mood-label').style.color=d.score<40?'#ff6363':d.score<60?'#f5b942':'#2ecc71';
document.getElementById('aplus-mood-detail').innerHTML=d.parts.map(function(p){return '<div style="display:flex;justify-content:space-between;gap:8px"><span>'+p.name+' <small>('+p.weight+'%)</small></span><span style="color:#e7eefc">'+p.text+'</span></div>'}).join('')+'<div style="margin-top:4px;font-size:11px">0 = very bearish, 100 = very bullish. Today so far, not a forecast.</div>'}).catch(function(){})}
box.addEventListener('click',function(){var x=document.getElementById('aplus-mood-detail');x.style.display=x.style.display==='none'?'block':'none'});
load();setInterval(load,30000)})();</script>
"""
