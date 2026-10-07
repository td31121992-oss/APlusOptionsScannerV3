"""Daily 'missed opportunities' report: what happened to every signal the scanner saw?

For each trading day it reads the scanner's own per-cycle reports
(data/reports/intraday_movement_<date>_<time>.json) and, for every stock/direction that reached
ENTRY_READY, records the price at its first ready signal and how the stock moved afterwards
(to the close, best and worst excursion). Each signal gets a FATE:

  TRADED                        a paper trade was opened for it
  CONVERSION_BLOCKED:<reason>   passed the filters but no trade (limits / safety / option selection)
  V2_BLOCKED                    passed the A+ filter but not the Top-5-per-side ranking
  A_PLUS:<rule>                 rejected by that A+ rule (most frequent rule across its ready cycles)
  UNFILTERED                    ready but not listed as rejected anywhere

The report compares fates, so over a few days you can see whether a filter rejects more winners
than losers. Moves are STOCK moves (direction-signed), not option P&L. Read-only; changes nothing.

    python missed_opportunities.py                   # today
    python missed_opportunities.py --day 2026-10-06
    python missed_opportunities.py --backfill        # every day that has scanner reports
"""

from __future__ import annotations

import argparse
import collections
import csv
import glob
import json
import os
import re
import statistics as st
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUT_ROOT = ROOT / "data" / "missed_opportunities"
_FILE_RE = re.compile(r"intraday_movement_(\d{8})_(\d{6})\.json$")


# ----------------------------------------------------------------------------- loading
def report_days(base: Path = ROOT) -> list[str]:
    days = set()
    for f in glob.glob(str(base / "data" / "reports" / "intraday_movement_*_*.json")):
        m = _FILE_RE.search(f)
        if m:
            days.add(f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}")
    return sorted(days)


def load_cycles(day: str, base: Path = ROOT) -> list[dict[str, Any]]:
    """Trimmed cycle records for one day, in time order, de-duplicated by timestamp."""
    stamp = day.replace("-", "")
    seen, cycles = set(), []
    for f in sorted(glob.glob(str(base / "data" / "reports" / f"intraday_movement_{stamp}_*.json"))):
        m = _FILE_RE.search(f)
        if not m or m.group(2) in seen:
            continue
        seen.add(m.group(2))
        try:
            rep = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        hh = m.group(2)
        cycles.append({
            "time": f"{hh[:2]}:{hh[2:4]}:{hh[4:]}",
            "ready": [
                {"symbol": x.get("symbol"), "direction": x.get("direction"), "ltp": x.get("ltp"), "stage": x.get("stage")}
                for x in ((rep.get("shortlists") or {}).get("ENTRY_READY") or []) if isinstance(x, dict)
            ],
            "a_plus_rejected": [
                {"symbol": x.get("symbol"), "direction": x.get("direction"), "status": x.get("status")}
                for x in ((rep.get("aplus_selective_gate") or {}).get("rejected_symbols") or []) if isinstance(x, dict)
            ],
            "v2_blocked": [
                {"symbol": x.get("symbol"), "direction": x.get("direction")}
                for x in ((rep.get("stock_selection_v2") or {}).get("blocked") or []) if isinstance(x, dict)
            ],
            "v2_passed": list((rep.get("stock_selection_v2") or {}).get("passed_symbols") or []),
            "ltp": {r.get("symbol"): r.get("ltp") for r in ((rep.get("fno_market_watch") or {}).get("rows") or []) if r.get("ltp")},
        })
    return cycles


def traded_keys(day: str, base: Path = ROOT) -> set[tuple[str, str]]:
    """(symbol, direction) pairs that became paper trades on `day` (history, journal, capsules)."""
    keys: set[tuple[str, str]] = set()
    try:
        import evaluate_rules as er

        for t in er.load_trades(base):
            tid = str(t.get("paper_trade_id", ""))
            if tid[3:11] == day.replace("-", "") and t.get("symbol"):
                keys.add((str(t["symbol"]).upper(), str(t.get("direction", "")).upper()))
    except Exception:  # noqa: BLE001 - best effort
        pass
    return keys


def conversion_failures(day: str, base: Path = ROOT) -> dict[tuple[str, str], str]:
    """(symbol, direction) -> short failure reason, parsed from the scanner log's conversion audit."""
    out: dict[tuple[str, str], collections.Counter] = collections.defaultdict(collections.Counter)
    candidates = [base / "logs" / f"scanner.log.{day}"]
    if day == date.today().isoformat():
        candidates.append(base / "logs" / "scanner.log")
    for path in candidates:
        if not path.exists():
            continue
        with path.open(encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if not line.startswith(day) or "PAPER conversion audit" not in line:
                    continue
                m = re.search(r"symbol=(\S+) direction=(\S+) plan=(\w+) safety=(\w+) option_error=(.*)", line)
                if m and m.group(3) == "FAIL":
                    reason = m.group(5).strip()
                    if "open-position" in reason.lower():
                        short = "open-position limit"
                    elif "total deployed" in reason.lower() or "premium" in reason.lower():
                        short = "premium cap"
                    elif "consecutive" in reason.lower():
                        short = "consecutive-loss limit"
                    elif "daily loss" in reason.lower():
                        short = "daily-loss limit"
                    else:
                        short = re.sub(r"[0-9.]+", "#", reason)[:40] or "other"
                    out[(m.group(1).upper(), m.group(2).upper())][short] += 1
    return {k: v.most_common(1)[0][0] for k, v in out.items()}


# ----------------------------------------------------------------------------- analysis
def build_signals(cycles: list[dict], traded: set[tuple[str, str]], conv: dict[tuple[str, str], str]) -> list[dict[str, Any]]:
    if not cycles:
        return []
    first: dict[tuple[str, str], dict] = {}
    rejects: dict[tuple[str, str], collections.Counter] = collections.defaultdict(collections.Counter)
    ready_cycles: collections.Counter = collections.Counter()
    passed_a_plus: set[tuple[str, str]] = set()
    v2_blocked: set[tuple[str, str]] = set()
    for c in cycles:
        rej_now = {(str(x["symbol"]).upper(), str(x["direction"]).upper()): x["status"] for x in c["a_plus_rejected"]}
        blk_now = {(str(x["symbol"]).upper(), str(x["direction"]).upper()) for x in c["v2_blocked"]}
        for x in c["ready"]:
            if not x.get("symbol") or not x.get("direction"):
                continue
            key = (str(x["symbol"]).upper(), str(x["direction"]).upper())
            ready_cycles[key] += 1
            ltp = x.get("ltp") or c["ltp"].get(x["symbol"])
            if key not in first and ltp:
                first[key] = {"time": c["time"], "price": float(ltp)}
            if key in rej_now:
                rejects[key][str(rej_now[key])] += 1
            else:
                passed_a_plus.add(key)
                if key in blk_now:
                    v2_blocked.add(key)

    last_ltp = {}
    for c in cycles:
        last_ltp.update({k: float(v) for k, v in c["ltp"].items() if v})

    signals = []
    for key, f in first.items():
        sym, direction = key
        sign = 1.0 if direction == "BULLISH" else -1.0
        path = [float(c["ltp"][sym]) for c in cycles if c["time"] >= f["time"] and c["ltp"].get(sym)]
        if len(path) < 2 or f["price"] <= 0:
            continue
        moves = [sign * (p - f["price"]) / f["price"] * 100.0 for p in path]
        if key in traded:
            fate = "TRADED"
        elif key in conv:
            fate = f"CONVERSION_BLOCKED:{conv[key]}"
        elif key in v2_blocked:
            fate = "V2_BLOCKED"
        elif key in passed_a_plus and key not in rejects:
            fate = "UNFILTERED"
        elif rejects.get(key):
            fate = "A_PLUS:" + rejects[key].most_common(1)[0][0].replace("A_PLUS_WAIT_", "").lower()
        else:
            fate = "UNFILTERED"
        signals.append({
            "symbol": sym, "direction": direction, "first_ready": f["time"][:5], "entry_price": round(f["price"], 2),
            "ready_cycles": ready_cycles[key], "fate": fate, "close_pct": round(moves[-1], 3),
            "best_pct": round(max(moves), 3), "worst_pct": round(min(moves), 3),
        })
    return sorted(signals, key=lambda s: (s["first_ready"], s["symbol"]))


def _group(fate: str) -> str:
    return fate.split(":")[0] if fate.startswith(("CONVERSION_BLOCKED", "A_PLUS")) else fate


def summarize(signals: list[dict[str, Any]], by: str = "fate") -> list[dict[str, Any]]:
    buckets: dict[str, list[dict]] = collections.defaultdict(list)
    for s in signals:
        buckets[s["fate"] if by == "fate" else _group(s["fate"])].append(s)
    rows = []
    for name, items in buckets.items():
        closes = [i["close_pct"] for i in items]
        rows.append({
            "fate": name, "n": len(items), "right_at_close_pct": round(100 * sum(1 for c in closes if c > 0) / len(items), 1),
            "median_close_pct": round(st.median(closes), 2), "mean_close_pct": round(st.mean(closes), 2),
            "median_best_pct": round(st.median([i["best_pct"] for i in items]), 2),
            "median_worst_pct": round(st.median([i["worst_pct"] for i in items]), 2),
            "went_1pct_against": round(100 * sum(1 for i in items if i["worst_pct"] <= -1.0) / len(items), 1),
        })
    return sorted(rows, key=lambda r: -r["n"])


def analyze_day(day: str, base: Path = ROOT) -> dict[str, Any]:
    cycles = load_cycles(day, base)
    signals = build_signals(cycles, traded_keys(day, base), conversion_failures(day, base))
    return {
        "day": day, "cycles": len(cycles), "signals": signals, "by_fate": summarize(signals), "by_group": summarize(signals, "group"),
        "overall": summarize([{**s, "fate": "ALL"} for s in signals]) if signals else [],
    }


# ----------------------------------------------------------------------------- output
def write_day(result: dict[str, Any], out_root: Path = OUT_ROOT) -> Path:
    folder = out_root / result["day"]
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "signals.csv").open("w", newline="", encoding="utf-8") as h:
        cols = ["symbol", "direction", "first_ready", "entry_price", "ready_cycles", "fate", "close_pct", "best_pct", "worst_pct"]
        w = csv.DictWriter(h, fieldnames=cols)
        w.writeheader()
        w.writerows(result["signals"])
    (folder / "summary.json").write_text(json.dumps({k: v for k, v in result.items() if k != "signals"}, indent=1), encoding="utf-8")
    (folder / "report.md").write_text(render_markdown(result), encoding="utf-8")
    return folder


def render_markdown(r: dict[str, Any]) -> str:
    def table(rows):
        head = "| fate | n | right at close | median close | median best | median worst | went 1% against |\n|---|---:|---:|---:|---:|---:|---:|\n"
        return head + "\n".join(
            f"| {x['fate']} | {x['n']} | {x['right_at_close_pct']}% | {x['median_close_pct']:+.2f}% | {x['median_best_pct']:+.2f}% | {x['median_worst_pct']:+.2f}% | {x['went_1pct_against']}% |"
            for x in rows)
    ov = r["overall"][0] if r["overall"] else None
    lines = [f"# Missed opportunities - {r['day']}", "",
             f"{r['cycles']} scanner cycles, {len(r['signals'])} signals (stock/direction pairs that reached ENTRY_READY).",
             "Moves are direction-signed STOCK moves from the first ready signal; they are not option P&L.", ""]
    if ov:
        lines += [f"**All signals:** {ov['right_at_close_pct']}% ended in the right direction; median close {ov['median_close_pct']:+.2f}%, "
                  f"median best {ov['median_best_pct']:+.2f}%, median worst {ov['median_worst_pct']:+.2f}%.", ""]
    lines += ["## By filter group", "", table(r["by_group"]), "", "## By exact fate", "", table(r["by_fate"]), ""]
    traded = [s for s in r["signals"] if s["fate"] == "TRADED"]
    if traded:
        lines += ["## Signals that were traded", ""] + [f"- {s['symbol']} {s['direction']} at {s['first_ready']}: close {s['close_pct']:+.2f}%, best {s['best_pct']:+.2f}%, worst {s['worst_pct']:+.2f}%" for s in traded] + [""]
    missed = sorted((s for s in r["signals"] if s["fate"] != "TRADED"), key=lambda s: -s["close_pct"])[:10]
    lines += ["## Biggest missed winners (not traded)", ""] + [f"- {s['symbol']} {s['direction']} first ready {s['first_ready']}: close {s['close_pct']:+.2f}%, best {s['best_pct']:+.2f}% - fate: {s['fate']}" for s in missed] + [""]
    return "\n".join(lines)


def update_cumulative(results: list[dict[str, Any]], out_root: Path = OUT_ROOT) -> dict[str, Any]:
    """Aggregate every stored day into cumulative.json / cumulative.csv (by filter group)."""
    all_signals: list[dict] = []
    days = []
    for folder in sorted(p for p in out_root.iterdir() if p.is_dir()) if out_root.exists() else []:
        f = folder / "signals.csv"
        if f.exists():
            days.append(folder.name)
            with f.open(encoding="utf-8") as h:
                for row in csv.DictReader(h):
                    for k in ("close_pct", "best_pct", "worst_pct"):
                        row[k] = float(row[k])
                    all_signals.append(row)
    summary = {"days": days, "signals": len(all_signals), "by_group": summarize(all_signals, "group"), "by_fate": summarize(all_signals)[:25]}
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "cumulative.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", default=date.today().isoformat())
    ap.add_argument("--backfill", action="store_true", help="process every day that has scanner reports")
    args = ap.parse_args()
    days = report_days() if args.backfill else [args.day]
    results = []
    for d in days:
        r = analyze_day(d)
        if not r["signals"]:
            print(f"{d}: no signals/reports"); continue
        folder = write_day(r)
        results.append(r)
        ov = r["overall"][0]
        print(f"{d}: {len(r['signals'])} signals, {ov['right_at_close_pct']}% right at close, median {ov['median_close_pct']:+.2f}%  -> {folder}", flush=True)
    try:                                           # evening trade review (high/low/drawdown per trade); never blocks this report
        import trade_review
        for d in days:
            folder = trade_review.write(d)
            if folder:
                print(f"{d}: trade review -> {folder}")
    except Exception as exc:                       # noqa: BLE001
        print(f"trade review skipped: {type(exc).__name__}: {exc}")
    summary = update_cumulative(results)
    print(f"cumulative: {summary['signals']} signals over {len(summary['days'])} days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
