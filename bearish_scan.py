"""Bearish setup scan over every F&O stock (research / display only; no trading effect).

For each stock on a day, from the saved 5-minute candles (data/pattern_log/candles/<day>.json, which also carry the previous day's high / low), it finds the FIRST 5-minute bar at which
all of these are true together:

    breakdown      the bar closes below the opening-range low (low of 09:15-09:45)
    VWAP           the close is below the session VWAP (cumulative typical price x volume)
    DL             the bar makes a fresh day low (its low is at or under every earlier low of the day)
    PDL            the close is below the previous day's low
    break confirm  this bar and the one before both closed below PDL, by at least CONFIRM_PCT (default 0.05 %)

Entry = the open of the NEXT bar (what a trader could actually get). For each signal it reports how far the stock then went (to the day low, to the close, and against us), whether it
reclaimed PDL later, and whether our paper journal took a put in that stock that day, and an option-style race (stock -0.65 % before +1.3 %, about option +10 % before -20 %). The same scan without the "break confirm" condition is shown for comparison, to see what confirmation
adds.

    python bearish_scan.py [YYYY-MM-DD ...]      default: every saved day;   writes data/reports/bearish_scan_<day>.csv and prints a summary
"""

from __future__ import annotations

import csv
import json
import statistics as st
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
OR_BARS = 6                      # 09:15-09:45 opening range
CONFIRM_PCT = 0.05
PROXY_TARGET_PCT, PROXY_STOP_PCT = 0.65, 1.3
FIRST_SIGNAL_MIN = 9 * 60 + 45   # the opening range must be complete
LAST_SIGNAL_MIN = 15 * 60


def _hm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def find_signal(d: Mapping[str, Any], confirm: bool = True) -> dict[str, Any] | None:
    """First bar where every condition holds, or None. d = one stock's entry of the candle file (minute/open/high/low/close/volume lists and pdl)."""
    m, o, h, l, c, v = (d[k] for k in ("minute", "open", "high", "low", "close", "volume"))
    pdl = float(d.get("pdl") or 0)
    n = len(m)
    if pdl <= 0 or n <= OR_BARS + 1:
        return None
    orl = min(l[:OR_BARS])
    cum_pv = cum_v = 0.0
    day_low = float("inf")
    for i in range(n):
        typical = (h[i] + l[i] + c[i]) / 3.0
        cum_pv += typical * v[i]
        cum_v += v[i]
        vwap = cum_pv / cum_v if cum_v > 0 else c[i]
        fresh_low = l[i] <= day_low
        day_low = min(day_low, l[i])
        if m[i] < FIRST_SIGNAL_MIN or m[i] > LAST_SIGNAL_MIN or i >= n - 1:
            continue
        thresh = pdl * (1 - CONFIRM_PCT / 100.0)
        below_pdl = c[i] < pdl
        confirmed = c[i] < thresh and i > 0 and c[i - 1] < thresh
        if c[i] < orl and c[i] < vwap and fresh_low and below_pdl and (confirmed or not confirm):
            entry = o[i + 1]
            proxy = ""                                   # option-style race: stock -TARGET % (about option +10 %) before +STOP % (about option -20 %); a bar touching both counts as the stop
            for j in range(i + 1, n):
                if h[j] >= entry * (1 + PROXY_STOP_PCT / 100.0):
                    proxy = 0
                    break
                if l[j] <= entry * (1 - PROXY_TARGET_PCT / 100.0):
                    proxy = 1
                    break
            after_low = min(l[i + 1:])
            after_high = max(h[i + 1:])
            return {"time": _hm(m[i] + 5), "entry": round(entry, 2), "pdl": pdl, "orl": round(orl, 2), "vwap": round(vwap, 2), "bar_close": c[i],
                    "to_day_low_pct": round((after_low / entry - 1) * 100, 2), "to_close_pct": round((c[-1] / entry - 1) * 100, 2),
                    "against_pct": round((after_high / entry - 1) * 100, 2), "reclaimed_pdl": int(any(x > pdl for x in c[i + 1:])),
                    "close_below_entry": int(c[-1] < entry), "proxy_hit": proxy}
    return None


def scan_day(day: str, root: Path = ROOT) -> dict[str, list[dict[str, Any]]]:
    path = root / "data" / "pattern_log" / "candles" / f"{day}.json"
    syms = json.loads(path.read_text(encoding="utf-8")).get("symbols", {})
    out: dict[str, list[dict[str, Any]]] = {"confirmed": [], "unconfirmed": []}
    for sym, d in sorted(syms.items()):
        for key, flag in (("confirmed", True), ("unconfirmed", False)):
            sig = find_signal(d, flag)
            if sig:
                out[key].append({"day": day, "symbol": sym, **sig})
    return out


def traded_puts(day: str, root: Path = ROOT) -> dict[str, str]:
    """symbol -> entry time of our paper PUT trade that day (bearish side)."""
    try:
        trades = json.loads((root / "data" / "reports" / "paper_trade_history.json").read_text(encoding="utf-8")).get("paper_trades") or []
    except (OSError, ValueError):
        return {}
    return {str(t.get("symbol")): str(t.get("entry_time"))[11:16] for t in trades if str(t.get("entry_time", "")).startswith(day) and str(t.get("direction")).upper() == "BEARISH"}


def summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    f = lambda k: [float(r[k]) for r in rows]
    return {"n": len(rows), "closed_below_entry_pct": round(100 * sum(int(r["close_below_entry"]) for r in rows) / len(rows), 0), "median_to_close_pct": round(st.median(f("to_close_pct")), 2),
            "median_to_day_low_pct": round(st.median(f("to_day_low_pct")), 2), "median_against_pct": round(st.median(f("against_pct")), 2),
            "reclaimed_pdl_pct": round(100 * sum(int(r["reclaimed_pdl"]) for r in rows) / len(rows), 0),
            "proxy_target_first_pct": round(100 * sum(1 for r in rows if str(r.get("proxy_hit")) == "1") / len(rows), 0),
            "proxy_stop_first_pct": round(100 * sum(1 for r in rows if str(r.get("proxy_hit")) == "0") / len(rows), 0)}


def main() -> int:
    days = sys.argv[1:] or sorted(p.stem for p in (ROOT / "data" / "pattern_log" / "candles").glob("2026-*.json"))
    both: dict[str, list[dict[str, Any]]] = {"confirmed": [], "unconfirmed": []}
    for day in days:
        res = scan_day(day)
        took = traded_puts(day)
        for r in res["confirmed"]:
            r["we_traded_put"] = took.get(r["symbol"], "")
        out = ROOT / "data" / "reports" / f"bearish_scan_{day}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="") as h:
            cols = ["day", "symbol", "time", "entry", "pdl", "orl", "vwap", "to_day_low_pct", "to_close_pct", "against_pct", "reclaimed_pdl", "close_below_entry", "proxy_hit", "we_traded_put"]
            w = csv.DictWriter(h, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(res["confirmed"])
        for k in both:
            both[k] += res[k]
        print(f"{day}: confirmed {len(res['confirmed'])}, without confirm {len(res['unconfirmed'])}  ->  {out.name}")
    print("\nconfirmed   ", summary(both["confirmed"]))
    print("no confirm  ", summary(both["unconfirmed"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
