"""A+ gate what-if (SHADOW ONLY: re-evaluates recorded signal snapshots with some wait rules switched off; nothing trades on it).

The A+ selective gate (opening_momentum_scanner._aplus_selective_entry_allowed) is a chain of WAIT rules checked in a fixed order; the first one that fires is the status the candidate gets. This copies the
chain (same order, same thresholds) and runs it on data/signal_snapshots/<day>.csv, where every entry-ready candidate was recorded with the numbers the gate used. With a rule disabled, a candidate that
it held falls through to the next rule, or passes. For the candidates that would then pass, the option is followed (nearest-the-money of the right side, from the chain snapshots) and the live exit ladder
is replayed on it (baseline_replay.simulate, same fills and Rs 250 charges, Rs 20,000 a trade).

    python gate_whatif.py check                      does the copy reproduce the recorded statuses?
    python gate_whatif.py LATE_10M_OVERHEAT [LATE_VWAP_EXTENSION ...]   what happens with those rules off, all recorded days
    python gate_whatif.py LATE_10M_OVERHEAT --stock COFORGE             the same, listing that stock's snapshots

Limits: the snapshot has one row per candidate per status change (or every 5 minutes), not every cycle; the next stage after the A+ gate (Selection V2, safety, option selection) is not replayed, so "passes
the A+ gate" is not "would have been traded"; option prices come from 5-minute chain snapshots, so fills are coarse.
"""

from __future__ import annotations

import csv
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
RULES = ("PIVOT_TO_R1", "LATE_10M_OVERHEAT", "LATE_VWAP_EXTENSION", "LATE_SESSION_EXTENSION", "LATE_CLOSE_EXTENSION", "OVEREXTENDED", "BULL_EXHAUSTION", "BEAR_EXHAUSTION",
         "BEAR_BREAKDOWN_CONFIRM", "DIRECTION_CONFLICT", "VWAP_ALIGNMENT", "NO_FOLLOW_THROUGH", "WEAK_PARTICIPATION", "QUALITY", "ALIGNMENT_STRUCTURE", "CLEAN_STRUCTURE")
PREFIX = "A_PLUS_WAIT_"


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


DEFAULTS = {"late10": 0.85, "latev": 0.87, "session": 2.81, "close": 2.96, "chase": 25.0}


def evaluate(r: Mapping[str, Any], off: frozenset[str] = frozenset(), p: Mapping[str, float] | None = None) -> str:
    """The A+ status of a snapshot row with the rules in `off` skipped: a WAIT name without the prefix, or PASSED. `p` overrides the thresholds (DEFAULTS are the live ones)."""
    p = {**DEFAULTS, **(p or {})}
    bull = str(r.get("direction", "")).upper() == "BULLISH"
    s = 1.0 if bull else -1.0
    pivot, setup = str(r.get("pivot_state", "")).upper(), str(r.get("setup_family", "")).upper()
    fresh = bool(_f(r.get("fresh_15m")) or _f(r.get("fresh_30m")) or _f(r.get("fresh_day")) or _f(r.get("opening_range_breakout")))
    d5, d10, d15 = s * _f(r.get("recent_5m_pct")), s * _f(r.get("recent_10m_pct")), s * _f(r.get("recent_15m_pct"))
    session, close, vwap = s * _f(r.get("move_from_0915_pct")), s * _f(r.get("day_change_pct")), s * _f(r.get("vwap_dist_pct"))
    chase, rsi, vwap_raw = _f(r.get("chase_risk")), _f(r.get("rsi_5m")), _f(r.get("vwap_dist_pct"))
    late_vwap = vwap > p["latev"]

    def on(name: str) -> bool:
        return name not in off

    if pivot == "PIVOT_TO_R1" and on("PIVOT_TO_R1"):
        return "PIVOT_TO_R1"
    if d10 > p["late10"] and on("LATE_10M_OVERHEAT"):
        return "LATE_10M_OVERHEAT"
    if late_vwap and (d5 > 0.25 or d15 > 0.45) and on("LATE_VWAP_EXTENSION"):
        return "LATE_VWAP_EXTENSION"
    if session > p["session"] and (d10 > 0.40 or late_vwap) and on("LATE_SESSION_EXTENSION"):
        return "LATE_SESSION_EXTENSION"
    if close > p["close"] and (d10 > 0.40 or late_vwap) and on("LATE_CLOSE_EXTENSION"):
        return "LATE_CLOSE_EXTENSION"
    if chase >= p["chase"] and abs(vwap_raw) >= 0.75 and on("OVEREXTENDED"):
        return "OVEREXTENDED"
    if bull and rsi >= 85.0 and vwap_raw >= 0.60 and d10 > 0.85 and on("BULL_EXHAUSTION"):
        return "BULL_EXHAUSTION"
    if not bull and rsi <= 15.0 and vwap_raw <= -0.60 and d10 > 0.85 and on("BEAR_EXHAUSTION"):
        return "BEAR_EXHAUSTION"
    if setup == "CLEAN_BEARISH_BREAKDOWN" and on("BEAR_BREAKDOWN_CONFIRM"):
        return "BEAR_BREAKDOWN_CONFIRM"
    if session <= 0.0 and not fresh and on("DIRECTION_CONFLICT"):
        return "DIRECTION_CONFLICT"
    if vwap < 0.0 and not fresh and on("VWAP_ALIGNMENT"):
        return "VWAP_ALIGNMENT"
    follow = d5 > 0.0 or d15 > 0.10
    participation = _f(r.get("rel_volume")) >= 1.0 or _f(r.get("rel_volume_15m")) >= 1.0 or _f(r.get("tape_acc_5m")) >= 1.15 or _f(r.get("tape_acc_15m")) >= 1.15
    if not follow and not fresh and on("NO_FOLLOW_THROUGH"):
        return "NO_FOLLOW_THROUGH"
    if not participation and on("WEAK_PARTICIPATION"):
        return "WEAK_PARTICIPATION"
    if _f(r.get("trade_quality")) < 65.0 and on("QUALITY"):
        return "QUALITY"
    if _f(r.get("trend_alignment")) < 60.0 and _f(r.get("clean_trend")) < 90.0 and not fresh and on("ALIGNMENT_STRUCTURE"):
        return "ALIGNMENT_STRUCTURE"
    if _f(r.get("clean_trend")) < 72.0 and not fresh and on("CLEAN_STRUCTURE"):
        return "CLEAN_STRUCTURE"
    return "PASSED"


def recorded(r: Mapping[str, Any]) -> str:
    st_ = str(r.get("status", ""))
    return "PASSED" if st_ == "PASSED_ALL_GATES" else st_.replace(PREFIX, "") if st_.startswith(PREFIX) else "OTHER"


def load(day: str, root: Path = ROOT) -> list[dict[str, str]]:
    path = root / "data" / "signal_snapshots" / f"{day}.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as h:
        return list(csv.DictReader(h))


def days(root: Path = ROOT) -> list[str]:
    return sorted(p.stem for p in (root / "data" / "signal_snapshots").glob("2026-*.csv") if not p.stem.startswith("chain_"))


def check(root: Path = ROOT) -> str:
    tot = ok = 0
    miss: Counter = Counter()
    for d in days(root):
        for r in load(d, root):
            rec = recorded(r)
            if rec == "OTHER":
                continue
            tot += 1
            got = evaluate(r)
            if got == rec:
                ok += 1
            else:
                miss[(rec, got)] += 1
    lines = [f"copy of the A+ chain reproduces the recorded status on {ok} of {tot} snapshots ({100 * ok / max(tot, 1):.1f}%)"]
    lines += [f"  recorded {a} -> copy said {b}: {n}" for (a, b), n in miss.most_common(6)]
    return "\n".join(lines)


def outcome(chain_rows: Sequence[Mapping[str, str]], direction: str, hhmm: str) -> dict[str, Any]:
    """Follow the nearest-the-money option from the first chain row after hhmm and replay the live ladder on its snapshot prices."""
    import late_runner
    import numpy as np
    from baseline_replay import simulate
    side = "CE" if direction == "BULLISH" else "PE"
    start = [r for r in chain_rows if r.get("side") == side and r["captured_at"][11:16] >= hhmm and _f(r.get("ltp")) > 0]
    if not start:
        return {}
    t0 = start[0]["captured_at"][11:16]
    if late_runner._minutes(t0) - late_runner._minutes(hhmm) > late_runner.MAX_CHAIN_GAP_MIN:
        return {}
    at = [r for r in start if r["captured_at"][11:16] == t0]
    exp = min(r["expiry"] for r in at)
    pick = min((r for r in at if r["expiry"] == exp), key=lambda r: abs(_f(r["strike"]) - _f(r["spot"])))
    key = (pick["strike"], pick["expiry"])
    ser = [(late_runner._minutes(r["captured_at"][11:16]), _f(r["ltp"])) for r in chain_rows if r.get("side") == side and (r["strike"], r["expiry"]) == key and _f(r.get("ltp")) > 0]
    ser = sorted(dict(ser).items())
    m = np.array([a for a, _ in ser], dtype=float)
    p = np.array([b for _, b in ser], dtype=float)
    k = int(np.searchsorted(m, late_runner._minutes(hhmm), side="right")) - 1
    res = simulate(m.tolist(), p.tolist(), p.tolist(), p.tolist(), p.tolist(), max(k, 0))
    return {**res, "strike": _f(pick["strike"]), "peak_ltp_pct": round((p[max(k, 0):].max() / p[max(k, 0)] - 1) * 100, 1)} if res else {}


def whatif(off: frozenset[str], root: Path = ROOT, stock: str | None = None, p: Mapping[str, float] | None = None, addon: tuple[float, float, float, float] | None = None, held_rules: frozenset[str] | None = None) -> str:
    import late_runner
    held_rules = held_rules or off

    def status(r: Mapping[str, Any]) -> str:
        got = evaluate(r, off, p)
        if got == "PASSED" and addon is not None:
            score_min, chase_max, rv_min, ret_min = addon
            if not (_f(r.get("score")) >= score_min and _f(r.get("chase_risk")) < chase_max and _f(r.get("rel_volume")) >= rv_min and _f(r.get("trend_retention_pct")) >= ret_min):
                return "QUALITY_ADDON"
        return got

    lines = [f"Rules switched off: {', '.join(sorted(off)) or '-'}" + (f"; thresholds {dict(p)}" if p else "") + (f"; extra quality filters score>={addon[0]:g}, chase<{addon[1]:g}, rel volume>={addon[2]:g}, retention>={addon[3]:g}" if addon else ""), ""]
    new_rows = []
    for d in days(root):
        rows = load(d, root)
        if not rows:
            continue
        held = [r for r in rows if recorded(r) in held_rules]
        c = Counter(status(r) for r in held)
        lines.append(f"{d}: {len(held)} snapshots were held by these rules; with them off they become: " + ", ".join(f"{k} {v}" for k, v in c.most_common()))
        first: dict[tuple[str, str], dict[str, str]] = {}
        for r in held:
            if status(r) == "PASSED":
                first.setdefault((r["symbol"], r["direction"]), r)
        actual_pass = {(r["symbol"], r["direction"]) for r in rows if recorded(r) == "PASSED"}
        chain = late_runner._chain(root, d, {k[0] for k in first})
        for (sym, direction), r in first.items():
            res = outcome(chain.get(sym, []), direction, r["time"][11:16])
            new_rows.append({"day": d, "symbol": sym, "direction": direction, "time": r["time"][11:16], "was": recorded(r), "also_passed_anyway": (sym, direction) in actual_pass, **res})
        if stock:
            for r in rows:
                if r["symbol"] == stock:
                    lines.append(f"    {stock} {r['time'][11:16]} {r['direction'][:4]} recorded {recorded(r)} -> with rules off {status(r)}")
    done = [r for r in new_rows if r.get("net_rs") is not None]
    fresh = [r for r in done if not r["also_passed_anyway"]]
    lines += ["", f"Stock-days that would newly pass the A+ gate: {len(new_rows)} ({len(done)} with option prices; {len(fresh)} of those never passed on the day anyway)."]
    if fresh:
        lines += [f"With the live ladder on the nearest-the-money option (Rs 20,000 a trade): wins {sum(r['net_rs'] > 0 for r in fresh)}, losses {sum(r['net_rs'] <= 0 for r in fresh)}, "
                  f"stopped at -20 % {sum(r['why'] == 'STOP' for r in fresh)}, median {st.median(r['gross_pct'] for r in fresh):+.1f} %, mean {st.mean(r['gross_pct'] for r in fresh):+.1f} %, total net Rs {sum(r['net_rs'] for r in fresh):,.0f}", "",
                  "| day | stock | dir | time | held by | entry | exit | why | gross % | peak % | net Rs |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        lines += [f"| {r['day']} | {r['symbol']} | {r['direction'][:4]} | {r['time']} | {r['was']} | {r['entry']:.2f} | {r['exit']:.2f} | {r['why']} | {r['gross_pct']:+.1f} | {r['peak_pct']:.0f} | {r['net_rs']:+,.0f} |"
                  for r in sorted(fresh, key=lambda r: (r["day"], r["time"]))]
    return "\n".join(lines)


VARIANTS = (("late_10m_off", frozenset({"LATE_10M_OVERHEAT"})), ("late_10m_and_vwap_off", frozenset({"LATE_10M_OVERHEAT", "LATE_VWAP_EXTENSION"})))

# The quality release found on 21 - 26 Oct (stable leave-one-day-out, still only 4 days): the late rules relaxed (10-minute move 1.8 %, VWAP distance 2.2 %, session / close extension off) but only for
# candidates scoring 80+ with chase risk under 20, relative volume 1.3x+ and trend retention 80 %+.
QUALITY_RELEASE = dict(p={"late10": 1.8, "latev": 2.2, "session": 99.0, "close": 99.0}, addon=(80.0, 20.0, 1.3, 80.0), held_rules=frozenset({"LATE_10M_OVERHEAT", "LATE_VWAP_EXTENSION", "LATE_SESSION_EXTENSION", "LATE_CLOSE_EXTENSION"}))


def run(day: str, root: Path = ROOT) -> Path:
    """Nightly entry point: the what-if for each variant over every recorded day, written to data/gate_whatif/<variant>.md (cumulative, so it grows with the days)."""
    folder = root / "data" / "gate_whatif"
    folder.mkdir(parents=True, exist_ok=True)
    for name, off in VARIANTS:
        note = "Shadow only. Newly passing = would pass the A+ gate; Selection V2 / safety are not replayed. Judge the total without its two biggest winners as well."
        (folder / f"{name}.md").write_text(whatif(off, root) + "\n\n" + note + "\n", encoding="utf-8")
    (folder / "quality_release.md").write_text(whatif(frozenset(), root, None, **QUALITY_RELEASE) + "\n\n" + note + "\n", encoding="utf-8")
    return folder


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    stock = None
    if "--stock" in args:
        i = args.index("--stock")
        stock = args[i + 1]
        del args[i:i + 2]
    if not args or args[0] == "check":
        print(check())
    else:
        print(whatif(frozenset(args), ROOT, stock))
