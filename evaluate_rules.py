"""What-if evaluator: re-score historical PAPER trades under candidate rules.

Loads every recorded trade (history CSV, per-trade evidence capsules, end-of-day
CSVs), de-duplicates by trade id, keeps CLOSED trades that used realistic fills
(on/after --since, not a rounded-up entry), applies the cost model, then reports
each rule set: trades kept, win rate, net P&L after costs, profit factor, max
drawdown, and a bootstrap probability that the net is positive.

Read-only. Usage:  python evaluate_rules.py [--since 2026-08-28] [--resamples 2000]

Rules are plain predicates on a trade dict - add your own in RULESETS.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import random
from datetime import datetime, time as clock_time
from pathlib import Path
from typing import Callable, Iterable

from trade_costs import round_trip_costs

ROOT = Path(__file__).resolve().parent


def _f(value, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if out == out else default
    except (TypeError, ValueError):
        return default


def load_trades(root: Path = ROOT) -> list[dict]:
    """Unique trades by id; a CLOSED record beats an OPEN one."""
    rows: dict[str, dict] = {}

    def put(rec: dict, src: str) -> None:
        tid = rec.get("paper_trade_id")
        if not tid:
            return
        cur = rows.get(tid)
        if cur is None or (str(cur.get("status")).upper() != "CLOSED" and str(rec.get("status")).upper() == "CLOSED"):
            rows[tid] = {**rec, "_src": src}

    hist = root / "data" / "reports" / "paper_trade_history.csv"
    if hist.exists():
        for r in csv.DictReader(hist.open(encoding="utf-8-sig")):
            put(r, "history")
    for f in sorted(glob.glob(str(root / "data" / "trade_evidence_capsules" / "*" / "*.json"))):
        try:
            j = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tr = dict(j.get("trade_record") or {})
        for k in ("status", "exit_time", "exit_reason", "entry_time", "setup_family"):
            if j.get(k) not in (None, ""):
                tr.setdefault(k, j[k])
        if "net_pnl" not in tr and j.get("pnl") is not None:
            tr["net_pnl"] = j["pnl"]
        tr.setdefault("paper_trade_id", j.get("trade_id"))
        put(tr, "capsule")
    for f in glob.glob(str(root / "data" / "after_market" / "*" / "paper_trades.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            put(r, "after_market")
    return list(rows.values())


def prepare(trades: Iterable[dict], since: str = "2026-08-28") -> list[dict]:
    """Closed, realistic-fill trades with cost-adjusted P&L ('net_after_costs')."""
    out = []
    for t in trades:
        if str(t.get("status", "")).upper() != "CLOSED":
            continue
        tid = str(t.get("paper_trade_id", ""))
        try:
            day = datetime.strptime(tid[3:11], "%Y%m%d").date().isoformat()
        except ValueError:
            continue
        if day < since:
            continue
        entry, ask = _f(t.get("entry_price")), _f(t.get("ask"))
        if entry > 0 and entry % 5 == 0 and entry > ask + 0.005:      # rounded-up fake fill era
            continue
        qty = int(_f(t.get("quantity")))
        exit_price = _f(t.get("exit_price"))
        gross = _f(t.get("gross_pnl"), (exit_price - entry) * qty)
        costs = _f(t.get("estimated_costs"))
        if costs <= 0:
            costs = round_trip_costs(entry, exit_price, qty, _f(t.get("spread_percent")))["total"]
        et = str(t.get("entry_time") or "")[:19]
        try:
            entry_clock = datetime.fromisoformat(et).time()
        except ValueError:
            entry_clock = clock_time(0, 0)
        out.append({**t, "_day": day, "_gross": gross, "_costs": costs, "_net": gross - costs,
                    "_entry_clock": entry_clock, "_spread": _f(t.get("spread_percent")), "_entry": entry})
    return sorted(out, key=lambda x: str(x.get("entry_time") or ""))


def metrics(trades: list[dict], resamples: int = 2000, seed: int = 7) -> dict:
    nets = [t["_net"] for t in trades]
    if not nets:
        return {"n": 0, "win%": 0.0, "net": 0.0, "PF": 0.0, "maxDD": 0.0, "P(net>0)": 0.0}
    wins = sum(x for x in nets if x > 0)
    losses = -sum(x for x in nets if x < 0)
    peak = cum = dd = 0.0
    for x in nets:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    rng = random.Random(seed)
    positive = sum(1 for _ in range(resamples) if sum(rng.choices(nets, k=len(nets))) > 0)
    return {
        "n": len(nets), "win%": round(100 * sum(1 for x in nets if x > 0) / len(nets), 1),
        "net": round(sum(nets)), "PF": round(wins / losses, 2) if losses > 0 else float("inf"),
        "maxDD": round(dd), "P(net>0)": round(positive / resamples, 2),
    }


Rule = Callable[[dict], bool]
RULESETS: dict[str, Rule] = {
    "baseline (all valid trades)": lambda t: True,
    "entries before 13:00": lambda t: t["_entry_clock"] <= clock_time(13, 0),
    "spread <= 2.0%": lambda t: t["_spread"] <= 2.0,
    "before 13:00 AND spread <= 2.0%": lambda t: t["_entry_clock"] <= clock_time(13, 0) and t["_spread"] <= 2.0,
    "before 12:00 AND spread <= 2.0%": lambda t: t["_entry_clock"] <= clock_time(12, 0) and t["_spread"] <= 2.0,
    "before 13:00 AND spread <= 2.0% AND premium >= 5": lambda t: t["_entry_clock"] <= clock_time(13, 0) and t["_spread"] <= 2.0 and t["_entry"] >= 5,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-08-28")
    ap.add_argument("--resamples", type=int, default=2000)
    args = ap.parse_args()
    trades = prepare(load_trades(), args.since)
    print(f"{len(trades)} valid closed trades since {args.since}; costs included "
          f"(total costs Rs{sum(t['_costs'] for t in trades):,.0f}, gross Rs{sum(t['_gross'] for t in trades):,.0f})\n")
    print(f"{'rule set':52s} {'n':>4s} {'win%':>6s} {'net':>9s} {'PF':>5s} {'maxDD':>8s} {'P(net>0)':>9s}")
    for name, rule in RULESETS.items():
        m = metrics([t for t in trades if rule(t)], args.resamples)
        print(f"{name:52s} {m['n']:4d} {m['win%']:6.1f} {m['net']:9,d} {m['PF']:5.2f} {m['maxDD']:8,d} {m['P(net>0)']:9.2f}")
    print("\nP(net>0) = share of bootstrap resamples with positive net. Treat anything below ~0.9 as 'not proven'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
