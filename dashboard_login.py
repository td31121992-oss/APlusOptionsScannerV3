"""Password gate with a welcome screen for the APlus dashboard (look + access only: no trading logic).

    python set_dashboard_password.py        you type the password (hidden, twice); only a salted scrypt hash is stored in data/control/dashboard_auth.json
    /login                                  the welcome screen ("WELCOME" over the title, ARJUNA by default); the dashboard opens after the right password
    /logout                                 locks the dashboard again

While no password is set the dashboard opens as before (nothing locks you out). Once one is set, EVERY page and API needs the session cookie (HttpOnly, SameSite=Strict, valid
APLUS_LOGIN_HOURS hours, default 12); an unauthenticated browser is sent to /login, an unauthenticated API call gets 401. Five wrong passwords from one address lock that address for five
minutes. Changing the password signs every browser out. Forgot it: delete data/control/dashboard_auth.json and run set_dashboard_password.py again.

The dashboard is plain HTTP, so on a shared Wi-Fi the password crosses the network unencrypted: keep APLUS_DASHBOARD_ACCESS at lan / local, or reach it through Tailscale (encrypted).
APLUS_LOGIN_TITLE changes the title (default Arjuna); APLUS_LOGIN_NAME, when set, shows a name above the title.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets
import threading
import time
from http import cookies
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
CONFIG = Path(os.getenv("APLUS_AUTH_FILE") or ROOT / "data" / "control" / "dashboard_auth.json")
COOKIE = "aplus_session"
MAX_FAILS, LOCK_SECONDS = 5, 300
MIN_LENGTH = 8
_LOCK = threading.Lock()
_FAILS: dict[str, list[float]] = {}
_CACHE: dict[str, Any] = {"mtime": None, "cfg": None}


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def _config(path: Path | None = None) -> dict[str, Any] | None:
    path = path or CONFIG
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _CACHE.get("path") != str(path) or _CACHE["mtime"] != mtime:
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        _CACHE.update(path=str(path), mtime=mtime, cfg=cfg if cfg.get("hash") and cfg.get("secret") else None)
    return _CACHE["cfg"]


def is_configured(path: Path | None = None) -> bool:
    return _config(path) is not None


def set_password(password: str, path: Path | None = None) -> None:
    """Store a salted scrypt hash and a fresh signing secret (this signs out every browser). The password itself is never stored."""
    if len(password) < MIN_LENGTH:
        raise ValueError(f"the password must be at least {MIN_LENGTH} characters")
    path = path or CONFIG
    salt = secrets.token_bytes(16)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"salt": salt.hex(), "hash": _scrypt(password, salt).hex(), "secret": secrets.token_hex(32), "created": time.strftime("%Y-%m-%d %H:%M:%S")}), encoding="utf-8")
    _CACHE["mtime"] = None


def verify(password: str, path: Path | None = None) -> bool:
    cfg = _config(path)
    if not cfg:
        return False
    try:
        return hmac.compare_digest(_scrypt(password, bytes.fromhex(cfg["salt"])).hex(), cfg["hash"])
    except (ValueError, KeyError):
        return False


def session_hours() -> float:
    try:
        return max(0.1, float(os.getenv("APLUS_LOGIN_HOURS", "12")))
    except ValueError:
        return 12.0


def make_token(now: float | None = None, path: Path | None = None) -> str:
    cfg = _config(path)
    exp = int((now if now is not None else time.time()) + session_hours() * 3600)
    body = f"{exp}.{secrets.token_hex(8)}"
    return f"{body}.{hmac.new(bytes.fromhex(cfg['secret']), body.encode(), hashlib.sha256).hexdigest()}" if cfg else ""


def valid_token(token: str, now: float | None = None, path: Path | None = None) -> bool:
    cfg = _config(path)
    try:
        exp, nonce, sig = str(token).split(".")
        good = hmac.new(bytes.fromhex(cfg["secret"]), f"{exp}.{nonce}".encode(), hashlib.sha256).hexdigest() if cfg else ""
        return bool(cfg) and hmac.compare_digest(sig, good) and int(exp) > (now if now is not None else time.time())
    except (ValueError, KeyError, TypeError):
        return False


def locked(ip: str, now: float | None = None) -> int:
    """Seconds left on this address's lock, 0 when it may try."""
    now = now if now is not None else time.time()
    with _LOCK:
        recent = [t for t in _FAILS.get(ip, []) if now - t < LOCK_SECONDS]
        _FAILS[ip] = recent
        return int(LOCK_SECONDS - (now - recent[0])) if len(recent) >= MAX_FAILS else 0


def record_fail(ip: str, now: float | None = None) -> None:
    with _LOCK:
        _FAILS.setdefault(ip, []).append(now if now is not None else time.time())


def clear_fails(ip: str) -> None:
    with _LOCK:
        _FAILS.pop(ip, None)


def _send(h: Any, code: int, body: bytes, ctype: str = "application/json", headers: dict[str, str] | None = None) -> None:
    h.send_response(code)
    h.send_header("Content-Type", ctype)
    h.send_header("Cache-Control", "no-store")
    h.send_header("Content-Length", str(len(body)))
    for k, v in (headers or {}).items():
        h.send_header(k, v)
    h.end_headers()
    h.wfile.write(body)


def _redirect(h: Any, location: str, headers: dict[str, str] | None = None) -> None:
    h.send_response(302)
    h.send_header("Location", location)
    h.send_header("Cache-Control", "no-store")
    h.send_header("Content-Length", "0")
    for k, v in (headers or {}).items():
        h.send_header(k, v)
    h.end_headers()


def _cookie_of(h: Any) -> str:
    try:
        jar = cookies.SimpleCookie(h.headers.get("Cookie") or "")
        return jar[COOKIE].value if COOKIE in jar else ""
    except cookies.CookieError:
        return ""


def _safe_next(value: str) -> str:
    return value if value.startswith("/") and not value.startswith("//") and "\\" not in value else "/"


def guard(h: Any, method: str) -> bool:
    """Called first in the dashboard's request handlers. True = the request was answered here (login page, 401, redirect); False = carry on normally."""
    try:
        import dashboard_access

        if not dashboard_access.is_allowed(h.client_address[0]):
            return False                                    # the dashboard's own 403 handles it
    except Exception:                                       # noqa: BLE001
        pass
    parsed = urlparse(h.path)
    path = parsed.path
    ip = str(h.client_address[0])
    if path == "/api/auth-status":
        _send(h, 200, json.dumps({"configured": is_configured()}).encode())
        return True
    if not is_configured():
        if path in ("/login", "/logout"):
            _redirect(h, "/")
            return True
        return False
    if path == "/logout":
        _redirect(h, "/login", {"Set-Cookie": f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})
        return True
    if path == "/api/login" and method == "POST":
        wait = locked(ip)
        if wait:
            _send(h, 429, json.dumps({"ok": False, "message": f"Too many attempts. Try again in {wait // 60 + 1} min."}).encode())
            return True
        try:
            n = min(int(h.headers.get("Content-Length") or 0), 2048)
            pw = str((json.loads(h.rfile.read(n) or b"{}")).get("password", ""))
        except (ValueError, TypeError, AttributeError):
            pw = ""
        if verify(pw):
            clear_fails(ip)
            _send(h, 200, json.dumps({"ok": True}).encode(), headers={"Set-Cookie": f"{COOKIE}={make_token()}; Path=/; Max-Age={int(session_hours() * 3600)}; HttpOnly; SameSite=Strict"})
        else:
            record_fail(ip)
            time.sleep(0.4)                                 # slows guessing
            _send(h, 401, json.dumps({"ok": False, "message": "Access denied."}).encode())
        return True
    if valid_token(_cookie_of(h)):
        if path == "/login":
            _redirect(h, _safe_next((parse_qs(parsed.query).get("next") or ["/"])[0]))
            return True
        return False
    if path == "/login" and method == "GET":
        name = html.escape(os.getenv("APLUS_LOGIN_NAME", "").strip())
        title = html.escape(os.getenv("APLUS_LOGIN_TITLE", "Arjuna").strip() or "Arjuna")
        big, small = (name, title) if name else (title, "AI TRADING CORE")           # a name, when set, goes big with the title under it
        _send(h, 200, LOGIN_HTML.replace("{{NAME}}", big).replace("{{TITLE}}", small).encode("utf-8"), "text/html; charset=utf-8")
        return True
    if method == "GET" and not path.startswith("/api/"):
        target = path + (("?" + parsed.query) if parsed.query else "")
        _redirect(h, "/login?next=" + _quote(target))
        return True
    _send(h, 401, json.dumps({"ok": False, "message": "Login required."}).encode())
    return True


def _quote(s: str) -> str:
    from urllib.parse import quote

    return quote(s, safe="/")


LOGIN_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Access</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
*{box-sizing:border-box}html,body{height:100%;margin:0;background:#03060d;color:#e6f6ff;font-family:Bahnschrift,"Segoe UI",Arial,sans-serif;overflow:hidden}
canvas#bg{position:fixed;inset:0;width:100%;height:100%}
.vig{position:fixed;inset:0;background:radial-gradient(ellipse at center,transparent 35%,rgba(0,0,0,.75) 100%);pointer-events:none}
.beam{position:fixed;left:0;right:0;top:0;height:160px;background:linear-gradient(180deg,transparent,rgba(34,230,255,.07),transparent);animation:beam 9s linear infinite;pointer-events:none}
@keyframes beam{from{transform:translateY(-180px)}to{transform:translateY(100vh)}}
.wrap{position:relative;z-index:2;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0;padding:20px;text-align:center}
.core{position:relative;width:150px;height:150px;margin-bottom:18px}
.core i{position:absolute;inset:0;border-radius:50%;border:2px solid transparent}
.core i:nth-child(1){border-top-color:#22e6ff;border-bottom-color:#27e3b0;animation:spin 4s linear infinite;box-shadow:0 0 30px rgba(34,230,255,.25)}
.core i:nth-child(2){inset:14px;border-left-color:#22e6ff;border-right-color:rgba(34,230,255,.3);animation:spin 6s linear infinite reverse}
.core i:nth-child(3){inset:30px;border:1px dashed rgba(34,230,255,.6);animation:spin 14s linear infinite}
.core b{position:absolute;inset:52px;border-radius:50%;background:radial-gradient(circle,#fff 0,#22e6ff 45%,transparent 72%);box-shadow:0 0 40px #22e6ff;animation:pulse 2.6s ease-in-out infinite}
@keyframes spin{to{transform:rotate(360deg)}}@keyframes pulse{0%,100%{opacity:.6;transform:scale(.82)}50%{opacity:1;transform:scale(1)}}
.hello{letter-spacing:.55em;font-size:13px;color:#5fd8ee;margin:0 0 6px .55em}
h1{margin:0;font-size:clamp(40px,8vw,84px);letter-spacing:.2em;font-weight:700;text-transform:uppercase;color:#fff;text-shadow:0 0 28px rgba(34,230,255,.7),0 0 70px rgba(34,230,255,.35);padding-left:.2em}
.uni{margin:8px 0 0;text-transform:uppercase;letter-spacing:.6em;font-size:clamp(12px,2vw,17px);color:#9be9f7;padding-left:.6em}
.box{margin-top:36px;width:min(360px,88vw);position:relative;padding:18px 18px 16px;border:1px solid rgba(34,230,255,.28);background:rgba(4,12,22,.72);backdrop-filter:blur(6px);box-shadow:0 0 40px rgba(34,230,255,.08)}
.box::before,.box::after{content:"";position:absolute;width:14px;height:14px;border:2px solid #22e6ff}.box::before{left:-2px;top:-2px;border-right:0;border-bottom:0}.box::after{right:-2px;bottom:-2px;border-left:0;border-top:0}
.lab{font-size:10.5px;letter-spacing:.3em;color:#5fd8ee;text-align:left;margin-bottom:7px}
input{width:100%;background:rgba(2,8,16,.9);border:1px solid rgba(34,230,255,.35);color:#e9fbff;font:600 18px Consolas,monospace;letter-spacing:.3em;padding:12px 14px;outline:0;text-align:center}
input:focus{border-color:#22e6ff;box-shadow:0 0 16px rgba(34,230,255,.35)}
button{margin-top:12px;width:100%;padding:12px;background:linear-gradient(90deg,rgba(34,230,255,.18),rgba(39,227,176,.18));border:1px solid #22e6ff;color:#dffaff;letter-spacing:.4em;font:700 13px Bahnschrift,"Segoe UI",sans-serif;cursor:pointer;transition:.2s}
button:hover{background:rgba(34,230,255,.32);box-shadow:0 0 22px rgba(34,230,255,.4)}button:disabled{opacity:.5;cursor:wait}
.msg{min-height:18px;margin-top:11px;font-size:12px;letter-spacing:.18em;color:#7fe9ff}.msg.bad{color:#ff7a8a}.msg.ok{color:#27e3b0}
.foot{position:fixed;bottom:14px;left:0;right:0;text-align:center;font-size:10.5px;letter-spacing:.35em;color:#3f8ea0;z-index:2}
.granted .core i:nth-child(1){animation-duration:.8s}.granted .box{border-color:#27e3b0;box-shadow:0 0 50px rgba(39,227,176,.35)}.granted h1{text-shadow:0 0 34px rgba(39,227,176,.9)}
.shake{animation:shake .35s}@keyframes shake{25%{transform:translateX(-8px)}75%{transform:translateX(8px)}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
</style></head><body><canvas id="bg"></canvas><div class="vig"></div><div class="beam"></div>
<div class="wrap" id="wrap"><div class="core"><i></i><i></i><i></i><b></b></div>
<p class="hello">WELCOME</p><h1>{{NAME}}</h1><p class="uni">{{TITLE}}</p>
<form class="box" id="f" autocomplete="off"><div class="lab">ACCESS KEY</div><input id="pw" type="password" autofocus autocomplete="current-password" aria-label="Password"><button id="go" type="submit">AUTHENTICATE</button><div class="msg" id="msg">ENTER YOUR PASSWORD</div></form></div>
<div class="foot">APLUS &middot; AI TRADING CORE</div>
<script>
(function(){
 var c=document.getElementById("bg"),x=c.getContext("2d"),N=[],W,H,R=window.devicePixelRatio||1;
 function size(){W=c.width=innerWidth*R;H=c.height=innerHeight*R;N=[];var n=Math.min(110,Math.floor(innerWidth*innerHeight/14000));for(var i=0;i<n;i++)N.push({x:Math.random()*W,y:Math.random()*H,vx:(Math.random()-.5)*.35*R,vy:(Math.random()-.5)*.35*R})}
 function draw(){x.clearRect(0,0,W,H);x.strokeStyle="rgba(34,230,255,.05)";x.lineWidth=1;var g=60*R;for(var gx=0;gx<W;gx+=g){x.beginPath();x.moveTo(gx,0);x.lineTo(gx,H);x.stroke()}for(var gy=0;gy<H;gy+=g){x.beginPath();x.moveTo(0,gy);x.lineTo(W,gy);x.stroke()}
  for(var i=0;i<N.length;i++){var a=N[i];a.x+=a.vx;a.y+=a.vy;if(a.x<0||a.x>W)a.vx*=-1;if(a.y<0||a.y>H)a.vy*=-1;
   for(var j=i+1;j<N.length;j++){var b=N[j],dx=a.x-b.x,dy=a.y-b.y,d=Math.sqrt(dx*dx+dy*dy),L=150*R;if(d<L){x.strokeStyle="rgba(34,230,255,"+(.22*(1-d/L))+")";x.beginPath();x.moveTo(a.x,a.y);x.lineTo(b.x,b.y);x.stroke()}}
   x.fillStyle="rgba(120,240,255,.8)";x.beginPath();x.arc(a.x,a.y,1.6*R,0,6.3);x.fill()}
  requestAnimationFrame(draw)}
 size();addEventListener("resize",size);if(!matchMedia("(prefers-reduced-motion:reduce)").matches)draw();else{draw=null}
 var f=document.getElementById("f"),pw=document.getElementById("pw"),msg=document.getElementById("msg"),go=document.getElementById("go");
 var next=(new URLSearchParams(location.search).get("next")||"/");if(next.charAt(0)!=="/"||next.indexOf("//")===0)next="/";
 f.addEventListener("submit",function(e){e.preventDefault();if(!pw.value)return;go.disabled=true;msg.className="msg";msg.textContent="VERIFYING...";
  fetch("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:pw.value})}).then(function(r){return r.json().then(function(j){return [r.status,j]})}).then(function(a){
   if(a[1].ok){msg.className="msg ok";msg.textContent="ACCESS GRANTED";document.getElementById("wrap").classList.add("granted");setTimeout(function(){location.href=next},1100)}
   else{msg.className="msg bad";msg.textContent=(a[1].message||"ACCESS DENIED").toUpperCase();pw.value="";go.disabled=false;f.classList.remove("shake");void f.offsetWidth;f.classList.add("shake");pw.focus()}})
  .catch(function(){msg.className="msg bad";msg.textContent="CORE UNREACHABLE";go.disabled=false})});
})();
</script></body></html>"""
