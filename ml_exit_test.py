"""Walk-forward tests of two small ML models on our own paper trades (RESEARCH ONLY - touches no scanner or trade).  .venv\\Scripts\\python ml_exit_test.py

A. ENTRY-QUALITY: from what the trade record holds at entry (setup family, side, entry minute, premium, spread, clean score, chase risk, Nifty move, the stock's last 15 minutes ...) predict whether the trade
   ends on its option stop. Trained on earlier DAYS only, tested on the next day, repeated day by day (paper trades from 1 Oct 2026). Metric: AUC, and the P&L of skipping the trades with the highest
   predicted stop risk.
B. EXIT: for the trades whose option was recorded tick by tick (data/option_ticks, 26-28 Oct), at every 5th minute after entry predict the option's remaining return to the day's end from time held, gain,
   best gain, drop from the best, the last 5 / 15 minutes, premium, side; exit at the first checkpoint where the prediction is below a threshold. Trained on earlier days only. Very small sample.
Costs are the trades' own recorded costs (they are the same in every variant). Output: E:\\APlusData\\top_movers_study\\ml_exit_test.txt
"""

from __future__ import annotations

import glob
import gzip
import io
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent
OUT = Path(r"E:\APlusData\top_movers_study")
lines: list[str] = []


def say(s: str = "") -> None:
    print(s)
    lines.append(s)


def load() -> pd.DataFrame:
    h = json.loads((ROOT / "data" / "reports" / "paper_trade_history.json").read_text(encoding="utf-8")).get("paper_trades", [])
    j = json.loads((ROOT / "data" / "intraday_movement" / "paper_trade_journal.json").read_text(encoding="utf-8")).get("trades", [])
    by = {t["paper_trade_id"]: t for t in h}
    by.update({t["paper_trade_id"]: t for t in j})
    d = pd.DataFrame(list(by.values()))
    d["day"] = d.entry_time.astype(str).str[:10]
    d = d[d.day >= "2026-10-01"].copy()
    d["net_pnl"] = pd.to_numeric(d.net_pnl, errors="coerce")
    d = d[d.status.astype(str).str.upper().isin(["CLOSED"]) & d.net_pnl.notna()].copy()
    d["stopped"] = (d.exit_reason == "OPTION_STOP_LOSS").astype(int)
    hm = d.entry_time.astype(str).str[11:16]
    d["entry_min"] = hm.str[:2].astype(int) * 60 + hm.str[3:5].astype(int)
    d["is_put"] = (d.option_type == "PE").astype(int)
    for fam in ("ESTABLISHED_TREND", "CONTINUATION_BREAKOUT", "HEALTHY_PULLBACK", "FRESH_BREAKOUT"):
        d["fam_" + fam] = (d.setup_family == fam).astype(int)
    return d.sort_values("entry_time").reset_index(drop=True)


A_FEATS = ["entry_min", "is_put", "entry_premium", "entry_spread_pct", "clean_trend_score", "chase_risk_score", "rule_nifty_pct_open", "recent_move_15m_percent", "momentum_score", "trend_alignment_score",
           "day_entry_rank", "fam_ESTABLISHED_TREND", "fam_CONTINUATION_BREAKOUT", "fam_HEALTHY_PULLBACK", "fam_FRESH_BREAKOUT"]


def test_a(d: pd.DataFrame) -> None:
    say("## A. Entry-quality model: will this trade end on its stop?")
    say("")
    X = d[A_FEATS].apply(pd.to_numeric, errors="coerce")
    X = X.fillna(X.median())
    days = sorted(d.day.unique())
    pred = pd.Series(np.nan, index=d.index)
    for i, day in enumerate(days):
        tr = d.day < day
        if tr.sum() < 40 or d.loc[tr, "stopped"].nunique() < 2:
            continue
        te = d.day == day
        m = make_pipeline(StandardScaler(), LogisticRegression(C=0.05, max_iter=500))
        m.fit(X[tr], d.loc[tr, "stopped"])
        pred[te] = m.predict_proba(X[te])[:, 1]
    t = d[pred.notna()].copy()
    t["p"] = pred[pred.notna()]
    say(f"Tested blind on {t.day.nunique()} days, {len(t)} trades ({t.day.min()}..{t.day.max()}); stop rate {t.stopped.mean() * 100:.0f}%, net {t.net_pnl.sum():,.0f}")
    auc = roc_auc_score(t.stopped, t.p)
    rs = np.random.default_rng(0)
    boots = [roc_auc_score(t.stopped.iloc[i], t.p.iloc[i]) for i in (rs.integers(0, len(t), len(t)) for _ in range(400)) if t.stopped.iloc[i].nunique() > 1]
    say(f"AUC {auc:.3f}  (0.5 = no skill; 95% range {np.percentile(boots, 2.5):.3f}..{np.percentile(boots, 97.5):.3f})")
    say("")
    say("| Skip the trades with the highest predicted stop risk | Trades skipped | Their net | Trades kept | Kept net |")
    say("|---|---|---|---|---|")
    for q in (0.0, 0.2, 0.33, 0.5):
        if q == 0:
            say(f"| none (all trades) | 0 | - | {len(t)} | {t.net_pnl.sum():,.0f} |")
            continue
        thr = t.p.quantile(1 - q)
        sk = t[t.p >= thr]
        say(f"| top {int(q * 100)}% | {len(sk)} | {sk.net_pnl.sum():,.0f} | {len(t) - len(sk)} | {t.net_pnl.sum() - sk.net_pnl.sum():,.0f} |")
    say("")


def ticks(t: pd.Series) -> pd.DataFrame | None:
    fs = glob.glob(str(ROOT / "data" / "option_ticks" / t["day"] / f"{t.get('option_security_id')}_*.csv.gz"))
    if not fs:
        return None
    raw = bytearray()
    try:
        with gzip.open(fs[0], "rb") as f:
            while True:
                c = f.read(4096)
                if not c:
                    break
                raw += c
    except Exception:                                    # noqa: BLE001
        pass
    if not raw:
        return None
    try:
        df = pd.read_csv(io.StringIO(raw.decode("utf-8", "ignore")), on_bad_lines="skip", engine="python")
    except Exception:                                    # noqa: BLE001
        return None
    if "ltp" not in df or "ts" not in df:
        return None
    df["ltp"] = pd.to_numeric(df.ltp, errors="coerce")
    df = df[df.ltp > 0].copy()
    hms = df.ts.astype(str).str[:8]                         # the tick time is HH:MM:SS...
    df = df[hms.str.match(r"^\d\d:\d\d:\d\d$")].copy()
    hms = df.ts.astype(str).str[:8]
    df["m"] = hms.str[:2].astype(int) * 60 + hms.str[3:5].astype(int)
    return df


def test_b(d: pd.DataFrame) -> None:
    say("## B. Exit model on tick paths (26-28 Oct)")
    say("")
    rows = []
    for _, t in d[d.day >= "2026-10-26"].iterrows():
        df = ticks(t)
        entry = float(t.entry_price)
        if df is None or not entry > 0:
            continue
        per = df.groupby("m").ltp.last()
        start = int(t.entry_min)
        per = per[per.index >= start]
        if len(per) < 20:
            continue
        path = per.reindex(range(start, 15 * 60 + 11)).ffill()
        path = path.dropna()
        if len(path) < 20:
            continue
        final = float(path.iloc[-1])
        cost = float(t.gross_pnl) - float(t.net_pnl)
        peak = entry
        for k in range(5, len(path) - 5, 5):
            px = float(path.iloc[k])
            peak = max(peak, float(path.iloc[:k + 1].max()))
            rows.append({"tid": t.paper_trade_id, "day": t.day, "k": k, "gain": (px / entry - 1) * 100, "peak": (peak / entry - 1) * 100, "dd": (px / peak - 1) * 100,
                         "r5": (px / float(path.iloc[k - 5]) - 1) * 100, "r15": (px / float(path.iloc[max(0, k - 15)]) - 1) * 100, "prem": entry, "put": int(t.is_put), "sp": float(t.entry_spread_pct or 0),
                         "rem": (final / px - 1) * 100, "px": px, "final": final, "entry": entry, "qty": float(t.quantity), "cost": cost, "stop": float(t.option_stop or 0) or entry * 0.8})
    cp = pd.DataFrame(rows)
    if cp.empty:
        say("no tick paths found")
        return
    n_tr = cp.tid.nunique()
    say(f"{n_tr} trades with usable tick paths, {len(cp)} five-minute checkpoints, days {sorted(cp.day.unique())}")
    say("")
    F = ["k", "gain", "peak", "dd", "r5", "r15", "prem", "put", "sp"]
    days = sorted(cp.day.unique())
    res = []
    for day in days[1:]:
        tr, te = cp[cp.day < day], cp[cp.day == day]
        m = HistGradientBoostingRegressor(max_depth=3, max_iter=80, learning_rate=0.05, min_samples_leaf=30, random_state=0)
        m.fit(tr[F], tr.rem.clip(-60, 60))
        te = te.assign(p=m.predict(te[F]))
        for thr in (-3.0, -5.0, -8.0):
            for tid, g in te.groupby("tid"):
                g = g.sort_values("k")
                hit = g[g.p < thr]
                px_exit = float(hit.px.iloc[0]) if len(hit) else float(g.final.iloc[0])
                hold = float(g.final.iloc[0])
                e, q, c = float(g.entry.iloc[0]), float(g.qty.iloc[0]), float(g.cost.iloc[0])
                res.append({"day": day, "thr": thr, "tid": tid, "model": (px_exit - e) * q - c, "hold": (hold - e) * q - c})
    r = pd.DataFrame(res)
    say("Walk-forward over days (train on earlier days, test the next). Hold = hold to the day end (the recorded last tick).")
    say("")
    say("| Exit when predicted remaining return is below | Test days | Trades | Model net | Hold-to-end net |")
    say("|---|---|---|---|---|")
    for thr, g in r.groupby("thr"):
        say(f"| {thr:.0f}% | {g.day.nunique()} | {g.tid.nunique()} | {g.model.sum():,.0f} | {g.hold.sum():,.0f} |")
    say("")
    say("Note: 2 test days and a few dozen trades: this shows whether the method runs and whether anything is visible, it cannot prove an edge.")
    say("")


def main() -> None:
    d = load()
    say(f"# ML tests on our paper trades  ({len(d)} closed trades from {d.day.min()} to {d.day.max()})")
    say("")
    test_a(d)
    test_b(d)
    (OUT / "ml_exit_test.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
