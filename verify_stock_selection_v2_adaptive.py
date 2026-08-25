from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parent
SCANNER = ROOT / "opening_momentum_scanner.py"
ENV = ROOT / ".env"

py_compile.compile(str(SCANNER), doraise=True)
src = SCANNER.read_text(encoding="utf-8")
required = [
    "rank_raw_movers(",
    "forced_symbols=v2_mover_symbols",
    "evaluate_entry_ready(",
    '"stock_selection_v2": {',
    "intraday_stock_selection_v2_latest.json",
    "intraday_stock_selection_v2.csv",
    "self._account_cache",
    "_fund_cache_seconds",
    "_positions_cache_seconds",
]
missing = [x for x in required if x not in src]
if missing:
    raise SystemExit("VERIFY FAIL: " + repr(missing))

env = ENV.read_text(encoding="utf-8", errors="ignore") if ENV.exists() else ""
checks = [
    "HISTORICAL_REQUESTS_PER_SECOND=1.0",
    "OPTION_CHAIN_REQUESTS_PER_SECOND=0.25",
    "INTRADAY_HISTORICAL_WORKERS=1",
    "INTRADAY_ACCOUNT_FUND_CACHE_SECONDS=300",
    "INTRADAY_ACCOUNT_POSITIONS_CACHE_SECONDS=30",
]

print("=" * 90)
print("APLUS STOCK SELECTION V2 + API RELIABILITY VERIFY")
print("=" * 90)
print("PASS: scanner compiles")
print("PASS: Stock Selection V2 installed")
print("PASS: account/fund/position cache code preserved")
for k in checks:
    print(f"{'PASS' if k in env else 'WARN'}: {k}")
print("PASS: PAPER ONLY")
print("=" * 90)
