from pathlib import Path
from datetime import datetime
import csv, json, shutil, py_compile, time
import requests

ROOT = Path(__file__).resolve().parent
DASH = ROOT / "aplus_live_pnl_dashboard.py"
REPORT = ROOT / "data" / "reports" / "fno_market_watch_latest.json"
REFDIR = ROOT / "data" / "reference"
SECTOR = REFDIR / "fno_sector_map.csv"

if not DASH.is_file():
    raise SystemExit("FAIL: aplus_live_pnl_dashboard.py not found")
if not REPORT.is_file():
    raise SystemExit("FAIL: data\\reports\\fno_market_watch_latest.json not found. Keep scanner running until this file exists.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / f"backup_before_marketwatch_button_sectorfix_{stamp}"
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(DASH, backup / DASH.name)
if SECTOR.is_file():
    shutil.copy2(SECTOR, backup / SECTOR.name)

def patch_button():
    s = DASH.read_text(encoding="utf-8")
    if 'href="/fno-market-watch"' not in s:
        anchor = "</body></html>"
        if anchor not in s:
            raise RuntimeError("main dashboard body anchor not found")
        button = '<a href="/fno-market-watch" style="position:fixed;right:22px;bottom:22px;z-index:9999;background:#17c964;color:#04130a;text-decoration:none;font-weight:800;padding:11px 16px;border-radius:12px;box-shadow:0 5px 24px #0008">F&amp;O MARKET WATCH</a>'
        s = s.replace(anchor, button + anchor, 1)
        DASH.write_text(s, encoding="utf-8")
        py_compile.compile(str(DASH), doraise=True)
    return True

def get_symbols():
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    rows = data.get("rows", []) if isinstance(data, dict) else []
    symbols = sorted({str(x.get("symbol") or "").strip().upper() for x in rows if str(x.get("symbol") or "").strip()})
    if not symbols:
        raise RuntimeError("No F&O symbols found in market-watch report")
    return symbols

def nse_session():
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
        "Connection": "keep-alive",
    })
    try:
        sess.get("https://www.nseindia.com", timeout=12)
    except Exception:
        pass
    return sess

def extract_sector(payload):
    candidates = []
    def walk(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                lk = str(k).lower()
                if lk in {"sector","macro","macrosector","macroeconomicsector","industry","basicindustry","basic_industry"} and isinstance(v, str) and v.strip():
                    candidates.append((lk, v.strip()))
                walk(v, prefix + "." + str(k))
        elif isinstance(obj, list):
            for v in obj:
                walk(v, prefix)
    walk(payload)

    # Prefer NSE's explicit Sector field.
    for key, val in candidates:
        if key == "sector":
            return val
    for key, val in candidates:
        if key in {"macro","macrosector","macroeconomicsector"}:
            return val
    for key, val in candidates:
        if key == "industry":
            return val
    for key, val in candidates:
        if key in {"basicindustry","basic_industry"}:
            return val
    return ""

def fetch_sector_map(symbols):
    REFDIR.mkdir(parents=True, exist_ok=True)
    existing = {}
    if SECTOR.is_file():
        try:
            with SECTOR.open("r", encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    sym = str(r.get("symbol") or "").strip().upper()
                    sec = str(r.get("sector") or "").strip()
                    if sym and sec and sec != "UNCLASSIFIED":
                        existing[sym] = sec
        except Exception:
            pass

    sess = nse_session()
    result = dict(existing)
    failures = []

    for idx, sym in enumerate(symbols, 1):
        if sym in result:
            continue
        url = "https://www.nseindia.com/api/quote-equity"
        try:
            r = sess.get(url, params={"symbol": sym}, timeout=12)
            if r.status_code in (401, 403):
                try:
                    sess.get("https://www.nseindia.com", timeout=10)
                except Exception:
                    pass
                time.sleep(0.6)
                r = sess.get(url, params={"symbol": sym}, timeout=12)
            r.raise_for_status()
            payload = r.json()
            sec = extract_sector(payload)
            if sec:
                result[sym] = sec
            else:
                failures.append(sym)
        except Exception:
            failures.append(sym)
        if idx % 20 == 0:
            print(f"NSE sector lookup: {idx}/{len(symbols)}")
        time.sleep(0.35)

    with SECTOR.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol","sector"])
        for sym in symbols:
            w.writerow([sym, result.get(sym, "UNCLASSIFIED")])

    return len(result), failures

try:
    patch_button()
    symbols = get_symbols()
    classified, failures = fetch_sector_map(symbols)
except Exception:
    shutil.copy2(backup / DASH.name, DASH)
    if (backup / SECTOR.name).is_file():
        shutil.copy2(backup / SECTOR.name, SECTOR)
    print("INSTALL FAILED - originals restored:", backup)
    raise

print("="*80)
print("SUCCESS: MARKET WATCH BUTTON RESTORED + SECTOR MAP BUILT")
print("Backup:", backup)
print("F&O symbols:", len(symbols))
print("Classified:", classified)
print("Still UNCLASSIFIED:", len(failures))
if failures:
    print("Unclassified symbols:", ", ".join(failures[:40]))
    if len(failures) > 40:
        print("... and", len(failures)-40, "more")
print()
print("IMPORTANT:")
print("1. Restart ONLY dashboard CMD to restore main-page button.")
print("2. Scanner can remain running.")
print("3. Sector values will appear on the NEXT scanner cycle because scanner reloads fno_sector_map.csv each cycle.")
print("="*80)
