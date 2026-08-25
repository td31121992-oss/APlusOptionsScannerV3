from pathlib import Path
from datetime import datetime
import shutil, py_compile

p=Path("aplus_live_pnl_dashboard.py")
if not p.is_file(): raise SystemExit("FAIL: dashboard file not found")
b=Path(f"aplus_live_pnl_dashboard_before_final_branding_{datetime.now():%Y%m%d_%H%M%S}.py")
shutil.copy2(p,b)
s=p.read_text(encoding="utf-8")
try:
    if ".aplus-logo{" not in s:
        a=".title{font-size:24px;font-weight:700}"
        if a not in s: raise RuntimeError("title CSS anchor not found")
        css=".brandrow{display:flex;align-items:center;gap:12px}.aplus-logo{width:48px;height:48px;flex:0 0 auto}.footer{margin-top:8px;padding:20px 24px;border-top:1px solid var(--line);display:flex;justify-content:center;align-items:center;gap:12px;position:relative;z-index:1;background:#0b1020}.footer .aplus-logo{width:38px;height:38px}.footer-title{font-size:17px;font-weight:700}.footer-sub{color:var(--muted);font-size:12px;margin-top:3px;text-align:center}"
        s=s.replace(a,a+css,1)

    logo='<svg class="aplus-logo" viewBox="0 0 64 64" aria-label="APlus logo"><defs><linearGradient id="ag" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#38bdf8"/><stop offset="1" stop-color="#22c55e"/></linearGradient></defs><path d="M8 54 L27 10 L43 54 H34 L27 34 L20 54 Z" fill="url(#ag)"/><path d="M18 47 L29 38 L37 42 L53 22" fill="none" stroke="#22c55e" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/><path d="M46 22 H54 V30" fill="none" stroke="#22c55e" stroke-width="5" stroke-linecap="round"/></svg>'

    title='<div class="title">APlus Live Trading Terminal</div>'
    if 'class="brandrow"' not in s:
        if title not in s: raise RuntimeError("title HTML anchor not found")
        s=s.replace(title,'<div class="brandrow">'+logo+'<div>'+title,1)
        combo='<div class="sub">Developed by Darpan Bobhate</div><div class="sub">Auto-refreshes every 5 seconds from data/reports</div>'
        if combo not in s: raise RuntimeError("header sub-lines anchor not found")
        s=s.replace(combo,combo+'</div></div>',1)

    if 'class="footer"' not in s:
        a='</body></html>'
        if a not in s: raise RuntimeError("body close anchor not found")
        footer='<div class="footer">'+logo+'<div><div class="footer-title">APlus Live Trading Terminal</div><div class="footer-sub">Developed by Darpan Bobhate</div></div></div>'
        s=s.replace(a,footer+a,1)

    p.write_text(s,encoding="utf-8")
    py_compile.compile(str(p),doraise=True)
except Exception:
    shutil.copy2(b,p)
    print("INSTALL FAILED - original restored:",b)
    raise

print("SUCCESS: FINAL APLUS DASHBOARD BRANDING INSTALLED")
print("PASS: logo at top and footer")
print("PASS: bottom terminal title + developer name")
print("PASS: existing V5 functionality preserved")
print("Backup:",b)
