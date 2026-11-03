"""3D View: a read-only page that shows the market and our paper trades in three dimensions (Three.js, served locally from /static/three.min.js).

    /view3d              the page
    /api/view3d          the data behind it (market watch + money flow + today's paper trades); nothing is written anywhere

Three views, switched by tabs:
    Market cloud    every F&O stock is a point: x = move from the open, y = money flow % (buying - selling), z = value traded (log). Colour = direction, size = value traded,
                    gold ring = a stock we traded today.  Rotate with the left mouse button, zoom with the wheel, double-click to reset.
    Sector towers   one tower per sector: height = money flow %, colour = the sector's move from the open.
    Trade towers    one column per paper trade today: height = option gain / loss %, a white tick = the peak gain, a red disc = the stop.
"""

from __future__ import annotations

from typing import Any, Mapping


def _num(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def build(market_watch: Mapping[str, Any], flow: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Merge the three sources into the lists the page draws."""
    fl = {str(s.get("symbol", "")).upper(): s for s in (flow or {}).get("stocks") or []}
    rows = snapshot.get("rows") or []
    traded = {str(r.get("symbol", "")).upper(): r for r in rows}
    stocks = []
    for r in (market_watch or {}).get("rows") or []:
        sym = str(r.get("symbol") or "").upper()
        if not sym:
            continue
        f = fl.get(sym, {})
        t = traded.get(sym)
        stocks.append({"s": sym, "sec": r.get("sector") or "", "mv": round(_num(r.get("from_open_pct")), 2), "ltp": _num(r.get("ltp")), "rp": round(_num(r.get("range_position_pct")), 0),
                       "flow": round(_num(f.get("flow_pct")), 1), "net": round(_num(f.get("net_cr")), 1), "cr": round(_num(f.get("traded_cr")), 1),
                       "traded": bool(t), "side": (str(t.get("side") or "").split(" ")[0] if t else "")})
    sectors = [{"sec": s.get("sector"), "flow": round(_num(s.get("flow_pct")), 1), "net": round(_num(s.get("net_cr")), 1), "chg": round(_num(s.get("chg_pct")), 2),
                "n": int(_num(s.get("stocks"))), "up": int(_num(s.get("up"))), "down": int(_num(s.get("down")))} for s in (flow or {}).get("sectors") or []]
    trades = []
    for r in sorted(rows, key=lambda x: str(x.get("entry_time") or "")):
        entry = _num(r.get("entry"))
        if entry <= 0:
            continue
        trades.append({"s": str(r.get("symbol") or ""), "side": str(r.get("side") or ""), "status": str(r.get("status") or ""), "t": str(r.get("entry_time") or "")[:5],
                       "ret": round((_num(r.get("last")) / entry - 1) * 100, 1), "peak": round((_num(r.get("high")) / entry - 1) * 100, 1) if _num(r.get("high")) > 0 else 0.0,
                       "stop": round((_num(r.get("sl")) / entry - 1) * 100, 1) if _num(r.get("sl")) > 0 else -20.0, "pnl": round(_num(r.get("pnl"))), "reason": str(r.get("exit_reason") or "")})
    return {"ok": True, "as_of": (flow or {}).get("as_of") or "", "stocks": stocks, "sectors": sectors, "trades": trades,
            "market": (flow or {}).get("market") or {}}


HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus 3D View</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><script src="/static/three.min.js"></script>
<style>
:root{--bg:#0a0f1d;--panel:#101828;--line:#1f2b45;--text:#e6edf9;--muted:#8a9bb8;--blue:#4f8cff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:13px/1.4 "Segoe UI",Arial,sans-serif;overflow:hidden}
.bar{display:flex;gap:8px;align-items:center;padding:8px 14px;border-bottom:1px solid var(--line);background:var(--panel)}
button{background:#0e1527;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:6px 12px;font:600 12.5px inherit;cursor:pointer}button.on{background:var(--blue);border-color:var(--blue)}
.sub{color:var(--muted);font-size:12px}#wrap{position:relative;height:calc(100vh - 100px)}canvas{display:block}
#tip{position:absolute;pointer-events:none;display:none;background:rgba(10,15,29,.94);border:1px solid #33466f;border-radius:8px;padding:7px 10px;font-size:12px;max-width:260px;z-index:5}
#info{position:absolute;left:12px;bottom:10px;background:rgba(16,24,40,.88);border:1px solid var(--line);border-radius:10px;padding:8px 12px;font-size:12px;max-width:340px}
#legend{position:absolute;right:12px;top:10px;background:rgba(16,24,40,.88);border:1px solid var(--line);border-radius:10px;padding:8px 12px;font-size:12px}
a{color:var(--blue);text-decoration:none;font-weight:700}
</style></head><body>
<div class="bar"><b>3D View</b><span id="tabs"></span><button id="spin">Auto-rotate</button><button id="reset">Reset view</button><span class="sub" id="meta">loading...</span></div>
<div id="wrap"><canvas id="c"></canvas><div id="tip"></div><div id="legend"></div><div id="info"></div></div>
<script>
var VIEWS=[["cloud","Market cloud"],["sectors","Sector towers"],["trades","Trade towers"]],cur=localStorage.getItem("v3d_view")||"cloud",D=null,spin=false,hover=null,sel=null;
var wrap=document.getElementById("wrap"),cv=document.getElementById("c"),tip=document.getElementById("tip");
var R=new THREE.WebGLRenderer({canvas:cv,antialias:true,alpha:false});R.setPixelRatio(Math.min(2,window.devicePixelRatio||1));R.setClearColor(0x0a0f1d,1);
var scene=new THREE.Scene(),cam=new THREE.PerspectiveCamera(50,1,0.1,1000),grp=new THREE.Group(),rc=new THREE.Raycaster(),mouse=new THREE.Vector2(),pickable=[];
scene.add(grp);scene.add(new THREE.AmbientLight(0xffffff,0.75));var dl=new THREE.DirectionalLight(0xffffff,0.8);dl.position.set(20,40,30);scene.add(dl);
var cam0={th:0.9,ph:1.0,r:70},cs={th:cam0.th,ph:cam0.ph,r:cam0.r},tgt=new THREE.Vector3(0,6,0);
function place(){cam.position.set(tgt.x+cs.r*Math.sin(cs.ph)*Math.sin(cs.th),tgt.y+cs.r*Math.cos(cs.ph),tgt.z+cs.r*Math.sin(cs.ph)*Math.cos(cs.th));cam.lookAt(tgt)}
function size(){var w=wrap.clientWidth,h=wrap.clientHeight;R.setSize(w,h,false);cam.aspect=w/h;cam.updateProjectionMatrix()}
window.addEventListener("resize",size);
var drag=false,lx=0,ly=0,moved=0;
cv.addEventListener("mousedown",function(e){drag=true;lx=e.clientX;ly=e.clientY;moved=0});window.addEventListener("mouseup",function(){drag=false});
window.addEventListener("mousemove",function(e){var b=cv.getBoundingClientRect();mouse.x=((e.clientX-b.left)/b.width)*2-1;mouse.y=-((e.clientY-b.top)/b.height)*2+1;
 if(drag){var dx=e.clientX-lx,dy=e.clientY-ly;moved+=Math.abs(dx)+Math.abs(dy);cs.th-=dx*0.006;cs.ph=Math.max(0.15,Math.min(3.0,cs.ph-dy*0.006));lx=e.clientX;ly=e.clientY}
 var tb=wrap.getBoundingClientRect();tip.style.left=Math.min(e.clientX-tb.left+14,tb.width-270)+"px";tip.style.top=(e.clientY-tb.top+14)+"px"});
cv.addEventListener("wheel",function(e){e.preventDefault();cs.r=Math.max(10,Math.min(220,cs.r*(e.deltaY>0?1.08:0.92)))},{passive:false});
cv.addEventListener("dblclick",function(){cs.th=cam0.th;cs.ph=cam0.ph;cs.r=cam0.r});
cv.addEventListener("click",function(){if(moved>6)return;sel=hover;showInfo()});
function label(text,color,scale){var c=document.createElement("canvas"),g=c.getContext("2d");c.width=256;c.height=64;g.font="600 28px Segoe UI,Arial";g.fillStyle=color||"#c7d3ea";g.textAlign="center";g.textBaseline="middle";g.fillText(text,128,32);
 var t=new THREE.CanvasTexture(c),s=new THREE.Sprite(new THREE.SpriteMaterial({map:t,transparent:true,depthTest:false}));s.scale.set(scale||8,(scale||8)/4,1);return s}
function clear(){while(grp.children.length){var o=grp.children.pop();if(o.geometry)o.geometry.dispose();if(o.material){if(o.material.map)o.material.map.dispose();o.material.dispose()}}pickable=[]}
function col(v,max){var k=Math.max(-1,Math.min(1,v/max)),c=new THREE.Color();if(k>=0)c.setRGB(0.18+0.0*k,0.45+0.5*k,0.30+0.1*k);else c.setRGB(0.45-k*0.55,0.2+k*0.1,0.25+k*0.1);return c}
function line(a,b,c){var g=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(a[0],a[1],a[2]),new THREE.Vector3(b[0],b[1],b[2])]);return new THREE.Line(g,new THREE.LineBasicMaterial({color:c||0x27334d}))}
function fmt(n,d){return (n>0?"+":"")+Number(n).toFixed(d==null?1:d)}
/* ---- views ---- */
function drawCloud(){var S=D.stocks;if(!S.length)return;var mx=Math.max(3,Math.max.apply(null,S.map(function(s){return Math.abs(s.mv)}))),fx=Math.max(30,Math.max.apply(null,S.map(function(s){return Math.abs(s.flow)}))),zc=Math.max.apply(null,S.map(function(s){return Math.log10(s.cr+1)}))||1;
 var W=30,H=24,Z=30;[[-W,0,-Z,W,0,-Z],[-W,0,Z,W,0,Z],[-W,0,-Z,-W,0,Z],[W,0,-Z,W,0,Z]].forEach(function(l){grp.add(line([l[0],-H,l[2]],[l[3],-H,l[5]],0x1f2b45))});
 grp.add(line([-W,0,0],[W,0,0],0x33466f));grp.add(line([0,-H,0],[0,H,0],0x33466f));grp.add(line([0,0,-Z],[0,0,Z],0x33466f));
 var a=label("move from open "+mx.toFixed(0)+"% >","#8aa0c6",11);a.position.set(W+4,0,0);grp.add(a);a=label("money flow % ^","#8aa0c6",11);a.position.set(0,H+3,0);grp.add(a);a=label("value traded >","#8aa0c6",11);a.position.set(0,0,Z+4);grp.add(a);
 S.forEach(function(s,i){var x=s.mv/mx*W,y=Math.max(-1,Math.min(1,s.flow/fx))*H,z=(Math.log10(s.cr+1)/zc*2-1)*Z,r=0.45+Math.min(2.2,Math.sqrt(s.cr)/9);
  var m=new THREE.Mesh(new THREE.SphereGeometry(r,10,8),new THREE.MeshLambertMaterial({color:col(s.mv,mx)}));m.position.set(x,y,z);m.userData={k:"stock",d:s};grp.add(m);pickable.push(m);
  if(s.traded){var ring=new THREE.Mesh(new THREE.TorusGeometry(r+0.8,0.18,8,24),new THREE.MeshBasicMaterial({color:0xf5b942}));ring.position.copy(m.position);ring.lookAt(cam.position);ring.userData={ring:1};grp.add(ring);var l=label(s.s,"#f5b942",8);l.position.set(x,y+r+2.4,z);grp.add(l)}
  else if(Math.abs(s.mv)>=Math.max(2.5,mx*0.6)||Math.abs(s.flow)>=fx*0.7){var l2=label(s.s,"#9db0d2",7);l2.position.set(x,y+r+1.6,z);grp.add(l2)}});
 cam0.r=85;tgt.set(0,0,0);document.getElementById("legend").innerHTML="<b>Market cloud</b><br>x move from open &nbsp; y money flow &nbsp; z value traded<br><span style='color:#2ecc71'>&#9679;</span> up &nbsp;<span style='color:#ff6363'>&#9679;</span> down &nbsp;<span style='color:#f5b942'>&#9711;</span> we traded it"}
function drawSectors(){var S=D.sectors.filter(function(s){return s.n>=1}).sort(function(a,b){return b.flow-a.flow});if(!S.length)return;var cols=Math.ceil(Math.sqrt(S.length*1.6)),mf=Math.max(10,Math.max.apply(null,S.map(function(s){return Math.abs(s.flow)}))),mc=Math.max(1,Math.max.apply(null,S.map(function(s){return Math.abs(s.chg||0)})));
 var gap=7;S.forEach(function(s,i){var cx=(i%cols-(cols-1)/2)*gap,cz=(Math.floor(i/cols)-(Math.ceil(S.length/cols)-1)/2)*gap,h=s.flow/mf*22,ah=Math.max(0.25,Math.abs(h));
  var m=new THREE.Mesh(new THREE.BoxGeometry(4.4,ah,4.4),new THREE.MeshLambertMaterial({color:col(s.chg||0,mc)}));m.position.set(cx,h>=0?ah/2:-ah/2,cz);m.userData={k:"sector",d:s};grp.add(m);pickable.push(m);
  var l=label(s.sec,"#c7d3ea",10);l.position.set(cx,(h>=0?h:0)+2.2,cz);grp.add(l);var v=label(fmt(s.flow)+"%","#8aa0c6",7);v.position.set(cx,(h>=0?h:0)+0.2,cz+3.0);grp.add(v)});
 var fl=new THREE.Mesh(new THREE.PlaneGeometry(cols*gap+6,Math.ceil(S.length/cols)*gap+6),new THREE.MeshBasicMaterial({color:0x101828,side:THREE.DoubleSide}));fl.rotation.x=-Math.PI/2;fl.position.y=-0.02;grp.add(fl);
 cam0.r=70;tgt.set(0,4,0);document.getElementById("legend").innerHTML="<b>Sector towers</b><br>height = money flow % (down = selling)<br>colour = sector move from open"}
function drawTrades(){var T=D.trades;if(!T.length){document.getElementById("info").innerHTML="No paper trades today.";return}var mr=Math.max(20,Math.max.apply(null,T.map(function(t){return Math.max(Math.abs(t.ret),t.peak)}))),cols=Math.min(T.length,8),gap=5.2;
 T.forEach(function(t,i){var cx=(i%cols-(cols-1)/2)*gap,cz=(Math.floor(i/cols)-(Math.ceil(T.length/cols)-1)/2)*gap,h=t.ret/mr*20,ah=Math.max(0.2,Math.abs(h)),c=t.ret>=0?0x2ecc71:0xff6363;
  var m=new THREE.Mesh(new THREE.BoxGeometry(2.6,ah,2.6),new THREE.MeshLambertMaterial({color:c,transparent:t.status!=="OPEN",opacity:t.status==="OPEN"?1:0.72}));m.position.set(cx,h>=0?ah/2:-ah/2,cz);m.userData={k:"trade",d:t};grp.add(m);pickable.push(m);
  var ph=t.peak/mr*20,pk=new THREE.Mesh(new THREE.BoxGeometry(3.2,0.18,3.2),new THREE.MeshBasicMaterial({color:0xffffff}));pk.position.set(cx,ph,cz);grp.add(pk);
  var sh=t.stop/mr*20,sd=new THREE.Mesh(new THREE.CylinderGeometry(1.6,1.6,0.12,20),new THREE.MeshBasicMaterial({color:0xff4d6d}));sd.position.set(cx,sh,cz);grp.add(sd);
  var l=label(t.s,t.status==="OPEN"?"#f5b942":"#c7d3ea",8);l.position.set(cx,Math.max(h,ph)+2.4,cz);grp.add(l);var v=label(fmt(t.ret)+"%",t.ret>=0?"#2ecc71":"#ff8080",6);v.position.set(cx,Math.min(h,0)-1.6,cz)});
 var fl=new THREE.Mesh(new THREE.PlaneGeometry(cols*gap+6,Math.ceil(T.length/cols)*gap+6),new THREE.MeshBasicMaterial({color:0x101828,side:THREE.DoubleSide}));fl.rotation.x=-Math.PI/2;fl.position.y=-0.02;grp.add(fl);
 cam0.r=60;tgt.set(0,2,0);document.getElementById("legend").innerHTML="<b>Trade towers</b> (today)<br>height = option gain / loss %<br>white tick = peak &nbsp; <span style='color:#ff4d6d'>&#9679;</span> stop<br>solid = open, faded = closed"}
function build(keep){clear();hover=null;sel=null;document.getElementById("info").innerHTML="";document.getElementById("tip").style.display="none";if(!D||!D.ok)return;
 if(cur==="cloud")drawCloud();else if(cur==="sectors")drawSectors();else drawTrades();if(!keep){cs.th=cam0.th;cs.ph=cam0.ph;cs.r=cam0.r}}
function describe(o){if(!o)return "";var d=o.d;if(o.k==="stock")return "<b>"+d.s+"</b> "+(d.traded?"("+d.side+" traded) ":"")+"<br>"+d.sec+"<br>move "+fmt(d.mv,2)+"% &nbsp; flow "+fmt(d.flow)+"%<br>net "+fmt(d.net)+" cr of "+d.cr+" cr traded";
 if(o.k==="sector")return "<b>"+d.sec+"</b><br>flow "+fmt(d.flow)+"% (net "+fmt(d.net)+" cr)<br>move "+fmt(d.chg,2)+"% &nbsp; "+d.up+" up / "+d.down+" down of "+d.n;
 return "<b>"+d.s+"</b> "+d.side+" "+d.status.toLowerCase()+" "+d.t+"<br>option "+fmt(d.ret)+"% now, peak "+fmt(d.peak)+"%, stop "+fmt(d.stop)+"%<br>P&amp;L Rs "+Number(d.pnl).toLocaleString("en-IN")+(d.reason&&d.reason!=="-"?"<br>"+d.reason:"")}
function showInfo(){var el=document.getElementById("info");if(!sel){el.innerHTML="";return}var h=describe(sel);if(sel.k==="stock")h+='<br><a href="/chart-lab?symbol='+sel.d.s+'">open chart</a> &nbsp; <a href="/stock-analysis?symbol='+sel.d.s+'">analysis</a>';el.innerHTML=h}
function pick(){rc.setFromCamera(mouse,cam);var hit=rc.intersectObjects(pickable,false)[0];var o=hit?hit.object.userData:null;if(o!==hover){hover=o;tip.style.display=o?"block":"none";tip.innerHTML=describe(o);cv.style.cursor=o?"pointer":"grab"}}
function loop(){requestAnimationFrame(loop);if(spin&&!drag)cs.th+=0.0035;place();if(!drag)pick();grp.children.forEach(function(o){if(o.userData&&o.userData.ring)o.lookAt(cam.position)});R.render(scene,cam)}
function tabs(){document.getElementById("tabs").innerHTML=VIEWS.map(function(v){return '<button data-v="'+v[0]+'" class="'+(v[0]===cur?"on":"")+'">'+v[1]+"</button>"}).join(" ");document.querySelectorAll("#tabs button").forEach(function(b){b.onclick=function(){cur=b.dataset.v;localStorage.setItem("v3d_view",cur);tabs();build(false)}})}
function load(first){fetch("/api/view3d",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){D=d;document.getElementById("meta").textContent=d.ok?(d.stocks.length+" stocks - "+d.sectors.length+" sectors - "+d.trades.length+" trades - flow to "+(d.as_of||"-")):"no data";build(!first)}).catch(function(){document.getElementById("meta").textContent="could not load"})}
document.getElementById("spin").onclick=function(){spin=!spin;this.className=spin?"on":""};document.getElementById("reset").onclick=function(){cs.th=cam0.th;cs.ph=cam0.ph;cs.r=cam0.r};
tabs();size();place();load(true);loop();setInterval(function(){if(!document.hidden&&!drag&&!sel)load(false)},15000);
</script></body></html>"""
