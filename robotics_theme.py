"""AI / robotics look for every dashboard page (LOOK ONLY: no data, no trading logic).

A layer on top of the compact skin (dashboard_skin.py for the main page, page_skin.py for the rest): a dark blueprint grid with a slow scan beam, cyan HUD accents, corner brackets on
cards, a "core" brand mark in the menu bar and a few honest status chips (dashboard core online / offline from /api/mode, PAPER or LIVE mode, in-session or off-hours by the IST clock,
and the IST time). Nothing on the page claims anything the software does not do.

    inject(html)       add the theme to a full html page (once; pages on a light palette are left alone)
    "AI theme" button  in the menu bar switches it on and off (remembered in the browser: aplus_theme = std turns it off); "Classic view" turns it off with the compact skin.
    Animations stop for people who ask their system for reduced motion.
"""

from __future__ import annotations

import re

CSS = """<style id="aplus-robo-css">
html.compact.robo{--rc:#22e6ff;--rc2:#27e3b0;--rl:rgba(34,230,255,.22);background:#04070f!important}
html.compact.robo body{background:transparent!important}
html.compact.robo body::before{content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;background:
 radial-gradient(900px 520px at 10% -8%,rgba(34,230,255,.11),transparent 62%),radial-gradient(820px 520px at 100% 0,rgba(90,120,255,.10),transparent 60%),
 linear-gradient(rgba(34,230,255,.04) 1px,transparent 1px) 0 0/46px 46px,linear-gradient(90deg,rgba(34,230,255,.04) 1px,transparent 1px) 0 0/46px 46px;animation:roboGrid 70s linear infinite}
html.compact.robo body::after{content:"";position:fixed;left:0;right:0;top:0;height:140px;z-index:-1;pointer-events:none;background:linear-gradient(180deg,transparent,rgba(34,230,255,.05),transparent);animation:roboBeam 12s linear infinite}
@keyframes roboGrid{to{background-position:0 0,0 0,0 46px,46px 0}}
@keyframes roboBeam{from{transform:translateY(-160px)}to{transform:translateY(100vh)}}
@keyframes roboSpin{to{transform:rotate(360deg)}}
@keyframes roboPulse{0%,100%{opacity:.55;transform:scale(.85)}50%{opacity:1;transform:scale(1)}}
@keyframes roboSweep{from{background-position:-300px 0}to{background-position:calc(100% + 300px) 0}}
html.compact.robo #aplus-topbar,html.compact.robo #aplus-main-nav{background:rgba(3,7,15,.92)!important;border-bottom:1px solid rgba(34,230,255,.28)!important;box-shadow:0 10px 28px rgba(0,0,0,.55)!important;backdrop-filter:blur(8px)}
html.compact.robo #aplus-topbar::after,html.compact.robo #aplus-main-nav::after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:1px;pointer-events:none;background:linear-gradient(90deg,transparent,#22e6ff,transparent) 0 0/300px 1px no-repeat;animation:roboSweep 6s linear infinite}
html.compact.robo #aplus-topbar a.cur,html.compact.robo #aplus-main-nav>a.cur{color:#c9f8ff!important;box-shadow:inset 0 -2px 0 var(--rc)!important;background:rgba(34,230,255,.08)!important;text-shadow:0 0 10px rgba(34,230,255,.55)}
html.compact.robo #aplus-topbar a:hover,html.compact.robo #aplus-main-nav>a:hover{background:rgba(34,230,255,.09)!important;color:#fff!important}
.robo-brand{display:none;align-items:center;gap:9px;margin-right:12px;padding-right:14px;border-right:1px solid rgba(34,230,255,.2);white-space:nowrap;font-family:Bahnschrift,"Segoe UI Semibold","Segoe UI",sans-serif}
html.compact.robo .robo-brand{display:flex}
.robo-brand b{font-size:15px;letter-spacing:.22em;color:#e9fbff;text-shadow:0 0 14px rgba(34,230,255,.6)}.robo-brand i{font-style:normal;font-size:9.5px;letter-spacing:.26em;color:#5fd8ee}
.robo-core{position:relative;width:20px;height:20px;flex:none}
.robo-core::before{content:"";position:absolute;inset:0;border-radius:50%;border:1.5px solid transparent;border-top-color:#22e6ff;border-bottom-color:#27e3b0;animation:roboSpin 3.2s linear infinite}
.robo-core::after{content:"";position:absolute;inset:6px;border-radius:50%;background:radial-gradient(circle,#e9fbff 0,#22e6ff 55%,transparent 75%);box-shadow:0 0 12px #22e6ff;animation:roboPulse 2.4s ease-in-out infinite}
.robo-chips{display:none;align-items:center;gap:6px;margin-right:8px;font:700 10.5px Bahnschrift,"Segoe UI",sans-serif;letter-spacing:.1em;white-space:nowrap}
html.compact.robo .robo-chips{display:flex}
.robo-chip{display:flex;align-items:center;gap:6px;padding:3px 8px;border:1px solid rgba(34,230,255,.25);border-radius:4px;background:rgba(34,230,255,.05);color:#9fe9f7;font-variant-numeric:tabular-nums}
.robo-chip .d{width:7px;height:7px;border-radius:50%;background:#27e3b0;box-shadow:0 0 8px #27e3b0;animation:roboPulse 2s ease-in-out infinite}
.robo-chip.bad{border-color:rgba(255,77,94,.4);color:#ff9aa6}.robo-chip.bad .d{background:#ff4d5e;box-shadow:0 0 8px #ff4d5e}.robo-chip.warn .d{background:#ffb454;box-shadow:0 0 8px #ffb454}
.robo-chip button{all:unset;cursor:pointer;color:#5fd8ee}.robo-chip button:hover{color:#fff}
html.compact.robo .card,html.compact.robo .panel,html.compact.robo .box,html.compact.robo .sec,html.compact.robo .icard,html.compact.robo .ais-tile,html.compact.robo #ais-entries,html.compact.robo .secs{position:relative;border-color:var(--rl)!important;box-shadow:0 0 0 1px rgba(34,230,255,.04),0 6px 22px rgba(0,0,0,.35)}
html.compact.robo .card::before,html.compact.robo .panel::before,html.compact.robo .box::before,html.compact.robo .icard::before,html.compact.robo .secs::before{content:"";position:absolute;left:-1px;top:-1px;width:11px;height:11px;border-left:2px solid var(--rc);border-top:2px solid var(--rc);border-radius:2px 0 0 0;pointer-events:none;opacity:.85}
html.compact.robo .card::after,html.compact.robo .panel::after,html.compact.robo .box::after,html.compact.robo .icard::after,html.compact.robo .secs::after{content:"";position:absolute;right:-1px;bottom:-1px;width:11px;height:11px;border-right:2px solid var(--rc);border-bottom:2px solid var(--rc);border-radius:0 0 2px 0;pointer-events:none;opacity:.85}
html.compact.robo .card:hover,html.compact.robo .icard:hover{box-shadow:0 0 18px rgba(34,230,255,.22),0 6px 22px rgba(0,0,0,.4)}
html.compact.robo th{color:#7fe9ff!important;background:#07202c!important;border-bottom:1px solid rgba(34,230,255,.28)!important;letter-spacing:.09em}
html.compact.robo tbody tr:hover td{background:rgba(34,230,255,.06)!important}
html.compact.robo h1,html.compact.robo h2,html.compact.robo .title{letter-spacing:.06em;text-shadow:0 0 18px rgba(34,230,255,.25)}
html.compact.robo .label,html.compact.robo .small{letter-spacing:.07em}
html.compact.robo td,html.compact.robo .value,html.compact.robo .pct,html.compact.robo .px,html.compact.robo .big{font-variant-numeric:tabular-nums}
html.compact.robo ::-webkit-scrollbar{width:10px;height:10px}html.compact.robo ::-webkit-scrollbar-track{background:#050a14}html.compact.robo ::-webkit-scrollbar-thumb{background:#12384b;border-radius:6px;border:2px solid #050a14}
@media (prefers-reduced-motion:reduce){html.compact.robo body::before,html.compact.robo body::after,.robo-core::before,.robo-core::after,.robo-chip .d,html.compact.robo #aplus-topbar::after,html.compact.robo #aplus-main-nav::after{animation:none!important}}
html.compact.robo #aplus-topbar,html.compact.robo #aplus-main-nav{flex-wrap:nowrap!important;overflow:visible}
.robo-brand,.robo-chips,.robo-chip{flex:none}
@media (max-width:1700px){.robo-brand i{display:none}}
@media (max-width:1500px){.robo-chips .hide-s{display:none}}
@media (max-width:1250px){.robo-chips #rc-clock{display:none}}
@media (max-width:900px){.robo-chips{display:none!important}}
</style>
<script>(function(){try{if(localStorage.getItem("aplus_theme")!=="std")document.documentElement.classList.add("robo")}catch(e){document.documentElement.classList.add("robo")}})()</script>
"""

JS = """<script id="aplus-robo-js">
(function(){
 var tries=0;
 function ist(){var p={};new Intl.DateTimeFormat("en-GB",{timeZone:"Asia/Kolkata",hour12:false,weekday:"short",hour:"2-digit",minute:"2-digit",second:"2-digit"}).formatToParts(new Date()).forEach(function(x){p[x.type]=x.value});return p}
 function build(){
  var bar=document.getElementById("aplus-topbar")||document.getElementById("aplus-main-nav");
  if(!bar){if(++tries<40)setTimeout(build,150);return}
  if(bar.querySelector(".robo-brand"))return;
  var brand=document.createElement("div");brand.className="robo-brand";brand.innerHTML='<span class="robo-core"></span><b>APLUS</b><i>AI TRADING CORE</i>';bar.insertBefore(brand,bar.firstChild);
  var chips=document.createElement("div");chips.className="robo-chips";
  chips.innerHTML='<span class="robo-chip" id="rc-core"><span class="d"></span>CORE <span id="rc-core-t">...</span></span><span class="robo-chip hide-s" id="rc-mode">MODE <span id="rc-mode-t">-</span></span>'
   +'<span class="robo-chip hide-s" id="rc-sess"><span class="d"></span><span id="rc-sess-t">-</span></span><span class="robo-chip" id="rc-clock">--:--:-- IST</span><span class="robo-chip"><button type="button" id="rc-toggle" title="Switch the AI look on or off">AI THEME</button></span><span class="robo-chip" id="rc-lock" style="display:none"><a href="/logout" style="color:#5fd8ee;text-decoration:none" title="Lock the dashboard">LOCK</a></span>';
  var vb=bar.querySelector(".viewBtn");if(vb)bar.insertBefore(chips,vb);else bar.appendChild(chips);
  document.getElementById("rc-toggle").onclick=function(){var on=!document.documentElement.classList.contains("robo");document.documentElement.classList.toggle("robo",on);try{localStorage.setItem("aplus_theme",on?"ai":"std")}catch(e){}};
  function tick(){var p=ist(),hm=parseInt(p.hour,10)*60+parseInt(p.minute,10),wk=["Sat","Sun"].indexOf(p.weekday)<0,open=wk&&hm>=555&&hm<=930,pre=wk&&hm>=540&&hm<555;
   document.getElementById("rc-clock").textContent=p.hour+":"+p.minute+":"+p.second+" IST";
   var s=document.getElementById("rc-sess"),t=document.getElementById("rc-sess-t");t.textContent=open?"IN SESSION":pre?"PRE-OPEN":"OFF-HOURS";s.className="robo-chip hide-s"+(open?"":pre?" warn":" bad")}
  function core(){fetch("/api/mode",{cache:"no-store"}).then(function(r){if(!r.ok)throw 0;return r.json()}).then(function(j){var c=document.getElementById("rc-core");c.className="robo-chip";document.getElementById("rc-core-t").textContent="ONLINE";
    var m=document.getElementById("rc-mode"),mt=document.getElementById("rc-mode-t"),live=j&&j.mode==="LIVE";mt.textContent=live?"LIVE ARMED":"PAPER";m.className="robo-chip hide-s"+(live?" bad":"")})
   .catch(function(){var c=document.getElementById("rc-core");c.className="robo-chip bad";document.getElementById("rc-core-t").textContent="OFFLINE"})}
  fetch('/api/auth-status',{cache:'no-store'}).then(function(r){return r.json()}).then(function(j){if(j&&j.configured)document.getElementById('rc-lock').style.display=''}).catch(function(){});
  tick();core();setInterval(tick,1000);setInterval(core,20000)}
 if(document.readyState==="complete")build();else window.addEventListener("load",build)})();
</script>
"""


def _is_light(html: str) -> bool:
    return re.search(r"--bg\s*:\s*#(?:fff|ffffff)(?![0-9a-fA-F])", html, flags=re.I) is not None


def inject(html: str) -> str:
    """Add the AI look to a full html page (idempotent; light pages are returned unchanged)."""
    if not isinstance(html, str) or 'id="aplus-robo-css"' in html or "<body" not in html.lower() or _is_light(html):
        return html
    out = html.replace("</head>", CSS + "</head>", 1) if "</head>" in html else CSS + html
    return out.replace("</body>", JS + "</body>", 1) if "</body>" in out else out + JS
