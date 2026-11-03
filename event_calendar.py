"""Corporate-event calendar for entry decisions (READ-ONLY; recorded as SHADOW tags and used by event_gate.py).

Why: an option's premium carries the market's expectation of a coming event. Before results the implied volatility is inflated (our own entries: IV 38-41 % with results 0-5 days away against 30 % with
none), and right after results it collapses, so a call can be right on direction and still lose. Ex-dates (bonus, split, dividend) change the share price and the option series.

Sources, all already collected by the scanner's own jobs:
    data/event_calendar/<day>.csv           daily archive of NSE's event calendar (board meetings / results dates)   } so history before today is known too
    data/safety/corporate_events.csv        today's NSE event calendar (refreshed 08:45 by update_safety_data.py)
    data/safety/corporate_actions.csv       upcoming ex-dates: dividend, bonus, split, rights (same refresh)
    data/news_intelligence/announcements.jsonl   what the stocks actually filed, with the minute (a results filing = results are OUT)
    data/safety/nse_holidays.csv            for trading-day counts

    tags(symbol, now) -> dict:
        ev_phase            RESULTS_TODAY / RESULTS_TOMORROW / RESULTS_NEAR (2-3 trading days) / REPORTED (results filed since the last close) / POST (1-3 trading days after) / "" (nothing)
        ev_results_days     trading days until the next results date (0 = today), blank when none within 15 days
        ev_results_date     that date
        ev_reported         1 when a results filing has appeared since the previous session's close
        ev_since_days       trading days since the last results date (blank when none in the last 15 days)
        ev_ex_type          DIVIDEND / BONUS / SPLIT / RIGHTS when an ex-date is today or tomorrow
        ev_ex_days          0 or 1
        ev_other            BUYBACK / FUND RAISING etc. board meeting today or tomorrow
        ev_note             a short plain-language read for the page / log

An event already filed today is never "upcoming": the premium has by then been repriced. The calendar tells WHEN, not what the result was.
"""

from __future__ import annotations

import csv
import glob
import json
import re
from collections import defaultdict
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
NEAR_DAYS = 3
LOOKAHEAD_DAYS = 15
_CACHE: dict[str, Any] = {"key": None, "data": None}
_RESULT_FILING = re.compile(r"financial result|quarterly result|outcome of board meeting.*result|unaudited", re.I)


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def _kind(event_type: str) -> str:
    t = str(event_type).upper()
    if "RESULT" in t:
        return "RESULTS"
    if "BUYBACK" in t:
        return "BUYBACK"
    if "FUND RAISING" in t:
        return "FUND RAISING"
    if "DIVIDEND" in t:
        return "DIVIDEND_MEETING"
    return "OTHER"


class Calendar:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root
        self.events: dict[str, dict[str, set[date]]] = defaultdict(lambda: defaultdict(set))   # symbol -> kind -> dates
        self.ex: dict[str, list[tuple[date, str]]] = defaultdict(list)                       # symbol -> (ex date, action)
        self.filings: dict[str, list[datetime]] = defaultdict(list)                          # symbol -> results filing times
        self.holidays: set[date] = set()
        self._load()

    # ---------------------------------------------------------------- loading
    def _load(self) -> None:
        files = sorted(glob.glob(str(self.root / "data" / "event_calendar" / "*.csv"))) + [str(self.root / "data" / "safety" / "corporate_events.csv")]
        for f in files:
            try:
                with open(f, encoding="utf-8-sig", newline="") as h:
                    for r in csv.DictReader(h):
                        d = _day(r.get("event_date", ""))
                        if d and r.get("symbol"):
                            self.events[r["symbol"].strip().upper()][_kind(r.get("event_type", ""))].add(d)
            except OSError:
                continue
        try:
            with open(self.root / "data" / "safety" / "corporate_actions.csv", encoding="utf-8-sig", newline="") as h:
                for r in csv.DictReader(h):
                    d = _day(r.get("ex_date", ""))
                    if d and r.get("symbol"):
                        self.ex[r["symbol"].strip().upper()].append((d, r.get("action", "OTHER")))
        except OSError:
            pass
        try:
            with open(self.root / "data" / "news_intelligence" / "announcements.jsonl", encoding="utf-8") as h:
                for line in h:
                    try:
                        a = json.loads(line)
                        if _RESULT_FILING.search(f"{a.get('desc', '')} {a.get('text', '')}") and str(a.get("desc", "")).lower().startswith(("outcome of board", "financial result", "integrated filing")):
                            self.filings[str(a["symbol"]).upper()].append(datetime.fromisoformat(a["published_at"]))
                    except (ValueError, KeyError, TypeError):
                        continue
        except OSError:
            pass
        try:
            with open(self.root / "data" / "safety" / "nse_holidays.csv", encoding="utf-8-sig", newline="") as h:
                self.holidays = {d for d in (_day(r.get("date", "")) for r in csv.DictReader(h)) if d}
        except OSError:
            pass

    # ---------------------------------------------------------------- dates
    def is_trading(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def trading_days_between(self, a: date, b: date) -> int:
        """Trading days from a to b (b later than a: positive; same day: 0; b earlier: negative)."""
        if a == b:
            return 0
        sign = 1 if b > a else -1
        lo, hi = (a, b) if b > a else (b, a)
        n, d = 0, lo
        while d < hi:
            d += timedelta(days=1)
            if self.is_trading(d):
                n += 1
        return sign * n

    def previous_close(self, now: datetime) -> datetime:
        d = now.date()
        if now.time() < clock_time(15, 30) or not self.is_trading(d):
            d -= timedelta(days=1)
        while not self.is_trading(d):
            d -= timedelta(days=1)
        return datetime.combine(d, clock_time(15, 30), tzinfo=now.tzinfo)

    # ---------------------------------------------------------------- the read
    def tags(self, symbol: str, now: datetime) -> dict[str, Any]:
        sym = str(symbol).upper()
        today = now.date()
        out: dict[str, Any] = {}
        results = sorted(self.events.get(sym, {}).get("RESULTS", set()))
        since = self.previous_close(now)
        filed = [t for t in self.filings.get(sym, []) if since <= (t.astimezone(now.tzinfo) if t.tzinfo and now.tzinfo else t) <= now]
        reported = bool(filed)
        upcoming = [d for d in results if d >= today]
        past = [d for d in results if d < today]
        days_to = None
        if upcoming:
            days_to = self.trading_days_between(today, upcoming[0])
            if days_to <= LOOKAHEAD_DAYS:
                out["ev_results_days"], out["ev_results_date"] = days_to, upcoming[0].isoformat()
        since_days = None
        if past:
            since_days = self.trading_days_between(past[-1], today)
            if since_days <= LOOKAHEAD_DAYS:
                out["ev_since_days"] = since_days
        out["ev_reported"] = int(reported)
        phase = ""
        if reported:
            phase = "REPORTED"
        elif days_to == 0:
            phase = "RESULTS_TODAY"
        elif days_to == 1:
            phase = "RESULTS_TOMORROW"
        elif days_to is not None and days_to <= NEAR_DAYS:
            phase = "RESULTS_NEAR"
        elif since_days is not None and 1 <= since_days <= 3:
            phase = "POST"
        out["ev_phase"] = phase
        for d, action in sorted(self.ex.get(sym, [])):
            k = (d - today).days
            if 0 <= k <= 1:
                out["ev_ex_type"], out["ev_ex_days"] = action, k
                break
        for kind in ("BUYBACK", "FUND RAISING"):
            for d in sorted(self.events.get(sym, {}).get(kind, set())):
                if 0 <= (d - today).days <= 1:
                    out["ev_other"] = kind
                    break
        out["ev_note"] = {"RESULTS_TODAY": "results due today: premium inflated, gap risk", "RESULTS_TOMORROW": "results next session: premium inflated, gap risk",
                          "RESULTS_NEAR": f"results in {days_to} trading days: premium running up", "REPORTED": "results filed since the last close: premium already repriced",
                          "POST": f"results {since_days} trading day(s) ago: premium deflated", "": ""}[phase]
        return out


def _key(root: Path) -> tuple:
    parts = []
    for p in (*glob.glob(str(root / "data" / "event_calendar" / "*.csv")), str(root / "data" / "safety" / "corporate_events.csv"), str(root / "data" / "safety" / "corporate_actions.csv"),
              str(root / "data" / "news_intelligence" / "announcements.jsonl"), str(root / "data" / "safety" / "nse_holidays.csv")):
        try:
            st = Path(p).stat()
            parts.append((p, st.st_mtime, st.st_size))
        except OSError:
            continue
    return tuple(parts)


def calendar(root: Path = ROOT) -> Calendar:
    key = (str(root), _key(root))
    if _CACHE["key"] != key:
        _CACHE.update(key=key, data=Calendar(root))
    return _CACHE["data"]


def tags(symbol: str, now: datetime, root: Path = ROOT) -> dict[str, Any]:
    """Shadow tags for a candidate; {} when anything goes wrong (a tag must never affect trading)."""
    try:
        return calendar(root).tags(symbol, now)
    except Exception:                                      # noqa: BLE001
        return {}
