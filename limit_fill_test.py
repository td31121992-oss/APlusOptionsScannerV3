"""Would a limit order near the mid price have filled - and was it worth it? (RESEARCH ONLY - touches no trade). python limit_fill_test.py

For every paper trade whose option contract was recorded tick by tick (data/option_ticks, 26 Oct on) this replays two things on the real order-book path:

  ENTRY   instead of paying the ask at the signal, rest a BUY limit at  bid + share x (ask - bid)  (share 0 = at the bid, 0.5 = the mid, 0.75 = inside the spread towards the ask) for T seconds.
          It fills when the best ask comes down to the limit, or when trades have printed at or below the limit for at least our whole quantity (our order is above the bid, so it is first in the
          queue at that price: a seller hitting the bid trades with us first). If it does not fill in time: SKIP the trade, or CHASE (buy at the ask when the time is up).
  EXIT    instead of selling at the bid, rest a SELL limit at  ask - share x (ask - bid)  for T seconds; it fills when the bid rises to the limit or trades print at or above it for our quantity;
          if not, sell at the bid when the time is up. Stop-loss exits are shown apart from the others (a stop that waits risks a worse price).
Limits: a snapshot every ~3 seconds, no queue position beyond the rule above, no partial fills, and the replayed exit price of the real trade is used after an entry (a different entry price would
move the stops slightly). Two to three days of ticks is a small sample - this measures fill behaviour, it does not prove profitability.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import ladder_tick_replay as lr

SHARES = (0.0, 0.5, 0.75)
WAITS = (10, 30, 60, 120, 300)


def secs(hms: str) -> float:
    h, m, s = str(hms).split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def prep(df: pd.DataFrame) -> dict[str, np.ndarray] | None:
    d = df.copy()
    for c in ("ltp", "vol", "bid", "ask"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["ltp", "vol"])
    if d.empty:
        return None
    d["t"] = d.ts.astype(str).map(secs)
    d = d.sort_values("t")
    return {k: d[k].to_numpy(dtype=float) for k in ("t", "ltp", "vol", "bid", "ask")}


def quote_at(a: dict[str, np.ndarray], t0: float) -> tuple[float, float] | None:
    i = int(np.searchsorted(a["t"], t0, side="right")) - 1
    i = max(i, 0)
    for j in range(i, min(i + 5, len(a["t"]))):                   # the last quote at or just after the signal with a real bid and ask
        b, k = a["bid"][j], a["ask"][j]
        if b > 0 and k >= b:
            return b, k
    return None


def try_buy(a: dict[str, np.ndarray], t0: float, limit: float, qty: float, wait: float) -> tuple[bool, float, float]:
    """(filled, price, seconds). Fills at the ask when the ask comes down to the limit, or at the limit when enough volume traded at or below it."""
    i0 = int(np.searchsorted(a["t"], t0, side="left"))
    got = 0.0
    prev_vol = a["vol"][max(i0 - 1, 0)]
    for i in range(i0, len(a["t"])):
        if a["t"][i] - t0 > wait:
            break
        if a["ask"][i] > 0 and a["ask"][i] <= limit:
            return True, float(a["ask"][i]), float(a["t"][i] - t0)
        dv = max(0.0, a["vol"][i] - prev_vol)
        prev_vol = a["vol"][i]
        if dv > 0 and a["ltp"][i] <= limit + 1e-9:
            got += dv
            if got >= qty:
                return True, float(limit), float(a["t"][i] - t0)
    return False, float("nan"), float("nan")


def try_sell(a: dict[str, np.ndarray], t0: float, limit: float, qty: float, wait: float) -> tuple[bool, float, float]:
    i0 = int(np.searchsorted(a["t"], t0, side="left"))
    got = 0.0
    prev_vol = a["vol"][max(i0 - 1, 0)]
    for i in range(i0, len(a["t"])):
        if a["t"][i] - t0 > wait:
            break
        if a["bid"][i] > 0 and a["bid"][i] >= limit:
            return True, float(a["bid"][i]), float(a["t"][i] - t0)
        dv = max(0.0, a["vol"][i] - prev_vol)
        prev_vol = a["vol"][i]
        if dv > 0 and a["ltp"][i] >= limit - 1e-9:
            got += dv
            if got >= qty:
                return True, float(limit), float(a["t"][i] - t0)
    return False, float("nan"), float("nan")


def price_at(a: dict[str, np.ndarray], t: float, side: str) -> float | None:
    """Ask (to buy) or bid (to sell) at time t."""
    q = quote_at(a, t)
    return None if q is None else (q[1] if side == "ask" else q[0])


def main() -> dict:
    rows_e, rows_x = [], []
    for t in lr.load_trades():
        df = lr.ticks(t)
        if df is None:
            continue
        a = prep(df)
        if a is None:
            continue
        entry, qty = float(t["entry_price"]), float(t["quantity"])
        closed = str(t.get("status")).upper() == "CLOSED"
        real_exit = float(t["exit_price"]) if closed else float(t.get("last_option_price") or entry)
        t0 = secs(str(t["entry_time"])[11:19])
        q = quote_at(a, t0)
        if q is None:
            continue
        bid, ask = q
        for share in SHARES:
            limit = round(bid + share * (ask - bid), 2)
            for w in WAITS:
                ok, px, sec = try_buy(a, t0, limit, qty, w)
                chase = price_at(a, t0 + w, "ask")
                rows_e.append({"trade": t["paper_trade_id"], "symbol": t["symbol"], "share": share, "wait": w, "spread_pct": (ask - bid) / ask * 100, "paper_entry": entry, "ask0": ask, "bid0": bid, "limit": limit,
                               "filled": ok, "fill": px, "sec": sec, "chase_ask": chase, "qty": qty, "real_exit": real_exit})
        if closed and t.get("exit_time"):
            t1 = secs(str(t["exit_time"])[11:19])
            q2 = quote_at(a, t1)
            if q2 is not None:
                b2, a2 = q2
                stop = "STOP" in str(t.get("exit_reason"))
                for share in SHARES[1:]:
                    limit = round(a2 - share * (a2 - b2), 2)
                    for w in WAITS[:4]:
                        ok, px, sec = try_sell(a, t1, limit, qty, w)
                        later = price_at(a, t1 + w, "bid")
                        rows_x.append({"trade": t["paper_trade_id"], "stop_exit": stop, "share": share, "wait": w, "paper_exit": float(t["exit_price"]), "bid1": b2, "ask1": a2, "limit": limit,
                                       "filled": ok, "fill": px, "later_bid": later, "qty": qty, "entry": entry})
    e, x = pd.DataFrame(rows_e), pd.DataFrame(rows_x)
    e.to_csv(r"E:\APlusData\top_movers_study\limit_fill_entries.csv", index=False)
    x.to_csv(r"E:\APlusData\top_movers_study\limit_fill_exits.csv", index=False)
    n = e.trade.nunique()
    print(f"{n} trades with ticks; median spread at entry {e.spread_pct.median():.2f}% of the ask; paper entry vs the ask at the signal: avg {((e.paper_entry / e.ask0 - 1) * 100).mean():+.2f}%")
    out = []
    for (share, w), g in e.groupby(["share", "wait"]):
        f = g[g.filled]
        m = g[~g.filled]
        base = ((g.real_exit - g.paper_entry) * g.qty).sum()
        skip = ((f.real_exit - f.fill) * f.qty).sum()
        chase_px = np.where(g.filled, g.fill, g.chase_ask.fillna(g.ask0))
        chase = ((g.real_exit - chase_px) * g.qty).sum()
        out.append({"limit": {0.0: "at the bid", 0.5: "at the mid", 0.75: "75% to the ask"}[share], "wait_s": w, "fill_rate_%": len(f) / len(g) * 100,
                    "saving_vs_paper_%": ((f.paper_entry - f.fill) / f.paper_entry * 100).mean() if len(f) else np.nan,
                    "filled_avg_pnl_rs": ((f.real_exit - f.fill) * f.qty).mean() if len(f) else np.nan, "missed_avg_pnl_rs": ((m.real_exit - m.paper_entry) * m.qty).mean() if len(m) else np.nan,
                    "total_market_rs": base, "total_limit_skip_rs": skip, "total_limit_chase_rs": chase})
    res = pd.DataFrame(out)
    print("\nENTRY: a buy limit instead of paying the ask")
    print(res.round(1).to_string(index=False))
    ex = []
    if len(x):
        for (share, w, stop), g in x.groupby(["share", "wait", "stop_exit"]):
            f = g[g.filled]
            end = np.where(g.filled, g.fill, g.later_bid.fillna(g.bid1))
            gain = ((end - g.paper_exit) * g.qty)
            ex.append({"exit": "stop-loss exits" if stop else "other exits", "limit": "at the mid" if share == 0.5 else "75% to the bid", "wait_s": w, "n": len(g), "fill_rate_%": len(f) / len(g) * 100,
                       "avg_vs_paper_rs": gain.mean(), "total_vs_paper_rs": gain.sum()})
        print("\nEXIT: a sell limit instead of selling at the bid (change in rupees against the journal's own exit price; chasing the bid when time is up)")
        print(pd.DataFrame(ex).round(1).to_string(index=False))
    return {"entries": res, "exits": pd.DataFrame(ex)}


if __name__ == "__main__":
    main()
