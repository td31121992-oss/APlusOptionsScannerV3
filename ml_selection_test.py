"""Can machine learning pick the right stock at 10:00? (RESEARCH ONLY - touches no scanner or trade.)  .venv\\Scripts\\python ml_selection_test.py

Data: the 5-minute stock cube of top_movers_study (210 F&O stocks, Jul 2021 - Aug 2026). For every stock-day the model sees only what is known at 10:00 (gap, move since the open, volume against the
stock's own 20-day norm, range position, price against VWAP, prior 1 / 5 / 20 day returns, 20-day average range, the market's move, the stock's move against the market) and predicts the return from the
09:55-10:00 entry (open of the 10:00 bar) to the 15:10 bar close (about 15:15). The model is refitted every quarter on PAST days only (one day purged); each quarter is then traded blind.
Rule traded: each day the K stocks with the highest predicted return are bought and the K with the lowest are sold short (only if the prediction is beyond 0.0). Returns are STOCK returns; the cost line is the
stock move an option buyer needs just to pay the entry / exit spread and charges (median 3.6% of premium / about 16 option-% per stock-% = 0.22%, rounded up to 0.25%).
Baselines: always follow the morning move, always fade it, random picks. Output: E:\\APlusData\\top_movers_study\\ml_selection_test.txt
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor

warnings.filterwarnings("ignore")
OUT = Path(r"E:\APlusData\top_movers_study")
ENTRY_BAR, EXIT_BAR = 9, 71          # entry = open of the 10:00 bar, exit = close of the 15:10 bar
DEC = 8                              # last bar known at the decision (closes 10:00)
COST = 0.25                          # percent of the stock price
K = 5
MIN_TRAIN_DAYS = 250
BLOCK = 63
FEATS = ["gap", "r_dec", "r_30", "r_last", "range_pos", "rng", "vol_x", "vs_vwap", "prior1", "prior5", "prior20", "atr20", "mkt_gap", "mkt_ret", "rel_ret", "rank_ret", "rank_gap", "rank_vol"]

lines: list[str] = []


def say(s: str = "") -> None:
    print(s)
    lines.append(s)


def build() -> pd.DataFrame:
    cube = np.load(OUT / "cube.npy", mmap_mode="r")
    days = np.load(OUT / "cube_days.npy", allow_pickle=True)
    syms = pd.read_csv(OUT / "cube_symbols.csv", header=None)[0].tolist()
    o, h, l, c, v = (np.array(cube[..., i]) for i in range(5))                 # (S, D, 75)
    S, D, _ = o.shape
    dayclose = c[:, :, 74]
    dayhigh = np.nanmax(np.where(np.isnan(h), -np.inf, h), axis=2)
    daylow = np.nanmin(np.where(np.isnan(l), np.inf, l), axis=2)
    dayrng = (dayhigh - daylow) / dayclose
    dayrng[~np.isfinite(dayrng)] = np.nan
    early_vol = np.nansum(v[:, :, :DEC + 1], axis=2)
    early_vol[np.isnan(v[:, :, 0])] = np.nan
    rows = []
    for d in range(21, D):
        pc = dayclose[:, d - 1]
        o0, cd, c5, c6 = o[:, d, 0], c[:, d, DEC], c[:, d, 5], c[:, d, 6]
        hi = np.nanmax(h[:, d, :DEC + 1], axis=1) if not np.all(np.isnan(h[:, d, :DEC + 1])) else np.full(S, np.nan)
        lo = np.nanmin(l[:, d, :DEC + 1], axis=1) if not np.all(np.isnan(l[:, d, :DEC + 1])) else np.full(S, np.nan)
        pv = (c[:, d, :DEC + 1] * v[:, d, :DEC + 1]).sum(axis=1) / np.where(v[:, d, :DEC + 1].sum(axis=1) > 0, v[:, d, :DEC + 1].sum(axis=1), np.nan)
        ent, ext = o[:, d, ENTRY_BAR], c[:, d, EXIT_BAR]
        gap = (o0 / pc - 1) * 100
        rdec = (cd / o0 - 1) * 100
        f = pd.DataFrame({
            "sym": syms, "day": days[d], "gap": gap, "r_dec": rdec, "r_30": (c5 / o0 - 1) * 100, "r_last": (cd / c6 - 1) * 100,
            "range_pos": (cd - lo) / np.where(hi > lo, hi - lo, np.nan), "rng": (hi - lo) / o0 * 100,
            "vol_x": early_vol[:, d] / np.nanmean(early_vol[:, d - 20:d], axis=1), "vs_vwap": (cd / pv - 1) * 100,
            "prior1": (pc / dayclose[:, d - 2] - 1) * 100, "prior5": (pc / dayclose[:, d - 6] - 1) * 100, "prior20": (pc / dayclose[:, d - 21] - 1) * 100,
            "atr20": np.nanmean(dayrng[:, d - 20:d], axis=1) * 100, "ret": (ext / ent - 1) * 100,
        })
        ok = np.isfinite(f.gap) & np.isfinite(f.ret) & np.isfinite(f.r_dec) & (f.gap.abs() < 20) & (f.ret.abs() < 25)
        f = f[ok].copy()
        if len(f) < 100:
            continue
        f["mkt_gap"], f["mkt_ret"] = f.gap.median(), f.r_dec.median()
        f["rel_ret"] = f.r_dec - f.mkt_ret
        f["rank_ret"], f["rank_gap"], f["rank_vol"] = f.r_dec.rank(pct=True), f.gap.rank(pct=True), f.vol_x.rank(pct=True)
        rows.append(f)
    return pd.concat(rows, ignore_index=True)


def trade(d: pd.DataFrame, pred: np.ndarray, label: str) -> dict:
    d = d.assign(pred=pred)
    out = []
    for day, g in d.groupby("day"):
        g = g.dropna(subset=["pred"])
        lo, hi = g.nsmallest(K, "pred"), g.nlargest(K, "pred")
        lo, hi = lo[lo.pred < 0], hi[hi.pred > 0]
        rets = list(hi.ret) + list(-lo.ret)
        if rets:
            out.append((day, np.mean(rets), len(rets)))
    t = pd.DataFrame(out, columns=["day", "gross", "n"])
    ic = np.nanmean([spearmanr(g.pred, g.ret)[0] for _, g in d.groupby("day") if len(g) > 30])
    return {"label": label, "days": len(t), "trades": int(t.n.sum()), "gross": t.gross.mean(), "net": t.gross.mean() - COST, "t_net": (t.gross.mean() - COST) / (t.gross.std() / np.sqrt(len(t))),
            "hit_net": float((t.gross > COST).mean() * 100), "ic": ic, "daily": t.assign(year=t.day // 10000)}


def main() -> None:
    d = build()
    d = d.sort_values(["day", "sym"]).reset_index(drop=True)
    days = np.array(sorted(d.day.unique()))
    say(f"# ML stock-selection test  ({len(d):,} stock-days, {len(days)} days, {days[0]}..{days[-1]})")
    say("")
    d["y"] = d.ret.clip(-8, 8) - d.groupby("day").ret.transform(lambda s: s.clip(-8, 8).mean())     # beat-the-day-average target, outliers clipped
    preds = pd.Series(np.nan, index=d.index)
    start = MIN_TRAIN_DAYS
    blocks = 0
    while start < len(days):
        test_days = days[start:start + BLOCK]
        train = d[d.day.isin(days[:start - 1])]                        # one day purged
        m = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=200, min_samples_leaf=400, l2_regularization=5.0, random_state=0)
        m.fit(train[FEATS], train.y)
        te = d.day.isin(test_days)
        preds[te] = m.predict(d.loc[te, FEATS])
        start += BLOCK
        blocks += 1
    t = d[preds.notna()].copy()
    p = preds[preds.notna()].to_numpy()
    say(f"Walk-forward: {blocks} quarterly refits, tested blind on {t.day.nunique()} days ({t.day.min()}..{t.day.max()}), K = {K} longs + {K} shorts a day, cost line {COST}% of the stock price")
    say("")
    rng = np.random.default_rng(1)
    res = [trade(t, p, "ML model (gradient boosting)"), trade(t, t.r_dec.to_numpy(), "follow the morning move"), trade(t, -t.r_dec.to_numpy(), "fade the morning move"), trade(t, rng.normal(size=len(t)), "random picks")]
    say("| Strategy | Days | Trades | Gross % / trade | After cost % / trade | t (after cost) | Days beating cost | Rank correlation (IC) |")
    say("|---|---|---|---|---|---|---|---|")
    for r in res:
        say(f"| {r['label']} | {r['days']} | {r['trades']} | {r['gross']:+.3f} | {r['net']:+.3f} | {r['t_net']:+.1f} | {r['hit_net']:.0f}% | {r['ic']:+.3f} |")
    say("")
    say("ML model, by year (gross % per trade, per-day average)")
    say("")
    say("| Year | Days | Gross % | After cost % | Days beating cost |")
    say("|---|---|---|---|---|")
    for y, g in res[0]["daily"].groupby("year"):
        say(f"| {y} | {len(g)} | {g.gross.mean():+.3f} | {g.gross.mean() - COST:+.3f} | {(g.gross > COST).mean() * 100:.0f}% |")
    say("")
    # decile spread: does a higher prediction mean a higher return at all?
    t["pred"] = p
    t["dec"] = t.groupby("day").pred.transform(lambda s: pd.qcut(s.rank(method="first"), 10, labels=False))
    dd = t.groupby("dec").ret.mean()
    say("Mean return 10:00 -> 15:10 by prediction decile (0 = lowest predicted, 9 = highest), % of the stock price")
    say("")
    say("| Decile | " + " | ".join(str(i) for i in range(10)) + " |")
    say("|---|" + "---|" * 10)
    say("| Mean return % | " + " | ".join(f"{dd[i]:+.3f}" for i in range(10)) + " |")
    say("")
    top, bot = t[t.dec == 9], t[t.dec == 0]
    say(f"Top decile long: {top.ret.mean():+.3f}%   bottom decile short: {-bot.ret.mean():+.3f}%   (a one-sided cost of the option trade is about {COST}%)")
    (OUT / "ml_selection_test.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
