"""Trades per day with the best profit each one reached after entry (read-only; no trading effect).

MFE = maximum favourable excursion: the most profit (Rs, for the lot traded) the option showed at any moment after our entry, whatever the trade finally made. Two files, rewritten each night
from paper_trade_history.json (every closed trade since the first one):

    data/trade_archive/daily_mfe.csv / .md     one row per day: trades, how many never went into profit, how many touched Rs 1,000 / 3,000 / 5,000, the best single peak (and which trade),
                                               the average peak, the sum of all peaks, what the day really made, and how much of the peaks was kept
    data/trade_archive/trade_mfe.csv           one row per trade: its peak profit (Rs and % of the entry price), minutes after entry when the peak came, what it finally made, what was given back

    python daily_mfe_report.py
"""

from __future__ import annotations

import csv
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent
THRESHOLDS = (1000, 3000, 5000)
DAY_COLUMNS = ["day", "trades", "never_in_profit", "touched_1k", "touched_3k", "touched_5k", "best_peak_rs", "best_peak_trade", "avg_peak_rs", "sum_peaks_rs", "net_pnl", "kept_pct_of_peaks"]
TRADE_COLUMNS = ["day", "paper_trade_id", "symbol", "side", "entry_time", "entry_price", "quantity", "peak_price", "peak_profit_rs", "peak_pct", "minutes_to_peak", "exit_reason", "net_pnl", "given_back_rs"]


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def trade_row(t: dict[str, Any]) -> dict[str, Any] | None:
    entry, qty, net = _f(t.get("entry_price")), _f(t.get("quantity")), _f(t.get("net_pnl"))
    if not entry or not qty or net is None:
        return None
    high = _f(t.get("highest_option_price")) or entry
    peak = _f(t.get("mfe_amount"))
    peak = max(0.0, (high - entry) * qty) if peak is None else max(0.0, peak)
    try:
        mins = round((datetime.fromisoformat(str(t.get("highest_option_price_at"))) - datetime.fromisoformat(str(t.get("entry_time")))).total_seconds() / 60, 1) if peak > 0 else None
    except ValueError:
        mins = None
    return {"day": str(t.get("entry_time") or "")[:10], "paper_trade_id": t.get("paper_trade_id"), "symbol": t.get("symbol"), "side": str(t.get("option_type") or "").upper(),
            "entry_time": str(t.get("entry_time") or "")[:19], "entry_price": entry, "quantity": qty, "peak_price": round(high, 4), "peak_profit_rs": round(peak, 2),
            "peak_pct": round((high / entry - 1) * 100, 2), "minutes_to_peak": mins, "exit_reason": t.get("exit_reason") or "", "net_pnl": round(net, 2),
            "given_back_rs": round(peak - net, 2)}


def day_rows(trades: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in trades:
        by[r["day"]].append(r)
    out = []
    for day in sorted(by):
        rows = by[day]
        peaks = [r["peak_profit_rs"] for r in rows]
        best = max(rows, key=lambda r: r["peak_profit_rs"])
        net, total_peak = sum(r["net_pnl"] for r in rows), sum(peaks)
        out.append({"day": day, "trades": len(rows), "never_in_profit": sum(1 for p in peaks if p <= 0), "touched_1k": sum(1 for p in peaks if p >= 1000),
                    "touched_3k": sum(1 for p in peaks if p >= 3000), "touched_5k": sum(1 for p in peaks if p >= 5000), "best_peak_rs": round(best["peak_profit_rs"]),
                    "best_peak_trade": f"{best['symbol']} {best['side']}", "avg_peak_rs": round(st.mean(peaks)), "sum_peaks_rs": round(total_peak), "net_pnl": round(net),
                    "kept_pct_of_peaks": round(100 * net / total_peak) if total_peak > 0 else None})
    return out


def render(days: Sequence[dict[str, Any]], trades: Sequence[dict[str, Any]]) -> str:
    n, peak, net = sum(d["trades"] for d in days), sum(d["sum_peaks_rs"] for d in days), sum(d["net_pnl"] for d in days)
    lines = ["# Trades per day and the best profit each reached after entry", "",
             f"{n} closed trades over {len(days)} sessions: peaks add up to Rs {peak:,.0f}, the trades really made Rs {net:,.0f}. Peak (MFE) = the most profit for the lot at any moment after entry.", "",
             "| Day | Trades | Never in profit | Touched 1k | 3k | 5k | Best peak Rs | Best trade | Avg peak Rs | Sum of peaks Rs | Day net Rs |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in days:
        lines.append(f"| {d['day']} | {d['trades']} | {d['never_in_profit']} | {d['touched_1k']} | {d['touched_3k']} | {d['touched_5k']} | {d['best_peak_rs']:,} | {d['best_peak_trade']} | {d['avg_peak_rs']:,} | {d['sum_peaks_rs']:,} | {d['net_pnl']:,} |")
    lines += ["", "The per-trade list is in trade_mfe.csv."]
    return "\n".join(lines) + "\n"


def run(history: Sequence[dict[str, Any]] | None = None, root: Path = ROOT, out: Path | None = None) -> list[dict[str, Any]]:
    out = out or root / "data" / "trade_archive"
    if history is None:
        import trade_archive

        history = trade_archive.load_history(root / "data" / "reports" / "paper_trade_history.json")
    trades = [r for t in history if str(t.get("status")).upper() == "CLOSED" and (r := trade_row(t))]
    trades.sort(key=lambda r: r["entry_time"])
    days = day_rows(trades)
    out.mkdir(parents=True, exist_ok=True)
    for name, cols, rows in (("daily_mfe.csv", DAY_COLUMNS, days), ("trade_mfe.csv", TRADE_COLUMNS, trades)):
        with (out / name).open("w", encoding="utf-8", newline="") as h:
            w = csv.DictWriter(h, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    (out / "daily_mfe.md").write_text(render(days, trades), encoding="utf-8")
    return days


def main() -> int:
    days = run()
    print(f"{len(days)} sessions -> data/trade_archive/daily_mfe.md, daily_mfe.csv, trade_mfe.csv")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
