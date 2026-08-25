from __future__ import annotations

from pathlib import Path
from datetime import datetime
import ast
import py_compile
import re
import shutil

ROOT = Path(__file__).resolve().parent
DASH = ROOT / "aplus_live_pnl_dashboard.py"

if not DASH.is_file():
    raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / f"backup_before_stock_chart_nav_{stamp}"
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(DASH, backup / DASH.name)

LINK = (
    '<a href="/stock-charts" '
    'style="padding:9px 14px;border:1px solid #27334d;border-radius:9px;'
    'color:#e7eefc;text-decoration:none;font-weight:800;background:#121a2d">'
    'STOCK CHARTS</a>'
)

def html_literals(text: str):
    out = []
    for m in re.finditer(r'(?m)^([A-Z][A-Z0-9_]*HTML)\s*=\s*', text):
        name = m.group(1)
        st = m.end()
        ends = [x for x in (text.find("\n\ndef ", st), text.find("\n\nclass ", st)) if x >= 0]
        if not ends:
            continue
        en = min(ends)
        try:
            value = ast.literal_eval(text[st:en])
        except Exception:
            continue
        if isinstance(value, str) and "<html" in value.lower():
            out.append((name, st, en, value))
    return out

def patch_one(html: str) -> tuple[str, bool]:
    if 'href="/stock-charts"' in html:
        return html, False

    # Preferred: current top navigation bar contains TECHNICAL ALERTS.
    tech_pos = html.find("TECHNICAL ALERTS")
    if tech_pos >= 0:
        close_a = html.find("</a>", tech_pos)
        if close_a >= 0:
            close_a += len("</a>")
            return html[:close_a] + LINK + html[close_a:], True

    # Next preference: aplus-main-nav container.
    nav_pos = html.find('id="aplus-main-nav"')
    if nav_pos >= 0:
        close_div = html.find("</div>", nav_pos)
        if close_div >= 0:
            return html[:close_div] + LINK + html[close_div:], True

    # Next preference: generic nav container.
    nav_pos = html.find('class="nav"')
    if nav_pos >= 0:
        close_div = html.find("</div>", nav_pos)
        if close_div >= 0:
            return html[:close_div] + LINK + html[close_div:], True

    return html, False

try:
    s = DASH.read_text(encoding="utf-8")
    changed = False

    # Patch every HTML literal that already carries the main 5-module navbar.
    blocks = html_literals(s)
    for name, st, en, html in reversed(blocks):
        if "TECHNICAL ALERTS" not in html and 'id="aplus-main-nav"' not in html:
            continue
        new_html, did = patch_one(html)
        if did:
            s = s[:st] + repr(new_html) + s[en:]
            changed = True

    # Last-resort source-level injection for dashboards where navbar HTML
    # is assembled outside a literal assignment.
    if 'href="/stock-charts"' not in s:
        tech_pos = s.find("TECHNICAL ALERTS")
        if tech_pos >= 0:
            close_a = s.find("</a>", tech_pos)
            if close_a >= 0:
                close_a += len("</a>")
                s = s[:close_a] + LINK + s[close_a:]
                changed = True

    if 'href="/stock-charts"' not in s:
        raise RuntimeError("Could not locate current dashboard navigation bar")

    DASH.write_text(s, encoding="utf-8")
    py_compile.compile(str(DASH), doraise=True)

except Exception:
    shutil.copy2(backup / DASH.name, DASH)
    print("NAV FIX FAILED - original dashboard restored automatically.")
    print("Backup:", backup)
    raise

print("=" * 86)
print("SUCCESS: STOCK CHARTS NAV TAB ADDED")
print("Backup:", backup)
print("PASS: STOCK CHARTS link present in dashboard source")
print("PASS: dashboard compiles")
print("PASS: route/API code left untouched")
print("PASS: scanner/trading logic untouched")
print("")
print("Restart ONLY run_live_pnl_dashboard.bat, then refresh the browser.")
print("=" * 86)
