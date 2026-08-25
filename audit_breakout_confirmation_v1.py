from pathlib import Path
import ast
p=Path("intraday_movement_engine.py")
s=p.read_text(encoding="utf-8");ast.parse(s)
checks={
"marker":"APLUS_BREAKOUT_CONFIRMATION_V1" in s,
"clearance":"def _breakout_clearance" in s,
"close_confirmation":"close_confirmed" in s,
"live_hold":"live_holding" in s,
"old_fresh_touch_removed":'return price >= max(float(c.high) for c in window)' not in s,
"old_cont_touch_removed":'price >= max(float(c.high) for c in reference)' not in s,
}
print("="*108);print("APLUS BREAKOUT CONFIRMATION V1 SOURCE AUDIT")
for k,v in checks.items():print("PASS" if v else "FAIL",k)
print("="*108)
raise SystemExit(0 if all(checks.values()) else 1)
