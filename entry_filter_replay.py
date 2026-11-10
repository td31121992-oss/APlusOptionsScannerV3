"""Entry-filter replay: spread cap and momentum confirmation (read-only research; no trading effect).

Follow-up of time_stop_replay.py (10 Nov 2026): waiting 30 minutes to cut a trade does not help, because a trade that is going to fail has already lost most of its money by then and
exiting costs the bid-ask spread. So the question moves to the entry:

  A. Spread cap     keep only trades whose option bid-ask spread at entry was at most X% (recorded on every closed paper trade).
  B. Momentum       after entry-signal time t0, wait k minutes; only take the trade if the option is then at or above entry * (1 + g) (last traded price from the recorded ticks).
                    A confirmed trade is re-priced: bought at the ask at t0 + k, sold where it really ended (real exit price), less the average round-trip cost.
                    A trade that was already closed (stopped out) before t0 + k is a trade that would not have been taken.
  C. Both           spread cap and momentum together.

Each row shows trades kept, win rate, net Rs, average per trade with a 95% bootstrap range, and the real net of what the filter removes. Everything is hindsight on paper trades,
before real fills; a filter chosen by looking at these same trades is partly fitted, so a result needs more sessions before it is trusted.

    python entry_filter_replay.py
"""

from __future__ import annotations

import csv
import glob
import gzip
import random
import statistics as st
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SPREADS = (0.5, 1.0, 1.5, 2.0, 3.0, 5.0)
CHECKS = ((3, 0.0), (5, 0.0), (10, 0.0), (5, 0.02), (10, 0.02))


def load_ticks(security_id: str, day: str, root: Path = ROOT) -> list[tuple[float, float, float]] | None:
    """[(seconds_since_midnight, ltp, ask)] in time order; None when nothing was recorded."""
    files = glob.glob(str(root / "data" / "option_ticks" / day / f"{security_id}_*.csv.gz"))
    if not files:
        return None
    out: list[tuple[float, float, float]] = []
    try:
        with gzip.open(files[0], "rt", encoding="utf-8", newline="") as h:
            for row in csv.DictReader(h):
                try:
                    hh, mm, ss = row["ts"].split(":")
                    ltp = float(row["ltp"])
                    ask = float(row["ask"]) if row.get("ask") not in (None, "", "nan") else ltp
                    out.append((int(hh) * 3600 + int(mm) * 60 + float(ss), ltp, ask if ask > 0 else ltp))
                except (ValueError, KeyError):
                    continue
    except (EOFError, OSError):                              # a file cut short: use the ticks read before the break
        pass
    out.sort(key=lambda r: r[0])
    return out or None


def seconds_of(stamp: Any) -> float | None:
    try:
        t = datetime.fromisoformat(str(stamp))
        return t.hour * 3600 + t.minute * 60 + t.second
    except ValueError:
        return None


def summary(pnls: list[float]) -> str:
    if not pnls:
        return "n=  0"
    random.seed(7)
    means = sorted(sum(random.choices(pnls, k=len(pnls))) / len(pnls) for _ in range(3000))
    lo, hi = (means[int(.025 * 3000)], means[int(.975 * 3000)]) if len(pnls) >= 8 else (float("nan"), float("nan"))
    win = 100 * sum(1 for x in pnls if x > 0) / len(pnls)
    return f"n={len(pnls):3d}  win={win:3.0f}%  net={sum(pnls):9,.0f}  avg={st.mean(pnls):6.0f}  (95% {lo:6.0f} .. {hi:6.0f})"


def confirm(trade: dict[str, Any], ticks: list[tuple[float, float, float]], k: int, g: float, cost: float) -> tuple[str, float | None]:
    """('skip', None) when the trade was already over before t0 + k; ('fail', None) when not confirmed; ('ok', repriced pnl) when confirmed."""
    entry, qty = float(trade["entry_price"]), float(trade["quantity"])
    t0, t_exit = seconds_of(trade.get("entry_time")), seconds_of(trade.get("exit_time"))
    exit_px = float(trade.get("exit_price") or 0)
    if t0 is None or entry <= 0 or qty <= 0 or exit_px <= 0:
        return "skip", None
    t_check = t0 + k * 60
    if t_exit is not None and t_exit <= t_check and str(trade.get("exit_time"))[:10] == str(trade.get("entry_time"))[:10]:
        return "skip", None                                    # stopped / closed before the check: it would not have been taken
    upto = [x for x in ticks if x[0] <= t_check]
    after = [x for x in ticks if x[0] >= t_check]
    if not upto or not after:
        return "skip", None
    if upto[-1][1] < entry * (1 + g):
        return "fail", None
    return "ok", (exit_px - after[0][2]) * qty - cost


def main() -> int:
    sys.path.insert(0, str(ROOT))
    import shadow_scoreboard as sb

    trades = sb.load_trades(upto=date.today().isoformat())
    cost = st.mean(float(t.get("gross_pnl") or 0) - float(t["net_pnl"]) for t in trades if t.get("gross_pnl") not in (None, ""))
    pnl = lambda t: float(t["net_pnl"])                              # noqa: E731
    sp = lambda t: sb._f(t.get("spread_percent"))                    # noqa: E731
    print(f"{len(trades)} closed trades since {trades[0]['_day']}; all: {summary([pnl(t) for t in trades])}\n")

    print("A. SPREAD CAP (spread at entry, % of price) - all trades with a recorded spread")
    known = [t for t in trades if sp(t) is not None]
    print(f"   spread known on {len(known)} trades; median {st.median(sp(t) for t in known):.1f}%, 25% of trades are above {sorted(sp(t) for t in known)[int(.75 * len(known))]:.1f}%")
    days = sorted({t["_day"] for t in known})
    first, second = set(days[: len(days) // 2]), set(days[len(days) // 2:])
    for x in SPREADS:
        kept = [t for t in known if sp(t) <= x]
        gone = [t for t in known if sp(t) > x]
        k1, k2 = [pnl(t) for t in kept if t["_day"] in first], [pnl(t) for t in kept if t["_day"] in second]
        print(f"   spread <= {x:3.1f}%  kept {summary([pnl(t) for t in kept])} | removed n={len(gone):3d} net={sum(pnl(t) for t in gone):9,.0f}"
              f" | first half {sum(k1):8,.0f} (n={len(k1)}), second half {sum(k2):8,.0f} (n={len(k2)})")

    print("\nB. MOMENTUM CONFIRMATION (recorded ticks; confirmed trades are re-priced at the ask after the wait)")
    have = {i: tk for i, t in enumerate(trades) if (tk := load_ticks(str(t.get("option_security_id")), t["_day"], ROOT))}
    base = [pnl(trades[i]) for i in have]
    print(f"   tick data for {len(have)} trades; all of them: {summary(base)}")
    results: dict[tuple[int, float], dict[int, tuple[str, float | None]]] = {}
    for k, g in CHECKS:
        res = {i: confirm(trades[i], tk, k, g, cost) for i, tk in have.items()}
        results[(k, g)] = res
        ok = [(i, v) for i, (s, v) in res.items() if s == "ok"]
        fail = [i for i, (s, v) in res.items() if s == "fail"]
        skip = [i for i, (s, v) in res.items() if s == "skip"]
        print(f"   wait {k:2d}m, price >= entry+{int(g * 100)}%:  taken {summary([v for _, v in ok])}")
        print(f"        real result of the same trades (no re-pricing): net={sum(pnl(trades[i]) for i, _ in ok):9,.0f} | not confirmed n={len(fail):3d} real net={sum(pnl(trades[i]) for i in fail):9,.0f}"
              f" | already over before the check n={len(skip):3d} real net={sum(pnl(trades[i]) for i in skip):9,.0f}")

    print("\nC. SPREAD <= 1% AND MOMENTUM (wait 5m, price >= entry)")
    res = results[(5, 0.0)]
    both = [(i, v) for i, (s, v) in res.items() if s == "ok" and (sp(trades[i]) is not None and sp(trades[i]) <= 1.0)]
    print(f"   taken {summary([v for _, v in both])}   | real result of the same trades: net={sum(pnl(trades[i]) for i, _ in both):,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
