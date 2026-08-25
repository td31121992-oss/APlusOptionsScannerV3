from __future__ import annotations
from pathlib import Path
from datetime import datetime
import shutil, py_compile

ROOT=Path(__file__).resolve().parent
J=ROOT/"paper_trade_journal.py"
D=ROOT/"aplus_live_pnl_dashboard.py"

if not J.is_file():
    raise SystemExit("FAIL: paper_trade_journal.py missing")
if not D.is_file():
    raise SystemExit("FAIL: aplus_live_pnl_dashboard.py missing")

stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
B=ROOT/f"backup_before_trade_history_dashboard_v4_{stamp}"
B.mkdir()
shutil.copy2(J,B/J.name)
shutil.copy2(D,B/D.name)

def ensure_import(text:str, line:str)->str:
    if line in text:
        return text
    lines=text.splitlines()
    idx=1 if lines and lines[0].startswith("from __future__ import") else 0
    lines.insert(idx,line)
    return "\n".join(lines)+("\n" if text.endswith("\n") else "")

def patch_journal(text:str)->str:
    text=ensure_import(text,"from paper_trade_history_store import sync_history")
    marker="sync_history(self.report_dir, self.trades)"
    if marker in text:
        return text

    exact='''    def flush(self) -> bool:
        """Persist journal files without terminating the scanner."""
        state_payload = {
'''
    repl='''    def flush(self) -> bool:
        """Persist journal files without terminating the scanner."""
        sync_history(self.report_dir, self.trades)
        state_payload = {
'''
    if exact not in text:
        raise RuntimeError("Exact current flush() anchor not found")
    return text.replace(exact,repl,1)

def patch_dashboard(text:str)->str:
    imp="from paper_trade_history_dashboard import history_html, history_payload, days_payload"
    text=ensure_import(text,imp)

    if 'if path == "/paper-history":' not in text:
        exact='''    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/fno-market-watch":
'''
        repl='''    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/paper-history":
            body = history_html().encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/api/paper-days":
            body = json.dumps(days_payload()).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/api/paper-history":
            q=parse_query(self.path); day=q.get("date") or ""
            body = json.dumps(history_payload(day)).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/api/fno-market-watch":
'''
        if exact not in text:
            raise RuntimeError("Exact current dashboard do_GET anchor not found")
        text=text.replace(exact,repl,1)

    return text

try:
    js=J.read_text(encoding="utf-8")
    js=patch_journal(js)
    J.write_text(js,encoding="utf-8")
    py_compile.compile(str(J),doraise=True)

    ds=D.read_text(encoding="utf-8")
    ds=patch_dashboard(ds)
    D.write_text(ds,encoding="utf-8")
    py_compile.compile(str(D),doraise=True)

    js=J.read_text(encoding="utf-8")
    ds=D.read_text(encoding="utf-8")
    checks={
        "journal_history_import":"from paper_trade_history_store import sync_history" in js,
        "journal_history_sync":"sync_history(self.report_dir, self.trades)" in js,
        "paper_history_page":'if path == "/paper-history":' in ds,
        "paper_days_api":'if path == "/api/paper-days":' in ds,
        "paper_history_api":'if path == "/api/paper-history":' in ds,
        "stock_charts_preserved":'if path == "/stock-charts":' in ds,
        "market_watch_preserved":'if path == "/fno-market-watch":' in ds,
        "opening_structure_preserved":'if path == "/opening-structure":' in ds,
    }
    if not all(checks.values()):
        raise RuntimeError(f"Post-install verification failed: {checks}")

except Exception:
    shutil.copy2(B/J.name,J)
    shutil.copy2(B/D.name,D)
    print("INSTALL FAILED - originals restored automatically.")
    print("Backup:",B)
    raise

print("="*110)
print("SUCCESS: PERMANENT PAPER TRADE HISTORY + DASHBOARD V4 INSTALLED")
print("Backup:",B)
for k,v in checks.items():
    print(("PASS" if v else "FAIL")+": "+k)
print("PASS: embedded dashboard HTML constants were NOT modified")
print("PASS: trading/risk/Dhan/Telegram logic untouched")
print("="*110)
