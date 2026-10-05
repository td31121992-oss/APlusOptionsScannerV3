from pathlib import Path
import py_compile
ROOT=Path(__file__).resolve().parent
for n in ("news_intelligence.py","market_event_intelligence.py","run_market_event_intelligence.bat","install_market_event_intelligence.ps1"):
    if not (ROOT/n).exists():raise SystemExit("MARKET_EVENT_FILES_MISSING")
for n in ("news_intelligence.py","market_event_intelligence.py"):py_compile.compile(str(ROOT/n),doraise=True)
t=(ROOT/"market_event_intelligence.py").read_text(encoding="utf-8")
for x in ("SEBI_RSS","CAlphaTrader:Telegram","RBI MPC October 2026","TCS Q2 FY27 results","trading_engine_untouched"):
    if x not in t:raise SystemExit("MARKET_EVENT_MARKER_MISSING:"+x)
print("APLUS_MARKET_EVENT_INTELLIGENCE_STATIC_OK")
