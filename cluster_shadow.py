"""Cluster (footprint) features at a level break (SHADOW ONLY: a nightly ledger and review; nothing trades on it).

A candle chart shows price; a cluster chart shows, at each price inside the candle, how much was bought at the ask and sold at the bid. The recorded stock ticks (data/ticks/<day>/<SYMBOL>.csv.gz,
tagged buyer- / seller-initiated by tick_recorder.py, approximate) are enough to rebuild that for the candle in which price crosses a level. For every level-cross signal of the day (the previous-day high / low or
the 15-minute opening-range high / low, first per stock, side and day - the plain rule of breakout_rule_shadow.py with no other filter) this records, for the break candle:

    stack     the longest run of price levels in a row where aggressive volume in our direction is at least 3x the opposing volume one level below (long) / above (short): a "stacked imbalance"
    poc       where the most-traded price sits in the candle, 0 = the unfavourable end, 1 = the favourable end
    beyond    share of the candle's volume traded beyond the broken level
    beyond_imb  buy minus sell volume beyond the level, in our direction, -1 .. +1

and follows the option (nearest-the-money, next candle's open, the live ladder: breakout_rule_shadow.follow_option). On 22 / 23 / 26 Oct (651 signals) the one feature that separated results was `stack`:
0 - 1 stacked levels: win 55 %, mean +0.1 %, -Rs 227 a trade; 2 or more: win 60 - 65 %, +Rs 970 to +Rs 2,000 a trade. POC and the volume beyond the level did not. Three days, so this ledger keeps counting.

    data/cluster_shadow/ledger.csv   one row per signal
    data/cluster_shadow/review.md    the splits above over every day recorded

    python cluster_shadow.py [YYYY-MM-DD ...]   rebuild those days (default today) and the review
"""

from __future__ import annotations

import collections
import csv
import json
import statistics as st
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
FOLDER = ("data", "cluster_shadow")
FIELDS = ["day", "symbol", "side", "time", "level", "stack", "poc", "beyond", "beyond_imb", "entry", "peak_pct", "exit", "why", "gross_pct", "net_rs"]
LEVEL_ONLY = frozenset({"volume", "vwap", "ema", "rsi", "gap"})
MIN_LEVEL_SHARE = 0.05


def read_ticks(root: Path, day: str, symbol: str) -> list[tuple[int, float, float, str]]:
    """(minute, price, traded quantity, side B / S) of the tagged ticks of one stock-day."""
    import tick_gz
    path = root / "data" / "ticks" / day / f"{symbol}.csv.gz"
    out: list[tuple[int, float, float, str]] = []
    if not path.exists():
        return out
    text, _members, _bad = tick_gz.read_text(path)
    for line in text.splitlines()[1:]:
        f = line.split(",")
        if len(f) < 16 or f[15] not in ("B", "S"):
            continue
        try:
            out.append((int(f[0][:2]) * 60 + int(f[0][3:5]), float(f[2]), float(f[14] or 0), f[15]))
        except ValueError:
            continue
    return out


def cluster(ticks: Sequence[tuple[int, float, float, str]], minute: int, side: int, level: float) -> dict[str, float] | None:
    """Cluster features of the 5-minute candle starting at `minute` (side +1 long, -1 short); None when it has too few tagged ticks."""
    tk = [t for t in ticks if minute <= t[0] < minute + 5 and t[2] > 0]
    if len(tk) < 20:
        return None
    px = [t[1] for t in tk]
    lo = min(px)
    width = max(0.05, round(sum(px) / len(px) * 0.0004, 2))
    buckets: dict[int, list[float]] = collections.defaultdict(lambda: [0.0, 0.0])
    for _, p, q, s in tk:
        buckets[int((p - lo) / width + 1e-9)][0 if s == "B" else 1] += q
    keys = sorted(buckets)
    total = sum(a + b for a, b in buckets.values())
    if total <= 0:
        return None
    poc = max(keys, key=lambda k: sum(buckets[k]))
    span = max(keys[-1] - keys[0], 1)
    poc_pos = (poc - keys[0]) / span
    run = best = 0
    for k in (keys if side > 0 else keys[::-1]):
        mine_k = buckets[k][0 if side > 0 else 1]
        other = buckets.get(k - 1 if side > 0 else k + 1, [0, 0])[1 if side > 0 else 0]
        ok = mine_k >= 3 * max(other, 1) and mine_k >= MIN_LEVEL_SHARE * total                     # a real imbalance: 3x the opposing volume one level away AND a meaningful share of the candle
        run = run + 1 if ok and sum(buckets[k]) > 0 else 0
        best = max(best, run)

    def beyond(k: int) -> bool:
        return lo + k * width >= level if side > 0 else lo + k * width <= level
    vol_b = sum(sum(v) for k, v in buckets.items() if beyond(k))
    mine = sum(v[0 if side > 0 else 1] for k, v in buckets.items() if beyond(k))
    theirs = sum(v[1 if side > 0 else 0] for k, v in buckets.items() if beyond(k))
    return {"stack": float(best), "poc": poc_pos if side > 0 else 1 - poc_pos, "beyond": vol_b / total, "beyond_imb": (mine - theirs) / (mine + theirs) if mine + theirs > 0 else 0.0}


def day_rows(day: str, root: Path = ROOT) -> list[dict[str, Any]]:
    import breakout_rule_shadow as brs
    universe = sorted(json.loads((root / "data" / "ticks" / "rs_all.json").read_text(encoding="utf-8")).get("stocks", {}))
    dhan = brs.Dhan(root)
    candles = brs.stock_candles(universe, day, root, dhan)
    opts = brs.OptionCache(dhan)
    out = []
    for sym in universe:
        for sg in brs.signals_for(candles.get(sym) or [], {day}, LEVEL_ONLY):
            side = 1 if sg["side"] == "LONG" else -1
            cl = cluster(read_ticks(root, day, sym), sg["minute"], side, sg["level"])
            opt = brs.option_for(sym, sg["side"], day, sg["close"], root) if cl else None
            res = brs.follow_option(opts.get(opt[0], day), day, sg["minute"]) if opt else {}
            if cl and res:
                out.append({"day": day, "symbol": sym, "side": sg["side"], "time": f"{sg['minute'] // 60:02d}:{sg['minute'] % 60:02d}", "level": sg["level"], **{k: round(v, 3) for k, v in cl.items()},
                            "entry": round(res["entry"], 2), "peak_pct": round(res["peak_pct"], 1), "exit": round(res["exit"], 2), "why": res["why"], "gross_pct": round(res["gross_pct"], 1), "net_rs": round(res["net_rs"])})
    opts.save()
    return out


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def review(rows: Sequence[Mapping[str, Any]]) -> str:
    days = sorted({r["day"] for r in rows})
    lines = ["# Cluster features at a level break (shadow; nothing trades on this)", "", f"Days: {len(days)} ({days[0] if days else '-'} .. {days[-1] if days else '-'}); signals: {len(rows)}. Option, fills and ladder as in breakout_rule_shadow.py.", ""]

    def block(title: str, groups: Sequence[tuple[str, Sequence[Mapping[str, Any]]]]) -> None:
        lines.extend([f"### {title}", "", "| group | trades | win % | never +1 % | reached +40 % | mean gross | net Rs per trade |", "|---|---|---|---|---|---|---|"])
        for name, g in groups:
            if g:
                n = len(g)
                lines.append(f"| {name} | {n} | {100 * sum(_f(r['net_rs']) > 0 for r in g) / n:.0f}% | {100 * sum(_f(r['peak_pct']) < 1 for r in g) / n:.0f}% | {100 * sum(_f(r['peak_pct']) >= 40 for r in g) / n:.0f}% | "
                             f"{st.mean(_f(r['gross_pct']) for r in g):+.1f}% | {sum(_f(r['net_rs']) for r in g) / n:+,.0f} |")
        lines.append("")
    if rows:
        block("All level breaks", [("all", rows)])
        block("Stacked imbalances in the break candle", [("0 - 1", [r for r in rows if _f(r["stack"]) <= 1]), ("2", [r for r in rows if _f(r["stack"]) == 2]), ("3 or more", [r for r in rows if _f(r["stack"]) >= 3])])
        block("Point of control (0 = unfavourable end of the candle, 1 = favourable)", [("under 0.33", [r for r in rows if _f(r["poc"]) < 0.33]), ("0.33 - 0.67", [r for r in rows if 0.33 <= _f(r["poc"]) <= 0.67]),
                                                                                         ("over 0.67", [r for r in rows if _f(r["poc"]) > 0.67])])
        block("Buy minus sell beyond the level, in our direction", [("negative", [r for r in rows if _f(r["beyond_imb"]) < 0]), ("positive", [r for r in rows if _f(r["beyond_imb"]) >= 0])])
    lines.append("Judge it on forward days: the 3-day sample behind this module is small.")
    return "\n".join(lines) + "\n"


def run(days: Sequence[str], root: Path = ROOT) -> Path:
    folder = root.joinpath(*FOLDER)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "ledger.csv"
    old: list[dict[str, str]] = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as h:
            old = [r for r in csv.DictReader(h) if r["day"] not in set(days)]
    rows: list[Mapping[str, Any]] = list(old)
    for d in days:
        rows += day_rows(d, root)
    rows = sorted(rows, key=lambda r: (r["day"], r["time"]))
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    out = folder / "review.md"
    out.write_text(review(rows), encoding="utf-8")
    return out


if __name__ == "__main__":
    ds = sys.argv[1:] or [datetime.now(IST).strftime("%Y-%m-%d")]
    print(run(ds))
    print((ROOT.joinpath(*FOLDER) / "review.md").read_text(encoding="utf-8"))
