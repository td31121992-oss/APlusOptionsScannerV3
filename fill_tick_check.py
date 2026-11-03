"""Tick-level fill check for the paper trades (RESEARCH ONLY: reads recorded option ticks and the journal, changes nothing).

Paper trades are filled at a price the journal chose. The question that decides whether paper results can be trusted is: at that second, with the real order book, could an order for our quantity
really have been filled at (about) that price? For every closed paper trade whose option contract was recorded by option_tick_recorder.py (data/option_ticks/<day>/<security_id>_<SYMBOL>.csv.gz)
this looks at the packets around the entry and the exit:

    ENTRY   entry_vs_ask_pct    how far the best ask was above the paper entry price, % (what a buy at the ask would have cost extra)
            top_covers          the best ask's quantity covers our whole quantity        depth5_covers   the five best asks together cover it
            traded_at_paper     some trade printed at or below the paper price within FILL_WINDOW_S seconds after entry (a resting buy at that price could have filled)
    EXIT    exit_vs_bid_pct     how far the best bid was below the paper exit price, %   top_covers / depth5_covers  for the bid side (our sell)
            traded_at_paper     some trade printed at or above the paper exit price within FILL_WINDOW_S seconds

    data/reports/fill_tick_check.csv      one row per trade and side
    data/reports/fill_tick_check.md       the totals, newest run
    python fill_tick_check.py [--days N]  default: all days that have option ticks

A trade with no recorded option ticks is listed as "no ticks" and left out of the percentages. Option ticks exist from the first session the recorder ran; before that, only fill_realism_report.py applies.
"""

from __future__ import annotations

import csv
import json
import statistics as st
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import tick_gz

ROOT = Path(__file__).resolve().parent
FILL_WINDOW_S = 15.0
LOOK_AHEAD_S = 3.0               # the first packet may arrive a couple of seconds after the entry (the recorder subscribes within 2-3 s): the nearest packet within this many seconds counts
COLUMNS = ["day", "paper_trade_id", "symbol", "side", "paper_price", "quantity", "ref_time", "book_bid", "book_ask", "book_vs_paper_pct", "top_qty", "top_covers", "depth5_qty", "depth5_covers",
           "traded_at_paper"]


def _secs(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def _iso_secs(iso: str) -> float | None:
    try:
        d = datetime.fromisoformat(str(iso))
        return d.hour * 3600 + d.minute * 60 + d.second + d.microsecond / 1e6
    except ValueError:
        return None


def load_trades(root: Path) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for rel, key in ((("data", "reports", "paper_trade_history.json"), "paper_trades"), (("data", "intraday_movement", "paper_trade_journal.json"), "trades")):
        try:
            for t in json.loads(root.joinpath(*rel).read_text(encoding="utf-8")).get(key) or []:
                seen[str(t.get("paper_trade_id") or id(t))] = t
        except (OSError, ValueError):
            continue
    return [t for t in seen.values() if str(t.get("status") or "").upper() == "CLOSED"]


def load_ticks(root: Path, day: str, sid: str, symbol: str) -> list[dict[str, Any]]:
    path = root / "data" / "option_ticks" / day / f"{sid}_{symbol}.csv.gz"
    if not path.exists():
        return []
    text, _members, _bad = tick_gz.read_text(path)
    rows = []
    for r in csv.DictReader(text.splitlines()):
        try:
            rows.append({"t": _secs(r["ts"]), "ltp": _f(r["ltp"]), "bid": _f(r["bid"]), "bq": _f(r["bq"]), "ask": _f(r["ask"]), "aq": _f(r["aq"]), "bsum5": _f(r["bsum5"]), "asum5": _f(r["asum5"]),
                         "tq": _f(r["tq"])})
        except (KeyError, ValueError):
            continue
    return rows


def check_side(ticks: list[dict[str, Any]], t0: float, price: float, qty: float, buy: bool) -> dict[str, Any] | None:
    """The book at the first packet in [t0, t0 + LOOK_AHEAD_S] (else the last packet before t0) and whether a trade printed at the paper price in the next FILL_WINDOW_S seconds."""
    if not ticks or price <= 0:
        return None
    book = next((x for x in ticks if t0 <= x["t"] <= t0 + LOOK_AHEAD_S), None) or next((x for x in reversed(ticks) if x["t"] < t0), None)
    if book is None or (book["ask"] if buy else book["bid"]) <= 0:
        return None
    px = book["ask"] if buy else book["bid"]
    top, depth = (book["aq"], book["asum5"]) if buy else (book["bq"], book["bsum5"])
    window = [x for x in ticks if t0 <= x["t"] <= t0 + FILL_WINDOW_S and x["tq"] > 0]
    traded = any((x["ltp"] <= price) if buy else (x["ltp"] >= price) for x in window)
    return {"ref_time": round(book["t"], 1), "book_bid": book["bid"], "book_ask": book["ask"], "book_vs_paper_pct": round(((px - price) if buy else (price - px)) / price * 100.0, 2),
            "top_qty": top, "top_covers": int(top >= qty), "depth5_qty": depth, "depth5_covers": int(depth >= qty), "traded_at_paper": int(traded)}


def run(root: Path = ROOT, days: int | None = None) -> dict[str, Any] | None:
    trades = load_trades(root)
    cache: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    rows, no_ticks = [], 0
    for t in sorted(trades, key=lambda x: str(x.get("entry_time"))):
        day = str(t.get("entry_time") or "")[:10]
        sid, sym, qty = str(t.get("option_security_id") or ""), str(t.get("symbol") or ""), _f(t.get("quantity"))
        if not (day and sid and qty > 0) or not (root / "data" / "option_ticks" / day).exists():
            continue
        key = (day, sid, sym)
        if key not in cache:
            cache[key] = load_ticks(root, day, sid, sym)
        ticks = cache[key]
        if not ticks:
            no_ticks += 1
            continue
        for side, when, price, buy in (("ENTRY", t.get("entry_time"), _f(t.get("entry_price")), True), ("EXIT", t.get("exit_time"), _f(t.get("exit_price")), False)):
            t0 = _iso_secs(str(when or ""))
            res = check_side(ticks, t0, price, qty, buy) if t0 is not None else None
            if res:
                rows.append({"day": day, "paper_trade_id": t.get("paper_trade_id"), "symbol": sym, "side": side, "paper_price": price, "quantity": qty, **res})
    if days:
        keep = sorted({r["day"] for r in rows})[-days:]
        rows = [r for r in rows if r["day"] in keep]
    if not rows:
        return None
    out = root / "data" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "fill_tick_check.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    summary = summarise(rows, no_ticks)
    (out / "fill_tick_check.md").write_text(render(summary), encoding="utf-8")
    return summary


def summarise(rows: list[dict[str, Any]], no_ticks: int = 0) -> dict[str, Any]:
    s: dict[str, Any] = {"trades_without_ticks": no_ticks, "days": sorted({r["day"] for r in rows})}
    for side in ("ENTRY", "EXIT"):
        g = [r for r in rows if r["side"] == side]
        if not g:
            continue
        pct = lambda key: round(100.0 * sum(1 for r in g if r[key]) / len(g), 1)
        s[side] = {"n": len(g), "median_book_vs_paper_pct": round(st.median(r["book_vs_paper_pct"] for r in g), 2), "worst_book_vs_paper_pct": round(max(r["book_vs_paper_pct"] for r in g), 2),
                   "top_covers_pct": pct("top_covers"), "depth5_covers_pct": pct("depth5_covers"), "traded_at_paper_pct": pct("traded_at_paper")}
    return s


def render(s: dict[str, Any]) -> str:
    L = ["# Tick-level fill check (research only)", "",
         f"Days: {', '.join(s['days'])}. Trades with no recorded option ticks (left out): {s['trades_without_ticks']}.", "",
         "Book vs paper = how much worse the best ask (buys) / best bid (sells) was than the paper price, %. Covers = the displayed quantity is at least our order size. Traded at paper = a trade printed at"
         f" or through the paper price within {FILL_WINDOW_S:.0f} s.", "",
         "| Side | Trades | Median book vs paper | Worst | Top of book covers | 5 levels cover | Traded at paper price |", "|---|---|---|---|---|---|---|"]
    for side in ("ENTRY", "EXIT"):
        if side in s:
            e = s[side]
            L.append(f"| {side} | {e['n']} | {e['median_book_vs_paper_pct']:+.2f}% | {e['worst_book_vs_paper_pct']:+.2f}% | {e['top_covers_pct']}% | {e['depth5_covers_pct']}% | {e['traded_at_paper_pct']}% |")
    return "\n".join(L) + "\n"


def main() -> int:
    days = None
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    s = run(ROOT, days)
    print("no option ticks to check yet" if s is None else render(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
