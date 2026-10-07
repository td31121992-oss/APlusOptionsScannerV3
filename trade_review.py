"""End-of-day trade review: one row per paper trade with its high, low, drawdown and what was captured.

    python trade_review.py [--day YYYY-MM-DD]

Writes data/trade_review/<day>/trade_review.md and trade_review.csv. Read-only on trading data.
Open trades are valued at their last real mark (flagged OPEN); nothing is invented.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from trade_costs import round_trip_costs

ROOT = Path(__file__).resolve().parent
OUT_ROOT = ROOT / "data" / "trade_review"
JOURNAL = ROOT / "data" / "intraday_movement" / "paper_trade_journal.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if out == out else default
    except (TypeError, ValueError):
        return default


def _hm(value: Any) -> str:
    text = str(value or "")
    return text[11:16] if len(text) >= 16 else ""


def load_day_trades(day: str, root: Path = ROOT) -> list[dict]:
    journal = root / "data" / "intraday_movement" / "paper_trade_journal.json"
    try:
        data = json.loads(journal.read_text(encoding="utf-8"))
        trades = [t for t in data.get("trades", []) if str(t.get("paper_trade_id", ""))[3:11] == day.replace("-", "")]
        if trades:
            return trades
    except (OSError, ValueError):
        pass
    try:
        from evaluate_rules import load_trades
        return [t for t in load_trades(root) if str(t.get("paper_trade_id", ""))[3:11] == day.replace("-", "")]
    except Exception:
        return []


def review_row(t: dict) -> dict[str, Any]:
    entry, qty = _f(t.get("entry_price")), int(_f(t.get("quantity")))
    closed = str(t.get("status", "")).upper() == "CLOSED"
    exit_price = _f(t.get("exit_price")) if closed else _f(t.get("last_option_price"))
    high = max(_f(t.get("highest_option_price")), entry)
    low = _f(t.get("lowest_option_price"))
    low = min(low, entry) if low > 0 else entry
    gross = (exit_price - entry) * qty if entry > 0 and exit_price > 0 else 0.0
    costs = _f(t.get("estimated_costs")) if closed and _f(t.get("estimated_costs")) > 0 else (
        round_trip_costs(entry, exit_price, qty, _f(t.get("spread_percent")))["total"] if exit_price > 0 else 0.0)
    pct = lambda p: (p / entry - 1) * 100 if entry > 0 else 0.0
    peak_gain = high - entry
    stop = _f(t.get("option_stop"))
    return {
        "symbol": t.get("symbol"), "direction": t.get("direction"), "setup": t.get("setup_family") or "",
        "entry_time": _hm(t.get("entry_time")), "entry_price": entry,
        "high": high, "high_time": _hm(t.get("highest_option_price_at")),
        "low": low, "low_time": _hm(t.get("lowest_option_price_at")),
        "exit_price": exit_price, "exit_time": _hm(t.get("exit_time")) if closed else "",
        "status": "CLOSED" if closed else "OPEN", "exit_reason": t.get("exit_reason") or "",
        "stop_pct": round((1 - stop / entry) * 100, 1) if entry > 0 and stop > 0 else 0.0,
        "mfe_pct": round(pct(high), 1), "mae_pct": round(pct(low), 1), "return_pct": round(pct(exit_price), 1),
        "captured_pct": round((exit_price - entry) / peak_gain * 100) if peak_gain > 0 else 0,
        "capital": round(_f(t.get("capital_deployed"))), "spread_pct": _f(t.get("spread_percent")),
        "gross": round(gross), "costs": round(costs), "net": round(gross - costs),
    }


def summarize(rows: list[dict], key: str) -> list[tuple[str, int, int, int]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[str(r[key])].append(r)
    return [(k, len(v), sum(1 for x in v if x["net"] > 0), sum(x["net"] for x in v))
            for k, v in sorted(groups.items(), key=lambda kv: -sum(x["net"] for x in kv[1]))]


def render(day: str, rows: list[dict]) -> str:
    if not rows:
        return f"# Trade review {day}\n\nNo paper trades.\n"
    net, gross, costs = sum(r["net"] for r in rows), sum(r["gross"] for r in rows), sum(r["costs"] for r in rows)
    wins = sum(1 for r in rows if r["net"] > 0)
    out = [f"# Trade review {day}", "",
           f"{len(rows)} trades ({sum(1 for r in rows if r['status'] == 'OPEN')} still open, valued at last mark) | "
           f"winners {wins} | gross {gross:+,} | costs {costs:,} | **net {net:+,}**", "",
           "| Symbol | Dir | Setup | In | Entry | High (time) | Low (time) | Exit | MFE% | MAE% | Ret% | Kept of peak | Stop% | Capital | Gross | Costs | Net |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        ex = f"{r['exit_price']:.2f} {r['exit_time']} {r['exit_reason']}".strip() if r["status"] == "CLOSED" else f"{r['exit_price']:.2f} OPEN"
        out.append(f"| {r['symbol']} | {str(r['direction'])[:4]} | {r['setup']} | {r['entry_time']} | {r['entry_price']:.2f} | "
                   f"{r['high']:.2f} ({r['high_time'] or '-'}) | {r['low']:.2f} ({r['low_time'] or '-'}) | {ex} | "
                   f"{r['mfe_pct']:+.0f} | {r['mae_pct']:+.0f} | {r['return_pct']:+.0f} | {r['captured_pct']}% | {r['stop_pct']:.0f} | "
                   f"{r['capital']:,} | {r['gross']:+,} | {r['costs']:,} | {r['net']:+,} |")
    for title, key in (("By setup", "setup"), ("By direction", "direction"), ("By entry hour", "hour")):
        data = rows if key != "hour" else [{**r, "hour": (r["entry_time"] or "??")[:2] + ":00"} for r in rows]
        out += ["", f"**{title}**", "", "| Group | Trades | Winners | Net |", "|---|---|---|---|"]
        out += [f"| {k} | {n} | {w} | {v:+,} |" for k, n, w, v in summarize(data, key)]
    gave_back = [r for r in rows if r["mfe_pct"] >= 15 and r["return_pct"] <= 5]
    if gave_back:
        out += ["", "**Gave back a gain** (peak at least +15%, ended at +5% or less): "
                + ", ".join(f"{r['symbol']} (peak {r['mfe_pct']:+.0f}%, ended {r['return_pct']:+.0f}%)" for r in gave_back)]
    deep = [r for r in rows if r["mae_pct"] <= -15]
    if deep:
        out += ["", "**Deep drawdown** (fell 15% or more below entry at some point): "
                + ", ".join(f"{r['symbol']} (low {r['mae_pct']:+.0f}%, ended {r['return_pct']:+.0f}%)" for r in deep)]
    return "\n".join(out) + "\n"


def write(day: str, root: Path = ROOT, out_root: Path | None = None) -> Path | None:
    rows = [review_row(t) for t in load_day_trades(day, root)]
    if not rows:
        return None
    folder = (out_root or root / "data" / "trade_review") / day
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "trade_review.md").write_text(render(day, rows), encoding="utf-8")
    with (folder / "trade_review.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return folder


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", default=date.today().isoformat())
    args = ap.parse_args()
    folder = write(args.day)
    print(f"{args.day}: {'no trades' if folder is None else folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
