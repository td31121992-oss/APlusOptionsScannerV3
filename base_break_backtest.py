"""Back-test of the base-break rule (base_break.py) on the stored 1-minute option history, against simpler versions and a random baseline. RESEARCH ONLY.

For every day in data (spot closes at 5-minute resolution, 09:15 on) the SAME rule code that runs live is evaluated minute by minute from 10:00 to 14:00. Each stock / side fires at most once a day. The
outcome of an event is the at-the-money option bought at that bar's close (+1 % slippage; events whose option costs under Rs 3 are dropped as untradeable), held to 15:15 with a -20 % stop (stop first
when a bar touches both), costs 1.5 %: did it reach +40 / +80 / +100 % first (the T1 / T2 / T3 levels of the user's ladder), the best price reached, and the return at 15:15.

Variants, to see what each part of the rule adds:
    base_break      the full rule (market against the trade, stock holding, base, break, momentum)
    no_market       base + break + strength, whatever the market is doing
    no_base         market + strength + a break above the 6-bar high, without the tight-base requirement
    rs_only         market + strength, first minute after 10:00 it holds (no base, no break)
    baseline        random stock and minute on a day when the market was against that side (the average option bought there)

    python base_break_backtest.py              -> data/base_breaks/backtest.md and backtest_events.csv
    python base_break_backtest.py bursts       -> data/base_breaks/backtest_bursts.md: single 5-minute BURST candles (see below)

Burst variants (price only: the stored history has no stock volume): a bar that closes 2 % (or 3 %) or more beyond the previous bar's close, 10:00-14:00, first per stock, side and day, whatever the
market is doing. The option is bought at that burst bar's close (the best a follower reacting to the candle can do) or one bar later (a follower with a small delay):
    burst2          move >= 2 %, entry at the burst bar's close            burst3   the same at >= 3 %
    burst2_quiet    move >= 2 % after a quiet 30 minutes (the 6 bars before stayed within 1.2 %)
    burst2_next     move >= 2 %, entry one bar (5 minutes) later           baseline_all   a random stock, side and minute in the same window on any day
"""

from __future__ import annotations

import sys
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
START, END = "2026-06-01", "2026-10-03"
STOP, SLIP, COST = 0.20, 1.01, 1.5
MIN_PREMIUM = 3.0
N_BARS = 75                                   # 5-minute bars 09:15 ... 15:25 (the stored history is 5-minute)
BAR = 5
BASELINE_SAMPLES = 3000


def spot_worker(sym: str):
    sys.path.insert(0, str(ROOT))
    from options_history import load_series

    try:
        df = load_series(sym, "CALL", offset=0, start=START, end=END)
    except Exception:                         # noqa: BLE001
        return sym, {}
    if df is None or df.empty:
        return sym, {}
    df = df[~df.index.duplicated()].sort_index()
    out = {}
    for day, g in df.groupby(df.index.date):
        m = ((g.index.hour * 60 + g.index.minute).values - 555) // BAR
        sp = g.spot.values.astype(float)
        ok = (m >= 0) & (m < N_BARS) & (sp > 0)
        if ok.sum() < 60:
            continue
        arr = np.full(N_BARS, np.nan)
        arr[m[ok]] = sp[ok]
        s = pd.Series(arr).ffill().bfill().values
        out[str(day)] = s
    return sym, out


def detect(spots: dict[str, dict[str, np.ndarray]]):
    import base_break as bb

    days = sorted({d for v in spots.values() for d in v})
    events = defaultdict(list)                # variant -> list of dicts
    red_minutes = []                          # (day, idx, side) market states for the baseline
    for day in days:
        syms = [s for s in spots if day in spots[s]]
        if len(syms) < bb.MIN_STOCKS:
            continue
        S = np.vstack([spots[s][day] for s in syms])
        fired = defaultdict(set)              # variant -> {(sym, side)}
        for i in range((bb.FIRST_MIN - 555) // BAR, (bb.LAST_MIN - 555) // BAR + 1):
            r = (S[:, i] / S[:, 0] - 1.0) * 100.0
            mkt = float(np.median(r))
            up = float((r > 0).mean())
            side_mkt = 1 if (mkt <= -bb.MARKET_MOVE and up <= bb.MAX_BREADTH) else -1 if (mkt >= bb.MARKET_MOVE and up >= 1 - bb.MAX_BREADTH) else 0
            if side_mkt:
                red_minutes.append((day, i, side_mkt))
            rs_up, rs_dn = r - mkt >= bb.MIN_RS, r - mkt <= -bb.MIN_RS
            cand = np.where(rs_up | rs_dn)[0]
            for j in cand:
                sym = syms[j]
                closes = S[j, : i + 1]
                side_rs = 1 if rs_up[j] else -1
                price = float(closes[-1])
                base = dict(symbol=sym, day=day, idx=i, price=price, rs=float(side_rs * (r[j] - mkt)))
                if side_mkt == side_rs and (sym, side_rs) not in fired["rs_only"]:
                    fired["rs_only"].add((sym, side_rs))
                    events["rs_only"].append({**base, "side": side_rs})
                e = bb.check(closes, side_rs, mkt, up, gate=False)
                if e is not None and (sym, side_rs) not in fired["no_market"]:
                    fired["no_market"].add((sym, side_rs))
                    events["no_market"].append({**base, "side": side_rs, "mkt_state": side_mkt})
                if side_mkt == side_rs:
                    e = bb.check(closes, side_rs, mkt, up)
                    if e is not None and (sym, side_rs) not in fired["base_break"]:
                        fired["base_break"].add((sym, side_rs))
                        events["base_break"].append({**base, "side": side_rs})
                    e = bb.check(closes, side_rs, mkt, up, base_range=None)
                    if e is not None and (sym, side_rs) not in fired["no_base"]:
                        fired["no_base"].add((sym, side_rs))
                        events["no_base"].append({**base, "side": side_rs})
    rng = np.random.default_rng(11)
    pick = rng.choice(len(red_minutes), size=min(BASELINE_SAMPLES, len(red_minutes)), replace=False)
    for k in pick:
        day, i, side = red_minutes[int(k)]
        syms = [s for s in spots if day in spots[s]]
        sym = syms[int(rng.integers(len(syms)))]
        events["baseline"].append({"symbol": sym, "day": day, "idx": i, "side": side, "price": float(spots[sym][day][i]), "rs": 0.0})
    return events


def detect_bursts(spots: dict[str, dict[str, np.ndarray]], pct: float = 2.0):
    events = defaultdict(list)
    first = (600 - 555) // BAR
    last = (840 - 555) // BAR
    allmin = []
    for sym, days in spots.items():
        for day, c in days.items():
            fired = defaultdict(set)
            for i in range(first, last + 1):
                allmin.append((sym, day, i))
                r = (c[i] / c[i - 1] - 1.0) * 100.0
                for thr, name in ((pct, "burst2"), (pct * 1.5, "burst3")):
                    if abs(r) >= thr:
                        side = 1 if r > 0 else -1
                        base = {"symbol": sym, "day": day, "side": side, "rs": r}
                        if side not in fired[name]:
                            fired[name].add(side)
                            events[name].append({**base, "idx": i, "price": float(c[i])})
                            if name == "burst2":
                                if i + 1 < N_BARS:
                                    events["burst2_next"].append({**base, "idx": i + 1, "price": float(c[i + 1])})
                                prior = c[max(0, i - 6):i]
                                if len(prior) == 6 and (prior.max() - prior.min()) / prior.mean() * 100 <= 1.2:
                                    events["burst2_quiet"].append({**base, "idx": i, "price": float(c[i])})
    rng = np.random.default_rng(5)
    for k in rng.choice(len(allmin), size=min(BASELINE_SAMPLES, len(allmin)), replace=False):
        sym, day, i = allmin[int(k)]
        events["baseline_all"].append({"symbol": sym, "day": day, "idx": i, "side": int(rng.choice([1, -1])), "price": float(spots[sym][day][i]), "rs": 0.0})
    return events


def outcome(mins: np.ndarray, hi: np.ndarray, lo: np.ndarray, cl: np.ndarray, k: int):
    entry = cl[k] * SLIP
    stop = entry * (1 - STOP)
    best, hit = 0.0, {40: 0, 80: 0, 100: 0}
    ret = None
    for j in range(k + 1, len(mins)):
        if lo[j] <= stop:
            ret = (min(stop, cl[j]) / entry - 1) * 100 - COST
            break
        best = max(best, hi[j] / entry - 1)
        for lv in hit:
            if best >= lv / 100.0:
                hit[lv] = 1
        if mins[j] >= 915:
            ret = (cl[j] / entry - 1) * 100 - COST
            break
    if ret is None:
        ret = (cl[-1] / entry - 1) * 100 - COST
    return {"best": best * 100, "hit40": hit[40], "hit80": hit[80], "hit100": hit[100], "ret": ret, "entry_px": float(cl[k])}


def outcome_worker(args):
    sym, items = args
    sys.path.insert(0, str(ROOT))
    from options_history import load_series

    res = []
    for side_name, side in (("CALL", 1), ("PUT", -1)):
        its = [x for x in items if x["side"] == side]
        if not its:
            continue
        parts = []
        for off in range(-3, 4):
            try:
                df = load_series(sym, side_name, offset=off, start=START, end=END)
            except Exception:                 # noqa: BLE001
                continue
            if df is not None and not df.empty:
                parts.append(df)
        if not parts:
            continue
        allo = pd.concat(parts)
        allo = allo.assign(date=allo.index.date.astype(str), minute=allo.index.hour * 60 + allo.index.minute)
        by_day = {d: g for d, g in allo.groupby("date")}
        for it in its:
            g = by_day.get(it["day"])
            if g is None:
                continue
            m = it["idx"] * BAR + 555
            at = g[g.minute == m]
            if at.empty:
                continue
            at = at.assign(dist=(at.strike - it["price"]).abs()).sort_values("dist")
            k_strike = float(at.strike.iloc[0])
            path = g[g.strike == k_strike].sort_index()
            path = path[~path.index.duplicated()]
            mins, hi, lo, cl = path.minute.values, path.high.values.astype(float), path.low.values.astype(float), path.close.values.astype(float)
            w = np.where(mins == m)[0]
            if not len(w) or cl[w[0]] < MIN_PREMIUM or w[0] >= len(mins) - 2:
                continue
            res.append({**it, **outcome(mins, hi, lo, cl, int(w[0]))})
    return res


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (0, 0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return round(100 * max(0, c - h)), round(100 * min(1, c + h))


def table(df: pd.DataFrame) -> list[str]:
    L = ["| Variant | Side | Events | Days with events | Positive at 15:15 | Hit +40% | Hit +80% | Hit +100% (95% CI) | Mean best | Mean return |", "|---|---|---|---|---|---|---|---|---|---|"]
    order = ["base_break", "no_market", "no_base", "rs_only", "baseline", "burst2", "burst3", "burst2_quiet", "burst2_next", "baseline_all"]
    for v in order:
        for side, name in ((1, "CALL"), (-1, "PUT")):
            g = df[(df.variant == v) & (df.side == side)]
            if g.empty:
                continue
            ci = wilson(int(g.hit100.sum()), len(g))
            L.append(f"| {v} | {name} | {len(g)} | {g.day.nunique()} | {100 * (g.ret > 0).mean():.0f}% | {100 * g.hit40.mean():.0f}% | {100 * g.hit80.mean():.0f}% | {100 * g.hit100.mean():.0f}% ({ci[0]}-{ci[1]}) | {g.best.mean():+.0f}% | {g.ret.mean():+.1f}% |")
    return L


def main() -> int:
    bursts = len(sys.argv) > 1 and sys.argv[1] == "bursts"
    sys.path.insert(0, str(ROOT))
    from options_history import DEFAULT_ROOT

    syms = sorted(d.name for d in DEFAULT_ROOT.iterdir() if d.is_dir())
    print("symbols", len(syms), flush=True)
    spots = {}
    with Pool(6) as pool:
        for n, (s, d) in enumerate(pool.imap_unordered(spot_worker, syms), 1):
            if d:
                spots[s] = d
            if n % 40 == 0:
                print("spot loaded", n, flush=True)
    print("stocks with spot", len(spots), "days", len({d for v in spots.values() for d in v}), flush=True)
    events = detect_bursts(spots) if bursts else detect(spots)
    print({k: len(v) for k, v in events.items()}, flush=True)
    work = defaultdict(list)
    for v, lst in events.items():
        for e in lst:
            work[e["symbol"]].append({**e, "variant": v})
    rows = []
    with Pool(6) as pool:
        for n, r in enumerate(pool.imap_unordered(outcome_worker, list(work.items())), 1):
            rows += r
            if n % 30 == 0:
                print("outcomes", n, len(rows), flush=True)
    df = pd.DataFrame(rows)
    out = ROOT / "data" / "base_breaks"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / ("backtest_bursts_events.csv" if bursts else "backtest_events.csv"), index=False)
    lost = {k: len(v) - int((df.variant == k).sum()) for k, v in events.items()}
    L = ["# Base-break back-test (research only)", "",
         f"5-minute bars from {START} to {END}. Rule: market against the trade (median stock {1.0:.0f}%+ the other way, at most 35% of stocks with it), stock 1.5%+ ahead, 6-bar (30-minute) base within 1.2%, close 0.15% beyond the base, +0.3% on the bar, 10:00-14:00, first break per stock and day.",
         "Outcome = the ATM option bought at that bar's close (+1% slippage), -20% stop, to 15:15, costs 1.5%. Options under Rs 3 are dropped (untradeable).", ""] + table(df)
    L += ["", f"Events dropped for a missing / too cheap option: {lost}", "", "Hit +40/+80/+100 = the option reached that gain before a -20% stop (the T1/T2/T3 levels of the user's ladder)."]
    if bursts:
        L[0] = "# Burst-candle back-test (research only)"
        L[2] = "Burst = a 5-minute bar closing 2 % (3 %) or more beyond the previous close, 10:00-14:00, first per stock, side and day; see base_break_backtest.py for the variants."
    (out / ("backtest_bursts.md" if bursts else "backtest.md")).write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
