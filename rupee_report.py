"""Profit in rupees after entry, per paper trade (DISPLAY / REPORT ONLY: reads the journal, changes nothing).

Percent returns hide what matters when sizes differ. For every paper trade this shows, in rupees:

    peak ₹     the best profit the position ever showed after entry: (highest option price - entry price) x quantity, and when that was (highest_option_price_at)
    final ₹    what it really made: net P&L for a closed trade (costs in), the open profit for an open one
    gave back  peak minus final: profit the position showed and then lost
    worst ₹    the deepest drawdown after entry, in rupees

and over all trades: how often a trade ever showed +₹500 / 1,000 / 2,000 / 3,000 / 5,000, how much of what the entries offered was kept, and a RUPEE-TARGET table: if every closed trade had been sold in full the moment it showed +₹T (when its peak reached T; otherwise as it really ended), what the total would have been.
That table is feasible by construction: a trade whose peak reached T was still alive when it did, so the target was reached before any exit, and costs of the real trade are taken off. It ignores slippage on the way out.

    data/reports/rupee_report/<day>.md / .csv      the nightly report (from the 15:50 chain)
    /rupees                                       the live page (today's trades update as the journal does)
"""

from __future__ import annotations

import csv
import json
import statistics as st
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent
THRESHOLDS = (500, 1000, 2000, 3000, 5000)
TARGETS = (500, 1000, 1500, 2000, 3000)
HISTORY = ("data", "reports", "paper_trade_history.json")
JOURNAL = ("data", "intraday_movement", "paper_trade_journal.json")
FIELDS = ["day", "entry_time", "symbol", "side", "status", "exit_reason", "entry", "peak", "now_or_exit", "qty", "capital", "peak_rs", "minutes_to_peak", "worst_rs", "final_rs", "gave_back"]


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def load_trades(root: Path) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for rel, key in ((HISTORY, "paper_trades"), (JOURNAL, "trades")):
        try:
            for t in json.loads(root.joinpath(*rel).read_text(encoding="utf-8")).get(key) or []:
                seen[str(t.get("paper_trade_id") or id(t))] = t
        except (OSError, ValueError):
            continue
    return list(seen.values())


def _minutes(a: Any, b: Any) -> float | None:
    try:
        return round((datetime.fromisoformat(str(b)) - datetime.fromisoformat(str(a))).total_seconds() / 60.0, 1)
    except (TypeError, ValueError):
        return None


def trade_row(t: Mapping[str, Any]) -> dict[str, Any] | None:
    entry, peak, qty = _f(t.get("entry_price")), _f(t.get("highest_option_price")), _f(t.get("quantity"))
    if not entry or peak is None or not qty or qty <= 0:
        return None
    closed = str(t.get("status") or "").upper() == "CLOSED"
    final = _f(t.get("net_pnl")) if closed else _f(t.get("unrealized_pnl"))
    if final is None:
        return None
    low = _f(t.get("lowest_option_price"))
    peak_rs = (peak - entry) * qty
    now = _f(t.get("exit_price")) if closed else _f(t.get("last_option_price"))
    return {"day": str(t.get("entry_time") or "")[:10], "entry_time": str(t.get("entry_time") or ""), "symbol": str(t.get("symbol") or ""), "side": "PUT" if str(t.get("direction")).upper() == "BEARISH" else "CALL",
            "status": "CLOSED" if closed else "OPEN", "exit_reason": str(t.get("exit_reason") or ""), "entry": entry, "peak": peak, "now_or_exit": now, "qty": int(qty), "capital": round(entry * qty),
            "peak_rs": round(peak_rs), "minutes_to_peak": _minutes(t.get("entry_time"), t.get("highest_option_price_at")), "worst_rs": None if low is None else round((low - entry) * qty),
            "final_rs": round(final), "gave_back": round(peak_rs - final), "_costs": _f(t.get("estimated_costs")) or 0.0}


def rows_of(root: Path) -> list[dict[str, Any]]:
    out = [r for r in (trade_row(t) for t in load_trades(root)) if r]
    return sorted(out, key=lambda r: r["entry_time"])


def target_table(closed: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    closed = list(closed)
    actual = sum(r["final_rs"] for r in closed)
    out = [{"target": 0, "total": round(actual), "hit": 0, "label": "as it really ended"}]
    for T in TARGETS:
        total, hit = 0.0, 0
        for r in closed:
            if r["peak_rs"] >= T:
                total += T - r["_costs"]
                hit += 1
            else:
                total += r["final_rs"]
        out.append({"target": T, "total": round(total), "hit": hit, "label": f"sell everything at +₹{T:,}"})
    return out


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    closed = [r for r in rows if r["status"] == "CLOSED"]
    peaks = [r["peak_rs"] for r in rows]
    offered = sum(max(r["peak_rs"], 0) for r in closed)
    gave = [r for r in closed if r["peak_rs"] > 0]
    s: dict[str, Any] = {"n": len(rows), "closed": len(closed), "days": len({r["day"] for r in rows}), "median_capital": round(st.median(r["capital"] for r in rows)), "peak_median": round(st.median(peaks)),
                         "peak_mean": round(st.mean(peaks)), "peak_p90": round(sorted(peaks)[int(0.9 * (len(peaks) - 1))]), "reached": {str(t): round(100.0 * sum(1 for p in peaks if p >= t) / len(peaks)) for t in THRESHOLDS}}
    if closed:
        s.update(banked_total=round(sum(r["final_rs"] for r in closed)), banked_median=round(st.median(r["final_rs"] for r in closed)), banked_mean=round(st.mean(r["final_rs"] for r in closed)), offered_total=round(offered),
                 in_profit_pct=round(100.0 * len(gave) / len(closed)), lost_anyway_pct=round(100.0 * sum(1 for r in gave if r["final_rs"] < 0) / len(gave)) if gave else 0,
                 gave_back_median=round(st.median(r["gave_back"] for r in gave)) if gave else 0, targets=target_table(closed))
    worst = [r["worst_rs"] for r in rows if r["worst_rs"] is not None]
    if worst:
        s["worst_median"] = round(st.median(worst))
    return s


def payload(root: Path = ROOT, today: date | None = None) -> dict[str, Any]:
    day = (today or date.today()).isoformat()
    rows = rows_of(root)
    t = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows if r["day"] == day]
    per_day = []
    for d in sorted({r["day"] for r in rows})[-12:]:
        g = [r for r in rows if r["day"] == d]
        per_day.append({"day": d, "n": len(g), "peaks": round(sum(max(r["peak_rs"], 0) for r in g)), "final": round(sum(r["final_rs"] for r in g))})
    return {"ok": True, "day": day, "today": t, "today_summary": {"peaks": round(sum(max(r["peak_rs"], 0) for r in t)), "final": round(sum(r["final_rs"] for r in t)), "n": len(t)},
            "all": summary(rows), "recent": summary([r for r in rows if r["day"] >= (sorted({r["day"] for r in rows})[-10] if len({r["day"] for r in rows}) >= 10 else "0")]), "per_day": per_day}


def render(day: str, rows: list[dict[str, Any]]) -> str:
    a = summary(rows)
    L = [f"# Profit in rupees after entry, up to {day}", ""]
    if not a["n"]:
        return "\n".join(L + ["No trades with prices yet.", ""])
    L += [f"{a['n']} paper trades over {a['days']} days; typical capital per trade ₹{a['median_capital']:,}.", "",
          f"- Best profit each trade ever showed: median ₹{a['peak_median']:,}, mean ₹{a['peak_mean']:,}, 90th percentile ₹{a['peak_p90']:,}. Reached +₹500: {a['reached']['500']}%, +₹1,000: {a['reached']['1000']}%, "
          f"+₹2,000: {a['reached']['2000']}%, +₹3,000: {a['reached']['3000']}%, +₹5,000: {a['reached']['5000']}%."]
    if a.get("closed"):
        L += [f"- Closed trades banked ₹{a['banked_total']:,} in total (median ₹{a['banked_median']:,} a trade) against ₹{a['offered_total']:,} that the entries showed at their peaks.",
              f"- {a['in_profit_pct']}% of closed trades were in profit at some point; {a['lost_anyway_pct']}% of those closed in a loss anyway; median given back from the peak ₹{a['gave_back_median']:,}.", "",
              "## If every closed trade had been sold in full when it showed +₹T", "", "| Rule | Total ₹ | Trades that reached the target |", "|---|---|---|"]
        L += [f"| {t['label']} | {t['total']:,} | {t['hit'] if t['target'] else '-'} |" for t in a["targets"]]
    today = [r for r in rows if r["day"] == day]
    if today:
        L += ["", f"## {day}, per trade", "", "| Time | Stock | Side | Entry | Peak | Now / exit | Qty | Peak ₹ | Final ₹ | Gave back ₹ | Status |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in today:
            now = "-" if r["now_or_exit"] is None else f"{r['now_or_exit']:.2f}"
            L.append(f"| {r['entry_time'][11:16]} | {r['symbol']} | {r['side']} | {r['entry']:.2f} | {r['peak']:.2f} | {now} | {r['qty']} | {r['peak_rs']:,} | {r['final_rs']:,} | {r['gave_back']:,} | {r['status']} |")
    return "\n".join(L) + "\n"


def run(day: str, root: Path = ROOT) -> None:
    rows = rows_of(root)
    folder = root / "data" / "reports" / "rupee_report"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{day}.md").write_text(render(day, rows), encoding="utf-8")
    with (folder / f"{day}.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    day = date.today().isoformat()
    run(day)
    print((ROOT / "data" / "reports" / "rupee_report" / f"{day}.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
