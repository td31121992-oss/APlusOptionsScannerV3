"""Greeks Lab: what an option's Greeks say, and a what-if calculator. READ-ONLY - nothing here touches the scanner, a signal or a trade.

    /greeks-lab?symbol=SBIN&side=CE                                   the page
    /api/greeks-lab?symbol=SBIN&side=CE&expiry=2026-11-23             Greeks for every strike of the chain
    /api/greeks-whatif?symbol=SBIN&side=CE&expiry=..&strike=950&move=1.5&days=2&iv=-2     one scenario + grid + decay curve

The chain comes from contract_lab.analyse (same live chain, 15 s cache). Greeks use greeks.py (Black-Scholes, 7% rate, implied volatility solved from the option's own price),
the same model that tags every paper trade, so numbers here compare directly with the trade review. They are model numbers, approximate - good for comparing strikes and for
sizing up a scenario, not exact pricing. Costs (brokerage, spread) are not in the what-if; the spread is shown beside it.

What-if: the option is re-priced with Black-Scholes after the stock moves by `move` %, `days` calendar days pass and implied volatility changes by `iv` points.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import contract_lab
import greeks as gk

MOVES = (-5.0, -3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 5.0)
DAYS = (0.0, 1.0, 2.0, 3.0, 5.0)
FAR_PCT = 10.0                                       # strikes further than this from the stock are left out of the Greeks table


def _num(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _lab(symbol: str, side: str, expiry: str) -> dict[str, Any]:
    return contract_lab.analyse(symbol, side, expiry)


def table(symbol: str, side: str = "CE", expiry: str = "") -> dict[str, Any]:
    """Greeks for every strike (within 10% of the stock) of one side, with the Contract Lab's verdict beside each."""
    lab = _lab(symbol, side, expiry)
    if not lab.get("ok"):
        return lab
    spot, call = _num(lab["spot"]), lab["side"] == "CE"
    rows = []
    for r in lab["rows"]:
        if r["from_spot_pct"] is not None and r["from_spot_pct"] > FAR_PCT:
            continue
        g = gk.greeks_at_entry(spot, r["strike"], lab["expiry"], lab["side"], r["ltp"], feed_iv_pct=r["iv"])
        if not g:
            continue
        be = (r["strike"] + r["ltp"]) if call else (r["strike"] - r["ltp"])
        lot = r.get("lot_size") or 0
        rows.append({"strike": r["strike"], "status": r["status"], "itm": r["itm"], "ltp": r["ltp"], "bid": r["bid"], "ask": r["ask"], "spread_pct": r["spread_pct"],
                     "lot_size": lot, "iv": g["gk_iv_pct"], "delta": g["gk_delta"], "gamma": g["gk_gamma"], "theta_day": g["gk_theta_day"], "theta_pct_day": g["gk_theta_pct_day"],
                     "theta_lot_day": round(g["gk_theta_day"] * lot, 0) if lot else None, "vega": g["gk_vega_1pt"], "move_10": g["gk_move_pct_to_10pct"],
                     "move_theta": g["gk_breakeven_move_pct"], "breakeven_pct": round((be - spot) / spot * 100.0, 2)})
    chosen = (lab.get("chosen") or {}).get("strike")
    return {"ok": True, "symbol": lab["symbol"], "side": lab["side"], "expiry": lab["expiry"], "expiries": lab["expiries"], "scanner_expiry": lab.get("scanner_expiry", ""),
            "days_to_expiry": lab["days_to_expiry"], "spot": spot, "atm": lab["atm"], "chosen_strike": chosen, "captured_at": lab.get("captured_at", ""), "rows": rows}


def _model(spot: float, strike: float, dte: int, call: bool, price: float, feed_iv: float) -> tuple[float, float, bool] | None:
    """(t0 in years, starting volatility, solved) - the same time convention as greeks.greeks_at_entry."""
    t0 = max(0.5, dte + 0.5) / 365.0
    v = gk.implied_vol(price, spot, strike, t0, call)
    if v:
        return t0, v, True
    if feed_iv:
        return t0, float(feed_iv) / 100.0, False
    return None


def _price(spot: float, strike: float, call: bool, t0: float, v0: float, move: float, days: float, ivc: float) -> float:
    return gk.bs_price(spot * (1.0 + move / 100.0), strike, max(0.0, t0 - days / 365.0), max(0.01, v0 + ivc / 100.0), call)


def whatif(symbol: str, side: str = "CE", expiry: str = "", strike: Any = 0, move: Any = 0, days: Any = 0, iv: Any = 0) -> dict[str, Any]:
    """Re-price one strike after a stock move, some days passing and an IV change; plus a move x days grid and the decay curve."""
    lab = _lab(symbol, side, expiry)
    if not lab.get("ok"):
        return lab
    k = _num(strike)
    row = next((r for r in lab["rows"] if abs(_num(r["strike"]) - k) < 1e-9), None)
    if row is None:
        return {"ok": False, "error": f"Strike {k:g} is not in this chain."}
    spot, call, dte = _num(lab["spot"]), lab["side"] == "CE", int(lab["days_to_expiry"])
    ltp = _num(row["ltp"])
    m = _model(spot, k, dte, call, ltp, _num(row["iv"]))
    if m is None:
        return {"ok": False, "error": "This strike has no usable price or IV, so it cannot be modelled."}
    t0, v0, solved = m
    mv, dy, ic = _clamp(_num(move), -30.0, 30.0), _clamp(_num(days), 0.0, dte + 0.5), _clamp(_num(iv), -30.0, 30.0)
    lot = row.get("lot_size") or 0
    base = _price(spot, k, call, t0, v0, 0.0, 0.0, 0.0)

    def pct(p: float) -> float | None:
        return round((p - base) / base * 100.0, 1) if base > 0 else None

    new = _price(spot, k, call, t0, v0, mv, dy, ic)
    theta_only = _price(spot, k, call, t0, v0, 0.0, dy, 0.0)
    grid_days = [d for d in DAYS if d <= dte] + ([float(dte) + 0.5] if dte + 0.5 not in DAYS else [])
    grid = [{"move": mv_, "cells": [{"days": d, "price": round(_price(spot, k, call, t0, v0, mv_, d, ic), 2), "pnl_pct": pct(_price(spot, k, call, t0, v0, mv_, d, ic))} for d in grid_days]} for mv_ in MOVES]
    curve = {"days": [], "flat": [], "up1": [], "down1": []}
    steps = sorted({float(i) for i in range(0, dte + 1)} | {dte + 0.5})
    for d in steps:
        curve["days"].append(d)
        curve["flat"].append(round(_price(spot, k, call, t0, v0, 0.0, d, ic), 2))
        curve["up1"].append(round(_price(spot, k, call, t0, v0, 1.0, d, ic), 2))
        curve["down1"].append(round(_price(spot, k, call, t0, v0, -1.0, d, ic), 2))
    spread = (row["ask"] - row["bid"]) if (row["ask"] and row["bid"]) else None
    return {"ok": True, "symbol": lab["symbol"], "side": lab["side"], "expiry": lab["expiry"], "strike": k, "spot": spot, "days_to_expiry": dte, "lot_size": lot,
            "inputs": {"move": mv, "days": dy, "iv": ic}, "start_iv": round(v0 * 100.0, 1), "iv_solved": solved, "start_price": round(base, 2), "market_price": ltp,
            "new_spot": round(spot * (1.0 + mv / 100.0), 2), "new_price": round(new, 2), "pnl_share": round(new - base, 2), "pnl_lot": round((new - base) * lot, 0) if lot else None,
            "pnl_pct": pct(new), "theta_only_price": round(theta_only, 2), "theta_only_pct": pct(theta_only), "spread_share": None if spread is None else round(spread, 2),
            "spread_pct": row["spread_pct"], "grid_days": grid_days, "grid": grid, "curve": curve}


GREEKS_LAB_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Greeks Lab</title>
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
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:6px 9px;text-align:right;border-bottom:1px solid #1b2640;white-space:nowrap}th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.35px;background:#0f1729}
td.l,th.l{text-align:left}tr.row{cursor:pointer}tr.row:hover{background:#16213a}tr.sel{background:#14274a}tr.CHOSEN td:first-child{box-shadow:inset 3px 0 var(--green)}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:800}.tag.CHOSEN{background:var(--green);color:#04251a}.tag.ELIGIBLE{background:#1c3b66;color:#cfe2ff}.tag.REJECTED{background:#3a2020;color:#ffb3b3}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-top:10px}.panel h3{margin:0 0 6px;font-size:13px}
.ctl{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px 22px;margin:6px 0}.ctl label{display:block;color:var(--muted);font-size:11px;text-transform:uppercase}.ctl b{color:var(--text);font-size:14px}.ctl input[type=range]{width:100%;padding:0}
.res{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-top:8px}.res div{background:#0e1527;border:1px solid var(--line);border-radius:8px;padding:7px 10px}.res span{display:block;color:var(--muted);font-size:11px;text-transform:uppercase}.res b{font-size:16px}
.up{color:var(--green)}.dn{color:var(--red)}.itm{color:var(--green)}.otm{color:var(--muted)}
td.g{text-align:center;font-weight:700}td.g small{display:block;font-weight:400;color:#c9d6ef;font-size:11px}
.nopick{background:#2a1414;border:1px solid #6b2a2a;border-radius:10px;padding:10px 14px;margin:8px 0}
.help{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:4px 22px}.help div span{color:var(--blue);font-weight:800}
</style></head><body>
<div class="top"><a href="/">&larr; Dashboard</a><b>Greeks Lab</b><input id="sym" list="syms" placeholder="stock"><datalist id="syms"></datalist>
<span><button id="bce" class="on">Calls (bullish)</button> <button id="bpe">Puts (bearish)</button></span>
<select id="exp"></select><button id="go">Refresh</button><span class="sub" id="meta"></span></div>
<div class="wrap">
<div class="sub" style="margin-bottom:6px">Model numbers (Black-Scholes, IV solved from each option's own price) - good for comparing strikes and testing a scenario, not exact pricing. Click a strike to test it. Read-only.</div>
<div id="out"><div class="sub">Pick a stock and press Enter.</div></div></div>
<script>
var S={side:"CE",strike:null,tab:null,timer:null,t:null};
function fmtTs(s){if(!s)return"";try{var d=new Date(s);if(isNaN(d))return String(s).replace("T"," ").slice(0,19);return d.toLocaleString("en-GB",{timeZone:"Asia/Kolkata",hour12:false}).replace(",","")+" IST"}catch(e){return String(s).slice(0,19)}}
function esc(t){return String(t==null?"":t).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function n(v,d){return v==null||v===""?"-":Number(v).toLocaleString("en-IN",{minimumFractionDigits:d||0,maximumFractionDigits:d||0})}
function inr(v){return v==null?"-":"₹"+Number(v).toLocaleString("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2})}
function cls(v){return v>0?"up":v<0?"dn":""}
function sgn(v,d){return v==null?"-":(v>0?"+":"")+n(v,d)}
function ls(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){return null}}
function card(l,v){return '<div class="card"><div class="l">'+esc(l)+'</div><div class="v">'+v+'</div></div>'}
function render(d){
  var o=document.getElementById("out");
  if(!d.ok){o.innerHTML='<div class="nopick">'+esc(d.error||"No data")+'</div>';return}
  S.d=d;var sel=document.getElementById("exp");sel.innerHTML=d.expiries.map(function(e){return '<option value="'+e+'"'+(e===d.expiry?" selected":"")+'>'+e+(e===d.scanner_expiry?" (scanner uses this)":"")+'</option>'}).join("");
  document.getElementById("meta").textContent=fmtTs(d.captured_at);
  if(S.strike==null||!d.rows.some(function(r){return r.strike===S.strike})){S.strike=d.chosen_strike!=null?d.chosen_strike:(d.rows.reduce(function(b,r){return b==null||Math.abs(r.strike-d.atm)<Math.abs(b-d.atm)?r.strike:b},null))}
  var h='<div class="cards">'+card("Stock",esc(d.symbol))+card("Stock price",inr(d.spot))+card("ATM strike",n(d.atm,2))+card("Expiry","in "+d.days_to_expiry+" days")+card("Scanner would buy",d.chosen_strike!=null?n(d.chosen_strike,2):"none")+'</div>';
  h+='<div style="overflow-x:auto"><table><thead><tr><th class="l">Scanner</th><th>Strike</th><th>Premium</th><th>Spread</th><th>IV %</th><th>Delta</th><th>Gamma</th><th>Theta / day</th><th>Theta % / day</th><th>Theta / lot / day</th><th>Vega / IV pt</th><th>Stock move for +10%</th><th>Stock move to cover a day</th><th>Breakeven at expiry</th></tr></thead><tbody>';
  d.rows.forEach(function(r){h+='<tr class="row '+r.status+(r.strike===S.strike?" sel":"")+'" data-k="'+r.strike+'"><td class="l"><span class="tag '+r.status+'">'+r.status+'</span></td><td class="'+(r.itm?"itm":"otm")+'">'+n(r.strike,2)+(r.strike===d.atm?" &#9733;":"")+'</td><td>'+inr(r.ltp)+'</td><td>'+(r.spread_pct==null?"-":n(r.spread_pct,2)+"%")+'</td><td>'+n(r.iv,1)+'</td><td>'+n(r.delta,3)+'</td><td>'+n(r.gamma,4)+'</td><td class="dn">'+n(r.theta_day,2)+'</td><td class="dn">'+n(r.theta_pct_day,2)+'%</td><td class="dn">'+(r.theta_lot_day==null?"-":n(r.theta_lot_day,0))+'</td><td>'+n(r.vega,2)+'</td><td>'+n(r.move_10,2)+'%</td><td>'+(r.move_theta===""?"-":n(r.move_theta,2)+"%")+'</td><td>'+sgn(r.breakeven_pct,2)+'%</td></tr>'});
  h+='</tbody></table></div><div class="sub" style="margin-top:6px">Strikes within 10% of the stock price. Green strikes are in the money, grey out of the money; a star marks the at-the-money strike. Rupee figures are per share unless a column says per lot.</div>';
  h+='<div class="panel" id="wi"><div class="sub">loading scenario ...</div></div>';
  h+='<div class="panel"><h3>What the columns mean (&#9432;)</h3><div class="help">'+
    '<div><span>Delta</span> premium change for Rs 1 move in the stock. 0.50 means the option gains about Rs 0.50 when the stock gains Rs 1 (calls); puts have negative delta and gain when the stock falls.</div>'+
    '<div><span>Gamma</span> how much delta changes for Rs 1 stock move. High gamma (near the money, near expiry) means gains and losses speed up.</div>'+
    '<div><span>Theta</span> premium lost per calendar day if nothing moves. "% / day" is that as a share of the premium - the option melting speed. Cheap, near-expiry options melt fastest in % terms.</div>'+
    '<div><span>Vega</span> premium change when implied volatility moves 1 point. Falling IV after the news hurts the option even if the stock moves your way.</div>'+
    '<div><span>Stock move for +10%</span> how far the stock must move your way for the premium to rise 10% (delta and gamma estimate).</div>'+
    '<div><span>Stock move to cover a day</span> how far the stock must move just to pay one day of theta.</div>'+
    '<div><span>Breakeven at expiry</span> stock move from here (percent) needed for the option to finish at what you paid - strike plus premium for calls, strike minus premium for puts.</div>'+
    '<div><span>IV</span> volatility that makes the model price equal the market price (not the feed IV, which can differ by a few points).</div></div></div>';
  o.innerHTML=h;
  [].slice.call(o.querySelectorAll("tr.row")).forEach(function(tr){tr.onclick=function(){S.strike=parseFloat(tr.getAttribute("data-k"));[].slice.call(o.querySelectorAll("tr.row")).forEach(function(x){x.className=x.className.replace(" sel","")});tr.className+=" sel";S.reset=true;whatif()}});
  S.reset=true;whatif()}
function whatif(){
  var d=S.d;if(!d||S.strike==null)return;var el=document.getElementById("wi");
  var mv=S.move!=null&&!S.reset?S.move:0,dy=S.days!=null&&!S.reset?S.days:0,iv=S.iv!=null&&!S.reset?S.iv:0;
  fetch("/api/greeks-whatif?symbol="+encodeURIComponent(d.symbol)+"&side="+d.side+"&expiry="+d.expiry+"&strike="+S.strike+"&move="+mv+"&days="+dy+"&iv="+iv,{cache:"no-store"}).then(function(r){return r.json()}).then(function(w){
    if(!w.ok){el.innerHTML='<div class="nopick">'+esc(w.error)+'</div>';return}
    var x=w.inputs;S.reset=false;S.move=x.move;S.days=x.days;S.iv=x.iv;
    var h='<h3>What if ... &nbsp;<span class="sub">'+esc(w.symbol)+' '+n(w.strike,2)+' '+w.side+', expiry '+w.expiry+' ('+w.days_to_expiry+' days), bought at about '+inr(w.start_price)+'</span></h3><div class="ctl">'+
      '<div><label>Stock moves <b id="vm">'+sgn(x.move,2)+'%</b> (to '+inr(w.new_spot)+')</label><input id="rm" type="range" min="-10" max="10" step="0.25" value="'+x.move+'"></div>'+
      '<div><label>Days pass <b id="vd">'+n(x.days,1)+'</b> of '+w.days_to_expiry+'</label><input id="rd" type="range" min="0" max="'+(w.days_to_expiry+0.5)+'" step="0.5" value="'+x.days+'"></div>'+
      '<div><label>IV changes <b id="vi">'+sgn(x.iv,1)+' points</b> (now '+n(w.start_iv,1)+')</label><input id="ri" type="range" min="-15" max="15" step="0.5" value="'+x.iv+'"></div></div>'+
      '<div class="res"><div><span>New premium</span><b>'+inr(w.new_price)+'</b></div><div><span>Gain / loss per share</span><b class="'+cls(w.pnl_share)+'">'+sgn(w.pnl_share,2)+'</b></div>'+
      '<div><span>Gain / loss per lot'+(w.lot_size?' ('+w.lot_size+')':'')+'</span><b class="'+cls(w.pnl_lot)+'">'+(w.pnl_lot==null?"-":sgn(w.pnl_lot,0))+'</b></div>'+
      '<div><span>On the premium</span><b class="'+cls(w.pnl_pct)+'">'+(w.pnl_pct==null?"-":sgn(w.pnl_pct,1)+"%")+'</b></div>'+
      '<div><span>Time alone costs</span><b class="dn">'+(w.theta_only_pct==null?"-":sgn(w.theta_only_pct,1)+"%")+'</b></div>'+
      '<div><span>Bid-ask gap</span><b>'+(w.spread_share==null?"-":inr(w.spread_share)+(w.spread_pct==null?"":" ("+n(w.spread_pct,1)+"%)"))+'</b></div></div>'+
      '<div class="sub" style="margin-top:6px">"Time alone costs" = the same stock price after the chosen days with no IV change. The gap is paid on the way in and out and is not in the gain figures; brokerage and taxes are not included either.'+(w.iv_solved?"":" The price was below intrinsic value, so the feed IV is the starting volatility.")+'</div>'+
      '<div style="overflow-x:auto;margin-top:8px"><table><thead><tr><th class="l">Stock move &darr; / days passed &rarr;</th>'+w.grid_days.map(function(g){return '<th>'+(g>w.days_to_expiry?"at expiry":(g===0?"today":g+" day"+(g>1?"s":"")))+'</th>'}).join("")+'</tr></thead><tbody>'+
      w.grid.map(function(r){return '<tr><td class="l">'+sgn(r.move,0)+'%</td>'+r.cells.map(function(c){var p=c.pnl_pct,a=p==null?0:Math.min(.55,Math.abs(p)/120);var bg=p==null?"":(p>=0?"rgba(39,194,129,"+a+")":"rgba(255,107,107,"+a+")");return '<td class="g" style="background:'+bg+'">'+(p==null?"-":sgn(p,0)+"%")+'<small>'+inr(c.price)+'</small></td>'}).join("")+'</tr>'}).join("")+'</tbody></table></div>'+
      '<div class="sub" style="margin-top:4px">Grid uses the IV change set above. Green = gain on the premium, red = loss.</div>'+curve(w);
    el.innerHTML=h;
    ["rm","rd","ri"].forEach(function(id){document.getElementById(id).oninput=function(){var v=parseFloat(this.value);if(id==="rm")S.move=v;if(id==="rd")S.days=v;if(id==="ri")S.iv=v;clearTimeout(S.t);S.t=setTimeout(whatif,120)}})
  }).catch(function(){el.innerHTML='<div class="nopick">Connection lost.</div>'})}
function curve(w){
  var c=w.curve,W=760,H=210,L=44,B=24,T=10,R=10,lines=[["flat","Stock unchanged","#8ea0bd"],["up1","Stock +1%","#27c281"],["down1","Stock -1%","#ff6b6b"]];
  var max=0;lines.forEach(function(l){c[l[0]].forEach(function(v){if(v>max)max=v})});if(max<=0)return"";
  var xm=c.days[c.days.length-1]||1;function X(d){return L+(W-L-R)*d/xm}function Y(v){return T+(H-T-B)*(1-v/max)}
  var s='<h3 style="margin-top:12px">Premium as time passes <span class="sub">(IV change as set above)</span></h3><svg viewBox="0 0 '+W+' '+H+'" style="width:100%;max-width:780px;background:#0e1527;border:1px solid #27334d;border-radius:8px">';
  for(var i=0;i<=4;i++){var v=max*i/4;s+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+Y(v)+'" y2="'+Y(v)+'" stroke="#1b2640"/><text x="4" y="'+(Y(v)+4)+'" fill="#8ea0bd" font-size="10">'+n(v,1)+'</text>'}
  lines.forEach(function(l){s+='<polyline fill="none" stroke="'+l[2]+'" stroke-width="2" points="'+c.days.map(function(d,i){return X(d)+","+Y(c[l[0]][i])}).join(" ")+'"/>'});
  s+='<text x="'+L+'" y="'+(H-6)+'" fill="#8ea0bd" font-size="10">today</text><text x="'+(W-R-50)+'" y="'+(H-6)+'" fill="#8ea0bd" font-size="10">expiry</text>';
  lines.forEach(function(l,i){s+='<text x="'+(L+10+i*150)+'" y="'+(T+12)+'" fill="'+l[2]+'" font-size="11">&#9632; '+l[1]+'</text>'});
  return s+'</svg><div class="sub">The lines bend downward faster as expiry nears - that is theta speeding up. Compare how much a +1% stock move adds against what a day of time takes away.</div>'}
function load(){var s=document.getElementById("sym").value.trim().toUpperCase();if(!s)return;ls("gl_sym",s);
  document.getElementById("out").innerHTML='<div class="sub">loading '+esc(s)+' ...</div>';
  fetch("/api/greeks-lab?symbol="+encodeURIComponent(s)+"&side="+S.side+"&expiry="+encodeURIComponent(document.getElementById("exp").value||""),{cache:"no-store"}).then(function(r){return r.json()}).then(render).catch(function(){document.getElementById("out").innerHTML='<div class="nopick">Connection lost.</div>'})}
function side(v){S.side=v;S.strike=null;document.getElementById("bce").className=v==="CE"?"on":"";document.getElementById("bpe").className=v==="PE"?"on":"";document.getElementById("exp").innerHTML="";load()}
document.getElementById("bce").onclick=function(){side("CE")};document.getElementById("bpe").onclick=function(){side("PE")};
document.getElementById("go").onclick=load;document.getElementById("exp").onchange=function(){S.strike=null;load()};
document.getElementById("sym").onkeydown=function(e){if(e.key==="Enter"){S.strike=null;document.getElementById("exp").innerHTML="";load()}};
fetch("/api/contract-lab-symbols",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){document.getElementById("syms").innerHTML=(d.symbols||[]).map(function(s){return '<option value="'+s+'">'}).join("")}).catch(function(){});
var q=new URLSearchParams(location.search);var s0=(q.get("symbol")||ls("gl_sym")||"").toUpperCase();if((q.get("side")||"").toUpperCase()==="PE"){S.side="PE";document.getElementById("bce").className="";document.getElementById("bpe").className="on"}
if(q.get("strike"))S.strike=parseFloat(q.get("strike"));
if(s0){document.getElementById("sym").value=s0;load()}
</script></body></html>"""
