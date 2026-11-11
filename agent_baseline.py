"""A plain statistical baseline for the AI agent: do the entry-time facts hold ANY signal? (read-only research; no trading effect)

Before an AI judge is trusted, it needs something to beat. This trains a simple model (logistic regression and a small gradient-boosted tree) on the same packets the agent sees, walking forward through
the days: for each day it trains only on earlier days and scores that day's trades. Out-of-sample scores are then compared with chance:

    AUC                   0.5 = no information; the range shown comes from shuffling the scores within each day 300 times
    "take the best X%"    each day take only the trades with the highest predicted chance of a profit; the net of those against the net of all trades, and against a random pick of the same size

Targets: net profit (win) and "touched Rs 3,000 of profit at some point". All the usual warnings apply: about 500 trades, a short period, many correlated features.

    python agent_baseline.py        writes data/ai_agent/baseline_report.md
"""

from __future__ import annotations

import random
import statistics as st
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "ai_agent"
WARMUP_TRADES = 150
TOP_SHARES = (0.5, 0.3, 0.2)


def frame(trades: Sequence[dict[str, Any]], root: Path = ROOT):
    """(features DataFrame, win labels, touched-3k labels, days, net P&L) for the trades, using only packet facts."""
    import pandas as pd

    import agent_packet
    from sector_rank945 import sector_labels

    sectors = sector_labels(root)
    rows = [agent_packet.packet(t, sectors) for t in trades]
    df = pd.DataFrame(rows)
    for col in ("entry_minute",):
        if col in df:
            df["entry_hour_min"] = df[col].map(lambda s: int(s[:2]) * 60 + int(s[3:5]) if isinstance(s, str) and len(s) >= 5 else float("nan"))
            df = df.drop(columns=[col])
    for col in list(df.columns):
        if df[col].dtype == object or df[col].dtype == bool:
            if col in ("symbol",):
                df = df.drop(columns=[col])
                continue
            nunique = df[col].nunique(dropna=True)
            if nunique > 30:
                df = df.drop(columns=[col])
    df = pd.get_dummies(df, dummy_na=False, dtype=float)
    df = df.astype(float)
    net = [float(t["net_pnl"]) for t in trades]
    win = [x > 0 for x in net]
    good = [(float(t.get("mfe_amount") or 0) >= 3000) for t in trades]
    days = [str(t["entry_time"])[:10] for t in trades]
    return df, win, good, days, net


def auc(scores: Sequence[float], labels: Sequence[bool]) -> float | None:
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return None
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def models():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return {"logistic": lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.1, max_iter=500)),
            "boosted tree": lambda: HistGradientBoostingClassifier(max_depth=3, max_iter=80, learning_rate=0.08, min_samples_leaf=15, random_state=0)}


def walk_forward(df, y: Sequence[bool], days: Sequence[str], make) -> list[float | None]:
    """Out-of-sample probability for every trade after the warm-up: trained on earlier days only."""
    import numpy as np

    scores: list[float | None] = [None] * len(days)
    uniq = sorted(set(days))
    for d in uniq:
        idx_test = [i for i, x in enumerate(days) if x == d]
        idx_train = [i for i, x in enumerate(days) if x < d]
        if len(idx_train) < WARMUP_TRADES or len(set(y[i] for i in idx_train)) < 2:
            continue
        train_df = df.iloc[idx_train]
        cols = [c for c in df.columns if train_df[c].notna().sum() >= 10 and train_df[c].nunique() > 1]          # drop columns that are empty or constant so far
        model = make()
        model.fit(train_df[cols].to_numpy(), np.array([y[i] for i in idx_train]))
        p = model.predict_proba(df.iloc[idx_test][cols].to_numpy())[:, 1]
        for i, v in zip(idx_test, p):
            scores[i] = float(v)
    return scores


def evaluate(scores: Sequence[float | None], y: Sequence[bool], days: Sequence[str], net: Sequence[float]) -> dict[str, Any]:
    idx = [i for i, s in enumerate(scores) if s is not None]
    if len(idx) < 40:
        return {"n": len(idx)}
    s, lab, d, n = [scores[i] for i in idx], [y[i] for i in idx], [days[i] for i in idx], [net[i] for i in idx]
    a = auc(s, lab)
    random.seed(11)
    by_day: dict[str, list[int]] = {}
    for j, day in enumerate(d):
        by_day.setdefault(day, []).append(j)
    shuffled = []
    for _ in range(300):
        sh = list(s)
        for js in by_day.values():
            vals = [s[j] for j in js]
            random.shuffle(vals)
            for j, v in zip(js, vals):
                sh[j] = v
        shuffled.append(auc(sh, lab) or 0.5)
    shuffled.sort()
    out: dict[str, Any] = {"n": len(idx), "auc": a, "auc_chance_95": (shuffled[7], shuffled[292]), "net_all": sum(n), "picks": {}}
    for share in TOP_SHARES:
        pick = []
        for js in by_day.values():
            k = max(1, round(share * len(js)))
            pick += sorted(js, key=lambda j: -s[j])[:k]
        random_nets = []
        for _ in range(300):
            r = []
            for js in by_day.values():
                r += random.sample(js, max(1, round(share * len(js))))
            random_nets.append(sum(n[j] for j in r))
        random_nets.sort()
        out["picks"][share] = {"n": len(pick), "net": sum(n[j] for j in pick), "win_pct": 100 * sum(1 for j in pick if lab[j]) / len(pick), "random_95": (random_nets[7], random_nets[292])}
    return out


def render(results: dict[str, dict[str, dict[str, Any]]], n_trades: int, n_days: int) -> str:
    lines = ["# Baseline: do the entry-time facts hold any signal?", "",
             f"{n_trades} trades over {n_days} days; walk-forward (each day is scored by a model trained on earlier days only), after a {WARMUP_TRADES}-trade warm-up. AUC 0.5 = chance.", ""]
    for target, per_model in results.items():
        lines += [f"## Target: {target}", ""]
        for name, r in per_model.items():
            if r.get("n", 0) < 40:
                lines.append(f"- {name}: not enough out-of-sample trades ({r.get('n', 0)})")
                continue
            lo, hi = r["auc_chance_95"]
            lines.append(f"- **{name}**: {r['n']} out-of-sample trades, AUC {r['auc']:.3f} (chance range {lo:.3f} to {hi:.3f}); all of them made Rs {r['net_all']:,.0f}")
            for share, p in r["picks"].items():
                lines.append(f"    - best {int(share * 100)}% each day: {p['n']} trades, {p['win_pct']:.0f}% win, net Rs {p['net']:,.0f} (a random pick of the same size: Rs {p['random_95'][0]:,.0f} to Rs {p['random_95'][1]:,.0f})")
        lines.append("")
    lines.append("A model only counts if its AUC is clearly above the chance range AND its best picks beat the random range; otherwise the facts show no usable signal on this sample.")
    return "\n".join(lines) + "\n"


def main() -> int:
    sys.path.insert(0, str(ROOT))
    import agent_run

    trades = agent_run.load_trades()
    df, win, good, days, net = frame(trades)
    results: dict[str, dict[str, dict[str, Any]]] = {}
    for target, y in (("net profit (win)", win), ("touched Rs 3,000 of profit", good)):
        results[target] = {}
        for name, make in models().items():
            results[target][name] = evaluate(walk_forward(df, y, days, make), y, days, net)
    text = render(results, len(trades), len(set(days)))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "baseline_report.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
