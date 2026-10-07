"""Data-science pipeline: build a labelled dataset from the stored option history, then evaluate models honestly.

    python ds_pipeline.py build       # -> data/data_science/dataset.csv.gz   (about 5-10 minutes)
    python ds_pipeline.py evaluate    # -> data/data_science/evaluation.md    (walk-forward, no future leakage)

One row = one hypothetical trade: stock, day, decision time (10:00 ... 12:00), side (call or put at the money).
Features are chart numbers known at the decision bar (chart_features.py), relative strength versus the market,
market regime and breadth, and option liquidity/IV/OI. Label = net return % of buying that ATM option at the
bar's close +1% slippage, with a 20% stop (filled at the bar close if gapped through), held to 15:15, minus 1.5% costs.

Everything is offline and read-only. Models are judged ONLY on later dates they never saw (walk-forward).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "data_science"
ENTRY_MINUTES = (600, 630, 660, 690, 720)      # 10:00, 10:30, 11:00, 11:30, 12:00
STOP, COST_PCT, SLIP = 0.20, 1.5, 1.01
FEATURES = ["d_ret_open", "d_ret_3", "d_ret_6", "d_ret_12", "range_pos_dir", "dist_extreme_pct", "vol_12", "or_status",
            "d_slope_12", "efficiency_12", "rs_dir", "mkt_dir", "breadth_dir", "premium_pct", "iv", "oi_change",
            "vol_ratio", "minute", "side", "weekday"]


def _simulate(minutes: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray, entry_idx: int) -> float | None:
    entry = close[entry_idx] * SLIP
    if entry <= 0:
        return None
    level = entry * (1 - STOP)
    for j in range(entry_idx + 1, len(minutes)):
        if low[j] <= level:
            px = min(level, close[j])
            return (px / entry - 1) * 100 - COST_PCT
        if minutes[j] >= 915:
            return (close[j] / entry - 1) * 100 - COST_PCT
    if len(minutes) - 1 <= entry_idx:
        return None
    return (close[-1] / entry - 1) * 100 - COST_PCT


def build(start: str = "2026-05-10", end: str = "2026-10-03") -> Path:
    from chart_features import feature_vector
    from options_history import DEFAULT_ROOT, load_series

    syms = sorted(d.name for d in DEFAULT_ROOT.iterdir() if d.is_dir() and (d / "2026-10-03").exists()
                  and any((d / "2026-06-05").glob("1_CE_ATM.json.gz")))
    print("symbols", len(syms), flush=True)
    data: dict[tuple[str, str], pd.DataFrame] = {}
    for n, s in enumerate(syms):
        for side_name in ("CALL", "PUT"):
            parts = []
            for off in range(-3, 4):
                try:
                    df = load_series(s, side_name, offset=off, start=start, end=end)
                except Exception:                                    # noqa: BLE001
                    continue
                if df is not None and not df.empty:
                    df = df.copy()
                    df["off"] = off
                    parts.append(df)
            if parts:
                allo = pd.concat(parts)
                allo["date"] = allo.index.date
                allo["minute"] = allo.index.hour * 60 + allo.index.minute
                data[(s, side_name)] = allo
        if n % 25 == 0:
            print("loaded", n, flush=True)
    days = sorted({d for (s, side), df in data.items() for d in df["date"].unique()})
    rows = []
    for day in days:
        spots = {}
        for s in syms:
            df = data.get((s, "CALL"))
            if df is None:
                continue
            x = df[(df.date == day) & (df.off == 0)].sort_index()
            x = x[~x.index.duplicated()]
            if len(x) >= 50 and (x.spot > 0).all():
                spots[s] = x
        if len(spots) < 40:
            continue
        for m in ENTRY_MINUTES:
            ret_open, ok = {}, {}
            for s, x in spots.items():
                upto = x[x.minute <= m]
                if len(upto) >= 13 and upto.minute.iloc[-1] == m:
                    ret_open[s] = (float(upto.spot.iloc[-1]) / float(upto.spot.iloc[0]) - 1) * 100
                    ok[s] = upto
            if len(ret_open) < 40:
                continue
            mkt = float(np.median(list(ret_open.values())))
            breadth = float(np.mean([v > 0 for v in ret_open.values()]))
            for s, upto in ok.items():
                spot_series = upto.spot.values
                for side, side_name in ((1, "CALL"), (-1, "PUT")):
                    allo = data.get((s, side_name))
                    if allo is None:
                        continue
                    day_all = allo[allo.date == day]
                    base = day_all[day_all.off == 0].sort_index()
                    base = base[~base.index.duplicated()]
                    erow = base[base.minute == m]
                    if erow.empty or float(erow.close.iloc[0]) < 0.5:
                        continue
                    k = float(erow.strike.iloc[0])
                    path = day_all[day_all.strike == k].sort_index()
                    path = path[~path.index.duplicated()]
                    if len(path) < 10 or not (path.minute == m).any():
                        continue
                    mins, hi, lo, cl = (path.minute.values, path.high.values.astype(float), path.low.values.astype(float),
                                        path.close.values.astype(float))
                    idx = int(np.where(mins == m)[0][0])
                    ret = _simulate(mins, hi, lo, cl, idx)
                    if ret is None:
                        continue
                    fv = feature_vector(spot_series, side)
                    vols = path.volume.values.astype(float)
                    prev = vols[max(0, idx - 12):idx]
                    oi = path.oi.values.astype(float)
                    fv.update({
                        "rs_dir": side * (ret_open[s] - mkt), "mkt_dir": side * mkt, "breadth_dir": side * (breadth - 0.5),
                        "premium_pct": float(cl[idx]) / float(spot_series[-1]) * 100,
                        "iv": float(path.iv.iloc[idx]) if np.isfinite(path.iv.iloc[idx]) else 0.0,
                        "oi_change": (oi[idx] / oi[0] - 1) * 100 if oi[0] > 0 else 0.0,
                        "vol_ratio": float(vols[idx] / prev.mean()) if len(prev) and prev.mean() > 0 else 0.0,
                        "minute": m, "side": side, "weekday": pd.Timestamp(day).weekday(),
                        "date": str(day), "symbol": s, "ret_pct": ret,
                    })
                    rows.append(fv)
        print("day", day, "rows", len(rows), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    path_out = OUT / "dataset.csv.gz"
    pd.DataFrame(rows).to_csv(path_out, index=False, compression="gzip")
    print("saved", path_out, len(rows), flush=True)
    return path_out


def evaluate(min_train_days: int = 35, test_block_days: int = 8) -> Path:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import roc_auc_score

    df = pd.read_csv(OUT / "dataset.csv.gz")
    df = df.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    dates = sorted(df.date.unique())
    rng = np.random.default_rng(7)
    folds = []
    i = min_train_days
    while i < len(dates):
        folds.append((dates[:i], dates[i:i + test_block_days]))
        i += test_block_days
    results, last = [], None
    for train_d, test_d in folds:
        tr, te = df[df.date.isin(train_d)], df[df.date.isin(test_d)]
        if len(te) < 500:
            continue
        clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=300,
                                             l2_regularization=5.0, random_state=0)
        clf.fit(tr[FEATURES], (tr.ret_pct > 0).astype(int))
        p = clf.predict_proba(te[FEATURES])[:, 1]
        te = te.assign(p=p)
        n10 = max(50, int(len(te) * 0.10))
        top = te.nlargest(n10, "p")
        mom = te.nlargest(n10, "d_ret_6")
        rs = te.nlargest(n10, "rs_dir")
        rnd = te.iloc[rng.choice(len(te), n10, replace=False)]
        try:
            auc = roc_auc_score((te.ret_pct > 0).astype(int), p)
        except ValueError:
            auc = float("nan")
        results.append({"test": f"{test_d[0]}..{test_d[-1]}", "n_test": len(te), "auc": auc,
                        "all": te.ret_pct.mean(), "model_top10": top.ret_pct.mean(), "model_win": float((top.ret_pct > 0).mean()),
                        "momentum_top10": mom.ret_pct.mean(), "rs_top10": rs.ret_pct.mean(), "random10": rnd.ret_pct.mean()})
        last = (clf, te)
    res = pd.DataFrame(results)
    lines = ["# Data-science evaluation (walk-forward)", "",
             f"Rows {len(df):,}, days {len(dates)}, label = net % return of a 20%-stop ATM option bought at the decision bar, held to 15:15, after 1.5% costs.",
             "Each test block is later than everything the model trained on.", "",
             "| Test dates | Rows | AUC | Average of all | Model top 10% | Model top-10% winners | Momentum top 10% | Relative-strength top 10% | Random 10% |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        lines.append(f"| {r['test']} | {r['n_test']:,} | {r['auc']:.3f} | {r['all']:+.2f}% | {r['model_top10']:+.2f}% | {r['model_win']*100:.0f}% | "
                     f"{r['momentum_top10']:+.2f}% | {r['rs_top10']:+.2f}% | {r['random10']:+.2f}% |")
    if len(res):
        lines += ["", f"**Average over test blocks:** all {res['all'].mean():+.2f}% | model top 10% {res.model_top10.mean():+.2f}% | "
                      f"momentum {res.momentum_top10.mean():+.2f}% | relative strength {res.rs_top10.mean():+.2f}% | random {res.random10.mean():+.2f}% | "
                      f"mean AUC {res.auc.mean():.3f} (0.5 = no skill)"]
    if last:
        clf, te = last
        imp = permutation_importance(clf, te[FEATURES], (te.ret_pct > 0).astype(int), n_repeats=3, random_state=0, scoring="roc_auc")
        top = sorted(zip(FEATURES, imp.importances_mean), key=lambda x: -x[1])[:8]
        lines += ["", "**Most useful features on the last block (permutation importance, drop in AUC):** "
                  + ", ".join(f"{f} {v:+.4f}" for f, v in top)]
    path = OUT / "evaluation.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return path


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    cmd = sys.argv[1] if len(sys.argv) > 1 else "evaluate"
    build() if cmd == "build" else evaluate()
