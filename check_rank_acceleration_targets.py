from __future__ import annotations
import csv, json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
P=ROOT/"data"/"reports"/"time_relative_ranking_latest.csv"
TARGETS=["BDL","CDSL","GVT&D","POWERINDIA","POWERGRID"]

if not P.exists():
    raise SystemExit("Run time_relative_ranking_engine.py first.")

with P.open("r",encoding="utf-8-sig",newline="") as f:
    rows={r["symbol"]:r for r in csv.DictReader(f)}

print("="*105)
print("APLUS TARGET STOCK RANK-ACCELERATION CHECK")
print("="*105)
for s in TARGETS:
    r=rows.get(s)
    if not r:
        print(f"{s:<14} NOT PRESENT")
        continue
    print(
        f"{s:<14} dir={r['direction']:<4} rank={r['current_rank']:>3} "
        f"5m={r['rank_change_5m']:>4} 10m={r['rank_change_10m']:>4} 15m={r['rank_change_15m']:>4} "
        f"move={float(r['from_open_pct']):>7.3f}% move5={float(r['move_change_5m_pct']):>7.3f}% "
        f"state={r['rank_acceleration_state']:<12} score={float(r['rank_acceleration_score']):>7.2f}"
    )
print("="*105)
