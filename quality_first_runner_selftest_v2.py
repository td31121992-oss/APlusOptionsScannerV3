from pathlib import Path
import py_compile
r=Path(__file__).resolve().parent
ps=[r/"opening_momentum_scanner.py",r/"paper_trade_journal.py",r/"safety_gate.py"]
for p in ps: py_compile.compile(str(p),doraise=True)
s=ps[0].read_text(encoding="utf-8"); j=ps[1].read_text(encoding="utf-8"); g=ps[2].read_text(encoding="utf-8")
assert "actionable = selective_entry_ready[:1]" not in s
assert "A_PLUS_WAIT_NO_FOLLOW_THROUGH" in s
assert 'reason = "OPTION_TARGET3"' not in j
assert '"RUNNER_TRAIL_EXIT"' in j and "gain_trail" in j
assert "maximum_trades_per_day: int = 0" in g
print("PASS: quality-first + unlimited-runner PAPER self-test")
