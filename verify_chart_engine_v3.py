from pathlib import Path
import csv, json
ROOT=Path(__file__).resolve().parent
P=ROOT/"data"/"chart_engine_research_v3"/"2026-08-20"
print("="*88)
print("APlus Chart Engine V3 Verification")
print("="*88)
for n in ["run_manifest.json","v3_cohort_comparison.csv","v3_detections.csv","v3_true_positives.csv","v3_false_positives.csv"]:
    p=P/n
    print(f"{n:<30} exists={p.exists()} size={p.stat().st_size if p.exists() else 0}")
if (P/"run_manifest.json").exists():
    print((P/"run_manifest.json").read_text(encoding="utf-8"))
print("="*88)
