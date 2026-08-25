from __future__ import annotations

from pathlib import Path
from datetime import datetime
import csv, json, shutil, py_compile
import requests

ROOT = Path(__file__).resolve().parent
DASH = ROOT / "aplus_live_pnl_dashboard.py"
RUNBAT = ROOT / "run_live_pnl_dashboard.bat"
REPORT = ROOT / "data" / "reports" / "fno_market_watch_latest.json"
REFDIR = ROOT / "data" / "reference"
SECTOR = REFDIR / "fno_sector_map.csv"

if not DASH.is_file():
    raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")
if not REPORT.is_file():
    raise SystemExit(r"FAIL: data\reports\fno_market_watch_latest.json not found")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / f"backup_before_marketwatch_sector_v2_{stamp}"
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(DASH, backup / DASH.name)
if RUNBAT.is_file():
    shutil.copy2(RUNBAT, backup / RUNBAT.name)
if SECTOR.is_file():
    shutil.copy2(SECTOR, backup / SECTOR.name)

def get_symbols():
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    rows = data.get("rows", []) if isinstance(data, dict) else []
    symbols = sorted({
        str(x.get("symbol") or "").strip().upper()
        for x in rows
        if str(x.get("symbol") or "").strip()
    })
    if not symbols:
        raise RuntimeError("No F&O symbols found in market-watch report")
    return symbols

def restore_market_watch_button():
    s = DASH.read_text(encoding="utf-8")
    if 'href="/fno-market-watch"' in s:
        return False
    anchor = "</body></html>"
    if anchor not in s:
        raise RuntimeError("dashboard body closing anchor not found")
    btn = (
        '<a href="/fno-market-watch" '
        'style="position:fixed;right:22px;bottom:22px;z-index:9999;'
        'background:#17c964;color:#04130a;text-decoration:none;font-weight:800;'
        'padding:11px 16px;border-radius:12px;box-shadow:0 5px 24px #0008">'
        'F&amp;O MARKET WATCH</a>'
    )
    s = s.replace(anchor, btn + anchor, 1)
    DASH.write_text(s, encoding="utf-8")
    py_compile.compile(str(DASH), doraise=True)
    return True

def fix_dashboard_bat():
    content = (
        '@echo off\n'
        'setlocal\n'
        'cd /d "%~dp0"\n'
        'echo ============================================================\n'
        'echo APlus Live Trading Terminal\n'
        'echo ============================================================\n'
        'start "" "http://127.0.0.1:8765"\n'
        'python aplus_live_pnl_dashboard.py\n'
        'pause\n'
    )
    RUNBAT.write_text(content, encoding="utf-8")

def load_existing():
    m = {}
    if SECTOR.is_file():
        try:
            with SECTOR.open("r", encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    sym = str(r.get("symbol") or "").strip().upper()
                    sec = str(r.get("sector") or "").strip()
                    if sym and sec and sec.upper() != "UNCLASSIFIED":
                        m[sym] = sec
        except Exception:
            pass
    return m

def normalize_sector(v):
    v = str(v or "").strip()
    if not v:
        return ""
    replacements = {
        "Consumer Durables": "Consumer Durables",
        "Consumer Non-Durables": "Consumer Goods",
        "Health Technology": "Pharma & Healthcare",
        "Technology Services": "IT",
        "Electronic Technology": "Electronics & Technology",
        "Producer Manufacturing": "Capital Goods",
        "Industrial Services": "Industrial Services",
        "Process Industries": "Chemicals & Materials",
        "Non-Energy Minerals": "Metals & Mining",
        "Energy Minerals": "Energy",
        "Finance": "Financial Services",
        "Transportation": "Transportation",
        "Utilities": "Utilities",
        "Retail Trade": "Retail",
        "Distribution Services": "Distribution",
        "Commercial Services": "Commercial Services",
        "Communications": "Telecom & Media",
        "Consumer Services": "Consumer Services",
    }
    return replacements.get(v, v)

def tradingview_bulk(symbols):
    url = "https://scanner.tradingview.com/india/scan"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/",
    }
    result = {}
    failures = []
    chunk_size = 50

    for start in range(0, len(symbols), chunk_size):
        chunk = symbols[start:start+chunk_size]
        payload = {
            "symbols": {
                "tickers": [f"NSE:{s}" for s in chunk],
                "query": {"types": []},
            },
            "columns": ["name", "sector", "industry"],
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            r.raise_for_status()
            data = r.json()
            rows = data.get("data", []) if isinstance(data, dict) else []
            seen = set()
            for row in rows:
                ticker = str(row.get("s") or "")
                sym = ticker.split(":",1)[-1].upper()
                vals = row.get("d") or []
                sector = vals[1] if len(vals) > 1 else ""
                industry = vals[2] if len(vals) > 2 else ""
                sec = normalize_sector(sector) or normalize_sector(industry)
                if sym and sec:
                    result[sym] = sec
                    seen.add(sym)
            for sym in chunk:
                if sym not in seen and sym not in result:
                    failures.append(sym)
            print(f"TradingView sector lookup: {min(start+chunk_size,len(symbols))}/{len(symbols)}")
        except Exception as exc:
            print("WARN: TradingView batch failed:", type(exc).__name__, exc)
            failures.extend(chunk)

    return result, sorted(set(failures))

def write_map(symbols, sector_map):
    REFDIR.mkdir(parents=True, exist_ok=True)
    with SECTOR.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol","sector"])
        for sym in symbols:
            w.writerow([sym, sector_map.get(sym, "UNCLASSIFIED")])

try:
    symbols = get_symbols()
    existing = load_existing()
    lookup_symbols = [s for s in symbols if s not in existing]

    tv_map, failures = tradingview_bulk(lookup_symbols) if lookup_symbols else ({}, [])
    merged = dict(existing)
    merged.update(tv_map)
    write_map(symbols, merged)

    button_added = restore_market_watch_button()
    fix_dashboard_bat()

except Exception:
    shutil.copy2(backup / DASH.name, DASH)
    if (backup / RUNBAT.name).is_file():
        shutil.copy2(backup / RUNBAT.name, RUNBAT)
    if (backup / SECTOR.name).is_file():
        shutil.copy2(backup / SECTOR.name, SECTOR)
    print("INSTALL FAILED - originals restored:", backup)
    raise

classified = sum(1 for s in symbols if merged.get(s))
unclassified = [s for s in symbols if not merged.get(s)]

print("="*80)
print("SUCCESS: MARKET WATCH / SECTOR FIX V2 COMPLETE")
print("Backup:", backup)
print("F&O symbols:", len(symbols))
print("Classified:", classified)
print("Still UNCLASSIFIED:", len(unclassified))
print("Main dashboard button:", "ADDED" if button_added else "ALREADY PRESENT")
print("run_live_pnl_dashboard.bat: FIXED")
if unclassified:
    print("Unclassified:", ", ".join(unclassified[:50]))
    if len(unclassified) > 50:
        print("... and", len(unclassified)-50, "more")
print()
print("NEXT:")
print("1. Keep scanner running.")
print("2. Wait for the next scanner cycle.")
print("3. Restart ONLY dashboard with run_live_pnl_dashboard.bat.")
print("4. Press Ctrl+F5 in the browser.")
print("="*80)
