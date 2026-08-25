from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parent
src = ROOT / "top_bottom_from_open_history.py"
if not src.is_file():
    raise SystemExit("FAIL: top_bottom_from_open_history.py missing")

py_compile.compile(str(src), doraise=True)

(ROOT / "run_top_bottom_from_open_history.bat").write_text(
"""@echo off
setlocal
cd /d "%~dp0"
python top_bottom_from_open_history.py
""",
encoding="utf-8"
)

print("=" * 82)
print("SUCCESS: TOP/BOTTOM FROM OPEN HISTORY INSTALLED")
print("Tracks Top 5 and Bottom 5 separately through the entire session.")
print("Records ENTER / RE_ENTER / EXIT / RANK_CHANGE with exact time.")
print("Stores per-stock daily history + snapshots + CSV/JSON latest reports.")
print("Uses existing Market Watch JSON only. Zero extra Dhan API calls.")
print("=" * 82)
