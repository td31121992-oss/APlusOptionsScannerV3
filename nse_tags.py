"""Shadow tags from NSE's daily data and the pre-open auction (nd_ and po_ prefixes: recorded on the candidate / trade, never used to allow or block anything).

Sources: nse_daily_data.py (data/nse_daily/stock_daily.csv, deals/) and preopen_recorder.py (data/preopen/<day>_final.csv). Everything is about the PREVIOUS trading day or earlier except the pre-open
tags, which are today's auction, so nothing here looks into the future.

    nd_deliv_pct        previous day's delivery %                      nd_deliv_x      that vs the stock's average delivery % over the 20 days before it
    nd_vol_x            previous day's traded quantity vs its 20-day average
    nd_pcr_oi           previous day's put OI / call OI (all expiries) nd_pcr_oi_x     that vs its 10-day average
    nd_fut_label        previous day's near-month future: LONG_BUILDUP / SHORT_COVERING / SHORT_BUILDUP / LONG_UNWINDING / NEUTRAL (price move and OI move, as in futures_flow.py)
    nd_fut_oi_chg_pct   the future's open-interest change that day, %
    nd_prem_x           previous day's option premium turnover (calls + puts, Rs crore) vs its 10-day average: a real full-day baseline, unlike the 5-minute chain data
    nd_prem_call_share  calls' share of that premium, 0..1
    nd_days             how many earlier days of history this stock has
    nd_deal_dir_cr      bulk + block deals of the last 5 calendar days: net BUYING value in Rs crore in OUR direction (positive = deals were with the trade);  nd_deal_n  deals counted

    po_gap_dir_pct      the pre-open indicative price vs the previous close, % in OUR direction (positive = the gap is with the trade)
    po_imb_dir          pre-open (buy - sell) / (buy + sell) queued quantity in OUR direction, -1..1
    po_qty_pct_adv      quantity that would trade at the indicative price, % of the stock's 20-day average daily volume
    po_turnover_cr      Rs crore at the indicative price

Missing data leaves the tag out (a stock with no history gets only what exists).
"""

from __future__ import annotations

import csv
import statistics as st
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
NUM = ("close", "prev_close", "ttl_qty", "turnover_cr", "trades", "deliv_qty", "deliv_per", "fut_oi", "fut_oi_chg", "fut_close", "fut_settle", "call_oi", "put_oi", "call_vol", "put_vol",
       "call_prem_cr", "put_prem_cr")
MIN_PRICE_MOVE_PCT = 0.10
MIN_OI_MOVE_PCT = 0.30
_DAILY: dict[str, Any] = {"mtime": None, "path": None, "rows": {}}
_DEALS: dict[str, Any] = {"key": None, "rows": []}
_PRE: dict[str, Any] = {"path": None, "mtime": None, "rows": {}}


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _daily(root: Path) -> dict[str, list[dict[str, Any]]]:
    path = root / "data" / "nse_daily" / "stock_daily.csv"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _DAILY["path"] != str(path) or _DAILY["mtime"] != mtime:
        rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        try:
            with path.open(encoding="utf-8", newline="") as h:
                for r in csv.DictReader(h):
                    for k in NUM:
                        r[k] = _f(r.get(k))
                    rows[r["symbol"]].append(r)
        except (OSError, KeyError):
            return {}
        for v in rows.values():
            v.sort(key=lambda r: r["day"])
        _DAILY.update(path=str(path), mtime=mtime, rows=dict(rows))
    return _DAILY["rows"]


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    v = [r[key] for r in rows if r.get(key) is not None]
    return st.mean(v) if v else None


def _label(px_pct: float, oi_pct: float) -> str:
    if abs(px_pct) < MIN_PRICE_MOVE_PCT or abs(oi_pct) < MIN_OI_MOVE_PCT:
        return "NEUTRAL"
    if px_pct > 0:
        return "LONG_BUILDUP" if oi_pct > 0 else "SHORT_COVERING"
    return "SHORT_BUILDUP" if oi_pct > 0 else "LONG_UNWINDING"


def daily_tags(symbol: str, today: str, root: Path) -> dict[str, Any]:
    rows = [r for r in _daily(root).get(symbol, []) if r["day"] < today]
    if not rows:
        return {}
    last, hist = rows[-1], rows[:-1]
    out: dict[str, Any] = {"nd_days": len(hist)}
    if last.get("deliv_per") is not None:
        out["nd_deliv_pct"] = round(last["deliv_per"], 1)
        base = _mean(hist[-20:], "deliv_per")
        if base and len(hist) >= 5:
            out["nd_deliv_x"] = round(last["deliv_per"] / base, 2)
    base = _mean(hist[-20:], "ttl_qty")
    if last.get("ttl_qty") and base and len(hist) >= 5:
        out["nd_vol_x"] = round(last["ttl_qty"] / base, 2)
    if last.get("call_oi") and last.get("put_oi") is not None:
        pcr = last["put_oi"] / last["call_oi"]
        out["nd_pcr_oi"] = round(pcr, 2)
        past = [r["put_oi"] / r["call_oi"] for r in hist[-10:] if r.get("call_oi") and r.get("put_oi") is not None]
        if len(past) >= 3 and st.mean(past) > 0:
            out["nd_pcr_oi_x"] = round(pcr / st.mean(past), 2)
    if last.get("fut_oi") and last.get("fut_oi_chg") is not None and last.get("prev_close") and last.get("close"):
        before = last["fut_oi"] - last["fut_oi_chg"]
        if before > 0:
            oi_pct = last["fut_oi_chg"] / before * 100.0
            out["nd_fut_oi_chg_pct"] = round(oi_pct, 2)
            out["nd_fut_label"] = _label((last["close"] / last["prev_close"] - 1.0) * 100.0, oi_pct)
    calls, puts = last.get("call_prem_cr"), last.get("put_prem_cr")
    if calls is not None and puts is not None and calls + puts > 0:
        total = calls + puts
        past = [(r["call_prem_cr"] or 0.0) + (r["put_prem_cr"] or 0.0) for r in hist[-10:] if r.get("call_prem_cr") is not None]
        if len(past) >= 3 and st.mean(past) > 0:
            out["nd_prem_x"] = round(total / st.mean(past), 2)
        out["nd_prem_call_share"] = round(calls / total, 2)
    return out


def deal_tags(symbol: str, sign: float, today: str, root: Path) -> dict[str, Any]:
    folder = root / "data" / "nse_daily" / "deals"
    key = (str(folder), today, sum(p.stat().st_mtime_ns for p in folder.glob("*.csv")) if folder.exists() else 0)
    if _DEALS["key"] != key:
        rows: list[dict[str, str]] = []
        lo = (date.fromisoformat(today) - timedelta(days=5)).isoformat()
        for p in sorted(folder.glob("*.csv")) if folder.exists() else []:
            if lo <= p.name[:10] < today:
                with p.open(encoding="utf-8", newline="") as h:
                    rows += list(csv.DictReader(h))
        _DEALS.update(key=key, rows=rows)
    mine = [r for r in _DEALS["rows"] if r.get("symbol") == symbol]
    if not mine:
        return {}
    net = sum((_f(r.get("value_cr")) or 0.0) * (1 if r.get("side") == "BUY" else -1) for r in mine)
    return {"nd_deal_dir_cr": round(sign * net, 2), "nd_deal_n": len(mine)}


def preopen_tags(symbol: str, sign: float, today: str, root: Path) -> dict[str, Any]:
    path = root / "data" / "preopen" / f"{today}_final.csv"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _PRE["path"] != str(path) or _PRE["mtime"] != mtime:
        try:
            with path.open(encoding="utf-8", newline="") as h:
                _PRE.update(path=str(path), mtime=mtime, rows={r["symbol"]: r for r in csv.DictReader(h)})
        except OSError:
            return {}
    r = _PRE["rows"].get(symbol)
    if not r:
        return {}
    out: dict[str, Any] = {}
    gap, imb = _f(r.get("gap_pct")), _f(r.get("imbalance"))
    if gap is not None:
        out["po_gap_dir_pct"] = round(sign * gap, 2)
    if imb is not None:
        out["po_imb_dir"] = round(sign * imb, 3)
    turnover = _f(r.get("turnover_cr"))
    if turnover is not None:
        out["po_turnover_cr"] = turnover
    adv = _mean([x for x in _daily(root).get(symbol, []) if x["day"] < today][-20:], "ttl_qty")
    qty = _f(r.get("final_qty"))
    if qty is not None and adv:
        out["po_qty_pct_adv"] = round(qty / adv * 100.0, 2)
    return out


def tags(symbol: str, direction: str, now: datetime, root: Path = ROOT) -> dict[str, Any]:
    """Shadow tags for a candidate (see the module docstring)."""
    try:
        today = now.date().isoformat()
        sign = 1.0 if str(direction).upper() == "BULLISH" else -1.0
        return {**daily_tags(symbol, today, root), **deal_tags(symbol, sign, today, root), **preopen_tags(symbol, sign, today, root)}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}
