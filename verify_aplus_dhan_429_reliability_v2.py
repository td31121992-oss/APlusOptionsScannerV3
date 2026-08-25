from pathlib import Path
import py_compile
d=Path("core/dhan_client.py"); s=Path("opening_momentum_scanner.py")
py_compile.compile(str(d),doraise=True); py_compile.compile(str(s),doraise=True)
ds=d.read_text(encoding="utf-8"); ss=s.read_text(encoding="utf-8")
checks={
"dhan_marker":"APLUS_DHAN_429_RELIABILITY_V2" in ds,
"quote_cap":"safe_rps = 0.30" in ds,
"history_cap":"safe_rps = 1.50" in ds,
"global_gap":"global_gap = 0.45" in ds,
"scanner_survival":"APLUS_SCANNER_429_SURVIVAL_V2" in ss,
"skip_marker":"APLUS_429_CYCLE_SKIPPED" in ss,
"observer_preserved":"OPEN_MOVE_PATTERN_OBSERVER" in ss,
"conversion_preserved":"PAPER conversion audit" in ss,
"expiry_preserved":"OPTION_EXPIRY_FALLBACK" in ss,
}
print("="*108); print("APLUS DHAN 429 RELIABILITY V2 VERIFY")
for k,v in checks.items(): print("PASS" if v else "FAIL",k)
print("="*108)
raise SystemExit(0 if all(checks.values()) else 1)
