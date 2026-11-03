"""Research replay (no trading effect): what 'move the stop to cost' variants would have done on every paper trade since 22 Sep, from Upstox 1-minute option candles.

Baseline replica of the live exit logic: initial stop -20%; at +20% (T1) stop to entry; at +35% (T2) stop to +8%; at +50% (T3) runner: stop = max(+15%, entry + 70% of the best gain so far).
Variants add: when the best gain reaches X% the stop moves up to entry (cost) if it is below it. A stop is checked against each 1-minute bar's low BEFORE that bar's high can raise it (conservative);
a stop fills at the stop price (or the bar's open if it gapped through). Costs: the real trade's cost (net - gross) is added to every replay.
"""
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd
import strict_label as sl

ROOT = Path(__file__).resolve().parent
END_MIN = 15 * 60 + 25


def simulate(bars, entry_min, entry, cost_at=None, init=0.20, t1=0.20, t2=0.35, t3=0.50):
    stop = entry * (1 - init)
    best = entry
    for b in bars:
        m, o, h, l, c = b
        if m <= entry_min:
            continue
        if m > END_MIN:
            break
        if l <= stop:
            return m, min(o, stop), "STOP"
        best = max(best, h)
        gain = best / entry - 1
        if cost_at is not None and gain >= cost_at:
            stop = max(stop, entry)
        if gain >= t1:
            stop = max(stop, entry)
        if gain >= t2:
            stop = max(stop, entry * 1.08)
        if gain >= t3:
            stop = max(stop, entry * 1.15, entry + 0.70 * (best - entry))
    last = [b for b in bars if entry_min < b[0] <= END_MIN]
    return (last[-1][0], last[-1][4], "SESSION_END") if last else (entry_min, entry, "NONE")


def main():
    h = pd.read_csv(ROOT / "data" / "reports" / "paper_trade_history.csv", low_memory=False)
    j = json.load(open(ROOT / "data" / "intraday_movement" / "paper_trade_journal.json"))
    cur = pd.DataFrame(j["trades"] if isinstance(j, dict) else j)
    d = pd.concat([h, cur], ignore_index=True)
    d["k"] = d.symbol.astype(str) + d.entry_time.astype(str)
    d = d.drop_duplicates("k", keep="last").copy()
    for c in ("entry_price", "exit_price", "quantity", "net_pnl", "strike"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d[(d.status.astype(str).str.upper() == "CLOSED") & d.net_pnl.notna() & (d.entry_price > 0) & (d.quantity > 0)].copy()
    d["day"] = d.entry_time.astype(str).str[:10]
    d = d[d.day >= "2026-09-22"]
    src = sl.Source(pause=0.25)
    und = sl._underlyings(src, ROOT)
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    variants = {"baseline": None, "cost@8": 0.08, "cost@10": 0.10, "cost@15": 0.15}
    rows = []
    for r in d.itertuples():
        try:
            ukey = und.get(str(r.symbol).upper())
            exp = str(r.expiry)[:10]
            expired = exp < today
            cts = src.contracts(ukey, exp, expired)
            side = "CE" if "CE" in str(r.option_type).upper() or str(r.option_type).upper().startswith("C") else "PE"
            ct = next((c for c in cts if c["type"] == side and abs(c["strike"] - float(r.strike)) < 1e-6), None)
            if ct is None:
                continue
            bars = src.candles(ct["key"], r.day, expired)
            em = int(str(r.entry_time)[11:13]) * 60 + int(str(r.entry_time)[14:16])
            if not bars:
                continue
        except Exception as exc:
            print(r.symbol, r.day, "skipped:", str(exc)[:80], flush=True)
            continue
        gross_real = (r.exit_price - r.entry_price) * r.quantity if r.exit_price == r.exit_price else 0
        cost = r.net_pnl - gross_real
        row = dict(day=r.day, symbol=r.symbol, direction=r.direction, qty=r.quantity, entry=r.entry_price, real=r.net_pnl)
        for name, th in variants.items():
            m, px, why = simulate(bars, em, r.entry_price, cost_at=th)
            row[name] = (px - r.entry_price) * r.quantity + cost
            row[name + "_why"] = why
        rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(ROOT / "data" / "reports" / "ladder_replay.csv", index=False)
    print(len(out), "trades replayed")
    print("real net", round(out.real.sum()))
    for n in variants:
        print(f"{n:10s} net {out[n].sum():+10.0f}   vs baseline {out[n].sum() - out.baseline.sum():+8.0f}   wins {(out[n] > 0).sum()}")
    print("baseline replica vs real, per-trade mean abs diff:", round((out.baseline - out.real).abs().mean()), "| total diff", round(out.baseline.sum() - out.real.sum()))


if __name__ == "__main__":
    main()
