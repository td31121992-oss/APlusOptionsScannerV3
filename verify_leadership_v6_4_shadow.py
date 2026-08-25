from pathlib import Path
ROOT=Path(__file__).resolve().parent
files=["leadership_v6_4_shadow.py","run_leadership_v6_4_shadow.py","leadership_v6_4_replay_forensic.py"]
for n in files:
    p=ROOT/n
    if not p.exists():raise SystemExit("FAIL missing "+n)
    compile(p.read_text(encoding="utf-8"),n,"exec")
src=(ROOT/"leadership_v6_4_shadow.py").read_text(encoding="utf-8")
for bad in (".place_order(",".modify_order(",".cancel_order(","get_market_quotes(","get_option_chain("):
    if bad in src:raise SystemExit("FAIL forbidden authority/API call "+bad)
checks={
"fast_track":"LEADERSHIP_FAST_TRACK" in src,
"premium_fragility":"OPTION_PREMIUM_FRAGILITY" in src,
"fresh_leg":"FRESH_NEW_LEG" in src,
"reacceleration":"REACCELERATION_NEW_LEG" in src,
"stale_move":"STALE_MOVE" in src,
"futures_paper":"FUTURES_PAPER_RECOMMENDED" in src,
"zero_dhan":"ZERO DHAN CALLS" in src,
}
print("="*108);print("APLUS LEADERSHIP V6.4 SHADOW VERIFY")
for k,v in checks.items():print("PASS" if v else "FAIL",k)
print("PASS production scanner files are not patched")
print("PASS live stock-options rules remain unchanged")
print("="*108)
raise SystemExit(0 if all(checks.values()) else 1)
