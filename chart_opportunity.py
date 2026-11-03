"""Chart opportunity scanner: which stock charts look like the ones that went on to make a big option move? (SHADOW ONLY: a page, a log and tags; nothing trades on it.)

The user's observation: every day the top-10 call and top-10 put options gain 100 % or more, and we capture little of it. This asks the chart for help. From 83 days of 1-minute option history it builds
one row per (stock, day, side, decision time) with the stock's chart numbers at that moment (chart_features.py: returns since the open and over 3 / 6 / 12 bars, position in the day's range, distance from
the extreme, volatility, opening-range status, trend slope and efficiency), its relative strength against the median stock, the market's direction and breadth, the minute of day, the side and the weekday,
and four LABELS taken from the ATM option bought at that bar's close (+1 % slippage):

    run_pct       the best price the option reached afterwards, % above the entry
    hit50 / hit100   it reached +50 % / +100 % before a -20 % stop
    ret_pct       the return held to 15:15 with the -20 % stop, after 1.5 % costs

A gradient-boosting model is trained on chart-only features (no option data, so it can score EVERY stock every 20 seconds from the live tick feed) to rank the setups by the chance of a +100 % run.
It is judged walk-forward (train on earlier days, test on later ones) against the base rate.

    python chart_opportunity.py build       -> data/chart_opportunity/dataset.csv.gz       (10-25 minutes)
    python chart_opportunity.py evaluate    -> data/chart_opportunity/evaluation.md          walk-forward result
    python chart_opportunity.py train       -> data/chart_opportunity/model.pkl              final model + score quantiles

Live (tick recorder, every 20 s): scores every stock for both sides -> data/ticks/chart_opps_live.json (top lists for the /chart-opportunities page); each stock that newly enters the top list is logged once
per 30 minutes to data/chart_opps/<day>.csv; the scanner adds co_ tags to its candidates; the nightly review (chart_opportunity.review) measures what those flags did, against the market.
"""

from __future__ import annotations

import csv
import json
import pickle
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
OUT = ROOT / "data" / "chart_opportunity"
ENTRY_MINUTES = (585, 615, 645, 675, 705, 735, 765, 795)                  # 09:45 ... 13:15, every 30 minutes
STOP, SLIP, COST_PCT = 0.20, 1.01, 1.5
FEATURES = ["d_ret_open", "d_ret_3", "d_ret_6", "d_ret_12", "range_pos_dir", "dist_extreme_pct", "vol_12", "or_status", "d_slope_12", "efficiency_12",
            "rs_dir", "mkt_dir", "breadth_dir", "minute", "side", "weekday"]
LABEL = "hit100"
MODEL_PATH = ("data", "chart_opportunity", "model.pkl")
LIVE_PATH = ("data", "ticks", "chart_opps_live.json")
TOP_N = 12
LOG_EVERY_MIN = 30
VERSION = "co-1"


# --- labels ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
def labels(minutes: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray, idx: int) -> dict[str, float] | None:
    entry = close[idx] * SLIP
    if entry <= 0 or idx >= len(minutes) - 1:
        return None
    stop = entry * (1 - STOP)
    best, hit50, hit100, ret = 0.0, 0, 0, None
    for j in range(idx + 1, len(minutes)):
        if low[j] <= stop and ret is None:
            ret = (min(stop, close[j]) / entry - 1) * 100 - COST_PCT
            stopped = True
            # a bar can reach the stop AND a target; the stop is taken first (conservative)
            break
        best = max(best, high[j] / entry - 1)
        if best >= 0.5:
            hit50 = 1
        if best >= 1.0:
            hit100 = 1
        if ret is None and minutes[j] >= 915:
            ret = (close[j] / entry - 1) * 100 - COST_PCT
            break
    if ret is None:
        ret = (close[-1] / entry - 1) * 100 - COST_PCT
    return {"run_pct": best * 100, "hit50": hit50, "hit100": hit100, "ret_pct": ret}


def build(start: str = "2026-05-10", end: str = "2026-10-03") -> Path:
    import pandas as pd
    from chart_features import feature_vector
    from options_history import DEFAULT_ROOT, load_series

    syms = sorted(d.name for d in DEFAULT_ROOT.iterdir() if d.is_dir() and (d / "2026-10-03").exists() and any((d / "2026-06-05").glob("1_CE_ATM.json.gz")))
    print("symbols", len(syms), flush=True)
    data: dict[tuple[str, str], Any] = {}
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
    # one pass over each (stock, side): per day, the at-the-money series (offset 0) and a cache of strike paths, as plain arrays (the earlier per-minute DataFrame filtering took hours)
    prep: dict[tuple[str, str], dict[Any, Any]] = {}
    for key, allo in data.items():
        perday = {}
        for day, g in allo.groupby("date"):
            g = g.sort_index()
            base = g[g.off == 0]
            base = base[~base.index.duplicated()]
            perday[day] = {"g": g, "bmin": base.minute.values, "bstrike": base.strike.values.astype(float), "bclose": base.close.values.astype(float), "bspot": base.spot.values.astype(float), "paths": {}}
        prep[key] = perday
    days = sorted({d for v in prep.values() for d in v})

    def strike_path(rec, k):
        p = rec["paths"].get(k)
        if p is None:
            g = rec["g"]
            path = g[g.strike == k]
            path = path[~path.index.duplicated()]
            p = (path.minute.values, path.high.values.astype(float), path.low.values.astype(float), path.close.values.astype(float))
            rec["paths"][k] = p
        return p

    rows = []
    for day in days:
        spots = {}
        for s in syms:
            rec = prep.get((s, "CALL"), {}).get(day)
            if rec is not None and len(rec["bmin"]) >= 50 and (rec["bspot"] > 0).all():
                spots[s] = rec
        if len(spots) < 40:
            continue
        for m in ENTRY_MINUTES:
            ret_open, ok = {}, {}
            for s, rec in spots.items():
                n_up = int(np.searchsorted(rec["bmin"], m, side="right"))
                if n_up >= 13 and rec["bmin"][n_up - 1] == m:
                    sp = rec["bspot"][:n_up]
                    ret_open[s] = (float(sp[-1]) / float(sp[0]) - 1) * 100
                    ok[s] = sp
            if len(ret_open) < 40:
                continue
            mkt = float(np.median(list(ret_open.values())))
            breadth = float(np.mean([v > 0 for v in ret_open.values()]))
            for s, spot_series in ok.items():
                for side, side_name in ((1, "CALL"), (-1, "PUT")):
                    rec = prep.get((s, side_name), {}).get(day)
                    if rec is None:
                        continue
                    w = np.where(rec["bmin"] == m)[0]
                    if not len(w) or float(rec["bclose"][w[0]]) < 0.5:
                        continue
                    k = float(rec["bstrike"][w[0]])
                    mins, hi, lo, cl = strike_path(rec, k)
                    if len(mins) < 10:
                        continue
                    hit = np.where(mins == m)[0]
                    if not len(hit):
                        continue
                    idx = int(hit[0])
                    lab = labels(mins, hi, lo, cl, idx)
                    if lab is None:
                        continue
                    fv = feature_vector(spot_series, side)
                    fv.update({"rs_dir": side * (ret_open[s] - mkt), "mkt_dir": side * mkt, "breadth_dir": side * (breadth - 0.5), "minute": m, "side": side,
                               "weekday": pd.Timestamp(day).weekday(), "date": str(day), "symbol": s, "premium_pct": float(cl[idx]) / float(spot_series[-1]) * 100, **lab})
                    rows.append(fv)
        print("day", day, "rows", len(rows), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    path_out = OUT / "dataset.csv.gz"
    pd.DataFrame(rows).to_csv(path_out, index=False, compression="gzip")
    print("saved", path_out, len(rows), flush=True)
    return path_out


# --- evaluation / training -----------------------------------------------------------------------------------------------------------------------------------------------------
def _params() -> dict[str, Any]:
    return dict(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=400, l2_regularization=5.0, random_state=0)


def evaluate(min_train_days: int = 30, block_days: int = 8, root: Path = ROOT) -> Path:
    import pandas as pd
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score

    df = pd.read_csv(root / "data" / "chart_opportunity" / "dataset.csv.gz").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    dates = sorted(df.date.unique())
    res, i = [], min_train_days
    while i < len(dates):
        tr, te = df[df.date.isin(dates[:i])], df[df.date.isin(dates[i:i + block_days])]
        i += block_days
        if len(te) < 800 or te[LABEL].sum() < 5:
            continue
        clf = HistGradientBoostingClassifier(**_params()).fit(tr[FEATURES], tr[LABEL])
        p = clf.predict_proba(te[FEATURES])[:, 1]
        te = te.assign(p=p)
        row = {"test": f"{te.date.min()}..{te.date.max()}", "n": len(te), "base": te[LABEL].mean() * 100, "auc": roc_auc_score(te[LABEL], p)}
        for frac, name in ((0.01, "top1"), (0.05, "top5")):
            top = te.nlargest(max(20, int(len(te) * frac)), "p")
            row[name] = top[LABEL].mean() * 100
            row[name + "_best"] = top.run_pct.mean()
            row[name + "_ret"] = top.ret_pct.mean()
        row["all_ret"], row["all_best"] = te.ret_pct.mean(), te.run_pct.mean()
        res.append(row)
    L = ["# Chart opportunity model: walk-forward evaluation", "",
         f"Rows {len(df):,} over {len(dates)} days; label = the ATM option reaches +100 % before a -20 % stop after the decision bar (base rate in the first column). Each test block is later than all training data.", "",
         "| Test dates | Rows | Base rate | AUC | Top 1 % hit rate | Top 5 % hit rate | Top 1 % mean best | Top 5 % mean best | All mean best | Top 5 % return to 15:15 | All return |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in res:
        L.append(f"| {r['test']} | {r['n']:,} | {r['base']:.1f}% | {r['auc']:.3f} | {r['top1']:.1f}% | {r['top5']:.1f}% | {r['top1_best']:+.0f}% | {r['top5_best']:+.0f}% | {r['all_best']:+.0f}% | {r['top5_ret']:+.1f}% | {r['all_ret']:+.1f}% |")
    if res:
        m = lambda k: float(np.mean([r[k] for r in res]))
        L += ["", f"**Average:** base rate {m('base'):.1f}% | top 1 % hit {m('top1'):.1f}% | top 5 % hit {m('top5'):.1f}% | mean AUC {m('auc'):.3f} (0.5 = no skill) | top 5 % return {m('top5_ret'):+.1f}% vs all {m('all_ret'):+.1f}%"]
    path = root / "data" / "chart_opportunity" / "evaluation.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return path


def train(root: Path = ROOT) -> dict[str, Any]:
    import pandas as pd
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score

    df = pd.read_csv(root / "data" / "chart_opportunity" / "dataset.csv.gz").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    dates = sorted(df.date.unique())
    cut = dates[int(len(dates) * 0.8)]
    a, b = df[df.date < cut], df[df.date >= cut]
    check = HistGradientBoostingClassifier(**_params()).fit(a[FEATURES], a[LABEL])
    p = check.predict_proba(b[FEATURES])[:, 1]
    q = {k: float(np.quantile(p, v)) for k, v in (("q50", 0.5), ("q90", 0.9), ("q95", 0.95), ("q99", 0.99))}
    top5 = b.assign(p=p).nlargest(max(20, int(len(b) * 0.05)), "p")
    clf = HistGradientBoostingClassifier(**_params()).fit(df[FEATURES], df[LABEL])
    meta = {"version": VERSION, "trained_at": datetime.now(IST).isoformat(timespec="seconds"), "rows": int(len(df)), "days": len(dates), "holdout_from": str(cut),
            "holdout_auc": round(float(roc_auc_score(b[LABEL], p)), 3), "holdout_base_rate": round(float(b[LABEL].mean() * 100), 2), "holdout_top5_hit": round(float(top5[LABEL].mean() * 100), 2),
            "p_quantiles": q, "features": FEATURES}
    path = root.joinpath(*MODEL_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as h:
        pickle.dump({"model": clf, "meta": meta}, h)
    _CACHE.update(mtime=None, obj=None)
    return meta


_CACHE: dict[str, Any] = {"mtime": None, "obj": None, "live_mtime": None, "live": None}


def _model(root: Path) -> dict[str, Any] | None:
    path = root.joinpath(*MODEL_PATH)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _CACHE["mtime"] != mtime:
        try:
            with path.open("rb") as h:
                _CACHE.update(mtime=mtime, obj=pickle.load(h))
        except Exception:                                  # noqa: BLE001
            return None
    return _CACHE["obj"]


# --- live scoring (called by ml_shadow.MinuteBars after it writes the 1-minute features) -------------------------------------------------------------------------------------
class LiveScorer:
    def __init__(self) -> None:
        self._logged: dict[tuple[str, int], float] = {}

    def score(self, root: Path, feats: Mapping[str, Any], day: str, t_s: float, wall: float | None = None) -> bool:
        """Score every stock and side from the 1-minute features dict (ml_shadow.live_features), write the live file, log new top entries. False when there is no model."""
        import pandas as pd

        obj = _model(root)
        if not obj or not feats:
            return False
        minute = int(feats["minute"])
        weekday = datetime.fromisoformat(day).weekday()
        keys, rows = [], []
        for sym, sides in feats["stocks"].items():
            for side in ("1", "-1"):
                f = sides.get(side)
                if f:
                    keys.append((sym, int(side)))
                    rows.append([f[k] for k in FEATURES if k not in ("minute", "side", "weekday")] + [min(max(minute, ENTRY_MINUTES[0]), ENTRY_MINUTES[-1]), int(side), weekday])
        if not rows:
            return False
        cols = [k for k in FEATURES if k not in ("minute", "side", "weekday")] + ["minute", "side", "weekday"]
        p = obj["model"].predict_proba(pd.DataFrame(rows, columns=cols)[FEATURES])[:, 1]
        q = obj["meta"]["p_quantiles"]
        order = np.argsort(-p)
        top = {"1": [], "-1": []}
        for rank_all, i in enumerate(order, 1):
            sym, side = keys[i]
            if len(top[str(side)]) < TOP_N:
                f = feats["stocks"][sym][str(side)]
                top[str(side)].append({"s": sym, "p": round(float(p[i]), 4), "x": round(float(p[i]) / max(q["q50"], 1e-6), 2), "rank": rank_all, "ret_open": round(f["d_ret_open"], 2), "rs": round(f["rs_dir"], 2),
                                       "or": f["or_status"], "range_pos": round(f["range_pos_dir"], 2), "eff": round(f["efficiency_12"], 2), "d3": round(f["d_ret_3"], 2), "d12": round(f["d_ret_12"], 2),
                                       "top5": int(p[i] >= q["q95"]), "top1": int(p[i] >= q["q99"])})
        all_p = {f"{s}|{side}": round(float(v), 4) for (s, side), v in zip(keys, p)}
        payload = {"day": day, "updated": f"{int(t_s // 3600):02d}:{int(t_s % 3600 // 60):02d}:{int(t_s % 60):02d}", "minute": minute, "n": len(keys), "calls": top["1"], "puts": top["-1"], "p": all_p,
                   "q": {k: round(v, 4) for k, v in q.items()}, "version": obj["meta"]["version"], "holdout_auc": obj["meta"]["holdout_auc"]}
        path = root.joinpath(*LIVE_PATH)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            return False
        self._log(root, day, t_s, payload)
        return True

    def _log(self, root: Path, day: str, t_s: float, payload: Mapping[str, Any]) -> None:
        new = []
        for side, key in ((1, "calls"), (-1, "puts")):
            for r in payload[key]:
                if not r["top5"]:
                    continue
                k = (r["s"], side)
                if t_s - self._logged.get(k, -1e9) >= LOG_EVERY_MIN * 60:
                    self._logged[k] = t_s
                    new.append({"date": day, "time": f"{int(t_s // 3600):02d}:{int(t_s % 3600 // 60):02d}:{int(t_s % 60):02d}", "symbol": r["s"], "side": side, "p": r["p"], "x_median": r["x"],
                                "top1": r["top1"], "ret_open": r["ret_open"], "rs": r["rs"], "or_status": r["or"], "range_pos": r["range_pos"], "efficiency": r["eff"], "rank": r["rank"]})
        if not new:
            return
        p = root / "data" / "chart_opps" / f"{day}.csv"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            fresh = not p.exists()
            with p.open("a", encoding="utf-8", newline="") as h:
                w = csv.DictWriter(h, fieldnames=list(new[0]))
                if fresh:
                    w.writeheader()
                w.writerows(new)
        except OSError:
            pass


def load_live(root: Path, day: str) -> dict[str, Any] | None:
    path = root.joinpath(*LIVE_PATH)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _CACHE["live_mtime"] != mtime:
        try:
            _CACHE.update(live_mtime=mtime, live=json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None
    d = _CACHE["live"]
    return d if d and d.get("day") == day else None


def tags(symbol: str, direction: str, now: datetime, root: Path = ROOT) -> dict[str, Any]:
    """co_ tags for a candidate: co_p (chance of a +100 % run, from the chart alone), co_x (times the median score), co_top5 / co_top1 (in the model's top 5 % / 1 % of all scores)."""
    try:
        d = load_live(root, now.date().isoformat())
        if not d:
            return {}
        p = d["p"].get(f"{symbol}|{1 if str(direction).upper() == 'BULLISH' else -1}")
        if p is None:
            return {}
        q = d["q"]
        return {"co_p": p, "co_x": round(p / max(q["q50"], 1e-6), 2), "co_top5": int(p >= q["q95"]), "co_top1": int(p >= q["q99"])}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}


def payload(root: Path = ROOT, today: date | None = None) -> dict[str, Any]:
    d = load_live(root, (today or date.today()).isoformat())
    if not d:
        return {"ok": False, "error": "no live chart scores yet today (the tick recorder runs 09:05-15:32; needs about 40 stocks with 13 one-minute bars)"}
    return {**{k: v for k, v in d.items() if k != "p"}, "ok": True}


# --- nightly review -----------------------------------------------------------------------------------------------------------------------------------------------------------------
def review(root: Path = ROOT, day: str | None = None) -> Path | None:
    """Flags logged in data/chart_opps/<day>.csv against what the stock did next (5 / 15 / 30 / 60 minutes later) minus the market, from the recorded ticks (rs_replay), top 1 % vs the rest of the top 5 %."""
    import rs_replay

    day = day or date.today().isoformat()
    p = root / "data" / "chart_opps" / f"{day}.csv"
    if not p.exists():
        return None
    with p.open(encoding="utf-8", newline="") as h:
        flags = list(csv.DictReader(h))
    samples = rs_replay.load_samples(root, day)
    if not samples:
        return None
    series = rs_replay.series_by_symbol(samples)
    events = [{"time": r["time"], "symbol": r["symbol"], "kind": ("LEADER" if r["side"] == "1" else "LAGGARD") + ("_TOP1" if r["top1"] == "1" else "_TOP5")} for r in flags]
    rows = rs_replay.forward_moves(events, series, day)
    table = rs_replay._group(rows, lambda r: r["kind"])
    folder = root / "data" / "chart_opps"
    L = [f"# Chart opportunity flags, {day}", "", f"{len(flags)} flags (each stock and side at most once per {LOG_EVERY_MIN} minutes). Excess = the stock's move in the flagged direction minus the median stock's, over the same minutes (stock level; the option leverage comes on top).", ""]
    L += rs_replay._fmt_quality(table)
    (folder / f"review_{day}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return folder / f"review_{day}.md"


def run(day: str, root: Path = ROOT) -> None:
    review(root, day)


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "evaluate"
    if cmd == "build":
        build()
    elif cmd == "train":
        print(json.dumps(train(), indent=1))
    elif cmd == "review":
        print(review(ROOT, sys.argv[2] if len(sys.argv) > 2 else None) or "nothing to review")
    else:
        evaluate()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
