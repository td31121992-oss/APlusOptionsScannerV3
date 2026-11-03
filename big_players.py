"""Big Players page data: where unusually large aggressive prints are landing, with four independent confirmations (READ-ONLY, display only).

    /big-players        the page (big_players_page.py)
    /api/big-players    JSON for the page

Per stock it joins
    big prints      big buying / selling in Rs crore today and over the last 15 minutes (big_prints.py, from the live tick stream)
    futures         the near-month future's price and open-interest move over ~30 minutes: LONG_BUILDUP / SHORT_COVERING (price up) or SHORT_BUILDUP / LONG_UNWINDING (price down)  (futures_recorder.py)
    options         share of the last 15 minutes' option premium on calls vs puts  (premium_flow.py, from the chain collector)
    order book      resting bid vs ask size, -1..1  (money_flow, order-book recorder)
    tick flow       net buying value over total traded value, %, by the tick rule  (money_flow)
and lists the stocks with the most big NET BUYING and the most big NET SELLING, each with how many of the four confirm.

Big prints cannot tell an institution from a retail trader, or one large order from many split ones: this shows where size is pressing, not who is behind it. Not a trade signal.
"""

from __future__ import annotations

import csv
import gzip
import threading
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
TOP_N = 15
MIN_PRICE_MOVE_PCT = 0.10
MIN_OI_MOVE_PCT = 0.30
_LOCK = threading.Lock()
_FUT: dict[str, Any] = {"path": None, "mtime": None, "data": {}}


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def _minute(stamp: str) -> int:
    return int(stamp[11:13]) * 60 + int(stamp[14:16])


def classify_future(px_chg_pct: float, oi_chg_pct: float) -> str:
    if abs(px_chg_pct) < MIN_PRICE_MOVE_PCT or abs(oi_chg_pct) < MIN_OI_MOVE_PCT:
        return "NEUTRAL"
    if px_chg_pct > 0:
        return "LONG_BUILDUP" if oi_chg_pct > 0 else "SHORT_COVERING"
    return "SHORT_BUILDUP" if oi_chg_pct > 0 else "LONG_UNWINDING"


def futures_state(root: Path, day: str) -> dict[str, dict[str, Any]]:
    """symbol -> near-month future's label and 30-minute price / OI change from data/futures/<day>.csv.gz (cached by modification time)."""
    path = root / "data" / "futures" / f"{day}.csv.gz"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    with _LOCK:
        if _FUT["path"] == str(path) and _FUT["mtime"] == mtime:
            return _FUT["data"]
    series: dict[str, list[tuple[int, float, float, float]]] = defaultdict(list)
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                if r.get("kind") == "STK" and r.get("contract") == "NEAR":
                    series[r["symbol"]].append((_minute(r["captured_at"]), _f(r["fut_ltp"]), _f(r["oi"]), _f(r["basis_pct"])))
    except (OSError, EOFError, KeyError, ValueError):
        pass                                               # a file still being written yields what was read
    out: dict[str, dict[str, Any]] = {}
    for sym, rows in series.items():
        rows.sort()
        last = rows[-1]
        past = next((x for x in reversed(rows) if x[0] <= last[0] - 30), rows[0])
        if past[1] > 0 and past[2] > 0 and past is not last:
            px, oi = (last[1] / past[1] - 1) * 100, (last[2] / past[2] - 1) * 100
            out[sym] = {"label": classify_future(px, oi), "px_pct": round(px, 2), "oi_pct": round(oi, 2), "basis": round(last[3], 2)}
    with _LOCK:
        _FUT.update(path=str(path), mtime=mtime, data=out)
    return out


def premium_lean(series: list[tuple[int, float, float]] | None) -> dict[str, Any]:
    """Call share of the premium traded in the last 15 minutes of the stock's captures (premium_flow series: minute, ce_cr, pe_cr)."""
    if not series:
        return {}
    end = series[-1][0]
    ce = sum(c for m, c, _p in series if m > end - 15)
    pe = sum(p for m, _c, p in series if m > end - 15)
    return {"ce_share": round(ce / (ce + pe), 2), "prem15_cr": round(ce + pe, 2)} if ce + pe > 0 else {}


def confirmations(side: str, fut: Mapping[str, Any] | None, lean: Mapping[str, Any] | None, imbalance: float | None, flow_pct: float | None) -> list[str]:
    """Which of the four independent signals agree with `side` ('BUY' or 'SELL')."""
    buy = side == "BUY"
    out = []
    label = (fut or {}).get("label", "")
    if label in (("LONG_BUILDUP", "SHORT_COVERING") if buy else ("SHORT_BUILDUP", "LONG_UNWINDING")):
        out.append("FUT")
    share = (lean or {}).get("ce_share")
    if share is not None and (share >= 0.65 if buy else share <= 0.35):
        out.append("OPT")
    if imbalance is not None and (imbalance >= 0.15 if buy else imbalance <= -0.15):
        out.append("BOOK")
    if flow_pct is not None and (flow_pct >= 10 if buy else flow_pct <= -10):
        out.append("TICK")
    return out


def build(bp: Mapping[str, Any], fut: Mapping[str, Any], prem: Mapping[str, Any], mf_stocks: Mapping[str, Mapping[str, Any]], sectors: Mapping[str, str]) -> dict[str, Any]:
    rows = []
    for sym, b in (bp.get("stocks") or {}).items():
        if not (b.get("n_buy") or b.get("n_sell")):
            continue
        m = mf_stocks.get(sym, {})
        lean = premium_lean(prem.get(sym))
        imb, flow = m.get("imbalance"), m.get("flow_pct")
        rows.append({"s": sym, "sec": sectors.get(sym) or m.get("sector") or "Other", "chg": m.get("chg_pct"), "ltp": b.get("ltp"), "net15": b["net15_cr"], "net": b["net_cr"],
                     "buy": b["buy_cr"], "sell": b["sell_cr"], "nb": b["n_buy"], "ns": b["n_sell"], "n15": b["n15"], "last": b.get("last"),
                     "fut": fut.get(sym), "lean": lean or None, "imb": imb, "flow": flow,
                     "cb": confirmations("BUY", fut.get(sym), lean, imb, flow), "cs": confirmations("SELL", fut.get(sym), lean, imb, flow)})
    buyers = sorted([r for r in rows if r["net15"] > 0 or (r["net15"] == 0 and r["net"] > 0)], key=lambda r: (-r["net15"], -r["net"]))[:TOP_N]
    sellers = sorted([r for r in rows if r["net15"] < 0 or (r["net15"] == 0 and r["net"] < 0)], key=lambda r: (r["net15"], r["net"]))[:TOP_N]
    sec: dict[str, dict[str, float]] = defaultdict(lambda: {"net": 0.0, "net15": 0.0, "n": 0})
    for r in rows:
        sec[r["sec"]]["net"] += r["net"]
        sec[r["sec"]]["net15"] += r["net15"]
        sec[r["sec"]]["n"] += 1
    sector_rows = sorted(({"sec": k, "net": round(v["net"], 1), "net15": round(v["net15"], 1), "n": int(v["n"])} for k, v in sec.items()), key=lambda x: -x["net"])
    tot_buy, tot_sell = sum(r["buy"] for r in rows), sum(r["sell"] for r in rows)
    return {"ok": True, "as_of": bp.get("updated", ""), "buyers": buyers, "sellers": sellers, "sectors": sector_rows, "tape": list(reversed(bp.get("tape") or []))[:40],
            "market": {"buy_cr": round(tot_buy, 1), "sell_cr": round(tot_sell, 1), "net_cr": round(tot_buy - tot_sell, 1),
                       "net_buying": sum(1 for r in rows if r["net"] > 0), "net_selling": sum(1 for r in rows if r["net"] < 0), "with_prints": len(rows)},
            "futures_ok": bool(fut), "options_ok": bool(prem)}


def payload(root: Path = ROOT, today: date | None = None) -> dict[str, Any]:
    import big_prints
    import money_flow
    import premium_flow

    day = (today or date.today()).isoformat()
    bp = big_prints.load(root, day)
    if not bp:
        return {"ok": False, "error": "no big-print data yet today (the tick recorder runs 09:05-15:32 and needs about 200 prints per stock before it flags big ones)"}
    mf = money_flow.payload(window=15, root=root, today=today)
    mf_stocks = {s["symbol"]: s for s in (mf.get("stocks") or [])}
    return build(bp, futures_state(root, day), premium_flow._load(root, day), mf_stocks, money_flow._sector_map(root))
