from pathlib import Path
ROOT=Path(__file__).resolve().parent
P=ROOT/"data"/"chart_engine_research_v5"/"2026-08-20"
print("="*90)
print("APlus Chart Engine V5 Verification")
print("="*90)
for n in ["run_manifest.json","v5_trade_episodes.csv","v5_fast_breakout.csv","v5_persistent_trend.csv","v5_path_comparison.csv","v5_key_cases.csv"]:
    p=P/n
    print(f"{n:<32} exists={p.exists()} size={p.stat().st_size if p.exists() else 0}")
if (P/"run_manifest.json").exists():
    print((P/"run_manifest.json").read_text(encoding="utf-8"))
print("="*90)
