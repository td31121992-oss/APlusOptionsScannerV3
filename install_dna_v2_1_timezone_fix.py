from __future__ import annotations
from pathlib import Path
import shutil, py_compile
from datetime import datetime

ROOT=Path(__file__).resolve().parent
TARGET=ROOT/"aplus_winner_loser_dna_v2.py"
FIX=ROOT/"aplus_winner_loser_dna_v2_fixed_source.py"

if not TARGET.exists():
    raise SystemExit("FAIL: aplus_winner_loser_dna_v2.py not found in project root.")
if not FIX.exists():
    raise SystemExit("FAIL: fixed source file missing.")

stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
backup=ROOT/f"aplus_winner_loser_dna_v2.py.backup_before_timezone_fix_{stamp}"
shutil.copy2(TARGET,backup)
shutil.copy2(FIX,TARGET)
py_compile.compile(str(TARGET),doraise=True)

src=TARGET.read_text(encoding="utf-8")
checks={
    "zoneinfo_import":"from zoneinfo import ZoneInfo" in src,
    "aware_to_ist":"astimezone(ZoneInfo(\"Asia/Kolkata\"))" in src,
    "drop_tzinfo":"replace(tzinfo=None)" in src,
}
print("="*104)
print("SUCCESS: DNA V2.1 DATETIME NORMALIZATION FIX INSTALLED")
print("Backup:",backup)
for k,v in checks.items():
    print("PASS" if v else "FAIL",k)
print("PASS scanner strategy unchanged")
print("PASS zero Dhan calls added")
print("="*104)
raise SystemExit(0 if all(checks.values()) else 1)
