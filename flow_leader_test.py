"""Research test (no trading effect): would picking the money-flow leaders at 09:30 / 10:00 have found good option trades?

From data/order_book/<day>.csv (once-a-minute readings of every F&O stock) it rebuilds the money-flow state with money_flow.step / build up to the checkpoint, then takes
  calls: stock flow >= +FLOW_PCT, its sector flow >= +SEC_PCT and stock net flow >= NET_CR crore;  puts: the mirror image
ranked by the size of the net flow, top TOP_N overall. Each pick's ATM-ish option (about 0.5% ITM, nearest expiry) is priced from Upstox 1-minute candles, entry = checkpoint + 1 minute,
+1% slippage, and labelled with the strict test (+10% before -20%).
"""
import copy, csv, glob, sys
from pathlib import Path
import pandas as pd
import money_flow as mf
import strict_label as sl

ROOT = Path(__file__).resolve().parent
FLOW_PCT, SEC_PCT, NET_CR, TOP_N = 10.0, 5.0, 20.0, 5
CHECKS = ("09:30", "10:00")


def picks_for_day(day, sectors):
    path = ROOT / "data" / "order_book" / f"{day}.csv"
    rows = sorted(csv.DictReader(path.open(encoding="utf-8")), key=lambda r: r["time"])
    state, out, done = {}, {}, set()
    for r in rows:
        t = r["time"][11:16]
        for c in CHECKS:
            if c not in done and t >= c:
                done.add(c)
                out[c] = mf.build(copy.deepcopy(state), c, 0, sectors, {})
        try:
            mf.step(state, r["symbol"], r["time"][11:19], float(r["ltp"]), float(r["volume"]), float(r["imbalance"] or 0))
        except (ValueError, KeyError):
            continue
    return out


def choose(p):
    secs = {s["sector"]: s for s in p["sectors"] if s["stocks"] >= 2}
    cand = []
    for st in p["stocks"]:
        s = secs.get(st["sector"])
        if not s:
            continue
        if st["flow_pct"] >= FLOW_PCT and s["flow_pct"] >= SEC_PCT and st["net_cr"] >= NET_CR:
            cand.append((abs(st["net_cr"]), st["symbol"], "BULLISH", st))
        elif st["flow_pct"] <= -FLOW_PCT and s["flow_pct"] <= -SEC_PCT and st["net_cr"] <= -NET_CR:
            cand.append((abs(st["net_cr"]), st["symbol"], "BEARISH", st))
    return sorted(cand, reverse=True)[:TOP_N]


def main():
    sectors = mf._sector_map(ROOT)
    src = sl.Source(pause=0.3)
    und = sl._underlyings(src, ROOT)
    rows = []
    for f in sorted(glob.glob(str(ROOT / "data" / "order_book" / "20*.csv"))):
        day = Path(f).stem
        if day < "2026-10-08":
            continue
        for chk, p in picks_for_day(day, sectors).items():
            for _, sym, dirn, st in choose(p):
                ukey = und.get(sym)
                if not ukey:
                    continue
                try:
                    exps = [e for e in src.expiries(ukey) if e >= day]
                    ct = sl.pick_contract(src.contracts(ukey, exps[0], False), dirn == "BULLISH", st["ltp"])
                    bars = src.candles(ct["key"], day, False)
                    h, m = chk.split(":")
                    lab = sl.label(bars, int(h) * 60 + int(m), 1)
                except Exception as exc:
                    print(day, sym, "skipped:", str(exc)[:80], flush=True)
                    continue
                if lab:
                    rows.append(dict(day=day, check=chk, symbol=sym, dir=dirn, stock_flow=st["flow_pct"], net_cr=st["net_cr"], **{k: lab[k] for k in ("entry", "hit10_first", "stop_first", "best_day", "worst_day", "close_pct")}))
        print(day, len(rows), "picks so far", flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(ROOT / "data" / "strict_labels" / "flow_leaders.csv", index=False)
    print(len(d), "picks;", d.day.nunique(), "days")
    for key in (None, "check", "dir"):
        g = d if key is None else None
        grp = [("all", d)] if key is None else list(d.groupby(key))
        for name, x in grp:
            print(f"{str(name):8s} n={len(x):3d} per day {len(x)/d.day.nunique():.1f} hit+10 {x.hit10_first.mean()*100:3.0f}% stop {x.stop_first.mean()*100:3.0f}% median best {x.best_day.median():+.0f}% median close {x.close_pct.median():+.0f}%")
    print(d.groupby("day").agg(n=("symbol", "size"), hit=("hit10_first", lambda s: round(s.mean() * 100)), stop=("stop_first", lambda s: round(s.mean() * 100)), close=("close_pct", "median")).to_string())


if __name__ == "__main__":
    main()
