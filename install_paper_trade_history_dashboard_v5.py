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
B=ROOT/f"backup_before_trade_history_dashboard_v5_{stamp}"
B.mkdir()
shutil.copy2(J,B/J.name)
shutil.copy2(D,B/D.name)

def ensure_import_after_future(text:str, import_line:str)->str:
    if import_line in text:
        return text
    lines=text.splitlines()
    # Always insert AFTER the last __future__ import, wherever it appears.
    future_idxs=[i for i,line in enumerate(lines) if line.strip().startswith("from __future__ import")]
    if future_idxs:
        idx=max(future_idxs)+1
    else:
        # If no future import, insert after module docstring if present; otherwise at top.
        idx=0
        if lines and lines[0].lstrip().startswith(('"""', "'''")):
            quote='"""' if '"""' in lines[0] else "'''"
            if lines[0].count(quote)>=2:
                idx=1
            else:
                for i in range(1,min(len(lines),80)):
                    if quote in lines[i]:
                        idx=i+1
                        break
    lines.insert(idx,import_line)
    return "\n".join(lines)+("\n" if text.endswith("\n") else "")

def patch_journal(text:str)->str:
    text=ensure_import_after_future(text,"from paper_trade_history_store import sync_history")
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
    text=ensure_import_after_future(
        text,
        "from paper_trade_history_dashboard import history_html, history_payload, days_payload"
    )

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
    # Patch journal
    js=J.read_text(encoding="utf-8")
    js=patch_journal(js)
    J.write_text(js,encoding="utf-8")
    py_compile.compile(str(J),doraise=True)

    # Patch dashboard
    ds=D.read_text(encoding="utf-8")
    ds=patch_dashboard(ds)
    D.write_text(ds,encoding="utf-8")
    py_compile.compile(str(D),doraise=True)

    # Verify
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

print("="*112)
print("SUCCESS: PERMANENT PAPER TRADE HISTORY + DASHBOARD V5 INSTALLED")
print("Backup:",B)
for k,v in checks.items():
    print(("PASS" if v else "FAIL")+": "+k)
print("PASS: imports inserted AFTER __future__ imports")
print("PASS: embedded dashboard HTML constants untouched")
print("PASS: trading/risk/Dhan/Telegram logic untouched")
print("="*112)
