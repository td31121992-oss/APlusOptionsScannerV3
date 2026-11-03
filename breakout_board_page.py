"""HTML of the Breakouts & Breakdowns page (see breakout_board.py). Plain JS, no external libraries."""

HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Breakouts and Breakdowns</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{--bg:#05080f;--panel:#0a111d;--line:#17324a;--text:#e6edf9;--muted:#7d8fab;--g:#27e39a;--r:#ff4d5e;--gold:#ffb454;--c:#22e6ff}
*{box-sizing:border-box}html,body{background:var(--bg)!important;color:var(--text);margin:0;font:12.5px/1.35 "Segoe UI",Arial,sans-serif}
#bo{padding:10px 14px 26px;max-width:1600px;margin:0 auto}h1{font-size:15px;letter-spacing:.2em;margin:8px 0 2px;text-transform:uppercase}.sub{color:var(--muted);font-size:11.5px}
.banner{display:flex;gap:18px;align-items:center;flex-wrap:wrap;border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px 14px;margin:10px 0}
.big{font-size:20px;font-weight:800;font-variant-numeric:tabular-nums}.g{color:var(--g)}.r{color:var(--r)}
.ctl{display:flex;gap:14px;align-items:center;margin:6px 0;color:var(--muted)}.ctl select{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:5px;padding:3px 6px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}.box{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px 10px}
.box h2{margin:0 0 6px;font-size:12px;letter-spacing:.16em;text-transform:uppercase}.box.up h2{color:var(--g)}.box.dn h2{color:var(--r)}.box.up{border-color:#14634f}.box.dn{border-color:#6a2230}
table{width:100%;border-collapse:collapse}th,td{padding:4px 6px;border-bottom:1px solid #112238;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
th{color:var(--muted);font-size:10px;letter-spacing:.08em;text-transform:uppercase;font-weight:600}td:first-child,th:first-child{text-align:left}td:first-child{font-weight:800}
.chip{display:inline-block;padding:0 5px;margin-left:3px;border-radius:3px;font-size:10px;font-weight:800;border:1px solid var(--c);color:var(--c)}
.tk{display:inline-block;width:15px;text-align:center;font-weight:800}.tk.y{color:var(--g)}.tk.n{color:#5a3a45}
.note{color:var(--muted);font-size:11px;margin-top:10px}@media(max-width:1200px){.cols{grid-template-columns:1fr}}
</style></head><body><div id="bo"><h1>Breakouts &amp; breakdowns</h1><div class="sub" id="asof">loading...</div>
<div class="banner" id="banner"></div>
<div class="ctl"><label>Show stocks with at least <select id="min"><option value="0">any score</option><option value="3">3 of 6</option><option value="4" selected>4 of 6</option><option value="5">5 of 6</option><option value="6">6 of 6</option></select> checks</label></div>
<div class="cols"><div class="box up"><h2>Breakouts: broke a level upward</h2><div id="up"></div></div><div class="box dn"><h2>Breakdowns: broke a level downward</h2><div id="dn"></div></div></div>
<div class="note">Levels: PDH / PDL = previous day's high / low; OR = the first 15 minutes' range; IB = the first hour's range (known after 10:15). The six ticks, in order: <b>M</b>arket not against it (or the stock is 1.5%+ ahead / behind),
<b>D</b>ecisive (0.15%+ beyond the level), <b>V</b>olume 2x+ the usual, V<b>W</b>AP side, <b>S</b>trength (1%+ ahead of / behind the market and not behind its sector), <b>O</b>ption spread within 2%. Updated every 5 seconds from the live ticks.
This is a filter to cut the noise: our own back-tests of break patterns on 87 days found no edge by themselves. It is not a trade signal.</div></div><script>
var D=null;function sg(n,d){n=Number(n);return (n>0?"+":"")+n.toFixed(d==null?2:d)}function cl(n){return n>0?"g":n<0?"r":""}
var K=["market","decisive","volume","vwap","strength","options"],L=["M","D","V","W","S","O"];
function ticks(c){return K.map(function(k,i){return '<span class="tk '+(c[k]?'y':'n')+'" title="'+k+'">'+(c[k]?L[i]:'·')+'</span>'}).join("")}
function table(rows,min){rows=(rows||[]).filter(function(r){return r.score>=min});if(!rows.length)return '<div class="sub">none right now</div>';
 return '<table><thead><tr><th>Stock</th><th>Price</th><th>Levels</th><th>Beyond</th><th>Vol x</th><th>vs VWAP</th><th>vs mkt</th><th>2 min</th><th>Opt spr</th><th>Checks</th><th>Score</th></tr></thead><tbody>'+rows.map(function(r){
  var chips=r.levels.map(function(x){return '<span class="chip">'+x+'</span>'}).join("");
  return '<tr><td>'+r.s+'<span class="sub"> '+(r.sec||"")+'</span></td><td>'+r.ltp.toFixed(2)+'</td><td>'+chips+'</td><td>'+(r.break_pct==null?"-":sg(r.break_pct)+"%")+'</td><td>'+r.rvol.toFixed(1)+'x</td><td class="'+cl(r.vs_vwap*(r.side))+'">'+sg(r.vs_vwap)+'%</td><td class="'+cl(r.rs)+'">'+sg(r.rs)+'%</td><td class="'+cl(r.acc2)+'">'+sg(r.acc2)+'%</td><td>'+(r.opt_spread==null?"-":r.opt_spread.toFixed(1)+"%")+'</td><td>'+ticks(r.checks)+'</td><td><b>'+r.score+'/6</b></td></tr>'}).join("")+'</tbody></table>'}
function render(){var a=document.getElementById("asof");if(!D||!D.ok){a.textContent=(D&&D.error)||"loading...";return}
 var m=D.market,min=Number(document.getElementById("min").value);a.textContent="Live to "+D.updated+" - "+m.n+" stocks";
 document.getElementById("banner").innerHTML='<span>median stock <span class="big '+cl(m.median)+'">'+sg(m.median)+'%</span></span><span>stocks down <span class="big">'+m.pct_down.toFixed(0)+'%</span></span><span>breakouts <span class="big g">'+D.n_breakouts+'</span></span><span>breakdowns <span class="big r">'+D.n_breakdowns+'</span></span>';
 document.getElementById("up").innerHTML=table(D.breakouts,min);document.getElementById("dn").innerHTML=table(D.breakdowns,min)}
function load(){fetch("/api/breakouts",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){D=d;render()}).catch(function(){document.getElementById("asof").textContent="connection lost - retrying"})}
document.getElementById("min").onchange=render;load();setInterval(load,5000);
</script></body></html>"""
