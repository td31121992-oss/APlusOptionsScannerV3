"""Big movers we did not trade - nightly report (research only; changes nothing).

A "big mover" is an F&O stock that moved 3% or more from its open in one direction during the day (day high for up, day low for down,
whichever is larger). For each one this records

    mark1 / mark2    the first 5-minute close at +1% / +2% from the open in that direction (time), the earliest point a trend entry could have been judged
    left_after_1     how much further it still went from the +1% mark to the day's extreme, in %
    outcome          TRADED            we traded that stock that day in the same direction
                     NO_SIGNAL         the scanner never marked it entry-ready (in that direction)
                     V2_BLOCKED / A_PLUS:<rule> / CONVERSION_BLOCKED:<why>   a signal existed and was held back, with the first such signal's time
    lag_min          first signal time minus the +1% mark time (blank when there was no signal)

Each night `run()` writes data/shadow_rules/big_movers/<day>.csv from the saved 5-minute candles (data/pattern_log/candles/<day>.json), the day's
option_returns.json (the signal list with its fate) and the paper-trade history, and `write_summary()` rebuilds data/shadow_rules/big_movers.md.

    python big_movers_review.py [YYYY-MM-DD ...]
"""

from __future__ import annotations

import csv
import glob
import json
import statistics as st
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
BIG_PCT = 3.0
MIN_BARS = 40
FIELDS = ["day", "symbol", "dir", "move_pct", "close_pct", "mark1", "mark2", "left_after_1", "outcome", "first_signal", "lag_min", "traded"]


def _hm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _mins(h: str) -> int:
    a, b = str(h).split(":")[:2]
    return int(a) * 60 + int(b)


def find_movers(symbols: dict[str, dict[str, Any]], big_pct: float = BIG_PCT) -> list[dict[str, Any]]:
    out = []
    for s, d in symbols.items():
        m = d.get("minute") or []
        if len(m) < MIN_BARS:
            continue
        o = float(d["open"][0])
        hi, lo = max(float(x) for x in d["high"]), min(float(x) for x in d["low"])
        if o <= 0:
            continue
        up, dn = (hi / o - 1) * 100, (1 - lo / o) * 100
        if max(up, dn) < big_pct:
            continue
        sgn = 1 if up >= dn else -1
        ext = hi if sgn > 0 else lo
        marks: dict[int, tuple[int, float]] = {}
        for minute, c in zip(m, d["close"]):
            mv = sgn * (float(c) / o - 1) * 100
            for lvl in (1, 2):
                if lvl not in marks and mv >= lvl:
                    marks[lvl] = (int(minute), float(c))
        row = {"symbol": s, "dir": "BULLISH" if sgn > 0 else "BEARISH", "move_pct": round(max(up, dn), 2),
               "close_pct": round(sgn * (float(d["close"][-1]) / o - 1) * 100, 2),
               "mark1": _hm(marks[1][0]) if 1 in marks else "", "mark2": _hm(marks[2][0]) if 2 in marks else "",
               "left_after_1": round(sgn * (ext / marks[1][1] - 1) * 100, 2) if 1 in marks else "", "_mark1_min": marks[1][0] if 1 in marks else None}
        out.append(row)
    out.sort(key=lambda r: -r["move_pct"])
    return out


def classify(movers: list[dict[str, Any]], signals: list[dict[str, Any]], traded: set[tuple[str, str]]) -> list[dict[str, Any]]:
    """signals: option_returns rows (kind ATM) of the day; traded: {(symbol, 'BULLISH'|'BEARISH')} actually traded that day."""
    first: dict[tuple[str, str], dict[str, Any]] = {}
    for r in sorted(signals, key=lambda x: str(x.get("ready"))):
        first.setdefault((r["symbol"], r.get("dir")), r)
    rows = []
    for m in movers:
        key = (m["symbol"], m["dir"])
        sig = first.get(key)
        is_traded = key in traded or (sig is not None and str(sig.get("fate")) == "TRADED")
        lag = ""
        if sig is not None and m.get("_mark1_min") is not None:
            lag = _mins(sig["ready"]) - m["_mark1_min"]
        outcome = "TRADED" if is_traded else (str(sig["fate"]).split(":")[0] + (":" + str(sig["fate"]).split(":", 1)[1] if ":" in str(sig["fate"]) else "") if sig else "NO_SIGNAL")
        rows.append({**{k: v for k, v in m.items() if not k.startswith("_")}, "outcome": outcome, "first_signal": sig["ready"] if sig else "",
                     "lag_min": lag, "traded": int(is_traded)})
    return rows


def _traded_set(day: str, root: Path) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for name in ("paper_trade_history.json", "paper_trades_latest.json"):
        try:
            data = json.loads((root / "data" / "reports" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for t in data.get("paper_trades", []) if isinstance(data, dict) else data:
            if str(t.get("entry_time") or "")[:10] == day:
                out.add((str(t.get("symbol")), "BULLISH" if str(t.get("option_type")).upper() == "CE" else "BEARISH"))
    return out


def run(day: str | None = None, root: Path = ROOT, symbols: dict[str, Any] | None = None) -> Path | None:
    day = day or date.today().isoformat()
    if symbols is None:
        try:
            symbols = json.loads((root / "data" / "pattern_log" / "candles" / f"{day}.json").read_text(encoding="utf-8")).get("symbols", {})
        except (OSError, ValueError):
            return None
    try:
        sigs = [r for r in json.loads((root / "data" / "missed_opportunities" / day / "option_returns.json").read_text(encoding="utf-8")) if r.get("kind") == "ATM"]
    except (OSError, ValueError):
        sigs = []
    rows = classify(find_movers(symbols), sigs, _traded_set(day, root))
    folder = root / "data" / "shadow_rules" / "big_movers"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.csv"
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({"day": day, **r})
    write_summary(root)
    return path


def _f(v: Any) -> float | None:
    try:
        return float(v) if v not in ("", None) else None
    except (TypeError, ValueError):
        return None


def write_summary(root: Path = ROOT) -> Path | None:
    rows: list[dict[str, Any]] = []
    for p in sorted(glob.glob(str(root / "data" / "shadow_rules" / "big_movers" / "20*.csv"))):
        with open(p, encoding="utf-8", newline="") as h:
            rows.extend(csv.DictReader(h))
    if not rows:
        return None
    days = sorted({r["day"] for r in rows})
    n = len(rows)
    traded = sum(int(r["traded"]) for r in rows)
    kinds = Counter((r["outcome"].split(":")[0]) for r in rows)
    out = ["# Big movers we did not trade (research only)", "",
           f"{n} stocks moved {BIG_PCT:g}%+ from their open in one direction on {len(days)} day(s) ({days[0]} to {days[-1]}). "
           f"We traded {traded} ({100 * traded / n:.0f}%); {n - traded} were not traded.", "",
           "| Outcome | Stocks | Share |", "|---|---|---|"]
    for k, v in kinds.most_common():
        out.append(f"| {k} | {v} | {100 * v / n:.0f}% |")
    left = [x for x in (_f(r["left_after_1"]) for r in rows) if x is not None]
    lags = [x for x in (_f(r["lag_min"]) for r in rows) if x is not None]
    if left:
        out += ["", f"After the first close at +1% from the open, the median stock still moved another **{st.median(left):.2f}%** to its day extreme "
                    f"({100 * sum(1 for x in left if x >= 1.5) / len(left):.0f}% had 1.5%+ left)."]
    if lags:
        out.append(f"Where a scanner signal existed, it came a median **{st.median(lags):.0f} min** after the +1% mark "
                   f"({100 * sum(1 for x in lags if x <= 0) / len(lags):.0f}% were at or before it).")
    out += ["", "## By day", "", "| Day | Movers | Traded | Signal but held back | No signal |", "|---|---|---|---|---|"]
    for d in days:
        g = [r for r in rows if r["day"] == d]
        t = sum(int(r["traded"]) for r in g)
        ns = sum(1 for r in g if r["outcome"] == "NO_SIGNAL")
        out.append(f"| {d} | {len(g)} | {t} | {len(g) - t - ns} | {ns} |")
    held = Counter(r["outcome"] for r in rows if r["outcome"] not in ("TRADED", "NO_SIGNAL"))
    if held:
        out += ["", "## What held the signals back", "", "| Reason | Stocks |", "|---|---|"]
        out += [f"| {k} | {v} |" for k, v in held.most_common(12)]
    last = [r for r in rows if r["day"] == days[-1] and not int(r["traded"])][:12]
    if last:
        out += ["", f"## Biggest not traded on {days[-1]}", "", "| Stock | Way | Move | +1% mark | Left after it | Outcome | First signal |", "|---|---|---|---|---|---|---|"]
        out += [f"| {r['symbol']} | {r['dir'].title()} | {r['move_pct']}% | {r['mark1'] or '-'} | {r['left_after_1'] or '-'}% | {r['outcome']} | {r['first_signal'] or '-'} |" for r in last]
    out += ["", "_Hindsight list: a stock that moved 3% by the close is easy to spot afterwards. Research only; nothing here changes trading._", ""]
    path = root / "data" / "shadow_rules" / "big_movers.md"
    path.parent.mkdir(parents=True, exist_ok=True)
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
