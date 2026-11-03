"""Breakouts and breakdowns board for F&O stocks, intraday (DISPLAY ONLY: it reads the live files the tick recorder writes; nothing here trades).

A stock is listed when it has broken a level in the direction of the move:
    PDH / PDL   the previous day's high (breakout) / low (breakdown)                    data/reports/daily_indicators.json
    OR          the opening range of the first 15 minutes (the first three 5-minute bars)   data/ticks/ml_features_live.json (or_status)
    IB          the initial balance, the first hour's high / low (known after 10:15)         data/ticks/amt_live.json
and is then scored on six checks, each shown as a tick or a cross:
    market      the market is not against the trade (median stock not 0.3 % the wrong way) OR the stock is 1.5 %+ ahead of / behind it (strong enough to go against it)
    decisive    the price is at least 0.15 % beyond the highest PDH / IB level it broke (a close, not a wick, is what the scanner later waits for)
    volume      relative volume (so far today against the usual for this time) of 2x or more
    vwap        on the right side of the exchange VWAP
    strength    at least 1 % ahead of the market (breakouts) / behind it (breakdowns), and not behind its own sector index or sector median
    options     the at-the-money option on the trade's side has a bid-ask spread within 2 %, from the latest option-chain snapshot
The board is a filter to cut the noise, not a signal: our own back-tests (87 days) found no edge in the break pattern by itself.

    data/ticks/rs_all.json     every stock's live numbers, written by the tick recorder (rs_leaders.py) every 5 seconds
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
MARKET_FIGHT_PCT, STRONG_RS = 0.3, 1.5
BREAK_PCT, MIN_RVOL, MIN_RS, MAX_OPT_SPREAD = 0.15, 2.0, 1.0, 2.0
TOP_N = 40
CHECKS = ("market", "decisive", "volume", "vwap", "strength", "options")
_CACHE: dict[str, Any] = {}


def _read(root: Path, rel: tuple[str, ...], day: str | None = None) -> dict[str, Any] | None:
    path = root.joinpath(*rel)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = str(path)
    if _CACHE.get(key, (None, None))[0] != mtime:
        try:
            _CACHE[key] = (mtime, json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None
    d = _CACHE[key][1]
    if day is not None and d.get("day") != day:
        return None
    return d


def evaluate(sym: str, side: int, r: dict[str, Any], market_median: float, amt: dict[str, Any] | None, ml: dict[str, Any] | None, levels: dict[str, float] | None,
             chain: dict[str, Any] | None) -> dict[str, Any] | None:
    """The board row for one stock and side (+1 breakout, -1 breakdown), or None when no level has been broken in that direction."""
    px = float(r.get("ltp") or 0)
    if px <= 0:
        return None
    broke: list[str] = []
    prices: list[float] = []
    pdh, pdl = (levels or {}).get("pdh", 0.0), (levels or {}).get("pdl", 0.0)
    lvl = pdh if side > 0 else pdl
    if lvl > 0 and (px > lvl if side > 0 else px < lvl):
        broke.append("PDH" if side > 0 else "PDL")
        prices.append(lvl)
    if amt and amt.get("ib_done"):
        ib = amt["ib_hi"] if side > 0 else amt["ib_lo"]
        if (px > ib) if side > 0 else (px < ib):
            broke.append("IB")
            prices.append(ib)
    orr = ((ml or {}).get(str(side)) or {}).get("or_status")
    if orr is not None and float(orr) > 0:
        broke.append("OR")
    if not broke:
        return None
    ref = max(prices) if side > 0 and prices else min(prices) if prices else 0.0
    brk = ((px / ref - 1.0) if side > 0 else (ref / px - 1.0)) * 100.0 if ref > 0 else None
    rs = side * float(r.get("rs") or 0)                                             # + = ahead of the market in the trade's direction
    sec = r.get("rsi") if r.get("rsi") is not None else r.get("rss")
    spread = None
    if chain:
        spread = chain.get("ce_spread" if side > 0 else "pe_spread")
    checks = {"market": (side * market_median >= -MARKET_FIGHT_PCT) or rs >= STRONG_RS,
              "decisive": brk is not None and brk >= BREAK_PCT,
              "volume": float(r.get("rv") or 0) >= MIN_RVOL,
              "vwap": side * float(r.get("vw") or 0) > 0,
              "strength": rs >= MIN_RS and (sec is None or side * float(sec) > 0),
              "options": spread is not None and spread <= MAX_OPT_SPREAD}
    return {"s": sym, "sec": r.get("sec", ""), "side": side, "ltp": round(px, 2), "levels": broke, "break_pct": None if brk is None else round(brk, 2), "rvol": round(float(r.get("rv") or 0), 1),
            "vs_vwap": round(float(r.get("vw") or 0), 2), "rs": round(rs, 2), "rs_sector": None if sec is None else round(side * float(sec), 2), "acc2": round(side * float(r.get("a2") or 0), 2),
            "opt_spread": spread, "checks": checks, "score": sum(1 for v in checks.values() if v), "move": round(float(r.get("m") or 0), 2)}


def payload(root: Path = ROOT, today: date | None = None) -> dict[str, Any]:
    day = (today or date.today()).isoformat()
    rs = _read(root, ("data", "ticks", "rs_all.json"), day)
    if not rs:
        return {"ok": False, "error": "no live data yet today (the tick recorder runs 09:05-15:32 and needs about 100 stocks with ticks)"}
    amt = (_read(root, ("data", "ticks", "amt_live.json"), day) or {}).get("stocks", {})
    ml = (_read(root, ("data", "ticks", "ml_features_live.json"), day) or {}).get("stocks", {})
    ind = (_read(root, ("data", "reports", "daily_indicators.json")) or {}).get("symbols", {})
    try:
        import rs_leaders

        chain = rs_leaders.chain_check(root, day)
    except Exception:                                      # noqa: BLE001 - the options check is extra information
        chain = {}
    med = float(rs["market"]["median"])
    rows = {1: [], -1: []}
    for sym, r in rs["stocks"].items():
        lv = {"pdh": float((ind.get(sym) or {}).get("pdh") or 0), "pdl": float((ind.get(sym) or {}).get("pdl") or 0)}
        for side in (1, -1):
            e = evaluate(sym, side, r, med, amt.get(sym), ml.get(sym), lv, chain.get(sym))
            if e:
                rows[side].append(e)
    key = lambda e: (-e["score"], -(e["break_pct"] or 0.0), -e["rvol"])
    return {"ok": True, "updated": rs.get("updated"), "market": rs["market"], "breakouts": sorted(rows[1], key=key)[:TOP_N], "breakdowns": sorted(rows[-1], key=key)[:TOP_N],
            "n_breakouts": len(rows[1]), "n_breakdowns": len(rows[-1]), "checks": list(CHECKS)}
