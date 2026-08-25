from pathlib import Path
import py_compile
ROOT=Path(__file__).resolve().parent
for n in ("technical_alert_engine.py","technical_alert_dashboard.py"):
    p=ROOT/n
    if not p.is_file():raise SystemExit("FAIL missing "+n)
    py_compile.compile(str(p),doraise=True)

# Optional daily technical level file template.
ref=ROOT/"data"/"reference";ref.mkdir(parents=True,exist_ok=True)
levels=ref/"technical_levels_latest.csv"
if not levels.exists():
    levels.write_text("symbol,prev_day_high,prev_day_low,high_5d,low_5d,high_10d,low_10d,high_30d,low_30d,high_90d,low_90d,high_52w,low_52w,ema20,sma50,sma100,sma200,supertrend_level\n",encoding="utf-8")

(ROOT/"run_technical_alert_engine.bat").write_text("""@echo off
setlocal
cd /d "%~dp0"
python technical_alert_engine.py
""",encoding="utf-8")
(ROOT/"run_technical_alert_dashboard.bat").write_text("""@echo off
setlocal
cd /d "%~dp0"
start "" "http://127.0.0.1:8766"
python technical_alert_dashboard.py
""",encoding="utf-8")

print("="*86)
print("SUCCESS: APLUS TECHNICAL ALERT SYSTEM INSTALLED")
print("Active from existing scanner data:")
print("  Opening Range BO/BD, VWAP crosses, Open-Low/Open-High confirmation")
print("  Relative Volume 2x/3x, Gap Continuation/Failure")
print("  Top-5 rank entry, 5-minute acceleration, round-level crosses")
print("  Sector-relative context and A+ confluence grading")
print("Optional historical-level interface:")
print("  Prev Day H/L, 5D,10D,30D,90D,52W, EMA20,SMA50/100/200, Supertrend")
print("  These fire automatically when technical_levels_latest.csv contains levels.")
print("Storage:")
print("  all_alerts.jsonl + per-stock daily JSON + latest JSON/CSV")
print("Telegram:")
print("  STRONG and A+ only, reusing CAlphaTrader:Telegram keyring credentials")
print("NO LIVE ORDERS. ZERO additional Dhan API calls.")
print("="*86)
