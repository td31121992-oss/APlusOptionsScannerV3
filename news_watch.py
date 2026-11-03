"""News watch: raise a Telegram alert when a news story hits a watched theme that can move a group of F&O stocks.

Reads the news collector's headlines (data/news_intelligence/events.jsonl) and matches each rule's keywords:
a rule fires when a headline/summary contains ANY topic word AND ANY company word. One alert per rule per day (the
first matching headline), with a count of further matches. Alerts are informational only: they are sent to Telegram and
logged to data/news_intelligence/news_watch_alerts.csv. They never touch the scanner or the safety gate.
Quiet hours (23:00-07:00 IST): matches are queued and sent after 07:00.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, time as clock, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")
QUIET_START, QUIET_END = clock(23, 0), clock(7, 0)
MAX_AGE = timedelta(hours=36)
IT_SYMBOLS = ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTM", "COFORGE", "PERSISTENT", "MPHASIS", "KPITTECH", "TATAELXSI", "OFSS"]

RULES: list[dict[str, Any]] = [
    {"key": "US_VISA_POLICY", "title": "US visa / PERM / H-1B policy",
     "topics": ["perm program", "perm filings", "perm applications", "labour certification", "labor certification", "h-1b", "h1b", "green card",
                "visa fraud", "visa curbs", "visa restriction", "visa suspension", "work visa", "immigration"],
     "companies": ["tcs", "tata consultancy", "infosys", "wipro", "hcl", "tech mahindra", "cognizant", "capgemini", "ltimindtree",
                   "coforge", "persistent", "mphasis", "indian it", "it stocks", "it firms", "it companies", "nifty it", "outsourcing"],
     "symbols": IT_SYMBOLS},
]


def _in_quiet(now: datetime) -> bool:
    t = now.time()
    return t >= QUIET_START or t < QUIET_END


def match_event(event: dict[str, Any], rule: dict[str, Any]) -> bool:
    text = f"{event.get('title', '')} {event.get('summary', '')}".lower()
    return any(t in text for t in rule["topics"]) and any(c in text for c in rule["companies"])


def _published(event: dict[str, Any]) -> datetime | None:
    try:
        return parsedate_to_datetime(str(event.get("published_at_raw", ""))).astimezone(IST)
    except (TypeError, ValueError):
        return None


def _load_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"seen": [], "alerted": {}, "pending": []}


def format_alert(rule: dict[str, Any], first: dict[str, Any], extra: int) -> str:
    when = first.get("time", "")
    lines = [f"📰 News watch: {rule['title']}", "", str(first.get("title", ""))[:220], f"({first.get('source', '')}, {when})"]
    if extra > 0:
        lines.append(f"+ {extra} more headline(s) on the same theme")
    lines += ["", "May affect: " + ", ".join(rule["symbols"]), "Informational only - check the pre-open gap before acting."]
    return "\n".join(lines)


def scan(now: datetime | None = None, send: Callable[[str], tuple[bool, str]] | None = None, dry_run: bool = False,
         base: Path = ROOT) -> dict[str, Any]:
    now = now or datetime.now(IST)
    news_dir = base / "data" / "news_intelligence"
    state_path = news_dir / "news_watch_state.json"
    state = _load_state(state_path)
    seen = set(state.get("seen", []))
    found: dict[str, list[dict[str, Any]]] = {}
    try:
        lines = (news_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[-800:]
    except OSError:
        return {"matched": 0, "sent": 0, "queued": 0, "error": "no news file"}
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        eid = str(ev.get("event_id", ""))
        when = _published(ev)
        if not eid or eid in seen or when is None or now - when > MAX_AGE or when > now + timedelta(hours=1):
            continue
        for rule in RULES:
            if match_event(ev, rule):
                found.setdefault(rule["key"], []).append({"title": ev.get("title", ""), "source": ev.get("source", ""),
                                                          "time": when.strftime("%d %b %H:%M"), "id": eid})
        seen.add(eid)
    today = now.date().isoformat()
    pending: list[dict[str, Any]] = list(state.get("pending", []))
    for rule in RULES:
        hits = found.get(rule["key"], [])
        if hits and state.get("alerted", {}).get(rule["key"]) != today:
            pending.append({"rule": rule["key"], "first": hits[0], "extra": len(hits) - 1, "queued_at": now.isoformat()})
            state.setdefault("alerted", {})[rule["key"]] = today
    sent = 0
    rules_by_key = {r["key"]: r for r in RULES}
    if not _in_quiet(now) and pending:
        keep = []
        for item in pending:
            rule = rules_by_key.get(item["rule"])
            if not rule:
                continue
            msg = format_alert(rule, item["first"], int(item.get("extra", 0)))
            if dry_run or send is None:
                keep.append(item)
                continue
            ok, _ = send(msg)
            if ok:
                sent += 1
                news_dir.mkdir(parents=True, exist_ok=True)
                log = news_dir / "news_watch_alerts.csv"
                new = not log.exists()
                with log.open("a", newline="", encoding="utf-8") as handle:
                    w = csv.writer(handle)
                    if new:
                        w.writerow(["sent_at", "rule", "symbols", "headline", "source", "extra_headlines"])
                    w.writerow([now.isoformat(), item["rule"], " ".join(rule["symbols"]), item["first"]["title"], item["first"]["source"], item.get("extra", 0)])
            else:
                keep.append(item)
        pending = keep
    state["seen"] = list(seen)[-3000:]
    state["pending"] = pending
    if not dry_run:
        news_dir.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), encoding="utf-8")
    return {"matched": sum(len(v) for v in found.values()), "sent": sent, "queued": len(pending)}
