"""Time-stop replay (read-only research; no trading effect).

Question (10 Nov 2026): in options you need momentum, so what if a trade that is not in profit N minutes after entry were closed right there?
Every closed paper trade that has recorded option ticks (data/option_ticks/<day>/<option_security_id>_*.csv.gz, from 26 Oct 2026) is replayed:

    in profit  = at some tick within the first N minutes after entry, the option traded above entry_price * (1 + gain)
    if not in profit by minute N and the trade was still open: sell at the last BID at or before minute N (fall back to the last price), less the average round-trip cost
    otherwise the trade is left exactly as it really ended

Prints, per (N minutes, required gain): trades the rule would have closed, their real result vs the replayed result, how many of them later turned into winners (what the rule
would have cut off), and the change in the total. Upstox has no candles for expired contracts, so the system's own recorded ticks are the price path.

    python time_stop_replay.py
"""

from __future__ import annotations

import csv
import glob
import gzip
import statistics as st
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
WINDOWS = (10, 15, 20, 30, 45)
GAINS = (0.0, 0.02, 0.05)


def load_ticks(security_id: str, day: str, root: Path = ROOT) -> list[tuple[float, float, float]] | None:
    """[(seconds_since_midnight, ltp, bid)] for the option on `day`, in time order; None when nothing was recorded."""
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
                    bid = float(row["bid"]) if row.get("bid") not in (None, "", "nan") else ltp
                    out.append((int(hh) * 3600 + int(mm) * 60 + float(ss), ltp, bid if bid > 0 else ltp))
                except (ValueError, KeyError):
                    continue
    except (EOFError, OSError):                              # a file cut short (recorder stopped mid-write): use the ticks read before the break
        pass
    out.sort(key=lambda r: r[0])
    return out or None


def seconds_of(stamp: Any) -> float | None:
    try:
        t = datetime.fromisoformat(str(stamp))
        return t.hour * 3600 + t.minute * 60 + t.second
    except ValueError:
        return None


def replay(trade: dict[str, Any], ticks: list[tuple[float, float, float]], window: int, gain: float, cost: float) -> dict[str, Any] | None:
    """What the rule would have done to one trade; None when the data cannot say."""
    entry, qty = float(trade["entry_price"]), float(trade["quantity"])
    t0, t_exit = seconds_of(trade.get("entry_time")), seconds_of(trade.get("exit_time"))
    if t0 is None or entry <= 0 or qty <= 0:
        return None
    end = t0 + window * 60
    if t_exit is not None and t_exit <= end and str(trade.get("exit_time"))[:10] == str(trade.get("entry_time"))[:10]:
        return {"affected": False, "ended_early": True}                              # already closed (stop / target) inside the window
    inside = [x for x in ticks if t0 <= x[0] <= end]
    if not inside:
        return None
    if max(x[1] for x in inside) > entry * (1 + gain):
        return {"affected": False, "ended_early": False}                             # showed momentum in time: left alone
    return {"affected": True, "new_pnl": (inside[-1][2] - entry) * qty - cost, "ended_early": False}


def main() -> int:
    sys.path.insert(0, str(ROOT))
    import shadow_scoreboard as sb

    trades = sb.load_trades(upto=date.today().isoformat())
    cost = st.mean(float(t.get("gross_pnl") or 0) - float(t["net_pnl"]) for t in trades if t.get("gross_pnl") not in (None, ""))
    have = {i: tk for i, t in enumerate(trades) if (tk := load_ticks(str(t.get("option_security_id")), t["_day"], ROOT))}
    print(f"{len(trades)} closed trades, tick data for {len(have)} ({100 * len(have) / len(trades):.0f}%); average round-trip cost Rs {cost:.0f}")
    print(f"Trades with data: real net Rs {sum(float(trades[i]['net_pnl']) for i in have):,.0f}\n")
    print("window gain  closed  ended-already   real net of closed -> replayed   later winners cut   change in total")
    for w in WINDOWS:
        for g in GAINS:
            aff = ended = later_win = 0
            real = new = 0.0
            for i, tk in have.items():
                r = replay(trades[i], tk, w, g, cost)
                if not r:
                    continue
                ended += r.get("ended_early", False)
                if r["affected"]:
                    aff += 1
                    real += float(trades[i]["net_pnl"])
                    new += r["new_pnl"]
                    later_win += float(trades[i]["net_pnl"]) > 0
            print(f" {w:3d}m  >{int(g * 100):2d}%  {aff:5d}  {ended:8d}        {real:10,.0f} -> {new:10,.0f}        {later_win:4d}              {new - real:+10,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
