from pathlib import Path
import py_compile
ROOT=Path(__file__).resolve().parent
p=ROOT/"technical_alert_engine.py"
py_compile.compile(str(p),doraise=True)
s=p.read_text(encoding="utf-8")
ok="TELEGRAM_MIN_GRADE = 99" in s
print("="*84)
print("APLUS TELEGRAM ALERT POLICY VERIFY")
print("="*84)
print("research Telegram disabled :",ok)
print("technical storage retained :", "self.events.insert(0,ev)" in s)
print("Telegram code still present:", "send_telegram(alert_msg(ev))" in s)
print("="*84)
raise SystemExit(0 if ok else 1)
