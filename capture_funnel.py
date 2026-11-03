"""Capture funnel (RESEARCH ONLY: reads recorded data, changes nothing).

The question: of the significant, actionable moves in the eligible F&O universe, how many did APlus detect in time, and exactly where did it lose the rest?

    SIGNIFICANT MOVE   a stock gains >= 3.0 % in our direction inside 30 minutes and still holds at least half of that gain 30 minutes after its best point.
                       One move per stock and direction per day (the earliest start). Start t0 = the first minute from which such a 30-minute window exists (09:30 - 14:45).
    DEADLINE           the first time the stock stands 1.5 % (half the bar) from its t0 price. Detected "in time" = flagged by then.
    ACTIONABLE         the nearest-the-money option of the right side, bought at the first chain row after the deadline (+60 s) at the ask, reaches +40 % before -30 % (late_runner.follow).

Each move ends in exactly ONE stage, the first that applies:
    TRADED             a paper trade in that direction, entered from 10 minutes before t0 to 10 minutes after the deadline            (result in Rs shown)
    PASSED_NOT_TRADED  an entry-ready snapshot with PASSED_ALL_GATES in that window but no trade                                       (Selection V2 / safety / option selection)
    HELD_BY_<status>   entry-ready snapshots in that window, none passed: the status that held it longest (A+ wait such as LATE_10M_OVERHEAT, PIVOT_TO_R1, ...)
    ENTRY_READY_LATE   its first entry-ready snapshot came after the deadline
    SEEN_NOT_READY     named by the radar logs (leadership / move-pattern observer) by the deadline but never entry-ready: it dropped out between the radar and entry-ready.
                       The scanner does not record WHY for this step (analysed-but-rejected stages such as EXTENDED_NO_ENTRY, VWAP_CONFLICT, or cut by the 30-stock analysis limit), so it is one bucket until it does
    NOT_SEEN           not named anywhere by the deadline

    data/capture_funnel/<day>.md   the stage counts and every move with its stage
    data/capture_funnel/ledger.csv all days

    python capture_funnel.py [YYYY-MM-DD ...]   default: every day that has recorded ticks and scanner snapshots
"""

from __future__ import annotations

import csv
import json
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
BAR_PCT, DEADLINE_PCT, WINDOW_S, HOLD_FRACTION = 3.0, 1.5, 1800, 0.5
FIRST_T, LAST_T = 9 * 3600 + 30 * 60, 14 * 3600 + 45 * 60
LEAD_S, TRAIL_S = 600, 600
LEDGER = ("data", "capture_funnel", "ledger.csv")
FIELDS = ["day", "symbol", "direction", "t0", "deadline", "gain_pct", "stage", "detail", "actionable", "option", "entry", "peak_pct", "first", "trade_rs"]


def hms(t: float) -> str:
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}"


def secs(text: str) -> float:
    m = re.search(r"(\d\d):(\d\d):(\d\d)", text)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) if m else -1.0


# ------------------------------------------------------------------ ground truth ----------------------------------------------------------------------
def find_moves(series: Mapping[str, Sequence[tuple[float, float]]]) -> list[dict[str, Any]]:
    """series: symbol -> [(seconds, price)] oldest first."""
    out = []
    for sym, sr in series.items():
        if len(sr) < 50:
            continue
        times = [t for t, _ in sr]
        prices = [p for _, p in sr]
        for sg in (1, -1):
            found = None
            t = FIRST_T
            while t <= LAST_T and not found:
                i0 = _idx(times, t)
                if i0 is None:
                    t += 60
                    continue
                p0 = prices[i0]
                i1 = _idx(times, t + WINDOW_S)
                if i1 is None or i1 <= i0:
                    t += 60
                    continue
                window = prices[i0:i1 + 1]
                best = max(window) if sg > 0 else min(window)
                gain = sg * (best / p0 - 1) * 100
                if gain >= BAR_PCT:
                    ib = i0 + window.index(best)
                    after = prices[ib:_idx(times, times[ib] + WINDOW_S) + 1 if _idx(times, times[ib] + WINDOW_S) else None]
                    held = True
                    if len(after) > 1 and times[-1] >= times[ib] + WINDOW_S - 60:
                        worst = min(after) if sg > 0 else max(after)
                        held = sg * (worst / p0 - 1) * 100 >= (1 - HOLD_FRACTION) * gain
                    if held:
                        dead = next((times[k] for k in range(i0, len(prices)) if sg * (prices[k] / p0 - 1) * 100 >= DEADLINE_PCT), times[ib])
                        found = {"symbol": sym, "direction": "BULLISH" if sg > 0 else "BEARISH", "t0": times[i0], "deadline": dead, "gain_pct": round(gain, 2), "p0": p0}
                t += 60
            if found:
                out.append(found)
    return sorted(out, key=lambda m: m["t0"])


def _idx(times: Sequence[float], t: float) -> int | None:
    """Index of the last sample at or before t (None before the first sample)."""
    lo, hi, best = 0, len(times) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if times[mid] <= t:
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    return best


# ------------------------------------------------------------------ detection records -----------------------------------------------------------------
LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d) .*?(LEADERSHIP_V6_SHADOW|OPEN_MOVE_PATTERN_OBSERVER_V1_1)(.*)$")


def radar_sightings(day: str, root: Path = ROOT) -> dict[str, list[float]]:
    """symbol -> seconds at which the scanner's own radar logs named it (leadership hits, progressive / reversal move patterns) that day."""
    out: dict[str, list[float]] = defaultdict(list)
    for path in sorted((root / "logs").glob("scanner.log*")):
        try:
            with path.open(encoding="utf-8", errors="ignore") as h:
                for line in h:
                    if line[:10] != day or ("LEADERSHIP_V6" not in line and "OPEN_MOVE_PATTERN" not in line):
                        continue
                    m = LOG_LINE.match(line.strip())
                    if not m:
                        continue
                    t = secs(m.group(2))
                    for key in ("symbols=", "progressive_symbols=", "reversal_symbols="):
                        for mm in re.finditer(re.escape(key) + r"([A-Z0-9&\-,]*)", m.group(4)):
                            for s in mm.group(1).split(","):
                                if s and s != "NONE":
                                    out[s].append(t)
        except OSError:
            continue
    return {s: sorted(set(v)) for s, v in out.items()}


def snapshots(day: str, root: Path = ROOT) -> dict[tuple[str, str], list[tuple[float, str, str]]]:
    path = root / "data" / "signal_snapshots" / f"{day}.csv"
    out: dict[tuple[str, str], list[tuple[float, str, str]]] = defaultdict(list)
    if not path.exists():
        return out
    with path.open(encoding="utf-8", newline="") as h:
        for r in csv.DictReader(h):
            out[(r["symbol"], r["direction"])].append((secs(r["time"][11:19]), r["status"], r.get("stage", "")))
    return out


def trades(day: str, root: Path = ROOT) -> list[dict[str, Any]]:
    out = {}
    for src in (root / "data" / "reports" / "paper_trade_history.json", root / "data" / "intraday_movement" / "paper_trade_journal.json"):
        try:
            d = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for x in (d.get("paper_trades") or d.get("trades") or []):
            if str(x.get("entry_time", "")).startswith(day):
                out[(x["symbol"], x["entry_time"][:16])] = x
    return list(out.values())


# ------------------------------------------------------------------ attribution ----------------------------------------------------------------------
def classify(move: Mapping[str, Any], sightings: Mapping[str, Sequence[float]], snaps: Mapping[tuple[str, str], Sequence[tuple[float, str, str]]], day_trades: Sequence[Mapping[str, Any]]) -> tuple[str, str, float | None]:
    """(stage, detail, trade_rs)."""
    sym, d, t0, dead = move["symbol"], move["direction"], move["t0"], move["deadline"]
    lo, hi = t0 - LEAD_S, dead + TRAIL_S
    for x in day_trades:
        if x.get("symbol") == sym and x.get("direction") == d:
            te = secs(str(x["entry_time"])[11:19])
            if lo <= te <= hi:
                pnl = x.get("net_pnl") if x.get("status") == "CLOSED" else x.get("unrealized_pnl")
                return "TRADED", f"entered {hms(te)[:5]}, {x.get('exit_reason') or x.get('status')}", float(pnl or 0)
    rows = snaps.get((sym, d), [])
    window = [r for r in rows if lo <= r[0] <= hi]
    if any(r[1] == "PASSED_ALL_GATES" for r in window):
        return "PASSED_NOT_TRADED", "passed the A+ gates; no paper trade (Selection V2 / safety / option selection)", None
    if window:
        c = Counter(r[1] for r in window)
        status = c.most_common(1)[0][0]
        return f"HELD_BY_{status.replace('A_PLUS_WAIT_', '')}", f"{len(window)} entry-ready snapshots, first {hms(window[0][0])[:5]}", None
    later = [r for r in rows if r[0] > hi]
    if later:
        return "ENTRY_READY_LATE", f"first entry-ready {hms(later[0][0])[:5]} ({later[0][1].replace('A_PLUS_WAIT_', '')}), deadline was {hms(dead)[:5]}", None
    seen = [t for t in sightings.get(sym, []) if t <= hi]
    if seen:
        return "SEEN_NOT_READY", f"named by the radar logs from {hms(seen[0])[:5]}; never entry-ready (reason not recorded)", None
    return "NOT_SEEN", "not named by the radar logs by the deadline", None


def actionable(move: Mapping[str, Any], chain: Mapping[str, Sequence[Mapping[str, str]]]) -> dict[str, Any]:
    import late_runner
    got = late_runner.follow(chain.get(move["symbol"], []), move["direction"], hms(move["deadline"] + 60)[:5])
    if not got:
        return {"actionable": "", "option": "", "entry": "", "peak_pct": "", "first": ""}
    ok = got["first"] == "T1" or (got["peak_pct"] >= 40 and got["first"] != "SL")
    return {"actionable": int(ok), "option": f"{got['strike']:.0f} {got['side']}", "entry": got["entry"], "peak_pct": got["peak_pct"], "first": got["first"]}


def day_rows(day: str, root: Path = ROOT) -> list[dict[str, Any]]:
    import late_runner
    import rs_replay
    series = rs_replay.series_by_symbol(rs_replay.load_samples(root, day, step=30.0))
    moves = find_moves(series)
    sight, snaps, trs = radar_sightings(day, root), snapshots(day, root), trades(day, root)
    chain = late_runner._chain(root, day, {m["symbol"] for m in moves})
    out = []
    for m in moves:
        stage, detail, rs = classify(m, sight, snaps, trs)
        out.append({"day": day, "symbol": m["symbol"], "direction": m["direction"], "t0": hms(m["t0"])[:5], "deadline": hms(m["deadline"])[:5], "gain_pct": m["gain_pct"], "stage": stage, "detail": detail,
                    **actionable(m, chain), "trade_rs": "" if rs is None else round(rs)})
    return out


def render(day: str, rows: Sequence[Mapping[str, Any]]) -> str:
    n = len(rows)
    act = [r for r in rows if r["actionable"] == 1]
    lines = [f"# Capture funnel {day}", "", f"Significant moves (stock >= {BAR_PCT:.0f} % in 30 minutes, half held 30 minutes later): **{n}**. Of them actionable (nearest-the-money option +40 % before -30 % from the deadline): **{len(act)}**.", ""]
    for title, sel in (("All significant moves", rows), ("Actionable moves only", act)):
        c = Counter(r["stage"] for r in sel)
        lines += [f"### {title}", "", "| where it ended | moves | share |", "|---|---|---|"]
        lines += [f"| {k} | {v} | {100 * v / max(len(sel), 1):.0f}% |" for k, v in sorted(c.items(), key=lambda kv: -kv[1])]
        lines.append("")
    lines += ["### Every move", "", "| stock | dir | start | deadline | gain % | option peak % | actionable | where it ended | detail |", "|---|---|---|---|---|---|---|---|---|"]
    lines += [f"| {r['symbol']} | {r['direction'][:4]} | {r['t0']} | {r['deadline']} | {r['gain_pct']} | {r['peak_pct'] if r['peak_pct'] != '' else '-'} | {'yes' if r['actionable'] == 1 else 'no' if r['actionable'] == 0 else '?'} | {r['stage']} | {r['detail']} |"
              for r in sorted(rows, key=lambda r: -float(r["gain_pct"]))]
    return "\n".join(lines) + "\n"


def run(days: Sequence[str], root: Path = ROOT) -> list[Path]:
    path = root.joinpath(*LEDGER)
    path.parent.mkdir(parents=True, exist_ok=True)
    old: list[dict[str, str]] = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as h:
            old = [r for r in csv.DictReader(h) if r["day"] not in set(days)]
    allrows: list[dict[str, Any]] = list(old)
    outs = []
    for d in days:
        rows = day_rows(d, root)
        allrows += rows
        p = path.parent / f"{d}.md"
        p.write_text(render(d, rows), encoding="utf-8")
        outs.append(p)
    allrows.sort(key=lambda r: (r["day"], r["t0"]))
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(allrows)
    return outs


if __name__ == "__main__":
    ds = sys.argv[1:] or sorted(p.name for p in (ROOT / "data" / "ticks").iterdir() if p.is_dir() and (ROOT / "data" / "signal_snapshots" / f"{p.name}.csv").exists())
    for p in run(ds):
        print(p)
