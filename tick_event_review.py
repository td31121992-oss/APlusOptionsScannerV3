"""Nightly review of the tick burst detector (research only; no trading effect).

For every event in data/tick_events/<day>.csv (or, with --replay, events regenerated from that day's recorded ticks) it takes the option we would have bought (the strict-label
contract: about 0.5 % in the money, nearest expiry, Upstox 1-minute candles) and asks whether it reaches +10 % before -20 %, entering one minute after the event.  It also shows how
many minutes before our own paper trade in that stock and direction the event fired (blank when we did not trade it).

    data/tick_events/review_<day>.csv     one row per event with the outcome
    data/tick_events/summary.md           hit rates by volume surge, size of move, direction and hour, across all reviewed days

    python tick_event_review.py [YYYY-MM-DD] [--replay]
"""

from __future__ import annotations

import csv
import json
import statistics as st
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

ROOT = Path(__file__).resolve().parent
FIELDS = ["day", "time", "symbol", "direction", "ltp", "move_pct", "volx", "buy_share", "day_move_pct", "strike", "entry", "hit10_first", "stop_first", "best_30", "best_day", "close_pct",
          "min_to_hit10", "trade_lead_min"]


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def trade_leads(trades: Iterable[Mapping[str, Any]], day: str) -> dict[tuple[str, str], float]:
    """(symbol, direction) -> minute of day of our first paper entry that day."""
    out: dict[tuple[str, str], float] = {}
    for t in trades:
        et = str(t.get("entry_time") or "")
        if not et.startswith(day) or len(et) < 16:
            continue
        key = (str(t.get("symbol")), str(t.get("direction")).upper())
        m = int(et[11:13]) * 60 + int(et[14:16])
        out[key] = min(out.get(key, m), m)
    return out


def review_events(events: list[Mapping[str, Any]], day: str, price_bars: Callable[[str, str], tuple[list, dict] | None], leads: Mapping[tuple[str, str], float]) -> list[dict[str, Any]]:
    """price_bars(symbol, direction) -> (option 1-minute bars, contract) or None. Pure apart from that callback (unit tested with a stub)."""
    import strict_label as sl

    rows = []
    for e in events:
        got = price_bars(e["symbol"], e["direction"])
        if not got:
            continue
        bars, ct = got
        h, m = e["time"].split(":")[:2]
        minute = int(h) * 60 + int(m)
        lab = sl.label(bars, minute, 1)
        if not lab:
            continue
        lead = leads.get((e["symbol"], e["direction"]))
        rows.append({"day": day, **{k: e.get(k, "") for k in ("time", "symbol", "direction", "ltp", "move_pct", "volx", "buy_share", "day_move_pct")}, "strike": ct.get("strike", ""),
                     **{k: lab[k] for k in ("entry", "hit10_first", "stop_first", "best_30", "best_day", "close_pct", "min_to_hit10")},
                     "trade_lead_min": round(lead - minute, 1) if lead is not None else ""})
    return rows


def summarise(rows: list[Mapping[str, Any]]) -> list[str]:
    def table(title: str, keyf: Callable[[Mapping[str, Any]], str]) -> list[str]:
        groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for r in rows:
            groups[keyf(r)].append(r)
        out = [f"### {title}", "", "| group | n | hit +10% first | stopped first | median best 30m | median close |", "|---|---|---|---|---|---|"]
        for k in sorted(groups):
            g = groups[k]
            best = [x for x in (_f(r.get("best_30")) for r in g) if x is not None]
            close = [x for x in (_f(r.get("close_pct")) for r in g) if x is not None]
            out.append(f"| {k} | {len(g)} | {100 * sum(int(r['hit10_first']) for r in g) / len(g):.0f}% | {100 * sum(int(r['stop_first']) for r in g) / len(g):.0f}% | "
                       f"{st.median(best):.0f}% | {st.median(close):.0f}% |" if best and close else f"| {k} | {len(g)} | | | | |")
        return out + [""]

    def vx(r: Mapping[str, Any]) -> str:
        v = _f(r.get("volx")) or 0
        return "a) 3-4x" if v < 4 else "b) 4-6x" if v < 6 else "c) 6x+"

    def mv(r: Mapping[str, Any]) -> str:
        v = abs(_f(r.get("move_pct")) or 0)
        return "a) 0.25-0.5%" if v < 0.5 else "b) 0.5-1%" if v < 1 else "c) 1%+"

    traded = lambda r: "we traded it" if str(r.get("trade_lead_min")) != "" else "not traded"
    lines = [f"# Tick burst detector review ({len(rows)} events)", ""]
    if rows:
        lines += table("All events", lambda r: "all") + table("By volume surge", vx) + table("By size of move", mv) + table("By direction", lambda r: str(r.get("direction")))
        lines += table("By hour", lambda r: str(r.get("time"))[:2]) + table("Traded by us or not", traded)
        leads = [x for x in (_f(r.get("trade_lead_min")) for r in rows) if x is not None]
        if leads:
            lines += [f"Detector fired a median {st.median(leads):.0f} minutes before our own entry (when we traded the stock; negative = after).", ""]
    return lines


def _price_source(root: Path) -> Callable[[str, str], tuple[list, dict] | None]:
    import strict_label as sl

    src = sl.Source(root)
    und = sl._underlyings(src, root)
    state: dict[str, Any] = {}

    def get(symbol: str, direction: str) -> tuple[list, dict] | None:
        ukey = und.get(symbol)
        if not ukey:
            return None
        day = state["day"]
        try:
            exps = [e for e in src.expiries(ukey) if e >= day]
            spot = state["spot"].get(symbol)
            ct = sl.pick_contract(src.contracts(ukey, exps[0], False), direction == "BULLISH", spot or 0.0)
            return (src.candles(ct["key"], day, False), ct) if ct else None
        except Exception:                                  # noqa: BLE001 - one stock failing must not stop the review
            return None
    get.state = state                                      # type: ignore[attr-defined]
    return get


def run(day: str, root: Path = ROOT, replay: bool = False) -> Path | None:
    import tick_detector

    path = root / "data" / "tick_events" / f"{day}.csv"
    if replay:
        events = tick_detector.replay(day, None, root)
    elif path.exists():
        with path.open(encoding="utf-8", newline="") as h:
            events = list(csv.DictReader(h))
    else:
        return None
    if not events:
        return None
    try:
        trades = json.loads((root / "data" / "reports" / "paper_trade_history.json").read_text(encoding="utf-8")).get("paper_trades") or []
    except (OSError, ValueError):
        trades = []
    get = _price_source(root)
    get.state["day"] = day
    get.state["spot"] = {}
    for e in events:                                       # the first event's price per stock is its spot for contract choice
        get.state["spot"].setdefault(e["symbol"], float(e["ltp"]))
    rows = review_events(events, day, get, trade_leads(trades, day))
    out = root / "data" / "tick_events" / f"review_{day}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    every: list[dict[str, Any]] = []
    for p in sorted((root / "data" / "tick_events").glob("review_*.csv")):
        with p.open(encoding="utf-8", newline="") as h:
            every += list(csv.DictReader(h))
    (root / "data" / "tick_events" / "summary.md").write_text("\n".join(summarise(every)) + "\n", encoding="utf-8")
    return out


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.path.insert(0, str(ROOT))
    out = run(args[0] if args else date.today().isoformat(), ROOT, "--replay" in sys.argv)
    print(out or "no events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
