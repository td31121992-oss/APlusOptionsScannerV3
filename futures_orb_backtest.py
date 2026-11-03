"""Opening-range breakout on "stocks in play", tested as STOCK FUTURES with realistic costs. READ-ONLY research - touches no scanner, signal or trade.

    python futures_orb_backtest.py        -> E:\\APlusData\\top_movers_study\\orb_futures\\  (grid.csv, summary.json, index.html)

The rule (Zarattini, Barbon, Aziz 2024, adapted): at 09:15 + OR minutes, rank the stocks by the volume of the opening window over the average of the same window on the previous 14 sessions
("relative volume", "stocks in play"); take the top N that are at or above the minimum; go long if the opening window closed up, short if it closed down, at the open of the next 5-minute bar;
protective stop at STOP x the stock's 14-day average true range; flat at 15:15. Equal notional per position.

Prices are the cash stock's 5-minute candles (stock futures trade within a hair of them intraday; the basis is ignored). Stops use the candle low / high: a candle whose OPEN is already beyond
the stop fills at that open (gap through), otherwise at the stop price; a candle that touches the stop on the entry candle itself counts as stopped (pessimistic).

Costs: Indian stock-futures statutory charges + brokerage for a Rs 10 lakh position (about 3 basis points round trip) PLUS slippage per side (scenarios 0 / 1 / 2 / 4 bp; stop exits pay double).
A basis point = 0.01% of the position value. Results are before tax on profits and before margin interest.

Honesty rules: the main specification (5-minute opening range, top 20, relative volume >= 1.0, stop 10% of ATR) is fixed BEFORE looking at results; the other 71 grid cells are shown with a
multiple-testing warning and are not presented as findings unless they hold in both halves and clear a high t-statistic.
"""

from __future__ import annotations

import json
import time
import warnings
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import top_movers_study as tm

OUT = tm.OUT
RES = OUT / "orb_futures"
NB = tm.NB
EXIT_BAR = 71                         # close of the 15:10-15:15 bar = 15:15
SPLIT = 20240101
OR_BARS = {5: 1, 15: 3, 30: 6}        # opening-range minutes -> number of 5-minute bars
TOP_N = (5, 10, 20)
RVOL_MIN = (1.0, 2.0)
STOPS = (0.05, 0.10, 0.25, None)
SLIP_BP = (0.0, 1.0, 2.0, 4.0)
MAIN = {"or": 5, "n": 20, "rvol": 1.0, "stop": 0.10}
NOTIONAL = 1_000_000.0


def futures_costs_bp(notional: float = NOTIONAL) -> float:
    """Round-trip statutory + brokerage cost of one futures position, in basis points of the notional (STT 0.02% on the sell side, exchange 0.00183% each way, SEBI 0.0001% each way, stamp 0.002%
    on the buy side, brokerage Rs 20 per order, GST 18% on brokerage + exchange + SEBI)."""
    brokerage = 20.0 * 2
    exchange = notional * 2 * 0.0000183
    sebi = notional * 2 * 0.000001
    stt = notional * 0.0002
    stamp = notional * 0.00002
    gst = (brokerage + exchange + sebi) * 0.18
    return (brokerage + exchange + sebi + stt + stamp + gst) / notional * 1e4


def load() -> dict[str, Any]:
    cube = np.load(OUT / "cube.npy", mmap_mode="r")
    syms = pd.read_csv(OUT / "cube_symbols.csv", header=None)[0].tolist()
    days = np.load(OUT / "cube_days.npy")
    o, h, l, c, v = (np.asarray(cube[..., i]) for i in range(5))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        day_c = np.full(c.shape[:2], np.nan, dtype="float32")
        for k in range(NB - 1, -1, -1):                       # last valid close of each day
            x = c[:, :, k]
            day_c = np.where(np.isnan(day_c), x, day_c)
        day_h, day_l = np.nanmax(h, axis=2), np.nanmin(l, axis=2)
        nbars = (~np.isnan(c)).sum(axis=2)
    prev = np.full_like(day_c, np.nan)
    prev[:, 1:] = day_c[:, :-1]
    tr = np.nanmax(np.stack([day_h - day_l, np.abs(day_h - prev), np.abs(day_l - prev)]), axis=0)
    atr = np.full_like(tr, np.nan)
    for d in range(14, tr.shape[1]):
        atr[:, d] = np.nanmean(tr[:, d - 14:d], axis=1)
    open_first = np.where(np.isnan(o[:, :, 0]), o[:, :, 1], o[:, :, 0])
    valid = (nbars >= 70) & np.isfinite(prev) & (np.abs(open_first / prev - 1) <= 0.20) & (np.abs(day_c / prev - 1) <= 0.25) & (prev > 5) & np.isfinite(atr)
    return {"o": o, "h": h, "l": l, "c": c, "v": v, "syms": syms, "days": days, "prev": prev, "atr": atr, "valid": valid}


def opening(data: dict[str, Any], or_min: int) -> dict[str, np.ndarray]:
    """Direction of the opening window, its relative volume and the entry price."""
    n = OR_BARS[or_min]
    o, c, v = data["o"], data["c"], data["v"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        win_v = np.nansum(v[:, :, :n], axis=2)
        win_v = np.where((~np.isnan(v[:, :, :n])).all(axis=2), win_v, np.nan)
        base = np.full_like(win_v, np.nan)
        for d in range(14, win_v.shape[1]):
            base[:, d] = np.nanmean(win_v[:, d - 14:d], axis=1)
    rvol = win_v / base
    direction = np.sign(c[:, :, n - 1] - o[:, :, 0])
    return {"n": n, "rvol": rvol, "dir": direction, "entry": o[:, :, n]}


def run_trades(data: dict[str, Any], op: dict[str, np.ndarray], stop_k: float | None) -> dict[str, np.ndarray]:
    """Gross exit price, whether stopped, for every stock-day (before any selection)."""
    n = op["n"]
    entry, d = op["entry"], op["dir"]
    h, l, o, c = data["h"][:, :, n:EXIT_BAR + 1], data["l"][:, :, n:EXIT_BAR + 1], data["o"][:, :, n:EXIT_BAR + 1], data["c"]
    exit_px = c[:, :, EXIT_BAR].copy()
    stopped = np.zeros(entry.shape, dtype=bool)
    if stop_k is None:
        return {"exit": exit_px, "stopped": stopped, "stop_px": np.full(entry.shape, np.nan, dtype="float32")}
    dist = stop_k * data["atr"]
    stop_px = entry - d * dist
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        long_hit = (l <= stop_px[:, :, None]) & (d[:, :, None] > 0)
        short_hit = (h >= stop_px[:, :, None]) & (d[:, :, None] < 0)
        hit = long_hit | short_hit
    anyhit = hit.any(axis=2)
    first = hit.argmax(axis=2)
    bar_open = np.take_along_axis(o, first[:, :, None], axis=2)[:, :, 0]
    gap_through = np.where(d > 0, bar_open <= stop_px, bar_open >= stop_px)
    fill = np.where(gap_through & (first > 0), bar_open, stop_px)                  # the entry bar itself (first == 0) opens at the entry price, so it fills at the stop
    exit_px = np.where(anyhit, fill, exit_px)
    return {"exit": exit_px, "stopped": anyhit, "stop_px": stop_px}


def trade_returns(entry: np.ndarray, exit_px: np.ndarray, direction: np.ndarray, stopped: np.ndarray, slip_bp: float, cost_bp: float) -> np.ndarray:
    """Net return of each trade in % of the position value (slippage on entry and exit, doubled on a stop; statutory + brokerage costs)."""
    s_in = slip_bp / 1e4
    s_out = np.where(stopped, 2 * slip_bp, slip_bp) / 1e4
    e = entry * (1 + direction * s_in)                                           # a buyer pays up, a seller receives less
    x = exit_px * (1 - direction * s_out)
    return (direction * (x / e - 1)) * 100.0 - cost_bp / 100.0


def daily_stats(day_ret: pd.Series, days: np.ndarray) -> dict[str, float]:
    if len(day_ret) < 30:
        return {}
    mean, sd = float(day_ret.mean()), float(day_ret.std(ddof=1))
    eq = (1 + day_ret / 100.0).cumprod()
    dd = (eq / eq.cummax() - 1).min() * 100
    return {"days": int(len(day_ret)), "avg_day_%": mean, "t_stat": mean / (sd / np.sqrt(len(day_ret))) if sd > 0 else 0.0, "sharpe": mean / sd * np.sqrt(250) if sd > 0 else 0.0,
            "total_%": float((eq.iloc[-1] - 1) * 100), "max_dd_%": float(dd)}


def evaluate(data: dict[str, Any], op: dict[str, np.ndarray], tr: dict[str, np.ndarray], cfg: dict[str, Any], slip: float, cost_bp: float, extra: np.ndarray | None = None) -> dict[str, Any]:
    ok = data["valid"] if extra is None else (data["valid"] & extra)
    ok = ok & np.isfinite(op["rvol"]) & (op["dir"] != 0) & np.isfinite(tr["exit"]) & np.isfinite(op["entry"]) & (op["rvol"] >= cfg["rvol"])
    rk = np.where(ok, op["rvol"], -np.inf)
    order = (-rk).argsort(axis=0).argsort(axis=0)
    sel = ok & (order < cfg["n"])
    net = trade_returns(op["entry"], tr["exit"], op["dir"], tr["stopped"], slip, cost_bp)
    gross = trade_returns(op["entry"], tr["exit"], op["dir"], tr["stopped"], 0.0, 0.0)
    days = data["days"]
    per_day = pd.Series(np.where(sel, net, 0.0).sum(axis=0) / cfg["n"], index=days)       # capital split over N slots; an unused slot earns nothing
    half1 = days < SPLIT
    t = net[sel]
    return {"trades": int(sel.sum()), "trades_per_day": float(sel.sum() / max(1, (sel.any(axis=0)).sum())), "win_%": float((t > 0).mean() * 100), "avg_net_%": float(t.mean()), "avg_gross_%": float(gross[sel].mean()),
            "stopped_%": float(tr["stopped"][sel].mean() * 100), "long_%": float((op["dir"][sel] > 0).mean() * 100),
            "all": daily_stats(per_day[sel.any(axis=0)], days), "h1": daily_stats(per_day[half1 & sel.any(axis=0)], days[half1]), "h2": daily_stats(per_day[~half1 & sel.any(axis=0)], days[~half1]),
            "avg_net_h1_%": float(net[sel & half1[None, :]].mean()), "avg_net_h2_%": float(net[sel & ~half1[None, :]].mean()), "series": per_day}


def main() -> int:
    t0 = time.time()
    RES.mkdir(parents=True, exist_ok=True)
    cost_bp = futures_costs_bp()
    data = load()
    print(f"loaded {len(data['syms'])} stocks x {len(data['days'])} days ({time.time() - t0:.0f}s); statutory + brokerage cost {cost_bp:.2f} bp round trip")
    rows, series = [], {}
    ops = {m: opening(data, m) for m in OR_BARS}
    for stop_k in STOPS:
        for m, op in ops.items():
            tr = run_trades(data, op, stop_k)
            for n, rv in product(TOP_N, RVOL_MIN):
                for slip in SLIP_BP:
                    cfg = {"or": m, "n": n, "rvol": rv, "stop": stop_k}
                    r = evaluate(data, op, tr, cfg, slip, cost_bp)
                    key = (m, n, rv, stop_k, slip)
                    if (m, n, rv, stop_k) == (MAIN["or"], MAIN["n"], MAIN["rvol"], MAIN["stop"]):
                        series[slip] = r.pop("series")
                    else:
                        r.pop("series")
                    rows.append({"or_min": m, "top_n": n, "rvol_min": rv, "stop_atr": "none" if stop_k is None else stop_k, "slip_bp": slip, "trades": r["trades"], "win_%": r["win_%"],
                                 "avg_gross_%": r["avg_gross_%"], "avg_net_%": r["avg_net_%"], "avg_net_h1_%": r["avg_net_h1_%"], "avg_net_h2_%": r["avg_net_h2_%"], "stopped_%": r["stopped_%"],
                                 "t_stat": r["all"].get("t_stat", np.nan), "sharpe": r["all"].get("sharpe", np.nan), "total_%": r["all"].get("total_%", np.nan), "max_dd_%": r["all"].get("max_dd_%", np.nan),
                                 "h1_t": r["h1"].get("t_stat", np.nan), "h2_t": r["h2"].get("t_stat", np.nan)})
        print(f"stop {stop_k} done ({time.time() - t0:.0f}s)")
    grid = pd.DataFrame(rows)
    grid.to_csv(RES / "grid.csv", index=False)
    pd.DataFrame({f"net_day_%_slip{int(s)}bp": v for s, v in series.items()}).to_csv(RES / "main_daily_returns.csv")
    main_rows = grid[(grid.or_min == MAIN["or"]) & (grid.top_n == MAIN["n"]) & (grid.rvol_min == MAIN["rvol"]) & (grid.stop_atr == MAIN["stop"])]
    summary = {"cost_bp": cost_bp, "main": main_rows.round(4).to_dict("records"), "grid_cells": int(len(grid) // len(SLIP_BP))}
    (RES / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(main_rows.round(3).to_string(index=False))
    print(f"wrote {RES} ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
