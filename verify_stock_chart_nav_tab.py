from pathlib import Path
import py_compile
ROOT=Path(__file__).resolve().parent
DASH=ROOT/"aplus_live_pnl_dashboard.py"
py_compile.compile(str(DASH),doraise=True)
s=DASH.read_text(encoding="utf-8")
checks=[
    ("stock chart route",'if path == "/stock-charts":'),
    ("stock chart API",'if path == "/api/stock-chart":'),
    ("stock charts nav",'href="/stock-charts"'),
]
print("="*80)
print("APLUS STOCK CHARTS NAV VERIFY")
print("="*80)
bad=False
for label,marker in checks:
    ok=marker in s
    bad=bad or not ok
    print(("PASS" if ok else "FAIL")+": "+label)
print("="*80)
raise SystemExit(1 if bad else 0)
