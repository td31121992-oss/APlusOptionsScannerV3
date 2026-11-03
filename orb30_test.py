"""Research test (no trading effect): the 30-minute opening-range breakout + retest idea seen on another tool, measured with the strict +10%-before--20% label.

For every stock and day with saved 5-minute candles (data/pattern_log/candles/<day>.json):
  range   = high/low of the 09:15-09:44 bars (six 5-minute bars)
  break   = first 5-minute close after 09:45 outside the range (long above the high, short below the low)
  retest  = within the next 12 bars a bar that touches back to the broken edge but closes outside it again
The option (about 0.5% ITM put for a short, call for a long, nearest expiry) is priced from Upstox 1-minute candles; entry = signal minute + 1, +1% slippage.

    data/strict_labels/orb30_events.csv      one row per event
    data/strict_labels/orb30_summary.md      hit-before-stop by variant, range width, hour, direction, volume, market agreement
"""
import csv, glob, json, sys, statistics as st
from pathlib import Path
import numpy as np
import pandas as pd
import strict_label as sl

ROOT = Path(__file__).resolve().parent
OR_END = 585          # 09:45 (first bar after the opening range starts here)


def events_for(sym: str, d: dict) -> list[dict]:
    m, o, h, l, c, v = d["minute"], d["open"], d["high"], d["low"], d["close"], d["volume"]
    idx = [i for i, x in enumerate(m) if 555 <= x < OR_END]
    if len(idx) < 5:
        return []
    orh, orl = max(h[i] for i in idx), min(l[i] for i in idx)
    base = o[idx[0]]
    if base <= 0 or orh <= orl:
        return []
    rng = (orh - orl) / base * 100
    avgv = np.mean([v[i] for i in idx]) or 1.0
    out = []
    first = {}
    for i, x in enumerate(m):
        if x < OR_END:
            continue
        side = "BULLISH" if c[i] > orh else ("BEARISH" if c[i] < orl else None)
        if side and side not in first:
            first[side] = i
            out.append(dict(symbol=sym, kind="break", dir=side, minute=x + 5, spot=c[i], range_pct=round(rng, 2), vol_x=round(v[i] / avgv, 2)))
            edge = orh if side == "BULLISH" else orl
            for j in range(i + 1, min(len(m), i + 13)):
                touched = l[j] <= edge if side == "BULLISH" else h[j] >= edge
                closed_out = c[j] > edge if side == "BULLISH" else c[j] < edge
                if touched and closed_out:
                    out.append(dict(symbol=sym, kind="retest", dir=side, minute=m[j] + 5, spot=c[j], range_pct=round(rng, 2), vol_x=round(v[j] / avgv, 2)))
                    break
    return out


def main() -> int:
    days = sorted(Path(p).stem for p in glob.glob(str(ROOT / "data" / "pattern_log" / "candles" / "20*.json")))
    src = sl.Source(pause=0.3)
    und = sl._underlyings(src, ROOT)
    rows = []
    for day in days:
        S = json.load(open(ROOT / "data" / "pattern_log" / "candles" / f"{day}.json"))["symbols"]
        nifty = None
        today = pd.Timestamp.now().strftime("%Y-%m-%d")
        for sym, d in S.items():
            ukey = und.get(sym)
            if not ukey:
                continue
            for ev in events_for(sym, d):
                try:
                    exps = [e for e in src.expiries(ukey) if e >= day]
                    if not exps:
                        continue
                    exp = exps[0]
                    expired = exp < today
                    ct = sl.pick_contract(src.contracts(ukey, exp, expired), ev["dir"] == "BULLISH", ev["spot"])
                    if ct is None:
                        continue
                    bars = src.candles(ct["key"], day, expired)
                    lab = sl.label(bars, ev["minute"], 1)
                except Exception as exc:
                    print(day, sym, "skipped:", str(exc)[:80], flush=True)
                    continue
                if lab:
                    rows.append(dict(day=day, **ev, **{k: lab[k] for k in ("entry", "hit10_first", "stop_first", "best_day", "worst_day", "close_pct", "hit10_30")}))
        print(day, len(rows), "events so far, calls", src.calls, flush=True)
        pd.DataFrame(rows).to_csv(ROOT / "data" / "strict_labels" / "orb30_events.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
