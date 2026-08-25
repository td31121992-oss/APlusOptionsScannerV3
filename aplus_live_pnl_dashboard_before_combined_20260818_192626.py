from __future__ import annotations

from pathlib import Path
from datetime import datetime
import csv
import json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "data" / "reports"
HOST = "127.0.0.1"
PORT = 8765

def _num(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default

def _load_trades():
    p_json = REPORTS / "paper_trades_latest.json"
    p_csv = REPORTS / "paper_trades.csv"
    if p_json.is_file():
        try:
            obj = json.loads(p_json.read_text(encoding="utf-8"))
            trades = obj.get("paper_trades") or obj.get("trades") or []
            return [t for t in trades if isinstance(t, dict)]
        except Exception:
            pass
    if p_csv.is_file():
        with p_csv.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    return []

def _status(t):
    return str(t.get("status") or "").upper()

def _pnl(t):
    return _num(t.get("net_pnl") if t.get("net_pnl") not in (None, "") else t.get("pnl"))

def _capital(t):
    return _num(t.get("capital_deployed") or t.get("capital"))

def _return_pct(t):
    if t.get("return_percent") not in (None, ""):
        return _num(t.get("return_percent"))
    cap = _capital(t)
    return (_pnl(t) / cap * 100.0) if cap else 0.0

def _time(v):
    s = str(v or "")
    if "T" in s:
        return s.split("T", 1)[1].split("+", 1)[0].split(".", 1)[0]
    return s or "-"

def snapshot():
    trades = _load_trades()
    today = datetime.now().date().isoformat()
    todays = [t for t in trades if str(t.get("entry_time") or "").startswith(today)]
    if todays:
        trades = todays

    open_trades = [t for t in trades if _status(t) == "OPEN"]
    closed = [t for t in trades if _status(t) == "CLOSED"]
    wins = [t for t in closed if _pnl(t) > 0 or str(t.get("result") or "").upper() == "WIN"]
    losses = [t for t in closed if _pnl(t) < 0 or str(t.get("result") or "").upper() == "LOSS"]

    rows = []
    for t in sorted(trades, key=lambda x: str(x.get("entry_time") or ""), reverse=True):
        rows.append({
            "id": str(t.get("paper_trade_id") or t.get("trade_id") or ""),
            "symbol": str(t.get("symbol") or "-"),
            "side": (str(t.get("direction") or "") + " " + str(t.get("option_type") or t.get("side") or "")).strip(),
            "strike": _num(t.get("strike")),
            "entry_time": _time(t.get("entry_time")),
            "exit_time": _time(t.get("exit_time")),
            "status": _status(t) or "-",
            "entry": _num(t.get("entry_price")),
            "last": _num(t.get("last_option_price") or t.get("exit_price") or t.get("entry_price")),
            "pnl": _pnl(t),
            "return_pct": _return_pct(t),
            "capital": _capital(t),
            "mfe": _num(t.get("mfe_amount")),
            "mae": _num(t.get("mae_amount")),
            "exit_reason": str(t.get("exit_reason") or "-"),
            "setup": str(t.get("setup_family") or "-"),
            "quality": _num(t.get("momentum_score") or t.get("trade_quality_score")),
            "clean": _num(t.get("clean_trend_score")),
        })

    return {
        "updated_at": datetime.now().strftime("%H:%M:%S"),
        "trade_count": len(trades),
        "open_count": len(open_trades),
        "closed_count": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round((len(wins) / len(closed) * 100.0) if closed else 0.0, 2),
        "capital": round(sum(_capital(t) for t in trades), 2),
        "total_pnl": round(sum(_pnl(t) for t in trades), 2),
        "closed_pnl": round(sum(_pnl(t) for t in closed), 2),
        "open_pnl": round(sum(_pnl(t) for t in open_trades), 2),
        "rows": rows[:300],
    }

HTML = '''<!doctype html>
<html><head><meta charset="utf-8"><title>APlus Live Trading Terminal</title>
<style>
:root{--bg:#0b1020;--panel:#121a2d;--muted:#8ea0bd;--text:#e7eefc;--green:#17c964;--red:#f31260;--line:#27334d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}
.header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}
.title{font-size:24px;font-weight:700}.sub{color:var(--muted);font-size:13px;margin-top:4px}
.grid{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;padding:18px 24px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px}
.label{color:var(--muted);font-size:12px}.value{font-size:24px;font-weight:750;margin-top:6px}.green{color:var(--green)}.red{color:var(--red)}
.tablewrap{padding:0 24px 24px}table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
th,td{padding:10px;border-bottom:1px solid var(--line);font-size:13px;text-align:left;white-space:nowrap}
th{color:var(--muted);font-weight:600;background:#0f1729;position:sticky;top:0}.right{text-align:right}
tr:hover{background:#18233b}.pill{padding:3px 8px;border-radius:999px;font-size:12px}.open{background:#1e3a5f}.closed{background:#243326}.loss{color:var(--red)}.win{color:var(--green)}
.watermark{position:fixed;left:50%;top:52%;transform:translate(-50%,-50%) rotate(-24deg);font-size:52px;font-weight:700;letter-spacing:2px;color:rgba(231,238,252,.045);white-space:nowrap;pointer-events:none;user-select:none;z-index:0}
.header,.grid,.tablewrap{position:relative;z-index:1}
@media(max-width:1200px){.grid{grid-template-columns:repeat(3,1fr)}}
</style></head><body>
<div class="watermark">Developed by Darpan Bobhate</div>
<div class="header"><div><div class="title">APlus Live Trading Terminal</div><div class="sub">Auto-refreshes every 5 seconds from data/reports</div></div><div class="sub">Last update: <span id="updated">-</span></div></div>
<div class="grid">
<div class="card"><div class="label">Total P&L</div><div id="total_pnl" class="value">-</div></div>
<div class="card"><div class="label">Open P&L</div><div id="open_pnl" class="value">-</div></div>
<div class="card"><div class="label">Closed P&L</div><div id="closed_pnl" class="value">-</div></div>
<div class="card"><div class="label">Trades</div><div id="trade_count" class="value">-</div></div>
<div class="card"><div class="label">Open / Closed</div><div id="open_closed" class="value">-</div></div>
<div class="card"><div class="label">Win Rate</div><div id="win_rate" class="value">-</div></div>
</div>
<div class="tablewrap"><table><thead><tr>
<th>Symbol</th><th>Side</th><th>Strike</th><th>Entry</th><th>Exit</th><th>Status</th><th class="right">Entry ₹</th><th class="right">Last/Exit ₹</th><th class="right">P&L</th><th class="right">Return</th><th class="right">Capital</th><th>Setup</th><th>Exit Reason</th><th class="right">Q</th><th class="right">Clean</th>
</tr></thead><tbody id="rows"></tbody></table></div>
<script>
const fmt=n=>"₹"+Number(n||0).toLocaleString("en-IN",{maximumFractionDigits:2});
const pct=n=>Number(n||0).toFixed(2)+"%"; const cls=n=>Number(n)>=0?"green":"red";
async function load(){const r=await fetch('/api/snapshot?ts='+Date.now()); const d=await r.json();
updated.textContent=d.updated_at; for(const k of ["total_pnl","open_pnl","closed_pnl"]){let e=document.getElementById(k);e.textContent=fmt(d[k]);e.className="value "+cls(d[k]);}
trade_count.textContent=d.trade_count; open_closed.textContent=d.open_count+" / "+d.closed_count; win_rate.textContent=pct(d.win_rate);
rows.innerHTML=d.rows.map(x=>{const pnlc=Number(x.pnl)>=0?"win":"loss"; const st=x.status=="OPEN"?"open":"closed"; return `<tr><td><b>${x.symbol}</b></td><td>${x.side}</td><td>${x.strike}</td><td>${x.entry_time}</td><td>${x.exit_time}</td><td><span class="pill ${st}">${x.status}</span></td><td class="right">${fmt(x.entry)}</td><td class="right">${fmt(x.last)}</td><td class="right ${pnlc}"><b>${fmt(x.pnl)}</b></td><td class="right ${pnlc}">${pct(x.return_pct)}</td><td class="right">${fmt(x.capital)}</td><td>${x.setup}</td><td>${x.exit_reason}</td><td class="right">${Number(x.quality||0).toFixed(1)}</td><td class="right">${Number(x.clean||0).toFixed(1)}</td></tr>`}).join("");}
load(); setInterval(load,5000);
</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/snapshot":
            body = json.dumps(snapshot()).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        body = HTML.encode("utf-8")
        self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, fmt, *args):
        return

def main():
    print("="*72)
    print("APlus Live Trading Terminal")
    print("Open: http://127.0.0.1:8765")
    print("Press Ctrl+C to stop.")
    print("="*72)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == "__main__":
    main()
