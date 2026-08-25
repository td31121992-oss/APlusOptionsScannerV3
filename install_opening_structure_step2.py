from pathlib import Path
import py_compile

ROOT=Path(__file__).resolve().parent
for name in ("opening_structure_evidence_engine.py","opening_structure_evidence_summary.py"):
    p=ROOT/name
    if not p.is_file(): raise SystemExit("FAIL: missing "+name)
    py_compile.compile(str(p),doraise=True)

runbat=ROOT/"run_opening_structure_evidence.bat"
runbat.write_text("""@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo APlus Opening Structure Evidence Engine - Step 2
echo PAPER RESEARCH ONLY - NO EXECUTION
echo ============================================================
python opening_structure_evidence_engine.py
pause
""",encoding="utf-8")

summarybat=ROOT/"run_opening_structure_summary.bat"
summarybat.write_text("""@echo off
setlocal
cd /d "%~dp0"
python opening_structure_evidence_summary.py
pause
""",encoding="utf-8")

print("="*82)
print("SUCCESS: OPENING STRUCTURE STEP 2 INSTALLED")
print("PASS: OPEN_LOW_CE / OPEN_HIGH_PE evidence IDs")
print("PASS: confirmation time + stock + sector context")
print("PASS: full-session underlying MFE/MAE-style tracking")
print("PASS: exact option evidence attaches when existing scanner plan/trade provides it")
print("PASS: no invented option prices when scanner has no exact option plan")
print("PASS: automatic latest JSON + CSV + daily research archive")
print("PASS: after-market setup summary")
print("PASS: zero additional Dhan API calls")
print("PASS: no live/paper execution authority")
print("="*82)
