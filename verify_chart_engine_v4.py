from pathlib import Path
import json
ROOT=Path(__file__).resolve().parent
P=ROOT/"data"/"chart_engine_research_v4"/"2026-08-20"
print("="*88)
print("APlus Chart Engine V4 Verification")
print("="*88)
for n in ["run_manifest.json","trade_episodes.csv","trade_episode_detail.csv","key_case_episodes.csv","no_confirmation_symbols.csv"]:
    p=P/n
    print(f"{n:<30} exists={p.exists()} size={p.stat().st_size if p.exists() else 0}")
if (P/"run_manifest.json").exists(): print((P/"run_manifest.json").read_text(encoding="utf-8"))
print("="*88)
