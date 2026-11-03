"""Review of the results-reaction check (research only; no trading effect).

For every signal in data/strict_labels/ladder_replay.csv on a day with saved 5-minute candles, it works out what result_reaction.evaluate would have said AT THE SIGNAL TIME (results filings from
the announcement feed, volume / VWAP from the day's candles, previous close and the 20-day average volume from the NSE daily file) and groups the signals by it, next to how each one turned out
under the user's ladder, the old rules and holding to 15:25 (the ladder replay's columns, option returns after a 2.5 % cost).

    data/result_reaction/review.md        the tables
    data/result_reaction/review.csv       one row per signal with its reaction state

    python result_reaction_review.py
"""

from __future__ import annotations

import csv
import json
import statistics as st
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import result_reaction as rr

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def load_daily(root: Path) -> dict[str, list[tuple[str, float, float]]]:
    """symbol -> [(day, close, traded quantity)] ascending, from the NSE daily file."""
    out: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    try:
        with (root / "data" / "nse_daily" / "stock_daily.csv").open(encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                c, q = _f(r.get("close")), _f(r.get("ttl_qty"))
                if c and q is not None:
                    out[r["symbol"]].append((r["day"], c, q))
    except OSError:
        return {}
    for v in out.values():
        v.sort()
    return out


def state_at(symbol: str, day: str, ready: str, candles: Mapping[str, Any], daily: Mapping[str, list[tuple[str, float, float]]], filings: Mapping[str, list[datetime]]) -> dict[str, Any] | None:
    """The reaction state of one stock at a signal time, from the day's candles. None when there is not enough data."""
    c = (candles.get("symbols") or {}).get(symbol)
    rows = [x for x in daily.get(symbol, []) if x[0] < day]
    if not c or len(rows) < 10:
        return None
    ready_min = int(ready[:2]) * 60 + int(ready[3:5])
    idx = [i for i, m in enumerate(c["minute"]) if m + 5 <= ready_min]                 # bars completed when the signal was raised
    if not idx:
        return None
    cum_pv = cum_v = 0.0
    for i in idx:
        cum_pv += (c["high"][i] + c["low"][i] + c["close"][i]) / 3.0 * c["volume"][i]
        cum_v += c["volume"][i]
    now = datetime.fromisoformat(f"{day}T{ready}:00").replace(tzinfo=IST)
    age = rr.results_age_h(symbol, now, filings=filings)
    avg20 = st.mean(q for _d, _c, q in rows[-20:])
    return rr.evaluate(c["close"][idx[-1]], rows[-1][1], cum_v, avg20, cum_pv / cum_v if cum_v else 0.0, float(c.get("pdh") or 0), float(c.get("pdl") or 0), now, age)


def review(root: Path = ROOT) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with (root / "data" / "strict_labels" / "ladder_replay.csv").open(encoding="utf-8", newline="") as h:
            replay = list(csv.DictReader(h))
    except OSError:
        return []
    daily, filings = load_daily(root), rr.results_filings(root)
    cache: dict[str, Any] = {}
    for r in replay:
        day = r["day"]
        if day not in cache:
            try:
                cache[day] = json.loads((root / "data" / "pattern_log" / "candles" / f"{day}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cache[day] = None
        if not cache[day]:
            continue
        ev = state_at(r["symbol"], day, r["ready"], cache[day], daily, filings)
        if ev is None:
            continue
        results_out = ev["age_h"] is not None
        with_us = ev["direction"] == r["dir"]
        label = "reaction confirmed, with the signal" if ev["confirmed"] and with_us else "reaction confirmed, AGAINST the signal" if ev["confirmed"] else \
                "results out, no confirmed reaction" if results_out else "no results in the last 30h"
        rows.append({**{k: r[k] for k in ("day", "symbol", "dir", "group", "fate", "ready", "ladder_pct", "old_pct", "hold_pct")}, "state": label, "age_h": ev["age_h"] if results_out else "",
                     "rvol": ev["rvol"], "move_prev_pct": ev["move_prev_pct"], "vs_vwap_pct": ev["vs_vwap_pct"], "pd_break": ev["pd_break"]})
    return rows


def _stats(rows: Sequence[Mapping[str, Any]], key: str) -> tuple[int, int, float] | None:
    v = [x for x in (_f(r.get(key)) for r in rows) if x is not None]
    return (len(v), round(100 * sum(1 for x in v if x > 0) / len(v)), round(st.mean(v), 1)) if v else None


def summary(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    L = [f"# Results-reaction review ({len(rows)} signals, {len({r['day'] for r in rows})} days)", "",
         "Each signal is placed in one state using only what was known at its signal time. Returns are option returns after a 2.5% cost: the user's ladder, the old live rules, and holding to 15:25.", ""]

    def table(title: str, groups: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
        L.extend([f"## {title}", "", "| Group | Signals | Ladder win % / mean % | Old rules win % / mean % | Hold win % / mean % |", "|---|---|---|---|---|"])
        for g, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            a, b, c = _stats(rs, "ladder_pct"), _stats(rs, "old_pct"), _stats(rs, "hold_pct")
            if a:
                L.append(f"| {g} | {a[0]} | {a[1]}% / {a[2]:+} | {b[1] if b else '-'}% / {b[2] if b else '-'} | {c[1] if c else '-'}% / {c[2] if c else '-'} |")
        L.append("")

    def by(key: str, rows_: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
        d: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for r in rows_:
            d[str(r[key])].append(r)
        return d

    table("All signals, by reaction state", by("state", rows))
    for g in ("A+ late_vwap_extension", "V2 rank rule", "TRADED"):
        sub = [r for r in rows if r["group"] == g]
        if sub:
            table(f"Signals in the group '{g}', by reaction state", by("state", sub))
    hits = [r for r in rows if r["state"] == "reaction confirmed, with the signal"]
    L.extend(["## Every signal with a confirmed reaction on its side", "", "| Day | Stock | Side | Ready | What happened to it | RVOL | Move vs prev close | Ladder % | Hold % |", "|---|---|---|---|---|---|---|---|---|"])
    for r in sorted(hits, key=lambda x: (x["day"], x["ready"])):
        L.append(f"| {r['day']} | {r['symbol']} | {r['dir'][:4]} | {r['ready']} | {r['fate']} | {r['rvol']} | {r['move_prev_pct']:+} | {r['ladder_pct']} | {r['hold_pct']} |")
    return L


def main() -> int:
    rows = review(ROOT)
    out = ROOT / "data" / "result_reaction"
    out.mkdir(parents=True, exist_ok=True)
    if rows:
        with (out / "review.csv").open("w", encoding="utf-8", newline="") as h:
            w = csv.DictWriter(h, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    (out / "review.md").write_text("\n".join(summary(rows)) + "\n", encoding="utf-8")
    print(len(rows), "signals reviewed ->", out / "review.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
