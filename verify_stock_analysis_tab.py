from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parent
DASH = ROOT / "aplus_live_pnl_dashboard.py"
MODULE = ROOT / "stock_analysis_tab.py"

py_compile.compile(str(DASH), doraise=True)
py_compile.compile(str(MODULE), doraise=True)

dash = DASH.read_text(encoding="utf-8")
module = MODULE.read_text(encoding="utf-8")

checks = [
    ("stock analysis module import", "from stock_analysis_tab import STOCK_ANALYSIS_HTML, analysis_payload"),
    ("route /stock-analysis", 'if path == "/stock-analysis":'),
    ("API /api/stock-analysis", 'if path == "/api/stock-analysis":'),
    ("F&O stock analysis link", '/stock-analysis?symbol='),
    ("main nav Stock Analysis", 'href="/stock-analysis"'),
    ("read-only marker", '"read_only": True'),
    ("trading engine untouched marker", '"trading_engine_untouched": True'),
]

print("=" * 82)
print("APLUS STOCK ANALYSIS TAB VERIFY")
print("=" * 82)
failed = False
for label, marker in checks:
    source = module if marker in module else dash
    ok = marker in source
    failed = failed or not ok
    print(("PASS" if ok else "FAIL") + ": " + label)
print("=" * 82)
raise SystemExit(1 if failed else 0)
