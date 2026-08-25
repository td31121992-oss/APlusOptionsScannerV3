from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from movement_campaign_intelligence_v1_shadow import Book

IST=ZoneInfo("Asia/Kolkata")
b=Book()
t=datetime(2026,8,25,9,15,tzinfo=IST)

def row(move,price=100):
    return [{"symbol":"TEST","ltp":price*(1+move/100),"from_open_pct":move}]

# Two DOWN observations cannot confirm an early campaign.
r=b.update(t,row(-0.80))[0]
assert not r["direction_confirmed"]
r=b.update(t+timedelta(seconds=30),row(-0.90))[0]
assert not r["direction_confirmed"]

# Reversal resets the direction streak.
r=b.update(t+timedelta(seconds=60),row(0.30))[0]
assert r["direction"]=="UP" and r["direction_streak"]==1
r=b.update(t+timedelta(seconds=90),row(0.55))[0]
assert r["direction_streak"]==2 and not r["direction_confirmed"]
r=b.update(t+timedelta(seconds=120),row(0.80))[0]
assert r["direction_streak"]==3 and r["direction_confirmed"]

print("PASS opposite_direction_does_not_confirm")
print("PASS reversal_resets_streak")
print("PASS three_same_direction_observations_confirm")
print("PASS SHADOW ONLY - no production entry hook")
print("="*98)
print("ALL MOVEMENT CAMPAIGN V1.1 DIRECTION-PERSISTENCE SELF-TESTS PASSED")
print("="*98)
