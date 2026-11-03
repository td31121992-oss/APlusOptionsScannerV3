"""Statistics for the top-movers study (stage 3 of top_movers_study.py). READ-ONLY research.

Every function takes the stock-day table (stock_days.pkl) or the option table (option_days.pkl) and returns small DataFrames the report turns into tables and charts.
Rule used throughout: a pattern is only called real when it points the same way in BOTH halves of the history (Jul 2021-Dec 2023 and Jan 2024-Aug 2026) and survives a volatility control
(compared only with stocks of the same normal range that day, because jumpy stocks reach the top-10 lists more often for no pattern reason).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

import top_movers_study as tm

SPLIT_DAY = 20240101
INF = np.inf

# feature -> (label, bucket edges). Every feature is known BEFORE the move (yesterday's close or earlier, or today's opening gap).
FEATURES: dict[str, tuple[str, list[float]]] = {
    "gap": ("Opening gap today (%)", [-INF, -2, -1, -0.3, 0.3, 1, 2, INF]),
    "pre_chg1": ("Yesterday's change (%)", [-INF, -4, -2, -0.5, 0.5, 2, 4, INF]),
    "pre_ret5": ("Return over the 5 days before (%)", [-INF, -6, -3, 0, 3, 6, INF]),
    "pre_ret20": ("Return over the 20 days before (%)", [-INF, -12, -5, 0, 5, 12, INF]),
    "pre_streak": ("Days up(+) / down(-) in a row before", [-INF, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, INF]),
    "pre_rng_ratio": ("Yesterday's range vs its 10-day average (x)", [0, 0.6, 0.8, 1.0, 1.3, INF]),
    "pre_close_pos": ("Where yesterday closed inside its range (%)", [-0.1, 20, 40, 60, 80, 100.1]),
    "pre_vol_ratio": ("Yesterday's volume vs 20-day average (x)", [0, 0.7, 1.0, 1.5, 2.5, INF]),
    "pre_from_hi20": ("Yesterday's close vs 20-day high (%)", [-INF, -10, -5, -2, -0.5, 0.01]),
    "pre_from_lo20": ("Yesterday's close vs 20-day low (%)", [-0.01, 0.5, 2, 5, 10, INF]),
    "pre_from_hi250": ("Yesterday's close vs 1-year high (%)", [-INF, -30, -15, -5, -1, 0.01]),
    "pre_from_lo250": ("Yesterday's close vs 1-year low (%)", [-0.01, 5, 15, 30, 60, INF]),
    "pre_dma20": ("Yesterday's close vs 20-day average (%)", [-INF, -6, -3, 0, 3, 6, INF]),
    "pre_dma50": ("Yesterday's close vs 50-day average (%)", [-INF, -10, -5, 0, 5, 10, INF]),
    "dte": ("Days to the monthly expiry", [-1, 3, 7, 14, 21, 40]),
}


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Valid stock-days only, with the volatility tercile (within the day), the half, the days-to-expiry and the market-day type."""
    v = df[df.valid & df.pre_atr20.notna()].copy()
    v["vol_t"] = (v.groupby("day").pre_atr20.rank(pct=True, method="first") * 3).clip(upper=2.999).astype(int)
    v["half"] = np.where(v.day < SPLIT_DAY, 1, 2)
    d = pd.to_datetime(v.day.astype(str), format="%Y%m%d")
    exp = {x: tm.monthly_expiry(x) for x in d.unique()}
    v["dte"] = (d.map(exp) - d).dt.days
    v["weekday"] = d.dt.dayofweek
    v["mkt_type"] = pd.cut(v.mkt_chg, [-INF, -1, -0.4, 0.4, 1, INF], labels=["market down >1%", "down 0.4-1%", "flat", "up 0.4-1%", "market up >1%"])
    return v


def _lift(sub: pd.DataFrame, flag: str, bucket: pd.Series) -> pd.DataFrame:
    """Hit rate of `flag` per bucket and the volatility-adjusted lift (hits / hits expected from the same-volatility base rate)."""
    base_t = sub.groupby("vol_t")[flag].mean()
    t = sub.assign(_b=bucket, _exp=sub.vol_t.map(base_t))
    g = t.groupby("_b", observed=True).agg(n=(flag, "size"), hits=(flag, "sum"), exp=("_exp", "sum"))
    g["rate"] = g.hits / g.n * 100
    g["lift"] = g.hits / g.exp
    return g


def lift_table(v: pd.DataFrame, feature: str, flag: str) -> pd.DataFrame:
    """One feature: per bucket, lift in the whole history and in each half, and a verdict."""
    label, edges = FEATURES[feature]
    col = v[feature].astype(float)
    if feature == "pre_streak":
        bk = pd.cut(col, edges, labels=["3+ down", "2 down", "1 down", "(none)", "1 up", "2 up", "3+ up"])
        bk = bk.where(col != 0)
    else:
        bk = pd.cut(col, edges, include_lowest=True)
    out = _lift(v, flag, bk)
    for h in (1, 2):
        s = v[v.half == h]
        out[f"lift_h{h}"] = _lift(s, flag, bk[s.index]).lift
    out["n_h1"], out["n_h2"] = [(bk[v.half == h].value_counts()).reindex(out.index).fillna(0) for h in (1, 2)]
    def verdict(r: pd.Series) -> str:
        a, b = r.lift_h1, r.lift_h2
        if not (np.isfinite(a) and np.isfinite(b)) or min(r.n_h1, r.n_h2) < 300:
            return "thin"
        if a >= 1.15 and b >= 1.15:
            return "MORE likely (holds in both halves)"
        if a <= 0.87 and b <= 0.87:
            return "LESS likely (holds in both halves)"
        return "no stable effect"
    out["verdict"] = out.apply(verdict, axis=1)
    out.index = [_label(i) for i in out.index]
    return out


def _label(i: Any) -> str:
    if isinstance(i, pd.Interval):
        lo, hi = i.left, i.right
        if lo == -INF:
            return f"up to {hi:g}"
        if hi == INF:
            return f"above {lo:g}"
        return f"{lo:g} to {hi:g}"
    return str(i)


def categorical_lift(v: pd.DataFrame, col: str, flag: str, min_n: int = 400) -> pd.DataFrame:
    out = _lift(v, flag, v[col].astype(str))
    for h in (1, 2):
        s = v[v.half == h]
        out[f"lift_h{h}"] = _lift(s, flag, s[col].astype(str)).lift
    return out[out.n >= min_n].sort_values("lift", ascending=False)


def prior_listing(v: pd.DataFrame) -> pd.DataFrame:
    """Does being in yesterday's top 10 (gainers / losers) change today's chance?"""
    rows = []
    for flag in ("top_gainer", "top_loser"):
        for prev in ("pre_top_gainer", "pre_top_loser"):
            s = v[v[prev].notna()]
            for val, name in ((True, "yes"), (False, "no")):
                m = s[s[prev] == val]
                rows.append({"today": flag, "yesterday_in": prev.replace("pre_", ""), "answer": name, "n": len(m), "rate_%": round(m[flag].mean() * 100, 2),
                             "h1_%": round(m[m.half == 1][flag].mean() * 100, 2), "h2_%": round(m[m.half == 2][flag].mean() * 100, 2)})
    return pd.DataFrame(rows)


def when_it_happens(v: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """How the day unfolds for the top-10 lists: how much of the final move was done by each clock time, when the high / low formed, and how many started with a gap."""
    out: dict[str, pd.DataFrame] = {}
    rows = []
    for flag, name in (("top_gainer", "gainers"), ("top_loser", "losers")):
        s = v[v[flag]]
        r = {"list": name, "n": len(s), "median_final_%": s.chg.median(), "gap_beyond_1%_in_direction": ((s.gap * np.sign(s.chg)) > 1).mean() * 100,
             "gap_beyond_2%_in_direction": ((s.gap * np.sign(s.chg)) > 2).mean() * 100}
        for k in tm.CHECKPOINTS:
            done = (s[f"r{k}"] / s.chg).clip(-1, 2)
            r[f"done_by_{k}_%"] = done.median() * 100
        extreme = s.hi_min if flag == "top_gainer" else s.lo_min
        r["extreme_before_10:00_%"] = (extreme <= 45).mean() * 100
        r["extreme_after_14:00_%"] = (extreme >= 285).mean() * 100
        rows.append(r)
    out["timing"] = pd.DataFrame(rows).set_index("list").round(1).T
    hist = {}
    for flag, name, col in (("top_gainer", "gainers: minute of day high", "hi_min"), ("top_loser", "losers: minute of day low", "lo_min")):
        s = v[v[flag]][col]
        hist[name] = np.histogram(s, bins=np.arange(0, 391, 30))[0] / max(1, len(s)) * 100
    out["extreme_hist"] = pd.DataFrame(hist, index=[f"{9 + (15 + m) // 60}:{(15 + m) % 60:02d}" for m in range(0, 361, 30)]).round(1)
    return out


def early_visibility(v: pd.DataFrame) -> pd.DataFrame:
    """If a stock is in the top-N at a clock time (ranked by its return vs yesterday's close at that moment) - how often is it a top-10 at the close, and what is left of the move?"""
    rows = []
    for side, up, flag, sign in (("gainers", "up_rank", "top_gainer", 1), ("losers", "dn_rank", "top_loser", -1)):
        for clk in ("0930", "1000", "1100"):
            rk = v[f"{up}_{clk}"]
            for n in (5, 10, 20):
                s = v[rk <= n]
                left = (s.close / s[f"px{clk}"] - 1) * 100 * sign                     # move still to come, in the direction of the list (stock terms)
                rows.append({"list": side, "seen_at": clk, "ranked_in_top": n, "n": len(s), "ends_top10_%": s[flag].mean() * 100, "median_left_%": left.median(), "avg_left_%": left.mean(),
                             "still_better_at_close_%": (left > 0).mean() * 100, "h1_still_%": (left[s.half == 1] > 0).mean() * 100, "h2_still_%": (left[s.half == 2] > 0).mean() * 100})
    return pd.DataFrame(rows).round(2)


def after_the_move(v: pd.DataFrame) -> pd.DataFrame:
    """Next day / next 3 and 5 days, measured from the move day's close, in the direction of the list (positive = the move continues)."""
    rows = []
    for flag, name, sign in (("top_gainer", "gainers", 1), ("top_loser", "losers", -1)):
        s = v[v[flag] & v.nx_chg.notna()]
        for label, m in (("all", s.index == s.index), ("closed in top 25% of range" if sign == 1 else "closed in bottom 25% of range",
                          (s.close - s.low) / (s.high - s.low).replace(0, np.nan) >= 0.75 if sign == 1 else (s.close - s.low) / (s.high - s.low).replace(0, np.nan) <= 0.25),
                         ("closed away from the extreme (reversal)", (s.close - s.low) / (s.high - s.low).replace(0, np.nan) <= 0.5 if sign == 1 else (s.close - s.low) / (s.high - s.low).replace(0, np.nan) >= 0.5),
                         ("move over 3 normal ranges", s.move_x_atr >= 3)):
            t = s[np.asarray(m)]
            row = {"list": name, "subset": label, "n": len(t)}
            for col, key in (("nx_gap", "next-day gap"), ("nx_chg", "next day"), ("nx_chg3", "next 3 days"), ("nx_chg5", "next 5 days")):
                x = t[col] * sign
                row[f"{key} avg %"] = x.mean()
                row[f"{key} continues %"] = (x > 0).mean() * 100
            row["h1 next-day avg %"] = (t[t.half == 1].nx_chg * sign).mean()
            row["h2 next-day avg %"] = (t[t.half == 2].nx_chg * sign).mean()
            rows.append(row)
    return pd.DataFrame(rows).round(2)


def event_paths(df: pd.DataFrame, v: pd.DataFrame, before: int = 10, after: int = 5) -> dict[str, pd.DataFrame]:
    """Average close path (rebased to yesterday's close = 0) from `before` days before to `after` days after the move day, for gainers and losers, and the same for a random stock (control)."""
    g = df.sort_values(["sym", "day_i"]).copy()
    g["cl"] = g.close
    out = {}
    for flag, name in (("top_gainer", "gainers"), ("top_loser", "losers")):
        keys = v[v[flag]][["sym", "day_i"]]
        paths = []
        by = {s: d for s, d in g.groupby("sym")}
        cols = {}
        for k in range(-before, after + 1):
            cols[k] = []
        for s, grp in keys.groupby("sym"):
            d = by[s].set_index("day_i")
            c = d.cl
            for di in grp.day_i:
                base = c.get(di - 1)
                if base is None or not np.isfinite(base):
                    continue
                for k in range(-before, after + 1):
                    x = c.get(di + k)
                    if x is not None and np.isfinite(x):
                        cols[k].append((x / base - 1) * 100)
        out[name] = pd.Series({k: np.mean(vv) if vv else np.nan for k, vv in cols.items()})
        out[name + "_median"] = pd.Series({k: np.median(vv) if vv else np.nan for k, vv in cols.items()})
    return out


def intraday_paths(v: pd.DataFrame, cube: np.ndarray, syms: list[str]) -> dict[str, np.ndarray]:
    """Average 5-minute return-vs-yesterday's-close path (75 points) of each list, from the candle cube; plus 25/75 percentiles."""
    sidx = {s: i for i, s in enumerate(syms)}
    out = {}
    for flag, name in (("top_gainer", "gainers"), ("top_loser", "losers")):
        s = v[v[flag]]
        rows = []
        for sym, di, prev in zip(s.sym, s.day_i, s.prev_close):
            c = cube[sidx[sym], int(di), :, 3].astype("float64")
            if np.isfinite(c).sum() >= 60:
                rows.append((pd.Series(c).ffill().to_numpy() / prev - 1) * 100)
        a = np.array(rows)
        out[name] = np.vstack([np.nanmean(a, axis=0), np.nanpercentile(a, 25, axis=0), np.nanpercentile(a, 75, axis=0)])
    return out


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# options
COST_PCT = 2.0           # round-trip cost taken off every option trade, in % of the premium (spread + slippage; brokerage is small beside it)


def join_options(opt: pd.DataFrame, v: pd.DataFrame) -> pd.DataFrame:
    """Option trades joined to the stock-day facts. `dir_ok` = the option's side matches the stock's final direction (call on a gainer, put on a loser)."""
    keep = ["sym", "day", "top_gainer", "top_loser", "chg", "gap", "from_open", "half", "vol_t", "mkt_chg", "pre_vol_ratio", "pre_rng_ratio",
            "up_rank_0930", "up_rank_1000", "up_rank_1100", "dn_rank_0930", "dn_rank_1000", "dn_rank_1100", "r0930", "r1000", "r1100"]
    j = opt.merge(v[keep], on=["sym", "day"], how="inner")
    j["half"] = j.half.astype(int)
    j["iv_chg"] = j.iv_c - j.iv_e
    j["oi_chg_pct"] = (j.oi_c / j.oi_e - 1) * 100
    j["out_A"] = np.where(j.wA == 1, 20.0, np.where(j.wA == -1, -20.0, j.close_g.clip(-20, 20)))
    j["out_B"] = np.where(j.wB == 1, 40.0, np.where(j.wB == -1, -25.0, j.close_g.clip(-25, 40)))
    j["net_close"] = j.close_g - COST_PCT
    j["net_A"] = j.out_A - COST_PCT
    j["net_B"] = j.out_B - COST_PCT
    return j


def summarise(t: pd.DataFrame) -> dict[str, Any]:
    """One row of option outcome statistics for a set of trades (gross unless named net)."""
    if t.empty:
        return {"n": 0}
    return {"n": len(t), "avg_premium": t.px_e.mean(), "close_avg_%": t.close_g.mean(), "close_med_%": t.close_g.median(), "close_win_%": (t.close_g > 0).mean() * 100,
            "max_avg_%": t.max_g.mean(), "max_med_%": t.max_g.median(), "touch_+20_%": (t.max_g >= 20).mean() * 100, "touch_-20_%": (t.min_g <= -20).mean() * 100,
            "touch_-10_%": (t.min_g <= -10).mean() * 100, "touch_-15_%": (t.min_g <= -15).mean() * 100, "A_win_%": (t.wA == 1).mean() * 100, "A_loss_%": (t.wA == -1).mean() * 100, "A_net_ev_%": t.net_A.mean(), "B_net_ev_%": t.net_B.mean(), "close_net_ev_%": t.net_close.mean(),
            "iv_chg_avg": t.iv_chg.mean(), "h1_A_net": t[t.half == 1].net_A.mean(), "h2_A_net": t[t.half == 2].net_A.mean(), "h1_close_net": t[t.half == 1].net_close.mean(),
            "h2_close_net": t[t.half == 2].net_close.mean()}


def table_rows(groups: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame({k: summarise(g) for k, g in groups.items()}).T


def hindsight_table(j: pd.DataFrame) -> pd.DataFrame:
    """Buy the matching option on each day's top-10 (call on gainers, put on losers) - the best case, picked with hindsight - by entry time and strike."""
    rows = {}
    for et in ("0920", "0930", "1000", "1030", "1100"):
        for st in ("ITM1", "ATM", "OTM1"):
            g = j[(j.et == et) & (j.st == st)]
            m = g[((g.side == "CE") & g.top_gainer) | ((g.side == "PE") & g.top_loser)]
            rows[f"hindsight top-10 | {et} | {st}"] = m
    return table_rows(rows)


def control_table(j: pd.DataFrame) -> pd.DataFrame:
    """The same trades on EVERY stock-day (no stock picking) - what a plain option bought at that time does: this is the bar a pattern has to beat."""
    rows = {}
    for et in ("0930", "1000", "1100"):
        for side in ("CE", "PE"):
            rows[f"all stocks | {side} | {et} | ATM"] = j[(j.et == et) & (j.st == "ATM") & (j.side == side)]
    return table_rows(rows)


def rule_table(j: pd.DataFrame) -> pd.DataFrame:
    """Rules a scanner could actually apply (only information known at the entry time), ATM, with the same stats and the halves."""
    A = j[j.st == "ATM"]
    def pick(et: str, side: str, mask_fn) -> pd.DataFrame:
        g = A[(A.et == et) & (A.side == side)]
        return g[mask_fn(g)]
    rules = {
        "CHASE: call on a top-10 gainer at 10:00 (buy at 10:00)": pick("1000", "CE", lambda g: g.up_rank_1000 <= 10),
        "CHASE: put on a top-10 loser at 10:00 (buy at 10:00)": pick("1000", "PE", lambda g: g.dn_rank_1000 <= 10),
        "CHASE: call on a top-10 gainer at 11:00 (buy at 11:00)": pick("1100", "CE", lambda g: g.up_rank_1100 <= 10),
        "CHASE: put on a top-10 loser at 11:00 (buy at 11:00)": pick("1100", "PE", lambda g: g.dn_rank_1100 <= 10),
        "FADE: put on a top-10 gainer at 10:00": pick("1000", "PE", lambda g: g.up_rank_1000 <= 10),
        "FADE: call on a top-10 loser at 10:00": pick("1000", "CE", lambda g: g.dn_rank_1000 <= 10),
        "GAP-AND-GO: call when gap > +2% (buy 09:30)": pick("0930", "CE", lambda g: g.gap > 2),
        "GAP-AND-GO: put when gap < -2% (buy 09:30)": pick("0930", "PE", lambda g: g.gap < -2),
        "GAP-FADE: put when gap > +2% (buy 09:30)": pick("0930", "PE", lambda g: g.gap > 2),
        "GAP-FADE: call when gap < -2% (buy 09:30)": pick("0930", "CE", lambda g: g.gap < -2),
        "GAP-FADE: put when gap > +1% (buy 09:30)": pick("0930", "PE", lambda g: g.gap > 1),
        "GAP-FADE: call when gap < -1% (buy 09:30)": pick("0930", "CE", lambda g: g.gap < -1),
    }
    return table_rows(rules)


def by_dte(j: pd.DataFrame) -> pd.DataFrame:
    """Hindsight trades split by days to expiry (theta and gamma change a lot)."""
    g = j[(j.et == "1000") & (j.st == "ATM")]
    m = g[((g.side == "CE") & g.top_gainer) | ((g.side == "PE") & g.top_loser)].copy()
    m["dte_bucket"] = pd.cut(m.dte, [-1, 3, 7, 14, 21, 40], labels=["0-3", "4-7", "8-14", "15-21", "22+"])
    return table_rows({f"DTE {k}": x for k, x in m.groupby("dte_bucket", observed=True)})


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# day types
DAY_TYPES = ("gap-driven (most of the move at the open)", "recovery (went against the list first, then reversed)", "late surge (over 40% of the move after 13:00)",
             "early trend (a third done by 10:00)", "mid-day build (slow start)")


def classify(v: pd.DataFrame) -> pd.Series:
    """Label every top-10 stock-day with how its day unfolded (the lists' members only; first matching rule wins)."""
    s = np.where(v.top_gainer, 1.0, np.where(v.top_loser, -1.0, np.nan))
    chg = v.chg.abs()
    gap_part = s * v.gap
    against = np.where(s > 0, (v.low / v.prev_close - 1) * 100, -(v.high / v.prev_close - 1) * 100)         # worst excursion against the list's direction, in % (<= 0)
    late = s * (v.chg - v.r1300) / chg
    early = s * v.r1000 / chg
    t = np.select([gap_part >= 1.5, (against <= -0.8) & (gap_part < 1.5) & (chg >= 2) & (np.abs(v.gap) < 1.5), late >= 0.4, early >= 0.35],
                  [DAY_TYPES[0], DAY_TYPES[1], DAY_TYPES[2], DAY_TYPES[3]], default=DAY_TYPES[4])
    return pd.Series(np.where(np.isnan(s), "", t), index=v.index)


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ceiling: can a trained model see it?
CEILING_FEATURES = ["gap", "r0930", "r1000", "intr1000", "rel1000", "mkt_r1000", "pre_chg1", "pre_ret5", "pre_ret20", "pre_rng_ratio", "pre_vol_ratio", "pre_close_pos", "pre_from_hi20",
                    "pre_from_lo20", "pre_dma20", "pre_dma50", "pre_atr20", "pre_streak", "dte"]


def ceiling(v: pd.DataFrame) -> dict[str, Any]:
    """Train on 2021-23, test on 2024-26 with everything known by 10:00 (pre-day features, the gap, the move so far, the market's move so far). Does it beat simply ranking by the 10:00 move?"""
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    from sklearn.metrics import roc_auc_score

    w = v[v.r1000.notna()].copy()
    w["mkt_r1000"] = w.groupby("day").r1000.transform("median")
    w["rel1000"] = w.r1000 - w.mkt_r1000
    w["intr1000"] = (w.px1000 / w.open - 1) * 100
    w = w.dropna(subset=CEILING_FEATURES)
    tr, te = w[w.day < SPLIT_DAY], w[w.day >= SPLIT_DAY].copy()
    rows = []
    for tgt, name, sign in (("top_gainer", "top-10 gainers", 1), ("top_loser", "top-10 losers", -1)):
        m = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.06, max_depth=4, random_state=1).fit(tr[CEILING_FEATURES], tr[tgt])
        te["p"] = m.predict_proba(te[CEILING_FEATURES])[:, 1]

        def prec(score: pd.Series) -> float:
            r = te.assign(s=score).groupby("day").s.rank(ascending=False, method="first")
            return te[r <= 10][tgt].mean() * 100
        rows.append({"target": name, "AUC (model)": roc_auc_score(te[tgt], te.p), "model picks that finish in the top 10 (%)": prec(te.p),
                     "picks by simply ranking the 10:00 move (%)": prec(sign * te.r1000), "random pick (%)": te[tgt].mean() * 100})
    w["left"] = (w.close / w.px1000 - 1) * 100
    tr, te = w[w.day < SPLIT_DAY], w[w.day >= SPLIT_DAY].copy()
    reg = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, max_depth=4, random_state=1).fit(tr[CEILING_FEATURES], tr.left)
    te["pred"] = reg.predict(te[CEILING_FEATURES])
    te["dec"] = te.groupby("day").pred.rank(pct=True)
    dec = te.groupby(pd.cut(te.dec, [0, .1, .2, .5, .8, .9, 1.0]), observed=True).left.agg(["mean", "median", "size"])
    dec.index = ["lowest 10%", "10-20%", "20-50%", "50-80%", "80-90%", "highest 10%"]
    return {"classify": pd.DataFrame(rows).set_index("target"), "left_by_decile": dec.rename(columns={"mean": "avg move left to close %", "median": "median %", "size": "n"}),
            "corr": float(te.pred.corr(te.left)), "n_test": len(te)}
