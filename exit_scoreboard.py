"""One honest exit scoreboard (RESEARCH ONLY - touches no trade). python exit_scoreboard.py [first_day]

Every paper trade whose option was recorded tick by tick (data/option_ticks) is replayed on the SAME price path under each stop policy, so the policies are compared like for like:

    old_rules    the live rules while APLUS_EXIT_LADDER_MODE=SHADOW: initial stop, T1 -> cost, T2 -> +8%, T3 -> runner (+15% floor / 70% of the peak gain). Targets are the trade's own.
    user_ladder  +5% -> -15%, +10% -> +3%, +20% -> +13%, +30% -> +22%, then +2 per +5%
    cost5        the same with the first step at cost
    two_step     +5% -> -15%, +10% -> cost
    ladder2      the 24 Nov 2026 ladder: +10% -> +3%, +20% -> +12%, +30% -> +22%, then +2 per +5% (paper_trade_journal.ladder2_floor)

Rules of the replay (the same for every policy): the entry is the trade's real entry price; the best price (last traded) updates first, then the stop is compared with the same tick, as the journal does;
a stop FILLS at the bid of the tick that crossed it (the price you could have sold at), not at the stop price; a trade still open at 15:25 is closed at that tick's bid; the trade's own recorded
cost is charged to every policy. Fills at the last-traded price are shown as well so the cost of selling into the bid is visible.

Not covered: exits that need the stock's price (burst-over, structure, stall) - those stay in exit_review.py. Writes data/shadow_rules/exit_scoreboard.md and .csv.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import pandas as pd

import paper_trade_journal as pj
from ladder_tick_replay import ticks as load_ticks

ROOT = Path(__file__).resolve().parent
FIRST_DAY = "2026-10-26"
END_HMS = "15:25:00"
POLICIES = ("old_rules", "user_ladder", "cost5", "two_step", "ladder2")
LABELS = {"old_rules": "Old live rules (T1/T2/T3 + runner)", "user_ladder": "Your ladder (+5% -> -15%)", "cost5": "Your ladder, first step at cost",
          "two_step": "Two-step (+5% -15%, +10% cost)", "ladder2": "NEW ladder (+10% +3 / +20% +12 / +30% +22)"}


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def floor_for(policy: str, entry: float, high: float, targets: tuple[float, float, float]) -> float:
    if policy == "user_ladder":
        return pj.user_ladder_floor(entry, high)
    if policy == "cost5":
        return pj.cost5_floor(entry, high)
    if policy == "two_step":
        return pj.two_step_floor(entry, high)
    if policy == "ladder2":
        return pj.ladder2_floor(entry, high)
    # old_rules: what the targets reached so far imply (the targets are the trade's own prices)
    t1, t2, t3 = (t > 0 and high >= t for t in targets)
    f = 0.0
    if t1:
        f = max(f, entry)
    if t2:
        f = max(f, entry * 1.08)
    if t3:
        f = max(f, entry * 1.15, entry + max(0.0, high - entry) * 0.70)
    return f


def replay(trade: dict[str, Any], df: pd.DataFrame, policy: str) -> tuple[float, float, str]:
    """(fill at the bid, fill at the last price, how it ended: stop / end)."""
    entry = _f(trade.get("entry_price"))
    stop0 = _f(trade.get("option_stop")) or entry * 0.8
    targets = (_f(trade.get("option_target1")), _f(trade.get("option_target2")), _f(trade.get("option_target3")))
    since = str(trade["entry_time"])[11:19]
    high = entry
    last_bid, last_ltp = entry, entry
    for hms, p, bid in zip(df.hms, df.ltp, df.bid if "bid" in df else [0.0] * len(df)):
        if hms <= since:
            continue
        if hms > END_HMS:
            break
        b = float(bid) if bid == bid and float(bid) > 0 else float(p)
        high = max(high, float(p))
        last_bid, last_ltp = b, float(p)
        if p <= max(stop0, floor_for(policy, entry, high, targets)):
            return b, float(p), "stop"
    return last_bid, last_ltp, "end"


def load_trades(first_day: str = FIRST_DAY) -> list[dict[str, Any]]:
    import json

    h = json.loads((ROOT / "data" / "reports" / "paper_trade_history.json").read_text(encoding="utf-8"))
    by = {t["paper_trade_id"]: t for t in h.get("paper_trades", h) if t.get("paper_trade_id")}
    try:
        j = json.loads((ROOT / "data" / "intraday_movement" / "paper_trade_journal.json").read_text(encoding="utf-8")).get("trades", [])
        by.update({t["paper_trade_id"]: t for t in j if t.get("paper_trade_id")})
    except (OSError, ValueError):
        pass
    return sorted((t for t in by.values() if str(t.get("status")).upper() == "CLOSED" and str(t.get("entry_time"))[:10] >= first_day and _f(t.get("entry_price")) > 0),
                  key=lambda t: str(t.get("entry_time")))


def build(first_day: str = FIRST_DAY, loader: Callable[[dict], Any] = load_ticks) -> pd.DataFrame:
    rows = []
    for t in load_trades(first_day):
        df = loader(t)
        if df is None or df.empty:
            continue
        entry, qty = _f(t.get("entry_price")), _f(t.get("quantity"))
        cost = _f(t.get("gross_pnl")) - _f(t.get("net_pnl"))
        row = {"day": str(t["entry_time"])[:10], "trade": t["paper_trade_id"], "symbol": t.get("symbol"), "real": _f(t.get("net_pnl"))}
        for pol in POLICIES:
            bid, ltp, how = replay(t, df, pol)
            row[pol] = (bid - entry) * qty - cost
            row[pol + "_ltp"] = (ltp - entry) * qty - cost
            row[pol + "_how"] = how
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(d: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"n": len(d), "days": sorted(d.day.unique()) if len(d) else [], "policies": {}}
    for pol in ("real",) + POLICIES:
        per_day = d.groupby("day")[pol].sum() if len(d) else pd.Series(dtype=float)
        out["policies"][pol] = {"total": float(d[pol].sum()) if len(d) else 0.0, "at_ltp": float(d[pol + "_ltp"].sum()) if pol != "real" and len(d) else None,
                                "days_pos": int((per_day > 0).sum()), "days": int(len(per_day)), "worst_day": float(per_day.min()) if len(per_day) else 0.0,
                                "best_day": float(per_day.max()) if len(per_day) else 0.0, "win": float((d[pol] > 0).mean() * 100) if len(d) else 0.0,
                                "per_day": per_day.to_dict()}
    return out


def render(s: dict[str, Any]) -> str:
    days = s["days"]
    out = ["# Exit scoreboard: every stop policy on the same recorded price path", "",
           f"{s['n']} closed trades with recorded ticks, {len(days)} days ({days[0] if days else '-'} to {days[-1] if days else '-'}). Stops fill at the bid of the tick that crossed them; the trade's own cost is charged; "
           "open at 15:25 closes at the bid. 'Real' is the journal's actual net (live fills, other exit rules included).", "",
           "| Policy | Net Rs (bid fills) | Net Rs (last-price fills) | Selling-into-the-bid cost | Positive days | Worst day | Best day | Win % |", "|---|---|---|---|---|---|---|---|"]
    for pol in ("real",) + POLICIES:
        p = s["policies"][pol]
        label = "Real journal result" if pol == "real" else LABELS[pol]
        ltp = "-" if p["at_ltp"] is None else f"{p['at_ltp']:+,.0f}"
        gap = "-" if p["at_ltp"] is None else f"{p['total'] - p['at_ltp']:+,.0f}"
        out.append(f"| {label} | {p['total']:+,.0f} | {ltp} | {gap} | {p['days_pos']} of {p['days']} | {p['worst_day']:+,.0f} | {p['best_day']:+,.0f} | {p['win']:.0f} |")
    out += ["", "## By day (bid fills)", "", "| Day | " + " | ".join(["Real"] + [LABELS[p].split(" (")[0] for p in POLICIES]) + " |", "|---|" + "---|" * (len(POLICIES) + 1)]
    for day in days:
        out.append(f"| {day} | " + " | ".join(f"{s['policies'][p]['per_day'].get(day, 0):+,.0f}" for p in ("real",) + POLICIES) + " |")
    out += ["", "_All of this is hindsight on paper trades. A policy is only worth switching to when it also wins on days recorded AFTER it was chosen (forward), on more than half the days._", ""]
    return "\n".join(out)


def write(first_day: str = FIRST_DAY, root: Path = ROOT) -> Path:
    d = build(first_day)
    folder = root / "data" / "shadow_rules"
    folder.mkdir(parents=True, exist_ok=True)
    if len(d):
        d.to_csv(folder / "exit_scoreboard.csv", index=False)
    path = folder / "exit_scoreboard.md"
    path.write_text(render(summarize(d)), encoding="utf-8")
    return path


if __name__ == "__main__":
    first = sys.argv[1] if len(sys.argv) > 1 else FIRST_DAY
    print(write(first).read_text(encoding="utf-8"))
