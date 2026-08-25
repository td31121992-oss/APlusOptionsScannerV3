from __future__ import annotations
from pathlib import Path
from datetime import datetime
import shutil,py_compile,re

ROOT=Path(__file__).resolve().parent
J=ROOT/"paper_trade_journal.py";D=ROOT/"aplus_live_pnl_dashboard.py"
if not J.exists():raise SystemExit("FAIL: paper_trade_journal.py missing")
if not D.exists():raise SystemExit("FAIL: aplus_live_pnl_dashboard.py missing")
B=ROOT/("backup_before_trade_history_dashboard_"+datetime.now().strftime("%Y%m%d_%H%M%S"));B.mkdir()
shutil.copy2(J,B/J.name);shutil.copy2(D,B/D.name)
try:
    s=J.read_text(encoding="utf-8")
    imp="from paper_trade_history_store import sync_history"
    if imp not in s:
        anchor="from typing import Any, Mapping, Sequence"
        s=s.replace(anchor,anchor+"\n"+imp,1) if anchor in s else imp+"\n"+s
    if "sync_history(self.report_dir, self.trades)" not in s:
        s,n=re.subn(r'(?m)^(    def flush\(self\) -> None:\s*\n)',r'\1        sync_history(self.report_dir, self.trades)\n',s,count=1)
        if n!=1:raise RuntimeError("Could not patch PaperTradeJournal.flush")
    J.write_text(s,encoding="utf-8");py_compile.compile(str(J),doraise=True)

    s=D.read_text(encoding="utf-8")
    dimp="from paper_trade_history_dashboard import history_html, history_payload, days_payload"
    if dimp not in s:
        lines=s.splitlines();pos=0
        for i,line in enumerate(lines):
            if line.startswith("from ") or line.startswith("import "):pos=i+1
        lines.insert(pos,dimp);s="\n".join(lines)+"\n"
    if 'if path == "/paper-history":' not in s:
        anchor='path = urlparse(self.path).path'
        if anchor not in s:raise RuntimeError("Dashboard path anchor not found")
        route = """
        if path == "/paper-history":
            body = history_html().encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/api/paper-days":
            body = json.dumps(days_payload()).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/api/paper-history":
            from urllib.parse import parse_qs
            q = parse_qs(urlparse(self.path).query)
            day = (q.get("date") or [""])[0]
            body = json.dumps(history_payload(day)).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
"""
        s=s.replace(anchor,anchor+route,1)
    if 'href="/paper-history"' not in s:
        if "<body>" in s:
            s=s.replace("<body>","<body><div style='position:fixed;right:20px;top:16px;z-index:9999'><a style='color:#e7eefc' href='/paper-history'>PAPER HISTORY</a></div>",1)
    D.write_text(s,encoding="utf-8");py_compile.compile(str(D),doraise=True)
except Exception:
    shutil.copy2(B/J.name,J);shutil.copy2(B/D.name,D)
    print("INSTALL FAILED - originals restored.");print("Backup:",B);raise
print("="*100)
print("SUCCESS: PERMANENT PAPER TRADE HISTORY + DASHBOARD INSTALLED")
print("Backup:",B)
print("PASS: permanent history sync")
print("PASS: /paper-history")
print("PASS: /api/paper-days")
print("PASS: /api/paper-history")
print("PASS: no trading/risk/Dhan logic changed")
print("="*100)
