"""HTML of the Stock Study page (see stock_study.py): every F&O stock's pattern today and its personality. Plain JS, no external libraries."""

HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Stock Study</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{--bg:#05080f;--panel:#0a111d;--line:#17324a;--text:#e6edf9;--muted:#7d8fab;--g:#27e39a;--r:#ff4d5e;--gold:#ffb454;--c:#22e6ff}
*{box-sizing:border-box}html,body{background:var(--bg)!important;color:var(--text);margin:0;font:12.5px/1.35 "Segoe UI",Arial,sans-serif}
#ss{padding:10px 14px 26px;max-width:1700px;margin:0 auto}h1{font-size:15px;letter-spacing:.2em;margin:8px 0 2px;text-transform:uppercase}.sub{color:var(--muted);font-size:11.5px}
.ctl{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:10px 0;color:var(--muted)}.ctl select,.ctl input{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:5px;padding:4px 7px}
.mix{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 10px}.pill{border:1px solid var(--line);background:var(--panel);border-radius:14px;padding:3px 10px;cursor:pointer;font-size:11.5px}.pill.on{border-color:var(--c);color:var(--c)}
table{width:100%;border-collapse:collapse}th,td{padding:4px 6px;border-bottom:1px solid #112238;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
th{color:var(--muted);font-size:10px;letter-spacing:.08em;text-transform:uppercase;font-weight:600;cursor:pointer;position:sticky;top:44px;background:var(--bg)}td:first-child,th:first-child{text-align:left}td:first-child{font-weight:800}
.g{color:var(--g)}.r{color:var(--r)}.pat{display:inline-block;padding:0 6px;border-radius:3px;font-size:10px;font-weight:800;border:1px solid var(--c);color:var(--c)}
.pat.TREND_UP,.pat.REVERSAL_UP,.pat.GAP_AND_GO{border-color:#14634f;color:var(--g)}.pat.TREND_DOWN,.pat.REVERSAL_DOWN,.pat.GAP_FADE{border-color:#6a2230;color:var(--r)}.pat.TIGHT_RANGE,.pat.RANGE_BOUND,.pat.CHOPPY{border-color:var(--line);color:var(--muted)}
.strip{display:inline-flex;gap:2px}.strip i{width:8px;height:12px;border-radius:2px;display:block;background:#2a3a55}.strip i.TREND_UP,.strip i.REVERSAL_UP,.strip i.GAP_AND_GO{background:#1f9b76}.strip i.TREND_DOWN,.strip i.REVERSAL_DOWN,.strip i.GAP_FADE{background:#b13a4a}.strip i.LATE_SURGE{background:var(--gold)}
.mixbar{display:inline-flex;width:110px;height:10px;border-radius:3px;overflow:hidden;background:#1a2640;vertical-align:middle}.mixbar b{display:block;height:100%}
.note{color:var(--muted);font-size:11px;margin-top:10px;max-width:1200px}
</style></head><body><div id="ss"><h1>Stock study: patterns and personality</h1><div class="sub" id="asof">loading...</div>
<div class="ctl"><label>Search <input id="q" size="10" placeholder="symbol"></label><label>Sector <select id="sec"><option value="">all</option></select></label><span id="count"></span></div>
<div class="mix" id="pills"></div>
<table><thead><tr><th data-k="s">Stock</th><th data-k="sec">Sector</th><th data-k="pat">Today</th><th data-k="move">Move</th><th data-k="range">Range</th><th data-k="gap">Gap</th><th>Today's path</th><th data-k="beta">Beta</th><th data-k="avgr">Avg range</th><th data-k="orb">ORB holds</th><th data-k="hh">Day high hour</th><th>Pattern mix (last 60 days)</th><th>Last 15 days</th></tr></thead><tbody id="rows"></tbody></table>
<div class="note">Each day the 5-minute closes of every stock are classified: TREND (closes at the extreme and pushes through the first-hour range), REVERSAL (a V or inverted V after an early extreme), GAP_AND_GO / GAP_FADE, LATE_SURGE, RANGE_BOUND, TIGHT_RANGE, CHOPPY.
Beta = how much the stock moves for a 1% move of the median stock; ORB holds = how often a break of the first 15 minutes' range is still beyond it at the close; the mix and strip show how the stock usually behaves. The study is descriptive: a stock's history of behaviour is not a prediction.</div></div><script>
var D=null,sortK="move",sortD=-1,PAT=null,COL={TREND_UP:"#1f9b76",TREND_DOWN:"#b13a4a",REVERSAL_UP:"#2fc79c",REVERSAL_DOWN:"#e05a6a",GAP_AND_GO:"#4f8cff",GAP_FADE:"#8a6cff",LATE_SURGE:"#ffb454",RANGE_BOUND:"#3a4c6b",TIGHT_RANGE:"#2a3a55",CHOPPY:"#5b6b88"};
function sg(n,d){n=Number(n);return (n>0?"+":"")+n.toFixed(d==null?2:d)}function cl(n){return n>0?"g":n<0?"r":""}
function spark(a,c){if(!a||a.length<3)return"";var mn=Math.min.apply(null,a),mx=Math.max.apply(null,a),w=90,h=22,p=a.map(function(v,i){return (i*w/(a.length-1)).toFixed(1)+","+(h-(v-mn)/(mx-mn||1)*h).toFixed(1)}).join(" ");return '<svg width="'+w+'" height="'+h+'"><polyline points="'+p+'" fill="none" stroke="'+c+'" stroke-width="1.4"/></svg>'}
function mixbar(m){var o="";Object.keys(COL).forEach(function(k){if(m[k])o+='<b title="'+k+" "+m[k]+'%" style="width:'+m[k]+'%;background:'+COL[k]+'"></b>'});return '<span class="mixbar">'+o+'</span>'}
function rowsOf(){var q=document.getElementById("q").value.toUpperCase(),sec=document.getElementById("sec").value,out=[];
 Object.keys(D.stocks).forEach(function(s){var r=D.stocks[s],t=r.today;if(q&&s.indexOf(q)<0)return;if(sec&&r.sec!==sec)return;if(PAT&&t.pattern!==PAT)return;
  out.push({s:s,sec:r.sec,pat:t.pattern,move:+t.move_pct,range:+t.range_pct,gap:+t.gap_pct,beta:r.beta==null?-9:r.beta,avgr:r.avg_range,orb:r.orb_follow==null?-1:r.orb_follow,hh:r.hi_hour==null?0:r.hi_hour,r:r})});
 out.sort(function(a,b){var x=a[sortK],y=b[sortK];return (x>y?1:x<y?-1:0)*sortD});return out}
function render(){var a=document.getElementById("asof");if(!D||!D.ok){a.textContent=(D&&D.error)||"loading...";return}
 a.textContent="Latest day "+D.day+" - "+Object.keys(D.stocks).length+" stocks - "+D.days+" days of history";
 var secs={};Object.keys(D.stocks).forEach(function(s){secs[D.stocks[s].sec]=1});var sel=document.getElementById("sec");if(sel.options.length<2){Object.keys(secs).sort().forEach(function(k){if(k){var o=document.createElement("option");o.value=k;o.textContent=k;sel.appendChild(o)}})}
 var cnt={};Object.keys(D.stocks).forEach(function(s){var p=D.stocks[s].today.pattern;cnt[p]=(cnt[p]||0)+1});
 document.getElementById("pills").innerHTML='<span class="pill'+(PAT?"":" on")+'" data-p="">all</span>'+D.patterns.map(function(p){return '<span class="pill'+(PAT===p?" on":"")+'" data-p="'+p+'">'+p.replace("_"," ")+" "+(cnt[p]||0)+'</span>'}).join("");
 var rows=rowsOf();document.getElementById("count").textContent=rows.length+" shown";
 document.getElementById("rows").innerHTML=rows.map(function(x){var r=x.r,t=r.today,c=t.move_pct>=0?"#27e39a":"#ff4d5e";
  return '<tr><td>'+x.s+'</td><td class="sub">'+x.sec+'</td><td><span class="pat '+x.pat+'">'+x.pat.replace("_"," ")+'</span></td><td class="'+cl(x.move)+'">'+sg(x.move)+'%</td><td>'+x.range.toFixed(2)+'%</td><td class="'+cl(x.gap)+'">'+sg(x.gap)+'%</td><td>'+spark(r.spark,c)+'</td><td>'+(r.beta==null?"-":r.beta.toFixed(2))+'</td><td>'+x.avgr.toFixed(2)+'%</td><td>'+(r.orb_follow==null?"-":r.orb_follow+"%")+'</td><td>'+(r.hi_hour==null?"-":r.hi_hour+":00")+'</td><td>'+mixbar(r.mix)+'</td><td><span class="strip">'+r.strip.map(function(p){return '<i class="'+p+'" title="'+p+'"></i>'}).join("")+'</span></td></tr>'}).join("")}
function load(){fetch("/api/stock-study",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){D=d;render()}).catch(function(){document.getElementById("asof").textContent="connection lost"})}
document.getElementById("q").oninput=render;document.getElementById("sec").onchange=render;
document.getElementById("pills").onclick=function(e){var p=e.target.getAttribute&&e.target.getAttribute("data-p");if(p!==null&&p!==undefined){PAT=p||null;render()}};
document.querySelector("thead").onclick=function(e){var k=e.target.getAttribute("data-k");if(!k)return;if(sortK===k)sortD=-sortD;else{sortK=k;sortD=-1}render()};
load();
</script></body></html>"""
