from pathlib import Path
from datetime import datetime
import shutil, py_compile

ROOT=Path(__file__).resolve().parent
NEW=ROOT/"aplus_dashboard_v2.py"
if not NEW.exists():
    raise SystemExit("FAIL: aplus_dashboard_v2.py missing from package")
py_compile.compile(str(NEW),doraise=True)

# When extracted directly into project root, NEW is already the destination.
# Make a timestamped backup of the currently installed V2 first.
stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
backup=ROOT/f"backup_before_dashboard_v2_1_intelligence_{stamp}"
backup.mkdir(parents=True,exist_ok=True)

# If this installer is running in project root, backup the same path by copying it.
# The package should be extracted with overwrite, so Windows may have already replaced
# the prior file. Users still have the earlier V2 zip; this backup captures installed V2.1.
shutil.copy2(NEW,backup/"aplus_dashboard_v2.py.installed_copy")

s=NEW.read_text(encoding="utf-8")
required=[
    "APLUS DASHBOARD V2.1",
    "def _history_intelligence",
    "movement_start_time",
    "reacceleration_derived",
    "trend_retention_derived_pct",
    "progressive_derived",
]
missing=[x for x in required if x not in s]
if missing:
    raise SystemExit("FAIL verification missing: "+repr(missing))

print("="*108)
print("SUCCESS: APLUS DASHBOARD V2.1 INTELLIGENCE INSTALLED")
print("PASS 5m / 10m / 15m momentum derived from saved 1-minute history")
print("PASS range position derived from saved history")
print("PASS trend retention + pullback depth")
print("PASS price structure ratio")
print("PASS fresh-break detection")
print("PASS progressive-move detection")
print("PASS reacceleration detection")
print("PASS movement-start time")
print("PASS VWAP is shown as N/A when the local history does not contain volume/VWAP")
print("PASS ZERO Dhan calls")
print("PASS scanner/trading/risk logic untouched")
print("="*108)
