"""Chart-pattern outcome log (RESEARCH ONLY - it never influences a trade).

Every day after the close, for every F&O stock, find the candle / structure patterns that formed on the 5-minute chart and record
what the stock did AFTER each one (next 15, 30, 60 minutes and to the close, best and worst move inside the next hour). Results
accumulate across days so we can see which patterns actually lead to a move and which do not.

    data/pattern_log/<day>.csv      one row per pattern occurrence
    data/pattern_log/summary.md     cumulative statistics per pattern (and per time of day)
    data/pattern_log/summary.json   the same numbers

Moves are signed in the direction the pattern "expects": bullish patterns (hammer, bullish engulfing, break above the previous day's
high, ...) count an up move as positive, bearish patterns count a down move as positive. Neutral patterns (doji, inside bar, NR7,
compression) are shown raw (+ = up).

    python pattern_log.py [YYYY-MM-DD]     build today (or that day)
"""

from __future__ import annotations

import csv
import glob
import json
import os
import statistics as st
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
FIRST_DAY = "2026-10-01"

# pattern -> side (+1 expects up, -1 expects down, 0 neutral/raw)
PATTERNS: dict[str, int] = {
    "bullish_engulfing": 1, "bearish_engulfing": -1, "hammer": 1, "shooting_star": -1, "doji": 0, "marubozu_up": 1,
    "marubozu_down": -1, "inside_bar": 0, "nr7": 0, "expansion_up": 1, "expansion_down": -1, "range_breakout": 1,
    "range_breakdown": -1, "compression": 0, "hh_hl_trend": 1, "lh_ll_trend": -1,
    "prev_day_high_break": 1, "prev_day_low_break": -1, "opening_range_high_break": 1, "opening_range_low_break": -1,
}
HORIZONS = (3, 6, 12)                                      # bars of 5 minutes: 15, 30, 60 minutes
BUCKETS = ((0, 630, "09:15-10:30"), (630, 780, "10:30-13:00"), (780, 1440, "after 13:00"))


def _minutes(ts: Any) -> int:
    x = datetime.fromtimestamp(int(ts), IST)
    return x.hour * 60 + x.minute


def detect_events(candles: dict[str, list[float]], prev_high: float | None = None, prev_low: float | None = None) -> list[dict[str, Any]]:
    """candles: parallel lists timestamp/open/high/low/close/volume for ONE day, 5-minute. Returns pattern events with forward moves."""
    import pandas as pd

    from candle_chart_patterns import add_candle_patterns, add_chart_structure

    n = len(candles.get("close") or [])
    if n < 8:
        return []
    df = pd.DataFrame({k: candles[k] for k in ("open", "high", "low", "close", "volume")}).astype(float)
    df = add_chart_structure(add_candle_patterns(df))
    mins = [_minutes(t) for t in candles["timestamp"]]
    flags: dict[str, Any] = {
        "bullish_engulfing": df["bullish_engulfing"], "bearish_engulfing": df["bearish_engulfing"], "hammer": df["hammer"],
        "shooting_star": df["shooting_star"], "doji": df["doji"],
        "marubozu_up": df["marubozu"] & df["bullish"], "marubozu_down": df["marubozu"] & df["bearish"],
        "inside_bar": df["inside_bar"], "nr7": df["nr7"],
        "expansion_up": df["expansion_candle"] & df["bullish"], "expansion_down": df["expansion_candle"] & df["bearish"],
        "range_breakout": df["range_breakout"], "range_breakdown": df["range_breakdown"], "compression": df["compression"],
        "hh_hl_trend": df["hh_hl"], "lh_ll_trend": df["lh_ll"],
    }
    if prev_high:
        flags["prev_day_high_break"] = df["close"] > prev_high
    if prev_low:
        flags["prev_day_low_break"] = df["close"] < prev_low
    orb = [i for i, m in enumerate(mins) if m < 570]        # 09:15-09:29 bars form the opening range
    if len(orb) >= 3:
        orh, orl = float(df["high"].iloc[orb].max()), float(df["low"].iloc[orb].min())
        after = pd.Series([m >= 570 for m in mins])
        flags["opening_range_high_break"] = (df["close"] > orh) & after
        flags["opening_range_low_break"] = (df["close"] < orl) & after
    closes, highs, lows = df["close"].tolist(), df["high"].tolist(), df["low"].tolist()
    events: list[dict[str, Any]] = []
    for name, series in flags.items():
        arr = [bool(x) for x in series.fillna(False).tolist()]
        for i in range(1, n):
            if not arr[i] or arr[i - 1]:                    # first bar of each run only
                continue
            if name in ("hh_hl_trend", "lh_ll_trend", "compression") and i < 6:
                continue
            side = PATTERNS[name] or 1
            px = closes[i]
            if px <= 0:
                continue
            row: dict[str, Any] = {"pattern": name, "side": PATTERNS[name], "time": f"{mins[i] // 60:02d}:{mins[i] % 60:02d}",
                                   "minute": mins[i], "price": round(px, 2)}
            for h in HORIZONS:
                j = i + h
                row[f"f{h * 5}"] = round(side * (closes[j] / px - 1) * 100, 3) if j < n else ""
            row["f_close"] = round(side * (closes[-1] / px - 1) * 100, 3) if i < n - 1 else ""
            window = range(i + 1, min(n, i + 13))
            if len(window) >= 3:
                if side > 0:
                    row["mfe60"] = round((max(highs[k] for k in window) / px - 1) * 100, 3)
                    row["mae60"] = round((min(lows[k] for k in window) / px - 1) * 100, 3)
                else:
                    row["mfe60"] = round((1 - min(lows[k] for k in window) / px) * 100, 3)
                    row["mae60"] = round((1 - max(highs[k] for k in window) / px) * 100, 3)
            else:
                row["mfe60"] = row["mae60"] = ""
            events.append(row)
    return events


def _num(v: Any) -> float | None:
    try:
        return float(v) if v not in ("", None) else None
    except (TypeError, ValueError):
        return None


def summarize(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[r["pattern"]].append(r)
    for name, g in by.items():
        entry: dict[str, Any] = {"side": PATTERNS.get(name, 0), "all": _stats(g), "buckets": {}}
        for lo, hi, label in BUCKETS:
            sub = [r for r in g if lo <= int(_num(r.get("minute")) or 0) < hi]
            if sub:
                entry["buckets"][label] = _stats(sub)
        out[name] = entry
    return out


def _stats(g: list[dict[str, Any]]) -> dict[str, Any]:
    f30 = [x for x in (_num(r.get("f30")) for r in g) if x is not None]
    f60 = [x for x in (_num(r.get("f60")) for r in g) if x is not None]
    fc = [x for x in (_num(r.get("f_close")) for r in g) if x is not None]
    mfe = [x for x in (_num(r.get("mfe60")) for r in g) if x is not None]
    mae = [x for x in (_num(r.get("mae60")) for r in g) if x is not None]
    def pct_pos(v):
        return round(100 * sum(1 for x in v if x > 0) / len(v)) if v else None
    return {"n": len(g), "days": len({r.get("day") for r in g}),
            "up30": pct_pos(f30), "mean30": round(st.mean(f30), 3) if f30 else None, "median30": round(st.median(f30), 3) if f30 else None,
            "up60": pct_pos(f60), "mean60": round(st.mean(f60), 3) if f60 else None,
            "up_close": pct_pos(fc), "mean_close": round(st.mean(fc), 3) if fc else None,
            "mfe60": round(st.mean(mfe), 2) if mfe else None, "mae60": round(st.mean(mae), 2) if mae else None}


def render(summary: dict[str, Any], days: list[str], symbols: int) -> str:
    out = ["# Chart-pattern outcome log (research only)", "",
           f"{len(days)} day(s) on file ({days[0] if days else '-'} to {days[-1] if days else '-'}), F&O stocks, 5-minute candles. "
           "Each row is a pattern's first bar; moves are in the pattern's expected direction (+ = it worked), measured from that bar's close.",
           "Neutral patterns (doji, inside bar, NR7, compression) show the raw move (+ = up). A pattern is only interesting when it "
           "beats ~50% 'worked' AND a positive mean over many occurrences on several days; small counts mean nothing.", "",
           "| Pattern | Expects | n | Worked @30m | Mean 30m | Worked @60m | Mean 60m | Worked to close | Mean close | Avg best 1h | Avg worst 1h |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    def line(label, s, expects=""):
        f = lambda v, suf="%": "-" if v is None else f"{v:+.2f}{suf}" if isinstance(v, float) else f"{v}{suf}"
        return (f"| {label} | {expects} | {s['n']} | {f(s['up30'])} | {f(s['mean30'])} | {f(s['up60'])} | {f(s['mean60'])} | "
                f"{f(s['up_close'])} | {f(s['mean_close'])} | {f(s['mfe60'])} | {f(s['mae60'])} |")
    for name, entry in sorted(summary.items(), key=lambda kv: -kv[1]["all"]["n"]):
        sd = entry["side"]
        out.append(line(name, entry["all"], "up" if sd > 0 else "down" if sd < 0 else "-"))
    for _lo, _hi, label in BUCKETS:
        out += ["", f"## {label}", "", "| Pattern | Expects | n | Worked @30m | Mean 30m | Worked @60m | Mean 60m | Worked to close | Mean close | Avg best 1h | Avg worst 1h |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]
        for name, entry in sorted(summary.items(), key=lambda kv: -kv[1]["all"]["n"]):
            s = entry["buckets"].get(label)
            if s:
                sd = entry["side"]
                out.append(line(name + ("" if s["n"] >= 30 else " (few)"), s, "up" if sd > 0 else "down" if sd < 0 else "-"))
    out += ["", f"_{symbols} symbols scanned on the latest day. Nothing here changes trading._", ""]
    return "\n".join(out)


def _load_rows(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    days: list[str] = []
    for path in sorted(glob.glob(str(root / "data" / "pattern_log" / "20*.csv"))):
        day = Path(path).stem
        if day < FIRST_DAY:
            continue
        days.append(day)
        with open(path, encoding="utf-8", newline="") as handle:
            rows.extend(csv.DictReader(handle))
    return rows, days


def write_summary(root: Path = ROOT, symbols: int = 0) -> Path | None:
    rows, days = _load_rows(root)
    if not rows:
        return None
    summary = summarize(rows)
    folder = root / "data" / "pattern_log"
    (folder / "summary.json").write_text(json.dumps({"days": days, "patterns": summary}, indent=1), encoding="utf-8")
    path = folder / "summary.md"
    path.write_text(render(summary, days, symbols), encoding="utf-8")
    return path


def _headers(root: Path) -> dict[str, str]:
    from dotenv import load_dotenv

    load_dotenv(root / ".env")
    from dhan_auth import resolve_access_token

    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    tok = resolve_access_token(project_root=root, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    return {"access-token": tok, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"}


def _fetch(sid: int, day: str, headers: dict[str, str], frm: str | None = None) -> dict[str, list[float]]:
    import requests

    r = requests.post("https://api.dhan.co/v2/charts/intraday", headers=headers, timeout=30, json={
        "securityId": str(sid), "exchangeSegment": "NSE_EQ", "instrument": "EQUITY", "interval": "5", "oi": False,
        "fromDate": f"{frm or day} 09:00:00", "toDate": f"{day} 15:30:00"})
    if r.status_code != 200:
        return {}
    return r.json() or {}


def run(day: str | None = None, root: Path = ROOT, pause: float = 0.35) -> Path | None:
    """Build the pattern log for `day` (default today). Safe to re-run: the day's file is rewritten."""
    day = day or date.today().isoformat()
    if day < FIRST_DAY:
        return None
    from order_book_recorder import _universe

    universe = _universe()
    headers = _headers(root)
    start = (date.fromisoformat(day) - timedelta(days=6)).isoformat()
    rows: list[dict[str, Any]] = []
    done = 0
    for symbol, sid in sorted(universe.items()):
        try:
            time.sleep(pause)
            data = _fetch(sid, day, headers, start)
            ts = data.get("timestamp") or []
            if len(ts) < 10:
                continue
            by_day: dict[str, list[int]] = defaultdict(list)
            for i, t in enumerate(ts):
                by_day[datetime.fromtimestamp(int(t), IST).strftime("%Y-%m-%d")].append(i)
            if day not in by_day:
                continue
            prior = [d for d in sorted(by_day) if d < day]
            prev_high = prev_low = None
            if prior:
                idx = by_day[prior[-1]]
                prev_high = max(data["high"][i] for i in idx)
                prev_low = min(data["low"][i] for i in idx)
            sel = by_day[day]
            candles = {k: [data[k][i] for i in sel] for k in ("timestamp", "open", "high", "low", "close", "volume")}
            for ev in detect_events(candles, prev_high, prev_low):
                ev.update({"day": day, "symbol": symbol})
                rows.append(ev)
            done += 1
        except Exception:                                  # noqa: BLE001 - one bad symbol must not stop the log
            continue
    folder = root / "data" / "pattern_log"
    folder.mkdir(parents=True, exist_ok=True)
    cols = ["day", "symbol", "time", "minute", "pattern", "side", "price", "f15", "f30", "f60", "f_close", "mfe60", "mae60"]
    with (folder / f"{day}.csv").open("w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return write_summary(root, done)


def main() -> int:
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    p = run(day)
    print(p or "no data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
