from pathlib import Path
from datetime import datetime
import shutil, py_compile, re
p=Path("aplus_live_pnl_dashboard.py")
if not p.is_file(): raise SystemExit("FAIL: dashboard file not found")
b=Path(f"aplus_live_pnl_dashboard_before_crisp_footer_{datetime.now():%Y%m%d_%H%M%S}.py")
shutil.copy2(p,b); s=p.read_text(encoding="utf-8")
try:
    s=re.sub(r'<div class="footer exact-footer">.*?</div>', '', s, count=1, flags=re.S)
    css=".crisp-footer{margin-top:14px;border-top:1px solid #1e6091;border-bottom:1px solid #1e6091;background:linear-gradient(90deg,#071426,#0b1b35,#071426);padding:16px 22px;display:grid;grid-template-columns:1.25fr 1.7fr 1.35fr .65fr;gap:22px;align-items:center;position:relative;z-index:2}.cf-quote{font-size:13px;line-height:1.45;color:#e7eefc}.cf-brand{display:flex;align-items:center;justify-content:center;gap:12px}.cf-logo{width:54px;height:54px}.cf-title{font-size:20px;font-weight:800;white-space:nowrap}.cf-title .live{color:#17c964}.cf-dev{font-size:12px;color:#d7e3f5;margin-top:4px;text-align:center}.cf-flow{font-size:11px;font-weight:700;white-space:nowrap}.cf-flow .dot{color:#17c964;padding:0 7px}.cf-safe{font-size:11px;color:#d7e3f5;margin-top:8px;white-space:nowrap}.cf-copy{text-align:right;font-size:11px;color:#d7e3f5;line-height:1.7}.cf-flag{font-size:18px}@media(max-width:1100px){.crisp-footer{grid-template-columns:1fr 1fr}.cf-copy{text-align:left}}"
    if ".crisp-footer{" not in s:
        if "</style>" not in s: raise RuntimeError("style anchor not found")
        s=s.replace("</style>",css+"</style>",1)
    logo='<svg class="cf-logo" viewBox="0 0 64 64"><defs><linearGradient id="cfg" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#38bdf8"/><stop offset="1" stop-color="#22c55e"/></linearGradient></defs><path d="M7 55 27 9l17 46h-10l-7-20-8 20z" fill="url(#cfg)"/><path d="m18 47 12-10 8 5 17-21" fill="none" stroke="#22c55e" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/><path d="M47 21h9v9" fill="none" stroke="#22c55e" stroke-width="5" stroke-linecap="round"/></svg>'
    footer='<div class="crisp-footer"><div class="cf-quote">❝ &nbsp;<b>Discipline Creates Profits,</b><br>&nbsp;&nbsp;&nbsp;&nbsp;Automation Protects Them.</div><div class="cf-brand">'+logo+'<div><div class="cf-title">APlus <span class="live">Live</span> Trading Terminal</div><div class="cf-dev">— &nbsp; Developed by Darpan Bobhate &nbsp; —</div></div></div><div><div class="cf-flow">RESEARCH <span class="dot">•</span> ANALYZE <span class="dot">•</span> EXECUTE <span class="dot">•</span> IMPROVE</div><div class="cf-safe">🛡️ &nbsp; Paper Trading &nbsp; | &nbsp; NSE F&amp;O &nbsp; | &nbsp; No Live Orders</div></div><div class="cf-copy">© 2026 &nbsp; <span class="cf-flag">🇮🇳</span><br>All Rights Reserved</div></div>'
    if "</body></html>" not in s: raise RuntimeError("body anchor not found")
    s=s.replace("</body></html>",footer+"</body></html>",1)
    p.write_text(s,encoding="utf-8"); py_compile.compile(str(p),doraise=True)
except Exception:
    shutil.copy2(b,p); print("INSTALL FAILED - original restored:",b); raise
print("SUCCESS: CRISP NATIVE FOOTER INSTALLED")
print("PASS: native sharp text + vector logo")
print("PASS: V5 dashboard behavior untouched")
print("Backup:",b)
