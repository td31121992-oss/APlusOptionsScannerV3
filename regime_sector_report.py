"""Daily report of the regime + sector shadow gate (READ-ONLY on the trading software).  .venv\\Scripts\\python regime_sector_report.py [day ...]

For each day it rebuilds, from the recorded stock ticks, the market regime (how many F&O stocks are above / below yesterday's close) and the sector medians at every 30-minute checkpoint, then judges every
paper trade of that day with the rule of regime_sector_gate.py: the trade passes only if its side is the majority side of the market AND its stock sits in the top gainer sector (calls) / top loser sector (puts)
at the last checkpoint before the entry. It shows what the passed and the blocked trades made. Hindsight on few days: it describes the days, it does not prove the rule (see regime_sector_backtest.py).
Output: data/shadow_rules/regime_sector_<day>.md, data/shadow_rules/regime_sector_latest.md (all days given) and a one-line-per-day ledger data/shadow_rules/regime_sector_ledger.csv.
"""

from __future__ import annotations

import csv
import gzip
import json
import os
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TICKS = ROOT / "data" / "ticks"
HISTORY = ROOT / "data" / "reports" / "paper_trade_history.json"
OUTDIR = ROOT / "data" / "shadow_rules"
CHECKPOINTS = ["09:30:00", "10:00:00", "10:30:00", "11:00:00", "11:30:00", "12:00:00", "12:30:00", "13:00:00", "13:30:00", "14:00:00", "14:30:00", "15:00:00", "15:30:00"]
MIN_SECTOR = 4


def sector_map() -> dict[str, str]:
    with open(ROOT / "data" / "reference" / "fno_sector_map.csv", encoding="utf-8-sig") as f:
        return {r["symbol"]: r["sector"] for r in csv.DictReader(f)}


def read_ticks(day: str, sym: str) -> list[tuple[str, float]]:
    """(time, ltp) pairs; the files can be truncated, so read in small chunks and keep what decompresses."""
    p = TICKS / day / f"{sym}.csv.gz"
    if not p.exists():
        return []
    buf = b""
    try:
        with open(p, "rb") as raw:
            d = gzip.GzipFile(fileobj=raw)
            while True:
                try:
                    ch = d.read(4096)
                except Exception:                              # noqa: BLE001 - truncated file: keep the part we have
                    break
                if not ch:
                    break
                buf += ch
    except OSError:
        return []
    out = []
    for line in buf.decode("utf-8", "ignore").splitlines()[1:]:
        a = line.split(",")
        if len(a) > 3:
            try:
                out.append((a[0][:8], float(a[2])))
            except ValueError:
                pass
    return out


def previous_day(day: str) -> str | None:
    days = sorted(d.name for d in TICKS.iterdir() if d.is_dir() and d.name[:2] == "20")
    earlier = [d for d in days if d < day]
    return earlier[-1] if earlier else None


def build_day(day: str, smap: dict[str, str]):
    prev = previous_day(day)
    if not prev:
        return None
    pc: dict[str, float] = {}
    px: dict[str, dict[str, float | None]] = {}
    for f in os.listdir(TICKS / day):
        if not f.endswith(".csv.gz"):
            continue
        s = f[:-7]
        if s not in smap:
            continue
        p0, cur = read_ticks(prev, s), read_ticks(day, s)
        if not p0 or not cur:
            continue
        pc[s] = p0[-1][1]
        d, i, last = {}, 0, None
        for t in CHECKPOINTS:
            while i < len(cur) and cur[i][0] <= t:
                last = cur[i][1]
                i += 1
            d[t] = last
        px[s] = d
    return prev, pc, px


def state(t: str, pc, px, smap):
    moves = {s: (d[t] / pc[s] - 1) * 100 for s, d in px.items() if d[t]}
    up, down = sum(1 for m in moves.values() if m > 0), sum(1 for m in moves.values() if m < 0)
    by = defaultdict(list)
    for s, m in moves.items():
        by[smap[s]].append(m)
    meds = {k: (st.median(v), len(v), sum(1 for x in v if x > 0)) for k, v in by.items() if len(v) >= MIN_SECTOR}
    return up, down, meds, moves


def report(day: str, smap, history) -> tuple[str, list[dict]] | None:
    built = build_day(day, smap)
    if not built:
        return None
    prev, pc, px = built
    if len(px) < 100:
        return None
    L = [f"# Regime + sector gate - {day}  (vs close of {prev}; {len(px)} stocks)", ""]
    up, down, meds, moves = state("15:30:00", pc, px, smap)
    order = sorted(meds.items(), key=lambda kv: -kv[1][0])
    L.append(f"Close: {up} up / {down} down ({up / max(1, up + down) * 100:.0f}% up), median stock {st.median(moves.values()):+.2f}%.")
    L.append("Top gainer sectors: " + ", ".join(f"{k} {v[0]:+.2f}%" for k, v in order[:3]) + ".  Top loser sectors: " + ", ".join(f"{k} {v[0]:+.2f}%" for k, v in order[-3:][::-1]) + ".")
    trades = sorted([t for t in history if str(t.get("entry_time"))[:10] == day], key=lambda t: t["entry_time"])
    rows = []
    for t in trades:
        hh = str(t["entry_time"])[11:19]
        cp = max([c for c in CHECKPOINTS if c <= hh] or [CHECKPOINTS[0]])
        u, d_, m, _ = state(cp, pc, px, smap)
        bull = str(t.get("option_type")).upper() == "CE"
        regime_ok = (u > d_) if bull else (d_ > u)
        sec = smap.get(t["symbol"], "?")
        ordr = sorted(m, key=lambda k: -m[k][0] * (1 if bull else -1))
        sector_ok = bool(ordr) and ordr[0] == sec
        rows.append(dict(day=day, time=hh[:5], symbol=t["symbol"], side="CALL" if bull else "PUT", sector=sec, share_up=round(u / max(1, u + d_) * 100), top_sector=ordr[0] if ordr else "",
                         regime_ok=regime_ok, sector_ok=sector_ok, gate_pass=regime_ok and sector_ok, pnl=float(t.get("net_pnl") or 0),
                         live_tag=t.get("rgs_would_block")))
    if rows:
        def tot(f):
            a, b = [r for r in rows if f(r)], [r for r in rows if not f(r)]
            return f"PASS {len(a)} trades {sum(r['pnl'] for r in a):+,.0f} | BLOCK {len(b)} trades {sum(r['pnl'] for r in b):+,.0f}"
        L += ["", f"Paper trades: {len(rows)}.  Regime only: {tot(lambda r: r['regime_ok'])}.  Regime + top sector (the combined gate): {tot(lambda r: r['gate_pass'])}.", "",
              "| Time | Stock | Side | Sector | % of stocks up | Top sector then | Regime ok | Top sector | Gate | Net P&L |", "|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            L.append(f"| {r['time']} | {r['symbol']} | {r['side']} | {r['sector']} | {r['share_up']}% | {r['top_sector']} | {'yes' if r['regime_ok'] else 'no'} | {'yes' if r['sector_ok'] else 'no'} | "
                     f"{'PASS' if r['gate_pass'] else 'block'} | {r['pnl']:+,.0f} |")
    else:
        L.append("\nNo paper trades on this day.")
    return "\n".join(L), rows


def main(days: list[str]) -> int:
    history = json.loads(HISTORY.read_text(encoding="utf-8")).get("paper_trades", [])
    smap = sector_map()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    allrows, parts = [], []
    for day in days:
        out = report(day, smap, history)
        if not out:
            print(f"{day}: no usable ticks / previous day")
            continue
        text, rows = out
        (OUTDIR / f"regime_sector_{day}.md").write_text(text, encoding="utf-8")
        parts.append(text)
        allrows += rows
        print(text.splitlines()[0]); print(text.splitlines()[2]); print(text.splitlines()[3])
        if rows:
            print("  " + text.split("\n")[5])
    if allrows:
        a = [r for r in allrows if r["gate_pass"]]
        b = [r for r in allrows if not r["gate_pass"]]
        c = [r for r in allrows if r["regime_ok"]]
        summary = (f"\nALL {len(set(r['day'] for r in allrows))} DAYS, {len(allrows)} trades: combined gate PASS {len(a)} trades {sum(r['pnl'] for r in a):+,.0f} (avg {sum(r['pnl'] for r in a) / max(1, len(a)):+,.0f}) | "
                   f"BLOCK {len(b)} trades {sum(r['pnl'] for r in b):+,.0f} (avg {sum(r['pnl'] for r in b) / max(1, len(b)):+,.0f}).  Regime-only pass {len(c)} trades {sum(r['pnl'] for r in c):+,.0f}.")
        print(summary)
        (OUTDIR / "regime_sector_latest.md").write_text("\n\n".join(parts) + "\n" + summary, encoding="utf-8")
        ledger = OUTDIR / "regime_sector_ledger.csv"
        new = not ledger.exists()
        done = set()
        if not new:
            with open(ledger, encoding="utf-8") as f:
                done = {(r["day"], r["time"], r["symbol"]) for r in csv.DictReader(f)}
        with open(ledger, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(allrows[0]))
            if new:
                w.writeheader()
            for r in allrows:
                if (r["day"], r["time"], r["symbol"]) not in done:
                    w.writerow(r)
    return 0


if __name__ == "__main__":
    days = sys.argv[1:] or sorted(d.name for d in TICKS.iterdir() if d.is_dir() and d.name[:2] == "20")[-1:]
    raise SystemExit(main(days))
