from __future__ import annotations

import csv, json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST=ZoneInfo("Asia/Kolkata")
ROOT=Path(__file__).resolve().parent
REPORTS=ROOT/"data"/"reports"
LATEST=REPORTS/"opening_structure_evidence_latest.json"

def n(v):
    try:return float(v)
    except:return 0.0

def main():
    if not LATEST.is_file():
        raise SystemExit("No opening structure evidence file found.")
    d=json.loads(LATEST.read_text(encoding="utf-8"))
    rows=d.get("records",[]) or []
    out=REPORTS/"opening_structure_evidence_summary.csv"
    fields=["setup_id","signals","exact_option_evidence","actual_closed","actual_wins","actual_losses",
            "actual_net_pnl","avg_actual_return_pct","avg_underlying_best_favorable_pct",
            "avg_underlying_worst_adverse_pct","avg_option_mfe","avg_option_mae"]
    result=[]
    for setup in ("OPEN_LOW_CE","OPEN_HIGH_PE"):
        a=[x for x in rows if x.get("setup_id")==setup]
        exact=[x for x in a if x.get("option_evidence_status")=="EXACT_EXISTING_SCANNER_PLAN"]
        closed=[x for x in a if x.get("actual_exit_time")]
        returns=[n(x.get("actual_return_percent")) for x in closed]
        result.append({
            "setup_id":setup,"signals":len(a),"exact_option_evidence":len(exact),"actual_closed":len(closed),
            "actual_wins":sum(n(x.get("actual_net_pnl"))>0 for x in closed),
            "actual_losses":sum(n(x.get("actual_net_pnl"))<0 for x in closed),
            "actual_net_pnl":round(sum(n(x.get("actual_net_pnl")) for x in closed),2),
            "avg_actual_return_pct":round(sum(returns)/len(returns),2) if returns else 0,
            "avg_underlying_best_favorable_pct":round(sum(n(x.get("underlying_best_favorable_pct")) for x in a)/len(a),3) if a else 0,
            "avg_underlying_worst_adverse_pct":round(sum(n(x.get("underlying_worst_adverse_pct")) for x in a)/len(a),3) if a else 0,
            "avg_option_mfe":round(sum(n(x.get("option_mfe_amount")) for x in exact)/len(exact),2) if exact else 0,
            "avg_option_mae":round(sum(n(x.get("option_mae_amount")) for x in exact)/len(exact),2) if exact else 0,
        })
    with out.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(result)
    print("="*76)
    print("OPENING STRUCTURE STEP 2 SUMMARY")
    for r in result: print(r)
    print("Saved:",out)
    print("="*76)

if __name__=="__main__":main()
