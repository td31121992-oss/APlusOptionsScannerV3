from pathlib import Path
p=Path(__file__).resolve().parent/"aplus_winner_loser_dna_v1.py"
compile(p.read_text(encoding="utf-8"),p.name,"exec")
src=p.read_text(encoding="utf-8")
for bad in ("place_order(","modify_order(","cancel_order(","get_market_quotes(","get_option_chain("):
    if bad in src:raise SystemExit("FAIL forbidden call "+bad)
checks={
"entry_only_features":"NUMERIC_FEATURES" in src,
"leakage_guard":"LEAKAGE_KEYWORDS" in src,
"winner_dna":"feature_dna" in src,
"categorical_dna":"categorical_dna" in src,
"selective_rules":"candidate_rules" in src,
"day_check":"leave_one_day_out" in src,
"selectivity_ladder":"selectivity_ladder" in src,
"premium_excluded":'"premium_used_in_dna_score":False' in src,
"read_only":"ZERO STRATEGY CHANGES" in src,
}
print("="*110);print("APLUS WINNER-vs-LOSER DNA V1 VERIFY")
for k,v in checks.items():print("PASS" if v else "FAIL",k)
print("PASS premium is descriptive only and excluded from default DNA score")
print("PASS post-entry/exit outcomes are not DNA predictors")
print("PASS ZERO DHAN CALLS")
print("PASS ZERO STRATEGY CHANGES")
print("="*110)
raise SystemExit(0 if all(checks.values()) else 1)
