from dataclasses import dataclass
from intraday_movement_engine import IntradayMovementEngine

@dataclass
class C:
    open: float
    high: float
    low: float
    close: float

def ok(name,condition):
    print(("PASS" if condition else "FAIL"),name)
    if not condition: raise AssertionError(name)

prior=[C(99,99.5,98.8,99.3),C(99.3,99.8,99.1,99.6),C(99.6,100,99.4,99.8)]
touch=C(99.8,100.2,99.7,99.99)
confirmed=C(99.8,100.3,99.7,100.15)

ok("bull_touch_rejected", IntradayMovementEngine._breaks_recent(100.01,prior+[touch],3,bullish=True) is False)
ok("bull_close_confirmed", IntradayMovementEngine._breaks_recent(100.18,prior+[confirmed],3,bullish=True) is True)
ok("bull_live_hold_required", IntradayMovementEngine._breaks_recent(99.99,prior+[confirmed],3,bullish=True) is False)

priorb=[C(101,101.2,100.4,100.8),C(100.8,101,100.2,100.5),C(100.5,100.8,100,100.3)]
touchb=C(100.3,100.4,99.8,100.01)
confirmedb=C(100.3,100.4,99.7,99.84)

ok("bear_touch_rejected", IntradayMovementEngine._breaks_recent(99.99,priorb+[touchb],3,bullish=False) is False)
ok("bear_close_confirmed", IntradayMovementEngine._breaks_recent(99.82,priorb+[confirmedb],3,bullish=False) is True)

rows=[C(99,99.4,98.9,99.2),C(99.2,99.8,99.1,99.5),C(99.5,100,99.3,99.7),C(99.7,100.2,99.5,99.99)]
ok("continuation_touch_rejected", IntradayMovementEngine._continuation_breakout(direction="BULLISH",price=100.01,recent5=0.2,completed=rows,previous_state="WAIT_FOR_PULLBACK",healthy_pullback=False) is False)
rows[-1]=C(99.7,100.3,99.5,100.15)
ok("continuation_close_confirmed", IntradayMovementEngine._continuation_breakout(direction="BULLISH",price=100.18,recent5=0.2,completed=rows,previous_state="WAIT_FOR_PULLBACK",healthy_pullback=False) is True)

print("="*96)
print("ALL BREAKOUT CONFIRMATION V1 SELF-TESTS PASSED")
print("="*96)
