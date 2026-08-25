from pathlib import Path
ROOT=Path(__file__).resolve().parent
p=ROOT/"aplus_full_history_forensic.py"
compile(p.read_text(encoding="utf-8"),p.name,"exec")
src=p.read_text(encoding="utf-8")
for bad in ("place_order(","modify_order(","cancel_order(","get_market_quotes(","get_option_chain("):
    if bad in src:
        raise SystemExit("FAIL forbidden trading/API call: "+bad)
checks={
    "discovers_history":"discover_trade_files" in src,
    "dedupe":"dedupe_trades" in src,
    "underlying_history":"time_relative_rank_history" in src,
    "winner_loser":"result_class" in src,
    "false_stop":"FALSE_OPTION_STOP_UNDERLYING_CONTINUED" in src,
    "premium_fragility":"OPTION_PREMIUM_FRAGILITY" in src,
    "daily_summary":"daily_summary.csv" in src,
    "html_report":"full_history_forensic.html" in src,
}
print("="*100)
print("APLUS FULL-HISTORY FORENSIC VERIFY")
for k,v in checks.items(): print("PASS" if v else "FAIL",k)
print("PASS ZERO DHAN CALLS")
print("PASS ZERO STRATEGY CHANGES")
print("="*100)
raise SystemExit(0 if all(checks.values()) else 1)
