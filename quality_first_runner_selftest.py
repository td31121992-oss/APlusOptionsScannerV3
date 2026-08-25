from pathlib import Path
import py_compile
r=Path(__file__).resolve().parent
for f in ["opening_momentum_scanner.py","paper_trade_journal.py","safety_gate.py"]:
    py_compile.compile(str(r/f),doraise=True)
sc=(r/"opening_momentum_scanner.py").read_text(encoding="utf-8")
pj=(r/"paper_trade_journal.py").read_text(encoding="utf-8")
sg=(r/"safety_gate.py").read_text(encoding="utf-8")
assert "selective_entry_ready[:1]" not in sc
assert "A_PLUS_WAIT_NO_FOLLOW_THROUGH" in sc
assert "A_PLUS_WAIT_INTRADAY_CONFLICT" in sc
assert "RUNNER_TRAIL_EXIT" in pj
assert 'reason = "OPTION_TARGET3"' not in pj
assert "runner_stop" in pj
assert "maximum_trades_per_day: int = 0" in sg
print("ALL QUALITY-FIRST / RUNNER SELF-TESTS PASSED")
print("PAPER ONLY")
