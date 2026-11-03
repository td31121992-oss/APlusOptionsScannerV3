"""Strategy Builder: combine option legs (buy / sell, call / put, any strike of the live chain) and see the whole position. READ-ONLY analysis - it places nothing and touches no trade.

    /strategy-builder?symbol=SBIN&expiry=2026-11-23&legs=B:CE:950:1,S:CE:1000:1     the page (legs are  B|S : CE|PE : strike : lots )
    /api/strategy-chain?symbol=SBIN&expiry=...                                        the chain (both sides), the lot size and ready-made templates
    /api/strategy-eval?symbol=SBIN&expiry=...&legs=...&fill=worst&move=0&days=0&iv=0  payoff curves, max profit / loss, breakevens, chance of profit, net Greeks

Prices: the chain comes from contract_lab.analyse (live Upstox chain). A leg is entered at the worst side of the book (buy at the ask, sell at the bid) unless fill=mid / last. Each leg's
model volatility is solved from its own mid price (greeks.py, Black-Scholes, 7% rate), so the "today" curve passes through the position's mark value; the gap between that and what
you paid is the spread cost. The expiry curve is exact (intrinsic values). The what-if curve re-prices every leg after `days` calendar days with the IV moved by `iv` points.
Not included: brokerage and taxes, and margin (selling options needs margin; it is not calculated here).
"""

from __future__ import annotations

import math
from typing import Any

import contract_lab
import greeks as gk

MAX_LEGS = 8
MAX_LOTS = 50
FILLS = ("worst", "mid", "last")


def _num(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def parse_legs(text: str) -> list[dict[str, Any]]:
    """'B:CE:950:1,S:CE:1000:1' -> [{'side': 1, 'opt': 'CE', 'strike': 950.0, 'lots': 1}, ...]; raises ValueError with a readable message."""
    legs = []
    for part in [p for p in str(text or "").replace(";", ",").split(",") if p.strip()]:
        bits = part.strip().split(":")
        if len(bits) < 3:
            raise ValueError(f"Leg '{part}' should look like B:CE:950:1 (buy/sell, CE/PE, strike, lots).")
        side = {"B": 1, "BUY": 1, "S": -1, "SELL": -1}.get(bits[0].strip().upper())
        opt = {"CE": "CE", "C": "CE", "CALL": "CE", "PE": "PE", "P": "PE", "PUT": "PE"}.get(bits[1].strip().upper())
        strike = _num(bits[2], -1)
        lots = int(_num(bits[3], 1)) if len(bits) > 3 else 1
        if side is None or opt is None or strike <= 0:
            raise ValueError(f"Leg '{part}' is not valid (use B or S, CE or PE, and a strike).")
        legs.append({"side": side, "opt": opt, "strike": strike, "lots": max(1, min(MAX_LOTS, lots))})
    if len(legs) > MAX_LEGS:
        raise ValueError(f"At most {MAX_LEGS} legs.")
    return legs


def _both_sides(symbol: str, expiry: str) -> tuple[dict[str, Any], dict[str, Any]]:
    ce, pe = contract_lab.analyse(symbol, "CE", expiry), contract_lab.analyse(symbol, "PE", expiry)
    for d in (ce, pe):
        if not d.get("ok"):
            raise ValueError(d.get("error") or "No chain data.")
    return ce, pe


def _leg_quote(row: dict[str, Any] | None) -> dict[str, float]:
    r = row or {}
    return {"ltp": _num(r.get("ltp")), "bid": _num(r.get("bid")), "ask": _num(r.get("ask")), "iv": _num(r.get("iv")), "oi": int(_num(r.get("oi"))), "volume": int(_num(r.get("volume"))),
            "spread_pct": r.get("spread_pct")}


def chain(symbol: str, expiry: str = "") -> dict[str, Any]:
    """Both sides of the chain by strike, plus the lot size and ready-made strategy templates."""
    try:
        ce, pe = _both_sides(symbol, expiry)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    by: dict[float, dict[str, Any]] = {}
    lot = 0
    for side, d in (("ce", ce), ("pe", pe)):
        for r in d["rows"]:
            if r["strike"]:
                by.setdefault(float(r["strike"]), {"strike": float(r["strike"])})[side] = _leg_quote(r)
                lot = lot or int(_num(r.get("lot_size")))
    strikes = sorted(by)
    spot = _num(ce["spot"])
    return {"ok": True, "symbol": ce["symbol"], "expiry": ce["expiry"], "expiries": ce["expiries"], "scanner_expiry": ce.get("scanner_expiry", ""), "days_to_expiry": ce["days_to_expiry"],
            "spot": spot, "atm": ce["atm"], "lot_size": lot, "captured_at": ce.get("captured_at", ""), "strikes": [by[k] for k in strikes], "templates": templates(strikes, spot)}


def templates(strikes: list[float], spot: float) -> list[dict[str, Any]]:
    """Common strategies placed around the at-the-money strike (strike steps are taken from the chain itself)."""
    if len(strikes) < 7:
        return []
    atm_i = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))

    def k(step: int) -> float:
        return strikes[max(0, min(len(strikes) - 1, atm_i + step))]

    def L(side: str, opt: str, step: int, lots: int = 1) -> str:
        return f"{side}:{opt}:{k(step):g}:{lots}"
    rows = [
        ("Long call", "Bullish: pays if the stock rises. Risk is the premium.", [L("B", "CE", 0)]),
        ("Long put", "Bearish: pays if the stock falls. Risk is the premium.", [L("B", "PE", 0)]),
        ("Bull call spread", "Mildly bullish: cheaper than a call, profit capped.", [L("B", "CE", 0), L("S", "CE", 2)]),
        ("Bear put spread", "Mildly bearish: cheaper than a put, profit capped.", [L("B", "PE", 0), L("S", "PE", -2)]),
        ("Long straddle", "Big move either way: buy the call and the put at the money.", [L("B", "CE", 0), L("B", "PE", 0)]),
        ("Long strangle", "Big move either way, cheaper: buy an out-of-the-money call and put.", [L("B", "CE", 1), L("B", "PE", -1)]),
        ("Short straddle", "Little movement: sell the call and put at the money. Unlimited risk, needs margin.", [L("S", "CE", 0), L("S", "PE", 0)]),
        ("Iron condor", "Range-bound: sell a call and a put, buy wings for protection. Risk is capped.", [L("S", "PE", -1), L("B", "PE", -3), L("S", "CE", 1), L("B", "CE", 3)]),
        ("Call butterfly", "Pin near one strike: small cost, small capped profit at the middle strike.", [L("B", "CE", -1), L("S", "CE", 0, 2), L("B", "CE", 1)]),
    ]
    return [{"name": n, "note": note, "legs": ",".join(legs)} for n, note, legs in rows]


# model -------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _intrinsic(opt: str, s: float, k: float) -> float:
    return max(0.0, s - k) if opt == "CE" else max(0.0, k - s)


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _expiry_payoff(legs: list[dict[str, Any]], s: float) -> float:
    """Profit / loss in rupees at expiry if the stock is at s (exact)."""
    return sum(L["sgn_qty"] * (_intrinsic(L["opt"], s, L["strike"]) - L["entry"]) for L in legs)


def _roots(points: list[tuple[float, float]], tail_slope: float) -> list[float]:
    out = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if y0 == 0:
            out.append(x0)
        elif y0 * y1 < 0:
            out.append(x0 + (0 - y0) * (x1 - x0) / (y1 - y0))
    x, y = points[-1]
    if y == 0 and (not out or out[-1] != x):
        out.append(x)
    elif tail_slope != 0 and y * tail_slope < 0:
        out.append(x - y / tail_slope)
    return sorted({round(v, 2) for v in out if v > 0})


def evaluate(symbol: str, expiry: str, legs_text: str, fill: str = "worst", move: Any = 0, days: Any = 0, iv: Any = 0) -> dict[str, Any]:
    """The whole position: entry cost, payoff curves, max profit / loss, breakevens, chance of profit, net Greeks and the what-if."""
    try:
        legs_in = parse_legs(legs_text)
        if not legs_in:
            return {"ok": False, "error": "Add at least one leg."}
        ce, pe = _both_sides(symbol, expiry)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    fill = fill if fill in FILLS else "worst"
    spot, dte, exp = _num(ce["spot"]), int(ce["days_to_expiry"]), ce["expiry"]
    rows = {"CE": {float(r["strike"]): r for r in ce["rows"] if r["strike"]}, "PE": {float(r["strike"]): r for r in pe["rows"] if r["strike"]}}
    lot = next((int(_num(r.get("lot_size"))) for d in (ce, pe) for r in d["rows"] if _num(r.get("lot_size")) > 0), 0)
    if lot <= 0:
        return {"ok": False, "error": "Lot size is not known for this stock."}
    t0 = max(0.5, dte + 0.5) / 365.0
    mv, dy, ivs = max(-30.0, min(30.0, _num(move))), max(0.0, min(dte + 0.5, _num(days))), max(-30.0, min(30.0, _num(iv)))
    legs: list[dict[str, Any]] = []
    warnings: list[str] = []
    for L in legs_in:
        r = rows[L["opt"]].get(L["strike"])
        if r is None:
            return {"ok": False, "error": f"No {L['opt']} {L['strike']:g} in this chain."}
        bid, ask, ltp = _num(r["bid"]), _num(r["ask"]), _num(r["ltp"])
        mid = (bid + ask) / 2.0 if (bid > 0 and ask >= bid) else ltp
        buy = L["side"] > 0
        entry = {"worst": (ask if buy else bid) or ltp, "mid": mid, "last": ltp}[fill]
        if entry <= 0 or mid <= 0:
            return {"ok": False, "error": f"{L['opt']} {L['strike']:g} has no usable price right now."}
        call = L["opt"] == "CE"
        v0 = gk.implied_vol(mid, spot, L["strike"], t0, call) or (_num(r["iv"]) / 100.0 or None)
        if not v0:
            return {"ok": False, "error": f"{L['opt']} {L['strike']:g} cannot be modelled (price below intrinsic value and no IV)."}
        g = gk.greeks_at_entry(spot, L["strike"], exp, L["opt"], mid, feed_iv_pct=_num(r["iv"])) or {}
        qty = L["lots"] * lot
        sq = L["side"] * qty
        spread = (ask - bid) if (bid > 0 and ask >= bid) else None
        if spread is None or (ask > 0 and spread / ask * 100.0 > 2.0):
            warnings.append(f"{L['opt']} {L['strike']:g}: bid-ask spread {('%.1f%% of the ask' % (spread / ask * 100.0)) if spread is not None and ask else 'unknown'} - the scanner's own limit is 2%. Fills will be worse than shown.")
        if int(_num(r["oi"])) < 5000:
            warnings.append(f"{L['opt']} {L['strike']:g}: open interest {int(_num(r['oi'])):,} is thin.")
        legs.append({**L, "qty": qty, "sgn_qty": sq, "entry": entry, "mark": mid, "iv": v0, "model_t0": t0, "spread": spread,
                     "label": f"{'Buy' if buy else 'Sell'} {L['lots']} x {L['opt']} {L['strike']:g}", "delta": g.get("gk_delta"), "gamma": g.get("gk_gamma"),
                     "theta_day": g.get("gk_theta_day"), "vega": g.get("gk_vega_1pt")})

    cash = sum(L["sgn_qty"] * L["entry"] for L in legs)                      # + = you pay (debit), - = you receive (credit)
    strikes = sorted({L["strike"] for L in legs})
    pts = [(0.0, _expiry_payoff(legs, 0.0))] + [(k, _expiry_payoff(legs, k)) for k in strikes]
    net_ce = sum(L["sgn_qty"] for L in legs if L["opt"] == "CE")              # slope of the payoff above the highest strike
    vals = [y for _, y in pts]
    up_unlimited_profit, up_unlimited_loss = net_ce > 0, net_ce < 0
    max_profit = None if up_unlimited_profit else max(vals)
    max_loss = None if up_unlimited_loss else min(vals)
    be = _roots(pts, float(net_ce))
    sigma = sum(L["iv"] for L in legs) / len(legs)

    lo, hi = min(spot * 0.85, strikes[0] * 0.95), max(spot * 1.15, strikes[-1] * 1.05)
    n = 81
    grid = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
    vol_shift = ivs / 100.0

    def scen(s: float, k: float, shift: float) -> float:
        tot = 0.0
        for L in legs:
            p = gk.bs_price(s, L["strike"], max(0.0, t0 - k / 365.0), max(0.01, L["iv"] + shift), L["opt"] == "CE")
            tot += L["sgn_qty"] * (p - L["entry"])
        return tot
    curve_exp = [round(_expiry_payoff(legs, s), 0) for s in grid]
    curve_now = [round(scen(s, 0.0, 0.0), 0) for s in grid]
    curve_scn = [round(scen(s, dy, vol_shift), 0) for s in grid]
    pnl_here = scen(spot * (1.0 + mv / 100.0), dy, vol_shift)

    # chance of profit at expiry: stock ~ lognormal with the position's average implied volatility, drift = risk-free rate
    sig_t = sigma * math.sqrt(t0)
    mu = (gk.RATE - 0.5 * sigma * sigma) * t0
    def cdf_s(x: float) -> float:
        return 1.0 if x == math.inf else (0.0 if x <= 0 else _cdf((math.log(x / spot) - mu) / sig_t))
    cuts = [0.0] + be + [math.inf]
    pop = 0.0
    for a, b in zip(cuts, cuts[1:]):
        rep = max(a * 1.25, strikes[-1] * 1.5, spot * 1.5) if b == math.inf else ((a + b) / 2.0 if a > 0 else (b / 2.0))
        if _expiry_payoff(legs, rep) > 0:
            pop += cdf_s(b) - cdf_s(a)
    greeks_net = {k: round(sum(L["sgn_qty"] * (L[src] or 0.0) for L in legs), 3) for k, src in (("delta", "delta"), ("gamma", "gamma"), ("theta_day", "theta_day"), ("vega_per_iv_pt", "vega"))}
    spread_cost = sum(abs(L["qty"]) * (L["spread"] / 2.0) for L in legs if L["spread"] is not None)
    mark_now = sum(L["sgn_qty"] * (L["mark"] - L["entry"]) for L in legs)
    shorts = [L for L in legs if L["side"] < 0]
    if shorts:
        warnings.append("Selling options needs margin and can lose more than the premium received; margin is not calculated here.")
    if up_unlimited_loss:
        warnings.append("Loss is unlimited if the stock rises sharply (more calls sold than bought).")
    return {"ok": True, "symbol": ce["symbol"], "expiry": exp, "days_to_expiry": dte, "spot": spot, "lot_size": lot, "fill": fill,
            "legs": [{"label": L["label"], "side": "B" if L["side"] > 0 else "S", "opt": L["opt"], "strike": L["strike"], "lots": L["lots"], "qty": L["qty"], "entry": round(L["entry"], 2),
                      "mark": round(L["mark"], 2), "iv": round(L["iv"] * 100.0, 1), "delta": L["delta"], "theta_day": L["theta_day"]} for L in legs],
            "net": {"cash": round(cash, 0), "kind": "debit (you pay)" if cash > 0 else "credit (you receive)", "max_profit": None if max_profit is None else round(max_profit, 0),
                    "max_loss": None if max_loss is None else round(max_loss, 0), "max_profit_unlimited": up_unlimited_profit, "max_loss_unlimited": up_unlimited_loss,
                    "breakevens": be, "breakeven_pct": [round((b / spot - 1.0) * 100.0, 2) for b in be], "pop_pct": round(pop * 100.0, 1), "spread_cost": round(spread_cost, 0),
                    "mark_pnl_now": round(mark_now, 0), "greeks": greeks_net, "avg_iv": round(sigma * 100.0, 1)},
            "curves": {"spots": [round(s, 2) for s in grid], "expiry": curve_exp, "today": curve_now, "scenario": curve_scn},
            "scenario": {"move": mv, "days": dy, "iv": ivs, "spot": round(spot * (1.0 + mv / 100.0), 2), "pnl": round(pnl_here, 0)}, "warnings": warnings}


STRATEGY_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Strategy Builder</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--blue:#4c8dff;--green:#27c281;--red:#ff6b6b;--amber:#f5b942}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:13px/1.4 -apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--blue);text-decoration:none;font-weight:700}
.top{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--line);background:var(--panel)}
button,input,select{background:#0e1527;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:6px 9px;font:inherit}button{cursor:pointer;font-weight:700}button.on{background:var(--blue);border-color:var(--blue)}
#sym{width:140px;text-transform:uppercase;font-weight:800}.wrap{padding:10px 12px;max-width:1500px;margin:0 auto}.sub{color:var(--muted);font-size:12px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:8px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 12px}
.card .l{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.4px}.card .v{font-size:18px;font-weight:800;margin-top:2px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-top:10px}.panel h3{margin:0 0 6px;font-size:13px}
.tpl{display:flex;flex-wrap:wrap;gap:6px}.tpl button{font-weight:600;font-size:12px}
table{width:100%;border-collapse:collapse}th,td{padding:5px 8px;text-align:right;border-bottom:1px solid #1b2640;white-space:nowrap}th{color:var(--muted);font-size:11px;text-transform:uppercase;background:#0f1729}td.l,th.l{text-align:left}
.ctl{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px 22px;margin:6px 0}.ctl label{display:block;color:var(--muted);font-size:11px;text-transform:uppercase}.ctl b{color:var(--text);font-size:14px}.ctl input[type=range]{width:100%;padding:0}
.up{color:var(--green)}.dn{color:var(--red)}.nopick{background:#2a1414;border:1px solid #6b2a2a;border-radius:10px;padding:10px 14px;margin:8px 0}.warn{background:#2a2310;border:1px solid #6b5a1f;border-radius:10px;padding:8px 12px;margin:6px 0;font-size:12px}
.chart{width:100%;max-width:900px;background:#0e1527;border:1px solid var(--line);border-radius:8px}select.mini,input.mini{padding:3px 6px;font-size:12px}input.lots{width:56px}
</style></head><body>
<div class="top"><a href="/">&larr; Dashboard</a><b>Strategy Builder</b><input id="sym" list="syms" placeholder="stock"><datalist id="syms"></datalist><select id="exp"></select>
<label class="sub">fill at <select id="fill"><option value="worst">worst side (buy ask / sell bid)</option><option value="mid">mid</option><option value="last">last price</option></select></label>
<button id="go">Refresh prices</button><span class="sub" id="meta"></span></div>
<div class="wrap">
<div class="sub" style="margin-bottom:6px">Combine legs and see the whole position: payoff at expiry and today, max profit / loss, breakevens, chance of profit, net Greeks. Model numbers (Black-Scholes, IV from each leg's own price); no brokerage or margin. Analysis only - it places nothing.</div>
<div id="out"><div class="sub">Pick a stock and press Enter.</div></div></div>
<script>
var S={chain:null,legs:[],move:0,days:0,iv:0,t:null};
function fmtTs(s){if(!s)return"";try{var d=new Date(s);if(isNaN(d))return String(s).replace("T"," ").slice(0,19);return d.toLocaleString("en-GB",{timeZone:"Asia/Kolkata",hour12:false}).replace(",","")+" IST"}catch(e){return String(s).slice(0,19)}}
function esc(t){return String(t==null?"":t).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function n(v,d){return v==null||v===""?"-":Number(v).toLocaleString("en-IN",{minimumFractionDigits:d||0,maximumFractionDigits:d||0})}
function sg(v,d){return v==null?"-":(v>0?"+":"")+n(v,d)}function inr(v){return v==null?"-":(v<0?"-":"")+"₹"+n(Math.abs(v),0)}
function cl(v){return v>0?"up":v<0?"dn":""}function ls(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){return null}}
function legsText(){return S.legs.map(function(l){return l.side+":"+l.opt+":"+l.strike+":"+l.lots}).join(",")}
function sym(){return document.getElementById("sym").value.trim().toUpperCase()}
function loadChain(keepLegs){var s=sym();if(!s)return;ls("sb_sym",s);document.getElementById("out").innerHTML='<div class="sub">loading '+esc(s)+' ...</div>';
  fetch("/api/strategy-chain?symbol="+encodeURIComponent(s)+"&expiry="+encodeURIComponent(document.getElementById("exp").value||""),{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){
    if(!d.ok){document.getElementById("out").innerHTML='<div class="nopick">'+esc(d.error)+'</div>';return}
    S.chain=d;var sel=document.getElementById("exp");sel.innerHTML=d.expiries.map(function(e){return '<option value="'+e+'"'+(e===d.expiry?" selected":"")+'>'+e+(e===d.scanner_expiry?" (scanner uses this)":"")+'</option>'}).join("");
    document.getElementById("meta").textContent=fmtTs(d.captured_at);
    if(!keepLegs||!S.legs.length){var t=d.templates[0];S.legs=t?parse(t.legs):[]}S.move=0;S.days=0;S.iv=0;shell()}).catch(function(){document.getElementById("out").innerHTML='<div class="nopick">Connection lost.</div>'})}
function parse(t){return t.split(",").filter(Boolean).map(function(p){var b=p.split(":");return{side:b[0],opt:b[1],strike:parseFloat(b[2]),lots:parseInt(b[3]||"1",10)}})}
function shell(){var d=S.chain;var h='<div class="cards"><div class="card"><div class="l">Stock</div><div class="v">'+esc(d.symbol)+'</div></div><div class="card"><div class="l">Stock price</div><div class="v">'+inr(d.spot).replace("₹","₹")+'</div></div><div class="card"><div class="l">Expiry</div><div class="v">in '+d.days_to_expiry+' days</div></div><div class="card"><div class="l">Lot size</div><div class="v">'+d.lot_size+'</div></div></div>';
  h+='<div class="panel"><h3>Start from a template</h3><div class="tpl">'+d.templates.map(function(t,i){return '<button data-t="'+i+'" title="'+esc(t.note)+'">'+esc(t.name)+'</button>'}).join("")+'</div></div>';
  h+='<div class="panel"><h3>Legs</h3><div id="legs"></div><button id="add">+ Add leg</button></div><div id="res"></div>';
  document.getElementById("out").innerHTML=h;
  [].slice.call(document.querySelectorAll(".tpl button")).forEach(function(b){b.onclick=function(){S.legs=parse(d.templates[+b.getAttribute("data-t")].legs);S.move=0;S.days=0;S.iv=0;drawLegs();run()}});
  document.getElementById("add").onclick=function(){if(S.legs.length>=8)return;var k=d.strikes.reduce(function(b,x){return Math.abs(x.strike-d.spot)<Math.abs(b-d.spot)?x.strike:b},d.strikes[0].strike);S.legs.push({side:"B",opt:"CE",strike:k,lots:1});drawLegs();run()};
  drawLegs();run()}
function drawLegs(){var d=S.chain;var opts=d.strikes.map(function(x){return x.strike});
  var h='<table><thead><tr><th class="l">Buy / Sell</th><th class="l">Type</th><th>Strike</th><th>Lots</th><th></th></tr></thead><tbody>';
  S.legs.forEach(function(l,i){h+='<tr><td class="l"><select class="mini" data-i="'+i+'" data-f="side"><option value="B"'+(l.side==="B"?" selected":"")+'>Buy</option><option value="S"'+(l.side==="S"?" selected":"")+'>Sell</option></select></td>'+
    '<td class="l"><select class="mini" data-i="'+i+'" data-f="opt"><option value="CE"'+(l.opt==="CE"?" selected":"")+'>Call</option><option value="PE"'+(l.opt==="PE"?" selected":"")+'>Put</option></select></td>'+
    '<td><select class="mini" data-i="'+i+'" data-f="strike">'+opts.map(function(k){return '<option value="'+k+'"'+(k===l.strike?" selected":"")+'>'+n(k,2)+'</option>'}).join("")+'</select></td>'+
    '<td><input class="mini lots" type="number" min="1" max="50" value="'+l.lots+'" data-i="'+i+'" data-f="lots"></td><td><button data-rm="'+i+'">remove</button></td></tr>'});
  document.getElementById("legs").innerHTML=h+'</tbody></table>';
  [].slice.call(document.querySelectorAll("#legs [data-f]")).forEach(function(e){e.onchange=function(){var l=S.legs[+e.getAttribute("data-i")],f=e.getAttribute("data-f");l[f]=f==="strike"?parseFloat(e.value):f==="lots"?Math.max(1,Math.min(50,parseInt(e.value||"1",10))):e.value;run()}});
  [].slice.call(document.querySelectorAll("#legs [data-rm]")).forEach(function(b){b.onclick=function(){S.legs.splice(+b.getAttribute("data-rm"),1);drawLegs();run()}})}
function run(){var d=S.chain,el=document.getElementById("res");if(!S.legs.length){el.innerHTML='<div class="nopick">Add at least one leg.</div>';return}
  var u="/api/strategy-eval?symbol="+encodeURIComponent(d.symbol)+"&expiry="+d.expiry+"&legs="+encodeURIComponent(legsText())+"&fill="+document.getElementById("fill").value+"&move="+S.move+"&days="+S.days+"&iv="+S.iv;history.replaceState(null,"","?symbol="+d.symbol+"&expiry="+d.expiry+"&legs="+encodeURIComponent(legsText()));
  fetch(u,{cache:"no-store"}).then(function(r){return r.json()}).then(function(w){if(!w.ok){el.innerHTML='<div class="nopick">'+esc(w.error)+'</div>';return}show(w)}).catch(function(){el.innerHTML='<div class="nopick">Connection lost.</div>'})}
function show(w){var el=document.getElementById("res"),nt=w.net,g=nt.greeks;
  var mp=nt.max_profit_unlimited?"Unlimited":inr(nt.max_profit),ml=nt.max_loss_unlimited?"Unlimited":inr(nt.max_loss);
  var h='<div class="cards"><div class="card"><div class="l">'+esc(nt.kind)+'</div><div class="v">'+inr(Math.abs(nt.cash))+'</div></div><div class="card"><div class="l">Max profit</div><div class="v up">'+mp+'</div></div><div class="card"><div class="l">Max loss</div><div class="v dn">'+ml+'</div></div>'+
   '<div class="card"><div class="l">Breakeven at expiry</div><div class="v">'+(nt.breakevens.length?nt.breakevens.map(function(b,i){return n(b,2)+' <span class="sub">('+sg(nt.breakeven_pct[i],1)+'%)</span>'}).join(" &middot; "):"none")+'</div></div>'+
   '<div class="card"><div class="l">Chance of profit at expiry</div><div class="v">'+n(nt.pop_pct,0)+'%</div></div><div class="card"><div class="l">Spread cost if you exit now</div><div class="v dn">'+inr(-nt.spread_cost)+'</div></div></div>';
  h+=w.warnings.map(function(x){return '<div class="warn">'+esc(x)+'</div>'}).join("");
  h+='<div class="panel"><h3>Profit / loss by stock price</h3>'+chart(w)+'<div class="sub">Grey = at expiry (exact). Blue = the what-if below (today when days = 0). Dashed = today\'s price. Gain on the position, rupees, for the lots shown.</div></div>';
  h+='<div class="panel"><h3>What if ...</h3><div class="ctl"><div><label>Stock moves <b>'+sg(S.move,1)+'%</b> (to '+n(w.scenario.spot,2)+')</label><input id="rm" type="range" min="-15" max="15" step="0.5" value="'+S.move+'"></div>'+
   '<div><label>Days pass <b>'+n(S.days,1)+'</b> of '+w.days_to_expiry+'</label><input id="rd" type="range" min="0" max="'+(w.days_to_expiry+0.5)+'" step="0.5" value="'+S.days+'"></div>'+
   '<div><label>IV changes <b>'+sg(S.iv,1)+' points</b> (average now '+n(nt.avg_iv,1)+')</label><input id="ri" type="range" min="-15" max="15" step="0.5" value="'+S.iv+'"></div></div>'+
   '<div class="cards"><div class="card"><div class="l">Position then</div><div class="v '+cl(w.scenario.pnl)+'">'+(w.scenario.pnl>0?"+":"")+inr(w.scenario.pnl)+'</div></div><div class="card"><div class="l">Gain / loss marked now (spread paid)</div><div class="v '+cl(nt.mark_pnl_now)+'">'+(nt.mark_pnl_now>0?"+":"")+inr(nt.mark_pnl_now)+'</div></div></div></div>';
  h+='<div class="panel"><h3>Legs and net Greeks</h3><div style="overflow-x:auto"><table><thead><tr><th class="l">Leg</th><th>Quantity</th><th>Entry</th><th>Mark</th><th>IV %</th><th>Delta</th><th>Theta / day</th></tr></thead><tbody>'+
   w.legs.map(function(l){return '<tr><td class="l">'+esc(l.label)+'</td><td>'+n(l.qty)+'</td><td>'+n(l.entry,2)+'</td><td>'+n(l.mark,2)+'</td><td>'+n(l.iv,1)+'</td><td>'+n(l.delta,3)+'</td><td>'+n(l.theta_day,2)+'</td></tr>'}).join("")+
   '</tbody></table></div><div class="cards"><div class="card"><div class="l">Net delta (rupees per Rs 1 move)</div><div class="v">'+sg(g.delta,1)+'</div></div><div class="card"><div class="l">Net gamma</div><div class="v">'+sg(g.gamma,2)+'</div></div><div class="card"><div class="l">Net theta (rupees / day)</div><div class="v '+cl(g.theta_day)+'">'+sg(g.theta_day,0)+'</div></div><div class="card"><div class="l">Net vega (rupees per IV point)</div><div class="v">'+sg(g.vega_per_iv_pt,0)+'</div></div></div></div>';
  el.innerHTML=h;
  [["rm","move"],["rd","days"],["ri","iv"]].forEach(function(p){document.getElementById(p[0]).oninput=function(){S[p[1]]=parseFloat(this.value);clearTimeout(S.t);S.t=setTimeout(run,140)}})}
function chart(w){var c=w.curves,W=900,H=300,L=64,R=14,T=14,B=26,xs=c.spots,all=c.expiry.concat(c.scenario),lo=Math.min.apply(null,all.concat([0])),hi=Math.max.apply(null,all.concat([0]));if(hi===lo){hi=lo+1}
  var pad=(hi-lo)*.08;lo-=pad;hi+=pad;function X(v){return L+(W-L-R)*(v-xs[0])/(xs[xs.length-1]-xs[0])}function Y(v){return T+(H-T-B)*(1-(v-lo)/(hi-lo))}
  var s='<svg class="chart" viewBox="0 0 '+W+' '+H+'" xmlns="http://www.w3.org/2000/svg">';
  for(var i=0;i<=4;i++){var v=lo+(hi-lo)*i/4;s+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+Y(v)+'" y2="'+Y(v)+'" stroke="#1b2640"/><text x="4" y="'+(Y(v)+4)+'" fill="#8ea0bd" font-size="10">'+n(v,0)+'</text>'}
  s+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+Y(0)+'" y2="'+Y(0)+'" stroke="#3a4a6e" stroke-dasharray="4 3"/><line x1="'+X(w.spot)+'" x2="'+X(w.spot)+'" y1="'+T+'" y2="'+(H-B)+'" stroke="#f5b942" stroke-dasharray="3 3"/>';
  s+='<text x="'+(X(w.spot)+4)+'" y="'+(T+10)+'" fill="#f5b942" font-size="10">now '+n(w.spot,1)+'</text>';
  function line(arr,color,wd){return '<polyline fill="none" stroke="'+color+'" stroke-width="'+wd+'" points="'+arr.map(function(v,i){return X(xs[i])+","+Y(v)}).join(" ")+'"/>'}
  s+=line(c.expiry,"#8ea0bd",2)+line(c.scenario,"#4c8dff",2.4);
  w.net.breakevens.forEach(function(b){if(b>=xs[0]&&b<=xs[xs.length-1])s+='<circle cx="'+X(b)+'" cy="'+Y(0)+'" r="4" fill="#27c281"/>'});
  [0,2,4,6,8].forEach(function(i){var k=Math.round(i*(xs.length-1)/8);s+='<text x="'+X(xs[k])+'" y="'+(H-8)+'" fill="#8ea0bd" font-size="10" text-anchor="middle">'+n(xs[k],0)+'</text>'});
  return s+'</svg>'}
document.getElementById("go").onclick=function(){loadChain(true)};document.getElementById("exp").onchange=function(){S.legs=[];loadChain(false)};document.getElementById("fill").onchange=function(){if(S.chain)run()};
document.getElementById("sym").onkeydown=function(e){if(e.key==="Enter"){S.legs=[];document.getElementById("exp").innerHTML="";loadChain(false)}};
fetch("/api/contract-lab-symbols",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){document.getElementById("syms").innerHTML=(d.symbols||[]).map(function(s){return '<option value="'+s+'">'}).join("")}).catch(function(){});
var q=new URLSearchParams(location.search),s0=(q.get("symbol")||ls("sb_sym")||"").toUpperCase();
if(s0){document.getElementById("sym").value=s0;if(q.get("legs"))S.legs=parse(q.get("legs"));if(q.get("expiry")){var o=document.createElement("option");o.value=q.get("expiry");document.getElementById("exp").appendChild(o)}loadChain(!!q.get("legs"))}
</script></body></html>"""
