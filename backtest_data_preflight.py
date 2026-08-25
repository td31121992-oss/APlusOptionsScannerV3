from pathlib import Path
import pandas as pd, json, sys

root=Path(".").resolve()
cands=[root/"data"/"historical",root/"data"/"history",root/"data"/"candles",root/"data"/"research",root/"data"]
print("="*76)
print("APlus historical-data preflight (READ ONLY)")
print("="*76)
found=0
for base in cands:
    if not base.exists(): continue
    files=[p for p in base.rglob("*") if p.suffix.lower() in (".csv",".parquet",".pq")]
    if files:
        print(base,":",len(files),"candidate files")
        for p in files[:12]: print(" ",p)
        found+=len(files)
print("Candidate historical files:",found)
print("No files changed.")
