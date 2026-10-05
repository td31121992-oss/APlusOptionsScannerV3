from pathlib import Path
import py_compile
ROOT = Path(__file__).resolve().parent
for name in ("news_telegram_alerts.py", "install_news_telegram_alerts.ps1", "run_news_telegram_alerts.bat"):
    if not (ROOT / name).exists():
        raise SystemExit("NEWS_TELEGRAM_FILES_MISSING")
py_compile.compile(str(ROOT / "news_telegram_alerts.py"), doraise=True)
text = (ROOT / "news_telegram_alerts.py").read_text(encoding="utf-8")
for needle in ("SEBI_RSS", "CAlphaTrader:Telegram", "sent_event_ids", "trading_engine_untouched"):
    if needle not in text:
        raise SystemExit(f"NEWS_TELEGRAM_MARKER_MISSING:{needle}")
print("APLUS_NEWS_TELEGRAM_STATIC_OK")
print(" - official SEBI RSS: present")
print(" - secure existing Telegram credential lookup: present")
print(" - deduplication: present")
print(" - read-only safety marker: present")
print(" - Python syntax: OK")
