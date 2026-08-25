from pathlib import Path
from datetime import datetime
import csv, json, shutil, zipfile

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
REPORTS = DATA / "reports"
OUT = DATA / "after_market"

REPORT_FILES = [
    "paper_trades.csv",
    "paper_trades_latest.json",
    "intraday_movement_latest.json",
    "intraday_entry_ready.csv",
    "intraday_fresh_movement.csv",
    "intraday_wait_for_pullback.csv",
    "intraday_near_misses.csv",
]

EXTRA_FILES = [
    DATA / "intraday_movement" / "paper_trade_journal.json",
    DATA / "intraday_movement" / "quote_tape.json",
    ROOT / "logs" / "scanner.log",
]

def trading_date():
    p = REPORTS / "paper_trades_latest.json"
    if p.is_file():
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            d = str(obj.get("trading_date") or "").strip()
            if d:
                return d[:10]
        except Exception:
            pass
    return datetime.now().date().isoformat()

def summarize(path):
    info = {"name": path.name, "size_bytes": path.stat().st_size if path.is_file() else 0}
    try:
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                info["rows"] = sum(1 for _ in csv.DictReader(f))
        elif path.suffix.lower() == ".json":
            obj = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(obj, dict) and isinstance(obj.get("paper_trades"), list):
                trades = [t for t in obj["paper_trades"] if isinstance(t, dict)]
                info["paper_trades"] = len(trades)
                info["closed"] = sum(str(t.get("status","")).upper()=="CLOSED" for t in trades)
                info["open"] = sum(str(t.get("status","")).upper()=="OPEN" for t in trades)
                info["wins"] = sum(str(t.get("result","")).upper()=="WIN" for t in trades)
                info["losses"] = sum(str(t.get("result","")).upper()=="LOSS" for t in trades)
                info["net_pnl"] = round(sum(float(t.get("net_pnl") or 0) for t in trades),2)
    except Exception as e:
        info["summary_error"] = f"{type(e).__name__}: {e}"
    return info

def main():
    day = trading_date()
    day_dir = OUT / day
    day_dir.mkdir(parents=True, exist_ok=True)
    copied, missing = [], []

    for name in REPORT_FILES:
        src = REPORTS / name
        if src.is_file():
            dst = day_dir / name
            shutil.copy2(src, dst)
            copied.append(dst)
        else:
            missing.append(str(src))

    for src in EXTRA_FILES:
        if src.is_file():
            dst = day_dir / src.name
            shutil.copy2(src, dst)
            copied.append(dst)

    manifest = {
        "project": "APlusOptionsScannerV3",
        "trading_date": day,
        "created_at": datetime.now().astimezone().isoformat(),
        "paper_only": True,
        "live_orders_enabled": False,
        "files": [summarize(p) for p in copied],
        "missing_files": missing,
    }
    mp = day_dir / "after_market_manifest.json"
    mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    copied.append(mp)

    zip_path = OUT / f"APlus_AfterMarket_{day}.zip"
    tmp = OUT / f".APlus_AfterMarket_{day}.tmp"
    if tmp.exists():
        tmp.unlink()
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in copied:
            if p.is_file():
                zf.write(p, p.name)
    tmp.replace(zip_path)

    latest = OUT / "APlus_AfterMarket_LATEST.zip"
    shutil.copy2(zip_path, latest)

    print("="*68)
    print("APLUS AFTER-MARKET PACKAGE READY")
    print("Trading date :", day)
    print("ZIP          :", zip_path)
    print("LATEST       :", latest)
    print("Files copied :", len(copied))
    print("Missing      :", len(missing))
    print("Upload only  :", latest)
    print("="*68)

if __name__ == "__main__":
    main()
