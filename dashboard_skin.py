"""Compact skin for the main dashboard page (look only: no data, no trading logic).

The classic page stacks about 950 px of menus, banners and cards above the trade table. This layer, switched on by default, restyles the same page in place:

  - one sticky menu bar: the main pages stay visible, the rest sit under "More", the current page is highlighted
  - one slim status line: mode, market mood, new-entries state (its controls open on click), day verdict
  - the index tiles in one scrolling row; the sector indices behind a toggle
  - one row of the KPI tiles that matter (Total / Open / Closed P&L, trades, open-closed, win rate, day return)
  - a tighter, sticky-header trade table with a "Columns" menu (your choice is remembered)
  - the watermark, the big title block and the footer are hidden

"Classic view" in the menu bar switches back (remembered in the browser). Every element id the page's own script writes to is left in place.
"""

from __future__ import annotations

HEAD = """<style id="aplus-skin-css">
html.compact{--bg:#0a0f1d;--panel:#101828;--line:#1f2b45;--text:#e6edf9;--muted:#8a9bb8;--accent:#4f8cff}
html.compact body{background:var(--bg);font-size:13px;line-height:1.35}
html.compact .watermark,html.compact .crisp-footer,html.compact .footer,html.compact #ais-meta,html.compact .header .brandrow,html.compact .header .sub{display:none!important}
/* menu bar */
html.compact #aplus-main-nav{position:sticky;top:0;z-index:60;display:flex!important;align-items:center;flex-wrap:nowrap;gap:2px;padding:0 14px!important;margin:0!important;height:44px;background:rgba(10,15,29,.97);border-bottom:1px solid var(--line);backdrop-filter:blur(6px)}
html.compact #aplus-main-nav>a{padding:7px 12px!important;border:0!important;border-radius:8px!important;background:transparent!important;color:#9db0d2!important;font-size:12.5px!important;font-weight:600!important;letter-spacing:.2px;white-space:nowrap}
html.compact #aplus-main-nav>a:hover{background:#16213a!important;color:#fff!important}
html.compact #aplus-main-nav>a.cur{background:#16213a!important;color:#fff!important;box-shadow:inset 0 -2px 0 var(--accent)}
html.compact #aplus-main-nav .moreWrap{position:relative}html.compact #aplus-main-nav .moreBtn{padding:7px 12px;border-radius:8px;background:transparent;border:0;color:#9db0d2;font:600 12.5px inherit;cursor:pointer}
html.compact #aplus-main-nav .moreBtn:hover,html.compact #aplus-main-nav .moreWrap.open .moreBtn{background:#16213a;color:#fff}
html.compact #aplus-main-nav .moreMenu{display:none;position:absolute;left:0;top:38px;min-width:190px;background:#0f1729;border:1px solid var(--line);border-radius:10px;padding:6px;box-shadow:0 12px 30px #000a}
html.compact #aplus-main-nav .moreWrap.open .moreMenu{display:block}
html.compact #aplus-main-nav .moreMenu a{display:block;padding:7px 10px!important;border:0!important;border-radius:7px!important;background:transparent!important;color:#c7d3ea!important;font-size:12.5px!important;font-weight:600!important;text-decoration:none}
html.compact #aplus-main-nav .moreMenu a:hover{background:#16213a!important;color:#fff!important}
html.compact #aplus-main-nav .spacer{flex:1}html.compact #aplus-main-nav .viewBtn{font:600 11.5px inherit;color:#7f92b4;background:transparent;border:1px solid var(--line);border-radius:7px;padding:4px 9px;cursor:pointer}
html.compact #aplus-main-nav .viewBtn:hover{color:#fff;border-color:#33466f}
/* header line */
html.compact .header{padding:6px 16px!important;border:0!important;justify-content:flex-end!important;min-height:0}html.compact .header>div:last-child{font-size:11.5px;color:var(--muted);text-align:right}
/* status strip + index row */
html.compact #aplus-index-strip{padding:8px 14px 2px!important;margin:0!important}
html.compact .ais-top{display:flex!important;flex-wrap:nowrap!important;gap:10px!important;align-items:stretch!important}
html.compact #ais-left{display:flex!important;gap:8px!important;align-items:center;flex:0 0 auto}
html.compact #ais-entries{flex:0 0 auto;padding:5px 10px!important;border-radius:10px!important;max-width:380px;position:relative}
html.compact #ais-entries .ae-row{display:none!important}html.compact #ais-entries.open .ae-row{display:flex!important;position:absolute;left:0;top:100%;z-index:70;background:#0f1729;border:1px solid var(--line);border-radius:10px;padding:8px 10px;margin-top:4px;box-shadow:0 12px 30px #000a;white-space:nowrap}
html.compact #ais-entries .ae-title{cursor:pointer}html.compact #ais-entries .ae-title:after{content:" \\25BE";opacity:.7}
html.compact #ais-entries .ae-pnl{font-size:11.5px}
html.compact #ais-tiles{display:flex!important;flex-wrap:nowrap!important;flex:1 1 0;min-width:0;gap:6px!important;overflow-x:auto;scrollbar-width:thin;align-items:stretch;grid-template-columns:none!important}
html.compact #ais-entries .ae-state,html.compact #ais-entries .ae-pnl{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:340px}
html.compact #ais-tiles .ais-tile,html.compact #ais-sectors .ais-tile{flex:0 0 auto;min-width:118px;padding:5px 9px!important;border-radius:9px!important}
html.compact #ais-verdict{margin:6px 0 0!important;padding:4px 10px!important;font-size:12px!important;border-radius:8px!important}
html.compact #ais-sectors{display:none!important;margin-top:6px!important;gap:6px!important;overflow-x:auto}html.compact #ais-sectors.show{display:flex!important}
html.compact #aplus-index-strip .secBtn{font:600 11.5px inherit;color:#8aa0c6;background:transparent;border:1px solid var(--line);border-radius:7px;padding:3px 9px;cursor:pointer;margin:6px 0 0 6px}
/* KPI row */
html.compact .grid{display:flex!important;flex-wrap:wrap;gap:8px!important;padding:8px 14px!important}
html.compact .grid .card{padding:7px 14px!important;border-radius:10px!important;min-width:104px;background:var(--panel)}
html.compact .grid .card.hid{display:none!important}
html.compact .grid .label{font-size:10.5px!important;text-transform:uppercase;letter-spacing:.5px}html.compact .grid .value{font-size:17px!important;margin-top:2px!important}
html.compact .grid .card:first-child{min-width:150px}html.compact .grid .card:first-child .value{font-size:21px!important}
/* trade table */
html.compact .filterbar{padding:2px 14px 8px!important;position:relative}
html.compact .tablewrap{padding:0 14px 20px!important}
html.compact table{border-radius:10px!important;font-size:12.5px}
html.compact th,html.compact td{padding:6px 9px!important;font-size:12.5px!important}
html.compact th{top:44px!important;z-index:5;font-size:11px!important;text-transform:uppercase;letter-spacing:.4px}
html.compact tr:hover{background:#15203a}
html.compact .colBtn{margin-left:auto;font:600 11.5px inherit;color:#8aa0c6;background:transparent;border:1px solid var(--line);border-radius:7px;padding:4px 9px;cursor:pointer}
html.compact .colMenu{display:none;position:absolute;right:14px;top:34px;z-index:70;background:#0f1729;border:1px solid var(--line);border-radius:10px;padding:8px 10px;box-shadow:0 12px 30px #000a;columns:2;column-gap:18px}
html.compact .colMenu.show{display:block}html.compact .colMenu label{display:block;white-space:nowrap;padding:2px 0;color:#c7d3ea;font-size:12px}
@media(max-width:900px){html.compact #aplus-main-nav{overflow-x:auto}html.compact .ais-top{flex-wrap:wrap!important}}
</style>
<script>(function(){try{if(localStorage.getItem("aplus_view")!=="classic")document.documentElement.className+=" compact"}catch(e){document.documentElement.className+=" compact"}})()</script>
"""

BODY = """<script id="aplus-skin-js">
(function(){
 var compact=document.documentElement.classList.contains("compact");
 function ready(f){if(document.readyState!=="loading")f();else document.addEventListener("DOMContentLoaded",f)}
 ready(function(){
  var nav=document.getElementById("aplus-main-nav");if(!nav)return;
  /* the classic / compact switch is available in both views */
  var btn=document.createElement("button");btn.className="viewBtn";btn.textContent=compact?"Classic view":"Compact view";
  btn.onclick=function(){try{localStorage.setItem("aplus_view",compact?"classic":"compact")}catch(e){}location.reload()};
  if(!compact){btn.style.cssText="float:right;margin:8px 14px;font:600 12px sans-serif;color:#8ea0bd;background:#121a2d;border:1px solid #27334d;border-radius:7px;padding:5px 10px;cursor:pointer";nav.appendChild(btn);return}
  var MAIN=["/","/control-room","/decision-desk","/live-scanner","/journal","/money-flow","/chart-lab"],links=[].slice.call(nav.querySelectorAll(":scope>a")),here=location.pathname;
  var wrap=document.createElement("div");wrap.className="moreWrap";var mb=document.createElement("button");mb.className="moreBtn";mb.innerHTML="More &#9662;";var menu=document.createElement("div");menu.className="moreMenu";wrap.appendChild(mb);wrap.appendChild(menu);
  links.forEach(function(a){var h=a.getAttribute("href")||"";if(h===here||(h!=="/"&&here.indexOf(h)===0))a.classList.add("cur");a.textContent=a.textContent.replace(/\\s+/g," ").trim().toLowerCase().replace(/(^|\\s)\\S/g,function(c){return c.toUpperCase()}).replace("F&o","F&O");
   if(MAIN.indexOf(h)<0){menu.appendChild(a)}});
  var main=links.filter(function(a){return MAIN.indexOf(a.getAttribute("href"))>=0});
  main.sort(function(a,b){return MAIN.indexOf(a.getAttribute("href"))-MAIN.indexOf(b.getAttribute("href"))});main.forEach(function(a){nav.appendChild(a)});
  nav.appendChild(wrap);var sp=document.createElement("span");sp.className="spacer";nav.appendChild(sp);nav.appendChild(btn);
  mb.onclick=function(e){e.stopPropagation();wrap.classList.toggle("open")};document.addEventListener("click",function(){wrap.classList.remove("open")});
  /* new-entries controls open on click */
  var en=document.getElementById("ais-entries");if(en){var t=en.querySelector(".ae-title");if(t)t.onclick=function(e){e.stopPropagation();en.classList.toggle("open")};document.addEventListener("click",function(e){if(!en.contains(e.target))en.classList.remove("open")})}
  /* sector indices behind a toggle */
  var sec=document.getElementById("ais-sectors"),strip=document.getElementById("aplus-index-strip");
  if(sec&&strip){var sb=document.createElement("button");sb.className="secBtn";sb.textContent="Sector indices \\u25BE";sb.onclick=function(){sec.classList.toggle("show");sb.textContent=sec.classList.contains("show")?"Sector indices \\u25B4":"Sector indices \\u25BE"};var v=document.getElementById("ais-verdict");(v||sec).insertAdjacentElement("afterend",sb)}
  /* keep only the KPI tiles that matter */
  ["avg_duration","longest_duration","cap_deployed","open_return"].forEach(function(id){var e=document.getElementById(id);if(e&&e.closest(".card"))e.closest(".card").classList.add("hid")});
  /* trade-table columns menu */
  var table=document.querySelector(".tablewrap table"),bar=document.querySelector(".filterbar");
  if(table&&bar){var heads=[].slice.call(table.querySelectorAll("thead th")).map(function(th){return th.childNodes[0]?(th.childNodes[0].textContent||"").trim()||th.textContent.trim().split("\\n")[0]:th.textContent.trim()});
   var DEF_HIDE=["Date","Duration","Low \\u20B9 (time)","Capital","Q","Clean"],saved=null;try{saved=JSON.parse(localStorage.getItem("aplus_cols"))}catch(e){}
   var hidden=saved||heads.map(function(h,i){return DEF_HIDE.indexOf(h)>=0?i:-1}).filter(function(i){return i>=0});
   var st=document.createElement("style");document.head.appendChild(st);
   function apply(){st.textContent=hidden.map(function(i){return "html.compact .tablewrap table tr>*:nth-child("+(i+1)+"):not([colspan]){display:none}"}).join("\\n");try{localStorage.setItem("aplus_cols",JSON.stringify(hidden))}catch(e){}}
   var cb=document.createElement("button");cb.className="colBtn";cb.textContent="Columns \\u25BE";var cm=document.createElement("div");cm.className="colMenu";
   heads.forEach(function(h,i){if(!h)return;var l=document.createElement("label");var c=document.createElement("input");c.type="checkbox";c.checked=hidden.indexOf(i)<0;c.onchange=function(){hidden=hidden.filter(function(x){return x!==i});if(!c.checked)hidden.push(i);apply()};l.appendChild(c);l.appendChild(document.createTextNode(" "+h));cm.appendChild(l)});
   cb.onclick=function(e){e.stopPropagation();cm.classList.toggle("show")};document.addEventListener("click",function(e){if(!cm.contains(e.target))cm.classList.remove("show")});
   bar.appendChild(cb);bar.appendChild(cm);apply()}
 })})();
</script>
"""


def inject(html: str) -> str:
    """Add the compact skin to the main page html (once)."""
    if not isinstance(html, str) or 'id="aplus-skin-css"' in html:
        return html
    out = html.replace("</head>", HEAD + "</head>", 1) if "</head>" in html else HEAD + html
    return out.replace("</body>", BODY + "</body>", 1) if "</body>" in out else out + BODY
