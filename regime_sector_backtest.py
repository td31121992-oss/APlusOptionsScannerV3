"""Regime + sector gate backtest (RESEARCH ONLY - touches no scanner or trade).  .venv\\Scripts\\python regime_sector_backtest.py

The rule under test (the user's idea, as one separate shadow gate):
  1. Market regime: of all F&O stocks with a price, count how many are above / below yesterday's close at the decision time. The majority sets the ONLY side allowed
     (more rising than falling -> calls only, more falling -> puts only; with --thr a clear majority is required, else no trade).
  2. Sector: the sector with the highest median move (calls) / lowest (puts) is the only sector allowed. Stocks of every other sector are not traded.
  3. Candidates: inside that sector, the TOP_N stocks moving most in the allowed direction since yesterday's close (at least MIN_MOVE).
Compared with the same candidate rule WITHOUT the sector filter (and without the regime filter), on the 5-minute stock cube of top_movers_study (Jul 2021 - Aug 2026).
Entry = open of the next 5-minute bar after the decision time; exit = HORIZON bars later (or the 15:10 close). Returns are STOCK returns in the trade's direction; COST = the stock move an option
buyer needs to pay the spread and charges (0.25%). Days are the unit of evidence: the mean of daily means, a t-stat across days, both halves of the period, and each year.
Output: E:\\APlusData\\top_movers_study\\regime_sector_backtest.txt
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
OUT = Path(r"E:\APlusData\top_movers_study")
SECTOR_CSV = Path(__file__).resolve().parent / "data" / "reference" / "fno_sector_map.csv"
COST = 0.25
MIN_MOVE = 0.3                 # a candidate must already be this far (percent) from yesterday's close in the allowed direction
TOP_N = 3
TIMES = {"10:00": 9, "10:30": 15, "11:30": 27, "13:00": 45}          # entry bar (09:15 = bar 0)
HORIZONS = {"60min": 12, "to 15:10": None}
EXIT_BAR = 71
MIN_STOCKS = 150
MIN_SECTOR = 4

lines: list[str] = []


def say(s: str = "") -> None:
    print(s)
    lines.append(s)


def load():
    cube = np.load(OUT / "cube.npy", mmap_mode="r")
    days = [str(d) for d in np.load(OUT / "cube_days.npy", allow_pickle=True)]
    syms = pd.read_csv(OUT / "cube_symbols.csv", header=None)[0].tolist()
    o = np.array(cube[..., 0])
    c = np.array(cube[..., 3])
    smap = pd.read_csv(SECTOR_CSV, encoding="utf-8-sig").set_index("symbol")["sector"].to_dict()
    sec = np.array([smap.get(s, "") for s in syms])
    return o, c, days, syms, sec


def pick(move, sec, side, allowed_sectors, top_n):
    """indices of the top_n stocks moving most in `side` (+1 calls / -1 puts); restricted to allowed_sectors when given."""
    d = move * side
    ok = np.isfinite(d) & (d >= MIN_MOVE)
    if allowed_sectors is not None:
        ok &= np.isin(sec, list(allowed_sectors))
    idx = np.where(ok)[0]
    if len(idx) == 0:
        return idx
    return idx[np.argsort(-d[idx])[:top_n]]


def sector_rank(move, sec, side, n_sectors):
    meds = {}
    for s in set(sec):
        if not s:
            continue
        m = move[(sec == s) & np.isfinite(move)]
        if len(m) >= MIN_SECTOR:
            meds[s] = float(np.median(m))
    if not meds:
        return None
    order = sorted(meds, key=lambda k: -meds[k] * side)
    return set(order[:n_sectors])


def run():
    o, c, days, syms, sec = load()
    S, D, _ = o.shape
    dayclose = c[:, :, 74]
    res = []                                                   # one row per (variant, day): mean directional return of that day's picks, number of picks
    for tname, e in TIMES.items():
        for hname, hb in HORIZONS.items():
            xb = EXIT_BAR if hb is None else e + hb - 1
            if xb > 74:
                continue
            for d in range(1, D):
                pc = dayclose[:, d - 1]
                last = c[:, d, e - 1]
                move = (last / pc - 1) * 100
                valid = np.isfinite(move)
                if valid.sum() < MIN_STOCKS:
                    continue
                ent, ext = o[:, d, e], c[:, d, xb]
                ret = (ext / ent - 1) * 100
                up, down = int((move > 0).sum()), int((move < 0).sum())
                share_up = up / max(1, up + down) * 100
                for side_label, side in (("CALL", 1), ("PUT", -1)):
                    # A) no regime, no sector: the top movers of this side (both sides traded every day)
                    ia = pick(move, sec, side, None, TOP_N)
                    # B) regime only: this side is traded only when it is the majority side
                    majority = side if (share_up > 50 if side == 1 else share_up < 50) else 0
                    ib = ia if majority == side else np.array([], dtype=int)
                    # C) regime + top sector (user's gate), 50% majority and clear 60% majority; D) same but the 2 best sectors
                    out = {"A all-movers": ia, "B regime majority": ib}
                    for thr in (50, 60):
                        ok_regime = (share_up > thr) if side == 1 else ((100 - share_up) > thr)
                        for ns in (1, 2):
                            allowed = sector_rank(move, sec, side, ns) if ok_regime else None
                            ic = pick(move, sec, side, allowed, TOP_N) if (ok_regime and allowed) else np.array([], dtype=int)
                            out[f"C regime>{thr}% + top-{ns} sector"] = ic
                    # E) sector only (no regime): what the sector filter adds alone
                    allowed = sector_rank(move, sec, side, 1)
                    out["E top-1 sector only (no regime)"] = pick(move, sec, side, allowed, TOP_N) if allowed else np.array([], dtype=int)
                    for name, idx in out.items():
                        r = ret[idx] * side
                        r = r[np.isfinite(r)]
                        res.append((tname, hname, name, side_label, days[d], len(r), float(r.mean()) if len(r) else np.nan))
    return pd.DataFrame(res, columns=["time", "horizon", "variant", "side", "day", "n", "mean"])


def summarize(df: pd.DataFrame) -> None:
    df = df.copy()
    df["year"] = df["day"].str[:4]
    alld = sorted(df["day"].unique())
    half = alld[len(alld) // 2]
    say(f"# Regime + sector gate backtest   {alld[0]} .. {alld[-1]}  ({len(alld)} days, 210 F&O stocks)  cost {COST}%  top {TOP_N} movers, min move {MIN_MOVE}%")
    say("Entry = open of the bar after the decision time. Stock return in the trade's direction. 'after cost' = mean - 0.25. t = across days (mean of daily means). 'days' = days with at least one pick.")
    say(f"Halves: first = up to {half}, second = after.  N variants tested: {df.groupby(['time', 'horizon', 'variant']).ngroups}  (expect a best |t| of about 3 from chance alone)")
    rows = []
    for (t, h, v), g in df.groupby(["time", "horizon", "variant"]):
        # one daily number = average of the CALL and PUT picks of that day, weighted by their pick counts
        g = g[g["n"] > 0].copy()
        g["w"] = g["n"] * g["mean"]
        dd = g.groupby("day").agg(w=("w", "sum"), n=("n", "sum"))
        dd["m"] = dd["w"] / dd["n"]
        if len(dd) < 60:
            continue
        m = dd["m"]
        t_stat = m.mean() / (m.std(ddof=1) / np.sqrt(len(m)))
        h1, h2 = m[m.index <= half], m[m.index > half]
        yrs = m.groupby(m.index.str[:4]).mean()
        rows.append(dict(time=t, horizon=h, variant=v, days=len(m), trades=int(dd["n"].sum()), mean=m.mean(), after=m.mean() - COST, t=t_stat,
                         pos_days=(m - COST > 0).mean() * 100, h1=h1.mean() - COST, h2=h2.mean() - COST, yrs_pos=int((yrs - COST > 0).sum()), yrs=len(yrs)))
    R = pd.DataFrame(rows)
    pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 60)
    for (t, h), g in R.groupby(["time", "horizon"]):
        say(f"\n## decision {t}, hold {h}")
        say("| Variant | Days | Trades | Mean % | After cost % | t | Days > cost | 1st half | 2nd half | Years > cost |")
        say("|---|---|---|---|---|---|---|---|---|---|")
        for _, r in g.iterrows():
            say(f"| {r['variant']} | {r['days']} | {r['trades']} | {r['mean']:+.3f} | {r['after']:+.3f} | {r['t']:+.1f} | {r['pos_days']:.0f}% | {r['h1']:+.3f} | {r['h2']:+.3f} | {r['yrs_pos']}/{r['yrs']} |")
    best = R.sort_values("after", ascending=False).head(8)
    say("\n## Best 8 variants by after-cost mean (all times and horizons)")
    for _, r in best.iterrows():
        say(f"- {r['time']} {r['horizon']} | {r['variant']} | after cost {r['after']:+.3f}% | t {r['t']:+.1f} | halves {r['h1']:+.3f} / {r['h2']:+.3f} | years > cost {r['yrs_pos']}/{r['yrs']} | {r['trades']} trades")
    # paired effect: does the sector filter beat the same regime without it?
    say("\n## Does the sector filter add anything? (C regime>50 + top-1 sector minus B regime majority, same days, daily difference)")
    for (t, h), g in df.groupby(["time", "horizon"]):
        def daily(name):
            x = g[(g["variant"] == name) & (g["n"] > 0)].copy()
            x["w"] = x["n"] * x["mean"]
            dd = x.groupby("day").agg(w=("w", "sum"), n=("n", "sum"))
            return dd["w"] / dd["n"]
        a, b = daily("C regime>50% + top-1 sector"), daily("B regime majority")
        j = pd.concat([a.rename("c"), b.rename("b")], axis=1).dropna()
        if len(j) > 60:
            diff = j["c"] - j["b"]
            say(f"- {t} {h}: sector filter {diff.mean():+.3f}% per day vs regime-only, t {diff.mean() / (diff.std(ddof=1) / np.sqrt(len(diff))):+.1f}, {len(j)} common days")
    (OUT / "regime_sector_backtest.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    summarize(run())
