"""Nightly review of the four candidate entry gates on EVERY signal, not just the trades (research only; changes nothing).

Every signal on file (data/missed_opportunities/<day>/option_returns.json: ATM option bought at the signal, held to the close, hindsight, before costs)
is checked against the gates of gate_shadow.py that can be evaluated without the live candidate:

    premium80   option entry price >= 80
    ce_early    a call signalled before 10:00
    chasing     the stock moved 0.3%+ in the trade's direction over the 15 minutes before the signal (from the saved 5-minute candles)
(ESTABLISHED_TREND needs the live candidate; it is recorded on trades as gs_est_trend and checked on the trade set.)

    data/shadow_rules/gate_review/<day>.csv     data/shadow_rules/gate_review.md

For each gate: signals it would have blocked vs the rest, mean option close, share up, share of days where the blocked ones did worse than the rest.
A gate "holds" when it blocks at least 30 signals on 5+ days, the blocked mean is below the rest by 3+ points, and it was worse on 60%+ of days.

    python gate_review.py [YYYY-MM-DD ...]
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

import gate_shadow as gs

ROOT = Path(__file__).resolve().parent
FIELDS = ["day", "symbol", "dir", "ready", "fate", "entry", "close", "best", "stop_first", "premium80", "ce_early", "chasing"]
GATES = (("premium80", "Option premium 80+"), ("ce_early", "Call before 10:00"), ("chasing", "Stock already +0.3% in our direction (15 min)"))


def _mins(h: str) -> int:
    a, b = str(h).split(":")[:2]
    return int(a) * 60 + int(b)


def move15(symbol_data: dict[str, Any] | None, minute: int, bull: bool) -> float | None:
    if not symbol_data:
        return None
    idx = [i for i, m in enumerate(symbol_data.get("minute", [])) if m < minute]
    if len(idx) < 4:
        return None
    last, prev = float(symbol_data["close"][idx[-1]]), float(symbol_data["close"][idx[-4]])
    return None if prev <= 0 else (last / prev - 1.0) * 100.0                 # raw move, + = up (gate_shadow.flags makes it directional)


def run(day: str, root: Path = ROOT, symbols: dict[str, Any] | None = None) -> Path | None:
    try:
        sigs = [r for r in json.loads((root / "data" / "missed_opportunities" / day / "option_returns.json").read_text(encoding="utf-8")) if r.get("kind") == "ATM"]
    except (OSError, ValueError):
        return None
    if symbols is None:
        try:
            symbols = json.loads((root / "data" / "pattern_log" / "candles" / f"{day}.json").read_text(encoding="utf-8")).get("symbols", {})
        except (OSError, ValueError):
            symbols = {}
    rows = []
    for r in sigs:
        minute = _mins(r["ready"])
        bull = r.get("dir") == "BULLISH"
        raw = move15(symbols.get(r["symbol"]), minute, bull)          # raw stock move (+ = up); gate_shadow turns it into "our direction"
        f = gs.flags(str(r.get("dir")), r.get("entry"), minute, raw)
        rows.append({"day": day, "symbol": r["symbol"], "dir": r.get("dir"), "ready": r["ready"], "fate": str(r.get("fate") or "").split(":")[0], "entry": r.get("entry"),
                     "close": r.get("close"), "best": r.get("best"), "stop_first": int(bool(r.get("stop_first"))),
                     "premium80": "" if f["premium80"] is None else int(f["premium80"]), "ce_early": "" if f["ce_early"] is None else int(f["ce_early"]),
                     "chasing": "" if f["chasing"] is None else int(f["chasing"])})
    folder = root / "data" / "shadow_rules" / "gate_review"
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


def evaluate(rows: list[dict[str, Any]], gate: str) -> dict[str, Any]:
    ev = [r for r in rows if r.get(gate) not in ("", None) and _f(r.get("close")) is not None]
    blocked = [r for r in ev if int(r[gate])]
    rest = [r for r in ev if not int(r[gate])]
    out: dict[str, Any] = {"n_blocked": len(blocked), "n_rest": len(rest)}
    if not blocked or not rest:
        return out
    mb, mr = st.mean(_f(r["close"]) for r in blocked), st.mean(_f(r["close"]) for r in rest)
    byd: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"b": [], "r": []})
    for r in ev:
        byd[r["day"]]["b" if int(r[gate]) else "r"].append(_f(r["close"]))
    both = [d for d, v in byd.items() if v["b"] and v["r"]]
    worse = sum(1 for d in both if st.mean(byd[d]["b"]) < st.mean(byd[d]["r"]))
    out.update({"mean_blocked": mb, "mean_rest": mr, "up_blocked": 100 * sum(_f(r["close"]) > 0 for r in blocked) / len(blocked),
                "up_rest": 100 * sum(_f(r["close"]) > 0 for r in rest) / len(rest), "days": len(both), "days_worse": worse,
                "blocked_days": len({r["day"] for r in blocked}),
                "holds": len(blocked) >= 30 and len({r["day"] for r in blocked}) >= 5 and mb <= mr - 3.0 and bool(both) and worse / len(both) >= 0.6})
    return out


def write_summary(root: Path = ROOT) -> Path | None:
    rows: list[dict[str, Any]] = []
    for p in sorted(glob.glob(str(root / "data" / "shadow_rules" / "gate_review" / "20*.csv"))):
        with open(p, encoding="utf-8", newline="") as h:
            rows.extend(csv.DictReader(h))
    if not rows:
        return None
    days = sorted({r["day"] for r in rows})
    out = ["# Entry-gate shadow review (research only)", "",
           f"{len(rows)} signals on {len(days)} day(s) ({days[0]} to {days[-1]}). ATM option bought at the signal, held to close, hindsight, before costs. "
           "A gate 'holds' when it blocks 30+ signals on 5+ days, the blocked ones average 3+ points below the rest, and they were worse on 60%+ of days.", ""]
    for scope, sub in (("All signals", rows), ("Signals we actually traded", [r for r in rows if r["fate"] == "TRADED"])):
        out += [f"## {scope}", "", "| Gate | Blocked | Rest | Blocked: mean close / up | Rest: mean close / up | Days blocked were worse | Holds |", "|---|---|---|---|---|---|---|"]
        for g, label in GATES:
            e = evaluate(sub, g)
            if "mean_blocked" not in e:
                out.append(f"| {label} | {e['n_blocked']} | {e['n_rest']} | - | - | - | - |")
                continue
            out.append(f"| {label} | {e['n_blocked']} | {e['n_rest']} | {e['mean_blocked']:+.1f}% / {e['up_blocked']:.0f}% | {e['mean_rest']:+.1f}% / {e['up_rest']:.0f}% | "
                       f"{e['days_worse']} of {e['days']} | {'**yes**' if e['holds'] else 'not yet'} |")
        out.append("")
    out += ["_ESTABLISHED_TREND needs the live candidate, so it is checked on trades from the journal tags (gs_est_trend), not here. Research only._", ""]
    path = root / "data" / "shadow_rules" / "gate_review.md"
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
