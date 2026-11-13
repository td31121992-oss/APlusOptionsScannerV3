"""Smart analysis + drawing tools for Chart Lab (look and read-only analysis: nothing here touches the scanner or any trade).

Everything is calculated in the browser from the candles already on the chart and drawn on a canvas laid over the chart:
    FVG            fair value gaps (3-candle imbalance); open gaps extend to the right until price trades back through them
    Order blocks   the last opposite candle before a structure break; stays until a close goes through it
    BOS / CHoCH    swing structure breaks (continuation / change of character), with the swing level that was broken
    Support / Resistance  zones where swing highs/lows cluster (2+ touches); green below price, red above, darker = more touches
    Liquidity      equal highs / equal lows that price has not swept yet
    Key levels     previous day high / low / close, today's open, today's high / low with the time each was made, opening range (09:15-09:30) high / low
    Volume profile today's volume by price with POC and the 70% value area
    Patterns       engulfing, hammer, shooting star markers
    Order flow     markers on the candles with the heaviest buying / selling delta (needs recorded ticks) and a CVD pane
Drawing tools: horizontal line, trend line, box, fib retracement; saved per stock in this browser (localStorage). Not trade signals.
"""

BAR_HTML = r"""<div class="bar" id="smartbar"><b>Smart analysis</b>
<label class="chip"><input type="checkbox" data-sm="fvg"> FVG</label><label class="chip"><input type="checkbox" data-sm="ob"> Order blocks</label><label class="chip"><input type="checkbox" data-sm="bos"> BOS / CHoCH</label>
<label class="chip"><input type="checkbox" data-sm="sr"> Support / Resistance</label><label class="chip"><input type="checkbox" data-sm="liq"> Liquidity</label><label class="chip"><input type="checkbox" data-sm="lvl"> Key levels</label><label class="chip"><input type="checkbox" data-sm="vp"> Volume profile</label>
<label class="chip"><input type="checkbox" data-sm="pat"> Patterns</label><label class="chip"><input type="checkbox" data-sm="of"> Order-flow markers</label>
<button id="small">All</button><button id="smnone">None</button>
<span style="width:14px"></span><b>Draw</b><button data-tool="hline">H-line</button><button data-tool="trend">Trend line</button><button data-tool="rect">Box</button><button data-tool="fib">Fib</button><button id="dundo">Undo</button><button id="dclear">Clear</button>
<span class="sub" id="dhint"></span></div><div class="sub" id="smnote" style="padding:4px 12px"></div>"""

JS = r"""<script>
var SM={on:Object.assign({fvg:true,ob:false,bos:false,liq:false,sr:false,lvl:false,vp:false,pat:false,of:false},ls("cl_smart")||{}),tool:"",pend:null,draw:[],dsym:"",an:null,key:"",rev:0,sig:"",cv:null,mkFor:null};
function smT(t){if(t&&typeof t==="object"&&t.year)return t.year+"-"+("0"+t.month).slice(-2)+"-"+("0"+t.day).slice(-2);return t}
function smPiv(cs,k,L,R){var i=k-R;if(i-L<0)return null;var hi=true,lo=true;for(var j=i-L;j<=i+R;j++){if(j===i)continue;if(cs[j].h>cs[i].h||(j<i&&cs[j].h===cs[i].h))hi=false;if(cs[j].l<cs[i].l||(j<i&&cs[j].l===cs[i].l))lo=false}return {i:i,hi:hi,lo:lo}}
function smFmt(v){var a=Math.abs(v);return (v<0?"-":"+")+(a>=1e6?(a/1e6).toFixed(1)+"M":a>=1e3?(a/1e3).toFixed(0)+"K":Math.round(a))}
function smAnalyze(cs,daily){var n=cs.length,o={fvg:[],ob:[],ev:[],liq:[],lvl:[],vp:null,pat:[],of:[],note:""};if(n<8)return o;
 for(var i=2;i<n;i++){var a=cs[i-2],b=cs[i-1],c=cs[i];
  if(c.l>a.h&&(c.l-a.h)/c.c>=.0004){var z={up:true,t:b.t,lo:a.h,hi:c.l,i:i-1,end:null,ei:-1};for(var j=i+1;j<n;j++)if(cs[j].l<=z.lo){z.end=cs[j].t;z.ei=j;break}o.fvg.push(z)}
  else if(c.h<a.l&&(a.l-c.h)/c.c>=.0004){var z2={up:false,t:b.t,lo:c.h,hi:a.l,i:i-1,end:null,ei:-1};for(var j2=i+1;j2<n;j2++)if(cs[j2].h>=z2.hi){z2.end=cs[j2].t;z2.ei=j2;break}o.fvg.push(z2)}}
 var open=o.fvg.filter(function(z){return z.ei<0}).slice(-10),done=o.fvg.filter(function(z){return z.ei>=0&&z.ei>=n-60}).slice(-6);o.fvg=done.concat(open);
 var lastH=null,lastL=null,trend=0,ph=[],pl=[];
 for(var k=0;k<n;k++){var pv=smPiv(cs,k,3,3);if(pv){if(pv.hi){lastH={i:pv.i,p:cs[pv.i].h,br:false};ph.push(lastH)}if(pv.lo){lastL={i:pv.i,p:cs[pv.i].l,br:false};pl.push(lastL)}}
  var c2=cs[k].c;
  if(lastH&&!lastH.br&&c2>lastH.p){lastH.br=true;o.ev.push({kind:trend===-1?"CHoCH":"BOS",up:true,i0:lastH.i,i:k,p:lastH.p});trend=1;
   var s0=lastL?lastL.i:Math.max(0,lastH.i-8),best=-1;for(var m=s0;m<k;m++)if(cs[m].c<cs[m].o&&(best<0||cs[m].l<=cs[best].l))best=m;
   if(best>=0){var ob={up:true,t:cs[best].t,lo:cs[best].l,hi:cs[best].h,i:best,end:null};for(var q=k+1;q<n;q++)if(cs[q].c<ob.lo){ob.end=cs[q].t;break}o.ob.push(ob)}}
  if(lastL&&!lastL.br&&c2<lastL.p){lastL.br=true;o.ev.push({kind:trend===1?"CHoCH":"BOS",up:false,i0:lastL.i,i:k,p:lastL.p});trend=-1;
   var s1=lastH?lastH.i:Math.max(0,lastL.i-8),bst=-1;for(var m2=s1;m2<k;m2++)if(cs[m2].c>cs[m2].o&&(bst<0||cs[m2].h>=cs[bst].h))bst=m2;
   if(bst>=0){var ob2={up:false,t:cs[bst].t,lo:cs[bst].l,hi:cs[bst].h,i:bst,end:null};for(var q2=k+1;q2<n;q2++)if(cs[q2].c>ob2.hi){ob2.end=cs[q2].t;break}o.ob.push(ob2)}}}
 o.ob=o.ob.slice(-8);o.evAll=o.ev;o.ev=o.ev.slice(-8);o.trend=trend;
 [[ph,true],[pl,false]].forEach(function(z){var L=z[0],up=z[1],found=[];for(var a=0;a<L.length;a++)for(var b=a+1;b<L.length;b++){if(L[b].i-L[a].i<3)continue;var lv=up?Math.max(L[a].p,L[b].p):Math.min(L[a].p,L[b].p);if(Math.abs(L[a].p-L[b].p)/L[a].p>.0008)continue;
   var swept=false;for(var j3=L[b].i+1;j3<n;j3++)if(up?cs[j3].h>lv:cs[j3].l<lv){swept=true;break}if(!swept)found.push({up:up,t:cs[L[a].i].t,p:lv,label:up?"EQH":"EQL"})}
  o.liq=o.liq.concat(found.slice(-4))});
 o.sr=[];(function(){var lastC=cs[n-1].c,w=cs.slice(-50),atr=w.reduce(function(s,x){return s+(x.h-x.l)},0)/w.length,tol=Math.max(atr*.6,lastC*.0015),pv=ph.concat(pl).map(function(q){return {i:q.i,p:q.p}}).sort(function(a,b){return a.p-b.p}),g=[];
  pv.forEach(function(q){var cur=g[g.length-1];if(cur&&q.p-cur[cur.length-1].p<=tol)cur.push(q);else g.push([q])});
  g.forEach(function(c){if(c.length<2)return;var lo=Math.min.apply(null,c.map(function(q){return q.p})),hi=Math.max.apply(null,c.map(function(q){return q.p})),mid=(lo+hi)/2;if(hi-lo<tol*.5){lo=mid-tol*.25;hi=mid+tol*.25}
   var i0=Math.min.apply(null,c.map(function(q){return q.i})),i1=Math.max.apply(null,c.map(function(q){return q.i}));o.sr.push({lo:lo,hi:hi,n:c.length,t:cs[i0].t,i1:i1,res:mid>lastC})});
  var R=o.sr.filter(function(z){return z.res}).sort(function(a,b){return a.lo-b.lo}).slice(0,3),Sx=o.sr.filter(function(z){return !z.res}).sort(function(a,b){return b.hi-a.hi}).slice(0,3);o.sr=Sx.concat(R)})();
 if(!daily){var days=[],idx={};cs.forEach(function(x,i){if(!(x.day in idx)){idx[x.day]=days.length;days.push({d:x.day,i0:i,i1:i})}days[idx[x.day]].i1=i});var T=days[days.length-1],P=days.length>1?days[days.length-2]:null;
  if(P){var pd=cs.slice(P.i0,P.i1+1);o.lvl.push({p:Math.max.apply(null,pd.map(function(x){return x.h})),label:"PDH",col:"#f5b942"},{p:Math.min.apply(null,pd.map(function(x){return x.l})),label:"PDL",col:"#f5b942"},{p:pd[pd.length-1].c,label:"PDC",col:"#8ea0bd"})}
  var td=cs.slice(T.i0,T.i1+1),orb=td.filter(function(x){return (tnum(x.t)%86400)/60<9*60+30});o.lvl.push({p:td[0].o,label:"Open",col:"#c084fc"});
  if(orb.length){o.lvl.push({p:Math.max.apply(null,orb.map(function(x){return x.h})),label:"OR high",col:"#4c8dff"},{p:Math.min.apply(null,orb.map(function(x){return x.l})),label:"OR low",col:"#4c8dff"})}
  var hiI=0,loI=0;td.forEach(function(x,i){if(x.h>td[hiI].h)hiI=i;if(x.l<td[loI].l)loI=i});function hm(t){return typeof t==="number"?new Date(t*1000).toISOString().slice(11,16):""}
  o.lvl.push({p:td[hiI].h,label:"Day high "+hm(td[hiI].t),col:"#2ecc71",at:td[hiI].t},{p:td[loI].l,label:"Day low "+hm(td[loI].t),col:"#ff6363",at:td[loI].t});o.dayHL={hi:td[hiI].h,hiT:hm(td[hiI].t),lo:td[loI].l,loT:hm(td[loI].t)};
  o.lvlFrom=cs[T.i0].t;
  var lo=Math.min.apply(null,td.map(function(x){return x.l})),hi=Math.max.apply(null,td.map(function(x){return x.h})),B=40,bins=[];for(var u=0;u<B;u++)bins.push(0);var st=(hi-lo)/B||1;
  td.forEach(function(x){var a=Math.max(0,Math.floor((x.l-lo)/st)),b=Math.min(B-1,Math.floor((x.h-lo)/st)),w=x.v/(b-a+1);for(var u2=a;u2<=b;u2++)bins[u2]+=w});
  var tot=bins.reduce(function(p,q){return p+q},0),poc=0;bins.forEach(function(v,i){if(v>bins[poc])poc=i});var a1=poc,b1=poc,acc=bins[poc];
  while(acc<.7*tot&&(a1>0||b1<B-1)){var up1=b1<B-1?bins[b1+1]:-1,dn1=a1>0?bins[a1-1]:-1;if(up1>=dn1){b1++;acc+=bins[b1]}else{a1--;acc+=bins[a1]}}
  o.vp={lo:lo,st:st,bins:bins,poc:poc,val:lo+a1*st,vah:lo+(b1+1)*st,max:bins[poc]}}
 for(var p=Math.max(1,n-80);p<n;p++){var x=cs[p],y=cs[p-1],body=Math.abs(x.c-x.o),rg=x.h-x.l||1e-9,uw=x.h-Math.max(x.c,x.o),lw=Math.min(x.c,x.o)-x.l;
  if(y.c<y.o&&x.c>x.o&&x.o<=y.c&&x.c>=y.o)o.pat.push({t:x.t,up:true,text:"Engulf"});
  else if(y.c>y.o&&x.c<x.o&&x.o>=y.c&&x.c<=y.o)o.pat.push({t:x.t,up:false,text:"Engulf"});
  else if(body/rg<.35&&lw>=2*body&&uw<=.3*rg&&body>0)o.pat.push({t:x.t,up:true,text:"Hammer"});
  else if(body/rg<.35&&uw>=2*body&&lw<=.3*rg&&body>0)o.pat.push({t:x.t,up:false,text:"Star"})}
 var d=S.delta;if(d&&d.bars&&d.bars.length&&S.tf!=="1d"){var dur=DUR[S.tf],bk={};d.bars.forEach(function(b){var t=b.t-(b.t%dur);bk[t]=(bk[t]||0)+b.delta});var arr=cs.map(function(x){return bk[tnum(x.t)]}).filter(function(v){return v!=null}).map(Math.abs).sort(function(a,b){return a-b});
  if(arr.length>=10){var thr=arr[Math.floor(arr.length*.92)];cs.forEach(function(x){var v=bk[tnum(x.t)];if(v!=null&&Math.abs(v)>=thr&&thr>0)o.of.push({t:x.t,v:v})})}}
 var last=cs[n-1].c,bits=[];var ev=o.evAll[o.evAll.length-1];
 bits.push(trend===1?"Structure bullish":trend===-1?"Structure bearish":"No structure break yet");if(ev)bits.push("last "+ev.kind+(ev.up?" up":" down")+" at "+smWhen(cs[ev.i].t)+" (broke "+ev.p.toFixed(2)+")");
 var zs=o.fvg.filter(function(z){return z.ei<0}).map(function(z){return {k:"FVG",z:z}}).concat(o.ob.filter(function(z){return !z.end}).map(function(z){return {k:"OB",z:z}}));
 var below=zs.filter(function(q){return q.z.hi<=last}).sort(function(a,b){return b.z.hi-a.z.hi})[0],above=zs.filter(function(q){return q.z.lo>=last}).sort(function(a,b){return a.z.lo-b.z.lo})[0];
 if(below)bits.push("nearest open "+(below.z.up?"bull ":"bear ")+below.k+" below "+below.z.lo.toFixed(2)+"-"+below.z.hi.toFixed(2));if(above)bits.push("above "+(above.z.up?"bull ":"bear ")+above.k+" "+above.z.lo.toFixed(2)+"-"+above.z.hi.toFixed(2));
 var rs=o.sr.filter(function(z){return z.res})[0],ss=o.sr.filter(function(z){return !z.res})[0];if(ss)bits.push("support "+ss.lo.toFixed(2)+"-"+ss.hi.toFixed(2)+" ("+ss.n+" touches)");if(rs)bits.push("resistance "+rs.lo.toFixed(2)+"-"+rs.hi.toFixed(2)+" ("+rs.n+" touches)");
 if(o.liq.length)bits.push(o.liq.length+" untaken liquidity level(s)");if(o.dayHL)bits.push("today high "+o.dayHL.hi.toFixed(2)+" at "+o.dayHL.hiT+", low "+o.dayHL.lo.toFixed(2)+" at "+o.dayHL.loT);if(o.vp)bits.push("today POC "+(o.vp.lo+(o.vp.poc+.5)*o.vp.st).toFixed(2));
 o.note=bits.join(" · ");return o}
function smWhen(t){return typeof t==="string"?t:new Date(t*1000).toISOString().slice(11,16)}
function smKey(){var cs=S.data[S.tf]||[],last=cs.length?cs[cs.length-1]:{};return [S.sym,S.tf,cs.length,last.c,S.delta?S.delta.bars.length:0].join("|")}
function smMarkers(){if(!S.candle||SM.mkFor===S.candle)return;SM.mkFor=S.candle;var A=SM.an,m=[];if(!A)return;
 if(SM.on.pat)A.pat.forEach(function(p){m.push({time:p.t,position:p.up?"belowBar":"aboveBar",color:p.up?"#2ecc71":"#ff6363",shape:p.up?"arrowUp":"arrowDown",text:p.text})});
 if(SM.on.of)A.of.forEach(function(p){m.push({time:p.t,position:p.v>0?"belowBar":"aboveBar",color:p.v>0?"#7ff5c9":"#ff9aa6",shape:p.v>0?"arrowUp":"arrowDown",text:"Δ"+smFmt(p.v)})});
 m.sort(function(a,b){return tnum(a.time)-tnum(b.time)});try{S.candle.setMarkers(m)}catch(e){}}
function smEnsure(){var cs=S.data[S.tf];if(!cs||!cs.length)return false;var k=smKey();if(k!==SM.key||!SM.an){SM.key=k;SM.an=smAnalyze(cs,S.tf==="1d");SM.mkFor=null;document.getElementById("smnote").textContent=SM.an.note}return true}
function smDrawLoad(){if(SM.dsym!==S.sym){SM.dsym=S.sym;SM.draw=ls("cl_draw_"+S.sym)||[];SM.pend=null}}
function smRedraw(){var main=S.main,cd=S.candle,cs=S.data[S.tf];if(!main||!cd||!cs||!cs.length||!smEnsure())return;smDrawLoad();smMarkers();
 var host=document.getElementById("main"),w=host.clientWidth,h=host.clientHeight,cv=SM.cv;if(!cv||cv.parentNode!==host.parentNode){cv=SM.cv=document.createElement("canvas");cv.style.cssText="position:absolute;left:0;top:0;pointer-events:none;z-index:4";host.parentNode.appendChild(cv)}
 var r=window.devicePixelRatio||1;if(cv.width!==Math.round(w*r)||cv.height!==Math.round(h*r)){cv.width=Math.round(w*r);cv.height=Math.round(h*r);cv.style.width=w+"px";cv.style.height=h+"px"}
 var x=cv.getContext("2d");x.setTransform(r,0,0,r,0,0);x.clearRect(0,0,w,h);
 var ts=main.timeScale(),pw=72;try{pw=main.priceScale("right").width()||72}catch(e){}var RR=w-pw,lr=ts.getVisibleLogicalRange(),A=SM.an;
 function X(t){var v=ts.timeToCoordinate(t);if(v!=null)return v;if(!lr)return null;var i=Math.max(0,Math.min(cs.length-1,Math.round(lr.from)));return tnum(t)<tnum(cs[i].t)?-9999:RR+9999}
 function Y(p){return cd.priceToCoordinate(p)}
 var LB=[];function tag(text,px,py,col,al){x.font="bold 12px Segoe UI,Arial,sans-serif";x.textBaseline="middle";var tw=x.measureText(text).width,bw=tw+10,bh=17,x0=al==="r"?px-bw:al==="c"?px-bw/2:px;x0=Math.max(1,Math.min(RR-bw-1,x0));
  var offs=[0,18,-18,36,-36,54,-54],y0=py-bh/2;for(var k=0;k<offs.length;k++){var yy=py+offs[k]-bh/2,hit=false;for(var j=0;j<LB.length;j++){var q=LB[j];if(x0<q[1]&&x0+bw>q[0]&&yy<q[3]&&yy+bh>q[2]){hit=true;break}}if(!hit){y0=yy;break}}
  LB.push([x0,x0+bw,y0,y0+bh]);x.fillStyle="rgba(10,16,30,.88)";x.fillRect(x0,y0,bw,bh);x.strokeStyle=col;x.lineWidth=1;x.setLineDash([]);x.strokeRect(x0+.5,y0+.5,bw-1,bh-1);x.fillStyle="#f4f7ff";x.textAlign="left";x.fillText(text,x0+5,y0+bh/2+.5);x.textBaseline="alphabetic"}
 function box(t1,lo,hi,t2,fill,stroke,label,dash){var xa=X(t1),xb=t2==null?RR:X(t2),ya=Y(hi),yb=Y(lo);if(xa==null||xb==null||ya==null||yb==null)return;xa=Math.max(0,xa);xb=Math.min(RR,xb);if(xb<=xa)return;x.fillStyle=fill;x.fillRect(xa,ya,xb-xa,Math.max(1,yb-ya));x.strokeStyle=stroke;x.lineWidth=1;x.setLineDash(dash||[]);x.strokeRect(xa+.5,ya+.5,xb-xa,Math.max(1,yb-ya));x.setLineDash([]);if(label)tag(label,xa+4,ya+10,stroke,"l")}
 function hl(p,t1,col,label,dash){var y=Y(p);if(y==null||y<0||y>h)return;var xa=t1==null?0:Math.max(0,X(t1));x.strokeStyle=col;x.lineWidth=1;x.setLineDash(dash||[5,4]);x.beginPath();x.moveTo(xa,y+.5);x.lineTo(RR,y+.5);x.stroke();x.setLineDash([]);if(label)tag(label+" "+p.toFixed(2),RR-4,y-11,col,"r")}
 if(SM.on.fvg)A.fvg.forEach(function(z){var done=z.ei>=0,c=z.up?"46,204,113":"255,99,99";box(z.t,z.lo,z.hi,z.end,"rgba("+c+","+(done?.07:.20)+")","rgba("+c+","+(done?.35:.9)+")",z.up?"FVG":"FVG",done?[2,3]:[])});
 if(SM.on.ob)A.ob.forEach(function(z){var done=!!z.end,c=z.up?"76,141,255":"192,132,252";box(z.t,z.lo,z.hi,z.end,"rgba("+c+","+(done?.08:.24)+")","rgba("+c+","+(done?.4:1)+")",z.up?"OB bull":"OB bear",done?[2,3]:[])});
 if(SM.on.bos)A.ev.forEach(function(e){var y=Y(e.p),xa=X(cs[e.i0].t),xb=X(cs[e.i].t);if(y==null||xa==null||xb==null)return;var col=e.up?"#2ecc71":"#ff6363";x.strokeStyle=col;x.lineWidth=1;x.setLineDash([6,3]);x.beginPath();x.moveTo(Math.max(0,xa),y+.5);x.lineTo(Math.min(RR,xb),y+.5);x.stroke();x.setLineDash([]);
  if(xb>0&&xb<RR){tag(e.kind,(Math.max(0,xa)+Math.min(RR,xb))/2,e.up?y-12:y+12,col,"c")}});
 if(SM.on.sr)A.sr.forEach(function(z){var c=z.res?"255,99,99":"46,204,113",a=Math.min(.32,.10+.05*z.n);box(z.t,z.lo,z.hi,null,"rgba("+c+","+a+")","rgba("+c+",.85)",(z.res?"R x":"S x")+z.n)});
 if(SM.on.liq)A.liq.forEach(function(q){hl(q.p,q.t,q.up?"#ff9f43":"#48dbfb",q.label,[2,3])});
 if(SM.on.lvl)A.lvl.forEach(function(q){hl(q.p,A.lvlFrom,q.col,q.label);if(q.at!=null){var mx=X(q.at),my=Y(q.p);if(mx!=null&&my!=null&&mx>0&&mx<RR){x.fillStyle=q.col;x.beginPath();x.arc(mx,my,3.5,0,6.283);x.fill()}}});
 if(SM.on.vp&&A.vp){var v=A.vp,mw=Math.min(150,RR*.22);v.bins.forEach(function(b,i){var ya=Y(v.lo+(i+1)*v.st),yb=Y(v.lo+i*v.st);if(ya==null||yb==null)return;var inVA=(v.lo+i*v.st)>=v.val-1e-9&&(v.lo+(i+1)*v.st)<=v.vah+1e-9;x.fillStyle=i===v.poc?"rgba(245,185,66,.55)":inVA?"rgba(76,141,255,.30)":"rgba(142,160,189,.22)";var bw=b/v.max*mw;x.fillRect(RR-bw,ya,bw,Math.max(1,yb-ya-1))});
  hl(v.lo+(v.poc+.5)*v.st,null,"#f5b942","POC",[3,3]);hl(v.vah,null,"#4c8dff","VAH",[1,4]);hl(v.val,null,"#4c8dff","VAL",[1,4])}
 SM.draw.concat(SM.pend?[SM.pend]:[]).forEach(function(d){var col="#ffd166";
  if(d.k==="h")hl(d.p,null,col,"",[]);
  else{var xa=X(d.t1),ya=Y(d.p1),xb=d.t2==null?null:X(d.t2),yb=d.t2==null?null:Y(d.p2);if(xa==null||ya==null)return;
   if(d.k==="t"&&xb!=null&&yb!=null){var dx=xb-xa||1,sl=(yb-ya)/dx,xe=RR;x.strokeStyle=col;x.lineWidth=1.6;x.beginPath();x.moveTo(xa,ya);x.lineTo(xe,ya+sl*(xe-xa));x.stroke()}
   else if(d.k==="r"&&xb!=null&&yb!=null){x.fillStyle="rgba(255,209,102,.14)";x.strokeStyle=col;x.lineWidth=1.4;var x1=Math.max(0,Math.min(xa,xb)),x2=Math.min(RR,Math.max(xa,xb));x.fillRect(x1,Math.min(ya,yb),x2-x1,Math.abs(yb-ya));x.strokeRect(x1+.5,Math.min(ya,yb)+.5,x2-x1,Math.abs(yb-ya))}
   else if(d.k==="f"&&xb!=null&&yb!=null){[0,.236,.382,.5,.618,.786,1].forEach(function(lv){var p=d.p1+(d.p2-d.p1)*lv,y=Y(p);if(y==null)return;x.strokeStyle=lv===.5||lv===.618?"#ffd166":"rgba(255,209,102,.55)";x.lineWidth=1;x.beginPath();x.moveTo(Math.max(0,Math.min(xa,xb)),y+.5);x.lineTo(RR,y+.5);x.stroke();x.fillStyle="#ffd166";x.font="bold 12px Segoe UI,Arial,sans-serif";x.textAlign="right";x.fillText(lv+"  "+p.toFixed(2),RR-4,y-2);x.textAlign="left"})}
   else{x.fillStyle=col;x.beginPath();x.arc(xa,ya,4,0,6.3);x.fill()}}})}
function smSig(){if(!S.main||!S.candle)return"";var lr=S.main.timeScale().getVisibleLogicalRange();return (lr?lr.from.toFixed(2)+","+lr.to.toFixed(2):"")+"|"+S.candle.coordinateToPrice(0)+"|"+S.candle.coordinateToPrice(470)+"|"+SM.rev+"|"+(S.main===SM.mainSeen)}
function smClick(p){if(!SM.tool||!p.point||!S.candle)return;var cs=S.data[S.tf];if(!cs||!cs.length)return;var price=S.candle.coordinateToPrice(p.point.y),t=smT(p.time);if(t==null)t=smT(S.main.timeScale().coordinateToTime(p.point.x));if(t==null)t=cs[cs.length-1].t;if(price==null)return;
 var tool=SM.tool;if(tool==="hline"){SM.draw.push({k:"h",p:price});smSave();return}
 if(!SM.pend){SM.pend={k:tool==="trend"?"t":tool==="rect"?"r":"f",t1:t,p1:price,t2:null,p2:null};document.getElementById("dhint").textContent="click the second point";SM.rev++;return}
 SM.pend.t2=t;SM.pend.p2=price;SM.draw.push(SM.pend);SM.pend=null;smSave()}
function smSave(){ls("cl_draw_"+S.sym,SM.draw);SM.rev++;smHint()}
function smHint(){var h={hline:"click on the chart to place a horizontal line",trend:"click two points for a trend line",rect:"click two corners for a box",fib:"click the swing start, then the swing end"};document.getElementById("dhint").textContent=SM.tool?h[SM.tool]+" (click the tool again to stop)":"";
 document.querySelectorAll("#smartbar [data-tool]").forEach(function(b){b.className=b.dataset.tool===SM.tool?"on":""});document.getElementById("main").style.cursor=SM.tool?"crosshair":""}
function addCVD(ind,cs,tag){var d=S.delta;if(!d||!d.bars.length||S.tf==="1d"){newPane("CVD - needs recorded ticks (5m or lower timeframe)");return}
 var dur=DUR[S.tf],bk={};d.bars.forEach(function(b){var t=b.t-(b.t%dur);bk[t]=(bk[t]||0)+b.delta});var ch=newPane("CVD (cumulative delta, resets each day)"),s=ch.addLineSeries({color:ind.col,lineWidth:2,priceLineVisible:false}),acc=0,dd="";
 s.setData(cs.map(function(x){var v=bk[tnum(x.t)];if(x.day!==dd){dd=x.day;acc=0}if(v==null)return {time:x.t};acc+=v;return {time:x.t,value:acc}}))}
(function(){var _render=render;render=function(){_render.apply(null,arguments);try{if(S.main){S.main.subscribeClick(smClick);SM.mainSeen=S.main;SM.mkFor=null;SM.rev++}}catch(e){}};
 document.querySelectorAll("#smartbar [data-sm]").forEach(function(c){c.checked=!!SM.on[c.dataset.sm];c.onchange=function(){SM.on[c.dataset.sm]=c.checked;ls("cl_smart",SM.on);SM.mkFor=null;SM.rev++}});
 function setAll(v){Object.keys(SM.on).forEach(function(k){SM.on[k]=v});document.querySelectorAll("#smartbar [data-sm]").forEach(function(c){c.checked=v});ls("cl_smart",SM.on);SM.mkFor=null;SM.rev++}
 document.getElementById("small").onclick=function(){setAll(true)};document.getElementById("smnone").onclick=function(){setAll(false)};
 document.querySelectorAll("#smartbar [data-tool]").forEach(function(b){b.onclick=function(){SM.tool=SM.tool===b.dataset.tool?"":b.dataset.tool;SM.pend=null;smHint()}});
 document.getElementById("dundo").onclick=function(){smDrawLoad();SM.draw.pop();smSave()};document.getElementById("dclear").onclick=function(){smDrawLoad();SM.draw=[];smSave()};
 (function loop(){var s=smSig();if(s!==SM.sig){SM.sig=s;try{smRedraw()}catch(e){}}requestAnimationFrame(loop)})()})();
</script>"""
