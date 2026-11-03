"""Breakout / breakdown combination search (RESEARCH ONLY: reads cached candles, writes a report; nothing trades on it).

The given rule (breakout_rule_shadow.py) is one point in a big space of entry rules. Searching that space on the OPTION outcome would need an option-candle fetch for every signal of every
variant, so the search is scored on the STOCK's own next 60 minutes instead and only the best few are then followed on the option:

    for every 5-minute candle of every F&O stock: the entry is the open of the next candle; looking at the next 12 candles in the trade's direction
        MFE = best excursion in our favour (%), MAE = worst excursion against us (%)
        GOOD   = MFE >= 1.0 % and MAE <= 0.7 %      (a clean move: roughly where an at-the-money option clears its first locks without being stopped)
        NOTHING = MFE < 0.3 %                       (the "0 % profit after entry" case: the move never started)

    a combination = which level is crossed (previous-day high / low, opening range 15 or 30 minutes, the day's running high / low, the previous 12 candles' range) + volume multiple + close against
    VWAP + EMA 9/20 + RSI threshold + gap window + earliest signal time + candle strength. First signal per stock, side and day.
    score = GOOD % - NOTHING %, taken as the WORSE of the first and second half of the days, so a combination has to hold up in both. At least 120 signals (40 in each half).

    python breakout_search.py            search, write data/breakout_rule/search.md
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
CACHE = Path(r"E:\APlusData\shadow_cache") if Path("E:/").exists() else ROOT / "data" / "shadow_cache"
HORIZON = 12
GOOD_MFE, GOOD_MAE, NOTHING_MFE = 1.0, 0.7, 0.3
MIN_N, MIN_HALF = 120, 40


def build(candles: dict) -> dict[str, np.ndarray]:
    """Flat per-candle feature arrays over every stock and day."""
    import breakout_rule_shadow as brs
    cols: dict[str, list] = {k: [] for k in ("sym", "day", "minute", "n", "close", "pclose", "vwap", "pdh", "pdl", "orh15", "orl15", "orh30", "orl30", "hod", "lod", "range_hi", "range_lo", "gap", "volx", "dvol",
                                              "e9", "e20", "rsi", "bodypos", "lmfe", "lmae", "smfe", "smae")}
    syms = sorted(candles)
    for si, sym in enumerate(syms):
        rows = candles[sym]
        if len(rows) < 120:
            continue
        closes = [float(r[5]) for r in rows]
        e9, e20, rs = brs.ema(closes, 9), brs.ema(closes, 20), brs.rsi(closes)
        by_day: dict[str, list[int]] = {}
        for i, r in enumerate(rows):
            by_day.setdefault(r[0], []).append(i)
        days = sorted(by_day)
        dvol = {d: sum(float(rows[i][6]) for i in by_day[d]) for d in days}
        for di, day in enumerate(days):
            if di == 0:
                continue
            prev, idx = by_day[days[di - 1]], by_day[day]
            if len(idx) < 30:
                continue
            pdh, pdl, pclose = max(float(rows[i][3]) for i in prev), min(float(rows[i][4]) for i in prev), float(rows[prev[-1]][5])
            gap = (float(rows[idx[0]][2]) / pclose - 1) * 100
            window = [dvol[d] for d in days[max(0, di - 20):di]]
            avg_dvol = sum(window) / len(window)
            o15h, o15l = max(float(rows[i][3]) for i in idx[:3]), min(float(rows[i][4]) for i in idx[:3])
            o30h, o30l = max(float(rows[i][3]) for i in idx[:6]), min(float(rows[i][4]) for i in idx[:6])
            highs = [float(rows[i][3]) for i in idx]
            lows = [float(rows[i][4]) for i in idx]
            opens = [float(rows[i][2]) for i in idx]
            cum_pv = cum_v = 0.0
            for n, i in enumerate(idx):
                r = rows[i]
                tp = (float(r[3]) + float(r[4]) + float(r[5])) / 3.0
                cum_pv, cum_v = cum_pv + tp * float(r[6]), cum_v + float(r[6])
                if i < 21 or rs[i] is None or n + 1 >= len(idx):
                    continue
                avgv = sum(float(rows[k][6]) for k in range(i - 20, i)) / 20.0
                rng = float(r[3]) - float(r[4])
                j0, j1 = n + 1, min(n + 1 + HORIZON, len(idx))
                entry = opens[n + 1]
                hi, lo = max(highs[j0:j1]), min(lows[j0:j1])
                cols["sym"].append(si)
                cols["day"].append(di * 0 + days.index(day))
                cols["minute"].append(int(r[1]))
                cols["n"].append(n)
                cols["close"].append(float(r[5]))
                cols["pclose"].append(float(rows[i - 1][5]))
                cols["vwap"].append(cum_pv / cum_v if cum_v else float(r[5]))
                cols["pdh"].append(pdh)
                cols["pdl"].append(pdl)
                cols["orh15"].append(o15h)
                cols["orl15"].append(o15l)
                cols["orh30"].append(o30h)
                cols["orl30"].append(o30l)
                cols["hod"].append(max(highs[:n]) if n else float(r[3]))
                cols["lod"].append(min(lows[:n]) if n else float(r[4]))
                cols["range_hi"].append(max(highs[max(0, n - 12):n]) if n else float(r[3]))
                cols["range_lo"].append(min(lows[max(0, n - 12):n]) if n else float(r[4]))
                cols["gap"].append(gap)
                cols["volx"].append(float(r[6]) / avgv if avgv > 0 else 0.0)
                cols["dvol"].append(avg_dvol)
                cols["e9"].append(e9[i])
                cols["e20"].append(e20[i])
                cols["rsi"].append(rs[i])
                cols["bodypos"].append((float(r[5]) - float(r[4])) / rng if rng > 0 else 0.5)
                cols["lmfe"].append((hi / entry - 1) * 100)
                cols["lmae"].append((1 - lo / entry) * 100)
                cols["smfe"].append((1 - lo / entry) * 100)
                cols["smae"].append((hi / entry - 1) * 100)
    out = {k: np.array(v, dtype=float) for k, v in cols.items()}
    out["sym_names"] = np.array(syms)
    return out


def combos():
    levels = ("PDH_OR15", "OR15", "OR30", "PDH", "HOD", "RANGE12", "ANY")
    for lvl, vol, vw, ema_, rsi_, gap_, t0, body in itertools.product(levels, (0.0, 1.0, 1.5, 2.0, 3.0), (True, False), (True, False), (0, 50, 55, 60, 65), ("off", "0to3", "m1to3", "m3to3"),
                                                                       (9 * 60 + 30, 10 * 60), (0.0, 0.7)):
        yield dict(level=lvl, vol=vol, vwap=vw, ema=ema_, rsi=rsi_, gap=gap_, t0=t0, body=body)


def mask(D: dict[str, np.ndarray], c: dict, side: int) -> np.ndarray:
    """Boolean mask of the candles that fire for combination c; side +1 long, -1 short."""
    cl, pc = D["close"], D["pclose"]
    if side > 0:
        crossed = {"PDH": (pc <= D["pdh"]) & (cl > D["pdh"]), "OR15": (pc <= D["orh15"]) & (cl > D["orh15"]) & (D["n"] >= 3), "OR30": (pc <= D["orh30"]) & (cl > D["orh30"]) & (D["n"] >= 6),
                   "HOD": (cl > D["hod"]) & (D["n"] >= 6), "RANGE12": (cl > D["range_hi"]) & (D["n"] >= 12)}
    else:
        crossed = {"PDH": (pc >= D["pdl"]) & (cl < D["pdl"]), "OR15": (pc >= D["orl15"]) & (cl < D["orl15"]) & (D["n"] >= 3), "OR30": (pc >= D["orl30"]) & (cl < D["orl30"]) & (D["n"] >= 6),
                   "HOD": (cl < D["lod"]) & (D["n"] >= 6), "RANGE12": (cl < D["range_lo"]) & (D["n"] >= 12)}
    lvl = c["level"]
    if lvl == "PDH_OR15":
        m = crossed["PDH"] | crossed["OR15"]
    elif lvl == "ANY":
        m = crossed["PDH"] | crossed["OR15"] | crossed["OR30"] | crossed["HOD"] | crossed["RANGE12"]
    else:
        m = crossed[lvl]
    m = m & (D["minute"] >= c["t0"]) & (D["minute"] <= 14 * 60 + 40) & (D["dvol"] > 500_000)
    if c["vol"]:
        m &= D["volx"] > c["vol"]
    if c["vwap"]:
        m &= (cl > D["vwap"]) if side > 0 else (cl < D["vwap"])
    if c["ema"]:
        m &= (D["e9"] > D["e20"]) if side > 0 else (D["e9"] < D["e20"])
    if c["rsi"]:
        m &= (D["rsi"] > c["rsi"]) if side > 0 else (D["rsi"] < 100 - c["rsi"])
    g = D["gap"]
    lo, hi = {"off": (-99, 99), "0to3": (0, 3), "m1to3": (-1, 3), "m3to3": (-3, 3)}[c["gap"]] if side > 0 else {"off": (-99, 99), "0to3": (-3, 0), "m1to3": (-3, 1), "m3to3": (-3, 3)}[c["gap"]]
    m &= (g >= lo) & (g <= hi)
    if c["body"]:
        m &= (D["bodypos"] >= c["body"]) if side > 0 else (D["bodypos"] <= 1 - c["body"])
    return m


def first_per_day(D: dict[str, np.ndarray], m: np.ndarray) -> np.ndarray:
    """Indices of the first firing candle of each (stock, day)."""
    idx = np.nonzero(m)[0]
    if not len(idx):
        return idx
    key = D["sym"][idx] * 1000 + D["day"][idx]
    _, first = np.unique(key, return_index=True)
    return idx[np.sort(first)]


def score(D: dict[str, np.ndarray], idx: np.ndarray, side: int) -> dict | None:
    if len(idx) < MIN_N:
        return None
    mfe, mae = (D["lmfe"], D["lmae"]) if side > 0 else (D["smfe"], D["smae"])
    days = D["day"][idx]
    cut = np.median(np.unique(D["day"]))
    halves = []
    for sel in (days <= cut, days > cut):
        j = idx[sel]
        if len(j) < MIN_HALF:
            return None
        good = np.mean((mfe[j] >= GOOD_MFE) & (mae[j] <= GOOD_MAE)) * 100
        nothing = np.mean(mfe[j] < NOTHING_MFE) * 100
        halves.append((good, nothing, good - nothing))
    good = np.mean((mfe[idx] >= GOOD_MFE) & (mae[idx] <= GOOD_MAE)) * 100
    nothing = np.mean(mfe[idx] < NOTHING_MFE) * 100
    return {"n": len(idx), "good": good, "nothing": nothing, "score": good - nothing, "worst_half": min(h[2] for h in halves), "mean_net": float(np.mean(mfe[idx] - mae[idx]))}


def describe(c: dict) -> str:
    return (f"{c['level']} | vol>{c['vol'] or '-'} | {'VWAP' if c['vwap'] else '-'} | {'EMA' if c['ema'] else '-'} | RSI {('>' + str(c['rsi'])) if c['rsi'] else '-'} | gap {c['gap']} | from {c['t0'] // 60}:{c['t0'] % 60:02d} | body {c['body'] or '-'}")


GIVEN = dict(level="PDH_OR15", vol=1.5, vwap=True, ema=True, rsi=60, gap="0to3", t0=9 * 60 + 30, body=0.0)


def run() -> Path:
    candles = json.loads((CACHE / "stock_5m.json").read_text(encoding="utf-8"))
    D = build(candles)
    print("candles", len(D["close"]), flush=True)
    lines = ["# Breakout / breakdown combination search (research; scored on the stock's next 60 minutes)", "",
             f"{len(D['close']):,} candles, {len(np.unique(D['day']))} days, {len(D['sym_names'])} stocks. GOOD = MFE >= {GOOD_MFE}% with MAE <= {GOOD_MAE}% in the next 12 candles; NOTHING = MFE < {NOTHING_MFE}%. "
             f"score = GOOD% - NOTHING% (the worse of the two halves of the days is used to rank). At least {MIN_N} signals.", ""]
    results: dict[int, list] = {1: [], -1: []}
    allc = list(combos())
    for side in (1, -1):
        for k, c in enumerate(allc):
            s = score(D, first_per_day(D, mask(D, c, side)), side)
            if s:
                results[side].append((s, c))
        print("side", side, "combos scored", len(results[side]), "of", len(allc), flush=True)
    for side, name in ((1, "BREAKOUT (long)"), (-1, "BREAKDOWN (short)")):
        g = score(D, first_per_day(D, mask(D, GIVEN, side)), side)
        lines += [f"## {name}", "", "The rule as given: " + (f"n={g['n']}, GOOD {g['good']:.0f}%, NOTHING {g['nothing']:.0f}%, score {g['score']:+.0f}, worse half {g['worst_half']:+.0f}" if g else "too few signals"), ""]
        allr = results[side]
        base_nothing = float(np.mean(D["lmfe" if side > 0 else "smfe"] < NOTHING_MFE) * 100)
        base_good = float(np.mean((D["lmfe" if side > 0 else "smfe"] >= GOOD_MFE) & (D["lmae" if side > 0 else "smae"] <= GOOD_MAE)) * 100)
        lines += [f"Any candle at all (no rule): GOOD {base_good:.0f}%, NOTHING {base_nothing:.0f}%, score {base_good - base_nothing:+.0f}.", "",
                  "| rank | combination | signals | GOOD % | NOTHING % | score | worse half | mean MFE-MAE % |", "|---|---|---|---|---|---|---|---|"]
        for rank, (s, c) in enumerate(sorted(allr, key=lambda x: -x[0]["worst_half"])[:15], 1):
            lines.append(f"| {rank} | {describe(c)} | {s['n']} | {s['good']:.0f} | {s['nothing']:.0f} | {s['score']:+.0f} | {s['worst_half']:+.0f} | {s['mean_net']:+.2f} |")
        lines.append("")
        beats = sum(1 for s, _ in allr if s["worst_half"] > (g["worst_half"] if g else -999))
        lines.append(f"{beats} of {len(allr)} combinations (with enough signals) score better than the given rule in their worse half.")
        lines.append("")
    out = ROOT / "data" / "breakout_rule" / "search.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "data" / "breakout_rule" / "search_top.json").write_text(json.dumps({str(side): [(s, c) for s, c in sorted(results[side], key=lambda x: -x[0]["worst_half"])[:10]] for side in (1, -1)}), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(run())
    print((ROOT / "data" / "breakout_rule" / "search.md").read_text(encoding="utf-8"))
