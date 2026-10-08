"""Mobile-first "Positions" panel that looks like a broker app (Zerodha / Dhan / Upstox style) for the paper trades.

Served by the dashboard at /positions and fed by /api/snapshot every few seconds. It is PAPER data and says so on screen;
it only displays, it has no buttons that act on anything.
"""

POSITIONS_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>APlus Positions</title>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b1020">
<style>
:root{--bg:#0b1020;--panel:#121a2d;--panel2:#18223a;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--green:#2ecc71;--red:#ff6363;--blue:#4c8dff}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--text);font:15px/1.35 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:560px;margin:0 auto;padding:0 14px calc(90px + env(safe-area-inset-bottom))}
header{position:sticky;top:0;z-index:5;background:var(--bg);padding:14px 0 10px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line)}
header h1{font-size:20px;margin:0;font-weight:800}.badge{background:#2a3350;color:#9fb3ff;border-radius:999px;padding:3px 10px;font-size:12px;font-weight:800;letter-spacing:.4px}
.sub{color:var(--muted);font-size:12px}
.summary{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:16px;padding:16px;margin:14px 0}
.summary .big{font-size:34px;font-weight:800;margin:2px 0 6px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px;margin-top:8px}
.grid div span{display:block;color:var(--muted);font-size:12px}.grid div b{font-size:16px}
.pos{color:var(--green)}.neg{color:var(--red)}
.tabs{display:flex;gap:8px;margin:6px 0 12px}.tab{flex:1;text-align:center;padding:9px 6px;border:1px solid var(--line);border-radius:10px;background:var(--panel);color:var(--muted);font-weight:700;font-size:14px;cursor:pointer}
.tab.on{background:var(--blue);border-color:var(--blue);color:#fff}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:13px 14px;margin-bottom:10px}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.name{font-weight:800;font-size:16px}.tag{font-size:11px;font-weight:800;border-radius:6px;padding:2px 6px;margin-left:6px;vertical-align:middle}
.tag.buy{background:#12351f;color:var(--green)}.tag.sell{background:#3a1717;color:var(--red)}.tag.mis{background:#2a3350;color:#9fb3ff}
.pnl{font-weight:800;font-size:19px;white-space:nowrap}.small{color:var(--muted);font-size:12.5px}.mid{margin:7px 0 4px}
.detail{display:none;margin-top:9px;padding-top:9px;border-top:1px dashed var(--line);font-size:12.5px;color:var(--muted)}.card.open .detail{display:block}
.detail div{display:flex;justify-content:space-between;padding:2px 0}.detail b{color:var(--text);font-weight:600}
.by{font-weight:700;color:#9fb3ff;margin-top:1px}.foot{text-align:center;color:var(--muted);font-size:12px;padding:18px 0 6px}.foot b{color:var(--text)}
.empty{text-align:center;color:var(--muted);padding:40px 0}
nav{position:fixed;left:0;right:0;bottom:0;background:#0e1527;border-top:1px solid var(--line);display:flex;justify-content:space-around;padding:8px 0 calc(8px + env(safe-area-inset-bottom))}
nav a{color:var(--muted);text-decoration:none;font-size:12px;font-weight:700;text-align:center;flex:1}nav a.on{color:var(--blue)}
</style></head><body><div class="wrap">
<header><div><h1>Positions</h1><div class="sub" id="asof">loading...</div><div class="sub by">Managed by Mr. Darpan Bobhate</div></div><span class="badge">PAPER</span></header>
<div class="summary"><div class="sub">Total P&amp;L (today)</div><div class="big" id="total">-</div>
<div class="grid"><div><span>Open P&amp;L</span><b id="openpnl">-</b></div><div><span>Closed P&amp;L</span><b id="closedpnl">-</b></div>
<div><span>Capital deployed</span><b id="cap">-</b></div><div><span>Win rate (closed)</span><b id="wr">-</b></div></div></div>
<div class="tabs"><div class="tab on" data-t="OPEN" id="tOPEN">Open</div><div class="tab" data-t="CLOSED" id="tCLOSED">Closed</div><div class="tab" data-t="ALL" id="tALL">All</div></div>
<div id="list"></div>
<div class="foot">APlus Software &middot; Managed by <b>Mr. Darpan Bobhate</b><br>(F&amp;O Trader with 7 years of experience)</div>
</div>
<nav><a href="/" >Dashboard</a><a href="/positions" class="on">Positions</a><a href="/control-room">Control room</a><a href="/alerts">Alerts</a></nav>
<script>
var tab="OPEN",data=null,openIds={};
function inr(n,d){n=Number(n)||0;return(n<0?"-":"")+"₹"+Math.abs(n).toLocaleString("en-IN",{minimumFractionDigits:d==null?2:d,maximumFractionDigits:d==null?2:d})}
function cls(n){return Number(n)>=0?"pos":"neg"}
function sgn(n){n=Number(n)||0;return(n>0?"+":"")+n.toFixed(2)}
function expiry(e){if(!e)return"";var m=["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"],p=String(e).slice(0,10).split("-");return p.length==3?(p[2]+" "+m[Number(p[1])-1]):""}
function render(){
 if(!data)return;var rows=data.rows||[];
 var open=rows.filter(function(x){return x.status==="OPEN"}),closed=rows.filter(function(x){return x.status==="CLOSED"});
 var t=document.getElementById("total");t.textContent=inr(data.total_pnl);t.className="big "+cls(data.total_pnl);
 var o=document.getElementById("openpnl");o.textContent=inr(data.open_pnl);o.className=cls(data.open_pnl);
 var c=document.getElementById("closedpnl");c.textContent=inr(data.closed_pnl);c.className=cls(data.closed_pnl);
 document.getElementById("cap").textContent=inr(data.capital,0);document.getElementById("wr").textContent=(data.win_rate||0)+"%";
 document.getElementById("asof").textContent=(data.trading_day||"")+", "+(data.trading_date||"")+" - updated "+(data.updated_at||"");
 document.getElementById("tOPEN").textContent="Open ("+open.length+")";document.getElementById("tCLOSED").textContent="Closed ("+closed.length+")";
 ["OPEN","CLOSED","ALL"].forEach(function(k){document.getElementById("t"+k).className="tab"+(tab===k?" on":"")});
 var show=tab==="OPEN"?open:tab==="CLOSED"?closed:rows;
 if(!show.length){document.getElementById("list").innerHTML='<div class="empty">No '+(tab==="ALL"?"":tab.toLowerCase()+" ")+'positions</div>';return}
 document.getElementById("list").innerHTML=show.map(function(x){
  var bull=/BULL/i.test(x.side||""),opt=(String(x.side||"").split(" ").pop()||""),pnl=Number(x.pnl)||0,isOpen=x.status==="OPEN";
  var label=x.symbol+" "+(x.strike?String(Number(x.strike)):"")+" "+opt;
  var exp=expiry(x.expiry),qty=Number(x.qty)||0;
  var last=isOpen?x.last:(x.exit_price||x.last);
  return '<div class="card'+(openIds[x.id]?" open":"")+'" data-id="'+x.id+'">'
  +'<div class="row"><div><span class="name">'+label+'</span><span class="tag buy">BUY</span><span class="tag mis">MIS</span></div><div class="pnl '+cls(pnl)+'">'+inr(pnl)+'</div></div>'
  +'<div class="small">'+(exp?exp+" expiry - ":"")+(bull?"bullish view":"bearish view")+(isOpen?"":" - "+(x.exit_reason||"closed"))+'</div>'
  +'<div class="row mid"><div class="small">Qty <b style="color:var(--text)">'+qty.toLocaleString("en-IN")+'</b> &nbsp; Avg <b style="color:var(--text)">'+Number(x.entry).toFixed(2)+'</b></div>'
  +'<div class="small">'+(isOpen?"LTP":"Exit")+' <b style="color:var(--text)">'+Number(last).toFixed(2)+'</b> <span class="'+cls(x.return_pct)+'">('+sgn(x.return_pct)+'%)</span></div></div>'
  +'<div class="row small"><div>'+(x.sl?'SL '+Number(x.sl).toFixed(2):'')+(x.tp?' &nbsp; Target '+Number(x.tp).toFixed(2):'')+'</div><div>'+(x.entry_time||"")+(x.exit_time&&x.exit_time!=="-"?" - "+x.exit_time:"")+' &nbsp; '+(x.duration||"")+'</div></div>'
  +'<div class="detail"><div><a href="/trade?id='+encodeURIComponent(x.id)+'" style="color:var(--blue);font-weight:800;text-decoration:none">Open stock + option charts &rsaquo;</a></div><div><span>Highest since entry</span><b>'+(x.high?Number(x.high).toFixed(2):"-")+' '+(x.high_time||"")+'</b></div>'
  +'<div><span>Lowest since entry</span><b>'+(x.low?Number(x.low).toFixed(2):"-")+' '+(x.low_time||"")+'</b></div>'
  +'<div><span>Capital</span><b>'+inr(x.capital,0)+'</b></div><div><span>Setup</span><b>'+(x.setup||"-")+'</b></div></div></div>'}).join("")
}
document.getElementById("list").addEventListener("click",function(e){var c=e.target.closest(".card");if(!c)return;var id=c.getAttribute("data-id");openIds[id]=!openIds[id];c.classList.toggle("open")});
document.querySelector(".tabs").addEventListener("click",function(e){var t=e.target.getAttribute("data-t");if(t){tab=t;render()}});
function load(){fetch("/api/snapshot",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){data=d;render()}).catch(function(){document.getElementById("asof").textContent="connection lost - retrying"})}
load();setInterval(load,5000);
</script></body></html>
"""
