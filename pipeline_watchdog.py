"""Pipeline freshness watchdog (read-only; no trading effect).

A scheduled task that crashes inside a try/except still reports "success", so exit codes cannot tell you a job has stopped. This checks the one thing that cannot be faked: did each job's
OUTPUT get written after the last session that was due? (On 10 Nov 2026 the shadow scoreboard turned out to be 4 trading days stale and six shadow reviews 5 days stale, with every task green.)

For each check the "due day" is the most recent trading day (weekends and NSE holidays skipped, via trading_calendar) whose deadline for that output has already passed. A check is OK when the
output was written after that day's close, otherwise it is STALE (older than the close) or MISSING, and the message says how many trading days behind it is.

    data/pipeline_health.json        machine-readable result of the last run
    data/pipeline_health.md          the same as a readable list
    Telegram                         only when the set of failures changes (new failure, or all clear), through the same CAlphaTrader sender the 09:10 health message uses

    python pipeline_watchdog.py [--no-telegram]       exit code 1 when anything is failing

To add a job, add one line to checks(); nothing else needs to change.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parent
CLOSE = time(15, 25)                                         # an output written after this on the due day came from that day's session


@dataclass(frozen=True)
class Check:
    name: str
    path: str                                                # relative to the project root; {day} is replaced by the due day (YYYY-MM-DD)
    deadline: time                                           # by this time of day the output for that day should exist
    kind: str = "file"                                       # "file": that file; "dir": the newest file anywhere under that folder
    written_after: time | None = CLOSE                       # the write must be later than this time on the due day (None: any time that day is enough)


def checks() -> list[Check]:
    return [
        Check("Scanner health file", "data/intraday_movement/scanner_runtime_health.json", time(15, 45)),
        Check("Intraday report", "data/reports/intraday_movement_latest.json", time(15, 45)),
        Check("Paper trade history", "data/reports/paper_trade_history.json", time(15, 45)),
        Check("Missed-opportunity signals", "data/missed_opportunities/{day}/signals.csv", time(16, 15), written_after=None),
        Check("Option returns (missed opportunities)", "data/missed_opportunities/{day}/option_returns.json", time(17, 30), written_after=None),
        Check("Trade archive", "data/trade_archive/{day}.json", time(16, 50), written_after=None),
        Check("Integrity report", "data/trade_archive/integrity_{day}.md", time(16, 50), written_after=None),
        Check("Shadow scoreboard", "data/shadow_scoreboard/{day}.md", time(16, 50), written_after=None),
        Check("Daily indicators", "data/reports/daily_indicators.json", time(18, 0), written_after=time(17, 25)),
        Check("Shadow review: put_continuation", "data/shadow_rules/put_continuation", time(17, 30), "dir"),
        Check("Shadow review: pivot_review", "data/shadow_rules/pivot_review", time(17, 30), "dir"),
        Check("Shadow review: sector_leader_puts", "data/shadow_rules/sector_leader_puts", time(17, 30), "dir"),
        Check("Shadow review: big_movers", "data/shadow_rules/big_movers", time(17, 30), "dir"),
        Check("Shadow review: early_movers", "data/shadow_rules/early_movers", time(17, 30), "dir"),
        Check("Shadow review: event_reaction", "data/shadow_rules/event_reaction", time(17, 30), "dir"),
        Check("Shadow review: early_entry", "data/shadow_rules/early_entry", time(17, 30), "dir"),
        Check("Premium tracker", "data/premium_tracker", time(17, 30), "dir"),
        Check("Pattern log", "data/pattern_log", time(17, 30), "dir"),
        Check("Pattern log candles", "data/pattern_log/candles", time(17, 30), "dir"),
    ]


def is_trading_day(d: date) -> bool:
    try:
        from trading_calendar import is_trading_day as _is

        return bool(_is(d)[0])
    except Exception:                                        # noqa: BLE001 - without the calendar fall back to weekdays only
        return d.weekday() < 5


def due_day(now: datetime, deadline: time, trading: Callable[[date], bool] = is_trading_day) -> date:
    """The most recent trading day whose `deadline` has already passed."""
    d = now.date()
    if not (trading(d) and now.time() >= deadline):
        d -= timedelta(days=1)
        while not trading(d):
            d -= timedelta(days=1)
    return d


def trading_days_between(older: date, newer: date, trading: Callable[[date], bool] = is_trading_day) -> int:
    n, d = 0, older
    while d < newer:
        d += timedelta(days=1)
        n += trading(d)
    return n


def latest_write(path: Path, kind: str) -> datetime | None:
    try:
        if kind == "dir":
            stamps = [p.stat().st_mtime for p in path.rglob("*") if p.is_file()] if path.is_dir() else []
            return datetime.fromtimestamp(max(stamps)) if stamps else None
        return datetime.fromtimestamp(path.stat().st_mtime) if path.is_file() else None
    except OSError:
        return None


def evaluate(check: Check, now: datetime, root: Path = ROOT, trading: Callable[[date], bool] = is_trading_day) -> dict[str, str]:
    day = due_day(now, check.deadline, trading)
    path = root / check.path.replace("{day}", day.isoformat())
    wrote = latest_write(path, check.kind)
    result = {"name": check.name, "due_day": day.isoformat(), "status": "OK", "detail": ""}
    if wrote is None:
        result.update(status="MISSING", detail=f"nothing found for {day.isoformat()} ({check.path.replace('{day}', day.isoformat())})")
        return result
    needed = datetime.combine(day, check.written_after) if check.written_after else datetime.combine(day, time(0, 0))
    if "{day}" not in check.path and check.written_after is None:
        needed = datetime.combine(day, time(0, 0))
    if wrote < needed:
        behind = trading_days_between(wrote.date(), day, trading)
        result.update(status="STALE", detail=f"last written {wrote:%d %b %H:%M}, {behind} trading day(s) behind (needs a write after {needed:%d %b %H:%M})")
    else:
        result["detail"] = f"written {wrote:%d %b %H:%M}"
    return result


def run_checks(now: datetime, root: Path = ROOT, items: Sequence[Check] | None = None) -> list[dict[str, str]]:
    return [evaluate(c, now, root) for c in (items if items is not None else checks())]


def render(now: datetime, results: Sequence[dict[str, str]]) -> str:
    bad = [r for r in results if r["status"] != "OK"]
    lines = [f"# Pipeline health - {now:%Y-%m-%d %H:%M}", "", f"{len(results) - len(bad)} of {len(results)} outputs are current." + ("" if bad else " Nothing is stale."), ""]
    if bad:
        lines += ["## Not current", ""] + [f"- **{r['name']}** - {r['status']}: {r['detail']}" for r in bad] + [""]
    lines += ["## Current", ""] + [f"- {r['name']} - {r['detail']}" for r in results if r["status"] == "OK"]
    return "\n".join(lines) + "\n"


def alert_text(now: datetime, results: Sequence[dict[str, str]]) -> str:
    bad = [r for r in results if r["status"] != "OK"]
    if not bad:
        return f"APlus pipeline check {now:%d %b %H:%M}: all {len(results)} outputs are current."
    return f"APlus pipeline check {now:%d %b %H:%M}: {len(bad)} output(s) NOT current\n" + "\n".join(f"- {r['name']}: {r['detail']}" for r in bad[:12])


def send_telegram(message: str) -> tuple[bool, str]:
    try:
        sys.path.insert(0, str(ROOT / "tools" / "self_healing_watchdog"))
        import telegram_health_check

        return telegram_health_check.send(message)
    except Exception as exc:                                 # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:200]}"


def run(now: datetime | None = None, root: Path = ROOT, telegram: bool = True) -> int:
    now = now or datetime.now()
    results = run_checks(now, root)
    bad = sorted(r["name"] for r in results if r["status"] != "OK")
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "pipeline_health.json").write_text(json.dumps({"checked_at": now.isoformat(timespec="seconds"), "failing": bad, "results": results}, indent=1), encoding="utf-8")
    (data / "pipeline_health.md").write_text(render(now, results), encoding="utf-8")
    state_path = data / "pipeline_health_state.json"
    try:
        last = json.loads(state_path.read_text(encoding="utf-8")).get("failing", [])
    except (OSError, ValueError):
        last = []
    for r in results:
        if r["status"] != "OK":
            print(f"{r['status']:8s} {r['name']}: {r['detail']}")
    print(f"{len(results) - len(bad)}/{len(results)} outputs current")
    if telegram and bad != sorted(last):                     # only when the set of failures changes, so a long outage does not repeat every run
        ok, detail = send_telegram(alert_text(now, results))
        print("telegram:", "sent" if ok else f"NOT sent ({detail[:120]})")
        if ok:
            state_path.write_text(json.dumps({"failing": bad, "sent_at": now.isoformat(timespec="seconds")}), encoding="utf-8")
    elif not telegram:
        pass
    return 1 if bad else 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(run(telegram="--no-telegram" not in sys.argv))
