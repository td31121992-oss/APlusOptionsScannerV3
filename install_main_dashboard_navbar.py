from pathlib import Path
from datetime import datetime
import ast, shutil, py_compile, re

ROOT = Path(__file__).resolve().parent
DASH = ROOT / "aplus_live_pnl_dashboard.py"
if not DASH.is_file():
    raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / f"backup_before_main_navbar_{stamp}"
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(DASH, backup / DASH.name)

NAV = '\n<div style="padding:12px 20px;display:flex;gap:10px;flex-wrap:wrap;border-bottom:1px solid #27334d;background:#0b1020">\n  <a href="/" style="padding:9px 14px;border:1px solid #22d3ee;border-radius:9px;color:#9ffcff;text-decoration:none;font-weight:800;background:#0f2730">LIVE TRADING</a>\n  <a href="/fno-market-watch" style="padding:9px 14px;border:1px solid #27334d;border-radius:9px;color:#e7eefc;text-decoration:none;font-weight:800;background:#121a2d">F&amp;O MARKET WATCH</a>\n  <a href="/sector-performance" style="padding:9px 14px;border:1px solid #27334d;border-radius:9px;color:#e7eefc;text-decoration:none;font-weight:800;background:#121a2d">SECTOR PERFORMANCE</a>\n  <a href="/opening-structure" style="padding:9px 14px;border:1px solid #27334d;border-radius:9px;color:#e7eefc;text-decoration:none;font-weight:800;background:#121a2d">OPENING STRUCTURE</a>\n  <a href="http://127.0.0.1:8766" style="padding:9px 14px;border:1px solid #27334d;border-radius:9px;color:#e7eefc;text-decoration:none;font-weight:800;background:#121a2d">TECHNICAL ALERTS</a>\n</div>\n'

def find_main_html(text: str):
    preferred = ("HTML", "DASHBOARD_HTML", "MAIN_HTML", "LIVE_PNL_HTML")
    for name in preferred:
        marker = name + " = "
        i = text.find(marker)
        if i >= 0:
            st = i + len(marker)
            ends = [x for x in (text.find("\n\ndef ", st), text.find("\n\nclass ", st)) if x >= 0]
            if ends:
                en = min(ends)
                try:
                    html = ast.literal_eval(text[st:en])
                except Exception:
                    continue
                if isinstance(html, str) and "<html" in html.lower():
                    return st, en, name, html

    for m in re.finditer(r'^([A-Z_]+HTML)\s*=\s*', text, flags=re.M):
        name = m.group(1)
        if name in ("SECTOR_PERFORMANCE_HTML", "FNO_MARKET_WATCH_HTML", "OPENING_STRUCTURE_HTML"):
            continue
        st = m.end()
        ends = [x for x in (text.find("\n\ndef ", st), text.find("\n\nclass ", st)) if x >= 0]
        if not ends:
            continue
        en = min(ends)
        try:
            html = ast.literal_eval(text[st:en])
        except Exception:
            continue
        if isinstance(html, str) and "<html" in html.lower():
            return st, en, name, html
    raise RuntimeError("Main dashboard HTML block not found")

try:
    s = DASH.read_text(encoding="utf-8")
    st, en, name, html = find_main_html(s)

    if 'F&amp;O MARKET WATCH' not in html or 'TECHNICAL ALERTS' not in html:
        body_open = html.lower().find("<body")
        if body_open < 0:
            raise RuntimeError("Main dashboard <body> not found")
        body_end = html.find(">", body_open)
        if body_end < 0:
            raise RuntimeError("Main dashboard <body> malformed")
        html = html[:body_end+1] + NAV + html[body_end+1:]
        s = s[:st] + repr(html) + s[en:]
        DASH.write_text(s, encoding="utf-8")
        py_compile.compile(str(DASH), doraise=True)
    else:
        print("Navigation bar already present; no patch required.")

except Exception:
    shutil.copy2(backup / DASH.name, DASH)
    print("INSTALL FAILED - original dashboard restored:", backup)
    raise

print("="*82)
print("SUCCESS: MAIN DASHBOARD NAVIGATION BAR RESTORED")
print("Backup:", backup)
print("Links: LIVE TRADING | F&O MARKET WATCH | SECTOR PERFORMANCE | OPENING STRUCTURE | TECHNICAL ALERTS")
print("Scanner/trading logic untouched.")
print("="*82)
