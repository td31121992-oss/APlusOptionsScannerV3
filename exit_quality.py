"""Was the exit good? What the option did AFTER every exit (read-only; no trading effect).

For every closed paper trade that has recorded option ticks after its exit (data/option_ticks, from 26 Oct 2026; earlier contracts have expired and have no data), the option's price path after
the exit is measured against the exit price:

    after the exit            price 5 / 15 / 30 / 60 minutes later, the highest and lowest price until the close, the price at the close, and when the peak came
    in rupees (for the lot)   what holding to the close would have added or cost, what selling at the day's top would have added (the best case), what the exit avoided (lowest price)
    verdict                   WENT_UP    the option closed the day more than 3% above our exit price  (the exit was early)
                              WENT_DOWN  it closed more than 3% below the exit price               (the exit was good: selling later would have cost money)
                              FLAT       within 3%
    whipsaw                   a stop-loss exit after which the option climbed back to our entry price or higher (we were stopped out right before it recovered)

Hindsight only: nobody can sell at the top, and a verdict says what happened next, not what the exit should have been.

    data/trade_archive/exit_quality.csv    one row per trade
    data/trade_archive/exit_quality.md     the summary, by exit reason, with the worst and best exits

    python exit_quality.py
"""

from __future__ import annotations

import csv
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
BAND = 3.0                                                   # percent of the exit price that counts as "went up / went down"
COLUMNS = ["paper_trade_id", "day", "symbol", "side", "entry_time", "exit_time", "exit_reason", "entry_price", "exit_price", "quantity", "net_pnl", "peak_during_hold_rs",
           "after_5m_pct", "after_15m_pct", "after_30m_pct", "after_60m_pct", "after_close_pct", "after_high_pct", "minutes_to_after_high", "after_low_pct",
           "hold_to_close_rs", "best_case_rs", "avoided_rs", "whipsaw", "verdict", "story"]


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _secs(stamp: Any) -> float | None:
    from datetime import datetime

    try:
        t = datetime.fromisoformat(str(stamp))
        return t.hour * 3600 + t.minute * 60 + t.second
    except ValueError:
        return None


def analyse(trade: Mapping[str, Any], ticks: Sequence[tuple[float, float, float]]) -> dict[str, Any] | None:
    """The row for one trade; None when there are not enough ticks after the exit."""
    entry, exit_px, qty = _f(trade.get("entry_price")), _f(trade.get("exit_price")), _f(trade.get("quantity"))
    te = _secs(trade.get("exit_time"))
    if not entry or not exit_px or not qty or te is None or str(trade.get("exit_time"))[:10] != str(trade.get("entry_time"))[:10]:
        return None
    after = [(s, p) for s, p, _ in ticks if s > te and p > 0]
    if len(after) < 3:
        return None
    pct = lambda p: round((p / exit_px - 1) * 100, 2)                                                   # noqa: E731

    def at(minutes: int) -> float | None:
        target = te + minutes * 60
        if after[-1][0] < target:
            return None
        before = [p for s, p in after if s <= target]
        return pct(before[-1]) if before else None

    high_t, high = max(after, key=lambda x: x[1])
    low = min(p for _, p in after)
    close = after[-1][1]
    close_pct = pct(close)
    reason = str(trade.get("exit_reason") or "")
    whipsaw = bool("STOP" in reason and high >= entry)
    verdict = "WENT_UP" if close_pct > BAND else ("WENT_DOWN" if close_pct < -BAND else "FLAT")
    row = {"paper_trade_id": trade.get("paper_trade_id"), "day": str(trade.get("entry_time"))[:10], "symbol": trade.get("symbol"), "side": str(trade.get("option_type") or "").upper(),
           "entry_time": str(trade.get("entry_time"))[:19], "exit_time": str(trade.get("exit_time"))[:19], "exit_reason": reason, "entry_price": entry, "exit_price": exit_px,
           "quantity": qty, "net_pnl": _f(trade.get("net_pnl")), "peak_during_hold_rs": _f(trade.get("mfe_amount")),
           "after_5m_pct": at(5), "after_15m_pct": at(15), "after_30m_pct": at(30), "after_60m_pct": at(60), "after_close_pct": close_pct, "after_high_pct": pct(high),
           "minutes_to_after_high": round((high_t - te) / 60, 1), "after_low_pct": pct(low), "hold_to_close_rs": round((close - exit_px) * qty), "best_case_rs": round((high - exit_px) * qty),
           "avoided_rs": round((exit_px - low) * qty), "whipsaw": whipsaw, "verdict": verdict}
    hh, mm = int(high_t // 3600), int(high_t % 3600 // 60)
    row["story"] = (f"{reason or 'exit'} at {exit_px:g}; the option then peaked at {high:g} ({row['after_high_pct']:+.1f}%) at {hh:02d}:{mm:02d} and closed the day at {close:g} ({close_pct:+.1f}%). "
                    f"Holding to the close: Rs {row['hold_to_close_rs']:+,}; best case Rs {row['best_case_rs']:+,}" + ("; STOPPED OUT, THEN RECOVERED to the entry price or higher" if whipsaw else ""))
    return row


def summary(rows: Sequence[Mapping[str, Any]], total_closed: int) -> str:
    n = len(rows)
    net = sum(r["net_pnl"] or 0 for r in rows)
    held = sum(r["hold_to_close_rs"] for r in rows)
    v = {k: sum(1 for r in rows if r["verdict"] == k) for k in ("WENT_UP", "WENT_DOWN", "FLAT")}
    lines = ["# Was the exit good? What the option did after every exit", "",
             f"{n} of {total_closed} closed trades have option data after the exit (26 Oct onwards; earlier contracts have expired and have no data).", "",
             f"- After our exit the option **went up** (closed the day 3%+ above the exit price) on **{v['WENT_UP']}** trades ({100 * v['WENT_UP'] / n:.0f}%), **went down** on **{v['WENT_DOWN']}** "
             f"({100 * v['WENT_DOWN'] / n:.0f}%), stayed flat on {v['FLAT']}.",
             f"- These trades really made Rs {net:,.0f}. Had every one been held to the close it would have been Rs {net + held:,.0f} ({held:+,.0f}); this is hindsight, not a rule.",
             f"- {sum(1 for r in rows if r['whipsaw'])} stop-loss exits were followed by a recovery to the entry price or higher.", "", "## By exit reason", "",
             "| Exit reason | Trades | Went up | Went down | Avg close after exit % | Avg peak after exit % | Hold-to-close would add Rs | Real net Rs |", "|---|---|---|---|---|---|---|---|"]
    by: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        by[r["exit_reason"] or "-"].append(r)
    for k, v_ in sorted(by.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"| {k} | {len(v_)} | {sum(1 for r in v_ if r['verdict'] == 'WENT_UP')} | {sum(1 for r in v_ if r['verdict'] == 'WENT_DOWN')} | "
                     f"{st.mean(r['after_close_pct'] for r in v_):+.1f} | {st.mean(r['after_high_pct'] for r in v_):+.1f} | {sum(r['hold_to_close_rs'] for r in v_):+,} | {sum(r['net_pnl'] or 0 for r in v_):,.0f} |")
    for title, key, rev, extra in (("Exits that cost the most (the option kept rising)", "hold_to_close_rs", True, ""), ("Exits that saved the most (the option kept falling)", "hold_to_close_rs", False, "")):
        lines += ["", f"## {title}", ""]
        for r in sorted(rows, key=lambda x: x[key], reverse=rev)[:12]:
            lines.append(f"- {r['day']} **{r['symbol']} {r['side']}** - {r['story']}")
    wh = [r for r in rows if r["whipsaw"]]
    lines += ["", f"## Stopped out, then recovered ({len(wh)} trades)", ""] + [f"- {r['day']} **{r['symbol']} {r['side']}** - {r['story']}" for r in sorted(wh, key=lambda x: -x["best_case_rs"])[:12]]
    lines += ["", "Every trade's line is in exit_quality.csv. Hindsight only: nobody can sell at the top."]
    return "\n".join(lines) + "\n"


def run(history: Sequence[dict[str, Any]] | None = None, root: Path = ROOT, out: Path | None = None) -> list[dict[str, Any]]:
    out = out or root / "data" / "trade_archive"
    if history is None:
        import trade_archive

        history = trade_archive.load_history(root / "data" / "reports" / "paper_trade_history.json")
    from entry_filter_replay import load_ticks

    closed = [t for t in history if str(t.get("status")).upper() == "CLOSED" and _f(t.get("net_pnl")) is not None]
    rows = []
    for t in sorted(closed, key=lambda x: str(x.get("entry_time"))):
        ticks = load_ticks(str(t.get("option_security_id")), str(t.get("entry_time"))[:10], root)
        r = analyse(t, ticks) if ticks else None
        if r:
            rows.append(r)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "exit_quality.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    if rows:
        (out / "exit_quality.md").write_text(summary(rows, len(closed)), encoding="utf-8")
    return rows


def main() -> int:
    rows = run()
    print(f"{len(rows)} trades analysed -> data/trade_archive/exit_quality.md and exit_quality.csv")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
