"""How do stocks and their options react around results / corporate events? (research only; changes nothing)

Why: the Q2 results season runs 17 Oct - 13 Nov 2026 (370 calendar events, 28 on Monday 19 Oct alone) and event stocks move more. The safety gate blocks trades on an
event day (CORPORATE_EVENT), so today we never trade the stocks that move most, and nothing in the history says how their options behave. The calendar file is overwritten
every day, so past events were lost. This keeps them and measures the reaction:

    archive()   copies data/safety/corporate_events.csv to data/event_calendar/<as_of>.csv every night (the history that was missing)
    run(day)    for every stock whose event date is `day` (D) or the previous trading day (D+1 = the morning after an after-hours result):
                gap % from the previous close, move from the open to the close, the day's high/low excursion, relative volume if known, and the ATM option's peak and
                close from 09:20 and from the stock's first +1% close (same measures as option_scan.py)

    data/shadow_rules/event_reaction/<day>.csv     data/shadow_rules/event_reaction.md
The report compares event stocks with all the other stocks of the same days, and splits "continued in the gap direction" from "faded". Questions it answers over the
season: does a gap on results continue or fade, which day (D or D+1) carries it, and are the options worth buying before the event or only after it (IV drops once the
result is out).

    python event_reaction_review.py [YYYY-MM-DD ...]
"""

from __future__ import annotations

import csv
import glob
import json
import shutil
import statistics as st
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable

import option_scan as osn
import put_continuation as pc
from sector_groups import fine_map

ROOT = Path(__file__).resolve().parent
FIELDS = ["day", "symbol", "offset", "event_date", "event_type", "gap_pct", "open_to_close_pct", "high_pct", "low_pct", "dir", "continued", "a_best_pct", "a_close_pct",
          "b_best_pct", "b_close_pct", "contract"]


def archive(root: Path = ROOT) -> Path | None:
    src = root / "data" / "safety" / "corporate_events.csv"
    if not src.exists():
        return None
    try:
        with src.open(encoding="utf-8-sig", newline="") as h:
            first = next(csv.DictReader(h), None)
    except OSError:
        return None
    as_of = (first or {}).get("as_of") or date.today().isoformat()
    dst = root / "data" / "event_calendar" / f"{as_of}.csv"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return dst


def load_events(root: Path = ROOT) -> dict[tuple[str, str], dict[str, str]]:
    """(symbol, event_date) -> row, from every archived calendar plus the current one (the newest snapshot wins)."""
    out: dict[tuple[str, str], dict[str, str]] = {}
    files = sorted(glob.glob(str(root / "data" / "event_calendar" / "20*.csv")))
    cur = root / "data" / "safety" / "corporate_events.csv"
    if cur.exists():
        files.append(str(cur))
    for p in files:
        try:
            with open(p, encoding="utf-8-sig", newline="") as h:
                for r in csv.DictReader(h):
                    if r.get("symbol") and r.get("event_date"):
                        out[(r["symbol"], r["event_date"])] = r
        except OSError:
            continue
    return out


def previous_trading_day(day: str, root: Path) -> str | None:
    days = sorted(Path(p).stem for p in glob.glob(str(root / "data" / "pattern_log" / "candles" / "20*.json")) if Path(p).stem < day)
    return days[-1] if days else None


def reaction_rows(day: str, symbols: dict[str, dict[str, Any]], prev_close: dict[str, float], events: dict[tuple[str, str], dict[str, str]], prev_day: str | None
                  ) -> list[dict[str, Any]]:
    rows = []
    for (sym, ed), ev in events.items():
        if ed == day:
            offset = "D"
        elif prev_day and ed == prev_day:
            offset = "D+1"
        else:
            continue
        d = symbols.get(sym)
        pc_ = prev_close.get(sym)
        if not d or not d.get("minute") or not pc_ or pc_ <= 0:
            continue
        o = float(d["open"][0])
        gap = (o / pc_ - 1.0) * 100.0
        hi, lo = max(float(x) for x in d["high"]), min(float(x) for x in d["low"])
        c = float(d["close"][-1])
        direction = "BULLISH" if gap >= 0 else "BEARISH"
        sg = 1 if gap >= 0 else -1
        cont = sg * (c / o - 1.0) * 100.0
        rows.append({"day": day, "symbol": sym, "offset": offset, "event_date": ed, "event_type": ev.get("event_type", ""), "gap_pct": round(gap, 2),
                     "open_to_close_pct": round((c / o - 1.0) * 100.0, 2), "high_pct": round((hi / o - 1.0) * 100.0, 2), "low_pct": round((lo / o - 1.0) * 100.0, 2),
                     "dir": direction, "continued": int(cont > 0)})
    return rows


def run(day: str, root: Path = ROOT, fetch: Callable[[int, str], list] = osn.fetch_bars, master: Any = None, with_options: bool = True) -> Path | None:
    cf = root / "data" / "pattern_log" / "candles" / f"{day}.json"
    try:
        symbols = json.loads(cf.read_text(encoding="utf-8")).get("symbols", {})
    except (OSError, ValueError):
        return None
    prev_day = previous_trading_day(day, root)
    prev_close: dict[str, float] = {}
    if prev_day:
        try:
            pv = json.loads((root / "data" / "pattern_log" / "candles" / f"{prev_day}.json").read_text(encoding="utf-8")).get("symbols", {})
            prev_close = {s: float(d["close"][-1]) for s, d in pv.items() if d.get("close")}
        except (OSError, ValueError):
            pass
    rows = reaction_rows(day, symbols, prev_close, load_events(root), prev_day)
    if rows and with_options:
        if master is None:
            import pandas as pd

            master = pd.read_csv(root / "data" / "cache" / "api-scrip-master-detailed.csv", low_memory=False,
                                 usecols=["SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL", "SM_EXPIRY_DATE", "STRIKE_PRICE", "OPTION_TYPE"])
        subset = {r["symbol"]: symbols[r["symbol"]] for r in rows}
        scan = {r["symbol"]: r for r in osn.scan_day(day, subset, fine_map(pc.sector_map(root)), [], set(), master, fetch)}
        for r in rows:
            s = scan.get(r["symbol"], {})
            for k in ("a_best_pct", "a_close_pct", "b_best_pct", "b_close_pct", "contract"):
                if s.get(k) not in (None, ""):
                    r[k] = s[k]
    folder = root / "data" / "shadow_rules" / "event_reaction"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.csv"
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    write_summary(root)
    return path


def _f(v: Any) -> float | None:
    try:
        return float(v) if v not in ("", None) else None
    except (TypeError, ValueError):
        return None


def _block(label: str, g: list[dict[str, Any]]) -> str:
    if not g:
        return f"| {label} | 0 | | | | | |"
    gaps = [abs(_f(r["gap_pct"]) or 0.0) for r in g]
    cont = 100 * sum(int(r["continued"]) for r in g) / len(g)
    best = [x for x in (_f(r.get("a_best_pct")) for r in g) if x is not None]
    close = [x for x in (_f(r.get("a_close_pct")) for r in g) if x is not None]
    return (f"| {label} | {len(g)} | {st.mean(gaps):.1f}% | {cont:.0f}% | {(f'{st.median(best):+.0f}%' if best else '-')} | "
            f"{(f'{st.mean(close):+.1f}%' if close else '-')} | {(f'{100 * sum(x >= 0 for x in close) / len(close):.0f}%' if close else '-')} |")


def write_summary(root: Path = ROOT) -> Path | None:
    rows: list[dict[str, Any]] = []
    for p in sorted(glob.glob(str(root / "data" / "shadow_rules" / "event_reaction" / "20*.csv"))):
        with open(p, encoding="utf-8", newline="") as h:
            rows.extend(csv.DictReader(h))
    if not rows:
        return None
    days = sorted({r["day"] for r in rows})
    out = ["# Results / event reaction (research only)", "",
           f"{len(rows)} event stock-days on {len(days)} day(s) ({days[0]} to {days[-1]}). D = the event date, D+1 = the next trading day (after-hours results). Gap = open vs previous close; "
           "'continued' = the stock closed beyond its open in the gap direction. Option measures: ATM option from 09:20 in the direction of the gap, held to close (hindsight, before costs).", "",
           "| Group | Stock-days | Mean gap | Continued | Median option peak | Mean option close | Option closed up |", "|---|---|---|---|---|---|---|",
           _block("All event stock-days", rows), _block("Event date (D)", [r for r in rows if r["offset"] == "D"]), _block("Day after (D+1)", [r for r in rows if r["offset"] == "D+1"]),
           _block("Gap 2%+ either way", [r for r in rows if abs(_f(r["gap_pct"]) or 0.0) >= 2.0]),
           _block("Gap up 2%+ (calls)", [r for r in rows if (_f(r["gap_pct"]) or 0.0) >= 2.0]),
           _block("Gap down 2%+ (puts)", [r for r in rows if (_f(r["gap_pct"]) or 0.0) <= -2.0]),
           _block("Small gap (under 1%)", [r for r in rows if abs(_f(r["gap_pct"]) or 0.0) < 1.0]), ""]
    by = defaultdict(list)
    for r in rows:
        by[r["day"]].append(r)
    out += ["| Day | Event stock-days | Mean |gap| | Continued |", "|---|---|---|---|"]
    for d in days:
        g = by[d]
        out.append(f"| {d} | {len(g)} | {st.mean(abs(_f(r['gap_pct']) or 0.0) for r in g):.1f}% | {100 * sum(int(r['continued']) for r in g) / len(g):.0f}% |")
    out += ["", "_The calendar gives the board-meeting date, not the release time, so D and D+1 both appear. The comparison with non-event stocks is in option_scan.md. Research only._", ""]
    path = root / "data" / "shadow_rules" / "event_reaction.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def main() -> int:
    import sys

    print("archived:", archive())
    for d in sys.argv[1:] or [date.today().isoformat()]:
        print(d, run(d), flush=True)
    print(write_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
