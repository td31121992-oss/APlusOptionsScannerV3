
from pathlib import Path
import ast

p = Path("paper_trade_journal.py")
s = p.read_text(encoding="utf-8")
ast.parse(s)

checks = {
    "marker": "APLUS_OPTION_TAPE_V1" in s,
    "helper": "def _append_option_tape" in s,
    "call": "self._append_option_tape(trade, when, price)" in s,
    "update_method": ("def update_open_positions" in s or "def update_positions" in s),
}

print("=" * 100)
print("APLUS OPTION TAPE V1.1 AUDIT")
for k, v in checks.items():
    print("PASS" if v else "FAIL", k)
print("=" * 100)

raise SystemExit(0 if all(checks.values()) else 1)
