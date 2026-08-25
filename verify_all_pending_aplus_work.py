from pathlib import Path
import py_compile
ROOT=Path(__file__).resolve().parent
for p in ["paper_trade_journal.py","aplus_live_pnl_dashboard.py","opening_momentum_scanner.py"]:
    py_compile.compile(str(ROOT/p),doraise=True)
checks={
"history_sync":"sync_history(self.report_dir, self.trades)" in (ROOT/"paper_trade_journal.py").read_text(encoding="utf-8",errors="ignore"),
"paper_history_route":'if path == "/paper-history":' in (ROOT/"aplus_live_pnl_dashboard.py").read_text(encoding="utf-8",errors="ignore"),
"leadership_shadow":"LeadershipV6Shadow" in (ROOT/"opening_momentum_scanner.py").read_text(encoding="utf-8",errors="ignore"),
"conversion_audit":"PAPER conversion audit" in (ROOT/"opening_momentum_scanner.py").read_text(encoding="utf-8",errors="ignore"),
}
print("="*90);print("APLUS ALL-PENDING-WORK VERIFY")
for k,v in checks.items():print("PASS" if v else "FAIL",k)
print("="*90)
raise SystemExit(0 if all(checks.values()) else 1)
