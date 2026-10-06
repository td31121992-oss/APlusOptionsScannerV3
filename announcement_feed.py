"""NSE corporate-announcement feed for the F&O universe (24x7 'listening' layer).

Poll NSE's corporate-announcements API, keep filings for F&O stocks, grade each
HIGH / MEDIUM / LOW, persist them, publish HIGH/MEDIUM ones to
data/safety/announcement_events.csv (read by the safety gate), and send Telegram
alerts for HIGH ones. Read-only against NSE; never touches orders.

Telegram policy: no single alerts 23:00-07:00 (queued into one morning digest),
at most MAX_ALERTS_PER_DAY single alerts per day (the rest join the digest), and
the very first run records the current backlog silently (no alert burst).
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent
NEWS_DIR = ROOT / "data" / "news_intelligence"
STORE = NEWS_DIR / "announcements.jsonl"
STATE = NEWS_DIR / "announcement_state.json"
HEALTH = NEWS_DIR / "announcement_health.json"
GATE_CSV = ROOT / "data" / "safety" / "announcement_events.csv"
HOLIDAYS = ROOT / "data" / "safety" / "nse_holidays.csv"
CALPHA = Path.home() / "Desktop" / "CAlphaTrader"

API = "https://www.nseindia.com/api/corporate-announcements"
HOME = "https://www.nseindia.com/"
REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MAX_ALERTS_PER_DAY = 20
QUIET_START, QUIET_END = clock_time(23, 0), clock_time(7, 0)
MARKET_CLOSE = clock_time(15, 30)
SEEN_CAP = 30000

HIGH_DESC = (
    "financial results", "outcome of board meeting", "acquisition", "amalgamation", "merger", "demerger",
    "scheme of arrangement", "qualified institutional placement", "preferential", "rights issue", "fund raising",
    "buyback", "buy back", "bonus", "sub-division", "stock split", "action(s) initiated", "fraud", "default",
    "insolvency", "fire", "disruption", "bagging/receiving of orders", "awarding of order", "capacity expansion",
    "delisting", "open offer", "takeover",
)
MEDIUM_DESC = (
    "credit rating", "pendency of litigation", "spurt in volume", "clarification", "analysts/institutional investor meet",
    "press release", "appointment", "resignation", "investor presentation", "change in directors",
    "record date", "dividend",
)
KEY_ROLE = re.compile(r"\b(ceo|cfo|md|managing director|chief|auditor|chairman)\b", re.I)


# ----------------------------------------------------------------------------- classify / parse
def classify(desc: str, text: str = "") -> str:
    d = (desc or "").strip().lower()
    if "resignation" in d:
        return "HIGH" if KEY_ROLE.search(text or "") else "MEDIUM"
    if any(k in d for k in HIGH_DESC):
        return "HIGH"
    if any(k in d for k in MEDIUM_DESC):
        return "MEDIUM"
    return "LOW"


def _parse_an_dt(value: str) -> datetime | None:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value).strip().title(), fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def effective_session_date(published: datetime, holidays_file: Path = HOLIDAYS) -> date:
    """Date whose trading is affected: same day if published before the close, else next trading day."""
    from trading_calendar import is_trading_day

    day = published.date()
    if published.time() < MARKET_CLOSE and is_trading_day(day, holidays_file)[0]:
        return day
    day += timedelta(days=1)
    for _ in range(10):
        if is_trading_day(day, holidays_file)[0]:
            return day
        day += timedelta(days=1)
    return day


def parse_announcements(rows: list[dict], fno_symbols: set[str], holidays_file: Path = HOLIDAYS) -> list[dict]:
    out = []
    for r in rows or []:
        symbol = str(r.get("symbol") or "").strip().upper()
        if not symbol or symbol not in fno_symbols:
            continue
        published = _parse_an_dt(r.get("an_dt") or r.get("sort_date"))
        if published is None:
            continue
        desc = str(r.get("desc") or "").strip()
        text = " ".join(str(r.get("attchmntText") or "").split())
        key = f"{symbol}|{r.get('an_dt')}|{desc}|{r.get('seq_id') or ''}"
        out.append({
            "id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:20],
            "symbol": symbol, "company": str(r.get("sm_name") or "").strip(), "desc": desc, "text": text[:400],
            "published_at": published.isoformat(timespec="seconds"),
            "session_date": effective_session_date(published, holidays_file).isoformat(),
            "severity": classify(desc, text), "url": str(r.get("attchmntFile") or ""), "source": "NSE announcements",
        })
    return sorted(out, key=lambda a: a["published_at"])


# ----------------------------------------------------------------------------- persistence
def _atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def load_state(path: Path = STATE) -> dict[str, Any]:
    try:
        s = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(s, dict):
            s.setdefault("seen", [])
            s.setdefault("pending", [])
            s.setdefault("sent_today", {"date": "", "count": 0})
            s.setdefault("last_digest", "")
            return s
    except (OSError, ValueError):
        pass
    return {"baselined": False, "seen": [], "pending": [], "sent_today": {"date": "", "count": 0}, "last_digest": ""}


def save_state(state: dict[str, Any], path: Path = STATE) -> None:
    state["seen"] = state["seen"][-SEEN_CAP:]
    _atomic(path, json.dumps(state))


def append_store(items: list[dict], path: Path = STORE) -> None:
    if not items:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for a in items:
            handle.write(json.dumps(a, ensure_ascii=False) + "\n")


def recent_from_store(limit: int = 12, hours: int = 24, now: datetime | None = None, path: Path = STORE,
                      severities: tuple[str, ...] = ("HIGH", "MEDIUM")) -> list[dict]:
    """Newest announcements within `hours` (reads the tail of the file only)."""
    now = now or datetime.now(IST)
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 400_000))
            lines = handle.read().decode("utf-8", "ignore").splitlines()
    except OSError:
        return []
    cutoff = now - timedelta(hours=hours)
    items = []
    for line in lines:
        try:
            a = json.loads(line)
            if a.get("severity") in severities and datetime.fromisoformat(a["published_at"]) >= cutoff:
                items.append(a)
        except (ValueError, KeyError):
            continue
    items.sort(key=lambda a: a["published_at"], reverse=True)
    return items[:limit]


def write_gate_csv(items: list[dict], today: date, path: Path = GATE_CSV, keep_days: int = 3) -> int:
    """Publish HIGH/MEDIUM announcements whose session date is today or later (and recent) for the safety gate."""
    rows, seen = [], set()
    for a in items:
        if a["severity"] not in ("HIGH", "MEDIUM"):
            continue
        if date.fromisoformat(a["session_date"]) < today - timedelta(days=keep_days - 1):
            continue
        k = (a["symbol"], a["session_date"], a["desc"], a["severity"])
        if k in seen:
            continue
        seen.add(k)
        rows.append([a["symbol"], a["session_date"], f"ANNOUNCEMENT: {a['desc']}".upper()[:80], a["severity"],
                     today.isoformat(), "NSE announcements", a["text"][:140]])
    rows.sort(key=lambda r: (r[1], r[0]))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        w.writerow(["symbol", "event_date", "event_type", "severity", "as_of", "source", "notes"])
        w.writerows(rows)
    os.replace(tmp, path)
    return len(rows)


# ----------------------------------------------------------------------------- telegram
def send_telegram(message: str) -> tuple[bool, str]:
    py = CALPHA / ".venv" / "Scripts" / "python.exe"
    tools_dir = CALPHA / "tools"
    if not py.exists() or not (tools_dir / "telegram_alerts.py").exists():
        return False, "CAlpha Telegram sender missing"
    code = f"import sys; sys.path.insert(0, r'{tools_dir}'); import telegram_alerts as t; t.send_message(sys.argv[1])"
    try:
        p = subprocess.run([str(py), "-c", code, message], cwd=str(CALPHA), capture_output=True, text=True, timeout=90)
        return p.returncode == 0, ((p.stdout or "") + (p.stderr or ""))[-300:]
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def format_alert(a: dict) -> str:
    when = datetime.fromisoformat(a["published_at"]).strftime("%d %b %H:%M")
    return f"📢 {a['symbol']} - {a['desc']}\n{a['text'][:220]}\n({when}, affects {a['session_date']})"


def format_digest(items: list[dict]) -> str:
    lines = [f"📰 APlus announcements digest ({len(items)} HIGH-impact, F&O stocks)"]
    for a in items[:15]:
        lines.append(f"• {a['symbol']}: {a['desc']} ({datetime.fromisoformat(a['published_at']).strftime('%d %b %H:%M')})")
    if len(items) > 15:
        lines.append(f"... and {len(items) - 15} more (see Control Room)")
    return "\n".join(lines)


def in_quiet_hours(now: datetime) -> bool:
    t = now.time()
    return t >= QUIET_START or t < QUIET_END


# ----------------------------------------------------------------------------- one poll
def process(announcements: list[dict], state: dict[str, Any], now: datetime,
            sender: Callable[[str], tuple[bool, str]] | None = send_telegram) -> dict[str, Any]:
    """Update state with new announcements; return {'new': [...], 'sent': n, 'digest': bool, 'baseline': bool}."""
    seen = set(state["seen"])
    new = [a for a in announcements if a["id"] not in seen]
    result: dict[str, Any] = {"new": new, "sent": 0, "digest": False, "baseline": False}
    state["seen"] = state["seen"] + [a["id"] for a in new]

    if not state.get("baselined"):
        state["baselined"] = True        # first run: record silently, no alert burst
        result["baseline"] = True
        return result

    today = now.date().isoformat()
    if state["sent_today"].get("date") != today:
        state["sent_today"] = {"date": today, "count": 0}

    high = [a for a in new if a["severity"] == "HIGH"]
    for a in high:
        if sender is None or in_quiet_hours(now) or state["sent_today"]["count"] >= MAX_ALERTS_PER_DAY:
            state["pending"].append(a["id"])
            continue
        ok, _ = sender(format_alert(a))
        if ok:
            state["sent_today"]["count"] += 1
            result["sent"] += 1
        else:
            state["pending"].append(a["id"])

    # morning digest of everything queued overnight / over the cap
    if sender is not None and state["pending"] and not in_quiet_hours(now) and state.get("last_digest") != today:
        by_id = {a["id"]: a for a in announcements}
        queued = [by_id[i] for i in state["pending"] if i in by_id]
        if queued:
            ok, _ = sender(format_digest(queued))
            if ok:
                state["pending"], state["last_digest"] = [], today
                result["digest"] = True
        else:
            state["pending"] = []
    return result


def fetch_rows(session, day: date) -> list[dict]:
    stamp = day.strftime("%d-%m-%Y")
    r = session.get(f"{API}?index=equities&from_date={stamp}&to_date={stamp}", headers={"Referer": REFERER}, timeout=45)
    r.raise_for_status()
    body = r.json()
    return body if isinstance(body, list) else body.get("data", [])


def fno_symbols(base: Path = ROOT) -> set[str]:
    try:
        return {s.upper() for s in json.loads((base / "data" / "cache" / "instrument_universe.json").read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return set()


def poll_once(session, now: datetime | None = None, dry_run: bool = False, base: Path = ROOT) -> dict[str, Any]:
    """Fetch (today, plus yesterday before 10:00), process, persist, publish the gate file."""
    now = now or datetime.now(IST)
    symbols = fno_symbols(base)
    if not symbols:
        raise RuntimeError("F&O universe cache missing")
    session.get(HOME, timeout=20)
    days = [now.date()] + ([now.date() - timedelta(days=1)] if now.time() < clock_time(10, 0) else [])
    rows: list[dict] = []
    for d in days:
        rows.extend(fetch_rows(session, d))
    anns = parse_announcements(rows, symbols)
    state = load_state(base / "data" / "news_intelligence" / "announcement_state.json")
    result = process(anns, state, now, sender=None if dry_run else send_telegram)
    if not dry_run:
        append_store(result["new"], base / "data" / "news_intelligence" / "announcements.jsonl")
        save_state(state, base / "data" / "news_intelligence" / "announcement_state.json")
        write_gate_csv(recent_from_store(500, 72, now, base / "data" / "news_intelligence" / "announcements.jsonl"),
                       now.date(), base / "data" / "safety" / "announcement_events.csv")
    return {"fetched": len(rows), "fno": len(anns), "new": len(result["new"]),
            "new_high": sum(1 for a in result["new"] if a["severity"] == "HIGH"),
            "sent": result["sent"], "digest": result["digest"], "baseline": result["baseline"]}
