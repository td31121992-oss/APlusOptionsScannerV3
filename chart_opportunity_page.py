"""HTML of the Chart Opportunities page (see chart_opportunity.py). Plain JS, no external libraries."""

HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Chart Opportunities</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{--bg:#05080f;--panel:#0a111d;--line:#17324a;--text:#e6edf9;--muted:#7d8fab;--g:#27e39a;--r:#ff4d5e;--gold:#ffb454;--c:#22e6ff}
*{box-sizing:border-box}html,body{background:var(--bg)!important;color:var(--text);margin:0;font:12.5px/1.35 "Segoe UI",Arial,sans-serif}
#co{padding:10px 14px 26px;max-width:1500px;margin:0 auto}h1{font-size:15px;letter-spacing:.2em;margin:8px 0 2px;text-transform:uppercase}.sub{color:var(--muted);font-size:11.5px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px}.box{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px 10px}
.box h2{margin:0 0 6px;font-size:12px;letter-spacing:.16em;text-transform:uppercase}.box.up h2{color:var(--g)}.box.dn h2{color:var(--r)}.box.up{border-color:#14634f}.box.dn{border-color:#6a2230}
table{width:100%;border-collapse:collapse}th,td{padding:5px 6px;border-bottom:1px solid #112238;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
th{color:var(--muted);font-size:10px;letter-spacing:.08em;text-transform:uppercase;font-weight:600}td:first-child,th:first-child{text-align:left}td:first-child{font-weight:800}
.g{color:var(--g)}.r{color:var(--r)}.chip{display:inline-block;padding:0 5px;margin-left:4px;border-radius:3px;font-size:10px;font-weight:800;border:1px solid var(--gold);color:var(--gold)}
.note{color:var(--muted);font-size:11px;margin-top:10px}@media(max-width:1100px){.cols{grid-template-columns:1fr}}
</style></head><body><div id="co"><h1>Chart opportunities</h1><div class="sub" id="asof">loading...</div>
<div class="cols"><div class="box up"><h2>Calls: charts that look like past big runs</h2><div id="calls"></div></div><div class="box dn"><h2>Puts: charts that look like past big runs</h2><div id="puts"></div></div></div>
<div class="note">Each stock's chart (returns since the open and over 3 / 12 minutes, position in the day's range, opening-range status, trend efficiency, strength against the median stock, market direction and breadth) is scored by a model
trained on 83 days of option history to rank the setups by the chance the at-the-money option runs +100% before a 20% stop. "x median" = the score divided by the median stock's score. TOP 5% / TOP 1% = in the model's own top 5% / 1% of scores on its test days.
In testing the model is a weak ranker, so this shows which charts match past big movers; it is not a trade signal. Updated every 20 seconds from the live tick stream.</div></div><script>
var D=null;function sg(n,d){n=Number(n);return (n>0?"+":"")+n.toFixed(d==null?2:d)}function cl(n){return n>0?"g":n<0?"r":""}
function table(rows){if(!rows||!rows.length)return '<div class="sub">none right now</div>';
 return '<table><thead><tr><th>Stock</th><th>Score</th><th>x median</th><th>Since open</th><th>vs market</th><th>3 min</th><th>12 min</th><th>Range pos</th><th>Opening range</th><th>Efficiency</th></tr></thead><tbody>'+rows.map(function(r){
  var chip=r.top1?'<span class="chip">TOP 1%</span>':(r.top5?'<span class="chip">TOP 5%</span>':"");
  var orr=r.or>0?"beyond, with us":(r.or<0?"beyond, against":"inside");
  return '<tr><td>'+r.s+chip+'</td><td>'+(r.p*100).toFixed(1)+'%</td><td>'+r.x.toFixed(2)+'x</td><td class="'+cl(r.ret_open)+'">'+sg(r.ret_open)+'%</td><td class="'+cl(r.rs)+'">'+sg(r.rs)+'%</td><td class="'+cl(r.d3)+'">'+sg(r.d3)+'%</td><td class="'+cl(r.d12)+'">'+sg(r.d12)+'%</td><td>'+(r.range_pos*100).toFixed(0)+'%</td><td>'+orr+'</td><td>'+r.eff.toFixed(2)+'</td></tr>'}).join("")+'</tbody></table>'}
function render(){var a=document.getElementById("asof");if(!D||!D.ok){a.textContent=(D&&D.error)||"loading...";return}
 a.textContent="Live to "+D.updated+" - "+D.n+" stock/side charts scored - model "+D.version+", test AUC "+D.holdout_auc;
 document.getElementById("calls").innerHTML=table(D.calls);document.getElementById("puts").innerHTML=table(D.puts)}
function load(){fetch("/api/chart-opportunities",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){D=d;render()}).catch(function(){document.getElementById("asof").textContent="connection lost - retrying"})}
load();setInterval(load,5000);
</script></body></html>"""
