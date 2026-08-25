from __future__ import annotations
import csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "data" / "reports"
STATE = ROOT / "data" / "intraday_movement"
SYMS = ["GLENMARK","MCX","SBICARD","MOTILALOFS","PREMIERENE"]

def load_json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def scan_csv(path, symbols):
    out=[]
    if not path.is_file():
        return out
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                sym=str(r.get("symbol") or r.get("underlying") or "").upper().strip()
                if sym in symbols:
                    x=dict(r); x["_file"]=str(path); out.append(x)
    except Exception:
        pass
    return out

print("="*110)
print("APLUS TOP-5 FROM 09:15 FORENSIC CHECK")
print("="*110)

mw=load_json(REPORTS/"fno_market_watch_latest.json")
rows={str(r.get("symbol","")).upper():r for r in mw.get("rows",[]) if isinstance(r,dict)}

print("\nCURRENT MARKET WATCH")
for s in SYMS:
    r=rows.get(s,{})
    print(f"{s:<12} 09:15={r.get('open_0915','-')} LTP={r.get('ltp','-')} gap={r.get('gap_pct','-')} from_open={r.get('from_open_pct','-')} range_pos={r.get('range_position_pct','-')} sector={r.get('sector','-')}")

names=[
"intraday_entry_ready.csv","intraday_fresh_movement.csv","intraday_wait_for_pullback.csv",
"intraday_near_misses.csv","intraday_movement_candidates.csv","opening_momentum_candidates.csv",
"opening_momentum_early_entries.csv","opening_momentum_wait_for_pullback.csv","paper_trades.csv",
"rankings.csv","technical_alerts_today.csv","top_bottom_from_open_events_latest.csv"
]

found=[]
for name in names:
    found += scan_csv(REPORTS/name,set(SYMS))

print("\nMATCHES IN TODAY'S REPORT FILES")
if not found:
    print("No matching rows found in standard CSV reports.")
else:
    keep_keys=("symbol","timestamp","time","stage","direction","setup_family","selection_tier","score",
    "trade_quality_score","movement_capture_score","trend_alignment_score","clean_trend_score",
    "chase_risk_score","relative_volume","vwap_distance_percent","recent_move_5m_percent",
    "recent_move_15m_percent","from_open_pct","move_from_0915_open_percent","event","rank",
    "alert","reason","entry_reason","paper_trade_status","status","option_type","strike",
    "entry_price","exit_price","net_pnl")
    for r in found:
        keep={k:r[k] for k in keep_keys if k in r and str(r[k]).strip() not in ("","None")}
        print("\nFILE:",Path(r["_file"]).name)
        print(json.dumps(keep,indent=2,ensure_ascii=False))

print("\nPER-SYMBOL FILE HITS")
for s in SYMS:
    hits=[]
    for base in (REPORTS,STATE,ROOT/"data"/"research"):
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in (".json",".csv",".log",".txt"):
                continue
            try:
                if p.stat().st_size > 15000000:
                    continue
                txt=p.read_text(encoding="utf-8",errors="ignore")
            except Exception:
                continue
            if s in txt.upper():
                hits.append(str(p.relative_to(ROOT)))
    print("\n"+s+":")
    if hits:
        for h in hits[:25]:
            print(" ",h)
    else:
        print("  no text-file hits")

print("\nPaste this output back into ChatGPT.")
print("="*110)
