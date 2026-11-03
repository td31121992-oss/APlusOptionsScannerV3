"""Baseline replay: today's exit rules on 5-minute option history (RESEARCH ONLY: reads stored data, changes nothing).

Why: every rule question so far was answered on 15 paper sessions (about 170 trades). The stored option history (E:\\APlusData\\expired_options: 5-minute bars of the near-month option at strikes
-3..+3 of the money, with the spot price, 1 Jun - 6 Oct 2026, 89 sessions, 213 stocks) is about 30 times bigger, but it has no stock volume or VWAP, so the scanner's own entry gates (VWAP, relative
volume, ATR, pivots) CANNOT be replayed on it. What can be replayed is what happens AFTER an entry, and a few simple entry rules that need only the spot price. So:

    ENGINE       one trade on the bars of ONE fixed strike: initial stop -20 %; the live exit ladder (paper_trade_journal.user_ladder_floor: +5 % -> stop -15 %, +10 % -> +3 %, +20 % -> +13 %,
                 +30 % -> +22 %, then +2 points per further +5 %); anything left is sold at the last bar. Fills: entry at the NEXT bar's open + 1 %, a stop fills at the stop (or the open when it gaps through)
                 - 1 %, a flat Rs 250 per trade for charges (about the paper journal's Rs 175 - 310). A bar that touches the stop is a stop-out even if it also made a new high (conservative).
    VALIDATION   the engine is run on the real paper trades (their own entry price and time, option candles from Dhan) and compared with what they actually made.
    PROXIES      NOT the scanner. Simple spot-only entries over all 89 sessions, each first trigger per stock and day: BREAKOUT (spot >= 1.0 % from the open and at a new day extreme),
                 PAUSE (>= 1.0 % from the open, the extreme set 10 - 45 minutes ago, under 0.3 % moved in the last 30 minutes), OB_RETEST (an order-block retest on the spot series: an impulse of
                 >= 1.2 % off a local low, then price returns into the block's zone, holds it, and ticks back up), and a CONTROL (10:00 in the direction of the open, move >= 0.3 %).

    python baseline_replay.py cache        build the compact per-stock cache (about 20 minutes; resumable)
    python baseline_replay.py validate     engine against the paper trades
    python baseline_replay.py proxies      the three proxy entries over 89 sessions with the live exit ladder
"""

from __future__ import annotations

import json
import os
import statistics as st
import sys
import time
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parent
CACHE = Path(os.getenv("APLUS_BT_CACHE", r"E:\APlusData\backtest_cache" if Path("E:/").exists() else str(ROOT / "data" / "backtest_cache")))      # E: has the room; C: ran full on 26 Oct
START, END = "2026-06-01", "2026-10-07"
INIT_STOP = 0.20
ENTRY_SLIP, EXIT_SLIP = 0.01, 0.01
COST_RS, STAKE_RS = 250.0, 20000.0
OPEN_MIN, CLOSE_MIN = 9 * 60 + 15, 15 * 60 + 25


def _ladder(entry: float, high: float) -> float:
    from paper_trade_journal import user_ladder_floor
    return user_ladder_floor(entry, high)


# ---------------------------------------------------------------- engine ---------------------------------------------------------------------
def simulate(minutes: Sequence[int], o: Sequence[float], h: Sequence[float], low: Sequence[float], c: Sequence[float], i_signal: int, ladder=None, init_stop: float = INIT_STOP) -> dict[str, Any] | None:
    """Trade one strike. The signal is seen at the close of bar i_signal; the fill is the OPEN of bar i_signal + 1 (+ slippage). Returns None when there is no bar to enter on."""
    ladder = ladder or _ladder
    j0 = i_signal + 1
    if j0 >= len(o) or o[j0] <= 0:
        return None
    entry = o[j0] * (1 + ENTRY_SLIP)
    high = entry
    why, exit_px, k_exit = "SESSION_END", c[-1] * (1 - EXIT_SLIP), len(o) - 1
    for k in range(j0, len(o)):
        if minutes[k] > CLOSE_MIN:
            why, exit_px, k_exit = "SESSION_END", (c[k - 1] if k > j0 else c[k]) * (1 - EXIT_SLIP), max(k - 1, j0)
            break
        stop = max(entry * (1 - init_stop), ladder(entry, high))
        if low[k] <= stop:
            px = min(o[k], stop) if k > j0 else stop          # gap through the stop fills at the open
            why = "STOP" if stop <= entry * (1 - init_stop) + 1e-9 else "LOCK"
            exit_px, k_exit = px * (1 - EXIT_SLIP), k
            break
        high = max(high, h[k])
        if k == len(o) - 1:
            exit_px, k_exit = c[k] * (1 - EXIT_SLIP), k
    gross_pct = (exit_px / entry - 1) * 100
    net_rs = STAKE_RS * (exit_px / entry - 1) - COST_RS
    return {"entry": entry, "exit": exit_px, "why": why, "gross_pct": gross_pct, "net_rs": net_rs, "peak_pct": (high / entry - 1) * 100, "bars": k_exit - j0 + 1, "peak_t": None}


# ---------------------------------------------------------------- cache ----------------------------------------------------------------------
def _load_symbol(sym: str) -> None:
    import options_history as oh
    import pandas as pd
    out = CACHE / f"{sym}.pkl"
    if out.exists():
        return
    parts = []
    for side in ("CALL", "PUT"):
        for off in range(-3, 4):
            try:
                df = oh.load_series(sym, side, offset=off, start=START, end=END)
            except Exception:                                      # noqa: BLE001
                continue
            if df is None or df.empty:
                continue
            df = df[~df.index.duplicated()].sort_index()
            parts.append(pd.DataFrame({"side": side, "off": off, "day": df.index.strftime("%Y-%m-%d"), "minute": df.index.hour * 60 + df.index.minute,
                                       "strike": df.strike.astype("float32"), "o": df.open.astype("float32"), "h": df.high.astype("float32"), "l": df.low.astype("float32"),
                                       "c": df.close.astype("float32"), "spot": df.spot.astype("float32")}))
    if parts:
        CACHE.mkdir(parents=True, exist_ok=True)
        pd.concat(parts, ignore_index=True).to_pickle(out)


def build_cache() -> None:
    from options_history import DEFAULT_ROOT
    syms = sorted(d.name for d in Path(DEFAULT_ROOT).iterdir() if d.is_dir())
    CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with Pool(7) as pool:
        for n, _ in enumerate(pool.imap_unordered(_load_symbol, syms), 1):
            if n % 10 == 0:
                print("cached", n, "of", len(syms), round(time.time() - t0), "s", flush=True)
    print("done", len(list(CACHE.glob('*.pkl'))), "stocks", flush=True)


def _strike_arrays(df, side: str, day: str, strike: float):
    g = df[(df.side == side) & (df.day == day) & (df.strike == strike)].sort_values("minute")
    return g.minute.values, g.o.values.astype(float), g.h.values.astype(float), g.l.values.astype(float), g.c.values.astype(float)


# ---------------------------------------------------------------- proxy entries ---------------------------------------------------------------
def _day_spot(df, day: str):
    g = df[(df.day == day) & (df.side == "CALL") & (df.off == 0)].sort_values("minute")
    return g.minute.values, g.spot.values.astype(float), g.strike.values.astype(float)


def triggers(minutes: np.ndarray, spot: np.ndarray, prev: tuple[float, float] | None = None) -> dict[str, tuple[int, int]]:
    """First trigger of each proxy for one stock-day: name -> (bar index of the signal, direction +1 call / -1 put). `prev` = (previous day's highest, lowest spot reading) for the LEVEL proxies."""
    out: dict[str, tuple[int, int]] = {}
    if len(spot) < 20:
        return out
    if prev is not None:                                   # LEVEL_LONG / LEVEL_SHORT: the spot crosses the previous day's high / low or the 15-minute opening-range high / low (readings, not candle highs)
        orh, orl = float(spot[:3].max()), float(spot[:3].min())
        for i in range(3, len(spot) - 2):
            if minutes[i] < 9 * 60 + 30 or minutes[i] > 14 * 60 + 40:
                continue
            if "LEVEL_LONG" not in out and any(spot[i - 1] <= lvl < spot[i] for lvl in (prev[0], orh)):
                out["LEVEL_LONG"] = (i, 1)
            if "LEVEL_SHORT" not in out and any(spot[i - 1] >= lvl > spot[i] for lvl in (prev[1], orl)):
                out["LEVEL_SHORT"] = (i, -1)
    o = spot[0]
    for i in range(3, len(spot) - 2):
        if minutes[i] < 9 * 60 + 30 or minutes[i] > 14 * 60 + 45:
            continue
        move = (spot[i] / o - 1) * 100
        for sg in (1, -1):
            sm = sg * move
            ext_i = int(np.argmax(sg * spot[: i + 1]))
            at_ext = ext_i == i
            if "BREAKOUT" not in out and sm >= 1.0 and at_ext:
                out["BREAKOUT"] = (i, sg)
            if "PAUSE" not in out and sm >= 1.0 and 10 <= (i - ext_i) * 5 <= 45:
                j = max(0, i - 6)
                if abs(spot[i] / spot[j] - 1) * 100 < 0.3:
                    out["PAUSE"] = (i, sg)
        if "CONTROL" not in out and minutes[i] >= 10 * 60 and abs(move) >= 0.3:
            out["CONTROL"] = (i, 1 if move > 0 else -1)
        if "OB_RETEST" not in out:
            for sg in (1, -1):
                if _ob_retest(spot, i, sg):
                    out["OB_RETEST"] = (i, sg)
                    break
    return out


OB_IMPULSE_PCT, OB_LOOKBACK = 1.2, 24


def _ob_retest(spot: np.ndarray, i: int, sg: int) -> bool:
    """Order-block retest on the spot series (5-minute readings, no candle bodies). Bullish: a local low (+/- 3 readings) followed within 8 readings by a rise of >= 1.2 % marks the block, its zone
    being from that low to the next reading; afterwards price comes back into the zone (within 0.2 % of its top), never goes through its bottom (0.2 % tolerance), and the latest reading ticks up.
    Bearish mirrors it (a local high, a fall of >= 1.2 %, price returns up into the zone, never through its top, the latest reading ticks down)."""
    if i < 8:
        return False
    for j in range(max(3, i - OB_LOOKBACK), i - 4):
        win = spot[j - 3: j + 4]
        if sg > 0 and spot[j] != win.min() or sg < 0 and spot[j] != win.max():
            continue
        hi_k = min(j + 8, i - 2)
        if hi_k <= j + 1:
            continue
        leg = spot[j + 1: hi_k + 1]
        peak_k = j + 1 + int(np.argmax(leg) if sg > 0 else np.argmin(leg))
        gain = (spot[peak_k] / spot[j] - 1) * 100 if sg > 0 else (spot[j] / spot[peak_k] - 1) * 100
        if gain < OB_IMPULSE_PCT:
            continue
        zone_lo, zone_hi = min(spot[j], spot[j + 1]), max(spot[j], spot[j + 1])
        tail = spot[peak_k + 1: i + 1]
        if len(tail) < 2:
            continue
        if sg > 0:
            if tail[:-1].min() <= zone_hi * 1.002 and tail.min() >= zone_lo * 0.998 and spot[i] > spot[i - 1]:
                return True
        elif tail[:-1].max() >= zone_lo * 0.998 and tail.max() <= zone_hi * 1.002 and spot[i] < spot[i - 1]:
            return True
    return False

def _proxies_for(sym: str) -> list[dict[str, Any]]:
    import pandas as pd
    df = pd.read_pickle(CACHE / f"{sym}.pkl")
    groups = {k: g.sort_values("minute") for k, g in df.groupby(["side", "day", "strike"])}
    atm = df[df.off == 0]
    atm_strike = {(r.side, r.day, int(r.minute)): float(r.strike) for r in atm.itertuples()}
    spot_by_day = {d: g.sort_values("minute") for d, g in atm[atm.side == "CALL"].groupby("day")}
    rows = []
    ordered = sorted(spot_by_day)
    for di, day in enumerate(ordered):
        g = spot_by_day[day]
        minutes, spot = g.minute.values, g.spot.values.astype(float)
        prev = None
        if di:
            ps = spot_by_day[ordered[di - 1]].spot.values.astype(float)
            prev = (float(ps.max()), float(ps.min()))
        for name, (i, sg) in triggers(minutes, spot, prev).items():
            side = "CALL" if sg > 0 else "PUT"
            strike = atm_strike.get((side, day, int(minutes[i]) + 5))
            if strike is None or (side, day, strike) not in groups:
                continue
            gg = groups[(side, day, strike)]
            m, o, h, lo, c = gg.minute.values, gg.o.values.astype(float), gg.h.values.astype(float), gg.l.values.astype(float), gg.c.values.astype(float)
            k = int(np.searchsorted(m, minutes[i]))
            if k >= len(m) or m[k] != minutes[i]:
                k = int(np.searchsorted(m, minutes[i], side="right")) - 1
            if k < 0:
                continue
            res = simulate(m, o, h, lo, c, k)
            if res:
                rows.append({"sym": sym, "day": day, "proxy": name, "side": side, "strike": strike, "t": int(minutes[i]), **res})
    return rows


def run_proxies(ladder=None) -> list[dict[str, Any]]:
    syms = sorted(f.stem for f in CACHE.glob("*.pkl"))
    rows: list[dict[str, Any]] = []
    with Pool(7) as pool:
        for n, part in enumerate(pool.imap_unordered(_proxies_for, syms), 1):
            rows += part
            if n % 20 == 0:
                print("proxies", n, "of", len(syms), flush=True)
    return rows


def report_proxies(rows: Sequence[dict[str, Any]]) -> str:
    lines = ["| entry (proxy) | trades | win % | avg % per trade | net Rs per Rs20k trade | total net Rs | stopped at -20% | exited by a lock | held to the close | peak 100%+ |", "|---|---|---|---|---|---|---|---|---|---|"]
    for name in ("CONTROL", "BREAKOUT", "PAUSE", "OB_RETEST", "LEVEL_LONG", "LEVEL_SHORT"):
        g = [r for r in rows if r["proxy"] == name]
        if not g:
            continue
        n = len(g)
        lines.append(f"| {name} | {n} | {100 * sum(r['net_rs'] > 0 for r in g) / n:.0f} | {st.mean(r['gross_pct'] for r in g):+.1f} | {st.mean(r['net_rs'] for r in g):+.0f} | {sum(r['net_rs'] for r in g):,.0f} | "
                     f"{100 * sum(r['why'] == 'STOP' for r in g) / n:.0f}% | {100 * sum(r['why'] == 'LOCK' for r in g) / n:.0f}% | {100 * sum(r['why'] == 'SESSION_END' for r in g) / n:.0f}% | {100 * sum(r['peak_pct'] >= 100 for r in g) / n:.1f}% |")
    months: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        months[(r["proxy"], r["day"][:7])].append(r["net_rs"])
    lines += ["", "Net Rs per trade by month:", "", "| entry | " + " | ".join(sorted({k[1] for k in months})) + " |", "|---|" + "---|" * len({k[1] for k in months})]
    for name in ("CONTROL", "BREAKOUT", "PAUSE", "OB_RETEST", "LEVEL_LONG", "LEVEL_SHORT"):
        lines.append(f"| {name} | " + " | ".join(f"{st.mean(months[(name, m)]):+.0f} ({len(months[(name, m)])})" if months.get((name, m)) else "-" for m in sorted({k[1] for k in months})) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------- validation on the paper trades --------------------------------------------------
def validate() -> str:
    B = ROOT / "data" / "backtest_cache" / "paper_candles.json"
    cand = json.loads(B.read_text(encoding="utf-8")) if B.exists() else {}
    hist = json.loads((ROOT / "data" / "reports" / "paper_trade_history.json").read_text(encoding="utf-8")).get("paper_trades") or []
    cur = json.loads((ROOT / "data" / "intraday_movement" / "paper_trade_journal.json").read_text(encoding="utf-8"))["trades"]
    trades = {}
    for x in hist + cur:
        if x.get("status") == "CLOSED" and x.get("option_security_id") and str(x.get("entry_time", ""))[:10] >= "2026-10-01":
            trades[(x["symbol"], x["entry_time"][:16])] = x
    pairs = []
    for x in trades.values():
        bars = sorted(cand.get(f"{x['option_security_id']}|{x['entry_time'][:10]}", []), key=lambda b: b["minute"])
        if not bars:
            continue
        em = int(x["entry_time"][11:13]) * 60 + int(x["entry_time"][14:16])
        i = max((k for k, b in enumerate(bars) if b["minute"] + 5 <= em + 5 and b["minute"] <= em), default=-1)
        if i < 0:
            continue
        m = [b["minute"] for b in bars]
        h, lo, c = ([b[k] for b in bars] for k in ("high", "low", "close"))
        o = [c[0]] + c[:-1]                                         # the stored Dhan candles carry no open: the previous close stands in for it
        e = float(x["entry_price"])
        o[i + 1:i + 2] = [e / (1 + ENTRY_SLIP)] if i + 1 < len(o) else []          # fill at the paper trade's own entry price
        res = simulate(m, o, h, lo, c, i)
        if res:
            q = float(x["quantity"])
            actual = (float(x["exit_price"]) / e - 1) * 100
            pairs.append((actual, res["gross_pct"], float(x["net_pnl"]), res["net_rs"] * (e * q) / STAKE_RS, x["exit_reason"], res["why"]))
    a, s = np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs])
    lines = [f"Paper trades replayed: {len(pairs)} of {len(trades)} (the rest had no option candles).",
             f"Actual avg {a.mean():+.1f} % per trade, replay avg {s.mean():+.1f} %; correlation {np.corrcoef(a, s)[0, 1]:.2f}; mean absolute difference {np.abs(a - s).mean():.1f} points; "
             f"same sign (win/loss) on {100 * np.mean(np.sign(a) == np.sign(s)):.0f} % of trades.",
             f"Actual total net Rs {sum(p[2] for p in pairs):,.0f}; replay total (scaled to each trade's own size, Rs 250 charges) Rs {sum(p[3] for p in pairs):,.0f}."]
    return "\n".join(lines)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "cache":
        build_cache()
    elif cmd == "validate":
        print(validate())
    elif cmd == "proxies":
        rows = run_proxies()
        (CACHE / "proxy_rows.json").write_text(json.dumps(rows), encoding="utf-8")
        print(report_proxies(rows))
    else:
        print(__doc__)
