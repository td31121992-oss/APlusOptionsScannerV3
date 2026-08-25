from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parent
src = ROOT / "technical_alert_notifier.py"
if not src.is_file():
    raise SystemExit("FAIL: technical_alert_notifier.py missing")
py_compile.compile(str(src), doraise=True)

runbat = ROOT / "run_technical_alert_notifier.bat"
runbat.write_text("""@echo off
setlocal
cd /d "%~dp0"
python technical_alert_notifier.py
""", encoding="utf-8")

print("="*82)
print("SUCCESS: TECHNICAL ALERT SOUND/POPUP MODULE INSTALLED")
print("INFO       -> silent")
print("WATCH      -> soft single beep")
print("STRONG     -> directional double beep + Windows popup")
print("A+         -> directional 3-tone alert + Windows popup")
print("Duplicate prevention -> persistent event-id state")
print("Old-alert flood prevention -> baseline on first start")
print("No scanner changes. No Dhan calls. No order authority.")
print("="*82)
