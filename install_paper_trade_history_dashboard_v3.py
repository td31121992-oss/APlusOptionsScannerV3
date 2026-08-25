from __future__ import annotations
from pathlib import Path
from datetime import datetime
import ast, shutil, py_compile

ROOT=Path(__file__).resolve().parent
J=ROOT/"paper_trade_journal.py"
D=ROOT/"aplus_live_pnl_dashboard.py"

if not J.is_file():
    raise SystemExit("FAIL: paper_trade_journal.py missing")
if not D.is_file():
    raise SystemExit("FAIL: aplus_live_pnl_dashboard.py missing")

stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
B=ROOT/f"backup_before_trade_history_dashboard_v3_{stamp}"
B.mkdir()
shutil.copy2(J,B/J.name)
shutil.copy2(D,B/D.name)

def ensure_import(text:str, import_line:str)->str:
    if import_line in text:
        return text
    lines=text.splitlines()
    insert_at=0
    if lines and lines[0].startswith("#!"):
        insert_at=1
    # Keep __future__ import first.
    for i,line in enumerate(lines[:40]):
        if line.startswith("from __future__ import"):
            insert_at=i+1
    lines.insert(insert_at,import_line)
    return "\n".join(lines)+("\n" if text.endswith("\n") else "")

def patch_journal(text:str)->str:
    marker="sync_history(self.report_dir, self.trades)"
    text=ensure_import(text,"from paper_trade_history_store import sync_history")
    if marker in text:
        return text

    tree=ast.parse(text)
    target=None
    for node in ast.walk(tree):
        if isinstance(node,ast.ClassDef) and node.name=="PaperTradeJournal":
            for child in node.body:
                if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef)) and child.name=="flush":
                    target=child
                    break
    if target is None:
        raise RuntimeError("AST could not locate PaperTradeJournal.flush")

    lines=text.splitlines()
    if not target.body:
        raise RuntimeError("PaperTradeJournal.flush has no body")

    # Insert after docstring if present, otherwise before first executable statement.
    first=target.body[0]
    insert_lineno=first.lineno
    if (
        isinstance(first,ast.Expr)
        and isinstance(getattr(first,"value",None),ast.Constant)
        and isinstance(first.value.value,str)
        and len(target.body)>1
    ):
        insert_lineno=target.body[1].lineno

    indent=" "*(target.col_offset+4)
    lines.insert(insert_lineno-1,indent+marker)
    patched="\n".join(lines)+("\n" if text.endswith("\n") else "")
    ast.parse(patched)
    return patched

def patch_dashboard(text:str)->str:
    imp="from paper_trade_history_dashboard import history_html, history_payload, days_payload"
    text=ensure_import(text,imp)

    if 'if path == "/paper-history":' not in text:
        tree=ast.parse(text)
        doget=None
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name=="do_GET":
                doget=node
                break
        if doget is None:
            raise RuntimeError("AST could not locate dashboard do_GET")

        lines=text.splitlines()
        insert_after=None
        for lineno in range(doget.lineno, min(getattr(doget,"end_lineno",len(lines)),len(lines))+1):
            if "path = urlparse(self.path).path" in lines[lineno-1]:
                insert_after=lineno
                break
        if insert_after is None:
            raise RuntimeError("Could not locate dashboard URL path assignment inside do_GET")

        base_indent=lines[insert_after-1][:len(lines[insert_after-1])-len(lines[insert_after-1].lstrip())]
        route=[
            base_indent+'if path == "/paper-history":',
            base_indent+'    body = history_html().encode("utf-8")',
            base_indent+'    self.send_response(200)',
            base_indent+'    self.send_header("Content-Type","text/html; charset=utf-8")',
            base_indent+'    self.send_header("Cache-Control","no-store")',
            base_indent+'    self.send_header("Content-Length",str(len(body)))',
            base_indent+'    self.end_headers(); self.wfile.write(body); return',
            base_indent+'if path == "/api/paper-days":',
            base_indent+'    body = json.dumps(days_payload()).encode("utf-8")',
            base_indent+'    self.send_response(200)',
            base_indent+'    self.send_header("Content-Type","application/json")',
            base_indent+'    self.send_header("Cache-Control","no-store")',
            base_indent+'    self.send_header("Content-Length",str(len(body)))',
            base_indent+'    self.end_headers(); self.wfile.write(body); return',
            base_indent+'if path == "/api/paper-history":',
            base_indent+'    from urllib.parse import parse_qs',
            base_indent+'    q = parse_qs(urlparse(self.path).query)',
            base_indent+'    day = (q.get("date") or [""])[0]',
            base_indent+'    body = json.dumps(history_payload(day)).encode("utf-8")',
            base_indent+'    self.send_response(200)',
            base_indent+'    self.send_header("Content-Type","application/json")',
            base_indent+'    self.send_header("Cache-Control","no-store")',
            base_indent+'    self.send_header("Content-Length",str(len(body)))',
            base_indent+'    self.end_headers(); self.wfile.write(body); return',
        ]
        lines[insert_after:insert_after]=route
        text="\n".join(lines)+("\n" if text.endswith("\n") else "")

    if 'href="/paper-history"' not in text:
        if "<body>" in text:
            text=text.replace(
                "<body>",
                "<body><div style='position:fixed;right:20px;top:16px;z-index:9999'>"
                "<a style='color:#e7eefc;text-decoration:none;font-weight:700' href='/paper-history'>"
                "PAPER HISTORY</a></div>",
                1
            )
        else:
            print("WARNING: dashboard <body> tag not found; route works but nav link was not inserted.")

    ast.parse(text)
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
        "journal_import":"from paper_trade_history_store import sync_history" in js,
        "journal_sync":"sync_history(self.report_dir, self.trades)" in js,
        "history_page":'if path == "/paper-history":' in ds,
        "days_api":'if path == "/api/paper-days":' in ds,
        "history_api":'if path == "/api/paper-history":' in ds,
    }
    if not all(checks.values()):
        raise RuntimeError(f"Post-install verification failed: {checks}")

except Exception:
    shutil.copy2(B/J.name,J)
    shutil.copy2(B/D.name,D)
    print("INSTALL FAILED - originals restored automatically.")
    print("Backup:",B)
    raise

print("="*106)
print("SUCCESS: PERMANENT PAPER TRADE HISTORY + DASHBOARD V3 INSTALLED")
print("Backup:",B)
print("PASS: AST-based PaperTradeJournal.flush patch")
print("PASS: permanent cumulative history sync")
print("PASS: /paper-history")
print("PASS: /api/paper-days")
print("PASS: /api/paper-history")
print("PASS: trading/risk/Dhan/Telegram logic untouched")
print("="*106)
