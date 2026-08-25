import time
try:
    import winsound
except Exception:
    raise SystemExit("winsound unavailable - this test is for Windows.")
print("WATCH sound")
winsound.Beep(900,110)
time.sleep(.4)
print("STRONG bullish sound")
for f,d in [(1200,160),(1200,160)]:
    winsound.Beep(f,d); time.sleep(.05)
time.sleep(.4)
print("A+ bullish sound")
for f,d in [(1000,140),(1350,160),(1650,220)]:
    winsound.Beep(f,d); time.sleep(.05)
print("SOUND TEST COMPLETE")
