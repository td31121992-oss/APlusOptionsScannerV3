"""Contract Lab: why the scanner would (or would not) buy each strike of an option chain. READ-ONLY - nothing here touches the scanner, a signal or a trade.

    /contract-lab?symbol=SBIN&side=CE            the page
    /api/contract-lab?symbol=SBIN&side=CE&expiry=2026-11-23     the data behind it

For a stock, a side (calls = bullish, puts = bearish) and an expiry the lab fetches the current option chain and runs the SAME OptionSelector the scanner uses on every strike:
the selector's own pass / fail decides ELIGIBLE or REJECTED and its own score ranks the eligible strikes, so the page can never disagree with the scanner. The lab only adds the
explanation: every check with the actual number and the limit, the four score parts with their weights, and a sentence in plain words. The strike the scanner would pick right now
(selector.select) is marked CHOSEN, with the order it would place (price, lots, stop, targets).

Score = 35% closeness to the target strike (about 0.5% in the money) + 30% tight spread + 20% open interest + 15% volume; each part is 0-100 (see SCORE_PARTS).
"""

from __future__ import annotations

import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}
_LOCK = threading.Lock()
CACHE_SECONDS = 15.0

SCORE_PARTS = (("closeness", "Closeness to target strike", 0.35), ("spread", "Tight bid-ask spread", 0.30), ("oi", "Open interest", 0.20), ("volume", "Traded volume", 0.15))


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def _inr(v: float) -> str:
    return f"₹{v:,.2f}"


def evaluate_leg(selector: Any, leg: Any, contract: Any, option_type: str, spot: float) -> dict[str, Any]:
    """One strike: the selector's verdict plus every check, the score parts and a plain-words reason."""
    cfg = selector.config
    ltp, bid, ask = selector._positive_float(leg.ltp), selector._positive_float(leg.bid), selector._positive_float(leg.ask)
    strike = selector._positive_float(leg.strike)
    lot = selector._positive_int(getattr(contract, "lot_size", 0)) if contract is not None else None
    tick = selector._positive_float(getattr(contract, "tick_size", 0)) if contract is not None else None
    oi, vol = int(leg.oi or 0), int(leg.volume or 0)

    spread = ((ask - bid) / ask * 100.0) if (bid and ask and ask >= bid) else None
    dist = abs(strike - spot) / spot * 100.0 if strike and spot else None
    target = spot * (1.0 - cfg.target_itm_percent / 100.0) if option_type == "CE" else spot * (1.0 + cfg.target_itm_percent / 100.0)
    tdist = abs(strike - target) / spot * 100.0 if strike and spot else None
    entry = selector._round_up(ask * (1.0 + cfg.limit_buffer_percent / 100.0), tick) if (ask and tick) else None
    lots = None
    prem_lot = None
    if entry and lot:
        prem_lot = entry * lot
        risk_lot = entry * cfg.option_stop_loss_percent / 100.0 * lot
        lots = min(cfg.maximum_lots, int(cfg.maximum_premium_per_trade // prem_lot), int(cfg.maximum_risk_per_trade // risk_lot))

    checks = [
        {"key": "premium", "label": "Premium in range", "ok": bool(ltp and cfg.minimum_ltp <= ltp <= cfg.maximum_ltp),
         "detail": f"price {_inr(ltp or 0)}; allowed {_inr(cfg.minimum_ltp)} to {_inr(cfg.maximum_ltp)}"},
        {"key": "depth", "label": "Real bid and ask", "ok": bool(bid and ask and ask >= bid),
         "detail": f"bid {_inr(bid or 0)}, ask {_inr(ask or 0)}" if (bid and ask) else "no bid or no ask in the book"},
        {"key": "spread", "label": "Spread not too wide", "ok": bool(spread is not None and spread <= cfg.maximum_spread_percent),
         "detail": (f"spread {spread:.2f}% of the ask; limit {cfg.maximum_spread_percent:.1f}%" if spread is not None else "spread unknown (no usable bid/ask)")},
        {"key": "oi", "label": "Enough open interest", "ok": oi >= cfg.minimum_oi, "detail": f"open interest {oi:,}; needs at least {cfg.minimum_oi:,}"},
        {"key": "volume", "label": "Enough volume", "ok": vol >= cfg.minimum_volume, "detail": f"volume {vol:,}; needs at least {cfg.minimum_volume:,}"},
        {"key": "contract", "label": "Contract data known", "ok": bool(lot and tick and strike), "detail": (f"lot size {lot}, tick {tick}" if (lot and tick) else "lot size or tick size missing")},
        {"key": "distance", "label": "Close enough to the stock price", "ok": bool(dist is not None and dist <= cfg.maximum_moneyness_percent),
         "detail": (f"strike is {dist:.2f}% from the stock price; limit {cfg.maximum_moneyness_percent:.1f}%" if dist is not None else "strike unknown")},
        {"key": "buffered", "label": "Order price still affordable", "ok": bool(entry and entry <= cfg.maximum_ltp),
         "detail": (f"limit order {_inr(entry)} (ask + {cfg.limit_buffer_percent:.1f}% buffer); cap {_inr(cfg.maximum_ltp)}" if entry else "no order price")},
        {"key": "size", "label": "One lot fits the risk limits", "ok": bool(lots and lots >= 1),
         "detail": (f"{lots} lot(s): premium {_inr(prem_lot)} per lot vs ₹{cfg.maximum_premium_per_trade:,.0f} limit; risk {cfg.option_stop_loss_percent:.0f}% stop vs ₹{cfg.maximum_risk_per_trade:,.0f} limit" if prem_lot else "cannot size")},
    ]

    cand, reason = selector._candidate(leg=leg, contract=contract, option_type=option_type, spot=spot) if contract is not None else (None, "NO_CONTRACT_METADATA")
    row: dict[str, Any] = {
        "strike": strike, "security_id": str(leg.security_id), "ltp": round(_f(leg.ltp), 2), "bid": round(_f(leg.bid), 2), "ask": round(_f(leg.ask), 2),
        "spread_pct": None if spread is None else round(spread, 2), "oi": oi, "volume": vol, "iv": round(_f(leg.iv), 2),
        "from_spot_pct": None if dist is None else round(dist, 2), "from_target_pct": None if tdist is None else round(tdist, 2),
        "premium_pct_of_stock": round(_f(leg.ltp) / spot * 100.0, 2) if spot and _f(leg.ltp) else None,
        "itm": bool(strike and ((strike < spot) if option_type == "CE" else (strike > spot))),
        "checks": checks, "status": "ELIGIBLE" if cand is not None else "REJECTED", "reason_code": reason, "score": None, "parts": None,
        "order_price": entry, "lot_size": lot, "lots": lots, "premium_per_lot": None if prem_lot is None else round(prem_lot, 2), "rank": None, "why": "",
    }
    if cand is not None:
        raw = {"closeness": selector._score_inverse(cand.target_distance_percent, cfg.maximum_moneyness_percent),
               "spread": selector._score_inverse(cand.spread_percent, cfg.maximum_spread_percent),
               "oi": min(100.0, (leg.oi / max(1, cfg.minimum_oi)) * 40.0), "volume": min(100.0, (leg.volume / max(1, cfg.minimum_volume)) * 40.0)}
        row["parts"] = [{"key": k, "label": label, "weight": w, "value": round(raw[k], 1), "points": round(raw[k] * w, 1)} for k, label, w in SCORE_PARTS]
        row["score"] = round(cand.score, 2)
        row["_sort"] = (cand.score, -cand.target_distance_percent, -cand.spread_percent, leg.oi, leg.volume)
    return row


def _why(row: dict[str, Any], cfg: Any, chosen: bool) -> str:
    failed = [c for c in row["checks"] if not c["ok"]]
    if row["status"] == "REJECTED":
        if not failed:
            return "Rejected."
        more = f" (+{len(failed) - 2} more - click the row)" if len(failed) > 2 else ""
        return "Rejected: " + "; ".join(c["detail"] for c in failed[:2]) + "." + more
    bits = []
    td = row["from_target_pct"]
    bits.append("right on the ideal strike" if td is not None and td <= 0.25 else f"{td:.2f}% away from the ideal strike" if td is not None else "")
    sp = row["spread_pct"]
    if sp is not None:
        bits.append("very tight spread" if sp <= 0.8 else "acceptable spread" if sp <= 1.5 else "spread near the limit")
    bits.append(f"open interest {row['oi'] / max(1, cfg.minimum_oi):.1f}x the minimum")
    bits.append(f"volume {row['volume'] / max(1, cfg.minimum_volume):.1f}x the minimum")
    text = ", ".join(b for b in bits if b)
    return ("Chosen - highest score: " if chosen else "Eligible: ") + text + "."


def build_rows(selector: Any, snapshot: Any, underlying: Any, option_type: str) -> dict[str, Any]:
    """The chain's strikes for one side, each explained, plus what selector.select() would pick."""
    from analytics.enums import MarketBias, RecommendationType
    from option_selector import OptionSelectionError

    spot = _f(snapshot.underlying_ltp)
    contracts = list(getattr(underlying, "contracts", []) or [])
    by_id, by_key = selector._contract_indexes(contracts)
    rows = []
    for sd in snapshot.strikes:
        leg = sd.call if option_type == "CE" else sd.put
        if leg is None:
            continue
        contract = by_id.get(selector._normalize_id(leg.security_id)) or by_key.get(selector._contract_key(snapshot.expiry, leg.strike, option_type))
        rows.append(evaluate_leg(selector, leg, contract, option_type, spot))

    eligible = sorted((r for r in rows if r["status"] == "ELIGIBLE"), key=lambda r: r["_sort"], reverse=True)
    for i, r in enumerate(eligible, 1):
        r["rank"] = i

    chosen, error = None, ""
    try:
        rec, bias = (RecommendationType.BUY, MarketBias.BULLISH) if option_type == "CE" else (RecommendationType.SELL, MarketBias.BEARISH)
        sel = selector.select(snapshot=snapshot, underlying=underlying, recommendation=rec, bias=bias)
        chosen = {"strike": sel.strike, "security_id": sel.security_id, "trading_symbol": sel.trading_symbol, "limit_price": sel.limit_price, "ltp": sel.ltp, "bid": sel.bid,
                  "ask": sel.ask, "lot_size": sel.lot_size, "lots": sel.lots, "quantity": sel.quantity, "premium_per_lot": sel.premium_per_lot, "total_premium": sel.total_premium,
                  "stop_loss": sel.stop_loss, "target1": sel.target1, "target2": sel.target2, "target3": sel.target3, "total_risk": sel.total_risk, "score": sel.selection_score,
                  "reason": sel.selection_reason}
    except OptionSelectionError as exc:
        error = str(exc)

    for r in rows:
        is_chosen = bool(chosen and r["strike"] is not None and abs(float(r["strike"]) - float(chosen["strike"])) < 1e-9)
        if is_chosen:
            r["status"] = "CHOSEN"
        r["why"] = _why(r, selector.config, is_chosen)
        r.pop("_sort", None)
    counts: dict[str, int] = {}
    for r in rows:
        if r["status"] == "REJECTED":
            counts[r["reason_code"]] = counts.get(r["reason_code"], 0) + 1
    atm = min((r["strike"] for r in rows if r["strike"]), key=lambda s: abs(s - spot), default=None)
    return {"rows": rows, "chosen": chosen, "no_choice_reason": error, "spot": spot, "atm": atm, "eligible": len(eligible), "rejected": len(rows) - len(eligible),
            "rejection_counts": counts}


def _config_view(cfg: Any) -> list[dict[str, str]]:
    return [{"label": "Premium", "value": f"{_inr(cfg.minimum_ltp)} to {_inr(cfg.maximum_ltp)}"},
            {"label": "Largest bid-ask spread", "value": f"{cfg.maximum_spread_percent:.1f}% of the ask"},
            {"label": "Smallest open interest", "value": f"{cfg.minimum_oi:,}"}, {"label": "Smallest volume", "value": f"{cfg.minimum_volume:,}"},
            {"label": "Furthest from the stock price", "value": f"{cfg.maximum_moneyness_percent:.1f}%"},
            {"label": "Target strike", "value": f"{cfg.target_itm_percent:.2f}% in the money"},
            {"label": "Order price", "value": f"ask + {cfg.limit_buffer_percent:.1f}% buffer"},
            {"label": "Planned stop", "value": f"{cfg.option_stop_loss_percent:.0f}% of the premium"},
            {"label": "Position limits", "value": f"{cfg.maximum_lots} lot, premium up to ₹{cfg.maximum_premium_per_trade:,.0f}, risk up to ₹{cfg.maximum_risk_per_trade:,.0f}"}]


def symbols() -> list[str]:
    _, loader = _runtime()
    return sorted(u.symbol for u in loader.get_universe())


def _runtime() -> tuple[Any, Any]:
    import stock_analysis_tab

    return stock_analysis_tab._option_chain_runtime()


def analyse(symbol: str, side: str = "CE", expiry: str = "") -> dict[str, Any]:
    symbol = (symbol or "").strip().upper()
    side = "PE" if str(side).strip().upper() in {"PE", "PUT", "P", "PUTS"} else "CE"
    if not symbol:
        return {"ok": False, "error": "Pick a stock."}
    key = (symbol, side, expiry or "")
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    try:
        from core.option_chain import OptionChainService
        from option_selector import OptionSelector

        client, loader = _runtime()
        underlying = loader.get(symbol)
        if underlying is None:
            return {"ok": False, "error": f"{symbol} is not in the F&O list."}
        today = date.today().isoformat()
        expiries = sorted({str(getattr(c, "expiry", "") or "")[:10] for c in getattr(underlying, "contracts", []) or [] if str(getattr(c, "expiry", "") or "")})
        live = [e for e in expiries if e >= today]
        if not live:
            last = f" (the last one, {expiries[-1]}, has already expired)" if expiries else ""
            return {"ok": False, "error": f"{symbol} has no live option expiry listed right now{last}."}
        expiries = live
        use = expiry if expiry in expiries else expiries[0]
        snapshot = OptionChainService(client).fetch(underlying, expiry=use)
        selector = OptionSelector()
        built = build_rows(selector, snapshot, underlying, side)
        out = {"ok": True, "symbol": symbol, "side": side, "expiry": use, "expiries": expiries, "days_to_expiry": (date.fromisoformat(use) - date.today()).days,
               "captured_at": getattr(snapshot, "captured_at", ""), "config": _config_view(selector.config), "score_parts": [{"label": l, "weight": w} for _, l, w in SCORE_PARTS],
               "scanner_expiry": expiries[0] if expiries else "", **built}
    except Exception as exc:                                   # noqa: BLE001 - the page shows the message
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    with _LOCK:
        _CACHE[key] = (time.time(), out)
    return out


# the page ---------------------------------------------------------------------------------------------------------------------------------------------------------------
CONTRACT_LAB_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Contract Lab</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--blue:#4c8dff;--green:#27c281;--red:#ff6b6b;--amber:#f5b942}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:13px/1.4 -apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--blue);text-decoration:none;font-weight:700}
.top{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--line);background:var(--panel)}
button,input,select{background:#0e1527;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:6px 9px;font:inherit}button{cursor:pointer;font-weight:700}
button.on{background:var(--blue);border-color:var(--blue)}#sym{width:140px;text-transform:uppercase;font-weight:800}
.wrap{padding:10px 12px;max-width:1500px;margin:0 auto}.sub{color:var(--muted);font-size:12px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:8px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 12px}.card .l{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.4px}.card .v{font-size:18px;font-weight:800;margin-top:2px}
.pick{background:#0f2a22;border:1px solid #1f6b50;border-radius:10px;padding:10px 14px;margin:8px 0}.pick h3{margin:0 0 6px;font-size:14px;color:var(--green)}
.pick .g{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:6px 14px}.pick .g div span{display:block;color:#9fd9c1;font-size:11px;text-transform:uppercase}
.nopick{background:#2a1414;border:1px solid #6b2a2a;border-radius:10px;padding:10px 14px;margin:8px 0}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:6px 9px;text-align:right;border-bottom:1px solid #1b2640;white-space:nowrap}th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.35px;background:#0f1729}
td.l,th.l{text-align:left}tr.row{cursor:pointer}tr.row:hover{background:#16213a}tr.CHOSEN{background:#0f2a22}tr.REJECTED td{opacity:.62}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:800}.tag.CHOSEN{background:var(--green);color:#04251a}.tag.ELIGIBLE{background:#1c3b66;color:#cfe2ff}.tag.REJECTED{background:#3a2020;color:#ffb3b3}
.why{white-space:normal;max-width:520px;color:#c9d6ef;text-align:left}.det td{background:#0d1426;white-space:normal;text-align:left}
.chk{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:4px 18px;margin:4px 0}.chk div.ok::before{content:"\2714 ";color:var(--green)}.chk div.no::before{content:"\2716 ";color:var(--red)}
.parts{display:grid;grid-template-columns:150px 1fr 90px;gap:4px 10px;align-items:center;max-width:640px;margin-top:6px}.bar{height:8px;background:#1b2640;border-radius:5px;overflow:hidden}.bar i{display:block;height:100%;background:var(--blue)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-top:10px}.panel h3{margin:0 0 6px;font-size:13px}
.cfg{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:4px 18px}.cfg div span{color:var(--muted)}
.itm{color:var(--green)}.otm{color:var(--muted)}
</style></head><body>
<div class="top"><a href="/">&larr; Dashboard</a><b>Contract Lab</b><input id="sym" list="syms" placeholder="stock"><datalist id="syms"></datalist>
<span><button id="bce" class="on">Calls (bullish)</button> <button id="bpe">Puts (bearish)</button></span>
<select id="exp"></select><button id="go">Refresh</button><button id="far">Show far strikes</button><label class="sub"><input type="checkbox" id="auto"> auto-refresh</label><span class="sub" id="meta"></span></div>
<div class="wrap">
<div class="sub" style="margin-bottom:6px">Every strike is judged by the same selector code the scanner uses. Click a row to see each check and the score. Read-only - nothing here places or changes a trade.</div>
<div id="out"><div class="sub">Pick a stock and press Enter.</div></div></div>
<script>
var S={side:"CE",timer:null,far:false,last:null};
function fmtTs(s){if(!s)return"";try{var d=new Date(s);if(isNaN(d))return String(s).replace("T"," ").slice(0,19);return d.toLocaleString("en-GB",{timeZone:"Asia/Kolkata",hour12:false}).replace(",","")+" IST"}catch(e){return String(s).slice(0,19)}}
function esc(t){return String(t==null?"":t).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function n(v,d){return v==null?"-":Number(v).toLocaleString("en-IN",{minimumFractionDigits:d||0,maximumFractionDigits:d||0})}
function inr(v){return v==null?"-":"₹"+Number(v).toLocaleString("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2})}
function ls(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){return null}}
function card(l,v){return '<div class="card"><div class="l">'+esc(l)+'</div><div class="v">'+v+'</div></div>'}
function detail(r,parts){
  var h='<div class="chk">'+r.checks.map(function(c){return '<div class="'+(c.ok?"ok":"no")+'"><b>'+esc(c.label)+'</b> - '+esc(c.detail)+'</div>'}).join("")+'</div>';
  if(r.parts){h+='<div class="sub" style="margin-top:6px">Score '+n(r.score,1)+' out of 100 (the scanner picks the highest eligible score):</div><div class="parts">'+
    r.parts.map(function(p){return '<span>'+esc(p.label)+' ('+Math.round(p.weight*100)+'%)</span><div class="bar"><i style="width:'+p.value+'%"></i></div><span>'+n(p.value,1)+' &rarr; '+n(p.points,1)+' pts</span>'}).join("")+'</div>'}
  if(r.order_price&&r.lots)h+='<div class="sub" style="margin-top:6px">If bought: limit order '+inr(r.order_price)+' x '+r.lots+' lot(s); premium per lot '+inr(r.premium_per_lot)+'.</div>';
  return h}
function render(d){
  S.last=d;var o=document.getElementById("out");
  if(!d.ok){o.innerHTML='<div class="nopick">'+esc(d.error||"No data")+'</div>';return}
  var sel=document.getElementById("exp");sel.innerHTML=d.expiries.map(function(e){return '<option value="'+e+'"'+(e===d.expiry?" selected":"")+'>'+e+(e===d.scanner_expiry?" (scanner uses this)":"")+'</option>'}).join("");
  document.getElementById("meta").textContent=fmtTs(d.captured_at);
  var h='<div class="cards">'+card("Stock",esc(d.symbol))+card("Stock price",inr(d.spot))+card("ATM strike",n(d.atm,2))+card("Expiry","in "+d.days_to_expiry+" days")+card("Eligible strikes",d.eligible)+card("Rejected",d.rejected)+'</div>';
  if(d.chosen){var c=d.chosen;h+='<div class="pick"><h3>The scanner would buy: '+esc(c.trading_symbol||(d.symbol+" "+n(c.strike,2)+" "+d.side))+'</h3><div class="g">'+
    '<div><span>Strike</span>'+n(c.strike,2)+'</div><div><span>Limit price</span>'+inr(c.limit_price)+'</div><div><span>Quantity</span>'+c.quantity+' ('+c.lots+' lot x '+c.lot_size+')</div>'+
    '<div><span>Premium</span>'+inr(c.total_premium)+'</div><div><span>Stop</span>'+inr(c.stop_loss)+'</div><div><span>Targets</span>'+inr(c.target1)+' / '+inr(c.target2)+' / '+inr(c.target3)+'</div>'+
    '<div><span>Risk</span>'+inr(c.total_risk)+'</div><div><span>Score</span>'+n(c.score,1)+'</div></div></div>'}
  else h+='<div class="nopick"><b>No strike passes.</b> '+esc(d.no_choice_reason||"")+'</div>';
  h+='<div style="overflow-x:auto"><table><thead><tr><th class="l">Status</th><th>Rank</th><th>Strike</th><th>Premium</th><th>Bid / Ask</th><th>Spread</th><th>Open interest</th><th>Volume</th><th>IV</th><th>Prem % of stock</th><th>Score</th><th class="l">Why</th></tr></thead><tbody>';
  var hidden=0;
  d.rows.forEach(function(r,i){
    if(!S.far&&r.status==="REJECTED"&&r.from_spot_pct!=null&&r.from_spot_pct>6){hidden++;return}
    h+='<tr class="row '+r.status+'" data-i="'+i+'"><td class="l"><span class="tag '+r.status+'">'+r.status+'</span></td><td>'+(r.rank||"")+'</td><td class="'+(r.itm?"itm":"otm")+'">'+n(r.strike,2)+(r.strike===d.atm?" &#9733;":"")+'</td><td>'+inr(r.ltp)+'</td><td>'+n(r.bid,2)+' / '+n(r.ask,2)+'</td><td>'+(r.spread_pct==null?"-":n(r.spread_pct,2)+"%")+'</td><td>'+n(r.oi)+'</td><td>'+n(r.volume)+'</td><td>'+n(r.iv,1)+'</td><td>'+(r.premium_pct_of_stock==null?"-":n(r.premium_pct_of_stock,2)+"%")+'</td><td>'+(r.score==null?"-":n(r.score,1))+'</td><td class="why">'+esc(r.why)+'</td></tr>'+
      '<tr class="det" id="d'+i+'" style="display:none"><td colspan="12">'+detail(r)+'</td></tr>'});
  h+='</tbody></table></div>';
  if(hidden)h+='<div class="sub" style="margin-top:6px">'+hidden+' rejected strikes more than 6% from the stock price are hidden (press "Show far strikes").</div>';
  h+='<div class="sub" style="margin-top:6px">Green strikes are in the money for this side, grey are out of the money; a star marks the at-the-money strike. Premium % of stock is the option price divided by the stock price - the study of 250 trades found the cheaper ones (about 2.3% or less) lost far less.</div>';
  h+='<div class="panel"><h3>What the scanner looks for <span class="sub">(the live settings)</span></h3><div class="cfg">'+d.config.map(function(c){return '<div><span>'+esc(c.label)+':</span> '+esc(c.value)+'</div>'}).join("")+'</div>'+
     '<div class="sub" style="margin-top:8px"><b>Score</b> = '+d.score_parts.map(function(p){return Math.round(p.weight*100)+'% '+esc(p.label.toLowerCase())}).join(" + ")+'. Closeness and spread are 100 at the best value and fall to 0 at the limit; open interest and volume reach 100 at 2.5 times the minimum. A strike that fails any check is never bought, whatever its score.</div></div>';
  o.innerHTML=h;
  [].slice.call(o.querySelectorAll("tr.row")).forEach(function(tr){tr.onclick=function(){var x=document.getElementById("d"+tr.getAttribute("data-i"));x.style.display=x.style.display==="none"?"table-row":"none"}})}
function load(){var s=document.getElementById("sym").value.trim().toUpperCase();if(!s)return;ls("cl_sym",s);
  document.getElementById("out").innerHTML='<div class="sub">loading '+esc(s)+' ...</div>';
  fetch("/api/contract-lab?symbol="+encodeURIComponent(s)+"&side="+S.side+"&expiry="+encodeURIComponent(document.getElementById("exp").value||""),{cache:"no-store"}).then(function(r){return r.json()}).then(render).catch(function(){document.getElementById("out").innerHTML='<div class="nopick">Connection lost.</div>'})}
function side(v){S.side=v;document.getElementById("bce").className=v==="CE"?"on":"";document.getElementById("bpe").className=v==="PE"?"on":"";document.getElementById("exp").innerHTML="";load()}
document.getElementById("bce").onclick=function(){side("CE")};document.getElementById("bpe").onclick=function(){side("PE")};
document.getElementById("go").onclick=load;document.getElementById("exp").onchange=load;
document.getElementById("far").onclick=function(){S.far=!S.far;this.className=S.far?"on":"";this.textContent=S.far?"Hide far strikes":"Show far strikes";if(S.last)render(S.last)};
document.getElementById("sym").onkeydown=function(e){if(e.key==="Enter"){document.getElementById("exp").innerHTML="";load()}};
document.getElementById("auto").onchange=function(){clearInterval(S.timer);if(this.checked)S.timer=setInterval(load,30000)};
fetch("/api/contract-lab-symbols",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){document.getElementById("syms").innerHTML=(d.symbols||[]).map(function(s){return '<option value="'+s+'">'}).join("")}).catch(function(){});
var q=new URLSearchParams(location.search);var s0=(q.get("symbol")||ls("cl_sym")||"").toUpperCase();if((q.get("side")||"").toUpperCase()==="PE"){S.side="PE";document.getElementById("bce").className="";document.getElementById("bpe").className="on"}
if(s0){document.getElementById("sym").value=s0;load()}
</script></body></html>"""
