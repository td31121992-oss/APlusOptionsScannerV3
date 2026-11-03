"""Replay EVERY signal (traded, blocked by a rule, blocked by the V2 rank rule ...) through the exit rules on real 1-minute option prices (research only; no trading effect).

For each signal in data/missed_opportunities/<day>/signals.csv the option the strict-label test uses (about 0.5 % in the money, nearest expiry, Upstox 1-minute candles, cached by strict_label.py)
is bought one minute after the signal at the candle close plus 1 % slippage, then followed minute by minute until 15:25 under two exit rules:

    ladder   the user's ladder (paper_trade_journal.user_ladder_floor: +5 % -> stop -15 %, +10 % -> +3 %, +20 % -> +13 %, +30 % -> +22 %, then +2 per +5 %) on top of the initial -20 % stop
    old      the previous live rules: initial -20 % stop, T1 (+20 %) -> stop at entry, T2 (+35 %) -> +8 %, T3 (+50 %) -> runner (floor +15 %, 70 % of the peak gain)

A stop is tested against the minute's LOW using the stop level known at the start of that minute (the peak so far), and fills at the stop, or at the open when the minute opens below it (a gap);
the minute's high raises the peak only after the stop has been tested, so a spike and a dip in the same minute cannot both be used. COST_PCT is taken off every trade for spread and impact.

    data/strict_labels/ladder_replay.csv     one row per signal
    data/strict_labels/ladder_replay.md      the summary (by rule that blocked the signal, side, and per day)

    python ladder_replay_signals.py [--since YYYY-MM-DD]      (a re-run only fetches what is not cached yet)
"""

from __future__ import annotations

import argparse
import csv
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
SLIP_PCT, COST_PCT, STOP_PCT, DELAY = 1.0, 2.5, 20.0, 1
LAST_MIN = 15 * 60 + 25
FIELDS = ["day", "symbol", "dir", "group", "fate", "ready", "strike", "entry", "peak_pct", "ladder_pct", "ladder_exit", "old_pct", "old_exit", "hold_pct"]


def group_of(fate: str) -> str:
    if fate == "TRADED":
        return "TRADED"
    if fate == "A_PLUS:pivot_to_r1":
        return "A+ pivot_to_r1"
    if fate.startswith("A_PLUS:late_vwap_extension"):
        return "A+ late_vwap_extension"
    if fate.startswith("A_PLUS:late_10m_overheat"):
        return "A+ late_10m_overheat"
    if fate.startswith("A_PLUS"):
        return "A+ other rules"
    if fate == "V2_BLOCKED":
        return "V2 rank rule"
    return "other"


def simulate(bars: Sequence[tuple[int, float, float, float, float]], entry: float, stop_fn: Any) -> tuple[float, str, float]:
    """Walk the bars after entry. stop_fn(peak_price) -> stop level in force. Returns (exit price, reason, peak price reached)."""
    peak = entry
    stop0 = entry * (1.0 - STOP_PCT / 100.0)
    last = entry
    for minute, o, h, l, c in bars:
        if minute > LAST_MIN:
            break
        stop = max(stop0, stop_fn(peak))
        if l <= stop:
            return (min(o, stop) if o < stop else stop), "STOP", peak
        peak = max(peak, h)
        last = c
    return last, "SESSION_END", peak


def ladder_stop(entry: float) -> Any:
    from paper_trade_journal import user_ladder_floor

    return lambda peak: user_ladder_floor(entry, peak)


def old_stop(entry: float) -> Any:
    def f(peak: float) -> float:
        gain = (peak / entry - 1.0) * 100.0
        s = 0.0
        if gain >= 20.0:
            s = entry
        if gain >= 35.0:
            s = entry * 1.08
        if gain >= 50.0:
            s = max(entry * 1.08, entry * 1.15, entry + 0.70 * (peak - entry))
        return s
    return f


def replay_signal(bars: Sequence[tuple[int, float, float, float, float]], minute: int) -> dict[str, Any] | None:
    at = [b for b in bars if b[0] <= minute + DELAY]
    after = [b for b in bars if at and b[0] > at[-1][0]]
    if not at or not after or at[-1][4] <= 0:
        return None
    entry = at[-1][4] * (1 + SLIP_PCT / 100.0)
    lx, lr, peak = simulate(after, entry, ladder_stop(entry))
    ox, orr, _ = simulate(after, entry, old_stop(entry))
    pct = lambda x: round((x / entry - 1.0) * 100.0 - COST_PCT, 2)
    last = [b for b in after if b[0] <= LAST_MIN]
    return {"entry": round(entry, 2), "peak_pct": round((max(b[2] for b in after) / entry - 1) * 100, 1), "ladder_pct": pct(lx), "ladder_exit": lr, "old_pct": pct(ox), "old_exit": orr,
            "hold_pct": pct(last[-1][4]) if last else ""}


def run(since: str = "2026-08-20", root: Path = ROOT) -> Path:
    sys.path.insert(0, str(root))
    import strict_label as sl

    src = sl.Source(root, pause=0.3)
    und = sl._underlyings(src, root)
    today = datetime.now(IST).date().isoformat()
    out = root / "data" / "strict_labels" / "ladder_replay.csv"
    rows: list[dict[str, Any]] = []
    for p in sorted((root / "data" / "missed_opportunities").glob("20*/signals.csv")):
        day = p.parent.name
        if day < since:
            continue
        n0 = len(rows)
        for s in sl.signals(day, root):
            sym, minute = s["symbol"], sl._mins(s.get("first_ready", ""))
            ukey = und.get(sym)
            try:
                spot = float(s.get("entry_price") or 0)
            except ValueError:
                spot = 0.0
            if not ukey or minute is None or spot <= 0:
                continue
            try:
                exps = [e for e in src.expiries(ukey) if e >= day]
                if not exps:
                    continue
                expired = exps[0] < today
                ct = sl.pick_contract(src.contracts(ukey, exps[0], expired), s["direction"] == "BULLISH", spot)
                if ct is None:
                    continue
                bars = src.candles(ct["key"], day, expired)
            except Exception as exc:                       # noqa: BLE001 - one bad contract must not stop the run
                print(day, sym, "skipped:", str(exc)[:80], flush=True)
                continue
            r = replay_signal(bars, minute)
            if r:
                rows.append({"day": day, "symbol": sym, "dir": s["direction"], "group": group_of(s.get("fate", "")), "fate": s.get("fate", ""), "ready": s.get("first_ready", ""), "strike": ct["strike"], **r})
        print(day, len(rows) - n0, "signals replayed; API calls so far", src.calls, flush=True)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="") as h:
            w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    (out.parent / "ladder_replay.md").write_text("\n".join(summary(rows)) + "\n", encoding="utf-8")
    return out


def _stats(rows: Sequence[dict[str, Any]], key: str) -> dict[str, Any]:
    v = [float(r[key]) for r in rows if r.get(key) not in ("", None)]
    if not v:
        return {"n": 0}
    return {"n": len(v), "win": round(100 * sum(1 for x in v if x > 0) / len(v)), "mean": round(st.mean(v), 1), "median": round(st.median(v), 1), "sum": round(sum(v))}


def summary(rows: Sequence[dict[str, Any]]) -> list[str]:
    L = [f"# Ladder replay of every signal ({len(rows)} signals, {len({r['day'] for r in rows})} days)", "",
         f"Entry 1 minute after the signal at the candle close +{SLIP_PCT:.0f}% slippage; {COST_PCT}% taken off every trade for spread and impact; exits tested minute by minute to 15:25. Percent = option return on the premium.", ""]

    def table(title: str, groups: dict[str, list[dict[str, Any]]]) -> None:
        L.extend([f"## {title}", "", "| Group | Signals | Ladder: win % / mean % | Old rules: win % / mean % | Hold to 15:25: win % / mean % | Ladder minus old (mean) |", "|---|---|---|---|---|---|"])
        for g, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            a, b, c = _stats(rs, "ladder_pct"), _stats(rs, "old_pct"), _stats(rs, "hold_pct")
            if not a["n"]:
                continue
            L.append(f"| {g} | {a['n']} | {a['win']}% / {a['mean']:+} | {b['win']}% / {b['mean']:+} | {c.get('win', '-')}% / {c.get('mean', '-')} | {a['mean'] - b['mean']:+.1f} |")
        L.append("")

    by = defaultdict(list)
    for r in rows:
        by[r["group"]].append(r)
    table("By what happened to the signal", by)
    for side in ("BEARISH", "BULLISH"):
        sub = defaultdict(list)
        for r in rows:
            if r["dir"] == side:
                sub[r["group"]].append(r)
        table(f"{side} signals only ({'puts' if side == 'BEARISH' else 'calls'})", sub)
    days = defaultdict(list)
    for r in rows:
        days[r["day"]].append(r)
    L.extend(["## Per day (all signals not traded, ladder)", "", "| Day | Not-traded signals | Ladder mean % | Win % |", "|---|---|---|---|"])
    for d in sorted(days):
        rs = [r for r in days[d] if r["group"] != "TRADED"]
        s = _stats(rs, "ladder_pct")
        if s["n"]:
            L.append(f"| {d} | {s['n']} | {s['mean']:+} | {s['win']}% |")
    return L


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="2026-08-20")
    a = ap.parse_args()
    print(run(a.since))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
