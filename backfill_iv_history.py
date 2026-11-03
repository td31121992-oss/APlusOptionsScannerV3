"""Fill data/iv_history/<SYMBOL>.csv from the downloaded option history (local files only, no API calls).

For each stock and day: the average of the ATM call and ATM put implied volatility at the first 5-minute bar from 09:20 with data
(the scanner records its first sighting, normally just after 09:20). Days already recorded are kept. See iv_history.py.

    python backfill_iv_history.py [--days 120] [--symbols A,B]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def day_ivs(symbol: str, start: str, end: str) -> dict[str, float]:
    from options_history import load_series

    ce = load_series(symbol, "CALL", 0, start=start, end=end)
    pe = load_series(symbol, "PUT", 0, start=start, end=end)
    if ce.empty or pe.empty:
        return {}
    out: dict[str, float] = {}
    both = ce[["iv"]].join(pe[["iv"]], lsuffix="_c", rsuffix="_p", how="inner")
    both = both[(both.iv_c > 0) & (both.iv_p > 0)]
    both = both[(both.index.hour * 60 + both.index.minute) >= 9 * 60 + 20]
    for d, g in both.groupby(both.index.date):
        r = g.iloc[0]
        out[d.isoformat()] = round(float((r.iv_c + r.iv_p) / 2.0), 2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--symbols", default="")
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT))
    import iv_history
    from options_history import DEFAULT_ROOT

    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] or sorted(p.name for p in Path(DEFAULT_ROOT).iterdir() if p.is_dir() and not p.name.startswith("_"))
    end, start = date.today().isoformat(), (date.today() - timedelta(days=a.days)).isoformat()
    filled = 0
    for s in syms:
        try:
            days = day_ivs(s, start, end)
        except Exception as exc:                           # noqa: BLE001
            print(s, "skipped:", exc)
            continue
        have = {d for d, _ in iv_history.load(s)}
        for d, v in sorted(days.items()):
            if d not in have:
                iv_history.record(s, v, d)
                filled += 1
        print(s, len(days), flush=True)
    print("rows added:", filled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
