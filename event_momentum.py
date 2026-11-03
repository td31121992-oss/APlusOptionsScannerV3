"""Event-day momentum: a candidate that is moving WITH a high-volume event move (SHADOW ONLY: tags and a nightly review; nothing here allows, blocks or sizes a trade).

The problem (found 24 Oct, Swiggy 23 Oct): on a results / news day the stock gaps, trades on 10-45x its normal volume and keeps going. The scanner holds exactly these back with its "too late"
rules (A_PLUS_WAIT_LATE_10M_OVERHEAT, ..._VWAP_EXTENSION, ..._SESSION_EXTENSION, pivot_to_r1), because for an ordinary stock a move that has already run is a poor entry. Across 1,752 signals those
late blocks made no difference on average (+0.9 % vs +0.8 % mean option return at the close), but the few event-day continuations are the 100 %+ option moves the user sees every day.
On the 7 days with an event log, signals that agreed with a 8x+ volume event move returned +53 % at the close on average (10 signals, 40 % reached +100 %), against +0.8 % for all signals.
That is a small, hindsight sample, so this only measures it, forward, before anyone changes a rule.

    em_core      1 when relative volume >= CORE_RVOL (8x usual for the time of day) AND the stock is at least CORE_MOVE (2 %) from the previous close in the trade's direction
    em_loose     1 when relative volume >= LOOSE_RVOL (5x) AND at least LOOSE_MOVE (3 %) with the direction
    em_rvol, em_move_dir, em_gap_dir     the numbers (move and gap shown in OUR direction, positive = with the trade)
    em_blocked   1 when the candidate was held back by a rule at the time (status other than passed): the case this exists for

The nightly review (data/event_momentum/review.md) rebuilds the flags from data/signal_snapshots (every entry-ready candidate, blocked or not, with the features it was judged on, from 19 Oct) and joins
each to the option outcome in data/missed_opportunities (the ATM option from the signal's first-ready time: best, worst, close, and whether a -20 % stop came first). Groups: event momentum that WAS
blocked, event momentum that passed, loose, everything else. Rows dated after the first review (data/event_momentum/registered.json) are shown separately as forward evidence.

    python event_momentum.py [YYYY-MM-DD]      write the review (default today)
"""

from __future__ import annotations

import csv
import glob
import json
import os
import statistics as st
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
CORE_RVOL, CORE_MOVE = 8.0, 2.0
LOOSE_RVOL, LOOSE_MOVE = 5.0, 3.0
PASSED = ("PASSED_ALL_GATES", "TRADED")
MIN_N = 15


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def evaluate(rel_volume: Any, day_change_pct: Any, gap_pct: Any, direction: str, status: str = "") -> dict[str, Any]:
    """The em_ fields for one candidate. {} when the volume or the move is missing."""
    rv, mv, gp = _f(rel_volume), _f(day_change_pct), _f(gap_pct)
    if rv is None or mv is None:
        return {}
    sign = 1.0 if str(direction).upper() == "BULLISH" else -1.0
    move = sign * mv
    out = {"em_core": int(rv >= CORE_RVOL and move >= CORE_MOVE), "em_loose": int(rv >= LOOSE_RVOL and move >= LOOSE_MOVE), "em_rvol": round(rv, 1), "em_move_dir": round(move, 2)}
    if gp is not None:
        out["em_gap_dir"] = round(sign * gp, 2)
    if status:
        out["em_blocked"] = int(status not in PASSED)
    return out


def tags(record: Mapping[str, Any], direction: str) -> dict[str, Any]:
    """Shadow tags for a candidate's record (the scanner's candidate dict: relative_volume, day_change_percent, gap_percent)."""
    try:
        return evaluate(record.get("relative_volume"), record.get("day_change_percent"), record.get("gap_percent"), direction)
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}


# --- nightly review ---------------------------------------------------------------------------------------------------------------------------------------------------------------
def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return round(100 * max(0.0, c - h)), round(100 * min(1.0, c + h))


def _ladder(root: Path) -> dict[tuple[str, str, str], float]:
    """The ladder-replay result (data/strict_labels/ladder_replay.csv: the signal's option on real 1-minute prices under the user's ladder and the -20 % stop, costs included), earliest signal per stock, side and day."""
    out: dict[tuple[str, str, str], float] = {}
    try:
        with (root / "data" / "strict_labels" / "ladder_replay.csv").open(encoding="utf-8", newline="") as h:
            for r in sorted(csv.DictReader(h), key=lambda r: str(r.get("ready"))):
                v = _f(r.get("ladder_pct"))
                if v is not None:
                    out.setdefault((r["day"], r["symbol"], r["dir"]), v)
    except OSError:
        pass
    return out


def _load(root: Path, upto: str | None) -> list[dict[str, Any]]:
    """One row per (day, symbol, direction): the first time the candidate was em_core (else em_loose, else its first row), joined to its ATM option outcome."""
    snaps: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for f in sorted(glob.glob(str(root / "data" / "signal_snapshots" / "2026-*.csv"))):
        day = os.path.basename(f)[:10]
        if "chain" in f or (upto and day > upto):
            continue
        with open(f, encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                snaps.setdefault((day, r["symbol"], r["direction"]), []).append(r)
    outcomes: dict[tuple[str, str, str], dict[str, Any]] = {}
    for f in sorted(glob.glob(str(root / "data" / "missed_opportunities" / "2026-*" / "option_returns.json"))):
        day = os.path.basename(os.path.dirname(f))
        try:
            data = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for x in sorted((x for x in data if x.get("kind") == "ATM"), key=lambda x: str(x.get("ready"))):
            outcomes.setdefault((day, x["symbol"], x["dir"]), x)
    ladder = _ladder(root)
    rows = []
    for key, lst in snaps.items():
        o = outcomes.get(key)
        if o is None or o.get("close") in (None, ""):
            continue
        lst.sort(key=lambda r: r["time"])
        ev = [(r, evaluate(r.get("rel_volume"), r.get("day_change_pct"), r.get("gap_pct"), key[2], r.get("status", ""))) for r in lst]
        pick = next(((r, e) for r, e in ev if e.get("em_core")), None) or next(((r, e) for r, e in ev if e.get("em_loose")), None) or (ev[0] if ev else None)
        if pick is None or not pick[1]:
            continue
        r, e = pick
        rows.append({"day": key[0], "symbol": key[1], "direction": key[2], "status": r.get("status", ""), **e, "best": float(o.get("best") or 0), "worst": float(o.get("worst") or 0),
                     "close": float(o["close"]), "stop_first": bool(o.get("stop_first")), "ladder": ladder.get(key)})
    return rows


def _line(name: str, g: list[dict[str, Any]]) -> str:
    if not g:
        return f"| {name} | 0 | - | - | - | - | - | - |"
    n = len(g)
    lad = [r["ladder"] for r in g if r.get("ladder") is not None]
    lad_cell = "-" if not lad else f"{st.mean(lad):+.1f}% ({100 * sum(1 for x in lad if x > 0) / len(lad):.0f}% positive, n={len(lad)})"
    pos = sum(1 for r in g if r["close"] > 0)
    ci = wilson(pos, n)
    return (f"| {name} | {n} | {100 * sum(1 for r in g if r['stop_first']) / n:.0f}% | {100 * pos / n:.0f}% ({ci[0]}-{ci[1]}) | {100 * sum(1 for r in g if r['best'] >= 100) / n:.0f}% | "
            f"{st.mean(r['best'] for r in g):+.0f}% | {st.mean(r['close'] for r in g):+.1f}% | {lad_cell} |")


def review(root: Path = ROOT, upto: str | None = None) -> Path | None:
    rows = _load(root, upto)
    if not rows:
        return None
    folder = root / "data" / "event_momentum"
    folder.mkdir(parents=True, exist_ok=True)
    reg_path = folder / "registered.json"
    try:
        registered = json.loads(reg_path.read_text(encoding="utf-8"))["day"]
    except (OSError, ValueError, KeyError):
        registered = upto or date.today().isoformat()
        reg_path.write_text(json.dumps({"day": registered}), encoding="utf-8")
    groups = lambda rs: [("Event momentum, HELD BACK by a rule (the case this is about)", [r for r in rs if r["em_core"] and r.get("em_blocked")]),
                         ("Event momentum, passed all rules", [r for r in rs if r["em_core"] and not r.get("em_blocked")]),
                         ("Loose event momentum (5x volume, 3 % with us), not core", [r for r in rs if r["em_loose"] and not r["em_core"]]),
                         ("Everything else", [r for r in rs if not r["em_loose"] and not r["em_core"]])]
    head = ["| Group | Signals | -20% stop first | Positive at close (95% CI) | Reached +100% | Mean best | Mean close | With your ladder (real 1-min prices, costs in) |", "|---|---|---|---|---|---|---|---|"]
    days = sorted({r["day"] for r in rows})
    L = ["# Event-momentum shadow review (research only; nothing here trades)", "",
         f"Candidates from the signal snapshots with a known option outcome: {len(rows)} over {len(days)} day(s) ({days[0]}..{days[-1]}). Outcome = the ATM option from the signal's first-ready time to the close;"
         " 'stop first' = a -20 % stop was hit before the best point. Hindsight, before real fills; one row per stock and direction per day (its first event-momentum moment, else its first signal).", "",
         "## All days so far (includes the days the rule was designed on: do not trust)", ""] + head
    L += [_line(n, g) for n, g in groups(rows)]
    fwd = [r for r in rows if r["day"] > registered]
    L += ["", f"## Forward only (days after {registered}, when this review first ran)", ""]
    if fwd:
        L += head + [_line(n, g) for n, g in groups(fwd)]
        held = [r for r in fwd if r["em_core"] and r.get("em_blocked")]
        L += ["", "A verdict needs at least %d held-back event-momentum signals over several days; so far %d." % (MIN_N, len(held))]
    else:
        L += ["No forward days yet."]
    L += ["", "Held-back event-momentum signals so far:", ""] + [f"- {r['day']} {r['symbol']} {r['direction']} ({r['status']}): relative volume {r['em_rvol']}x, move with us {r['em_move_dir']}%, option best {r['best']:+.0f}% / worst {r['worst']:+.0f}% / close {r['close']:+.0f}%"
                                                                        for r in rows if r["em_core"] and r.get("em_blocked")]
    out = folder / "review.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    return out


def run(day: str, root: Path = ROOT) -> None:
    review(root, day)


def main() -> int:
    import sys

    print(review(ROOT, sys.argv[1] if len(sys.argv) > 1 else None) or "no signals with outcomes yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
