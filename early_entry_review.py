"""Earlier-entry shadow: what if each trade had been entered when its signal was FIRST flagged instead of after the waits? (research only; changes nothing)

Traded signals were first flagged a median 11.5 minutes before the actual entry (1-16 Oct), and the stock's 60-minute move from the first flag was +0.19% against
+0.00% from the real entry. The A+ / V2 / safety waits cost the first part of the move. This measures that on the OPTION for every trade:

    flag time    the first time the signal was entry-ready (data/missed_opportunities/<day>/option_returns.json, fate TRADED, "ready")
    from flag    the same ATM-style path statistics as the other reports, started at the flag candle (+1% on the candle close)
    from entry   the same statistics started at the real entry time, on the SAME contract the trade bought
    real         the trade's own recorded return

    data/shadow_rules/early_entry/<day>.csv      data/shadow_rules/early_entry.md

Bar for "supports entering earlier": 30+ matched trades on 5+ days, the flag-start mean close better than the entry-start mean by 3+ points, and better on 60%+ of days.
Research only: the waits exist for reasons (A+ and V2 saved us from many bad entries), so this is a measurement, not a recommendation.

    python early_entry_review.py [YYYY-MM-DD ...]
"""

from __future__ import annotations

import csv
import glob
import json
import statistics as st
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable

import option_scan as osn

ROOT = Path(__file__).resolve().parent
FIELDS = ["day", "symbol", "dir", "flag_time", "entry_time", "delay_min", "flag_entry", "flag_best", "flag_worst", "flag_close", "flag_stop_first",
          "act_entry", "act_best", "act_worst", "act_close", "act_stop_first", "real_return_pct"]


def _mins(h: str) -> int:
    a, b = str(h).split(":")[:2]
    return int(a) * 60 + int(b)


def trades_for(day: str, root: Path) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for name in ("paper_trade_history.json", "paper_trades_latest.json"):
        try:
            data = json.loads((root / "data" / "reports" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for t in data.get("paper_trades", []) if isinstance(data, dict) else data:
            if str(t.get("entry_time") or "")[:10] == day and t.get("option_security_id"):
                seen[str(t.get("paper_trade_id"))] = t
    return list(seen.values())


def run(day: str, root: Path = ROOT, fetch: Callable[[int, str], list] = osn.fetch_bars) -> Path | None:
    try:
        sigs = [r for r in json.loads((root / "data" / "missed_opportunities" / day / "option_returns.json").read_text(encoding="utf-8"))
                if r.get("kind") == "ATM" and str(r.get("fate")) == "TRADED"]
    except (OSError, ValueError):
        return None
    flag = {}
    for r in sorted(sigs, key=lambda x: str(x.get("ready"))):
        flag.setdefault((r["symbol"], r.get("dir")), r["ready"])
    rows = []
    for t in trades_for(day, root):
        d = "BULLISH" if str(t.get("option_type")).upper() == "CE" else "BEARISH"
        fl = flag.get((t["symbol"], d))
        if not fl:
            continue
        em = int(str(t["entry_time"])[11:13]) * 60 + int(str(t["entry_time"])[14:16])
        fm = _mins(fl)
        bars = fetch(int(float(t["option_security_id"])), day)
        a, b = osn.path_stats(bars, fm), osn.path_stats(bars, em)
        if not a or not b:
            continue
        rows.append({"day": day, "symbol": t["symbol"], "dir": d, "flag_time": fl, "entry_time": str(t["entry_time"])[11:16], "delay_min": em - fm,
                     "flag_entry": a["entry"], "flag_best": a["best"], "flag_worst": a["worst"], "flag_close": a["close"], "flag_stop_first": int(a["stop_first"]),
                     "act_entry": b["entry"], "act_best": b["best"], "act_worst": b["worst"], "act_close": b["close"], "act_stop_first": int(b["stop_first"]),
                     "real_return_pct": t.get("return_percent", "")})
    folder = root / "data" / "shadow_rules" / "early_entry"
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


def verdict(rows: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    why = []
    if len(rows) < 30:
        why.append(f"{len(rows)} of 30 matched trades")
    days = defaultdict(list)
    for r in rows:
        days[r["day"]].append(_f(r["flag_close"]) - _f(r["act_close"]))
    if len(days) < 5:
        why.append(f"{len(days)} of 5 days")
    if rows:
        gain = st.mean(_f(r["flag_close"]) - _f(r["act_close"]) for r in rows)
        if gain < 3.0:
            why.append(f"flag start only {gain:+.1f} points better (needs 3+)")
        better = sum(1 for v in days.values() if st.mean(v) > 0)
        if days and better / len(days) < 0.6:
            why.append(f"better on only {better} of {len(days)} days")
    return (not why and bool(rows)), why


def write_summary(root: Path = ROOT) -> Path | None:
    rows: list[dict[str, Any]] = []
    for p in sorted(glob.glob(str(root / "data" / "shadow_rules" / "early_entry" / "20*.csv"))):
        with open(p, encoding="utf-8", newline="") as h:
            rows.extend(r for r in csv.DictReader(h) if _f(r.get("flag_close")) is not None and _f(r.get("act_close")) is not None)
    if not rows:
        return None
    days = sorted({r["day"] for r in rows})
    n = len(rows)

    def block(prefix: str) -> str:
        c = [_f(r[f"{prefix}_close"]) for r in rows]
        b = [_f(r[f"{prefix}_best"]) for r in rows]
        sf = sum(int(r[f"{prefix}_stop_first"]) for r in rows)
        return f"{st.mean(c):+.1f}% | {100 * sum(x > 0 for x in c) / n:.0f}% | {100 * sum(x >= 15 for x in b) / n:.0f}% | {100 * sf / n:.0f}%"

    delays = [_f(r["delay_min"]) for r in rows]
    out = ["# Earlier-entry shadow (research only)", "",
           f"{n} traded signals on {len(days)} day(s) ({days[0]} to {days[-1]}), first flag to real entry: median **{st.median(delays):.0f} min** (mean {st.mean(delays):.0f}). "
           "Same contract, same path statistics; ATM-style option held to close, hindsight, before costs.", "",
           "| Entry point | Mean close | Closed up | Hit +15% | -20% first |", "|---|---|---|---|---|",
           f"| At the first flag | {block('flag')} |", f"| At the real entry | {block('act')} |", ""]
    diff = [_f(r["flag_close"]) - _f(r["act_close"]) for r in rows]
    out += [f"Flag start minus entry start: mean {st.mean(diff):+.1f} points, better in {100 * sum(d > 0 for d in diff) / n:.0f}% of trades.", "",
            "| Day | Trades | Median delay | Mean close from flag | Mean close from entry |", "|---|---|---|---|---|"]
    for d in days:
        g = [r for r in rows if r["day"] == d]
        out.append(f"| {d} | {len(g)} | {st.median(_f(r['delay_min']) for r in g):.0f} min | {st.mean(_f(r['flag_close']) for r in g):+.1f}% | {st.mean(_f(r['act_close']) for r in g):+.1f}% |")
    ok, why = verdict(rows)
    out += ["", f"**Verdict: {'supports looking at earlier entries' if ok else 'not yet'}.**" + ("" if ok else " Missing: " + "; ".join(why) + "."),
            "", "_Research only. The waits exist because A+ and V2 held back many bad entries; nothing here changes trading._", ""]
    path = root / "data" / "shadow_rules" / "early_entry.md"
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def main() -> int:
    import sys

    for d in sys.argv[1:] or [date.today().isoformat()]:
        print(d, run(d), flush=True)
    print(write_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
