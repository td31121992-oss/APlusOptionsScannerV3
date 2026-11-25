"""Shadow book of the setups the gates held back, priced as OPTION trades (RESEARCH ONLY - places and changes no trade). python held_shadow_book.py [first_day]

Input: data/held_signal_options/<day>.csv.gz (written by held_signal_recorder.py: bid / ask / last price once a minute for the first signal of each stock and side). Every tracked signal becomes
ONE virtual trade of one lot:

    contract   first strike in the money (what most real trades use); the at-the-money strike is reported beside it
    entry      the ASK of the first minute at or after the signal (no price within 5 minutes = not counted)
    stop       20% under the entry; targets +20% / +35% / +50% (risk x 1.0 / 1.75 / 2.5, as the live selector sets them)
    exits      the live rules: initial stop, T1 -> cost, T2 -> +8%, T3 -> runner (+15% floor / 70% of the peak gain); the stop is compared with the last price and FILLS at the bid
    end        a trade still open at the last recorded minute (15:20) is closed at the bid
    costs      trade_costs.round_trip_costs

Not covered: the live exits that need the stock's price, and moves inside a minute (a real stop can trigger on a tick this record never saw).

THE PASS MARK, fixed on 25 Nov 2026 before any result, for the narrow release (bullish, LATE_VWAP_EXTENSION or LATE_10M_OVERHEAT, first signal before 10:30):
at least 10 sessions and 100 trades; net above zero; 60% or more of days positive; still above zero without its 5 best trades; average per trade above the PASSED signals priced the same way.
A pass is a reason to ask, never to switch anything on by itself.

Writes data/shadow_rules/held_shadow_book.md and .csv.
"""

from __future__ import annotations

import csv
import gzip
import sys
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from exit_scoreboard import floor_for
from trade_costs import round_trip_costs

ROOT = Path(__file__).resolve().parent
FIRST_DAY = "2026-11-25"
STOP_PCT = 20.0
TARGET_RR = (1.0, 1.75, 2.5)
MAX_ENTRY_DELAY_S = 300
SESSION_DONE = "15:18:00"
NARROW_STATUSES = ("A_PLUS_WAIT_LATE_VWAP_EXTENSION", "A_PLUS_WAIT_LATE_10M_OVERHEAT")
NARROW_BEFORE = "10:30"
MIN_SESSIONS, MIN_TRADES, POSITIVE_DAYS_SHARE, TOP_N = 10, 100, 0.6, 5


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def read_day(path: Path) -> list[dict[str, str]]:
    """Rows of one day's file. The recorder may be appending to it: keep whatever can be read."""
    rows: list[dict[str, str]] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                rows.append(r)
    except (OSError, EOFError, zlib.error):
        pass
    return rows


def simulate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """One virtual trade from one contract's rows (time order). None when there is no usable price near the signal."""
    if not rows:
        return None
    signal = datetime.fromisoformat(str(rows[0]["signal_time"])[:19])
    start, entry, spread = None, 0.0, 0.0
    for i, r in enumerate(rows):
        at = datetime.fromisoformat(str(r["captured_at"])[:19])
        delay = (at - signal).total_seconds()
        if delay < 0:
            continue
        if delay > MAX_ENTRY_DELAY_S:
            return None
        ask, bid = _f(r.get("ask")), _f(r.get("bid"))
        if ask > 0 and bid > 0 and ask >= bid:
            start, entry, spread, entry_at = i, ask, (ask - bid) / ask * 100.0, at
            break
    if start is None:
        return None
    stop0 = entry * (1.0 - STOP_PCT / 100.0)
    targets = tuple(entry + (entry - stop0) * rr for rr in TARGET_RR)
    high, last_bid, last_at, how = entry, _f(rows[start].get("bid")), entry_at, "open"
    for r in rows[start + 1:]:
        bid = _f(r.get("bid"))
        price = _f(r.get("ltp")) or bid
        if price <= 0 or bid <= 0:
            continue
        last_bid, last_at = bid, datetime.fromisoformat(str(r["captured_at"])[:19])
        high = max(high, price)
        if price <= max(stop0, floor_for("old_rules", entry, high, targets)):
            how = "stop"
            break
    if how == "open" and last_at.strftime("%H:%M:%S") >= SESSION_DONE:
        how = "end"
    lot = int(_f(rows[start].get("lot")))
    if lot <= 0:
        return None
    gross = (last_bid - entry) * lot
    return {"entry_time": entry_at.isoformat(), "entry": entry, "exit": last_bid, "exit_time": last_at.isoformat(), "how": how, "spread_pct": round(spread, 2), "lot": lot,
            "mfe_pct": round((high / entry - 1.0) * 100.0, 1), "net": round(gross - round_trip_costs(entry, last_bid, lot)["total"], 2)}


def day_trades(rows: Sequence[Mapping[str, Any]], day: str) -> list[dict[str, Any]]:
    by: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for r in rows:
        by.setdefault((r["symbol"], r["direction"], r["kind"]), []).append(r)
    out = []
    for (symbol, direction, kind), lst in by.items():
        lst.sort(key=lambda r: str(r["captured_at"]))
        res = simulate(lst)
        if res is None:
            continue
        first = lst[0]
        out.append({"day": day, "symbol": symbol, "direction": direction, "kind": kind, "group": first["group"], "status": first["status"], "signal_time": first["signal_time"],
                    "strike": first["strike"], **res})
    return out


def is_narrow(t: Mapping[str, Any]) -> bool:
    return t["direction"] == "BULLISH" and t["status"] in NARROW_STATUSES and str(t["signal_time"])[11:16] < NARROW_BEFORE


def stats(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    per_day: dict[str, float] = {}
    for t in trades:
        per_day[t["day"]] = per_day.get(t["day"], 0.0) + t["net"]
    n, net = len(trades), sum(t["net"] for t in trades)
    best = sorted((t["net"] for t in trades), reverse=True)[:TOP_N]
    return {"n": n, "net": net, "avg": net / n if n else 0.0, "win": 100.0 * sum(1 for t in trades if t["net"] > 0) / n if n else 0.0, "days": len(per_day),
            "days_pos": sum(1 for v in per_day.values() if v > 0), "without_top": net - sum(best), "per_day": per_day}


def verdict(narrow: Mapping[str, Any], passed: Mapping[str, Any]) -> str:
    if narrow["days"] < MIN_SESSIONS or narrow["n"] < MIN_TRADES:
        return f"COLLECTING ({narrow['days']} of {MIN_SESSIONS} sessions, {narrow['n']} of {MIN_TRADES} trades)"
    failed = [why for why, ok in (("net is not above zero", narrow["net"] > 0),
                                  ("fewer than 60% of days positive", narrow["days_pos"] >= POSITIVE_DAYS_SHARE * narrow["days"]),
                                  (f"not above zero without its {TOP_N} best trades", narrow["without_top"] > 0),
                                  ("average not above the PASSED signals", narrow["avg"] > passed["avg"])) if not ok]
    return "PASSES the pass mark (ask before enabling anything)" if not failed else "FAILS: " + "; ".join(failed)


def cohorts(trades: Sequence[Mapping[str, Any]]) -> list[tuple[str, list[Mapping[str, Any]]]]:
    ext = [t for t in trades if t["group"] == "EXTENDED_WAIT"]
    out = [("PASSED all gates (comparison)", [t for t in trades if t["group"] == "PASSED"]),
           ("NARROW release (the test)", [t for t in ext if is_narrow(t)]),
           ("  narrow, entry spread 1% or less (information only)", [t for t in ext if is_narrow(t) and t["spread_pct"] <= 1.0]),
           ("All extended waits", ext),
           ("  bullish", [t for t in ext if t["direction"] == "BULLISH"]),
           ("  bearish", [t for t in ext if t["direction"] == "BEARISH"]),
           (f"  signal before {NARROW_BEFORE}", [t for t in ext if str(t["signal_time"])[11:16] < NARROW_BEFORE]),
           (f"  signal {NARROW_BEFORE} or later", [t for t in ext if str(t["signal_time"])[11:16] >= NARROW_BEFORE])]
    for status in sorted({t["status"] for t in ext}):
        out.append((f"  {status.replace('A_PLUS_WAIT_', '')}", [t for t in ext if t["status"] == status]))
    out += [("Other A+ waits", [t for t in trades if t["group"] == "OTHER_WAIT"]), ("V2 stock-selection blocks", [t for t in trades if t["group"] == "V2_BLOCK"])]
    return out


def render(trades: Sequence[Mapping[str, Any]]) -> str:
    itm = [t for t in trades if t["kind"] == "ITM1"]
    atm = [t for t in trades if t["kind"] == "ATM"]
    days = sorted({t["day"] for t in trades})
    groups = dict(cohorts(itm))
    out = ["# Held-back signals as option trades (shadow book)", "",
           f"Days: {len(days)} ({days[0] if days else '-'} to {days[-1] if days else '-'}). One lot, bought at the ask, live exit rules, sold at the bid, costs charged. "
           f"{sum(1 for t in itm if t['how'] == 'open')} trades are still open and marked at the latest bid.", "",
           f"**Narrow release: {verdict(stats(groups['NARROW release (the test)']), stats(groups['PASSED all gates (comparison)']))}**", "",
           f"| Group (first strike in the money) | Trades | Net Rs | Avg Rs | Win % | Positive days | Net without {TOP_N} best | ATM strike net |", "|---|---|---|---|---|---|---|---|"]
    atm_groups = dict(cohorts(atm))
    for label, lst in cohorts(itm):
        s = stats(lst)
        out.append(f"| {label} | {s['n']} | {s['net']:+,.0f} | {s['avg']:+,.0f} | {s['win']:.0f} | {s['days_pos']} of {s['days']} | {s['without_top']:+,.0f} | {stats(atm_groups.get(label, []))['net']:+,.0f} |")
    out += ["", "## By day (first strike in the money)", "", "| Day | Passed | Narrow | All extended |", "|---|---|---|---|"]
    cols = [stats(groups[k])["per_day"] for k in ("PASSED all gates (comparison)", "NARROW release (the test)", "All extended waits")]
    for day in days:
        out.append(f"| {day} | " + " | ".join(f"{c.get(day, 0.0):+,.0f}" for c in cols) + " |")
    out += ["", "_Prices are sampled once a minute, so real stops can differ. Passed signals here are not your real trades: they are every passed signal, priced by the same simple rules._", ""]
    return "\n".join(out)


def build(first_day: str = FIRST_DAY, root: Path = ROOT) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    for path in sorted((root / "data" / "held_signal_options").glob("*.csv.gz")):
        day = path.name[:10]
        if day >= first_day:
            trades += day_trades(read_day(path), day)
    return trades


def write(first_day: str = FIRST_DAY, root: Path = ROOT) -> Path:
    trades = build(first_day, root)
    folder = root / "data" / "shadow_rules"
    folder.mkdir(parents=True, exist_ok=True)
    if trades:
        with (folder / "held_shadow_book.csv").open("w", encoding="utf-8", newline="") as h:
            w = csv.DictWriter(h, fieldnames=list(trades[0]))
            w.writeheader()
            w.writerows(trades)
    path = folder / "held_shadow_book.md"
    path.write_text(render(trades), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write(sys.argv[1] if len(sys.argv) > 1 else FIRST_DAY).read_text(encoding="utf-8"))
