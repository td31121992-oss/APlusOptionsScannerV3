from pathlib import Path
import py_compile

ROOT=Path(__file__).resolve().parent
DASH=ROOT/"aplus_live_pnl_dashboard.py"
MODULE=ROOT/"stock_chart_dashboard_module.py"

py_compile.compile(str(DASH),doraise=True)
py_compile.compile(str(MODULE),doraise=True)

s=DASH.read_text(encoding="utf-8")
checks=[
    ("route /stock-charts",'if path == "/stock-charts":'),
    ("API symbols",'if path == "/api/stock-chart-symbols":'),
    ("API chart",'if path == "/api/stock-chart":'),
    ("module import","from stock_chart_dashboard_module import"),
    ("main nav link",'href="/stock-charts"'),
]
print("="*82)
print("APLUS STOCK CHART ROUTE V2 VERIFICATION")
print("="*82)
failed=False
for label,marker in checks:
    ok=marker in s
    failed = failed or not ok
    print(("PASS" if ok else "FAIL")+": "+label)
print("="*82)
raise SystemExit(1 if failed else 0)
