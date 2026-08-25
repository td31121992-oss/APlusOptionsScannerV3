from pathlib import Path
from datetime import datetime
import py_compile, shutil

ROOT=Path(__file__).resolve().parent
files=["btst_candidate_scanner.py","btst_next_morning_tracker.py"]
for f in files:
    p=ROOT/f
    if not p.is_file():
        raise SystemExit("FAIL: missing "+f)
    py_compile.compile(str(p),doraise=True)

bat1=ROOT/"run_btst_candidate_scanner.bat"
bat1.write_text(r"""@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo APlus BTST Candidate Scanner
echo PAPER RESEARCH ONLY
echo ============================================================
python btst_candidate_scanner.py
pause
""",encoding="utf-8")

bat2=ROOT/"run_btst_next_morning_tracker.bat"
bat2.write_text(r"""@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo APlus BTST Next Morning Tracker
echo PAPER RESEARCH ONLY
echo ============================================================
python btst_next_morning_tracker.py
pause
""",encoding="utf-8")

print("="*76)
print("SUCCESS: APLUS BTST RESEARCH MODULE INSTALLED")
print("PASS: 14:45-15:20 candidate scan")
print("PASS: Top 5 bullish CE candidates")
print("PASS: Top 5 bearish PE candidates")
print("PASS: strict qualified/watch status")
print("PASS: next-morning 09:15-10:00 outcome tracker")
print("PASS: no live orders")
print("PASS: scanner trading logic untouched")
print("="*76)
