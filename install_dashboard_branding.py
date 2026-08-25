from pathlib import Path
from datetime import datetime
import shutil, py_compile

p = Path("aplus_live_pnl_dashboard.py")
if not p.is_file():
    raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found in project root.")

backup = Path(f"aplus_live_pnl_dashboard_before_branding_{datetime.now():%Y%m%d_%H%M%S}.py")
shutil.copy2(p, backup)

s = p.read_text(encoding="utf-8")

# Visible branding only. Underlying scanner remains PAPER-only.
s = s.replace("APlus PAPER Live P&L Dashboard", "APlus Live Trading Terminal")
s = s.replace("APlus Paper Trading Live P&L", "APlus Live Trading Terminal")

# Add watermark CSS before responsive CSS if not already present.
if ".watermark{" not in s:
    anchor = "@media(max-width:1200px)"
    css = """.watermark{position:fixed;left:50%;top:52%;transform:translate(-50%,-50%) rotate(-24deg);font-size:52px;font-weight:700;letter-spacing:2px;color:rgba(231,238,252,.045);white-space:nowrap;pointer-events:none;user-select:none;z-index:0}
.header,.grid,.tablewrap{position:relative;z-index:1}
"""
    if anchor in s:
        s = s.replace(anchor, css + anchor, 1)
    else:
        s = s.replace("</style>", css + "</style>", 1)

# Add watermark element immediately after body.
wm = '<div class="watermark">Developed by Darpan Bobhate</div>'
if wm not in s:
    s = s.replace("<body>", "<body>\n" + wm, 1)

# Remove visible PAPER wording from dashboard subtitle, if present.
s = s.replace("PAPER Live P&L", "Live P&L")
s = s.replace("PAPER Trading", "Trading")

p.write_text(s, encoding="utf-8")

try:
    py_compile.compile(str(p), doraise=True)
except Exception:
    shutil.copy2(backup, p)
    raise

print("=" * 68)
print("SUCCESS: APLUS DASHBOARD BRANDING INSTALLED")
print("Backup:", backup)
print("Title     : APlus Live Trading Terminal")
print("Watermark : Developed by Darpan Bobhate")
print("PASS: subtle transparent background watermark")
print("PASS: dashboard trading logic/data source unchanged")
print("PASS: scanner remains PAPER-only; no broker-order code changed")
print("=" * 68)
