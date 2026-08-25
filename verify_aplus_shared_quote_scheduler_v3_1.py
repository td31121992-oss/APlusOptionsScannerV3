from pathlib import Path
import py_compile
p=Path("opening_momentum_scanner.py")
py_compile.compile(str(p),doraise=True)
s=p.read_text(encoding="utf-8")
checks={
"v3_1":"APLUS_SHARED_QUOTE_SCHEDULER_V3_1" in s,
"combined_nse_fno":'quote_request["NSE_FNO"] = open_option_ids' in s,
"shared_monitor":"_monitor_paper_positions_from_quote_map" in s,
"session_end":"final_update = self._monitor_paper_positions(now=now, force_close=True)" in s,
"v2_survival":"APLUS_SCANNER_429_SURVIVAL_V2" in s,
"observer":"OPEN_MOVE_PATTERN_OBSERVER" in s,
"conversion":"PAPER conversion audit" in s,
"expiry":"OPTION_EXPIRY_FALLBACK" in s,
}
print("="*110)
print("APLUS DHAN 429 RELIABILITY V3.1 VERIFY")
for k,v in checks.items(): print("PASS" if v else "FAIL",k)
print("="*110)
raise SystemExit(0 if all(checks.values()) else 1)
