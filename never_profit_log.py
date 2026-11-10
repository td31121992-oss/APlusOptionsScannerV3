"""Record of the trades that NEVER went into profit after entry, with a short post-mortem of what happened next (read-only; no trading effect).

"Never in profit" = the option's highest price after entry was not above the entry price (mfe_amount <= 0), for every closed paper trade since the first one (22 Sep 2026).
For each such trade one row is kept in data/trade_archive/never_profit.csv (rewritten each night, so a trade is never lost or duplicated) and the story is written to never_profit.md:

    when and how it ended           entry / exit time, exit reason, minutes held, stop distance, worst price and minutes to it
    what the stock did after entry  % move in OUR direction at +5 and +15 minutes, at the exit, the worst point while held, and the move in the 2 minutes BEFORE entry
    what we knew at entry           spread, setup, time of day, minutes since the first signal, sector pick at 09:45
    hints                           rule-based labels for what most likely went wrong (see HINTS), and a one-line diagnosis

The hints are a starting point for review, not proof: several can apply to the same trade.

    python never_profit_log.py
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "trade_archive"
HINTS = {
    "SPREAD_WIDE": "option bid-ask spread at entry was over 1%",
    "EARLY_ENTRY": "entered before 09:45",
    "CHASED": "the stock had already moved our way (0.10%+ in the 2 minutes before entry) or it was entered within 10 minutes of the first signal",
    "NO_FOLLOWTHROUGH": "the stock was not moving our way 5 minutes after entry",
    "STOCK_AGAINST": "the stock moved 0.30% or more against us while the trade was open",
    "QUICK_STOP": "stopped out within 15 minutes",
    "SLOW_BLEED": "held 60+ minutes with the stock flat: time decay, not a stock move",
    "OUTSIDE_SECTOR_PICKS": "not in the 09:45 top-2 gaining / losing sector picks",
}
COLUMNS = ["paper_trade_id", "day", "symbol", "side", "setup_family", "sector", "entry_time", "entry_price", "quantity", "spread_pct", "entry_minute", "lag_min_since_first_signal",
           "exit_time", "exit_reason", "minutes_held", "exit_price", "net_pnl", "stop_distance_pct", "lowest_option_price", "minutes_to_low",
           "stock_pre2m_pct", "stock_5m_pct", "stock_15m_pct", "stock_at_exit_pct", "stock_worst_pct", "hints", "diagnosis"]


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _dt(v: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def _secs(t: datetime) -> float:
    return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1e6


def stock_path(symbol: str, day: str, root: Path = ROOT) -> list[tuple[float, float]]:
    """[(seconds since midnight, stock price)]: the recorded ticks when there are any, else the stored 5-minute candles (price at the end of each bar)."""
    out: list[tuple[float, float]] = []
    p = root / "data" / "ticks" / day / f"{symbol}.csv.gz"
    if p.exists():
        try:
            with gzip.open(p, "rt", encoding="utf-8", newline="") as h:
                for row in csv.DictReader(h):
                    try:
                        hh, mm, ss = row["ts"].split(":")
                        out.append((int(hh) * 3600 + int(mm) * 60 + float(ss), float(row["ltp"])))
                    except (ValueError, KeyError):
                        continue
        except (EOFError, OSError):
            pass
        if out:
            return sorted(out)
    try:
        d = json.loads((root / "data" / "pattern_log" / "candles" / f"{day}.json").read_text(encoding="utf-8")).get("symbols", {}).get(symbol)
    except (OSError, ValueError):
        d = None
    if d:
        out = [(m * 60 + 300.0, float(c)) for m, c in zip(d.get("minute") or [], d.get("close") or [])]
    return sorted(out)


def never_in_profit(t: Mapping[str, Any]) -> bool:
    mfe, entry, high = _f(t.get("mfe_amount")), _f(t.get("entry_price")), _f(t.get("highest_option_price"))
    return (mfe is not None and mfe <= 0) or (high is not None and entry is not None and high <= entry)


def post_mortem(t: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """The row for one trade (see COLUMNS)."""
    sym, day = str(t.get("symbol") or ""), str(t.get("entry_time") or "")[:10]
    side = str(t.get("option_type") or "").upper()
    sign = 1.0 if side == "CE" else -1.0
    t0, t1 = _dt(t.get("entry_time")), _dt(t.get("exit_time"))
    entry, stop = _f(t.get("entry_price")), _f(t.get("option_stop"))
    held = round((t1 - t0).total_seconds() / 60, 1) if t0 and t1 else None
    low_at = _dt(t.get("lowest_option_price_at"))
    row: dict[str, Any] = {
        "paper_trade_id": t.get("paper_trade_id"), "day": day, "symbol": sym, "side": side, "setup_family": t.get("setup_family") or "", "sector": t.get("rgs_sector") or t.get("sf_sector") or "",
        "entry_time": str(t.get("entry_time") or "")[:19], "entry_price": entry, "quantity": t.get("quantity"), "spread_pct": _f(t.get("spread_percent")),
        "entry_minute": str(t.get("entry_time") or "")[11:16], "lag_min_since_first_signal": t.get("dx_lag_min"), "exit_time": str(t.get("exit_time") or "")[:19],
        "exit_reason": t.get("exit_reason") or "", "minutes_held": held, "exit_price": _f(t.get("exit_price")), "net_pnl": _f(t.get("net_pnl")),
        "stop_distance_pct": round((entry - stop) / entry * 100, 1) if entry and stop else None, "lowest_option_price": _f(t.get("lowest_option_price")),
        "minutes_to_low": round((low_at - t0).total_seconds() / 60, 1) if low_at and t0 else None,
        "stock_pre2m_pct": None, "stock_5m_pct": None, "stock_15m_pct": None, "stock_at_exit_pct": None, "stock_worst_pct": None,        # filled below when the stock's path is known
    }
    path = stock_path(sym, day, root) if sym and day else []
    s0 = _secs(t0) if t0 else None

    def at(sec: float) -> float | None:
        before = [p for s, p in path if s <= sec]
        return before[-1] if before and sec - max(s for s, _ in path if s <= sec) < 600 else None

    p0 = at(s0) if s0 is not None else None
    move = lambda p: None if p is None or not p0 else round(sign * (p / p0 - 1) * 100, 3)               # noqa: E731
    if p0 and s0 is not None:
        row["stock_pre2m_pct"] = move(at(s0 - 120))
        row["stock_pre2m_pct"] = None if row["stock_pre2m_pct"] is None else -row["stock_pre2m_pct"]       # how far the stock had ALREADY moved our way before entry
        row["stock_5m_pct"], row["stock_15m_pct"] = move(at(s0 + 300)), move(at(s0 + 900))
        s_exit = _secs(t1) if t1 else None
        row["stock_at_exit_pct"] = move(at(s_exit)) if s_exit else None
        held_path = [sign * (p / p0 - 1) * 100 for s, p in path if s0 <= s <= (s_exit or s0)]
        row["stock_worst_pct"] = round(min(held_path), 3) if held_path else None
    hints = []
    if (row["spread_pct"] or 0) > 1.0:
        hints.append("SPREAD_WIDE")
    if row["entry_minute"] and row["entry_minute"] < "09:45":
        hints.append("EARLY_ENTRY")
    lag = t.get("dx_lag_min")
    if (row.get("stock_pre2m_pct") or 0) >= 0.10 or (lag is not None and lag <= 10):
        hints.append("CHASED")
    if row.get("stock_5m_pct") is not None and row["stock_5m_pct"] <= 0:
        hints.append("NO_FOLLOWTHROUGH")
    if row.get("stock_worst_pct") is not None and row["stock_worst_pct"] <= -0.30:
        hints.append("STOCK_AGAINST")
    if held is not None and held <= 15:
        hints.append("QUICK_STOP")
    if held is not None and held >= 60 and row.get("stock_at_exit_pct") is not None and abs(row["stock_at_exit_pct"]) <= 0.15:
        hints.append("SLOW_BLEED")
    if t.get("dx_s945_block") is True:
        hints.append("OUTSIDE_SECTOR_PICKS")
    row["hints"] = ";".join(hints)
    bits = [f"{row['exit_reason'] or 'closed'} after {held if held is not None else '?'} min, Rs {row['net_pnl']:,.0f}" if row["net_pnl"] is not None else "closed"]
    if row.get("stock_5m_pct") is not None:
        worst = f", worst {row['stock_worst_pct']:+.2f}% while held" if row.get("stock_worst_pct") is not None else ""
        bits.append(f"stock {row['stock_5m_pct']:+.2f}% (our way) 5 min after entry{worst}")
    if row.get("stock_pre2m_pct") is not None:
        bits.append(f"had moved {row['stock_pre2m_pct']:+.2f}% our way in the 2 min before entry")
    if row["spread_pct"] is not None:
        bits.append(f"spread {row['spread_pct']:.1f}%")
    row["diagnosis"] = "; ".join(bits)
    return row


def render(rows: Sequence[Mapping[str, Any]], total_closed: int, total_net: float, shown: int = 15) -> str:
    net = sum(float(r["net_pnl"] or 0) for r in rows)
    lines = ["# Trades that never went into profit after entry", "",
             f"{len(rows)} of {total_closed} closed trades ({100 * len(rows) / max(1, total_closed):.0f}%) never traded above their entry price. They lost Rs {net:,.0f}; all closed trades together: Rs {total_net:,.0f}.", ""]
    for title, key in (("By exit reason", "exit_reason"), ("By side", "side"), ("By setup", "setup_family")):
        c: Counter[str] = Counter(str(r[key] or "-") for r in rows)
        lines += [f"**{title}:** " + ", ".join(f"{k} {v}" for k, v in c.most_common(6)), ""]
    hc: Counter[str] = Counter(h for r in rows for h in str(r["hints"]).split(";") if h)
    lines += ["## What most likely went wrong (a trade can have several hints)", ""]
    for h, n in hc.most_common():
        lines.append(f"- **{h}** - {n} trades ({100 * n / max(1, len(rows)):.0f}%): {HINTS[h]}")
    lines += ["", f"## Latest {min(shown, len(rows))} trades", ""]
    for r in sorted(rows, key=lambda x: str(x["entry_time"]), reverse=True)[:shown]:
        lines.append(f"- {r['day']} {r['entry_minute']} **{r['symbol']} {r['side']}** - {r['diagnosis']}" + (f" [{r['hints'].replace(';', ', ')}]" if r["hints"] else ""))
    lines += ["", "The full list is in never_profit.csv. Hints are a starting point for review, not proof."]
    return "\n".join(lines) + "\n"


def run(history: Sequence[dict[str, Any]] | None = None, root: Path = ROOT, out: Path | None = None) -> list[dict[str, Any]]:
    out = out or root / "data" / "trade_archive"
    if history is None:
        import trade_archive

        history = trade_archive.load_history(root / "data" / "reports" / "paper_trade_history.json")
    closed = [dict(t) for t in history if str(t.get("status")).upper() == "CLOSED" and _f(t.get("net_pnl")) is not None]
    never = [t for t in closed if never_in_profit(t)]
    try:                                                     # derived tags (minutes since the first signal, sector picks) for the hints
        import derived_tags

        derived_tags.enrich(never, root)
    except Exception:                                        # noqa: BLE001 - the record must not depend on them
        pass
    rows = sorted((post_mortem(t, root) for t in never), key=lambda r: str(r["entry_time"]))
    out.mkdir(parents=True, exist_ok=True)
    with (out / "never_profit.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    (out / "never_profit.md").write_text(render(rows, len(closed), sum(float(t["net_pnl"]) for t in closed)), encoding="utf-8")
    return rows


def main() -> int:
    rows = run()
    print(f"{len(rows)} trades never went into profit -> data/trade_archive/never_profit.csv and never_profit.md")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
