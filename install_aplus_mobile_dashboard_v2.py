from pathlib import Path
from datetime import datetime
import shutil, py_compile, re

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "aplus_live_pnl_dashboard.py"
ALERT = ROOT / "technical_alert_dashboard.py"

if not MAIN.is_file():
    raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")
if not ALERT.is_file():
    raise SystemExit("FAIL: technical_alert_dashboard.py not found")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / f"backup_before_mobile_dashboard_v2_{stamp}"
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(MAIN, backup / MAIN.name)
shutil.copy2(ALERT, backup / ALERT.name)

MOBILE_HELPER = r