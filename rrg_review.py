"""Nightly shadow review: does the sector-rotation (RRG) alignment tag separate winning from losing paper trades? (research only; nothing here changes a trade)

The paper journal records `rrg_aligned` on every trade (True when the stock's sector rotation quadrant agrees with the trade's direction). This reads every closed trade that has the tag
(data/reports/paper_trade_history.csv plus the live journal) and writes

    data/shadow_rules/rrg_review.md      per day and in total: trades, P&L, win rate, average P&L for aligned and not-aligned trades, and what a rule that skipped the
                                         not-aligned ones would have done (trades skipped, P&L removed, winners it would have lost), split by side

    python rrg_review.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent


def load_trades(root: Path = ROOT) -> pd.DataFrame:
    frames = []
    hist = root / "data" / "reports" / "paper_trade_history.csv"
    if hist.exists():
        frames.append(pd.read_csv(hist, low_memory=False))
    live = root / "data" / "intraday_movement" / "paper_trade_journal.json"
    if live.exists():
        try:
            obj = json.loads(live.read_text(encoding="utf-8"))
            frames.append(pd.DataFrame(obj["trades"] if isinstance(obj, dict) else obj))
        except (OSError, ValueError, KeyError):
            pass
    if not frames:
        return pd.DataFrame()
    d = pd.concat(frames, ignore_index=True)
    if "rrg_aligned" not in d or "net_pnl" not in d:
        return pd.DataFrame()
    d["key"] = d.symbol.astype(str) + d.entry_time.astype(str)
    d = d.drop_duplicates("key", keep="last").copy()
    d["net"] = pd.to_numeric(d.net_pnl, errors="coerce")
    d["day"] = d.entry_time.astype(str).str[:10]
    d["aligned"] = d.rrg_aligned.astype(str).str.strip().str.lower().map({"true": True, "false": False, "1": True, "0": False, "1.0": True, "0.0": False})
    d = d[d.net.notna() & d.aligned.notna() & d.status.astype(str).str.upper().eq("CLOSED")].copy()
    d["aligned"] = d.aligned.astype(bool)
    return d


def _row(g: pd.DataFrame) -> dict[str, Any]:
    return {"n": len(g), "pnl": float(g.net.sum()), "win": float((g.net > 0).mean() * 100) if len(g) else 0.0, "avg": float(g.net.mean()) if len(g) else 0.0}


def _fmt(r: dict[str, Any]) -> str:
    return f"{r['n']} trades, {r['pnl']:+,.0f}, {r['win']:.0f}% win, avg {r['avg']:+,.0f}"


def build(d: pd.DataFrame) -> str:
    days = sorted(d.day.unique())
    lines = ["# Sector-rotation (RRG) alignment: shadow review (research only)", "",
             f"{len(d)} closed paper trades with the tag over {len(days)} day(s) ({days[0]} to {days[-1]}). `Aligned` = the stock's sector rotation quadrant agrees with the trade's direction.", "",
             "## All days", "", "| Group | Result |", "|---|---|"]
    a, n = d[d.aligned], d[~d.aligned]
    lines += [f"| Aligned | {_fmt(_row(a))} |", f"| Not aligned | {_fmt(_row(n))} |", ""]
    lines += ["## What a rule that skipped the not-aligned trades would have done", "",
              f"- Trades skipped: **{len(n)}** of {len(d)}, P&L removed: **{n.net.sum():+,.0f}** | winners it would have lost: **{int((n.net > 0).sum())}** ({n[n.net > 0].net.sum():+,.0f})",
              f"- P&L of the remaining aligned trades: **{a.net.sum():+,.0f}** (all trades: {d.net.sum():+,.0f})", "",
              "## By side", "", "| Side | Aligned | Not aligned |", "|---|---|---|"]
    for side in ("BULLISH", "BEARISH"):
        s = d[d.direction.astype(str).str.upper() == side]
        if len(s):
            lines.append(f"| {side.title()} | {_fmt(_row(s[s.aligned]))} | {_fmt(_row(s[~s.aligned]))} |")
    lines += ["", "## By day", "", "| Day | Aligned | Not aligned |", "|---|---|---|"]
    better = 0
    for day in days:
        g = d[d.day == day]
        ga, gn = g[g.aligned], g[~g.aligned]
        if len(ga) and len(gn) and ga.net.mean() > gn.net.mean():
            better += 1
        lines.append(f"| {day} | {_fmt(_row(ga)) if len(ga) else '-'} | {_fmt(_row(gn)) if len(gn) else '-'} |")
    both = sum(1 for day in days if len(d[(d.day == day) & d.aligned]) and len(d[(d.day == day) & ~d.aligned]))
    lines += ["", f"Aligned had the better average on **{better} of {both}** days that had both groups.", "",
              "_Research only. A few days cannot prove an edge; look again after 10+ days and watch whether the gap keeps showing on days that go the other way._", ""]
    return "\n".join(lines)


def run(day: str | None = None, root: Path = ROOT) -> Path | None:
    d = load_trades(root)
    if d.empty:
        return None
    out = root / "data" / "shadow_rules" / "rrg_review.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(d), encoding="utf-8")
    return out


def main() -> int:
    print(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
