"""Research test (no trading effect): an early-burst trigger - the stock's volume surges while the option premium jumps.

Events come from the saved 5-minute stock candles (data/pattern_log/candles/<day>.json): a bar whose volume is at least VOL_X times the average of the previous 12 bars and whose body
is at least BODY_PCT in one direction (up = call, down = put), between 09:45 and 14:30, at most one per stock every 30 minutes. For each event the ~0.5% ITM option of that side
(nearest expiry) is priced from Upstox 1-minute candles: how far the premium had already jumped during the bar (jump5) and during its last two minutes (jump2), and what the option
did afterwards. Entry = the close of the bar's last minute + 1% slippage (decision time = bar close), labelled with the strict test (+10% before -20%).

    data/strict_labels/burst_events.csv      one row per event
    python burst_test.py
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

import strict_label as sl

ROOT = Path(__file__).resolve().parent
VOL_X, BODY_PCT, FIRST, LAST = 3.0, 0.4, 585, 870


def find_events(day: str, symbols: dict) -> list[dict]:
    out = []
    for sym, d in symbols.items():
        m, o, h, l, c, v = d["minute"], d["open"], d["high"], d["low"], d["close"], d["volume"]
        last = -999
        for i in range(12, len(m)):
            if not FIRST <= m[i] <= LAST or o[i] <= 0:
                continue
            avg = float(np.mean(v[i - 12:i]))
            if avg <= 0:
                continue
            body = (c[i] / o[i] - 1) * 100
            if v[i] >= VOL_X * avg and abs(body) >= BODY_PCT and m[i] - last >= 30:
                last = m[i]
                out.append({"day": day, "symbol": sym, "dir": "BULLISH" if body > 0 else "BEARISH", "bar": m[i], "vol_x": round(v[i] / avg, 1), "body_pct": round(body, 2), "spot": c[i]})
    return out


def price_at(bars, minute):
    p = [b for b in bars if b[0] <= minute]
    return p[-1][4] if p else None


def main() -> int:
    days = sorted(Path(p).stem for p in glob.glob(str(ROOT / "data" / "pattern_log" / "candles" / "2026-10-*.json")) if Path(p).stem >= "2026-10-07")
    src = sl.Source(pause=0.3)
    und = sl._underlyings(src, ROOT)
    rows = []
    for day in days:
        symbols = json.load(open(ROOT / "data" / "pattern_log" / "candles" / f"{day}.json"))["symbols"]
        for ev in find_events(day, symbols):
            ukey = und.get(ev["symbol"])
            if not ukey:
                continue
            try:
                exps = [e for e in src.expiries(ukey) if e >= day]
                ct = sl.pick_contract(src.contracts(ukey, exps[0], False), ev["dir"] == "BULLISH", ev["spot"])
                bars = src.candles(ct["key"], day, False)
            except Exception as exc:
                print(day, ev["symbol"], "skipped:", str(exc)[:80], flush=True)
                continue
            if not bars:
                continue
            start, end = ev["bar"], ev["bar"] + 4            # the bar's first and last minute
            p0, p_end, p_2 = price_at(bars, start - 1), price_at(bars, end), price_at(bars, end - 2)
            lab = sl.label(bars, end, 0)
            if not lab or not p0 or not p_end or p_end <= 0:
                continue
            after = [b for b in bars if b[0] > end and b[0] <= 15 * 60 + 25]
            peak = max(after, key=lambda b: b[2]) if after else None
            rows.append({**ev, "strike": ct["strike"], "opt_start": round(p0, 2), "opt_end": round(p_end, 2), "jump5": round((p_end / p0 - 1) * 100, 1),
                         "jump2": round((p_end / p_2 - 1) * 100, 1) if p_2 else "", "entry": lab["entry"], "hit10_first": lab["hit10_first"], "stop_first": lab["stop_first"],
                         "best_30": lab["best_30"], "best_day": lab["best_day"], "worst_day": lab["worst_day"], "close_pct": lab["close_pct"],
                         "t_peak": (peak[0] - end) if peak else "", "peak_vs_start_pct": round((peak[2] / p0 - 1) * 100, 1) if peak else ""})
        print(day, len(rows), "events so far, calls", src.calls, flush=True)
        pd.DataFrame(rows).to_csv(ROOT / "data" / "strict_labels" / "burst_events.csv", index=False)
    print("done", len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
