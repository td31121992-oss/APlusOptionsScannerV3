"""Shadow machine-learning score for every candidate (SHADOW ONLY: the score is recorded as ml_ tags and in a score log; nothing trades, blocks or sizes on it).

The offline research (ds_pipeline.py, 83 days, 118,819 hypothetical option trades, walk-forward) found a gradient-boosting model with weak, unstable skill (mean AUC 0.58; its top 10 % lost 6.7 %
against 10.5 % for all trades, and one block was far worse than random). This runs that model live, in shadow, so its real out-of-sample behaviour is measured on trades we actually consider
before anyone decides whether it deserves a vote.

    features   the ds_pipeline set minus the two option-candle features that cannot be had live (oi_change, vol_ratio): 10 chart numbers from the stock's 1-minute closes since the open
               (chart_features.py), relative strength vs the median stock, market direction and breadth (all from the live tick board, written by the tick recorder every 20 s to
               data/ticks/ml_features_live.json), the ATM option premium as % of the stock price (approximated from the candidate's slightly in-the-money leg: its time value) and the ATM IV (from the candidate's option chain), minute of day, side, weekday
    model      HistGradientBoostingClassifier(max_depth 3, 150 iterations, strong regularisation), label = the ATM option, bought at the bar close and held to 15:15 with a 20 % stop, wins after costs
    tags       ml_p (probability of a win), ml_top10 (1 when ml_p is in the model's own top 10 % of scores), ml_in_range (1 between 10:00 and 12:00, the only times it was trained on),
               ml_complete (1 when every feature was available), ml_version

    python ml_shadow.py train        fit on data/data_science/dataset.csv.gz (+ the newest rows of data/ml_shadow/training_extra.csv.gz when present) -> data/data_science/ml_model.pkl
    python ml_shadow.py review [day]  how the logged scores did against the day's candidates and paper trades -> data/ml_shadow/review.md

Every scored candidate is appended to data/ml_shadow/scores_<day>.csv with its features, so the model can later be retrained and judged on what the live system really saw.
"""

from __future__ import annotations

import csv
import json
import pickle
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
CHART = ["d_ret_open", "d_ret_3", "d_ret_6", "d_ret_12", "range_pos_dir", "dist_extreme_pct", "vol_12", "or_status", "d_slope_12", "efficiency_12"]
FEATURES = CHART + ["rs_dir", "mkt_dir", "breadth_dir", "premium_pct", "iv", "minute", "side", "weekday"]
MIN_BARS = 13                                   # five-minute bars (65 minutes: the model is only used from about 10:20)
BAR_MIN = 5                                     # the training data (options_history) is 5-minute bars; the live series is made from one-minute closes at the end of each 5-minute bucket
OPEN_MIN = 9 * 60 + 15
WRITE_EVERY_S = 20.0
RANGE = (10 * 60, 12 * 60)
MODEL_PATH = ("data", "data_science", "ml_model.pkl")
LIVE_PATH = ("data", "ticks", "ml_features_live.json")
VERSION = "ds-lite-1"


# --- live features (tick recorder side) -----------------------------------------------------------------------------------------------------------------------------------------
def five_min(closes: list[float]) -> list[float]:
    """Closes of the COMPLETE 5-minute bars from a one-minute close series that starts at 09:15 (index 0): the last minute of each bucket."""
    return closes[BAR_MIN - 1::BAR_MIN]


def live_features(bars_by_symbol: Mapping[str, list[float]], minute: int) -> dict[str, Any] | None:
    """Per stock and side, the chart numbers for the latest complete 5-minute bar (from the one-minute closes), plus the market numbers. None while fewer than 40 stocks have MIN_BARS bars.
    `minute` is the current minute of the day; the returned "minute" is the latest bar's own time (the label the training data uses) and "asof_minute" is the current minute."""
    from chart_features import feature_vector

    n_done = (minute - OPEN_MIN + 1) // BAR_MIN
    bars_by_symbol = {s: five_min(b) for s, b in bars_by_symbol.items()}
    minute_label = OPEN_MIN + BAR_MIN * (n_done - 1)
    ret_open = {s: (b[-1] / b[0] - 1.0) * 100.0 for s, b in bars_by_symbol.items() if len(b) >= MIN_BARS and b[0] > 0}
    if len(ret_open) < 40:
        return None
    vals = sorted(ret_open.values())
    mkt = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2.0
    breadth = sum(1 for v in vals if v > 0) / len(vals)
    stocks: dict[str, Any] = {}
    for s, r in ret_open.items():
        series = np.asarray(bars_by_symbol[s], dtype=float)
        stocks[s] = {str(side): {**{k: round(float(v), 4) for k, v in feature_vector(series, side).items()}, "rs_dir": round(side * (r - mkt), 4), "mkt_dir": round(side * mkt, 4),
                                 "breadth_dir": round(side * (breadth - 0.5), 4)} for side in (1, -1)}
    return {"minute": minute_label, "asof_minute": minute, "mkt": round(mkt, 3), "breadth": round(breadth, 3), "n": len(ret_open), "stocks": stocks}


class MinuteBars:
    """Last price of every minute since the open, per stock, filled forward over minutes without a tick. O(1) per tick."""

    def __init__(self) -> None:
        self.bars: dict[str, list[float]] = {}
        self.minute: dict[str, int] = {}
        self._written = -1e9
        self._scorer = None
        self._bb = None
        self._bb_bars = -1

    def update(self, sym: str, t_s: float, ltp: float) -> None:
        m = int(t_s // 60)
        if m < OPEN_MIN or ltp <= 0:
            return
        b = self.bars.get(sym)
        if b is None:
            self.bars[sym] = [ltp] * (m - OPEN_MIN + 1)                  # a stock whose first tick came late is padded back to the open with its first price
            self.minute[sym] = m
            return
        last_m = self.minute[sym]
        if m > last_m:
            b.extend([b[-1]] * (m - last_m - 1))
            b.append(ltp)
            self.minute[sym] = m
        elif m == last_m:
            b[-1] = ltp

    def maybe_write(self, root: Path, day: str, t_s: float, wall: float) -> bool:
        if wall - self._written < WRITE_EVERY_S:
            return False
        self._written = wall
        minute = int(t_s // 60)
        for s, b in self.bars.items():                                       # carry every stock to the current minute so all series end on the same bar
            gap = minute - self.minute[s]
            if 0 < gap < 400:
                b.extend([b[-1]] * gap)
                self.minute[s] = minute
        out = live_features(self.bars, minute)
        if out is None:
            return False
        out.update(day=day, updated=f"{int(t_s // 3600):02d}:{int(t_s % 3600 // 60):02d}:{int(t_s % 60):02d}")
        p = root.joinpath(*LIVE_PATH)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(out), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            return False
        try:                                               # base-break detector (base_break.py) on the same 5-minute closes, once per completed bar
            import base_break

            n_done = (minute - OPEN_MIN + 1) // BAR_MIN
            if n_done != self._bb_bars:
                self._bb_bars = n_done
                if self._bb is None:
                    self._bb = base_break.LiveDetector()
                self._bb.update(root, day, {s: five_min(b) for s, b in self.bars.items()}, OPEN_MIN + BAR_MIN * (n_done - 1), t_s)
        except Exception:                                  # noqa: BLE001
            pass
        try:                                               # the chart-opportunity scorer reads the same features (chart_opportunity.py); its failure never stops the recording
            import chart_opportunity

            if self._scorer is None:
                self._scorer = chart_opportunity.LiveScorer()
            self._scorer.score(root, out, day, t_s)
        except Exception:                                  # noqa: BLE001
            pass
        return True


# --- model ------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def train(root: Path = ROOT) -> dict[str, Any]:
    """Fit on the offline dataset (and any live-collected extra rows), keep the score distribution of a held-out last 20 % of days for the top-10 % line. Saves the model."""
    import pandas as pd
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score

    df = pd.read_csv(root / "data" / "data_science" / "dataset.csv.gz")
    extra = root / "data" / "ml_shadow" / "training_extra.csv.gz"
    if extra.exists():
        df = pd.concat([df, pd.read_csv(extra)], ignore_index=True)
    df = df.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    dates = sorted(df.date.unique())
    cut = dates[int(len(dates) * 0.8)]
    params = dict(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=300, l2_regularization=5.0, random_state=0)
    hold_tr, hold_te = df[df.date < cut], df[df.date >= cut]
    check = HistGradientBoostingClassifier(**params).fit(hold_tr[FEATURES], (hold_tr.ret_pct > 0).astype(int))
    p = check.predict_proba(hold_te[FEATURES])[:, 1]
    y = (hold_te.ret_pct > 0).astype(int)
    q = {k: float(np.quantile(p, v)) for k, v in (("q10", 0.10), ("q50", 0.50), ("q90", 0.90))}
    n10 = max(50, len(p) // 10)
    top = hold_te.assign(p=p).nlargest(n10, "p")
    clf = HistGradientBoostingClassifier(**params).fit(df[FEATURES], (df.ret_pct > 0).astype(int))
    meta = {"version": VERSION, "trained_at": datetime.now(IST).isoformat(timespec="seconds"), "rows": int(len(df)), "days": len(dates), "first_day": str(dates[0]), "last_day": str(dates[-1]),
            "holdout_from": str(cut), "holdout_auc": round(float(roc_auc_score(y, p)), 3), "holdout_top10_mean_ret": round(float(top.ret_pct.mean()), 2),
            "holdout_all_mean_ret": round(float(hold_te.ret_pct.mean()), 2), "p_quantiles": q, "features": FEATURES}
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


def _live(root: Path) -> dict[str, Any] | None:
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
    return _CACHE["live"]


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def tags(symbol: str, direction: str, now: datetime, record: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """The ml_ tags for a candidate. {} when the model or the live features are missing / from another day / older than 2 minutes."""
    try:
        obj, live = _model(root), _live(root)
        if not obj or not live or live.get("day") != now.date().isoformat():
            return {}
        minute = now.hour * 60 + now.minute
        if minute - int(live.get("asof_minute", live.get("minute", 0))) > 2:
            return {}
        side = 1 if str(direction).upper() == "BULLISH" else -1
        row = (live.get("stocks", {}).get(symbol) or {}).get(str(side))
        if not row:
            return {}
        ltp, kltp, iv = _f(record.get("ltp")), _f(record.get("oc_k_ltp")), _f(record.get("iv_atm"))
        complete = int(bool(ltp and kltp and iv))
        import options_tags

        prem = max(0.05, kltp / ltp * 100.0 - options_tags.ITM_PCT) if ltp and kltp else 0.0         # the leg we price is ITM_PCT % in the money: take its intrinsic value off to approximate the ATM premium the model trained on
        feats = {**row, "premium_pct": prem, "iv": iv or 0.0, "minute": min(max(minute, RANGE[0]), RANGE[1]), "side": side, "weekday": now.weekday()}
        import pandas as pd

        p = float(obj["model"].predict_proba(pd.DataFrame([[float(feats[k]) for k in FEATURES]], columns=FEATURES))[:, 1][0])
        q90 = obj["meta"]["p_quantiles"]["q90"]
        out = {"ml_p": round(p, 4), "ml_top10": int(p >= q90), "ml_in_range": int(RANGE[0] <= minute <= RANGE[1]), "ml_complete": complete, "ml_version": obj["meta"]["version"]}
        log_score(root, now, symbol, direction, out, feats)
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}


_LOGGED: dict[tuple[str, str, str], float] = {}
SCORE_FIELDS = ["time", "symbol", "direction", "ml_p", "ml_top10", "ml_in_range", "ml_complete"] + FEATURES


def log_score(root: Path, now: datetime, symbol: str, direction: str, out: Mapping[str, Any], feats: Mapping[str, Any]) -> None:
    """One line per candidate per 5 minutes (the scanner re-evaluates a candidate every cycle)."""
    key = (now.date().isoformat(), symbol, direction)
    if now.timestamp() - _LOGGED.get(key, 0.0) < 300:
        return
    _LOGGED[key] = now.timestamp()
    p = root / "data" / "ml_shadow" / f"scores_{now.date().isoformat()}.csv"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        new = not p.exists()
        with p.open("a", encoding="utf-8", newline="") as h:
            w = csv.DictWriter(h, fieldnames=SCORE_FIELDS)
            if new:
                w.writeheader()
            w.writerow({"time": now.strftime("%H:%M:%S"), "symbol": symbol, "direction": direction, **{k: out.get(k) for k in ("ml_p", "ml_top10", "ml_in_range", "ml_complete")},
                        **{k: round(float(feats[k]), 4) for k in FEATURES}})
    except OSError:
        pass


# --- review -------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _auc(pos: list[float], neg: list[float]) -> float | None:
    if not pos or not neg:
        return None
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    rank_sum, i = 0.0, 0
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]:
            j += 1
        avg = (i + 1 + j) / 2.0
        rank_sum += avg * sum(1 for k in range(i, j) if allv[k][1] == 1)
        i = j
    return round((rank_sum - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg)), 3)


def review(root: Path = ROOT, upto: str | None = None) -> Path | None:
    """Do the logged scores separate winners from losers? Against (a) every scored candidate's option outcome in data/missed_opportunities/<day>/option_returns.json (close > 0) and (b) the paper trades."""
    folder = root / "data" / "ml_shadow"
    days = sorted(p.stem.split("_", 1)[1] for p in folder.glob("scores_*.csv"))
    if upto:
        days = [d for d in days if d <= upto]
    if not days:
        return None
    cand_p, cand_y, buckets = [], [], {"top 10% (model's own line)": [], "rest": []}
    for d in days:
        try:
            outcomes = {(o["symbol"], o["dir"]): o for o in json.loads((root / "data" / "missed_opportunities" / d / "option_returns.json").read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            continue
        with (folder / f"scores_{d}.csv").open(encoding="utf-8", newline="") as h:
            seen = set()
            for r in csv.DictReader(h):
                k = (r["symbol"], r["direction"])
                o = outcomes.get(k)
                if o is None or k in seen or o.get("close") in (None, ""):
                    continue
                seen.add(k)
                p, close = float(r["ml_p"]), float(o["close"])
                cand_p.append(p)
                cand_y.append(close > 0)
                buckets["top 10% (model's own line)" if r["ml_top10"] == "1" else "rest"].append(close)
    lines = ["# Shadow ML score review (research only)", "", f"Days with scores: {len(days)} ({days[0]}..{days[-1]}). Outcome = the candidate's option return at the close (missed_opportunities), first score per candidate per day.", ""]
    if cand_p:
        pos = [p for p, y in zip(cand_p, cand_y) if y]
        neg = [p for p, y in zip(cand_p, cand_y) if not y]
        lines += [f"Candidates with an outcome: {len(cand_p)}; share with a positive close: {100 * len(pos) / len(cand_p):.0f}%; AUC of ml_p on them: {_auc(pos, neg)} (0.5 = no skill; needs several hundred candidates to mean anything).", "",
                  "| Group | Candidates | Mean option return at close | Positive close |", "|---|---|---|---|"]
        for k, v in buckets.items():
            lines.append(f"| {k} | {len(v)} | {np.mean(v):+.1f}% | {100 * sum(1 for x in v if x > 0) / len(v):.0f}% |" if v else f"| {k} | 0 | - | - |")
    else:
        lines.append("No scored candidates with a known outcome yet.")
    out = folder / "review.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def run(day: str, root: Path = ROOT) -> None:
    review(root, day)


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "review"
    if cmd == "train":
        print(json.dumps(train(), indent=1))
    else:
        print(review(ROOT, sys.argv[2] if len(sys.argv) > 2 else None) or "no scores yet")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
