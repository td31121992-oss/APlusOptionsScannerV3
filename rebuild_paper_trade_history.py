from pathlib import Path
import csv,json
from paper_trade_history_store import sync_history
ROOT=Path(__file__).resolve().parent;REPORTS=ROOT/"data"/"reports";rows=[];seen=set()
def add(p):
    rp=str(p.resolve())
    if rp in seen:return
    seen.add(rp)
    low=str(p).lower()
    if "selftest_paper_trade_pipeline" in low or "paper_trade_history" in p.name.lower():return
    try:
        if p.suffix.lower()==".csv":
            with p.open("r",encoding="utf-8-sig",newline="") as h:rows.extend(dict(x) for x in csv.DictReader(h))
        elif p.suffix.lower()==".json":
            obj=json.loads(p.read_text(encoding="utf-8"));arr=(obj.get("paper_trades") or obj.get("trades") or []) if isinstance(obj,dict) else (obj if isinstance(obj,list) else [])
            rows.extend(dict(x) for x in arr if isinstance(x,dict))
    except Exception:pass
for p in [REPORTS/"paper_trades.csv",REPORTS/"paper_trades_latest.json"]:
    if p.exists():add(p)
for pat in ("backup*/**/paper_trades.csv","backup*/**/paper_trades_latest.json","backup*/**/paper_trade_journal.json"):
    for p in ROOT.glob(pat):
        if p.is_file():add(p)
print("APLUS PAPER TRADE HISTORY REBUILD")
print("source rows:",len(rows),"source files:",len(seen))
print(sync_history(REPORTS,rows))
