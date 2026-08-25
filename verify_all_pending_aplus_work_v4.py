from pathlib import Path
import py_compile
ROOT=Path(__file__).resolve().parent
for p in ["paper_trade_journal.py","aplus_live_pnl_dashboard.py","opening_momentum_scanner.py"]:
    py_compile.compile(str(ROOT/p),doraise=True)
j=(ROOT/"paper_trade_journal.py").read_text(encoding="utf-8",errors="ignore")
d=(ROOT/"aplus_live_pnl_dashboard.py").read_text(encoding="utf-8",errors="ignore")
s=(ROOT/"opening_momentum_scanner.py").read_text(encoding="utf-8",errors="ignore")
checks={
"history_sync":"sync_history(self.report_dir, self.trades)" in j,
"history_route":'if path == "/paper-history":' in d,
"history_days_api":'if path == "/api/paper-days":' in d,
"history_data_api":'if path == "/api/paper-history":' in d,
"market_watch_route":'if path == "/fno-market-watch":' in d,
"stock_charts_route":'if path == "/stock-charts":' in d,
"opening_structure_route":'if path == "/opening-structure":' in d,
"conversion_audit":"PAPER conversion audit" in s,
"leadership_shadow":"LeadershipV6Shadow" in s,
}
print("="*96)
print("APLUS V4 FINAL VERIFY")
for k,v in checks.items():print(("PASS" if v else "FAIL"),k)
print("="*96)
raise SystemExit(0 if all(checks.values()) else 1)
