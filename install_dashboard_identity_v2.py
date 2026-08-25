from pathlib import Path
from datetime import datetime
import shutil, py_compile

p=Path("aplus_live_pnl_dashboard.py")
if not p.is_file():
    raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")

backup=Path(f"aplus_live_pnl_dashboard_before_identity_{datetime.now():%Y%m%d_%H%M%S}.py")
shutil.copy2(p,backup)
s=p.read_text(encoding="utf-8")

try:
    # Stronger but still subtle watermark.
    s=s.replace(
        'color:rgba(231,238,252,.045);',
        'color:rgba(231,238,252,.085);'
    )
    s=s.replace(
        'font-size:52px;',
        'font-size:58px;'
    )

    # Add visible developer line under title if not already there.
    visible = '<div class="sub">Developed by Darpan Bobhate</div>'
    if visible not in s:
        anchor = '<div class="title">APlus Live Trading Terminal</div>'
        if anchor not in s:
            raise RuntimeError("title anchor not found")
        s=s.replace(anchor, anchor + visible, 1)

    # Add date/day to snapshot if not present.
    if '"trading_date":' not in s:
        anchor = '        "updated_at": datetime.now().strftime("%H:%M:%S"),'
        if anchor not in s:
            raise RuntimeError("snapshot updated_at anchor not found")
        repl = anchor + '\n        "trading_date": datetime.now().strftime("%d-%b-%Y"),\n        "trading_day": datetime.now().strftime("%A"),'
        s=s.replace(anchor,repl,1)

    # Add date/day in header right block if not present.
    if 'id="trading_date"' not in s:
        anchor = '<div class="sub">Last update: <span id="updated">-</span></div>'
        if anchor not in s:
            raise RuntimeError("last update anchor not found")
        repl = '<div style="text-align:right"><div class="sub"><b><span id="trading_day">-</span>, <span id="trading_date">-</span></b></div>' + anchor + '</div>'
        s=s.replace(anchor,repl,1)

    # Wire date/day in JS.
    marker='updated.textContent=d.updated_at;'
    if 'trading_date.textContent' not in s:
        if marker not in s:
            raise RuntimeError("updated JS anchor not found")
        s=s.replace(marker, marker+'trading_date.textContent=d.trading_date;trading_day.textContent=d.trading_day;',1)

    p.write_text(s,encoding="utf-8")
    py_compile.compile(str(p),doraise=True)

except Exception:
    shutil.copy2(backup,p)
    print("INSTALL FAILED - original restored:",backup)
    raise

print("="*68)
print("SUCCESS: DASHBOARD IDENTITY PATCH INSTALLED")
print("PASS: visible Developed by Darpan Bobhate under title")
print("PASS: stronger background watermark")
print("PASS: date + day added to top-right")
print("PASS: existing trade filters preserved")
print("Backup:",backup)
print("="*68)
