"""The HTML of the Smart Money Flow page (see smart_flow.py). Plain canvas drawing, no external libraries."""

HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Smart Flow</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{--bg:#05080f;--panel:#0a111d;--line:#17324a;--text:#e6edf9;--muted:#7d8fab;--g:#27e39a;--r:#ff4d5e;--gd:#0f3d33;--rd:#4a1620;--gold:#ffb454}
*{box-sizing:border-box}html,body{background:var(--bg)!important;color:var(--text);margin:0;font:12.5px/1.35 "Segoe UI",Arial,sans-serif}
#sf{padding:10px 14px 24px;max-width:1700px;margin:0 auto}
.cards3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.icard{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:6px 10px;display:grid;grid-template-columns:150px 1fr;gap:8px;min-height:96px}
.icard.up{border-color:#14634f;box-shadow:inset 0 0 22px #0c3a2f55}.icard.dn{border-color:#6a2230;box-shadow:inset 0 0 22px #4a162055}
.iname{font-weight:800;font-size:15px;letter-spacing:.4px}.ichg{font-weight:800}.small{color:var(--muted);font-size:11px}.g{color:var(--g)}.r{color:var(--r)}
.icard canvas{width:100%;height:84px;display:block}
.head{display:flex;align-items:center;gap:18px;flex-wrap:wrap;margin:10px 2px 4px;font-size:11.5px;letter-spacing:.5px;color:var(--muted)}
.head b{font-size:13px;color:var(--text)}.big{font-size:26px;font-weight:800;line-height:1}
.main{display:grid;grid-template-columns:minmax(380px,40%) 1fr;gap:12px;margin-top:6px}
#curves{width:100%;height:560px;display:block;background:var(--panel);border:1px solid var(--line);border-radius:8px}
#dots{width:100%;height:70px;display:block;margin-bottom:6px}
.secs{margin:6px 0 0;border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:6px 8px}
.srow{display:grid;grid-template-columns:110px 1fr 56px;gap:8px;align-items:center;padding:1px 0}
.sname{font-weight:700;font-size:11px;letter-spacing:.3px;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.strack{position:relative;height:8px;background:#0e1828;border-radius:3px}.sfill{position:absolute;top:0;bottom:0;border-radius:3px}.smid{position:absolute;left:50%;top:-1px;bottom:-1px;width:1px;background:#2c4560}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:10px}
.card{position:relative;border:1px solid;border-radius:6px;background:var(--panel);padding:4px 6px;min-height:84px;overflow:hidden}
.card.up{border-color:#14634f;background:linear-gradient(180deg,#0b1f1b,#0a111d)}.card.dn{border-color:#6a2230;background:linear-gradient(180deg,#220d14,#0a111d)}
.card .sym,.mrow .s{color:#9fd0ff;text-decoration:none}.card .sym:hover,.mrow .s:hover{text-decoration:underline}
.card .top{display:flex;justify-content:space-between;align-items:baseline;gap:6px}.card .sym{font-weight:800;font-size:13px}.card .rk{color:var(--muted);font-size:11px;border:1px solid #28405a;border-radius:4px;padding:0 4px}
.card .pct{font-weight:800;font-size:12px}.card canvas{width:100%;height:40px;display:block;margin:2px 0}
.badge{display:inline-block;font-size:10px;font-weight:800;padding:0 5px;border-radius:3px;border:1px solid;margin-right:4px}
.badge.up{color:var(--gold);border-color:#7a5a22;background:#3a2a0e}.badge.dn{color:#ff9db0;border-color:#7a2a3b;background:#3a121b}
.px{position:absolute;right:6px;bottom:5px;background:#e8eef9;color:#05080f;font-weight:800;font-size:11px;padding:0 5px;border-radius:2px}
.flowrow{display:grid;grid-template-columns:minmax(380px,2fr) 1fr 1fr;gap:12px;margin-top:6px}
#flow{width:100%;height:360px;display:block;background:radial-gradient(ellipse at center,#0b1a2b,var(--panel) 70%);border:1px solid var(--line);border-radius:8px}
#flow2{width:100%;height:420px;display:block;background:radial-gradient(ellipse at center,#0b1a2b,var(--panel) 70%);border:1px solid var(--line);border-radius:8px}
#cum{width:100%;height:150px;display:block;background:var(--panel);border:1px solid var(--line);border-radius:8px}
.mrow{display:grid;grid-template-columns:90px 1fr 60px 64px;gap:6px;padding:2px 6px;border-bottom:1px solid #0e1828;font-size:12px}.mrow .s{font-weight:700}
.lab{margin:10px 2px 4px;font-size:11px;letter-spacing:.6px;color:var(--muted);text-transform:uppercase}
.note{color:var(--muted);font-size:11px;margin-top:10px}
@media(max-width:1100px){.cards3{grid-template-columns:1fr}.main{grid-template-columns:1fr}.grid{grid-template-columns:repeat(2,1fr)}}
</style></head><body><div id="sf">
<div class="cards3" id="cards"></div>
<div class="head" id="head">loading...</div>
<div class="lab">Live money flow &middot; green streams flow INTO a sector (net buying today), red streams flow OUT (net selling); thicker stream = more money</div><canvas id="flow"></canvas>
<div class="lab">Stock money flow &middot; the 10 biggest net buyers and 10 biggest net sellers today &middot; click a stock to open its chart in Chart Lab</div><canvas id="flow2"></canvas>
<div class="flowrow"><div><div class="lab">Cumulative net flow today (Rs crore, buying minus selling) &middot; <span class="g">NIFTY</span> / <span style="color:#ffb454">BANK</span> / <span style="color:#6fb3ff">SENSEX</span></div><canvas id="cum"></canvas></div>
<div><div class="lab" id="rlab">Net buying, last 30 min</div><div id="buyers"></div></div><div><div class="lab">Net selling, last 30 min</div><div id="sellers"></div></div></div>
<div class="main"><div><canvas id="dots"></canvas><canvas id="curves"></canvas><div class="secs" id="secs"></div></div>
<div><div class="lab">Top gainers &middot; flow bars = net buying (green) / selling (red) per 5 minutes</div><div class="grid" id="gain"></div>
<div class="lab">Top losers</div><div class="grid" id="lose"></div></div></div>
<div class="note">Flow is estimated from minute-by-minute price ticks and volume (up-tick = buying, down-tick = selling) in Rs crore per 5 minutes: where the traded money is concentrating, not who is buying. Index cards use the index quote with the net flow of the stocks named under each card (index futures are not recorded). CHoCH / BOS come from the 5-minute candles of today. Read-only, not a trade signal.</div>
</div><script>
var D=null;
function sg(n,d){n=Number(n);return (n>0?"+":"")+n.toFixed(d==null?2:d)}function cl(n){return n>0?"g":n<0?"r":""}
function dpr(c){var r=window.devicePixelRatio||1,w=c.clientWidth,h=c.clientHeight;if(c.width!==Math.round(w*r)||c.height!==Math.round(h*r)){c.width=Math.round(w*r);c.height=Math.round(h*r)}var x=c.getContext("2d");x.setTransform(r,0,0,r,0,0);x.clearRect(0,0,w,h);return [x,w,h]}
function bars(c,net,tot){var a=dpr(c),x=a[0],w=a[1],h=a[2],n=net.length;if(!n)return;var mx=Math.max.apply(null,net.map(Math.abs))||1,rh=h/Math.max(n,12);
 for(var i=0;i<n;i++){var v=net[i],bw=Math.abs(v)/mx*(w-2);x.fillStyle=v>=0?"#27e39a":"#ff4d5e";x.globalAlpha=.85;x.fillRect(0,i*rh+.5,Math.max(1,bw),Math.max(1,rh-1.2))}x.globalAlpha=1}
function icard(c){var d=c.chg==null?0:c.chg,pr=c.ltp?Number(c.ltp).toLocaleString("en-IN",{maximumFractionDigits:2}):"-";
 return '<div class="icard '+(d>=0?"up":"dn")+'"><div><div class="iname">'+c.name+'</div><div class="ichg '+cl(d)+'">'+(c.chg==null?"-":sg(d)+"%")+'</div><div class="small">'+pr+'</div><div class="small" style="margin-top:6px">'+c.note+'</div><div class="small '+cl(c.net)+'">net '+sg(c.net,1)+' cr of '+c.cr+'</div></div><canvas data-k="'+c.name+'"></canvas></div>'}
function card(x,up){var s=x.smc||{},b="";if(s.tag)b='<span class="badge '+(s.up?"up":"dn")+'">'+s.tag+' '+(s.up?"&uarr;":"&darr;")+'</span>'+(s.at||"");
 var extra=[];if(s.ob!=null)extra.push("OB "+Math.abs(s.ob)+"% "+(s.ob>=0?"above":"below"));if(s.liq!=null)extra.push("liq "+s.liq+"% ahead");
 return '<div class="card '+(up?"up":"dn")+'"><div class="top"><a class="sym" target="_blank" href="/chart-lab?symbol='+encodeURIComponent(x.s)+'">'+x.s+'</a><span class="pct '+cl(x.chg)+'">'+sg(x.chg)+'%</span><span class="rk">'+x.rank+'</span></div><canvas data-s="'+x.s+'"></canvas><div class="small">'+b+(extra.length?'<span>'+extra.join(" &middot; ")+'</span>':"")+'</div><span class="px">'+x.ltp+'</span></div>'}
function q95(){var v=D.dots.map(Math.abs).sort(function(p,q){return p-q});return v.length?v[Math.floor(v.length*.95)]:2}
function dots(){var c=document.getElementById("dots"),a=dpr(c),x=a[0],w=a[1],h=a[2],L=D.dots.slice().sort(function(p,q){return p-q}),lim=Math.max(2,Math.min(8,Math.ceil(Math.max(Math.abs(L[0]),Math.abs(L[L.length-1])))));
 function px(v){return w/2+Math.max(-lim,Math.min(lim,v))/lim*(w/2-8)}x.strokeStyle="#17324a";x.beginPath();x.moveTo(8,h-12);x.lineTo(w-8,h-12);x.stroke();x.fillStyle="#7d8fab";x.font="10px sans-serif";x.fillText("-"+lim+"%",8,h-1);x.fillText("+"+lim+"%",w-34,h-1);x.fillText("0",w/2-3,h-1);
 var bins={};L.forEach(function(v){var k=Math.round(px(v)/5),n=bins[k]=(bins[k]||0)+1;x.fillStyle=v>=0?"#27e39a":"#ff4d5e";x.beginPath();x.arc(k*5,h-18-(n-1)*5,2.2,0,6.3);x.fill()})}
function curves(){var c=document.getElementById("curves"),a=dpr(c),x=a[0],w=a[1],h=a[2],T=D.times,n=T.length,pl=8,pr=70,pt=10,pb=18,lim=Math.max(2,Math.min(8,Math.ceil(q95())));
 function X(i){return pl+(w-pl-pr)*i/Math.max(1,n-1)}function Y(v){return pt+(h-pt-pb)*(1-(Math.max(-lim,Math.min(lim,v))+lim)/(2*lim))}
 x.strokeStyle="#102338";x.fillStyle="#7d8fab";x.font="10px sans-serif";for(var g=-lim;g<=lim;g+=lim>4?2:1){x.beginPath();x.moveTo(pl,Y(g));x.lineTo(w-pr,Y(g));x.strokeStyle=g===0?"#4a6a8a":"#102338";x.stroke();x.fillText((g>0?"+":"")+g+"%",w-pr+4,Y(g)+3)}
 var step=Math.max(1,Math.ceil(n/8));for(var i=0;i<n;i+=step)x.fillText(T[i],X(i)-12,h-4);
 D.curves.forEach(function(k){var last=k.c[n-1];if(last==null)return;x.beginPath();var st=false;k.c.forEach(function(v,i){if(v==null)return;if(!st){x.moveTo(X(i),Y(v));st=true}else x.lineTo(X(i),Y(v))});x.strokeStyle=last>=0?"rgba(39,227,154,"+(k.top?.9:.16)+")":"rgba(255,77,94,"+(k.top?.9:.16)+")";x.lineWidth=k.top?1.6:.8;x.stroke()});
 x.lineWidth=2.2;var ls=[];D.sectors.forEach(function(s){x.beginPath();s.curve.forEach(function(v,i){i?x.lineTo(X(i),Y(v)):x.moveTo(X(i),Y(v))});x.strokeStyle=s.chg>=0?"#7ff5c9":"#ff9aa6";x.globalAlpha=.55;x.stroke();x.globalAlpha=1;ls.push([Y(s.chg),s.sec])});
 ls.sort(function(p,q){return p[0]-q[0]});for(var j=1;j<ls.length;j++)if(ls[j][0]-ls[j-1][0]<9)ls[j][0]=ls[j-1][0]+9;x.font="9px sans-serif";x.fillStyle="#cfe0f5";ls.forEach(function(p){x.fillText(p[1].slice(0,13),w-pr+4,p[0]+3)});x.lineWidth=1}
function secs(){var mx=Math.max.apply(null,D.sectors.map(function(s){return Math.abs(s.chg)}))||1;document.getElementById("secs").innerHTML=D.sectors.map(function(s){var wd=Math.min(50,Math.abs(s.chg)/mx*50);
 return '<div class="srow"><span class="sname">'+s.sec+'</span><span class="strack"><span class="smid"></span><span class="sfill" style="background:'+(s.chg>=0?"#27e39a":"#ff4d5e")+';'+(s.chg>=0?"left:50%":"right:50%")+';width:'+wd+'%"></span></span><span class="'+cl(s.chg)+'" title="net flow '+sg(s.net,1)+' cr">'+sg(s.chg)+'%</span></div>'}).join("")}
function paint(){document.querySelectorAll("canvas[data-k]").forEach(function(c){var k=D.cards.filter(function(q){return q.name===c.getAttribute("data-k")})[0];if(k)bars(c,k.bars,k.tot)});
 var by={};D.gainers.concat(D.losers).forEach(function(s){by[s.s]=s});document.querySelectorAll("canvas[data-s]").forEach(function(c){var s=by[c.getAttribute("data-s")];if(s)bars(c,s.bars,s.tot)})}
function cum(){var c=document.getElementById("cum"),a=dpr(c),x=a[0],w=a[1],h=a[2],n=D.times.length,pl=6,pr=52,pt=8,pb=16,S=[],cols=["#27e39a","#ffb454","#6fb3ff"];
 D.cards.forEach(function(k){var t=0;S.push(k.bars.map(function(v){t+=v;return t}))});var all=[0];S.forEach(function(s){all=all.concat(s)});var lo=Math.min.apply(null,all),hi=Math.max.apply(null,all);if(hi-lo<1){hi+=.5;lo-=.5}
 function X(i){return pl+(w-pl-pr)*i/Math.max(1,n-1)}function Y(v){return pt+(h-pt-pb)*(1-(v-lo)/(hi-lo))}
 x.strokeStyle="#4a6a8a";x.beginPath();x.moveTo(pl,Y(0));x.lineTo(w-pr,Y(0));x.stroke();x.fillStyle="#7d8fab";x.font="10px sans-serif";x.fillText("0",w-pr+4,Y(0)+3);x.fillText(hi.toFixed(0),w-pr+4,pt+8);x.fillText(lo.toFixed(0),w-pr+4,h-pb);
 var step=Math.max(1,Math.ceil(n/8));for(var i=0;i<n;i+=step)x.fillText(D.times[i],X(i)-12,h-3);
 S.forEach(function(s,j){x.beginPath();s.forEach(function(v,i){i?x.lineTo(X(i),Y(v)):x.moveTo(X(i),Y(v))});x.strokeStyle=cols[j];x.lineWidth=1.8;x.stroke();x.fillStyle=cols[j];x.fillText(sg(s[n-1],0),w-pr+4,Y(s[n-1])+(j-1)*10+3)});x.lineWidth=1}
var FP={},HIT={},FRUN=false,still=/[?&]calm=1/.test(location.search);
function flowDraw(id,items,l1,l2,l3){var c=document.getElementById(id);if(!c||!items.length)return;var a=dpr(c),x=a[0],w=a[1],h=a[2],n=items.length,cx=w/2,cy=h/2,rx=Math.max(120,w/2-150),ry=Math.max(80,h/2-56),
 mx=Math.max.apply(null,items.map(function(s){return Math.abs(s.net)}))||1,P=items.map(function(s,i){var an=-Math.PI/2+i*2*Math.PI/n;return [cx+rx*Math.cos(an),cy+ry*Math.sin(an)]}),fp=FP[id]=FP[id]||[];
 items.forEach(function(s,i){var k=Math.abs(s.net)/mx,col=s.net>=0?"39,227,154":"255,77,94";x.strokeStyle="rgba("+col+","+(.10+.30*k)+")";x.lineWidth=.8+3.2*k;x.beginPath();x.moveTo(cx,cy);x.lineTo(P[i][0],P[i][1]);x.stroke()});
 if(!still)items.forEach(function(s,i){var k=Math.abs(s.net)/mx;if(Math.random()<.04+.55*k)fp.push({i:i,t:0,v:.007+Math.random()*.008,o:(Math.random()-.5)*6})});
 FP[id]=fp=fp.filter(function(p){p.t+=p.v;return p.t<1&&items[p.i]});
 fp.forEach(function(p){var s=items[p.i],q=s.net>=0?p.t:1-p.t,px=cx+(P[p.i][0]-cx)*q,py=cy+(P[p.i][1]-cy)*q+p.o,g=Math.sin(p.t*Math.PI);
  x.fillStyle=s.net>=0?"rgba(127,245,201,"+(.35+.6*g)+")":"rgba(255,140,155,"+(.35+.6*g)+")";x.beginPath();x.arc(px,py,1.6+1.8*g,0,6.3);x.fill()});
 HIT[id]=[];
 items.forEach(function(s,i){var up=s.net>=0,k=Math.abs(s.net)/mx,r=7+9*k,col=up?"#27e39a":"#ff4d5e";x.fillStyle=up?"rgba(39,227,154,.22)":"rgba(255,77,94,.22)";x.beginPath();x.arc(P[i][0],P[i][1],r+4,0,6.3);x.fill();x.fillStyle=col;x.beginPath();x.arc(P[i][0],P[i][1],r,0,6.3);x.fill();
  var left=P[i][0]<cx-10,right=P[i][0]>cx+10;x.textAlign=left?"right":right?"left":"center";var tx=P[i][0]+(left?-r-8:right?r+8:0),ty=P[i][1]+(left||right?0:(P[i][1]<cy?-r-12:r+16));
  x.fillStyle=s.href?"#9fd0ff":"#e6edf9";x.font="700 11px Segoe UI,sans-serif";x.fillText(s.name.slice(0,22),tx,ty-2);x.fillStyle=col;x.font="11px Segoe UI,sans-serif";x.fillText(sg(s.net,1)+" cr  "+sg(s.chg)+"%",tx,ty+11);
  HIT[id].push({x:P[i][0],y:P[i][1],r:r+14,href:s.href})});
 x.textAlign="center";x.fillStyle="#0e2236";x.beginPath();x.arc(cx,cy,34,0,6.3);x.fill();x.strokeStyle="#2c4f73";x.lineWidth=1.5;x.stroke();x.fillStyle="#e6edf9";x.font="800 11px Segoe UI,sans-serif";x.fillText(l1,cx,cy-3);
 x.font="11px Segoe UI,sans-serif";x.fillStyle="#27e39a";x.fillText(l2,cx,cy+10);x.fillStyle="#ff4d5e";x.fillText(l3,cx,cy+22);x.textAlign="left"}
function flow(){if(!D||!D.ok)return;
 flowDraw("flow",D.sectors.map(function(s){return {name:s.sec,net:s.net,chg:s.chg}}),"MARKET",D.breadth.up+" up",D.breadth.down+" down");
 var sf=(D.stockflow||[]).map(function(s){return {name:s.name,net:s.net,chg:s.chg,href:"/chart-lab?symbol="+encodeURIComponent(s.name)}});
 flowDraw("flow2",sf,"STOCKS",sf.filter(function(s){return s.net>=0}).length+" buying",sf.filter(function(s){return s.net<0}).length+" selling")}
function hitAt(id,e){var c=document.getElementById(id),r=c.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top,L=HIT[id]||[];for(var i=0;i<L.length;i++)if(L[i].href&&Math.hypot(L[i].x-mx,L[i].y-my)<=L[i].r)return L[i];return null}
function flowLoop(){if(FRUN)return;FRUN=true;var c2=document.getElementById("flow2");c2.onclick=function(e){var h=hitAt("flow2",e);if(h)window.open(h.href,"_blank")};c2.onmousemove=function(e){c2.style.cursor=hitAt("flow2",e)?"pointer":"default"};
 (function f(){flow();if(!still)requestAnimationFrame(f);else setTimeout(f,15000)})()}
function mlist(id,L){document.getElementById(id).innerHTML=L.length?L.map(function(m){return '<div class="mrow"><a class="s" target="_blank" href="/chart-lab?symbol='+encodeURIComponent(m.s)+'">'+m.s+'</a><span class="small">'+m.sec+'</span><span class="'+cl(m.net)+'">'+sg(m.net,1)+' cr</span><span class="'+cl(m.chg)+'">'+sg(m.chg)+'%</span></div>'}).join(""):'<div class="small">none</div>'}
function render(){if(!D)return;var hd=document.getElementById("head");if(!D.ok){hd.textContent=D.error||"no data";return}
 document.getElementById("cards").innerHTML=D.cards.map(icard).join("");
 hd.innerHTML='<span>LAGGING SECTOR <b>'+D.lag+'</b> <span class="r">'+sg(D.lag_chg)+'%</span></span><span>LEADING SECTOR <b>'+D.lead+'</b> <span class="g">'+sg(D.lead_chg)+'%</span></span><span>BULLISH <span class="big g">'+D.breadth.up+'</span></span><span>BEARISH <span class="big r">'+D.breadth.down+'</span></span><span>flow to '+D.as_of+'</span>';
 document.getElementById("gain").innerHTML=D.gainers.map(function(x){return card(x,true)}).join("");document.getElementById("lose").innerHTML=D.losers.map(function(x){return card(x,false)}).join("");
 document.getElementById("rlab").textContent="Net buying, last "+D.recent_minutes+" min";mlist("buyers",D.buyers);mlist("sellers",D.sellers);cum();flowLoop();
 secs();dots();curves();paint()}
function load(){fetch("/api/smart-flow",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){D=d;render()}).catch(function(){document.getElementById("head").textContent="connection lost - retrying"})}
window.addEventListener("resize",function(){render()});load();setInterval(load,15000);
</script></body></html>"""
