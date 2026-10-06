"""HTML for the APlus Control Room page (served at /control-room)."""

CONTROL_ROOM_HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>APlus Control Room</title>
<style>
:root{--bg:#0b1020;--panel:#121a2d;--muted:#8ea0bd;--text:#e7eefc;--green:#17c964;--red:#f31260;--amber:#f5a524;--line:#27334d;--blue:#38bdf8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}
a{color:inherit;text-decoration:none}
.top{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between}
.title{font-size:22px;font-weight:700}.nav a{display:inline-block;margin:2px 4px 2px 0;padding:7px 12px;border:1px solid var(--line);border-radius:9px;font-weight:700;font-size:13px;background:var(--panel)}
.nav a.cur{border-color:#22d3ee;background:#0f2730;color:#9ffcff}
.wrap{padding:16px 20px;max-width:1500px;margin:0 auto}
.banner{padding:14px 16px;border-radius:12px;border:1px solid var(--line);background:var(--panel);font-size:16px;font-weight:600;margin-bottom:14px}
.banner.ok{border-color:#1f7a4a}.banner.warn{border-color:var(--amber)}.banner.bad{border-color:var(--red)}
.grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));margin-bottom:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}
.label{color:var(--muted);font-size:12px}.value{font-size:19px;font-weight:700;margin-top:4px}.detail{color:var(--muted);font-size:12px;margin-top:3px;min-height:15px}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:7px;background:#64748b}
.dot.ok{background:var(--green)}.dot.warn{background:var(--amber)}.dot.bad{background:var(--red)}
h2{font-size:15px;margin:18px 0 8px;color:#cfe0ff;letter-spacing:.3px}
.two{display:grid;gap:14px;grid-template-columns:1fr 1fr}@media(max-width:900px){.two{grid-template-columns:1fr}}
.bar{display:flex;align-items:center;gap:8px;margin:6px 0;font-size:13px}.bar .name{width:190px;color:var(--muted)}.bar .track{flex:1;background:#0f1729;border-radius:6px;height:16px;overflow:hidden}
.bar .fill{height:100%;background:linear-gradient(90deg,#2563eb,#38bdf8)}.bar .num{width:44px;text-align:right;font-weight:700}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);font-size:13px;text-align:left;white-space:nowrap}th{color:var(--muted);background:#0f1729;font-weight:600}
td.r,th.r{text-align:right}.pos{color:var(--green)}.neg{color:var(--red)}.muted{color:var(--muted)}
.note{color:var(--amber);font-size:13px;margin:6px 0}
.chip{display:inline-block;margin:3px 6px 3px 0;padding:5px 10px;border-radius:999px;background:#0f1729;border:1px solid var(--line);font-size:12px}
.scroll{overflow-x:auto}svg{width:100%;height:150px;background:var(--panel);border:1px solid var(--line);border-radius:12px}
</style></head><body>
<div class="top"><div class="title">APlus Control Room</div>
<div class="nav"><a href="/">Live Trading</a><a class="cur" href="/control-room">Control Room</a><a href="/fno-market-watch">F&amp;O Market Watch</a><a href="/stock-analysis">Stock Analysis</a><a href="/sector-performance">Sector Performance</a><a href="/paper-history">Paper History</a></div>
<div class="muted" id="stamp">loading...</div></div>
<div class="wrap">
<div id="banner" class="banner">Loading...</div>
<h2>System health</h2><div id="health" class="grid"></div>
<div class="two"><div><h2>Signal funnel (latest cycle)</h2><div id="funnel"></div><div id="reasons"></div></div>
<div><h2>Top movers</h2><div id="leaders"></div><h2>Safety blocks</h2><div id="safety" class="muted">none</div></div></div>
<h2>Open positions</h2><div id="posnote" class="note"></div><div class="scroll"><table><thead><tr><th>Symbol</th><th>Side</th><th class="r">Entry</th><th class="r">Last</th><th class="r">P&amp;L</th><th class="r">Stop</th><th class="r">To stop</th><th class="r">Held</th><th class="r">Mark age</th></tr></thead><tbody id="pos"></tbody></table></div>
<h2>Performance after costs (valid trades since 28 Aug)</h2><div id="kpis" class="grid"></div>
<div id="curve"></div>
<div class="two"><div><h2>By exit reason</h2><div class="scroll"><table id="byexit"></table></div></div><div><h2>By entry hour</h2><div class="scroll"><table id="byhour"></table></div></div></div>
<h2>By direction</h2><div class="scroll"><table id="bydir"></table></div>
<p class="muted" style="margin-top:18px">Read-only view of the scanner's own files. Refreshes every 10 s.</p>
</div>
<script>
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const inr=n=>(n<0?"-":"")+"₹"+Math.abs(Math.round(Number(n)||0)).toLocaleString("en-IN");
const sg=n=>Number(n)>=0?"pos":"neg";
const $=id=>document.getElementById(id);
function hold(m){if(m==null)return "-";return m>=60?Math.floor(m/60)+"h "+(m%60)+"m":m+"m";}
function table(rows,cols){return "<thead><tr>"+cols.map(c=>"<th class='"+(c.r?"r":"")+"'>"+esc(c.h)+"</th>").join("")+"</tr></thead><tbody>"+
 (rows.length?rows.map(r=>"<tr>"+cols.map(c=>"<td class='"+(c.r?"r ":"")+(c.cls?c.cls(r):"")+"'>"+esc(c.f(r))+"</td>").join("")+"</tr>").join(""):"<tr><td colspan='"+cols.length+"' class='muted'>no data</td></tr>")+"</tbody>";}
function render(d){
 $("stamp").textContent="updated "+d.generated_at.slice(11,19)+" IST";
 const m=d.market||{},h=d.health||{},f=d.funnel||{},p=d.positions||{},pf=d.performance||{};
 const dg=f.diagnosis||"";
 const lvl=(h.overall==="bad"||dg.startsWith("The scanner has not")||dg.startsWith("Trading is blocked"))?"bad":(h.overall==="warn"?"warn":"ok");
 $("banner").className="banner "+lvl;$("banner").textContent=(m.state||"?")+" - "+(dg||m.note||"");
 let cards="<div class='card'><div class='label'>Market</div><div class='value'><span class='dot "+(m.state==="OPEN"?"ok":"warn")+"'></span>"+esc(m.state)+"</div><div class='detail'>"+esc(m.note)+"</div></div>";
 (h.items||[]).forEach(i=>{cards+="<div class='card'><div class='label'>"+esc(i.key)+"</div><div class='value'><span class='dot "+esc(i.level)+"'></span>"+esc(i.value)+"</div><div class='detail'>"+esc(i.detail)+"</div></div>";});
 if(h.regime){const r=h.regime;cards+="<div class='card'><div class='label'>Market trend (NIFTY / VIX)</div><div class='value'>"+esc(r.regime)+"</div><div class='detail'>NIFTY "+esc(r.nifty_pct_prev)+"% vs prev, VIX "+esc(r.vix)+"</div></div>";}
 $("health").innerHTML=cards;
 const steps=f.steps||[],mx=Math.max(1,...steps.map(s=>s.value||0));
 $("funnel").innerHTML=steps.map(s=>"<div class='bar'><div class='name'>"+esc(s.label)+"</div><div class='track'><div class='fill' style='width:"+(100*(s.value||0)/mx)+"%'></div></div><div class='num'>"+(s.value==null?"-":s.value)+"</div></div>").join("");
 $("reasons").innerHTML=(f.rejection_reasons&&f.rejection_reasons.length)?"<div class='muted' style='margin-top:8px'>A+ filter rejections</div>"+f.rejection_reasons.map(r=>"<span class='chip'>"+esc(r.reason.replace("A_PLUS_WAIT_","").split("_").join(" ").toLowerCase())+" <b>"+r.count+"</b></span>").join(""):"";
 $("leaders").innerHTML=(f.leaders||[]).map(l=>"<span class='chip'><b>"+esc(l.symbol)+"</b> "+esc(l.direction)+" "+esc(l.score)+" <span class='muted'>"+esc(String(l.stage||"").split("_").join(" ").toLowerCase())+"</span></span>").join("")||"<span class='muted'>none</span>";
 $("safety").innerHTML=(f.safety_block_reasons&&f.safety_block_reasons.length)?f.safety_block_reasons.map(r=>"<span class='chip'>"+esc(r.reason)+" <b>"+r.count+"</b></span>").join(""):"none this cycle";
 $("posnote").textContent=p.note||"";
 $("pos").innerHTML=(p.rows||[]).map(r=>"<tr><td><b>"+esc(r.symbol)+"</b></td><td>"+esc(r.side)+"</td><td class='r'>"+esc(r.entry)+"</td><td class='r'>"+esc(r.last)+"</td><td class='r "+sg(r.pnl)+"'>"+inr(r.pnl)+"</td><td class='r'>"+esc(r.stop)+"</td><td class='r'>"+(r.stop_distance_pct==null?"-":esc(r.stop_distance_pct)+"%")+"</td><td class='r'>"+hold(r.held_min)+"</td><td class='r'>"+(r.mark_age_s==null?"-":esc(r.mark_age_s)+"s")+"</td></tr>").join("")||"<tr><td colspan='9' class='muted'>no open positions</td></tr>";
 if(!pf.n){$("kpis").innerHTML="<div class='card muted'>No valid trade history yet.</div>";$("curve").innerHTML="";return;}
 const k=(l,v,c,dtl)=>"<div class='card'><div class='label'>"+l+"</div><div class='value "+(c||"")+"'>"+v+"</div><div class='detail'>"+(dtl||"")+"</div></div>";
 $("kpis").innerHTML=k("Net after costs",inr(pf.net),sg(pf.net),"gross "+inr(pf.gross)+" - costs "+inr(pf.costs))+k("Trades",pf.n,"",pf.win_pct+"% win")+
  k("Profit factor",pf.profit_factor==null?"-":pf.profit_factor,pf.profit_factor>=1?"pos":"neg","avg win "+inr(pf.avg_win)+" / loss "+inr(pf.avg_loss))+k("Expectancy / trade",inr(pf.expectancy),sg(pf.expectancy))+k("Max drawdown",inr(-pf.max_drawdown),"neg");
 const c=pf.curve||[];if(c.length>1){const lo=Math.min(0,...c),hi=Math.max(0,...c),W=1000,H=150,x=i=>i*W/(c.length-1),y=v=>H-8-(v-lo)/(hi-lo||1)*(H-16);
  $("curve").innerHTML="<svg viewBox='0 0 "+W+" "+H+"' preserveAspectRatio='none'><line x1='0' x2='"+W+"' y1='"+y(0)+"' y2='"+y(0)+"' stroke='#334155' stroke-dasharray='4'/><polyline fill='none' stroke='#38bdf8' stroke-width='2' points='"+c.map((v,i)=>x(i).toFixed(1)+","+y(v).toFixed(1)).join(" ")+"'/></svg>";}
 const cols=[{h:"Group",f:r=>r.name},{h:"Trades",r:1,f:r=>r.n},{h:"Win %",r:1,f:r=>r.win_pct},{h:"Net",r:1,f:r=>inr(r.net),cls:r=>sg(r.net)},{h:"PF",r:1,f:r=>r.pf==null?"-":r.pf}];
 $("byexit").innerHTML=table(pf.by_exit||[],cols);$("byhour").innerHTML=table(pf.by_hour||[],cols);$("bydir").innerHTML=table(pf.by_direction||[],cols);
}
async function load(){try{const r=await fetch("/api/control-room?ts="+Date.now());render(await r.json());}catch(e){$("banner").className="banner bad";$("banner").textContent="Dashboard could not reach its own API: "+e;}}
load();setInterval(load,10000);
</script></body></html>
'''
