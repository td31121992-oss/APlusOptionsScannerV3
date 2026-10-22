"""The compact look on every page except the main one (look only: no data, no trading logic).

dashboard_skin.py restyles the main page. This gives all the other pages the same menu bar on top (main pages visible, the rest under "More", the current page highlighted),
one palette and tighter tables and cards. The dashboard's request handler passes every HTML page response through filter_response(); anything that is not a full HTML page
(JSON, CSV, images, scripts) is returned untouched. "Classic view" in the bar switches back (the same browser setting as the main page: aplus_view).
"""

from __future__ import annotations

import re

MAIN_LINKS = [("Live Trading", "/"), ("Control Room", "/control-room"), ("Decision Desk", "/decision-desk"), ("Live Scanner", "/live-scanner"), ("Journal", "/journal"),
              ("Money Flow", "/money-flow"), ("Chart Lab", "/chart-lab")]
MORE_LINKS = [("Sectors", "/sector-analysis"), ("Positions", "/positions"), ("F&amp;O Market Watch", "/fno-market-watch"), ("Stock Analysis", "/stock-analysis"), ("Alerts", "/alerts"),
              ("Sector Performance", "/sector-performance"), ("Opening Structure", "/opening-structure"), ("Technical Alerts", "http://127.0.0.1:8766"), ("Stock Charts", "/stock-charts")]

HEAD = """<style id="aplus-skin-css">
html.compact body{font-size:13px;line-height:1.38}
/*PALETTE*/html.compact #aplus-topbar{position:sticky;top:0;z-index:200;display:flex;align-items:center;gap:2px;padding:0 14px;height:44px;background:rgba(10,15,29,.97);border-bottom:1px solid #1f2b45;backdrop-filter:blur(6px);font-family:"Segoe UI",Arial,sans-serif}
html.compact #aplus-topbar a{padding:7px 12px;border-radius:8px;color:#9db0d2;font-size:12.5px;font-weight:600;letter-spacing:.2px;text-decoration:none;white-space:nowrap}
html.compact #aplus-topbar a:hover{background:#16213a;color:#fff}html.compact #aplus-topbar a.cur{background:#16213a;color:#fff;box-shadow:inset 0 -2px 0 #4f8cff}
html.compact #aplus-topbar .moreWrap{position:relative}html.compact #aplus-topbar .moreBtn{padding:7px 12px;border-radius:8px;background:transparent;border:0;color:#9db0d2;font:600 12.5px "Segoe UI",Arial,sans-serif;cursor:pointer}
html.compact #aplus-topbar .moreBtn:hover,html.compact #aplus-topbar .moreWrap.open .moreBtn{background:#16213a;color:#fff}
html.compact #aplus-topbar .moreMenu{display:none;position:absolute;left:0;top:38px;min-width:190px;background:#0f1729;border:1px solid #1f2b45;border-radius:10px;padding:6px;box-shadow:0 12px 30px #000a}
html.compact #aplus-topbar .moreWrap.open .moreMenu{display:block}html.compact #aplus-topbar .moreMenu a{display:block}
html.compact #aplus-topbar .spacer{flex:1}html.compact #aplus-topbar .viewBtn{font:600 11.5px "Segoe UI",Arial,sans-serif;color:#7f92b4;background:transparent;border:1px solid #1f2b45;border-radius:7px;padding:4px 9px;cursor:pointer}
html.compact #aplus-topbar .viewBtn:hover{color:#fff;border-color:#33466f}
html:not(.compact) #aplus-topbar{display:none}html:not(.compact) #aplus-viewfloat{display:block}#aplus-viewfloat{display:none;position:fixed;right:12px;bottom:12px;z-index:300;font:600 12px sans-serif;color:#8ea0bd;background:#121a2d;border:1px solid #27334d;border-radius:7px;padding:6px 10px;cursor:pointer}
html.compact .footer,html.compact .watermark,html.compact .crisp-footer{display:none!important}
html.compact .header{padding:8px 16px!important}html.compact .title{font-size:17px!important}html.compact h1{font-size:18px!important;margin:6px 0 2px!important}html.compact h2{font-size:15px!important}
html.compact .wrap{padding:8px 12px!important}html.compact .tablewrap{padding:0 14px 14px!important}
html.compact .cards,html.compact .grid{gap:8px!important}
html.compact .card{padding:8px 12px!important;border-radius:10px!important}html.compact .card .value,html.compact .value{font-size:18px!important;margin-top:2px!important}html.compact .label{font-size:10.5px!important;text-transform:uppercase;letter-spacing:.4px}
html.compact th,html.compact td{padding:6px 9px!important;font-size:12.5px!important}html.compact th{font-size:11px!important;text-transform:uppercase;letter-spacing:.35px}
html.compact .panel,html.compact .box,html.compact .sec{border-radius:10px!important}
html.compact .bar,html.compact .toolbar,html.compact .filterbar{padding-top:6px!important;padding-bottom:6px!important}
</style>
<script>(function(){try{if(localStorage.getItem("aplus_view")!=="classic")document.documentElement.className+=" compact"}catch(e){document.documentElement.className+=" compact"}})()</script>
"""

JS = """<script id="aplus-skin-js">
(function(){
 function ready(f){if(document.readyState!=="loading")f();else document.addEventListener("DOMContentLoaded",f)}
 ready(function(){
  var bar=document.getElementById("aplus-topbar");if(!bar)return;var here=location.pathname;
  [].slice.call(bar.querySelectorAll("a")).forEach(function(a){var h=a.getAttribute("href")||"";if(h===here||(h!=="/"&&h.charAt(0)==="/"&&here.indexOf(h)===0))a.classList.add("cur")});
  var wrap=bar.querySelector(".moreWrap"),mb=bar.querySelector(".moreBtn");mb.onclick=function(e){e.stopPropagation();wrap.classList.toggle("open")};document.addEventListener("click",function(){wrap.classList.remove("open")});
  function flip(){try{localStorage.setItem("aplus_view",document.documentElement.classList.contains("compact")?"classic":"compact")}catch(e){}location.reload()}
  bar.querySelector(".viewBtn").onclick=flip;document.getElementById("aplus-viewfloat").onclick=flip;
  var known={};[].slice.call(bar.querySelectorAll("a")).forEach(function(a){known[a.getAttribute("href")]=1});
  [].slice.call(document.querySelectorAll("div,nav,p,span")).forEach(function(p){if(p.closest("#aplus-topbar")||p.dataset.aplusChecked)return;p.dataset.aplusChecked="1";
   var as=[].slice.call(p.children).filter(function(c){return c.tagName==="A"});if(as.length<2||as.length<p.children.length-1)return;
   if(as.every(function(x){var h=x.getAttribute("href")||"";return known[h]||h.indexOf("8766")>0}))p.classList.add("aplus-dup")});
  var st=document.createElement("style");st.textContent="html.compact .aplus-dup{display:none!important}";document.head.appendChild(st)
 })})();
</script>
"""


def _topbar(host: str = "127.0.0.1") -> str:
    main = "".join(f'<a href="{h}">{t}</a>' for t, h in MAIN_LINKS)
    more = "".join(f'<a href="{h.replace("127.0.0.1", host)}">{t}</a>' for t, h in MORE_LINKS)
    return (f'<div id="aplus-topbar">{main}<div class="moreWrap"><button class="moreBtn" type="button">More &#9662;</button><div class="moreMenu">{more}</div></div>'
            '<span class="spacer"></span><button class="viewBtn" type="button">Classic view</button></div><button id="aplus-viewfloat" type="button">Compact view</button>')


PALETTE = """html.compact{--bg:#0a0f1d;--panel:#101828;--line:#1f2b45;--text:#e6edf9;--muted:#8a9bb8;--accent:#4f8cff}
html.compact body{background:var(--bg)!important;color:var(--text)}
"""


def _head_for(html: str) -> str:
    """Pages built on a light palette (the alerts page) keep their own colours: they get the menu bar and spacing but not the dark palette."""
    light = re.search(r"--bg\s*:\s*#(?:fff|ffffff)(?![0-9a-fA-F])", html, flags=re.I) is not None
    return HEAD.replace("/*PALETTE*/", "" if light else PALETTE)


def page_skin(html: str, host: str = "127.0.0.1") -> str:
    """Add the shared menu bar and compact styling to a full html page (once)."""
    if not isinstance(html, str) or 'id="aplus-skin-css"' in html or "<body" not in html.lower():
        return html
    m = re.search(r"<body[^>]*>", html, flags=re.I)
    if not m:
        return html
    out = html[: m.end()] + _topbar(host) + html[m.end():]
    head = _head_for(html)
    out = out.replace("</head>", head + "</head>", 1) if "</head>" in out else head + out
    return out.replace("</body>", JS + "</body>", 1) if "</body>" in out else out + JS


def filter_response(raw: bytes, host: str = "127.0.0.1") -> bytes:
    """raw = a full HTTP response (status line, headers, blank line, body). HTML pages get the shared skin; everything else passes through unchanged."""
    i = raw.find(b"\r\n\r\n")
    if i < 0:
        return raw
    head, body = raw[:i], raw[i + 4:]
    if b"text/html" not in head.lower() or b"<body" not in body.lower():
        return raw
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    new = page_skin(text, host).encode("utf-8")
    if new == body:
        return raw
    head = re.sub(rb"(?i)content-length:\s*\d+", b"Content-Length: " + str(len(new)).encode(), head)
    return head + b"\r\n\r\n" + new
