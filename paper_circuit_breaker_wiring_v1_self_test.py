from __future__ import annotations
import json, tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from opening_momentum_scanner import OpeningMomentumScanner
from safety_gate import SafetyGateConfig

IST=ZoneInfo("Asia/Kolkata")
def check(name, cond):
    print(("PASS" if cond else "FAIL"),name)
    if not cond: raise AssertionError(name)

class DummyGate:
    def __init__(self):
        self.config=SafetyGateConfig(maximum_consecutive_losses=2,fallback_account_capital=500000.0,maximum_daily_loss_percent=1.5)

def make(path):
    s=OpeningMomentumScanner.__new__(OpeningMomentumScanner)
    s.paper_portfolio_state_path=path
    s.paper_state_max_age_seconds=60
    s.safety_gate=DummyGate()
    return s

now=datetime.now(IST).replace(microsecond=0)
with tempfile.TemporaryDirectory() as td:
    p=Path(td)/"portfolio_state.json"; s=make(p)
    r=s._paper_native_circuit_breaker(now)
    check("missing_state_blocks",r["blocked"])

    p.write_text(json.dumps({"as_of":now.isoformat(),"date":now.date().isoformat(),"mode":"PAPER_NATIVE","consecutive_losses":0,"realized_pnl_today":0}),encoding="utf-8")
    check("healthy_state_passes",not s._paper_native_circuit_breaker(now)["blocked"])

    p.write_text(json.dumps({"as_of":now.isoformat(),"date":now.date().isoformat(),"mode":"PAPER_NATIVE","consecutive_losses":2,"realized_pnl_today":-1000}),encoding="utf-8")
    r=s._paper_native_circuit_breaker(now)
    check("consecutive_loss_blocks",any("CONSECUTIVE_LOSS_LIMIT" in x for x in r["reasons"]))

    p.write_text(json.dumps({"as_of":now.isoformat(),"date":now.date().isoformat(),"mode":"PAPER_NATIVE","consecutive_losses":0,"realized_pnl_today":-8000}),encoding="utf-8")
    r=s._paper_native_circuit_breaker(now)
    check("daily_loss_blocks",any("DAILY_LOSS_LIMIT" in x for x in r["reasons"]))

    old=now-timedelta(minutes=3)
    p.write_text(json.dumps({"as_of":old.isoformat(),"date":now.date().isoformat(),"mode":"PAPER_NATIVE","consecutive_losses":0,"realized_pnl_today":0}),encoding="utf-8")
    r=s._paper_native_circuit_breaker(now)
    check("stale_state_blocks",any("PAPER_STATE_STALE" in x for x in r["reasons"]))

print("="*100)
print("ALL PAPER CIRCUIT BREAKER WIRING V1 SELF-TESTS PASSED")
print("="*100)
