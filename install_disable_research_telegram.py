from pathlib import Path
from datetime import datetime
import py_compile, shutil, re
ROOT=Path(__file__).resolve().parent
TARGET=ROOT/"technical_alert_engine.py"
if not TARGET.is_file(): raise SystemExit("FAIL: technical_alert_engine.py not found")
stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
backup=ROOT/f"backup_before_technical_telegram_silence_{stamp}"
backup.mkdir(parents=True,exist_ok=False)
shutil.copy2(TARGET,backup/TARGET.name)
try:
    s=TARGET.read_text(encoding="utf-8")
    s,n=re.subn(r'(?m)^TELEGRAM_MIN_GRADE\s*=\s*\d+.*$',
                'TELEGRAM_MIN_GRADE = 99  # research/technical Telegram OFF',s,count=1)
    if n!=1: raise RuntimeError(f"TELEGRAM_MIN_GRADE anchor count={n}")
    TARGET.write_text(s,encoding="utf-8")
    py_compile.compile(str(TARGET),doraise=True)
except Exception:
    shutil.copy2(backup/TARGET.name,TARGET)
    print("INSTALL FAILED - restored automatically.")
    print("Backup:",backup)
    raise
print("="*90)
print("SUCCESS: TECHNICAL/RESEARCH TELEGRAM ALERTS DISABLED")
print("Backup:",backup)
print("ENTRY/EXIT Telegram watcher untouched")
print("Scanner health alerts untouched")
print("Trading logic untouched")
print("="*90)
