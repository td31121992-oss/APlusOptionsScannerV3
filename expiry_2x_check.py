"""Does "buy an at-the-money option near 09:30 and sell it when it doubles" work on REAL bid / ask prices? (RESEARCH ONLY). python expiry_2x_check.py

The 5-year candle data suggested +10% per trade for options of Rs 20+ with 0-3 days to expiry, but candles are trade prints (entry at the candle open, stray high prints, no spread). This repeats the
test on the Upstox chain captures the collector saves every 5 minutes (data/options_intelligence_upstox/<day>/option_chain_rows.csv.gz): buy the at-the-money call and put of the nearest expiry
at the ASK of the capture nearest 09:30, sell at the BID: either at +100% (the first capture whose bid is at least double the entry ask) or at the last bid before 15:25.
Needs expiry-week days in the folder (the monthly expiry is the 4th Tuesday: next ones 24 Nov and 29 Dec 2026); a file cut short is read as far as it goes. Writes expiry_2x_real_quotes.csv to E:.
"""

from __future__ import annotations

import glob
import gzip
import io
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = Path(r"E:\APlusData\top_movers_study") / "expiry_2x_real_quotes.csv"
MIN_ASK = 20.0
TARGET = 100.0


def read(path: str) -> pd.DataFrame:
    raw = bytearray()
    try:
        with gzip.open(path, "rb") as h:
            while True:
                c = h.read(4096)
                if not c:
                    break
                raw += c
    except Exception:                                    # noqa: BLE001 - a file cut short is read as far as it goes
        pass
    return pd.read_csv(io.StringIO(raw.decode("utf-8", "ignore")), on_bad_lines="skip", engine="python")


def main() -> pd.DataFrame:
    rows = []
    for f in sorted(glob.glob(str(ROOT / "data" / "options_intelligence_upstox" / "2026-*" / "option_chain_rows.csv.gz"))):
        day = os.path.basename(os.path.dirname(f))
        d = read(f)
        for c in ("spot", "strike", "ltp", "bid", "ask"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d["t"] = pd.to_datetime(d.captured_at.astype(str).str[:19], errors="coerce")
        d = d.dropna(subset=["t"])
        if d.empty:
            continue
        d["hm"] = d.t.dt.hour * 60 + d.t.dt.minute
        exp = pd.Timestamp(sorted(d.expiry.astype(str).unique())[0])
        dte = (exp - pd.Timestamp(day)).days
        d = d[d.expiry.astype(str) == str(exp.date())]
        t0 = d[(d.hm >= 9 * 60 + 28) & (d.hm <= 9 * 60 + 36)].t.min()
        if pd.isna(t0) or d.t.max().hour * 60 + d.t.max().minute < 15 * 60 + 20:
            continue                                     # no 09:30 capture, or the day is incomplete
        snap = d[d.t == t0].copy()
        snap["dist"] = (snap.strike - snap.spot).abs()
        atm = snap.sort_values("dist").groupby(["symbol", "side"]).head(1)
        atm = atm[(atm.ask >= MIN_ASK) & (atm.bid > 0) & (atm.ask >= atm.bid)]
        paths = dict(tuple(d[(d.t > t0) & (d.hm <= 15 * 60 + 25)].groupby("option_security_id")))
        for r in atm.itertuples():
            p = paths.get(r.option_security_id)
            if p is None or len(p) < 20:
                continue
            pb = p.bid[p.bid > 0]
            if pb.empty:
                continue
            rows.append({"day": day, "dte": dte, "sym": r.symbol, "side": r.side, "entry_ask": r.ask, "spread_pct": (r.ask - r.bid) / r.ask * 100, "best_bid": pb.max(), "last_bid": pb.iloc[-1]})
    d = pd.DataFrame(rows)
    if d.empty:
        print("no complete expiry-week days found")
        return d
    d["best_pct"] = (d.best_bid / d.entry_ask - 1) * 100
    d["close_pct"] = (d.last_bid / d.entry_ask - 1) * 100
    d["rule"] = np.where(d.best_pct >= TARGET, TARGET, d.close_pct)
    d.to_csv(OUT, index=False)
    g = d.groupby(["day", "dte"]).agg(n=("rule", "size"), median_spread=("spread_pct", "median"), touch_2x_on_bid=("best_pct", lambda x: (x >= TARGET).mean() * 100),
                                      close_avg=("close_pct", "mean"), rule_avg=("rule", "mean")).round(1)
    print(g.to_string())
    near = d[d.dte <= 3]
    if len(near):
        print(f"\nDTE 0-3: {len(near)} trades over {near.day.nunique()} days: touch +100% on the bid {(near.best_pct >= TARGET).mean() * 100:.1f}%, rule avg {near.rule.mean():.1f}%, win {(near.rule > 0).mean() * 100:.0f}%")
    return d


if __name__ == "__main__":
    main()
