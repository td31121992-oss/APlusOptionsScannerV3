"""Exit-ladder search on recorded option ticks (read-only research; no trading effect).

Which kind of stop / profit-lock ladder works? Every closed paper trade that has recorded option ticks (data/option_ticks/<day>/, from 26 Oct 2026) is replayed tick by tick under many ladders:

    initial stop   S % below entry
    break-even     once the highest price reaches +B %, the stop moves up to the entry price (B = none: never)
    trail          once the highest price reaches +A %, the stop is  entry + (peak gain) * (1 - G)  (give back at most G of the peak gain); none: never
    exit           the first tick at or below the stop, filled at that tick's last price; if never stopped: the last tick of the day (session end), less the average round-trip cost

The live "old rules" ladder (initial stop from the trade, target 1 -> entry, target 2 -> +8%, target 3 -> runner at +15% / 70% of the peak gain) is replayed the same way, and compared with
what really happened, to show how faithful the replay is.

To avoid picking a ladder that only fits past noise, the days are split: ladders are ranked on the first days (train) and judged on the later days (test), and the average effect of each
setting across all combinations is shown (a setting that helps on average is more trustworthy than one lucky combination).

    python ladder_search.py
"""

from __future__ import annotations

import itertools
import statistics as st
import sys
from datetime import date
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent
INITIAL = (15, 18, 22, 25, 30)
BREAKEVEN = (None, 8, 10, 15)
TRAILS = (None, (15, 0.4), (20, 0.3), (20, 0.4), (20, 0.5), (30, 0.3), (30, 0.4))
TRAIN_DAYS = 6


def ladder_exit(entry: float, ticks: Sequence[tuple[float, float]], stop_pct: float, be: float | None, trail: tuple[float, float] | None) -> float:
    """Exit price of one trade under a ladder. `ticks` = [(seconds, ltp)] from the entry on."""
    stop, high = entry * (1 - stop_pct / 100), entry
    for _, px in ticks:
        if px <= stop:
            return px
        if px > high:
            high = px
            if be is not None and high >= entry * (1 + be / 100):
                stop = max(stop, entry)
            if trail is not None and high >= entry * (1 + trail[0] / 100):
                stop = max(stop, entry + (high - entry) * (1 - trail[1]))
    return ticks[-1][1]


def old_rules_exit(trade: dict[str, Any], entry: float, ticks: Sequence[tuple[float, float]]) -> float:
    """The live ladder: initial stop, T1 -> entry, T2 -> +8%, T3 -> runner (floor +15%, 70% trail of the peak gain)."""
    stop0 = float(trade.get("option_stop") or 0)
    t1, t2, t3 = (float(trade.get(k) or 0) for k in ("option_target1", "option_target2", "option_target3"))
    stop, high, h1, h2, h3 = stop0, entry, False, False, False
    for _, px in ticks:
        if stop > 0 and px <= stop:
            return px
        if px > high:
            high = px
        h1, h2, h3 = h1 or (t1 > 0 and px >= t1), h2 or (t2 > 0 and px >= t2), h3 or (t3 > 0 and px >= t3)
        if h1:
            stop = max(stop, entry)
        if h2:
            stop = max(stop, entry * 1.08)
        if h3:
            stop = max(stop, entry * 1.15, entry + (high - entry) * 0.70)
    return ticks[-1][1]


def main() -> int:
    sys.path.insert(0, str(ROOT))
    import shadow_scoreboard as sb
    from entry_filter_replay import load_ticks, seconds_of

    trades = sb.load_trades(upto=date.today().isoformat())
    cost = st.mean(float(t.get("gross_pnl") or 0) - float(t["net_pnl"]) for t in trades if t.get("gross_pnl") not in (None, ""))
    data: list[tuple[dict[str, Any], float, float, list[tuple[float, float]]]] = []
    for t in trades:
        tk = load_ticks(str(t.get("option_security_id")), t["_day"], ROOT)
        t0 = seconds_of(t.get("entry_time"))
        if not tk or t0 is None:
            continue
        path = [(s, ltp) for s, ltp, _ in tk if s >= t0]
        if len(path) >= 3:
            data.append((t, float(t["entry_price"]), float(t["quantity"]), path))
    days = sorted({t["_day"] for t, *_ in data})
    train_days = set(days[:TRAIN_DAYS])
    print(f"{len(data)} trades with ticks over {len(days)} days ({days[0]} .. {days[-1]}); train = first {TRAIN_DAYS} days, test = the rest; round-trip cost Rs {cost:.0f}\n")

    def evaluate(fn) -> dict[str, float]:
        tr = te = 0.0
        nt = ne = 0
        allp = []
        for t, entry, qty, path in data:
            p = (fn(t, entry, path) - entry) * qty - cost
            allp.append(p)
            if t["_day"] in train_days:
                tr += p
                nt += 1
            else:
                te += p
                ne += 1
        return {"train": tr, "test": te, "all": tr + te, "n_train": nt, "n_test": ne, "win": 100 * sum(1 for x in allp if x > 0) / len(allp), "avg": st.mean(allp), "worst": min(allp)}

    real_all = sum(float(t["net_pnl"]) for t, *_ in data)
    base = evaluate(lambda t, e, path: old_rules_exit(t, e, path))
    print(f"REAL result of these trades: Rs {real_all:,.0f}   |   old rules replayed on ticks: Rs {base['all']:,.0f} (train {base['train']:,.0f}, test {base['test']:,.0f}, win {base['win']:.0f}%)  <- replay fidelity\n")

    rows = []
    for s, be, tr in itertools.product(INITIAL, BREAKEVEN, TRAILS):
        r = evaluate(lambda t, e, path, s=s, be=be, tr=tr: ladder_exit(e, path, s, be, tr))
        rows.append(((s, be, tr), r))

    def name(k):
        s, be, tr = k
        return f"stop -{s}% | BE {'none' if be is None else f'+{be}%':>5} | trail {'none' if tr is None else f'+{tr[0]}% give {int(tr[1] * 100)}%':>16}"

    print("TOP 8 ON THE TRAIN DAYS, and how they did on the unseen test days")
    print(f"  {'ladder':58s} train       test        all     win%  avg/trade  worst")
    for k, r in sorted(rows, key=lambda x: -x[1]["train"])[:8]:
        print(f"  {name(k):58s} {r['train']:8,.0f}  {r['test']:9,.0f}  {r['all']:9,.0f}  {r['win']:4.0f}  {r['avg']:8.0f}  {r['worst']:7,.0f}")
    print(f"  {'(old rules, the live ladder)':58s} {base['train']:8,.0f}  {base['test']:9,.0f}  {base['all']:9,.0f}  {base['win']:4.0f}  {base['avg']:8.0f}  {base['worst']:7,.0f}")

    print("\nTOP 8 OVERALL (hindsight; read with the table above)")
    for k, r in sorted(rows, key=lambda x: -x[1]["all"])[:8]:
        print(f"  {name(k):58s} {r['train']:8,.0f}  {r['test']:9,.0f}  {r['all']:9,.0f}  {r['win']:4.0f}  {r['avg']:8.0f}  {r['worst']:7,.0f}")

    print("\nAVERAGE EFFECT OF EACH SETTING (mean over all combinations; train / test / all, Rs)")
    for label, idx, options in (("initial stop", 0, INITIAL), ("break-even trigger", 1, BREAKEVEN), ("trail", 2, TRAILS)):
        for o in options:
            sel = [r for k, r in rows if k[idx] == o]
            lab = "none" if o is None else (f"-{o}%" if idx == 0 else (f"+{o}%" if idx == 1 else f"+{o[0]}% give {int(o[1] * 100)}%"))
            print(f"  {label:20s} {lab:18s} train {st.mean(r['train'] for r in sel):9,.0f}  test {st.mean(r['test'] for r in sel):9,.0f}  all {st.mean(r['all'] for r in sel):9,.0f}")
    better = sum(1 for k, r in rows if r["train"] > base["train"] and r["test"] > base["test"])
    print(f"\n{better} of {len(rows)} ladders beat the live old rules on BOTH the train and the test days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
