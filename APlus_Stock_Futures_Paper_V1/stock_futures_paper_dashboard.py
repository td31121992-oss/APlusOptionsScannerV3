from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parent
REPORT=ROOT/"data"/"reports"/"stock_futures_paper_latest.json"
HTML="""<!doctype html><html><head><meta charset='utf-8'><title>APlus Futures Paper</title>
<style>:root{--b:#0b1020;--p:#121a2d;--t:#e7eefc;--m:#8ea0bd;--l:#27334d;--g:#17c964;--r:#f31260}*{box-sizing:border-box}body{margin:0;background:var(--b);color:var(--t);font-family:Segoe UI,Arial}header{padding:22px 28px;border-bottom:1px solid var(--l)}h1{margin:0;font-size:24px}.sub{color:var(--m);margin-top:5px}.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;padding:20px}.c{background:var(--p);border:1px solid var(--l);border-radius:14px;padding:14px}.lab{color:var(--m);font-size:12px}.val{font-size:22px;font-weight:750}.wrap{padding:0 20px 30px;overflow:auto}table{width:100%;border-collapse:collapse;background:var(--p)}th,td{padding:9px;border-bottom:1px solid var(--l);font-size:12px;white-space:nowrap;text-align:left}th{color:var(--m);background:#0f1729}.g{color:var(--g)}.r{color:var(--r)}</style></head><body>
<header><h1>APlus Stock Futures — PAPER Research</h1><div class='sub'>Research-only futures. No live futures order authority.</div></header>
<div class='cards'><div class='c'><div class='lab'>Trades</div><div id='tr' class='val'>-</div></div><div class='c'><div class='lab'>Open</div><div id='op' class='val'>-</div></div><div class='c'><div class='lab'>Closed</div><div id='cl' class='val'>-</div></div><div class='c'><div class='lab'>Closed P&L</div><div id='pn' class='val'>-</div></div><div class='c'><div class='lab'>Estimated Margin</div><div id='mg' class='val'>-</div></div></div>
<div class='wrap'><table><thead><tr><th>Symbol</th><th>Side</th><th>Contract</th><th>Expiry</th><th>Qty</th><th>Entry Time</th><th>Entry Fut</th><th>Last/Exit Fut</th><th>Status</th><th>P&L</th><th>Est Margin</th><th>Return</th><th>Quality</th><th>RVOL</th><th>Leadership</th><th>Entry Reason</th><th>Exit Reason</th></tr></thead><tbody id='rows'></tbody></table></div>
<script>const money=n=>'₹'+Number(n||0).toLocaleString('en-IN',{maximumFractionDigits:2}),cls=n=>Number(n)>=0?'g':'r';
async function load(){let d={summary:{},trades:[]};try{d=await(await fetch('/api?x='+Date.now())).json()}catch(e){}let s=d.summary||{};tr.textContent=s.trades||0;op.textContent=s.open||0;cl.textContent=s.closed||0;pn.textContent=money(s.net_pnl||0);pn.className='val '+cls(s.net_pnl);mg.textContent=money(s.estimated_margin_total||0);rows.innerHTML=(d.trades||[]).slice().reverse().map(x=>`<tr><td><b>${x.symbol}</b></td><td>${x.side}</td><td>${x.trading_symbol}</td><td>${x.expiry}</td><td>${x.quantity}</td><td>${(x.entry_time||'').slice(11,19)}</td><td>${money(x.entry_future_price)}</td><td>${money(x.exit_future_price||x.last_future_price)}</td><td>${x.status}</td><td class='${cls(x.gross_pnl||x.estimated_unrealized_pnl)}'>${money(x.status==='CLOSED'?x.gross_pnl:x.estimated_unrealized_pnl)}</td><td>${money(x.estimated_margin)}</td><td>${Number(x.return_on_estimated_margin_pct||0).toFixed(2)}%</td><td>${Number(x.signal_quality||0).toFixed(1)}</td><td>${Number(x.relative_volume||0).toFixed(2)}x</td><td>${x.leadership_shadow?'YES':'-'}</td><td>${x.entry_reason||''}</td><td>${x.exit_reason||x.pending_exit_reason||''}</td></tr>`).join('')}</script></body></html>"""
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api"):
            try:body=REPORT.read_bytes()
            except Exception:body=b'{"summary":{},"trades":[]}'
            ct="application/json"
        else:body=HTML.encode();ct="text/html; charset=utf-8"
        self.send_response(200);self.send_header("Content-Type",ct);self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*a):return
if __name__=="__main__":
    print("APlus Futures PAPER Dashboard: http://127.0.0.1:8766")
    ThreadingHTTPServer(("127.0.0.1",8766),H).serve_forever()
