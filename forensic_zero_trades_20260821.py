from __future__ import annotations
import csv,json,re
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DAY="2026-08-21"
REPORTS=ROOT/"data"/"reports"
LOG=ROOT/"logs"/"scanner.log"
TARGETS=["BDL","CDSL","GVT&D","POWERGRID","POWERINDIA"]
FILES=["intraday_entry_ready.csv","intraday_fresh_movement.csv","intraday_movement_candidates.csv",
       "intraday_near_misses.csv","intraday_wait_for_pullback.csv","opening_momentum_candidates.csv",
       "intraday_stock_selection_v2.csv","paper_trades.csv"]

def read_csv(name):
    p=REPORTS/name
    if not p.exists(): return []
    try:
        with p.open("r",encoding="utf-8-sig",newline="") as h:return list(csv.DictReader(h))
    except Exception:return []

def norm(v):return str(v or "").strip().upper()
def pick(r,*ks):
    for k in ks:
        v=r.get(k)
        if v not in ("",None):return v
    return ""

print("="*118)
print("APLUS ZERO-TRADE FORENSIC - 21 AUG 2026")
print("="*118)

cycles=[]
if LOG.exists():
    for line in LOG.read_text(encoding="utf-8",errors="ignore").splitlines():
        if line.startswith(DAY) and "Intraday movement cycle" in line:
            d={"time":line[11:19]}
            for k in ("entry_ready","fresh","plans","paper_today","safety_blocked"):
                m=re.search(rf"\b{k}=([0-9]+)",line)
                d[k]=int(m.group(1)) if m else 0
            cycles.append(d)

if cycles:
    print("\nSESSION PIPELINE")
    print("cycles:",len(cycles))
    for k in ("entry_ready","fresh","plans","paper_today","safety_blocked"):
        print(f"max_{k:<16}: {max(x[k] for x in cycles)}")
    print("first entry_ready:",next((x for x in cycles if x["entry_ready"]>0),None))
    print("last cycle       :",cycles[-1])

counts=Counter()
if LOG.exists():
    for line in LOG.read_text(encoding="utf-8",errors="ignore").splitlines():
        if not line.startswith(DAY):continue
        low=line.lower()
        if "429" in line:counts["HTTP_429"]+=1
        if "fund-limit fetch failed" in low:counts["FUND_LIMIT_FAIL"]+=1
        if "scanner terminated" in low:counts["SCANNER_TERMINATED"]+=1
        if "permissionerror" in low:counts["PERMISSION_ERROR"]+=1
print("\nFAILURES")
for k,v in counts.items():print(f"{k:<22}: {v}")

latest=REPORTS/"intraday_movement_latest.json"
if latest.exists():
    try:x=json.loads(latest.read_text(encoding="utf-8"))
    except Exception:x={}
    print("\nLATEST PAYLOAD")
    print("generated_at       :",x.get("generated_at"))
    print("entry_ready        :",len(x.get("entry_ready",[]) or []))
    print("trade_plans        :",len(x.get("trade_plans",[]) or []))
    print("safety_evaluations :",len(x.get("safety_evaluations",[]) or []))

status=Counter()
for fn in FILES:
    for r in read_csv(fn):
        s=pick(r,"paper_trade_status","status","safety_decision")
        if s:status[str(s)]+=1
print("\nTOP STATUSES")
for k,v in status.most_common(20):print(f"{k:<48} {v}")

print("\nTARGET STOCK TRACE")
for sym in TARGETS:
    print("\n"+"-"*118)
    print(sym)
    found=False
    for fn in FILES:
        rows=[r for r in read_csv(fn) if norm(r.get("symbol") or r.get("underlying_symbol"))==sym]
        for r in rows[:3]:
            found=True
            print("FILE:",fn)
            print(" stage            :",pick(r,"stage"))
            print(" direction        :",pick(r,"direction"))
            print(" tier             :",pick(r,"selection_tier"))
            print(" setup            :",pick(r,"setup_family"))
            print(" quality          :",pick(r,"trade_quality_score","score"))
            print(" trend_alignment  :",pick(r,"trend_alignment_score"))
            print(" clean_trend      :",pick(r,"clean_trend_score"))
            print(" chase_risk       :",pick(r,"chase_risk_score"))
            print(" relative_volume  :",pick(r,"relative_volume"))
            print(" vwap_distance    :",pick(r,"vwap_distance_percent"))
            print(" paper_status     :",pick(r,"paper_trade_status","status"))
            print(" option_error     :",pick(r,"option_error"))
            print(" safety_decision  :",pick(r,"safety_decision"))
            print(" safety_blocks    :",pick(r,"safety_block_reasons"))
            print(" rejection_reason :",pick(r,"rejection_reason"))
    if not found:print("NO current CSV rows found.")

paper=read_csv("paper_trades.csv")
today=[r for r in paper if str(pick(r,"entry_time","trading_date")).startswith(DAY)]
print("\nAUTHORITATIVE PAPER TRADES TODAY:",len(today))

if cycles and max(x["entry_ready"] for x in cycles)>0 and max(x["plans"] for x in cycles)==0:
    print("\nCONFIRMED: ENTRY_READY existed, but ZERO option plans were created.")
    print("Failure is downstream of shortlist creation: selective gate / option-plan / safety path.")
print("="*118)
