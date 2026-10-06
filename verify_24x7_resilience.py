from pathlib import Path
import re
import py_compile

ROOT = Path(__file__).resolve().parent
required = [
    "APlus_MidSession_Token_Refresh.ps1",
    "aplus_overnight_intelligence.py",
    "aplus_24x7_supervisor.ps1",
    "install_aplus_24x7_resilience.ps1",
    "aplus_auto_start.bat",
    "aplus_preflight_check.py",
]
missing = [x for x in required if not (ROOT / x).exists()]
if missing:
    raise SystemExit("MISSING: " + ", ".join(missing))

for name in ("aplus_overnight_intelligence.py", "aplus_preflight_check.py"):
    py_compile.compile(str(ROOT / name), doraise=True)

auto = (ROOT / "aplus_auto_start.bat").read_text(encoding="utf-8-sig")
if "retry" not in auto.lower() or "15:35:00" not in auto:
    raise SystemExit("AUTO_START_RETRY_GUARD_MISSING")

news = (ROOT / "aplus_overnight_intelligence.py").read_text(encoding="utf-8")
for needle in ("news.google.com/rss/search", "dhan_dependency", "events.jsonl"):
    if needle not in news:
        raise SystemExit(f"NEWS_COMPONENT_MISSING:{needle}")

mid = (ROOT / "APlus_MidSession_Token_Refresh.ps1").read_text(encoding="utf-8-sig")
for needle in ("dhan_auto_token.py", "DHAN_TOKEN_REFRESH_OK", "NO process termination", "run_intraday_movement.bat"):
    if needle not in mid:
        raise SystemExit(f"MIDSESSION_SAFETY_MISSING:{needle}")

sup = (ROOT / "aplus_24x7_supervisor.ps1").read_text(encoding="utf-8-sig")
if "aplus_overnight_intelligence.py" not in sup:
    raise SystemExit("SUPERVISOR_NEWS_WATCH_MISSING")
if "Core trading engine is not modified" not in sup:
    raise SystemExit("TRADING_ENGINE_SAFETY_MARKER_MISSING")

print("APLUS_24X7_RESILIENCE_STATIC_OK")
print(" - unattended Dhan startup retry: present")
print(" - mid-session token refresh wrapper: present")
print(" - Dhan-independent overnight intelligence: present")
print(" - supervisor ownership of overnight collector: present")
print(" - Python syntax: OK")
print(" - trading engine safety marker: present")
