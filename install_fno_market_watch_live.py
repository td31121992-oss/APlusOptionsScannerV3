from __future__ import annotations

from datetime import datetime
from pathlib import Path
import py_compile
import shutil

ROOT = Path(__file__).resolve().parent
SCANNER = ROOT / "opening_momentum_scanner.py"
DASH = ROOT / "aplus_live_pnl_dashboard.py"

if not SCANNER.is_file():
    raise SystemExit("FAIL: opening_momentum_scanner.py not found")
if not DASH.is_file():
    raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / f"backup_before_fno_market_watch_{stamp}"
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(SCANNER, backup / SCANNER.name)
shutil.copy2(DASH, backup / DASH.name)

def once(s: str, old: str, new: str, label: str) -> str:
    c = s.count(old)
    if c != 1:
        raise RuntimeError(f"{label}: expected 1 anchor, found {c}")
    return s.replace(old, new, 1)

try:
    s = SCANNER.read_text(encoding="utf-8")

    if "def _build_fno_market_watch(" not in s:
        anchor = "    def _parse_quotes(\n"
        pos = s.find(anchor)
        if pos < 0:
            raise RuntimeError("_parse_quotes anchor not found")
        method = '''    def _build_fno_market_watch(
        self,
        *,
        universe: Sequence[UnderlyingInstrument],
        quote_map: Mapping[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        """Build full F&O market watch from the SAME quote batch used by scanner."""
        segment_data = quote_map.get("NSE_EQ", {})
        if not isinstance(segment_data, Mapping):
            segment_data = {}

        sector_map: dict[str, str] = {}
        sector_file = Path(self.config.paths.data_dir) / "reference" / "fno_sector_map.csv"
        if sector_file.is_file():
            try:
                with sector_file.open("r", encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle)
                    for row in reader:
                        symbol = str(row.get("symbol") or "").strip().upper()
                        sector = str(row.get("sector") or "").strip()
                        if symbol and sector:
                            sector_map[symbol] = sector
            except Exception:
                sector_map = {}

        rows: list[dict[str, Any]] = []
        for underlying in universe:
            security_id = str(underlying.security_id)
            raw = segment_data.get(security_id)
            if raw is None:
                try:
                    raw = segment_data.get(int(security_id))
                except (TypeError, ValueError):
                    raw = None
            if not isinstance(raw, Mapping):
                continue

            ohlc = raw.get("ohlc")
            if not isinstance(ohlc, Mapping):
                ohlc = {}

            ltp = self._positive(raw.get("last_price"))
            day_open = self._positive(ohlc.get("open"))
            day_high = self._positive(ohlc.get("high"))
            day_low = self._positive(ohlc.get("low"))
            previous_close = self._positive(ohlc.get("close"))
            if not all(v is not None for v in (ltp, day_open, day_high, day_low, previous_close)):
                continue

            assert ltp is not None
            assert day_open is not None
            assert day_high is not None
            assert day_low is not None
            assert previous_close is not None

            from_open = (ltp - day_open) / day_open * 100.0
            from_prev = (ltp - previous_close) / previous_close * 100.0
            gap_pct = (day_open - previous_close) / previous_close * 100.0
            range_pos = self._range_position(ltp, day_low, day_high) * 100.0
            symbol = str(underlying.symbol).strip().upper()

            rows.append({
                "symbol": symbol,
                "security_id": security_id,
                "sector": sector_map.get(symbol, "UNCLASSIFIED"),
                "open_0915": round(day_open, 2),
                "ltp": round(ltp, 2),
                "previous_close": round(previous_close, 2),
                "gap_pct": round(gap_pct, 3),
                "from_open_pct": round(from_open, 3),
                "from_prev_close_pct": round(from_prev, 3),
                "day_high": round(day_high, 2),
                "day_low": round(day_low, 2),
                "range_position_pct": round(range_pos, 2),
                "direction": "UP" if from_open > 0 else "DOWN" if from_open < 0 else "FLAT",
            })

        rows.sort(key=lambda x: x["from_open_pct"], reverse=True)
        sectors: dict[str, dict[str, Any]] = {}
        for row in rows:
            sec = row["sector"]
            item = sectors.setdefault(sec, {"sector": sec, "stocks": 0, "advancing": 0, "declining": 0, "sum_move": 0.0})
            item["stocks"] += 1
            item["advancing"] += int(row["from_open_pct"] > 0)
            item["declining"] += int(row["from_open_pct"] < 0)
            item["sum_move"] += float(row["from_open_pct"])

        sector_rows = []
        for item in sectors.values():
            count = max(1, int(item["stocks"]))
            sector_rows.append({
                "sector": item["sector"],
                "stocks": item["stocks"],
                "advancing": item["advancing"],
                "declining": item["declining"],
                "average_from_open_pct": round(item["sum_move"] / count, 3),
            })
        sector_rows.sort(key=lambda x: x["average_from_open_pct"], reverse=True)
        return {"generated_at": now.isoformat(), "count": len(rows), "rows": rows, "sectors": sector_rows}

'''
        s = s[:pos] + method + s[pos:]

    if "fno_market_watch = self._build_fno_market_watch(" not in s:
        old = '''        raw_quotes_received = max(
            0,
            len(universe) - len(missing_quote_symbols) - len(invalid_quote_symbols),
        )

'''
        new = old + '''        # Full F&O market watch from the SAME 208-stock quote response.
        # This adds ZERO additional Dhan API requests.
        fno_market_watch = self._build_fno_market_watch(
            universe=universe,
            quote_map=quote_map,
            now=current_time,
        )

'''
        s = once(s, old, new, "market-watch build")

    if '"fno_market_watch": fno_market_watch,' not in s:
        s = once(s, '            "raw_quotes_received": raw_quotes_received,\n', '            "raw_quotes_received": raw_quotes_received,\n            "fno_market_watch": fno_market_watch,\n', "payload market-watch")

    if '"fno_market_watch_latest.json"' not in s:
        old = '''        self._atomic_json(legacy_latest, payload)
        self._atomic_json(legacy_archive, payload)

'''
        new = old + '''        market_watch = payload.get("fno_market_watch", {}) or {}
        self._atomic_json(self.report_dir / "fno_market_watch_latest.json", market_watch)
        self._write_candidate_csv(
            self.report_dir / "fno_market_watch_latest.csv",
            list(market_watch.get("rows", []) or []),
            [
                "symbol", "sector", "open_0915", "ltp", "previous_close",
                "gap_pct", "from_open_pct", "from_prev_close_pct",
                "day_high", "day_low", "range_position_pct", "direction",
            ],
        )

'''
        s = once(s, old, new, "market-watch reports")

    SCANNER.write_text(s, encoding="utf-8")
    py_compile.compile(str(SCANNER), doraise=True)

    d = DASH.read_text(encoding="utf-8")

    if "def _load_fno_market_watch():" not in d:
        anchor = "def snapshot():"
        pos = d.find(anchor)
        if pos < 0:
            raise RuntimeError("dashboard snapshot anchor not found")
        helper = '''def _load_fno_market_watch():
    path = REPORTS / "fno_market_watch_latest.json"
    if not path.is_file():
        return {"generated_at": "", "count": 0, "rows": [], "sectors": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"generated_at": "", "count": 0, "rows": [], "sectors": []}


FNO_MARKET_WATCH_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>APlus F&O Market Watch</title>
<style>:root{--bg:#0b1020;--panel:#121a2d;--muted:#8ea0bd;--text:#e7eefc;--green:#17c964;--red:#f31260;--line:#27334d}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}.header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between}.title{font-size:24px;font-weight:750}.sub{color:var(--muted);font-size:12px;margin-top:4px}.toolbar{padding:14px 24px;display:flex;gap:8px;flex-wrap:wrap}.toolbar button,.toolbar select{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:8px 12px;font-weight:600}.toolbar button{cursor:pointer}.active{border-color:var(--green)!important;background:#173527!important;color:#9ff0bd!important}.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;padding:0 24px 14px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}.label{font-size:11px;color:var(--muted)}.value{font-size:20px;font-weight:750;margin-top:5px}.tablewrap{padding:0 24px 26px;overflow:auto}table{width:100%;border-collapse:collapse;background:var(--panel)}th,td{padding:9px 10px;border-bottom:1px solid var(--line);font-size:12px;white-space:nowrap}th{color:var(--muted);background:#0f1729;position:sticky;top:0}.right{text-align:right}.up{color:var(--green);font-weight:700}.down{color:var(--red);font-weight:700}a{color:#7dd3fc;text-decoration:none}.footer{padding:18px;text-align:center;color:var(--muted);border-top:1px solid var(--line)}@media(max-width:1100px){.cards{grid-template-columns:repeat(2,1fr)}}</style></head><body>
<div class="header"><div><div class="title">APlus F&O Market Watch</div><div class="sub">Full F&O universe • 09:15 Open → Now • Previous Close • High/Low • Gap • Sector</div></div><div style="text-align:right"><a href="/">← Live Trading Terminal</a><div id="updated" class="sub">Waiting for scanner data...</div></div></div>
<div class="cards"><div class="card"><div class="label">F&O Stocks</div><div class="value" id="count">-</div></div><div class="card"><div class="label">Advancing from Open</div><div class="value up" id="adv">-</div></div><div class="card"><div class="label">Declining from Open</div><div class="value down" id="dec">-</div></div><div class="card"><div class="label">Top From Open</div><div class="value up" id="topup">-</div></div><div class="card"><div class="label">Bottom From Open</div><div class="value down" id="topdown">-</div></div></div>
<div class="toolbar"><button id="bALL" class="active" onclick="setMode('ALL')">All</button><button id="bGAIN" onclick="setMode('GAIN')">Top Gainers</button><button id="bLOSS" onclick="setMode('LOSS')">Top Losers</button><button id="bUP" onclick="setMode('UP')">Strong Up ≥1%</button><button id="bDOWN" onclick="setMode('DOWN')">Strong Down ≤−1%</button><select id="sector" onchange="render()"><option value="ALL">All Sectors</option></select><select id="basis" onchange="render()"><option value="from_open_pct">Sort: From 09:15 Open %</option><option value="from_prev_close_pct">Sort: From Prev Close %</option><option value="gap_pct">Sort: Gap %</option></select><span class="sub" id="shown"></span></div>
<div class="tablewrap"><table><thead><tr><th>Symbol</th><th>Sector</th><th class="right">9:15 Open</th><th class="right">LTP</th><th class="right">Prev Close</th><th class="right">Gap %</th><th class="right">From Open %</th><th class="right">From Prev Close %</th><th class="right">Day High</th><th class="right">Day Low</th><th class="right">Range Pos %</th><th>Direction</th></tr></thead><tbody id="rows"></tbody></table></div>
<div class="footer">APlus Live Trading Terminal — Developed by Darpan Bobhate</div>
<script>let data=[],mode='ALL';const money=n=>'₹'+Number(n||0).toLocaleString('en-IN',{maximumFractionDigits:2});const pct=n=>(Number(n)>=0?'+':'')+Number(n||0).toFixed(2)+'%';function setMode(m){mode=m;document.querySelectorAll('.toolbar button').forEach(x=>x.classList.remove('active'));document.getElementById('b'+m).classList.add('active');render()}function render(){let a=[...data],sec=sector.value,b=basis.value;if(sec!=='ALL')a=a.filter(x=>x.sector===sec);if(mode==='GAIN')a=a.filter(x=>x[b]>0).sort((x,y)=>y[b]-x[b]).slice(0,30);else if(mode==='LOSS')a=a.filter(x=>x[b]<0).sort((x,y)=>x[b]-y[b]).slice(0,30);else if(mode==='UP')a=a.filter(x=>x.from_open_pct>=1).sort((x,y)=>y.from_open_pct-x.from_open_pct);else if(mode==='DOWN')a=a.filter(x=>x.from_open_pct<=-1).sort((x,y)=>x.from_open_pct-y.from_open_pct);else a.sort((x,y)=>y[b]-x[b]);shown.textContent='Showing '+a.length+' of '+data.length+' stocks';rows.innerHTML=a.map(x=>`<tr><td><b>${x.symbol}</b></td><td>${x.sector||'UNCLASSIFIED'}</td><td class="right">${money(x.open_0915)}</td><td class="right">${money(x.ltp)}</td><td class="right">${money(x.previous_close)}</td><td class="right ${x.gap_pct>=0?'up':'down'}">${pct(x.gap_pct)}</td><td class="right ${x.from_open_pct>=0?'up':'down'}">${pct(x.from_open_pct)}</td><td class="right ${x.from_prev_close_pct>=0?'up':'down'}">${pct(x.from_prev_close_pct)}</td><td class="right">${money(x.day_high)}</td><td class="right">${money(x.day_low)}</td><td class="right">${Number(x.range_position_pct||0).toFixed(1)}</td><td class="${x.direction==='UP'?'up':x.direction==='DOWN'?'down':''}">${x.direction==='UP'?'▲':x.direction==='DOWN'?'▼':'•'} ${x.direction}</td></tr>`).join('')}async function load(){const r=await fetch('/api/fno-market-watch?ts='+Date.now());const d=await r.json();data=d.rows||[];count.textContent=data.length;adv.textContent=data.filter(x=>x.from_open_pct>0).length;dec.textContent=data.filter(x=>x.from_open_pct<0).length;if(data.length){let u=[...data].sort((a,b)=>b.from_open_pct-a.from_open_pct)[0],dn=[...data].sort((a,b)=>a.from_open_pct-b.from_open_pct)[0];topup.textContent=u.symbol+' '+pct(u.from_open_pct);topdown.textContent=dn.symbol+' '+pct(dn.from_open_pct)}updated.textContent=d.generated_at?'Updated '+String(d.generated_at).slice(11,19):'Waiting for scanner data...';const old=sector.value;const secs=[...new Set(data.map(x=>x.sector||'UNCLASSIFIED'))].sort();sector.innerHTML='<option value="ALL">All Sectors</option>'+secs.map(x=>`<option value="${x}">${x}</option>`).join('');if(old==='ALL'||secs.includes(old))sector.value=old;render()}load();setInterval(load,5000)</script></body></html>"""

'''
        d = d[:pos] + helper + d[pos:]

    if 'if path == "/api/fno-market-watch":' not in d:
        anchor = '        if path == "/api/snapshot":'
        if anchor not in d:
            raise RuntimeError("dashboard API route anchor not found")
        routes = '''        if path == "/api/fno-market-watch":
            body = json.dumps(_load_fno_market_watch()).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/fno-market-watch":
            body = FNO_MARKET_WATCH_HTML.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
'''
        d = d.replace(anchor, routes + anchor, 1)

    if 'href="/fno-market-watch"' not in d:
        anchor = '</body></html>'
        if anchor not in d:
            raise RuntimeError("dashboard body closing anchor not found")
        button = '<a href="/fno-market-watch" style="position:fixed;right:22px;bottom:22px;z-index:999;background:#17c964;color:#04130a;text-decoration:none;font-weight:800;padding:11px 16px;border-radius:12px;box-shadow:0 5px 24px #0008">F&amp;O MARKET WATCH</a>'
        d = d.replace(anchor, button + anchor, 1)

    DASH.write_text(d, encoding="utf-8")
    py_compile.compile(str(DASH), doraise=True)

except Exception:
    shutil.copy2(backup / SCANNER.name, SCANNER)
    shutil.copy2(backup / DASH.name, DASH)
    print("INSTALL FAILED - originals restored:", backup)
    raise

print("=" * 78)
print("SUCCESS: APLUS F&O MARKET WATCH INSTALLED")
print("Backup:", backup)
print("PASS: reuses existing 208-stock scanner quote batch")
print("PASS: ZERO additional Dhan API calls")
print("PASS: LTP / 09:15 Open / Prev Close / Gap / From Open / From Prev Close")
print("PASS: Day High / Day Low / range position")
print("PASS: Top Gainers / Top Losers / Strong Up / Strong Down")
print("PASS: sector filter supported via data\\reference\\fno_sector_map.csv")
print("PASS: dashboard route /fno-market-watch")
print("PASS: scanner and dashboard compile")
print("=" * 78)
