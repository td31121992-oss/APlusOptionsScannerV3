"""Falling-sector put leaders - shadow list (research only; never trades, never touches the scanner).

Idea (16 Oct 2026): when a whole sector is falling, the stocks leading the fall keep going. In a 1-15 Oct replay, scanner put signals whose sector was
0.5%+ below its open at the signal minute averaged +19.8% on the ATM option held to close (76% up, 5 of 7 days) and the top-3 fallers +24.0%; only
1 of 107 was traded because A+ / V2 held the rest back.

A stock is on the list at the first 5-minute decision point from 09:30 to 14:30 where ALL of these hold (sectors from `sector_groups.fine_sector`,
at least 3 stocks with data):
    - its sector's average move from the open is -0.5% or lower
    - the stock is one of the 3 biggest fallers of that sector and itself down at least 0.5% from its open
For each, the ATM put is priced from the signal candle (best / worst / close, and whether -20% came before +15%).

    data/shadow_rules/sector_leader_puts/<day>.csv     (rebuilt nightly from data/pattern_log/candles/<day>.json)
    data/shadow_rules/sector_leader_puts.md            (cumulative report with a fixed bar)

Bar: 30+ priced signals on 5+ days, mean close positive and still positive without the best day, 60%+ of days positive.
Anything less is "not yet". Signals cluster inside a few sector-days, so the report also shows the number of distinct sector-days.
"""

from __future__ import annotations

import csv
import glob
import json
import statistics as st
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import put_continuation as pc
from sector_groups import fine_map

ROOT = Path(__file__).resolve().parent
DECIDE_FROM, DECIDE_TO, STEP = 9 * 60 + 30, 14 * 60 + 30, 5
SECTOR_MAX, STOCK_MAX, TOP_N = -0.5, -0.5, 3
FIELDS = ["day", "symbol", "sector", "sector_move", "rank", "minute", "time", "price", "move_pct", "stock_fwd60_pct", "stock_mfe60_pct", "contract",
          "strike", "opt_entry", "opt_best_pct", "opt_worst_pct", "opt_close_pct", "stop_first"]


def find_signals(symbols: dict[str, dict[str, Any]], sectors: dict[str, str]) -> list[dict[str, Any]]:
    """First qualifying decision point per stock for one day. `symbols` is the saved candles file's "symbols" mapping."""
    first: dict[str, dict[str, Any]] = {}
    for T in range(DECIDE_FROM, DECIDE_TO + 1, STEP):
        move: dict[str, float] = {}
        price: dict[str, float] = {}
        for s, d in symbols.items():
            idx = [i for i, m in enumerate(d.get("minute", [])) if m < T]
            if len(idx) < 3:
                continue
            move[s] = (d["close"][idx[-1]] / d["open"][idx[0]] - 1.0) * 100.0
            price[s] = d["close"][idx[-1]]
        groups: dict[str, list[str]] = defaultdict(list)
        for s in move:
            groups[sectors.get(s, "Other")].append(s)
        for k, members in groups.items():
            if len(members) < 3:
                continue
            avg = st.mean(move[s] for s in members)
            if avg > SECTOR_MAX:
                continue
            ranked = sorted(members, key=lambda s: move[s])
            for pos, s in enumerate(ranked[:TOP_N]):
                if s in first or move[s] > STOCK_MAX:
                    continue
                first[s] = {"symbol": s, "sector": k, "sector_move": round(avg, 2), "rank": pos + 1, "minute": T, "price": round(price[s], 2),
                            "move_pct": round(move[s], 2)}
    out = list(first.values())
    out.sort(key=lambda x: (x["minute"], x["symbol"]))
    return out


def run(day: str | None = None, root: Path = ROOT, with_options: bool = True, symbols: dict[str, Any] | None = None) -> Path | None:
    day = day or date.today().isoformat()
    if symbols is None:
        try:
            symbols = json.loads((root / "data" / "pattern_log" / "candles" / f"{day}.json").read_text(encoding="utf-8")).get("symbols", {})
        except (OSError, ValueError):
            return None
    rows = []
    for s in find_signals(symbols, fine_map(pc.sector_map(root))):
        fwd, mfe = pc.stock_forward(symbols[s["symbol"]], s["minute"])
        row = {"day": day, **s, "time": f"{s['minute'] // 60:02d}:{s['minute'] % 60:02d}", "stock_fwd60_pct": fwd if fwd is not None else "",
               "stock_mfe60_pct": mfe if mfe is not None else ""}
        if with_options:
            row.update(pc.option_outcome(s["symbol"], s["minute"], s["price"], day))
        rows.append(row)
    folder = root / "data" / "shadow_rules" / "sector_leader_puts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.csv"
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    write_summary(root)
    return path


def verdict(priced: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    why = []
    if len(priced) < 30:
        why.append(f"{len(priced)} of 30 priced signals")
    days = defaultdict(list)
    for r in priced:
        days[r["day"]].append(pc._num(r["opt_close_pct"]))
    if len(days) < 5:
        why.append(f"{len(days)} of 5 days")
    if days:
        pos = sum(1 for v in days.values() if st.mean(v) > 0)
        if pos / len(days) < 0.6:
            why.append(f"only {pos} of {len(days)} days positive")
        best = max(days, key=lambda d: sum(days[d]))
        rest = [pc._num(r["opt_close_pct"]) for r in priced if r["day"] != best]
        if rest and st.mean(rest) <= 0:
            why.append(f"not positive after removing {best}")
    if priced and st.mean(pc._num(r["opt_close_pct"]) for r in priced) <= 0:
        why.append("mean close not positive")
    return (not why and bool(priced)), why


def write_summary(root: Path = ROOT) -> Path | None:
    rows: list[dict[str, Any]] = []
    for p in sorted(glob.glob(str(root / "data" / "shadow_rules" / "sector_leader_puts" / "20*.csv"))):
        with open(p, encoding="utf-8", newline="") as h:
            rows.extend(csv.DictReader(h))
    if not rows:
        return None
    priced = [r for r in rows if pc._num(r.get("opt_close_pct")) is not None]
    days = sorted({r["day"] for r in rows})
    out = ["# Falling-sector put leaders (shadow list)", "",
           f"{len(rows)} signals on {len(days)} day(s) ({days[0]} to {days[-1]}), {len({(r['day'], r['sector']) for r in rows})} distinct sector-days. "
           "Rule: sector 0.5%+ below open, stock among its 3 biggest fallers and 0.5%+ down, first hit 09:30-14:30. ATM put bought at the signal candle, "
           "held to close, hindsight, before costs.", ""]
    if priced:
        c = [pc._num(r["opt_close_pct"]) for r in priced]
        b = [pc._num(r["opt_best_pct"]) for r in priced]
        sf = sum(1 for r in priced if str(r.get("stop_first")).lower() in ("true", "1"))
        out += [f"**Option:** {len(priced)} priced; closed up {100 * sum(x > 0 for x in c) / len(c):.0f}%, reached +15% {100 * sum(x >= 15 for x in b) / len(b):.0f}%, "
                f"+30% {100 * sum(x >= 30 for x in b) / len(b):.0f}%, -20% first {100 * sf / len(priced):.0f}%, mean close {st.mean(c):+.1f}%.", ""]
    out += ["| Day | Signals | Priced | Closed up | Mean option close |", "|---|---|---|---|---|"]
    for d in days:
        g = [r for r in rows if r["day"] == d]
        go = [r for r in g if pc._num(r.get("opt_close_pct")) is not None]
        m = st.mean(pc._num(r["opt_close_pct"]) for r in go) if go else None
        up = f"{round(100 * sum(pc._num(r['opt_close_pct']) > 0 for r in go) / len(go))}%" if go else "-"
        out.append(f"| {d} | {len(g)} | {len(go)} | {up} | {(f'{m:+.1f}%' if m is not None else '-')} |")
    by_sec = defaultdict(list)
    for r in priced:
        by_sec[r["sector"]].append(pc._num(r["opt_close_pct"]))
    out += ["", "| Sector | Priced | Mean close |", "|---|---|---|"]
    out += [f"| {k} | {len(v)} | {st.mean(v):+.1f}% |" for k, v in sorted(by_sec.items(), key=lambda kv: -len(kv[1]))]
    ok, why = verdict(priced)
    out += ["", f"**Verdict: {'supports adding it as a signal source' if ok else 'not yet'}.**" + ("" if ok else " Missing: " + "; ".join(why) + "."),
            "", "_Research only. Nothing here changes trading._", ""]
    path = root / "data" / "shadow_rules" / "sector_leader_puts.md"
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def main() -> int:
    import sys

    days = sys.argv[1:] or [date.today().isoformat()]
    for d in days:
        print(d, run(d))
    print(write_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
