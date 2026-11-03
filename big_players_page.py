"""HTML of the Big Players page (see big_players.py). Plain JS, no external libraries."""

HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Big Players</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{--bg:#05080f;--panel:#0a111d;--line:#17324a;--text:#e6edf9;--muted:#7d8fab;--g:#27e39a;--r:#ff4d5e;--gold:#ffb454;--c:#22e6ff}
*{box-sizing:border-box}html,body{background:var(--bg)!important;color:var(--text);margin:0;font:12.5px/1.35 "Segoe UI",Arial,sans-serif}
#bp{padding:10px 14px 26px;max-width:1750px;margin:0 auto}
h1{font-size:15px;letter-spacing:.2em;margin:8px 0 2px;text-transform:uppercase}.sub{color:var(--muted);font-size:11.5px}
.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:10px 0}.card{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px 12px}
.card .l{color:var(--muted);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase}.card .v{font-size:20px;font-weight:800;margin-top:2px;font-variant-numeric:tabular-nums}
.g{color:var(--g)}.r{color:var(--r)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.box{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px 10px;margin-bottom:12px}
.box h2{margin:0 0 6px;font-size:12px;letter-spacing:.16em;text-transform:uppercase}.box.buy h2{color:var(--g)}.box.sell h2{color:var(--r)}.box.buy{border-color:#14634f}.box.sell{border-color:#6a2230}
table{width:100%;border-collapse:collapse}th,td{padding:5px 6px;border-bottom:1px solid #112238;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
th{color:var(--muted);font-size:10px;letter-spacing:.08em;text-transform:uppercase;font-weight:600}td:first-child,th:first-child{text-align:left}td:first-child{font-weight:800}
.chip{display:inline-block;padding:0 5px;margin-left:3px;border-radius:3px;font-size:10px;font-weight:800;border:1px solid}
.chip.b{color:var(--g);border-color:#14634f;background:#0c2b24}.chip.s{color:var(--r);border-color:#6a2230;background:#2a1018}
.small{color:var(--muted);font-size:10.5px}.bar{display:inline-block;height:7px;border-radius:2px;vertical-align:middle}
.tape{max-height:430px;overflow:auto}.tape div{display:grid;grid-template-columns:62px 90px 40px 70px 70px;gap:6px;padding:3px 2px;border-bottom:1px solid #0f1f33;font-variant-numeric:tabular-nums}
.note{color:var(--muted);font-size:11px;margin-top:6px}
@media(max-width:1100px){.cards{grid-template-columns:repeat(2,1fr)}.cols{grid-template-columns:1fr}}
</style></head><body><div id="bp">
<h1>Big Players</h1><div class="sub" id="asof">loading...</div>
<div class="cards" id="cards"></div>
<div class="cols"><div class="box buy"><h2>Big players buying</h2><div id="buy"></div></div><div class="box sell"><h2>Big players selling</h2><div id="sell"></div></div></div>
<div class="cols"><div class="box"><h2 style="color:var(--c)">By sector (big net, Rs cr)</h2><div id="sec"></div></div><div class="box"><h2 style="color:var(--c)">Big print tape</h2><div class="tape" id="tape"></div></div></div>
<div class="note">A big print is a trade size at or above the 99th percentile of that stock's prints today (and 3x its median, at least Rs 10 lakh), tagged buyer- or seller-initiated from the live feed. Chips show which of four independent signals agree:
<b>FUT</b> near-month future (price and open interest, last ~30 min), <b>OPT</b> option premium in the last 15 min mostly on calls (buy) or puts (sell), <b>BOOK</b> resting bid vs ask size, <b>TICK</b> net buying value by the tick rule.
This shows where size is pressing, not who is behind it: it cannot tell an institution from a retail trader, or one large order from many small ones. Not a trade signal.</div>
</div><script>
var D=null;
function sg(n,d){n=Number(n);return (n>0?"+":"")+n.toFixed(d==null?2:d)}function cl(n){return n>0?"g":n<0?"r":""}
var FL={LONG_BUILDUP:"long build-up",SHORT_COVERING:"short covering",SHORT_BUILDUP:"short build-up",LONG_UNWINDING:"long unwinding",NEUTRAL:"-"};
function table(rows,side){if(!rows.length)return '<div class="sub">nothing yet</div>';var mx=Math.max.apply(null,rows.map(function(r){return Math.abs(r.net15)}))||1;
 return '<table><thead><tr><th>Stock</th><th>Big net 15m</th><th></th><th>Today net</th><th>B/S prints</th><th>Last big print</th><th>Futures</th><th>Chg</th><th>Confirms</th></tr></thead><tbody>'+rows.map(function(r){
  var chips=(side==="b"?r.cb:r.cs).map(function(c){return '<span class="chip '+side+'">'+c+'</span>'}).join("");
  var l=r.last?(r.last.t.slice(0,5)+' '+(r.last.side==="B"?'<span class="g">BUY</span>':'<span class="r">SELL</span>')+' '+r.last.lakh+'L'):"-";
  var f=r.fut?(FL[r.fut.label]+' <span class="small">'+sg(r.fut.oi_pct,1)+'% OI</span>'):"-";
  return '<tr><td>'+r.s+'</td><td class="'+cl(r.net15)+'">'+sg(r.net15)+'</td><td style="width:70px"><span class="bar" style="width:'+Math.max(2,Math.abs(r.net15)/mx*64)+'px;background:'+(r.net15>=0?"#27e39a":"#ff4d5e")+'"></span></td><td class="'+cl(r.net)+'">'+sg(r.net)+'</td><td>'+r.nb+' / '+r.ns+'</td><td>'+l+'</td><td>'+f+'</td><td class="'+cl(r.chg)+'">'+(r.chg==null?"-":sg(r.chg)+"%")+'</td><td style="text-align:left">'+chips+'</td></tr>'}).join("")+'</tbody></table>'}
function render(){if(!D)return;var a=document.getElementById("asof");if(!D.ok){a.textContent=D.error||"no data";return}
 var m=D.market;a.textContent="Big prints to "+D.as_of+" - futures data "+(D.futures_ok?"live":"not yet")+" - option premium data "+(D.options_ok?"live":"not yet");
 document.getElementById("cards").innerHTML=[["Big buying today",m.buy_cr+" cr",""],["Big selling today",m.sell_cr+" cr",""],["Net",sg(m.net_cr,1)+" cr",cl(m.net_cr)],["Stocks net buying",m.net_buying,"g"],["Stocks net selling",m.net_selling,"r"]].map(function(x){return '<div class="card"><div class="l">'+x[0]+'</div><div class="v '+x[2]+'">'+x[1]+'</div></div>'}).join("");
 document.getElementById("buy").innerHTML=table(D.buyers,"b");document.getElementById("sell").innerHTML=table(D.sellers,"s");
 var mx=Math.max.apply(null,D.sectors.map(function(s){return Math.abs(s.net)}))||1;
 document.getElementById("sec").innerHTML='<table><tbody>'+D.sectors.map(function(s){return '<tr><td>'+s.sec+'</td><td class="'+cl(s.net)+'">'+sg(s.net,1)+'</td><td style="width:160px"><span class="bar" style="width:'+Math.max(2,Math.abs(s.net)/mx*150)+'px;background:'+(s.net>=0?"#27e39a":"#ff4d5e")+'"></span></td><td class="small">15m '+sg(s.net15,1)+'</td></tr>'}).join("")+'</tbody></table>';
 document.getElementById("tape").innerHTML=D.tape.map(function(t){return '<div><span class="small">'+t.t+'</span><b>'+t.s+'</b><span class="'+(t.side==="B"?"g":"r")+'">'+(t.side==="B"?"BUY":"SELL")+'</span><span>'+t.lakh+' L</span><span class="small">@'+t.px+'</span></div>'}).join("")}
function load(){fetch("/api/big-players",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){D=d;render()}).catch(function(){document.getElementById("asof").textContent="connection lost - retrying"})}
load();setInterval(load,5000);
</script></body></html>"""
