from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DAY = "2026-08-20"

SRC = ROOT / "data" / "chart_engine_research_v2" / DAY / "full_market_timeline.csv"
MARKET = ROOT / "data" / "reports" / "fno_market_watch_latest.json"
OUTDIR = ROOT / "data" / "chart_history" / DAY
OUT = OUTDIR / "market_watch_1m.csv"

FIELDS = [
    "timestamp","date","minute","symbol","security_id","sector","ltp",
    "open_0915","previous_close","gap_pct","from_open_pct",
    "from_prev_close_pct","day_high","day_low","range_position_pct","direction"
]

def f(v, default=""):
    try:
        if v in ("", None):
            return default
        return float(v)
    except Exception:
        return default

def load_market():
    meta = {}
    if not MARKET.exists():
        return meta
    try:
        d = json.loads(MARKET.read_text(encoding="utf-8"))
        for r in d.get("rows", []) or []:
            sym = str(r.get("symbol") or "").upper().strip()
            if not sym:
                continue
            meta[sym] = r
    except Exception:
        pass
    return meta

def main():
    print("=" * 90)
    print("APlus Stock Charts - Backfill 20-Aug-2026")
    print("Uses existing Chart Engine V2 timeline - ZERO Dhan API calls")
    print("=" * 90)

    if not SRC.exists():
        raise SystemExit(f"FAIL: missing {SRC}")

    meta = load_market()
    best = {}

    with SRC.open("r", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            sym = str(r.get("symbol") or "").upper().strip()
            ts = str(r.get("snapshot_time") or "").strip()
            if not sym or not ts:
                continue
            try:
                d = datetime.fromisoformat(ts)
            except Exception:
                continue
            minute = d.strftime("%H:%M")
            key = (sym, minute)
            # keep the latest row inside each minute
            best[key] = (d, r)

    rows = []
    for (sym, minute), (d, r) in sorted(best.items(), key=lambda x: (x[0][0], x[1][0])):
        m = meta.get(sym, {})
        rows.append({
            "timestamp": d.isoformat(),
            "date": DAY,
            "minute": minute,
            "symbol": sym,
            "security_id": m.get("security_id", ""),
            "sector": m.get("sector", ""),
            "ltp": m.get("ltp", ""),
            "open_0915": m.get("open_0915", ""),
            "previous_close": m.get("previous_close", ""),
            "gap_pct": m.get("gap_pct", ""),
            "from_open_pct": r.get("from_open_pct", ""),
            "from_prev_close_pct": m.get("from_prev_close_pct", ""),
            "day_high": m.get("day_high", ""),
            "day_low": m.get("day_low", ""),
            "range_position_pct": m.get("range_pos_pct", m.get("range_position_pct", "")),
            "direction": r.get("direction", ""),
        })

    if not rows:
        raise SystemExit("FAIL: no timeline rows found")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    symbols = len({r["symbol"] for r in rows})
    print("SUCCESS")
    print("Output :", OUT)
    print("Rows   :", len(rows))
    print("Symbols:", symbols)
    print("")
    print("IMPORTANT:")
    print("- Today's graph is reconstructed from persisted scanner/Chart Engine state.")
    print("- It is suitable for intraday path/forensic review.")
    print("- It is NOT an exact tick/candlestick OHLC reconstruction.")
    print("- Tomorrow the live collector will build native minute history automatically.")
    print("=" * 90)

if __name__ == "__main__":
    main()
