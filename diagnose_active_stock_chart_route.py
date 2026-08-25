from pathlib import Path
import re, urllib.request

p=Path("aplus_live_pnl_dashboard.py")
s=p.read_text(encoding="utf-8")
print("="*100)
print("APLUS DASHBOARD ACTIVE-ROUTE DIAGNOSTIC")
print("="*100)
print("FILE:",p.resolve())
print("SIZE:",len(s))
print("Handler classes:",len(re.findall(r"(?m)^class\s+Handler\b",s)))
print("do_GET defs:",len(re.findall(r"(?m)^\s+def\s+do_GET\(",s)))
print("path parse occurrences:",s.count("path = urlparse(self.path).path"))
print("/stock-charts route occurrences:",s.count('if path == "/stock-charts":'))
print("STOCK CHARTS href occurrences:",s.count('href="/stock-charts"'))
print()

for label,pat in [
    ("Handler",r"(?m)^class\s+Handler\b"),
    ("do_GET",r"(?m)^\s+def\s+do_GET\("),
    ("path parse",re.escape("path = urlparse(self.path).path")),
    ("stock route",re.escape('if path == "/stock-charts":')),
]:
    print(label.upper())
    for m in re.finditer(pat,s):
        line=s.count("\n",0,m.start())+1
        print(" line",line)
    print()

try:
    body=urllib.request.urlopen("http://127.0.0.1:8765/stock-charts?diag=1",timeout=3).read().decode("utf-8","ignore")
    print("LIVE HTTP /stock-charts:")
    print("  bytes:",len(body))
    print("  has Stock Charts title:", "APlus Stock Charts / Day Replay" in body)
    print("  has Live Trading title:", "APlus Live Trading Terminal" in body)
    print("  first 180 chars:",repr(body[:180]))
except Exception as e:
    print("LIVE HTTP CHECK FAILED:",repr(e))
print("="*100)
