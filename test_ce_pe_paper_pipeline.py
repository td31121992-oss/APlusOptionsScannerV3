from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
import json, shutil

from paper_trade_journal import PaperTradeJournal

ROOT=Path(__file__).resolve().parent
BASE=ROOT/"data"/"selftest_paper_trade_pipeline"
STATE=BASE/"state"
REPORTS=BASE/"reports"

if BASE.exists():
    shutil.rmtree(BASE)
STATE.mkdir(parents=True,exist_ok=True)
REPORTS.mkdir(parents=True,exist_ok=True)

journal=PaperTradeJournal(state_dir=STATE,report_dir=REPORTS,rearm_minutes=5)

# Prevent real Telegram messages during this isolated smoke test.
class SilentNotifier:
    def notify_entry(self, record):
        print("TEST NOTIFIER ENTRY:",record.get("symbol"),record.get("option_type"),record.get("entry_price"))
    def notify_exit(self, record):
        print("TEST NOTIFIER EXIT :",record.get("symbol"),record.get("option_type"),record.get("exit_price"),record.get("net_pnl"))

journal.notifier=SilentNotifier()

now=datetime.now().astimezone()

def make_plan(symbol,direction,opt_type,sid,strike,price,qty):
    return {
        "symbol":symbol,
        "direction":direction,
        "stage":"ENTRY_READY",
        "setup_family":"SELFTEST_PIPELINE",
        "selection_tier":"A_PLUS",
        "momentum_score":95.0,
        "movement_capture_score":92.0,
        "trend_alignment_score":90.0,
        "clean_trend_score":92.0,
        "chase_risk_score":0.0,
        "pivot_state":"SELFTEST",
        "recent_move_15m_percent":0.75,
        "underlying":{
            "entry":1000.0,
            "stop_loss":995.0,
            "target1":1010.0,
            "target2":1020.0,
            "target3":1030.0,
            "risk_percent":0.5,
        },
        "option_contract":{
            "transaction":"BUY",
            "option_type":opt_type,
            "security_id":sid,
            "trading_symbol":f"SELFTEST-{opt_type}-{int(strike)}",
            "expiry":"2099-12-31",
            "strike":strike,
            "ltp":price,
            "bid":price-0.10,
            "ask":price,
            "limit_price":price,
            "stop_loss":round(price*0.90,2),
            "target1":round(price*1.10,2),
            "target2":round(price*1.20,2),
            "target3":round(price*1.30,2),
            "lot_size":qty,
            "lots":1,
            "quantity":qty,
            "total_premium":round(price*qty,2),
            "total_risk":round(price*qty*0.10,2),
            "oi":10000,
            "volume":5000,
            "iv":20.0,
            "spread_percent":0.4,
            "selection_score":95.0,
        },
        "safety_gate":{
            "decision":"PASS",
            "block_reasons":[],
            "warnings":["SELFTEST_ONLY"],
        },
        "reasons":["SELFTEST synthetic paper pipeline"],
    }

candidate_ce={
    "symbol":"SELFTESTCE","direction":"BULLISH","stage":"ENTRY_READY",
    "setup_family":"SELFTEST_PIPELINE","selection_tier":"A_PLUS",
}
candidate_pe={
    "symbol":"SELFTESTPE","direction":"BEARISH","stage":"ENTRY_READY",
    "setup_family":"SELFTEST_PIPELINE","selection_tier":"A_PLUS",
}

print("="*100)
print("APLUS PAPER TRADE PIPELINE SMOKE TEST")
print("ISOLATED SELFTEST - NO DHAN CALLS - NO LIVE ORDERS - NO PRODUCTION JOURNAL CHANGES")
print("="*100)

ce_plan=make_plan("SELFTESTCE","BULLISH","CE","990001",1000,10.0,50)
pe_plan=make_plan("SELFTESTPE","BEARISH","PE","990002",1000,12.0,50)

ce=journal.record_trade(plan=ce_plan,candidate=candidate_ce,when=now)
pe=journal.record_trade(plan=pe_plan,candidate=candidate_pe,when=now+timedelta(seconds=1))
journal.flush()

print("\nENTRY TEST")
print("CE:",ce["paper_trade_id"],ce["status"],ce["option_type"],"entry",ce["entry_price"],"capital",ce["capital_deployed"],"risk%",ce["planned_risk_percent"])
print("PE:",pe["paper_trade_id"],pe["status"],pe["option_type"],"entry",pe["entry_price"],"capital",pe["capital_deployed"],"risk%",pe["planned_risk_percent"])

# Feed synthetic option prices and force-close after a favorable move.
quotes={
    "990001":{"ltp":11.50},
    "990002":{"ltp":13.80},
}
closed=journal.update_open_positions(
    option_quotes=quotes,
    when=now+timedelta(minutes=5),
    force_close=True,
    force_close_reason="SELFTEST_EXIT",
)
journal.flush()

print("\nEXIT TEST")
for t in closed:
    print(t["symbol"],t["option_type"],t["status"],
          "entry",t["entry_price"],"exit",t["exit_price"],
          "net_pnl",t["net_pnl"],"return%",t["return_percent"],
          "reason",t["exit_reason"])

open_left=journal.open_positions(now+timedelta(minutes=5))
print("\nOPEN POSITIONS LEFT:",len(open_left))

report_json=REPORTS/"paper_trades_latest.json"
report_csv=REPORTS/"paper_trades.csv"
print("JSON EXISTS:",report_json.exists(),report_json)
print("CSV EXISTS :",report_csv.exists(),report_csv)

ok=(
    ce.get("status")=="CLOSED" and pe.get("status")=="CLOSED" and
    len(closed)==2 and len(open_left)==0 and
    report_json.exists() and report_csv.exists()
)
print("\nRESULT:", "PASS - CE AND PE PAPER PIPELINE WORKS" if ok else "FAIL")
print("NOTE: This proves paper journal entry/exit persistence works.")
print("NOTE: It does NOT test live Dhan option-plan creation, because market/API data is not used.")
print("="*100)
raise SystemExit(0 if ok else 1)
