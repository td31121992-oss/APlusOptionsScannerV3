"""Smart Money Flow: a live, read-only wall of where the money is moving, built from the order-book recorder's once-a-minute readings (data/order_book/<date>.csv).

    /smart-flow          the page
    /api/smart-flow      the data behind it; nothing is written anywhere

What it shows (all derived from the same minute readings money_flow.py uses, so the numbers agree with the Money Flow page):
    index cards     NIFTY 50, BANK NIFTY and SENSEX with their move and a column of 5-minute flow bars.  The index quote comes from index_strip; the bars are the net flow of
                    ALL F&O stocks (NIFTY), the bank stocks (BANK NIFTY) and the 30 most-traded stocks (SENSEX) - a proxy, because index futures are not recorded.
    sector curves   every stock's move from yesterday's close through the day (faint lines), each sector's average (bold), sectors ranked by move with a flow bar
    breadth         stocks up / down and a dot strip of every stock's move
    top cards       the 20 biggest gainers and 20 biggest losers with their 5-minute flow bars and a structure badge (CHoCH / BOS and when it happened)
Flow direction uses the tick rule (an up-tick is buying, a down-tick is selling): an estimate of who was the aggressor, not a record of who bought. Not a trade signal.
"""

from __future__ import annotations

import csv
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import money_flow

ROOT = Path(__file__).resolve().parent
CR = 1e7
TOP_N = 20
SUBSET_TOP_TRADED = 30
STOCK_FLOW_N = 10                    # the stock flow ring shows this many biggest net buyers and net sellers
RECENT_BARS = 6                     # the "last 30 minutes" lists use this many 5-minute buckets
_LOCK = threading.Lock()
_S: dict[str, Any] = {"key": None, "offset": 0, "header": None, "sym": {}, "last_time": "", "cache": None, "cache_at": 0.0}
_TTL = 8.0


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def _bucket(t: str) -> str:
    """'10:07' -> '10:05' (5-minute buckets)."""
    h, m = int(t[:2]), int(t[3:5])
    return f"{h:02d}:{m - m % 5:02d}"


def step(state: dict[str, Any], symbol: str, t: str, ltp: float, volume: float) -> None:
    """One reading of one stock: update its 5-minute buckets (open/high/low/close and bought / sold value). Pure; unit tested."""
    s = state.setdefault(symbol, {"lp": 0.0, "lv": 0.0, "cls": 0, "first": ltp, "b": {}})
    b = s["b"].setdefault(_bucket(t), {"o": ltp, "h": ltp, "l": ltp, "c": ltp, "buy": 0.0, "sell": 0.0})
    b["h"], b["l"], b["c"] = max(b["h"], ltp), min(b["l"], ltp), ltp
    if s["lp"] > 0 and volume >= s["lv"] and ltp > 0:
        value = (volume - s["lv"]) * (ltp + s["lp"]) / 2.0
        cls = 1 if ltp > s["lp"] else -1 if ltp < s["lp"] else s["cls"]
        if value > 0:
            b["buy" if cls >= 0 else "sell"] += value
        if cls:
            s["cls"] = cls
    s["lp"], s["lv"] = ltp, max(volume, s["lv"])


def _reset(key: str) -> None:
    _S.update(key=key, offset=0, header=None, sym={}, last_time="", cache=None, cache_at=0.0)


def _refresh(root: Path, day: date) -> None:
    path = root / "data" / "order_book" / f"{day.isoformat()}.csv"
    key = f"{root}|{day}"
    if _S["key"] != key:
        _reset(key)
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size < _S["offset"]:
        _reset(key)
    if size == _S["offset"]:
        return
    with path.open("rb") as handle:
        handle.seek(_S["offset"])
        chunk = handle.read()
    end = chunk.rfind(b"\n")
    if end < 0:
        return
    _S["offset"] += end + 1
    lines = chunk[: end + 1].decode("utf-8", errors="replace").splitlines()
    if _S["header"] is None:
        if not lines:
            return
        _S["header"] = next(csv.reader([lines.pop(0)]))
    head = _S["header"]
    for row in csv.reader(lines):
        if len(row) != len(head):
            continue
        r = dict(zip(head, row))
        t, sym, ltp = r.get("time", "")[11:16], r.get("symbol", ""), _f(r.get("ltp"))
        if sym and t and ltp > 0:
            step(_S["sym"], sym, t, ltp, _f(r.get("volume")))
            if t > _S["last_time"]:
                _S["last_time"] = t
    _S["cache"] = None


def _times(last_time: str) -> list[str]:
    out, m = [], 9 * 60 + 15
    end = int(last_time[:2]) * 60 + int(last_time[3:5])
    while m <= end:
        out.append(f"{m // 60:02d}:{m % 60:02d}")
        m += 5
    return out


def _badge(candles: Sequence[Mapping[str, float]], times: Sequence[str], bull: bool) -> dict[str, Any]:
    """Structure badge from the 5-minute candles: the latest CHoCH (else BOS) with its direction and time, plus order-block / liquidity distances."""
    out: dict[str, Any] = {"tag": "", "up": None, "at": "", "ob": None, "liq": None}
    try:
        import market_structure
        import smc_levels

        direction = "BULLISH" if bull else "BEARISH"
        ms = market_structure.structure_tags(candles, direction)
        for key, name in (("ms_choch", "CHoCH"), ("ms_bos", "BOS")):
            if ms.get(key):
                out["tag"], out["up"] = name, ms[key] == "BULL"
                ago = ms.get("ms_event_bars_ago")
                if isinstance(ago, int) and 0 <= ago < len(times):
                    out["at"] = times[-1 - ago]
                break
        sm = smc_levels.entry_tags(candles, direction)
        out["ob"] = sm.get("smc_ob_dist_pct")
        out["liq"] = sm.get("smc_liq_ahead_pct")
    except Exception:                                      # noqa: BLE001 - a badge must never break the page
        pass
    return out


def _fill(series: list[float | None]) -> list[float | None]:
    last = None
    for i, v in enumerate(series):
        if v is None:
            series[i] = last
        else:
            last = v
    return series


def build(state: Mapping[str, Any], last_time: str, sectors: Mapping[str, str], market: Mapping[str, Mapping[str, Any]], indices: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    times = _times(last_time)
    stocks = []
    for sym, s in state.items():
        b = s["b"]
        m = market.get(sym, {})
        prev = _f(m.get("previous_close")) or _f(s.get("first"))
        if prev <= 0 or s["lp"] <= 0:
            continue
        net_b = [(b[t]["buy"] - b[t]["sell"]) / CR if t in b else 0.0 for t in times]
        tot_b = [(b[t]["buy"] + b[t]["sell"]) / CR if t in b else 0.0 for t in times]
        buy, sell = sum(x["buy"] for x in b.values()), sum(x["sell"] for x in b.values())
        curve = _fill([round((b[t]["c"] / prev - 1) * 100, 2) if t in b else None for t in times])
        stocks.append({"s": sym, "sec": m.get("sector") or sectors.get(sym) or "Other", "ltp": round(s["lp"], 2), "chg": round((s["lp"] / prev - 1) * 100, 2),
                       "net": round((buy - sell) / CR, 2), "cr": round((buy + sell) / CR, 2), "flow": round((buy - sell) / (buy + sell) * 100, 1) if buy + sell > 0 else 0.0,
                       "bars": [round(x, 2) for x in net_b], "tot": [round(x, 2) for x in tot_b], "curve": curve})
    stocks.sort(key=lambda x: -x["chg"])
    up = [x for x in stocks if x["chg"] > 0]
    down = [x for x in stocks if x["chg"] < 0]
    gainers, losers = stocks[:TOP_N], stocks[::-1][:TOP_N]
    for rank, x in enumerate(gainers, 1):
        x["rank"] = rank
    for rank, x in enumerate(losers, 1):
        x["rank"] = rank
    for x in gainers + losers:
        cs = [{"open": state[x["s"]]["b"][t]["o"], "high": state[x["s"]]["b"][t]["h"], "low": state[x["s"]]["b"][t]["l"], "close": state[x["s"]]["b"][t]["c"]}
              for t in times if t in state[x["s"]]["b"]]
        x["smc"] = _badge(cs, [t for t in times if t in state[x["s"]]["b"]], x["chg"] > 0)

    groups: dict[str, list[dict[str, Any]]] = {}
    for x in stocks:
        groups.setdefault(x["sec"], []).append(x)
    secs = []
    for name, items in groups.items():
        n = len(times)
        curve = [round(sum((i["curve"][k] or 0.0) for i in items) / len(items), 2) for k in range(n)]
        buy_net = sum(i["net"] for i in items)
        tot = sum(i["cr"] for i in items)
        secs.append({"sec": name, "n": len(items), "chg": round(sum(i["chg"] for i in items) / len(items), 2), "net": round(buy_net, 1),
                     "flow": round(buy_net / tot * 100, 1) if tot > 0 else 0.0, "curve": curve})
    secs.sort(key=lambda x: -x["chg"])

    def agg(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        n = len(times)
        net = [round(sum(i["bars"][k] for i in items), 2) for k in range(n)]
        tot = [round(sum(i["tot"][k] for i in items), 2) for k in range(n)]
        return {"bars": net, "tot": tot, "net": round(sum(net), 1), "cr": round(sum(tot), 1)}

    by_traded = sorted(stocks, key=lambda x: -x["cr"])[:SUBSET_TOP_TRADED]
    banks = [x for x in stocks if "bank" in x["sec"].lower()]
    quotes = {str(r.get("name")): r for r in indices or []}
    cards = []
    for label, qname, items, note in (("NIFTY 50", "NIFTY 50", stocks, "flow: all F&O stocks"), ("BANK NIFTY", "BANK NIFTY", banks, "flow: bank stocks"),
                                      ("SENSEX", "SENSEX", by_traded, f"flow: top {SUBSET_TOP_TRADED} traded")):
        q = quotes.get(qname, {})
        cards.append({"name": label, "ltp": q.get("ltp"), "chg": q.get("pct_prev"), "note": note, **agg(items)})
    by_net = sorted(stocks, key=lambda x: -x["net"])
    ring = list({x["s"]: x for x in by_net[:STOCK_FLOW_N] + by_net[-STOCK_FLOW_N:]}.values())
    stockflow = [{"name": x["s"], "sec": x["sec"], "net": x["net"], "chg": x["chg"]} for x in ring]
    recent = sorted(stocks, key=lambda x: -sum(x["bars"][-RECENT_BARS:]))
    movers = [{"s": x["s"], "sec": x["sec"], "chg": x["chg"], "net": round(sum(x["bars"][-RECENT_BARS:]), 2), "cr": round(sum(x["tot"][-RECENT_BARS:]), 2)} for x in recent]
    return {"ok": True, "as_of": last_time, "times": times, "cards": cards, "recent_minutes": RECENT_BARS * 5, "stockflow": stockflow,
            "buyers": [m for m in movers[:8] if m["net"] > 0], "sellers": [m for m in movers[::-1][:8] if m["net"] < 0], "gainers": gainers, "losers": losers, "sectors": secs,
            "breadth": {"up": len(up), "down": len(down), "n": len(stocks)}, "dots": [x["chg"] for x in stocks],
            "lead": secs[0]["sec"] if secs else "", "lag": secs[-1]["sec"] if secs else "",
            "lead_chg": secs[0]["chg"] if secs else 0.0, "lag_chg": secs[-1]["chg"] if secs else 0.0,
            "curves": [{"s": x["s"], "c": x["curve"], "top": x["rank"] <= 5 if "rank" in x else False} for x in stocks]}


def payload(root: Path = ROOT, today: date | None = None, indices: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    with _LOCK:
        try:
            _refresh(root, today or date.today())
        except Exception:                                  # noqa: BLE001 - the page must still load
            pass
        if not _S["last_time"]:
            return {"ok": False, "error": "no order-book readings yet today (the recorder runs 09:15-15:30)"}
        if _S["cache"] is not None and time.time() - _S["cache_at"] < _TTL:
            return _S["cache"]
        out = build(_S["sym"], _S["last_time"], money_flow._sector_map(root), money_flow._market_rows(root), indices)
        _S["cache"], _S["cache_at"] = out, time.time()
        return out
