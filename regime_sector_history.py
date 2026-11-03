"""Regime + sector gate over ALL paper trades since the journal starts (READ-ONLY).  .venv\\Scripts\\python regime_sector_history.py

Uses the per-minute market-watch snapshots (data/chart_history/<day>/market_watch_1m.csv: symbol, sector, from_prev_close_pct) - the same fields the live shadow gate reads - and judges every paper trade
with regime_sector_gate.evaluate() at the last snapshot minute at or before its entry. Days with no (or too thin) snapshot data are listed as "no data". Hindsight on few days: it describes, it does not prove.
Output: data/shadow_rules/regime_sector_history.md and regime_sector_history.csv
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

import regime_sector_gate as g

ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / "data" / "reports" / "paper_trade_history.json"
SNAP = ROOT / "data" / "chart_history"
OUT = ROOT / "data" / "shadow_rules"


def main() -> int:
    trades = json.loads(HISTORY.read_text(encoding="utf-8")).get("paper_trades", [])
    by_day = defaultdict(list)
    for t in trades:
        by_day[str(t["entry_time"])[:10]].append(t)
    rows, nodata, L = [], [], []
    for day in sorted(by_day):
        f = SNAP / day / "market_watch_1m.csv"
        df = pd.read_csv(f, usecols=["minute", "symbol", "sector", "from_prev_close_pct"]) if f.exists() else None
        for t in sorted(by_day[day], key=lambda x: x["entry_time"]):
            hh = str(t["entry_time"])[11:16]
            snap = None
            if df is not None:
                sub = df[df["minute"] <= hh]
                if len(sub):
                    last = sub["minute"].max()
                    snap = sub[sub["minute"] == last]
                    if snap["symbol"].nunique() < 100:
                        snap = None
            if snap is None:
                nodata.append((day, t["symbol"]))
                continue
            ev = g.evaluate(t["symbol"], "BULLISH" if str(t.get("option_type")).upper() == "CE" else "BEARISH", snap.to_dict("records"))
            if "rgs_would_block" not in ev:
                nodata.append((day, t["symbol"]))
                continue
            rows.append(dict(day=day, time=hh, symbol=t["symbol"], side="CALL" if str(t.get("option_type")).upper() == "CE" else "PUT", sector=ev.get("rgs_sector"),
                             up_pct=ev.get("rgs_up_pct"), top_sector=ev.get("rgs_top_sector"), regime_ok=ev["rgs_regime_ok"], sector_ok=ev["rgs_sector1_ok"],
                             sector2_ok=ev["rgs_sector2_ok"], gate_pass=not ev["rgs_would_block"], pnl=float(t.get("net_pnl") or 0)))
    R = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    R.to_csv(OUT / "regime_sector_history.csv", index=False)

    def tot(d, m):
        a, b = d[m], d[~m]
        return f"PASS {len(a)} {a.pnl.sum():+,.0f} / BLOCK {len(b)} {b.pnl.sum():+,.0f}"

    L.append(f"# Regime + sector gate on all paper trades with market snapshots  ({R.day.min()} .. {R.day.max()})")
    L.append(f"Judged {len(R)} of {len(trades)} trades on {R.day.nunique()} days; {len(nodata)} trades on {len(set(d for d, _ in nodata))} days have no usable snapshot ({', '.join(sorted(set(d for d, _ in nodata)))}).\n")
    L.append("| Day | Trades | Combined gate (regime + top-1 sector) | Regime only | Day net |")
    L.append("|---|---|---|---|---|")
    for day, d in R.groupby("day"):
        L.append(f"| {day} | {len(d)} | {tot(d, d.gate_pass)} | {tot(d, d.regime_ok)} | {d.pnl.sum():+,.0f} |")
    L.append("")
    L.append(f"**ALL: combined gate** {tot(R, R.gate_pass)} (avg pass {R[R.gate_pass].pnl.mean() if R.gate_pass.any() else 0:+,.0f}, avg block {R[~R.gate_pass].pnl.mean():+,.0f})")
    L.append(f"**Regime only** {tot(R, R.regime_ok)}   **Regime + top-2 sectors** {tot(R, R.regime_ok & R.sector2_ok)}   **Sector only (no regime)** {tot(R, R.sector_ok)}")
    L.append("")
    L.append("By side:")
    for s, d in R.groupby("side"):
        L.append(f"- {s}: {len(d)} trades {d.pnl.sum():+,.0f}; combined PASS {int(d.gate_pass.sum())} {d[d.gate_pass].pnl.sum():+,.0f}; regime-only PASS {int(d.regime_ok.sum())} {d[d.regime_ok].pnl.sum():+,.0f}")
    L.append("")
    L.append("Trades the combined gate would have kept:")
    for _, r in R[R.gate_pass].iterrows():
        L.append(f"- {r.day} {r.time} {r.symbol} {r.side} ({r.sector}, {r.up_pct}% of stocks up): {r.pnl:+,.0f}")
    text = "\n".join(L)
    (OUT / "regime_sector_history.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
