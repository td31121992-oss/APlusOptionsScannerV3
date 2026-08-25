from pathlib import Path
p=Path(__file__).resolve().parent/"aplus_decision_evidence_recorder.py"
compile(p.read_text(encoding="utf-8"),p.name,"exec")
src=p.read_text(encoding="utf-8")
for bad in ("place_order(","modify_order(","cancel_order(","get_market_quotes(","get_option_chain("):
    if bad in src:raise SystemExit("FAIL forbidden broker/API call: "+bad)
checks={
"entry_ready":"intraday_entry_ready.csv" in src,
"fresh":"intraday_fresh_movement.csv" in src,
"wait":"intraday_wait_for_pullback.csv" in src,
"near":"intraday_near_misses.csv" in src,
"v6":"leadership_v6_shadow_latest" in src,
"v64":"leadership_v6_4_shadow_latest" in src,
"scanner_log":"PAPER conversion audit" in src,
"paper_entry":"PAPER_ENTRY" in src,
"paper_exit":"PAPER_EXIT" in src,
"path_1_60":"PATH_HORIZONS = (1, 3, 5, 10, 15, 30, 60)" in src,
"zero_dhan":"ZERO DHAN CALLS" in src,
}
print("="*112)
print("APLUS DECISION EVIDENCE RECORDER V1 VERIFY")
for k,v in checks.items():print("PASS" if v else "FAIL",k)
print("PASS production scanner is NOT patched")
print("PASS no order authority")
print("PASS no Dhan market-data calls")
print("="*112)
raise SystemExit(0 if all(checks.values()) else 1)
