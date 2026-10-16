"""Early-mover shadow list (research only; never trades, never touches the scanner).

Idea (16 Oct 2026): 89% of the stocks that moved 3%+ from their open were not traded, and the median stock still had 2.4% to go after its first +1%.
A stock is on the list at the first 5-minute decision point from 09:20 to 10:30 where ALL of these hold (from the saved 5-minute candles):

    - it is +1.0% to +2.5% from its open, in the direction of the trade (up = call, down = put); not yet stretched
    - volume burst: the biggest of its last 3 bars is 3x or more the median bar of the day so far
    - its sector (finer groups, sector_groups.py, 3+ stocks) is moving the same way by 0.5% or more from the open
For each signal the ATM option of the nearest expiry is priced from the signal candle (best / worst / close, and whether -20% came before +15%).

    data/shadow_rules/early_movers/<day>.csv     (rebuilt nightly from data/pattern_log/candles/<day>.json)
    data/shadow_rules/early_movers.md            (cumulative report; calls and puts separately)

The stock-only replay on 1-15 Oct showed no clear edge for the plain +1% rule (60-minute move about 0%), a small one for the strict version used here, so this
is a measurement, not a candidate. Bar: 30+ priced signals on 5+ days, positive mean option close and without the best day, 60%+ of days positive.
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
DECIDE_FROM, DECIDE_TO, STEP = 9 * 60 + 20, 10 * 60 + 30, 5
MOVE_LO, MOVE_HI, BURST_X, SECTOR_MIN = 1.0, 2.5, 3.0, 0.5
FIELDS = ["day", "symbol", "dir", "sector", "sector_move", "minute", "time", "price", "move_pct", "burst_x", "stock_fwd60_pct", "stock_to_close_pct",
          "contract", "strike", "opt_entry", "opt_best_pct", "opt_worst_pct", "opt_close_pct", "stop_first"]


def find_signals(symbols: dict[str, dict[str, Any]], sectors: dict[str, str]) -> list[dict[str, Any]]:
    first: dict[str, dict[str, Any]] = {}
    for T in range(DECIDE_FROM, DECIDE_TO + 1, STEP):
        idxs: dict[str, list[int]] = {}
        move: dict[str, float] = {}
        for s, d in symbols.items():
            idx = [i for i, m in enumerate(d.get("minute", [])) if m < T]
            if len(idx) < 2 or float(d["open"][0]) <= 0:
                continue
            idxs[s] = idx
            move[s] = (float(d["close"][idx[-1]]) / float(d["open"][0]) - 1.0) * 100.0
        groups: dict[str, list[float]] = defaultdict(list)
        for s, v in move.items():
            groups[sectors.get(s, "Other")].append(v)
        savg = {k: st.mean(v) for k, v in groups.items() if len(v) >= 3}
        for s, v in move.items():
            if s in first or not (MOVE_LO <= abs(v) <= MOVE_HI):
                continue
            sgn = 1 if v > 0 else -1
            sm = savg.get(sectors.get(s, "Other"))
            if sm is None or sgn * sm < SECTOR_MIN:
                continue
            d = symbols[s]
            vols = [float(d["volume"][i]) for i in idxs[s]]
            med = st.median(vols)
            if med <= 0 or max(vols[-3:]) < BURST_X * med:
                continue
            first[s] = {"symbol": s, "dir": "BULLISH" if sgn > 0 else "BEARISH", "sector": sectors.get(s, "Other"), "sector_move": round(sm, 2),
                        "minute": T, "price": round(float(d["close"][idxs[s][-1]]), 2), "move_pct": round(v, 2), "burst_x": round(max(vols[-3:]) / med, 1)}
    out = list(first.values())
    out.sort(key=lambda x: (x["minute"], x["symbol"]))
    return out


def stock_after(d: dict[str, Any], minute: int, bull: bool) -> tuple[float | None, float | None]:
    """(next-60-minute move, move to the close) in the trade's direction, %."""
    fwd = [i for i, m in enumerate(d.get("minute", [])) if m >= minute]
    if len(fwd) < 13:
        return None, None
    f0 = float(d["close"][fwd[0]])
    sgn = 1 if bull else -1
    return round(sgn * (float(d["close"][fwd[12]]) / f0 - 1) * 100, 3), round(sgn * (float(d["close"][-1]) / f0 - 1) * 100, 3)


def option_outcome(symbol: str, minute: int, price: float, day: str, bull: bool, fetch: Any = None, master: Any = None) -> dict[str, Any]:
    """ATM call (bull) / put of the nearest expiry at the signal: entry = close of the signal candle +1%, then best / worst / close and stop-first."""
    try:
        import pandas as pd

        if master is None:
            master = pd.read_csv(pc.ROOT / "data" / "cache" / "api-scrip-master-detailed.csv", low_memory=False,
                                 usecols=["SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL", "SM_EXPIRY_DATE", "STRIKE_PRICE", "OPTION_TYPE"])
        side = "CE" if bull else "PE"
        m = master[(master.UNDERLYING_SYMBOL == symbol) & (master.INSTRUMENT == "OPTSTK") & (master.OPTION_TYPE == side)].copy()
        m["exp"] = m.SM_EXPIRY_DATE.astype(str).str[:10]
        m = m[m.exp >= day]
        if m.empty:
            return {}
        m = m[m.exp == m.exp.min()].copy()
        m["d"] = (m.STRIKE_PRICE.astype(float) - price).abs()
        row = m.sort_values("d").iloc[0]
        bars = (fetch or pc._fetch_option_bars)(int(row.SECURITY_ID), day)
        at = [b for b in bars if b[0] <= minute]
        after = [b for b in bars if at and b[0] > at[-1][0]]
        if not at or len(after) < 3:
            return {}
        entry = at[-1][4] * 1.01
        if entry <= 0:
            return {}
        stop_first = False
        for b in after:
            if b[3] <= entry * 0.80:
                stop_first = True
                break
            if b[2] >= entry * 1.15:
                break
        return {"contract": f"{symbol} {int(float(row.STRIKE_PRICE)) if float(row.STRIKE_PRICE).is_integer() else row.STRIKE_PRICE} {side}",
                "strike": float(row.STRIKE_PRICE), "opt_entry": round(entry, 2),
                "opt_best_pct": round((max(b[2] for b in after) / entry - 1.0) * 100.0, 1),
                "opt_worst_pct": round((min(b[3] for b in after) / entry - 1.0) * 100.0, 1),
                "opt_close_pct": round((after[-1][4] / entry - 1.0) * 100.0, 1), "stop_first": bool(stop_first)}
    except Exception:                                      # noqa: BLE001 - the option half is an extra; the stock half still records
        return {}


def run(day: str | None = None, root: Path = ROOT, with_options: bool = True, symbols: dict[str, Any] | None = None) -> Path | None:
    day = day or date.today().isoformat()
    if symbols is None:
        try:
            symbols = json.loads((root / "data" / "pattern_log" / "candles" / f"{day}.json").read_text(encoding="utf-8")).get("symbols", {})
        except (OSError, ValueError):
            return None
    rows = []
    for s in find_signals(symbols, fine_map(pc.sector_map(root))):
        bull = s["dir"] == "BULLISH"
        fwd, end = stock_after(symbols[s["symbol"]], s["minute"], bull)
        row = {"day": day, **s, "time": f"{s['minute'] // 60:02d}:{s['minute'] % 60:02d}", "stock_fwd60_pct": fwd if fwd is not None else "",
               "stock_to_close_pct": end if end is not None else ""}
        if with_options:
            row.update(option_outcome(s["symbol"], s["minute"], s["price"], day, bull))
        rows.append(row)
    folder = root / "data" / "shadow_rules" / "early_movers"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.csv"
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    write_summary(root)
    return path


def _line(label: str, g: list[dict[str, Any]]) -> str:
    c = [pc._num(r["opt_close_pct"]) for r in g]
    b = [pc._num(r["opt_best_pct"]) for r in g]
    sf = sum(1 for r in g if str(r.get("stop_first")).lower() in ("true", "1"))
    days = defaultdict(list)
    for r, x in zip(g, c):
        days[r["day"]].append(x)
    return (f"| {label} | {len(g)} | {100 * sum(x > 0 for x in c) / len(c):.0f}% | {100 * sum(x >= 15 for x in b) / len(b):.0f}% | {100 * sf / len(g):.0f}% | "
            f"{st.mean(c):+.1f}% | {sum(1 for v in days.values() if st.mean(v) > 0)}/{len(days)} |")


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
    for p in sorted(glob.glob(str(root / "data" / "shadow_rules" / "early_movers" / "20*.csv"))):
        with open(p, encoding="utf-8", newline="") as h:
            rows.extend(csv.DictReader(h))
    if not rows:
        return None
    days = sorted({r["day"] for r in rows})
    priced = [r for r in rows if pc._num(r.get("opt_close_pct")) is not None]
    out = ["# Early-mover shadow list", "",
           f"{len(rows)} signals on {len(days)} day(s) ({days[0]} to {days[-1]}), {len(priced)} priced. Rule: +1.0% to +2.5% from the open in the trade's direction, "
           f"volume burst {BURST_X:g}x, sector the same way by {SECTOR_MIN:g}%+, first hit 09:20-10:30. ATM option bought at the signal candle, held to close, "
           "hindsight, before costs.", ""]
    if priced:
        head = "| Group | Priced | Closed up | Hit +15% | -20% first | Mean close | Days + |\n|---|---|---|---|---|---|---|"
        out += [head, _line("All", priced), _line("Calls", [r for r in priced if r["dir"] == "BULLISH"] or priced[:0]) if any(r["dir"] == "BULLISH" for r in priced) else "",
                _line("Puts", [r for r in priced if r["dir"] == "BEARISH"]) if any(r["dir"] == "BEARISH" for r in priced) else ""]
        out += ["", "| Day | Signals | Priced | Mean option close |", "|---|---|---|---|"]
        for d in days:
            g = [r for r in rows if r["day"] == d]
            gp = [r for r in g if pc._num(r.get("opt_close_pct")) is not None]
            m = st.mean(pc._num(r["opt_close_pct"]) for r in gp) if gp else None
            out.append(f"| {d} | {len(g)} | {len(gp)} | {(f'{m:+.1f}%' if m is not None else '-')} |")
    ok, why = verdict(priced)
    out += ["", f"**Verdict: {'supports adding it as a signal source' if ok else 'not yet'}.**" + ("" if ok else " Missing: " + "; ".join(why) + "."),
            "", "_Research only. Nothing here changes trading._", ""]
    path = root / "data" / "shadow_rules" / "early_movers.md"
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def main() -> int:
    import sys

    for d in sys.argv[1:] or [date.today().isoformat()]:
        print(d, run(d))
    print(write_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
