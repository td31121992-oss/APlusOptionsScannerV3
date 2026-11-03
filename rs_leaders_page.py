"""HTML of the Red Market Leaders page (see rs_leaders.py). Plain JS, no external libraries."""

HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Market Leaders</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{--bg:#05080f;--panel:#0a111d;--line:#17324a;--text:#e6edf9;--muted:#7d8fab;--g:#27e39a;--r:#ff4d5e;--gold:#ffb454;--c:#22e6ff}
*{box-sizing:border-box}html,body{background:var(--bg)!important;color:var(--text);margin:0;font:12.5px/1.35 "Segoe UI",Arial,sans-serif}
#rs{padding:10px 14px 26px;max-width:1500px;margin:0 auto}h1{font-size:15px;letter-spacing:.2em;margin:8px 0 2px;text-transform:uppercase}.sub{color:var(--muted);font-size:11.5px}
.banner{display:flex;gap:18px;align-items:center;flex-wrap:wrap;border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:10px 14px;margin:10px 0}
.state{font-weight:800;letter-spacing:.2em;padding:4px 12px;border-radius:5px;border:1px solid}.state.red{color:var(--r);border-color:#6a2230;background:#2a1018}.state.green{color:var(--g);border-color:#14634f;background:#0c2b24}
.big{font-size:22px;font-weight:800;font-variant-numeric:tabular-nums}.g{color:var(--g)}.r{color:var(--r)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}.box{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px 10px;margin-bottom:12px}
.box h2{margin:0 0 6px;font-size:12px;letter-spacing:.16em;text-transform:uppercase}.box.up h2{color:var(--g)}.box.dn h2{color:var(--r)}.box.up{border-color:#14634f}.box.dn{border-color:#6a2230}
table{width:100%;border-collapse:collapse}th,td{padding:5px 6px;border-bottom:1px solid #112238;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
th{color:var(--muted);font-size:10px;letter-spacing:.08em;text-transform:uppercase;font-weight:600}td:first-child,th:first-child{text-align:left}td:first-child{font-weight:800}
.chip{display:inline-block;padding:0 5px;margin-left:4px;border-radius:3px;font-size:10px;font-weight:800;border:1px solid var(--gold);color:var(--gold)}
.note{color:var(--muted);font-size:11px;margin-top:6px}@media(max-width:1100px){.cols{grid-template-columns:1fr}}
</style></head><body><div id="rs"><h1>Market leaders &amp; laggards</h1><div class="sub" id="asof">loading...</div>
<div class="banner" id="banner"></div>
<div class="cols"><div class="box up"><h2>Outperforming the market (above VWAP)</h2><div id="lead"></div></div><div class="box dn"><h2>Underperforming the market (below VWAP)</h2><div id="lag"></div></div></div>
<div class="note">The market is the median F&amp;O stock's move from its previous close; "vs market" is how far ahead of (+) or behind (-) it a stock is. A leader is 2% or more ahead of the market, above its exchange VWAP, on at least its usual volume (STRONG = 3% or more).
Checks (display only, nothing is blocked): nifty = ahead of NIFTY 50; sector = ahead of its sector index (where we stream one: IT, Auto, Pharma, FMCG, Metals, Energy, Banking/Financial) or else its sector's median stock; accel = still moving our way over the last 2 minutes; chase = has not already run 1.5% in 15 minutes; spread = stock bid-ask within 0.25%; chain = ATM option spread within 2%. A stock whose last tick is over 10 seconds old is hidden. Updated every 2 seconds from the live tick stream. In our history, leaders of a red market beat it by only about +0.3% by the close and calls on them were about break-even, so this shows where strength is, it is not a trade signal.</div></div><script>
var D=null;function sg(n,d){n=Number(n);return (n>0?"+":"")+n.toFixed(d==null?2:d)}function cl(n){return n>0?"g":n<0?"r":""}
function checks(r){var c=r.checks||{},bad=Object.keys(c).filter(function(k){return !c[k]});return bad.length?'<span class="r">'+bad.join(', ')+'</span>':'<span class="g">all pass</span>'}
function table(rows,strongAt){if(!rows||!rows.length)return '<div class="sub">none right now</div>';
 return '<table><thead><tr><th>Stock</th><th>Move</th><th>vs market</th><th>vs VWAP</th><th>Volume x</th><th>vs NIFTY</th><th>vs sector idx</th><th>vs sector</th><th>2 min</th><th>15 min</th><th>Big net 15m</th><th>Opt spread</th><th>Checks</th></tr></thead><tbody>'+rows.map(function(r){
  var strong=Math.abs(r.rs)>=strongAt?'<span class="chip">STRONG</span>':"";
  return '<tr><td>'+r.s+strong+'<span class="sub"> '+(r.sec||"")+'</span></td><td class="'+cl(r.move)+'">'+sg(r.move)+'%</td><td class="'+cl(r.rs)+'">'+sg(r.rs)+'%</td><td class="'+cl(r.vs_vwap)+'">'+sg(r.vs_vwap)+'%</td><td>'+r.rvol.toFixed(1)+'x</td><td class="'+cl(r.rs_nifty)+'">'+(r.rs_nifty==null?"-":sg(r.rs_nifty)+"%")+'</td><td class="'+cl(r.rs_sidx)+'">'+(r.rs_sidx==null?"-":sg(r.rs_sidx)+"%")+'</td><td class="'+cl(r.rs_sec)+'">'+(r.rs_sec==null?"-":sg(r.rs_sec)+"%")+'</td><td class="'+cl(r.acc2)+'">'+sg(r.acc2)+'%</td><td class="'+cl(r.mom15)+'">'+sg(r.mom15)+'%</td><td class="'+cl(r.big15)+'">'+(r.big15==null?"-":sg(r.big15,1)+" cr")+'</td><td>'+(r.opt_spread==null?"-":r.opt_spread.toFixed(1)+"%")+'</td><td>'+checks(r)+'</td></tr>'}).join("")+'</tbody></table>'}
function render(){var a=document.getElementById("asof");if(!D||!D.ok){a.textContent=(D&&D.error)||"loading...";return}
 var m=D.market;a.textContent="Live to "+D.updated+" - "+m.n+" stocks";
 document.getElementById("banner").innerHTML='<span class="state '+(m.red?"red":"green")+'">'+(m.red?"RED MARKET":"GREEN MARKET")+'</span><span>median stock <span class="big '+cl(m.median)+'">'+sg(m.median)+'%</span></span><span>NIFTY 50 <span class="big '+cl(m.nifty)+'">'+(m.nifty==null?'-':sg(m.nifty)+'%')+'</span></span><span>stocks down <span class="big">'+m.pct_down.toFixed(0)+'%</span></span><span>leaders <span class="big g">'+D.n_leaders+'</span></span><span>laggards <span class="big r">'+D.n_laggards+'</span></span>';
 document.getElementById("lead").innerHTML=table(D.leaders,3);document.getElementById("lag").innerHTML=table(D.laggards,3)}
function load(){fetch("/api/rs-leaders",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){D=d;render()}).catch(function(){document.getElementById("asof").textContent="connection lost - retrying"})}
load();setInterval(load,2000);
</script></body></html>"""
