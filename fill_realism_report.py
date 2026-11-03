"""Fill realism report (read-only): what real option bid/ask would have cost the paper trades.

For every closed trade that carries a real exit quote (recorded from 23 Oct on) it compares the journal's P&L (sold at the last traded price less an estimated impact)
with the P&L had the sell hit the bid, and shows the entry cost (paper entry vs last price), spreads, and how often the displayed bid could not cover the whole quantity.

    python fill_realism_report.py [--days N]        writes data/reports/fill_realism.csv and prints a summary
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / "data" / "reports" / "paper_trade_history.json"
COLUMNS = ["day", "symbol", "side", "entry_price", "entry_slip_pct", "entry_spread_pct", "exit_price", "exit_bid", "exit_spread_pct", "exit_bid_qty", "quantity",
           "exit_bid_covers_qty", "exit_slip_amount", "exit_reason", "net_pnl", "net_pnl_at_bid"]


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def load(path: Path = HISTORY) -> list[dict[str, Any]]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = d.get("paper_trades") if isinstance(d, Mapping) else d
    return [r for r in rows or [] if isinstance(r, Mapping)]


def summarise(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    closed = [t for t in trades if str(t.get("status")).upper() == "CLOSED"]
    quoted = [t for t in closed if _f(t.get("exit_bid"))]
    out: dict[str, Any] = {"closed": len(closed), "with_exit_quote": len(quoted)}
    if not quoted:
        return out
    pnl = sum(_f(t.get("net_pnl")) or 0.0 for t in quoted)
    at_bid = sum(_f(t.get("net_pnl_at_bid")) or 0.0 for t in quoted)

    def mean(key: str) -> float | None:
        v = [x for x in (_f(t.get(key)) for t in quoted) if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    covered = [t for t in quoted if str(t.get("exit_bid_covers_qty")) in ("0", "1")]
    out.update({"net_pnl": round(pnl, 0), "net_pnl_at_bid": round(at_bid, 0), "difference": round(at_bid - pnl, 0), "avg_entry_slip_pct": mean("entry_slip_pct"),
                "avg_entry_spread_pct": mean("entry_spread_pct"), "avg_exit_spread_pct": mean("exit_spread_pct"),
                "bid_too_thin_pct": round(100.0 * sum(1 for t in covered if str(t.get("exit_bid_covers_qty")) == "0") / len(covered), 1) if covered else None})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()
    trades = load()
    s = summarise(trades)
    print(json.dumps(s, indent=1))
    quoted = [t for t in trades if _f(t.get("exit_bid"))]
    if quoted:
        out = ROOT / "data" / "reports" / "fill_realism.csv"
        with out.open("w", newline="", encoding="utf-8") as h:
            w = csv.DictWriter(h, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            for t in quoted:
                w.writerow({**t, "day": str(t.get("entry_time") or "")[:10], "side": t.get("direction", "")})
        print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
