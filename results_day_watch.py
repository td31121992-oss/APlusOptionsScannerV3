"""Results-day watch (SHADOW ONLY: lists, paths and alerts in files; nothing trades on it).

The scanner already knows the morning that a stock reports that day (ev_phase RESULTS_TODAY, from NSE's event calendar) but only used it as a tag. On 26 Oct ATHERENERG was RESULTS_TODAY from 09:00, sat
flat all day, filed at 14:27:42 and ran +10 % in ten minutes; nobody was watching it. This is the watching:

    LIST     every stock in the F&O universe whose results are due today (any archived data/event_calendar/*.csv or today's safety copy that names the date), and the next date's list for the evening
    WATCH    the live numbers of those stocks only (data/ticks/rs_all.json, refreshed by the tick recorder every few seconds), one path row per stock per minute
    ALERT    one row when a watched stock moves >= 1.5 % in 5 minutes or >= 2.5 % in 15 minutes (either way), at most one per stock and direction every 5 minutes; marked FILED when its results filing
             (data/news_intelligence/announcements.jsonl) is already out and the minutes since, so the "results are out and the stock is moving" case stands apart

    data/results_day/<day>_list.json     the stocks and the dates the list came from
    data/results_day/<day>_path.csv      time, stock, price, % vs previous close, % over 5 min, % over 15 min, relative volume, filed
    data/results_day/<day>_alerts.csv    the alerts
    data/results_day/<day>_summary.md    nightly: per stock the filing time, the day's range and the biggest 5-minute move, and whether an alert fired

    python results_day_watch.py list [YYYY-MM-DD]      today's list (or the given day's); `list next` shows the next trading day's
    python results_day_watch.py live                   run during market hours (09:10 - 15:31), reads the live file every 10 s
    python results_day_watch.py replay [YYYY-MM-DD]    rebuild path, alerts and summary for a recorded day from the ticks
"""

from __future__ import annotations

import csv
import json
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
FOLDER = ("data", "results_day")
MOVE_5M_PCT, MOVE_15M_PCT = 1.5, 2.5
ALERT_EVERY_S = 300
PATH_EVERY_S = 60
PATH_FIELDS = ["time", "symbol", "price", "day_pct", "move_5m", "move_15m", "rel_volume", "filed"]
ALERT_FIELDS = ["time", "symbol", "price", "day_pct", "move_5m", "move_15m", "direction", "filed", "filed_min_ago"]


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def calendar_rows(root: Path = ROOT) -> list[dict[str, str]]:
    """Every row of every archived NSE event-calendar file plus today's safety copy: a result date is announced days ahead, so the file of the day itself may no longer list it."""
    out: list[dict[str, str]] = []
    paths = sorted((root / "data" / "event_calendar").glob("*.csv")) + [root / "data" / "safety" / "corporate_events.csv"]
    for path in paths:
        if path.exists():
            with path.open(encoding="utf-8", newline="") as h:
                out += list(csv.DictReader(h))
    return out


def results_symbols(event_date: str, root: Path = ROOT, universe: set[str] | None = None) -> list[str]:
    out = sorted({r["symbol"] for r in calendar_rows(root) if r.get("event_date") == event_date and "RESULT" in str(r.get("event_type", "")).upper() and r.get("symbol")})
    return [s for s in out if universe is None or s in universe]


def next_event_date(day: str, root: Path = ROOT) -> str | None:
    dates = sorted({r.get("event_date", "") for r in calendar_rows(root) if r.get("event_date", "") > day and "RESULT" in str(r.get("event_type", "")).upper()})
    return dates[0] if dates else None


def universe(root: Path = ROOT) -> set[str] | None:
    try:
        return set(json.loads(root.joinpath("data", "ticks", "rs_all.json").read_text(encoding="utf-8")).get("stocks", {}))
    except (OSError, ValueError):
        return None


def filings_today(day: str, root: Path = ROOT) -> dict[str, float]:
    """symbol -> seconds-of-day of its first results filing on `day` (made in or after market hours)."""
    import results_spike
    out: dict[str, float] = {}
    path = root.joinpath(*results_spike.ANN)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        pub = str(r.get("published_at") or "")
        if pub.startswith(day) and r.get("symbol") and results_spike.is_results(r):
            t = results_spike._secs_of(pub)
            if t is not None and t >= 9 * 3600:
                out[r["symbol"]] = min(out.get(r["symbol"], t), t)
    return out


class Watch:
    """Feeds on (seconds, symbol, price, day %, relative volume) and produces path rows and alerts. Pure logic: no clock, no files."""

    def __init__(self, symbols: Sequence[str], filed: Mapping[str, float] | None = None) -> None:
        self.symbols = set(symbols)
        self.filed = dict(filed or {})
        self.hist: dict[str, deque[tuple[float, float]]] = defaultdict(deque)
        self._last_path: dict[str, float] = {}
        self._last_alert: dict[tuple[str, str], float] = {}
        self.paths: list[dict[str, Any]] = []
        self.alerts: list[dict[str, Any]] = []

    def _ago(self, sym: str, t: float, secs: float) -> float | None:
        ref = None
        for ts, p in self.hist[sym]:
            if ts <= t - secs:
                ref = p
            else:
                break
        return ref

    def update(self, t: float, sym: str, price: float, day_pct: float, rel_volume: float | None = None) -> None:
        if sym not in self.symbols or price <= 0:
            return
        h = self.hist[sym]
        h.append((t, price))
        while h and h[0][0] < t - 1000:
            h.popleft()
        r5, r15 = self._ago(sym, t, 300), self._ago(sym, t, 900)
        m5 = round((price / r5 - 1) * 100, 2) if r5 else None
        m15 = round((price / r15 - 1) * 100, 2) if r15 else None
        filed_at = self.filed.get(sym)
        filed = 1 if filed_at is not None and filed_at <= t else 0
        clock = f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}"
        if t - self._last_path.get(sym, -1e9) >= PATH_EVERY_S:
            self._last_path[sym] = t
            self.paths.append({"time": clock, "symbol": sym, "price": round(price, 2), "day_pct": round(day_pct, 2), "move_5m": m5 if m5 is not None else "", "move_15m": m15 if m15 is not None else "",
                               "rel_volume": rel_volume if rel_volume is not None else "", "filed": filed})
        big = (m5 is not None and abs(m5) >= MOVE_5M_PCT) or (m15 is not None and abs(m15) >= MOVE_15M_PCT)
        if big:
            ref_move = m5 if (m5 is not None and abs(m5) >= MOVE_5M_PCT) else m15
            direction = "UP" if (ref_move or 0) > 0 else "DOWN"
            if t - self._last_alert.get((sym, direction), -1e9) >= ALERT_EVERY_S:
                self._last_alert[(sym, direction)] = t
                self.alerts.append({"time": clock, "symbol": sym, "price": round(price, 2), "day_pct": round(day_pct, 2), "move_5m": m5 if m5 is not None else "", "move_15m": m15 if m15 is not None else "",
                                    "direction": direction, "filed": filed, "filed_min_ago": round((t - filed_at) / 60.0, 1) if filed else ""})


def _write(path: Path, fields: Sequence[str], rows: Sequence[Mapping[str, Any]], append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or not append
    with path.open("a" if append else "w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(fields))
        if new:
            w.writeheader()
        w.writerows(rows)


def write_list(day: str, root: Path = ROOT) -> list[str]:
    syms = results_symbols(day, root, universe(root))
    p = root.joinpath(*FOLDER, f"{day}_list.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"day": day, "symbols": syms, "source": "data/event_calendar/*.csv + data/safety/corporate_events.csv"}, indent=1), encoding="utf-8")
    return syms


def summary(day: str, watch: Watch, root: Path = ROOT) -> Path:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in watch.paths:
        by[r["symbol"]].append(r)
    alerts = defaultdict(list)
    for a in watch.alerts:
        alerts[a["symbol"]].append(a)
    lines = [f"# Results-day watch {day} (shadow; nothing trades or alerts on this)", "", f"Watched: {len(watch.symbols)} F&O stocks reporting today. Alert = >= {MOVE_5M_PCT} % in 5 minutes or >= {MOVE_15M_PCT} % in 15.", "",
             "| stock | filed | day low % | day high % | last % | biggest 5-min move % | alerts | first alert |", "|---|---|---|---|---|---|---|---|"]
    for s in sorted(watch.symbols):
        rows = by.get(s) or []
        if not rows:
            lines.append(f"| {s} | - | no ticks | | | | | |")
            continue
        day_pcts = [r["day_pct"] for r in rows]
        m5 = [abs(r["move_5m"]) for r in rows if r["move_5m"] != ""]
        t = watch.filed.get(s)
        filed = f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}" if t is not None else "-"
        first = alerts[s][0] if alerts.get(s) else None
        lines.append(f"| {s} | {filed} | {min(day_pcts):+.2f} | {max(day_pcts):+.2f} | {day_pcts[-1]:+.2f} | {max(m5) if m5 else 0:.2f} | {len(alerts.get(s) or [])} | "
                     f"{(first['time'][:8] + ' ' + first['direction'] + (' (after filing)' if first['filed'] else '')) if first else '-'} |")
    p = root.joinpath(*FOLDER, f"{day}_summary.md")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def replay(day: str, root: Path = ROOT) -> Path | None:
    syms = write_list(day, root)
    if not syms:
        return None
    import rs_leaders
    import rs_replay
    ref = rs_leaders.load_reference(root, day)
    w = Watch(syms, filings_today(day, root))
    for t, sym, ltp, *_ in rs_replay.load_samples(root, day, step=10.0):
        if sym in w.symbols and sym in ref and ref[sym].get("prev_close"):
            w.update(t, sym, ltp, (ltp / ref[sym]["prev_close"] - 1) * 100)
    _write(root.joinpath(*FOLDER, f"{day}_path.csv"), PATH_FIELDS, w.paths)
    _write(root.joinpath(*FOLDER, f"{day}_alerts.csv"), ALERT_FIELDS, w.alerts)
    return summary(day, w, root)


def run(day: str, root: Path = ROOT) -> Path | None:
    """Nightly entry point (missed_option_returns chain)."""
    return replay(day, root)


def live(root: Path = ROOT) -> None:
    day = datetime.now(IST).strftime("%Y-%m-%d")
    syms = write_list(day, root)
    print(f"{day}: watching {len(syms)} results stocks: {', '.join(syms) or '-'}", flush=True)
    if not syms:
        return
    w = Watch(syms, filings_today(day, root))
    last_updated, n_path, n_alert, last_filings = None, 0, 0, 0.0
    while True:
        now = datetime.now(IST)
        t = now.hour * 3600 + now.minute * 60 + now.second
        if t > 15 * 3600 + 31 * 60:
            break
        if t - last_filings >= 60:                       # results filings turn up during the day
            w.filed = filings_today(day, root)
            last_filings = t
        try:
            d = json.loads(root.joinpath("data", "ticks", "rs_all.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = None
        if d and d.get("day") == day and d.get("updated") != last_updated:
            last_updated = d.get("updated")
            for s in syms:
                x = (d.get("stocks") or {}).get(s)
                if x:
                    w.update(t, s, _f(x.get("ltp")), _f(x.get("m")), x.get("rv"))
            if len(w.paths) > n_path:
                _write(root.joinpath(*FOLDER, f"{day}_path.csv"), PATH_FIELDS, w.paths[n_path:], append=True)
                n_path = len(w.paths)
            if len(w.alerts) > n_alert:
                _write(root.joinpath(*FOLDER, f"{day}_alerts.csv"), ALERT_FIELDS, w.alerts[n_alert:], append=True)
                for a in w.alerts[n_alert:]:
                    print(f"ALERT {a['time']} {a['symbol']} {a['direction']} {a['price']} 5m {a['move_5m']}% 15m {a['move_15m']}% {'FILED ' + str(a['filed_min_ago']) + ' min ago' if a['filed'] else ''}", flush=True)
                n_alert = len(w.alerts)
        time.sleep(10)
    summary(day, w, root)


def main(argv: Sequence[str]) -> int:
    cmd = argv[0] if argv else "list"
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if cmd == "live":
        live()
    elif cmd == "replay":
        print(replay(argv[1] if len(argv) > 1 else today))
    else:
        arg = argv[1] if len(argv) > 1 else today
        if arg == "next":
            nxt = next_event_date(today)
            print(f"next results date on the calendar: {nxt}")
            print(", ".join(results_symbols(nxt, ROOT, universe())) if nxt else "-")
        else:
            print(", ".join(results_symbols(arg, ROOT, universe())) or "-")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
