from pathlib import Path
import py_compile
r=Path(__file__).resolve().parent
checks={'config.py':['paper_trade_rearm_minutes: int = 180'],'opening_momentum_scanner.py':['selective_entry_ready[:1]','A_PLUS_WAIT_PIVOT_TO_R1','A_PLUS_WAIT_OVEREXTENDED','A_PLUS_WAIT_WEAK_PARTICIPATION'],'option_selector.py':['stop_loss = self._round_up('],'safety_gate.py':['maximum_trades_per_day: int = 6']}
for f,needles in checks.items():
 p=r/f; s=p.read_text(encoding='utf-8')
 for n in needles: assert n in s,(f,n)
 py_compile.compile(str(p),doraise=True)
print('ALL A+ SELECTIVE PATCH SELF-TESTS PASSED')
print('PAPER ONLY')
