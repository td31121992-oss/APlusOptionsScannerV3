"""Daily study of every F&O stock's chart behaviour (RESEARCH / DISPLAY ONLY: it classifies what each stock did and builds each stock's personality; nothing trades on it).

Every night the day's 5-minute closes of all 213 stocks (from the recorded ticks) are classified, and every stock's profile over its last PROFILE_DAYS days is rebuilt. The same classifier runs over the 87 days of
stored history (python stock_study.py backfill) so profiles are filled from day one.

DAY PATTERN (one label per stock per day, first rule that matches):
    TIGHT_RANGE        the whole day moved less than 1 %
    LATE_SURGE         the last 90 minutes made at least 1 % and 60 % of the day's range (checked before TREND: a flat day that moves at the end is not a trend day)
    TREND_UP / TREND_DOWN   closed in the top / bottom 20 % of the day's range, net move at least 60 % of the range, and pushed through the first-hour range by half its width
    REVERSAL_UP / REVERSAL_DOWN   the day's low (high) came in the first 90 minutes, the close is in the top (bottom) 30 % of the range, and the range is 1.5 %+  (a V / inverted V)
    GAP_AND_GO / GAP_FADE   opened 0.5 %+ away from the previous close and then kept going that way (net move at least half the gap) / came back against it (net move the other way by 0.3 %+)
    RANGE_BOUND        neither side of the first-hour range was extended by a quarter of its width
    CHOPPY             anything else
    Extra facts per day: gap %, range %, net move %, close position in the range, efficiency (net move / path travelled), first-hour range extension up / down (in first-hour widths), the opening-range
    (first 15 minutes) break and whether it HELD to the close, the hour of the day's high and low.

PERSONALITY (per stock, last 60 days): share of days of each pattern, average range, average absolute move, beta to the market (slope of the stock's net move on the median stock's net move), opening-range
break follow-through (how often a break held to the close), gap-fill rate, the modal hour of the day's high and low, and the last 15 days' pattern strip.

    data/stock_study/daily.csv         one row per stock per day (appended; a re-run of the same day replaces it)
    data/stock_study/profiles.json     every stock's personality + today's row, for the /stock-study page

    python stock_study.py backfill     classify the stored history (5-minute option-history spot series) and any recorded tick days
    python stock_study.py day YYYY-MM-DD   classify one recorded tick day and rebuild the profiles
"""

from __future__ import annotations

import csv
import json
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parent
OPEN_S = 9 * 3600 + 15 * 60
N_BARS = 75
BAR_S = 300
PROFILE_DAYS = 60
STRIP_DAYS = 15
PATTERNS = ["TREND_UP", "TREND_DOWN", "REVERSAL_UP", "REVERSAL_DOWN", "GAP_AND_GO", "GAP_FADE", "LATE_SURGE", "RANGE_BOUND", "TIGHT_RANGE", "CHOPPY"]
FIELDS = ["day", "symbol", "pattern", "gap_pct", "range_pct", "move_pct", "close_pos", "efficiency", "ib_up", "ib_dn", "orb", "orb_held", "hi_hour", "lo_hour", "spark"]
DAILY = ("data", "stock_study", "daily.csv")
PROFILES = ("data", "stock_study", "profiles.json")


def classify(closes: Sequence[float], prev_close: float | None) -> dict[str, Any] | None:
    """The day's pattern and facts from the 5-minute closes (index 0 = the 09:15 bar). None when there are fewer than 60 bars."""
    c = np.asarray(closes, dtype=float)
    if len(c) < 60 or c[0] <= 0 or not np.isfinite(c).all():
        return None
    o, hi, lo, close = c[0], c.max(), c.min(), c[-1]
    rng = (hi - lo) / o * 100.0
    move = (close / o - 1.0) * 100.0
    path = float(np.abs(np.diff(c)).sum())
    eff = abs(close - o) / path if path > 0 else 0.0
    pos = (close - lo) / (hi - lo) if hi > lo else 0.5
    prev = prev_close if prev_close and prev_close > 0 else o
    gap = (o / prev - 1.0) * 100.0
    t_hi, t_lo = int(np.argmax(c)), int(np.argmin(c))
    ib = c[:12]
    ib_hi, ib_lo = ib.max(), ib.min()
    w = max(ib_hi - ib_lo, o * 0.0005)
    ib_up, ib_dn = max(0.0, (hi - ib_hi) / w), max(0.0, (ib_lo - lo) / w)
    o3 = c[:3]
    or_hi, or_lo = o3.max(), o3.min()
    orb, held = 0, None
    for k in range(3, len(c)):
        if c[k] > or_hi:
            orb = 1
            break
        if c[k] < or_lo:
            orb = -1
            break
    if orb:
        held = bool(close > or_hi) if orb > 0 else bool(close < or_lo)
    last = c[-18:]
    late = (last[-1] / last[0] - 1.0) * 100.0
    if rng < 1.0:
        pat = "TIGHT_RANGE"
    elif abs(late) >= 1.0 and abs(late) >= 0.6 * rng:
        pat = "LATE_SURGE"
    elif pos >= 0.8 and abs(move) >= 0.6 * rng and move > 0 and ib_up >= 0.5:
        pat = "TREND_UP"
    elif pos <= 0.2 and abs(move) >= 0.6 * rng and move < 0 and ib_dn >= 0.5:
        pat = "TREND_DOWN"
    elif rng >= 1.5 and t_lo < 18 and pos >= 0.7:
        pat = "REVERSAL_UP"
    elif rng >= 1.5 and t_hi < 18 and pos <= 0.3:
        pat = "REVERSAL_DOWN"
    elif abs(gap) >= 0.5 and move * gap > 0 and abs(move) >= 0.5 * abs(gap):
        pat = "GAP_AND_GO"
    elif abs(gap) >= 0.5 and move * gap < 0 and abs(move) >= 0.3:
        pat = "GAP_FADE"
    elif ib_up < 0.25 and ib_dn < 0.25:
        pat = "RANGE_BOUND"
    else:
        pat = "CHOPPY"
    hour = lambda k: 9 + (15 + 5 * k) // 60 if True else 0
    spark = [round(float(x), 2) for x in (c[::5] / o * 100.0)]                      # 15 points, normalised to the open = 100
    return {"pattern": pat, "gap_pct": round(gap, 2), "range_pct": round(rng, 2), "move_pct": round(move, 2), "close_pos": round(float(pos), 2), "efficiency": round(float(eff), 2),
            "ib_up": round(float(ib_up), 2), "ib_dn": round(float(ib_dn), 2), "orb": orb, "orb_held": held, "hi_hour": hour(t_hi), "lo_hour": hour(t_lo), "spark": spark}


def bars_from_samples(series: Sequence[tuple[float, float]]) -> list[float] | None:
    """5-minute closes (the last price in each bucket, carried forward over empty ones) from (seconds of day, price) samples."""
    out: list[float] = []
    k, last = 0, None
    for t, p in series:
        if t < OPEN_S:
            continue
        idx = int((t - OPEN_S) // BAR_S)
        if idx >= N_BARS:
            break
        while len(out) < idx:
            out.append(last if last is not None else p)
        last = p
        if len(out) == idx:
            out.append(p)
        else:
            out[idx] = p
    return out if len(out) >= 60 else None


def read_daily(root: Path) -> list[dict[str, Any]]:
    try:
        with root.joinpath(*DAILY).open(encoding="utf-8", newline="") as h:
            return list(csv.DictReader(h))
    except OSError:
        return []


def write_daily(root: Path, rows: list[dict[str, Any]]) -> None:
    p = root.joinpath(*DAILY)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (str(r["day"]), str(r["symbol"])))
    with p.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            r = dict(r)
            if isinstance(r.get("spark"), list):
                r["spark"] = " ".join(str(x) for x in r["spark"])
            w.writerow({k: r.get(k, "") for k in FIELDS})


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def build_profiles(rows: list[dict[str, Any]], sectors: dict[str, str] | None = None) -> dict[str, Any]:
    """Personality of every stock over its last PROFILE_DAYS days, plus the latest day's row."""
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_day[str(r["day"])].append(r)
        by_sym[str(r["symbol"])].append(r)
    mkt = {d: st.median(_f(x["move_pct"]) for x in v) for d, v in by_day.items() if len(v) >= 50}
    days = sorted(by_day)
    out: dict[str, Any] = {"day": days[-1] if days else "", "days": len(days), "stocks": {}}
    for sym, lst in by_sym.items():
        lst = sorted(lst, key=lambda r: str(r["day"]))
        recent = lst[-PROFILE_DAYS:]
        n = len(recent)
        cnt = Counter(str(r["pattern"]) for r in recent)
        xs = [mkt[str(r["day"])] for r in recent if str(r["day"]) in mkt]
        ys = [_f(r["move_pct"]) for r in recent if str(r["day"]) in mkt]
        beta = None
        if len(xs) >= 15 and np.var(xs) > 0:
            beta = round(float(np.cov(xs, ys, bias=True)[0, 1] / np.var(xs)), 2)
        orb = [r for r in recent if str(r.get("orb")) in ("1", "-1")]
        held = [r for r in orb if str(r.get("orb_held")) in ("True", "true", "1")]
        gaps = [r for r in recent if abs(_f(r["gap_pct"])) >= 0.5]
        hi_h = Counter(int(_f(r["hi_hour"])) for r in recent)
        lo_h = Counter(int(_f(r["lo_hour"])) for r in recent)
        last = lst[-1]
        out["stocks"][sym] = {"sec": (sectors or {}).get(sym, ""), "n": n, "mix": {p: round(100.0 * cnt[p] / n) for p in PATTERNS if cnt[p]}, "avg_range": round(st.mean(_f(r["range_pct"]) for r in recent), 2),
                              "avg_abs_move": round(st.mean(abs(_f(r["move_pct"])) for r in recent), 2), "beta": beta, "orb_follow": None if len(orb) < 8 else round(100.0 * len(held) / len(orb)),
                              "gap_days": len(gaps), "hi_hour": hi_h.most_common(1)[0][0] if hi_h else None, "lo_hour": lo_h.most_common(1)[0][0] if lo_h else None,
                              "strip": [str(r["pattern"]) for r in lst[-STRIP_DAYS:]], "today": {k: last.get(k) for k in ("day", "pattern", "gap_pct", "range_pct", "move_pct", "close_pos", "efficiency", "orb", "orb_held")},
                              "spark": [float(x) for x in str(last.get("spark") or "").split()]}
    return out


def save_profiles(root: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    sectors: dict[str, str] = {}
    try:
        import money_flow

        sectors = money_flow._sector_map(root)
    except Exception:                                      # noqa: BLE001
        pass
    prof = build_profiles(rows, sectors)
    p = root.joinpath(*PROFILES)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(prof), encoding="utf-8")
    tmp.replace(p)
    return prof


def study_day(root: Path, day: str) -> int:
    """Classify one recorded tick day for all stocks, replace that day's rows and rebuild the profiles. Returns the number of stocks classified."""
    import rs_leaders
    import rs_replay

    samples = rs_replay.load_samples(root, day)
    if not samples:
        return 0
    ref = rs_leaders.load_reference(root, day)
    new = []
    for sym, series in rs_replay.series_by_symbol(samples).items():
        bars = bars_from_samples(series)
        c = classify(bars, (ref.get(sym) or {}).get("prev_close")) if bars else None
        if c:
            new.append({"day": day, "symbol": sym, **c})
    rows = [r for r in read_daily(root) if str(r["day"]) != day] + new
    write_daily(root, rows)
    save_profiles(root, read_daily(root))
    return len(new)


def run(day: str, root: Path = ROOT) -> None:
    study_day(root, day)


def backfill(root: Path = ROOT) -> int:
    """Classify the stored 5-minute history (all stocks, every day) and any recorded tick days."""
    from multiprocessing import Pool

    import base_break_backtest as bt
    from options_history import DEFAULT_ROOT

    syms = sorted(d.name for d in DEFAULT_ROOT.iterdir() if d.is_dir())
    spots: dict[str, dict[str, np.ndarray]] = {}
    with Pool(6) as pool:
        for s, d in pool.imap_unordered(bt.spot_worker, syms):
            if d:
                spots[s] = d
    rows = []
    for sym, days in spots.items():
        prev = None
        for day in sorted(days):
            arr = days[day]
            c = classify(arr, prev)
            if c:
                rows.append({"day": day, "symbol": sym, **c})
            prev = float(arr[-1])
    have = {(r["day"], r["symbol"]) for r in rows}
    old = [r for r in read_daily(root) if (str(r["day"]), str(r["symbol"])) not in have]
    write_daily(root, rows + old)
    save_profiles(root, read_daily(root))
    return len(rows)


def payload(root: Path = ROOT) -> dict[str, Any]:
    try:
        return {**json.loads(root.joinpath(*PROFILES).read_text(encoding="utf-8")), "ok": True, "patterns": PATTERNS}
    except (OSError, ValueError):
        return {"ok": False, "error": "no study yet (run: python stock_study.py backfill)"}


def main() -> int:
    a = sys.argv[1:]
    if a and a[0] == "backfill":
        print("classified", backfill(), "stock-days")
    elif a and a[0] == "day" and len(a) > 1:
        print("classified", study_day(ROOT, a[1]), "stocks")
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
