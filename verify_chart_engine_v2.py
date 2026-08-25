from pathlib import Path
import csv, json

ROOT=Path(__file__).resolve().parent
P=ROOT/"data"/"chart_engine_research_v2"/"2026-08-20"
print("="*86)
print("APlus Chart Engine V2 Output Verification")
print("="*86)
for name in ["run_manifest.json","cohort_comparison.csv","symbol_summary.csv","ranked_symbols.csv","state_transitions.csv"]:
    p=P/name
    print(f"{name:<28} exists={p.exists()} size={p.stat().st_size if p.exists() else 0}")
if (P/"run_manifest.json").exists():
    print((P/"run_manifest.json").read_text(encoding="utf-8"))
print("="*86)
