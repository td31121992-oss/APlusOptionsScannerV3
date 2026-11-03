"""HTML of the Candle Story page (see candle_story.py): pick a stock, read its last candles in words. Plain JS, no external libraries."""

HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Candle Story</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{--bg:#05080f;--panel:#0a111d;--line:#17324a;--text:#e6edf9;--muted:#7d8fab;--g:#27e39a;--r:#ff4d5e;--gold:#ffb454;--c:#22e6ff}
*{box-sizing:border-box}html,body{background:var(--bg)!important;color:var(--text);margin:0;font:12.5px/1.35 "Segoe UI",Arial,sans-serif}
#cs{padding:10px 14px 26px;max-width:1700px;margin:0 auto}h1{font-size:15px;letter-spacing:.2em;margin:8px 0 2px;text-transform:uppercase}.sub{color:var(--muted);font-size:11.5px}
.grid{display:grid;grid-template-columns:430px 1fr;gap:12px;margin-top:10px}.box{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px 10px}
.ctl{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px}.ctl input,.ctl select{background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:5px;padding:4px 7px}
.list{max-height:78vh;overflow:auto}.row{display:flex;justify-content:space-between;gap:8px;padding:5px 6px;border-bottom:1px solid #112238;cursor:pointer}.row:hover,.row.on{background:#0f1c30}.row b{font-weight:800}
.tag{display:inline-block;padding:0 6px;border-radius:3px;font-size:10px;font-weight:800;border:1px solid var(--line);color:var(--muted);white-space:nowrap}.tag.b{border-color:#14634f;color:var(--g)}.tag.s{border-color:#6a2230;color:var(--r)}
h2{margin:0 0 6px;font-size:12px;letter-spacing:.14em;text-transform:uppercase}#detail svg{width:100%;height:330px;display:block;background:#07101c;border-radius:6px}
table{width:100%;border-collapse:collapse;margin-top:8px}th,td{padding:4px 6px;border-bottom:1px solid #112238;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}th{color:var(--muted);font-size:10px;text-transform:uppercase;font-weight:600}td:first-child,th:first-child{text-align:left}
.story{font-size:14px;margin:6px 0 8px}.note{color:var(--muted);font-size:11px;margin-top:10px;max-width:1100px}@media(max-width:1100px){.grid{grid-template-columns:1fr}}
</style></head><body><div id="cs"><h1>Candle story</h1><div class="sub" id="asof">loading...</div>
<div class="grid"><div class="box"><div class="ctl"><input id="q" size="9" placeholder="symbol"><select id="f"><option value="">all stories</option><option value="bull">bullish stories</option><option value="bear">bearish stories</option><option value="seq">sequence stories only</option></select></div><div class="list" id="list"></div></div>
<div class="box" id="detail"><div class="sub">choose a stock</div></div></div>
<div class="note">Each 5-minute candle is read from its body, wicks, volume against the last six candles, buyer-minus-seller volume and its place against the previous day's high / low, the first-hour range and the day's extremes. The story is the multi-candle picture when there is one
(pullback and resume, base break, breakout retest, exhaustion), else the last candle's meaning. It is descriptive: the nightly review measures whether any label actually leads anywhere, and so far no chart pattern has shown an edge by itself.</div></div><script>
var D=null,SEL=null;function cl(l){return D.bull.indexOf(l)>=0?"b":D.bear.indexOf(l)>=0?"s":""}function nice(l){return (l||"").replace(/_/g," ").toLowerCase()}
function listHtml(){var q=document.getElementById("q").value.toUpperCase(),f=document.getElementById("f").value,rows=[];
 Object.keys(D.stocks).forEach(function(s){var r=D.stocks[s],c=cl(r.story);if(q&&s.indexOf(q)<0)return;if(f==="bull"&&c!=="b")return;if(f==="bear"&&c!=="s")return;if(f==="seq"&&!(r.candles.length&&r.candles[r.candles.length-1].story))return;rows.push([s,r,c])});
 rows.sort(function(a,b){var x=(a[2]?1:0),y=(b[2]?1:0);return y-x||(a[0]<b[0]?-1:1)});
 return rows.map(function(x){return '<div class="row'+(x[0]===SEL?" on":"")+'" data-s="'+x[0]+'"><b>'+x[0]+'</b><span><span class="tag '+x[2]+'">'+nice(x[1].story)+'</span></span></div>'}).join("")||'<div class="sub">none</div>'}
function chart(r){var c=r.candles;if(!c.length)return"";var W=800,H=330,P=34,hi=Math.max.apply(null,c.map(function(x){return x.h})),lo=Math.min.apply(null,c.map(function(x){return x.l})),lv=[r.vwap,r.pdh,r.pdl,r.ib_hi,r.ib_lo].filter(function(v){return v});
 lv.forEach(function(v){if(v>hi*1.01||v<lo*0.99)return;hi=Math.max(hi,v);lo=Math.min(lo,v)});var y=function(v){return P+(hi-v)/(hi-lo||1)*(H-2*P)},w=(W-2*P)/c.length,o="";
 [[r.vwap,"VWAP","#ffb454"],[r.pdh,"PDH","#8a6cff"],[r.pdl,"PDL","#8a6cff"],[r.ib_hi,"IB hi","#4f8cff"],[r.ib_lo,"IB lo","#4f8cff"]].forEach(function(l){if(l[0]&&l[0]<=hi&&l[0]>=lo)o+='<line x1="'+P+'" x2="'+(W-P)+'" y1="'+y(l[0])+'" y2="'+y(l[0])+'" stroke="'+l[2]+'" stroke-dasharray="4 3" opacity=".6"/><text x="'+(W-P+2)+'" y="'+(y(l[0])+3)+'" fill="'+l[2]+'" font-size="9">'+l[1]+'</text>'});
 c.forEach(function(k,i){var x=P+i*w+w/2,up=k.c>=k.o,col=up?"#27e39a":"#ff4d5e";o+='<line x1="'+x+'" x2="'+x+'" y1="'+y(k.h)+'" y2="'+y(k.l)+'" stroke="'+col+'"/><rect x="'+(x-w*.32)+'" y="'+Math.min(y(k.o),y(k.c))+'" width="'+(w*.64)+'" height="'+Math.max(1.5,Math.abs(y(k.o)-y(k.c)))+'" fill="'+col+'"/>';
  if(k.lab&&["INDECISION","DRIFT_UP","DRIFT_DOWN","FLAT"].indexOf(k.lab)<0)o+='<text x="'+x+'" y="'+(y(k.h)-4)+'" text-anchor="middle" font-size="8" fill="#9db0d2" transform="rotate(-50 '+x+' '+(y(k.h)-4)+')">'+nice(k.lab)+'</text>';
  o+='<text x="'+x+'" y="'+(H-8)+'" text-anchor="middle" font-size="9" fill="#7d8fab">'+k.t+'</text>'});return '<svg viewBox="0 0 '+W+' '+H+'">'+o+'</svg>'}
function detail(){if(!SEL||!D.stocks[SEL]){return}var r=D.stocks[SEL];document.getElementById("detail").innerHTML='<h2>'+SEL+' <span class="tag '+cl(r.story)+'">'+nice(r.story)+'</span></h2><div class="story">Last candle: <b>'+nice(r.last)+'</b>'+(r.vwap?' &middot; VWAP '+r.vwap:"")+' &middot; price '+r.ltp+'</div>'+chart(r)+
 '<table><thead><tr><th>Candle</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th><th>Buyers - sellers</th><th>Reads as</th><th>Story</th></tr></thead><tbody>'+r.candles.slice().reverse().map(function(k){return '<tr><td>'+k.t+'</td><td>'+k.o+'</td><td>'+k.h+'</td><td>'+k.l+'</td><td>'+k.c+'</td><td>'+k.v.toLocaleString("en-IN")+'</td><td class="'+(k.d>0?"g":"r")+'">'+(k.d>0?"+":"")+Math.round(k.d*100)+'%</td><td><span class="tag '+cl(k.lab)+'">'+nice(k.lab)+'</span></td><td>'+(k.story?'<span class="tag '+cl(k.story)+'">'+nice(k.story)+'</span>':"")+'</td></tr>'}).join("")+'</tbody></table>'}
function render(){var a=document.getElementById("asof");if(!D||!D.ok){a.textContent=(D&&D.error)||"loading...";return}a.textContent="Live to "+D.updated+" - "+Object.keys(D.stocks).length+" stocks";document.getElementById("list").innerHTML=listHtml();detail()}
function load(){fetch("/api/candle-story",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){D=d;render()}).catch(function(){document.getElementById("asof").textContent="connection lost - retrying"})}
document.getElementById("q").oninput=function(){if(D&&D.ok)document.getElementById("list").innerHTML=listHtml()};document.getElementById("f").onchange=function(){if(D&&D.ok)document.getElementById("list").innerHTML=listHtml()};
document.getElementById("list").onclick=function(e){var n=e.target.closest(".row");if(n){SEL=n.getAttribute("data-s");render()}};
load();setInterval(load,10000);
</script></body></html>"""
