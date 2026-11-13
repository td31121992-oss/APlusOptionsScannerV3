"""Facts for the AI Supervisor (read-only; no trading effect, nothing here changes a setting or a trade).

The Supervisor is a Claude session scheduled in the Claude app. It does not fetch or compute anything itself: it reads the compact facts written here, judges them, and writes a review.
Keeping the numbers in code (not in the model's head) makes every figure in a review checkable.

    python supervisor_facts.py evening [YYYY-MM-DD]     after the close: the day's scanner health, trades, peaks, exits, forward experiments, pipeline and system checks
    python supervisor_facts.py morning                  before the open: is everything ready (calendar, data, pre-flight, scanner, last night's issues)

Writes data/ai_supervisor/facts_<kind>_<day>.json (everything) and facts_<kind>_<day>.md (the same, readable).
Experiments (what we are testing forward, with the pass mark fixed in advance) are listed in ai_supervisor/experiments.json (versioned; the outputs go to data/ai_supervisor).
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import statistics as st
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "ai_supervisor"
MIN_SESSIONS, MIN_TRADES, MIN_BLOCKED, MIN_BLOCKED_DAYS, POSITIVE_DAYS_SHARE = 10, 100, 30, 8, 0.6    # the pass marks, fixed in advance


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------------------------------------------- scanner log
def scanner_day(day: str, root: Path = ROOT) -> dict[str, Any]:
    """What the scanner log says about one day."""
    path = root / "logs" / "scanner.log"
    c: Counter[str] = Counter()
    starts, errors = [], Counter()
    first = last = None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"error": "scanner.log not readable"}
    for line in lines:
        if not line.startswith(day):
            continue
        t = line[11:19]
        first, last = first or t, t
        if "Intraday movement cycle phase" in line:
            c["cycles"] += 1
        if "Continuous Intraday Movement Scanner started" in line:
            starts.append(t)
        if "Another intraday scanner instance" in line:
            c["duplicate_launches_blocked"] += 1
        if "cycle failed" in line.lower():
            c["failed_cycles"] += 1
        if re.search(r"ConnectTimeout|ConnectionError|Max retries", line):
            c["network_errors"] += 1
        if re.search(r"authoriz.*(fail|latch)|AUTHORIZATION_FAILED", line, re.I):
            c["auth_problems"] += 1
        if re.search(r"\bDhan\b", line) and "no Dhan" not in line and "08:55" <= t[:5] <= "15:45":                      # market hours only: tests run later in the evening write to the same log
            c["dhan_mentions"] += 1
        if " ERROR " in line:
            c["errors"] += 1
            errors[re.sub(r"\d+", "N", line[20:110])] += 1
    return {"first_line": first, "last_line": last, "scanner_starts": starts, **dict(c), "top_errors": errors.most_common(4)}


# ---------------------------------------------------------------------------------------------------------------- trades
def trades_day(day: str, history: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [t for t in history if str(t.get("entry_time"))[:10] == day]
    closed = [t for t in rows if str(t.get("status")).upper() == "CLOSED" and _f(t.get("net_pnl")) is not None]
    if not closed:
        return {"trades": len(rows), "closed": 0}
    pnl = [float(t["net_pnl"]) for t in closed]
    peak = [max(0.0, _f(t.get("mfe_amount")) or 0.0) for t in closed]
    pick = lambda t: {"symbol": t.get("symbol"), "side": t.get("option_type"), "entry": str(t.get("entry_time"))[11:16], "net": round(float(t["net_pnl"])),       # noqa: E731
                      "peak": round(max(0.0, _f(t.get("mfe_amount")) or 0.0)), "exit": t.get("exit_reason")}
    ranked = sorted(closed, key=lambda t: float(t["net_pnl"]))
    return {"trades": len(rows), "closed": len(closed), "open": len(rows) - len(closed), "net": round(sum(pnl)), "winners": sum(1 for x in pnl if x > 0), "losers": sum(1 for x in pnl if x <= 0),
            "winners_net": round(sum(x for x in pnl if x > 0)), "losers_net": round(sum(x for x in pnl if x <= 0)), "never_in_profit": sum(1 for x in peak if x <= 0),
            "touched_3k": sum(1 for x in peak if x >= 3000), "touched_5k": sum(1 for x in peak if x >= 5000), "sum_of_peaks": round(sum(peak)), "best_peak": round(max(peak)),
            "exit_reasons": Counter(t.get("exit_reason") for t in closed).most_common(), "worst_3": [pick(t) for t in ranked[:3]], "best_3": [pick(t) for t in ranked[-3:][::-1]],
            "opt5_recorded": sum(1 for t in closed if t.get("opt5")), "sector_labels": Counter(t.get("sf_sector") for t in closed).most_common(4)}


def blackouts(day: str, root: Path = ROOT, gap_seconds: int = 30) -> dict[str, Any]:
    """Minutes during which at least one OPEN position received no price (gaps over `gap_seconds` between consecutive OPEN rows of the per-trade option tape)."""
    spans: list[tuple[datetime, datetime]] = []
    folder = root / "data" / "option_trade_tape" / day
    for f in sorted(folder.glob("*.csv")) if folder.is_dir() else []:
        prev = None
        try:
            with f.open(encoding="utf-8-sig", newline="") as h:
                for r in csv.DictReader(h):
                    if str(r.get("status")).upper() != "OPEN":
                        prev = None
                        continue
                    t = datetime.fromisoformat(r["timestamp"])
                    if prev is not None and (t - prev).total_seconds() > gap_seconds:
                        spans.append((prev, t))
                    prev = t
        except (OSError, ValueError, KeyError):
            continue
    spans.sort()
    merged: list[list[datetime]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    mins = sum((b - a).total_seconds() for a, b in merged) / 60
    return {"windows": len(merged), "minutes": round(mins), "share_of_session_pct": round(100 * mins / 375), "longest_min": round(max(((b - a).total_seconds() / 60 for a, b in merged), default=0), 1),
            "windows_list": [f"{a.strftime('%H:%M')}-{b.strftime('%H:%M')}" for a, b in merged[:20]]}


def capture_day(day: str, history: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Peak profit vs kept, split so that it can be acted on: winners vs losers, and give-back by exit reason. (A single 'kept %' over all trades is misleading: a loser's peak can rarely be captured.)
    Also the stop fall-through (stop price minus fill, for plain stop-loss exits) and the three biggest give-backs."""
    rows = [t for t in history if str(t.get("entry_time"))[:10] == day and str(t.get("status")).upper() == "CLOSED" and _f(t.get("net_pnl")) is not None]
    if not rows:
        return {}
    peak = lambda t: max(0.0, _f(t.get("mfe_amount")) or 0.0)           # noqa: E731
    wins, loss = [t for t in rows if float(t["net_pnl"]) > 0], [t for t in rows if float(t["net_pnl"]) <= 0]
    wpk, wnet = sum(peak(t) for t in wins), sum(float(t["net_pnl"]) for t in wins)
    by: dict[str, list[float]] = defaultdict(lambda: [0, 0.0, 0.0])
    for t in rows:
        b = by[str(t.get("exit_reason"))]
        b[0] += 1
        b[1] += peak(t)
        b[2] += float(t["net_pnl"])
    slip = 0.0
    for t in rows:
        stop, fill, qty = _f(t.get("option_stop")), _f(t.get("exit_price")), _f(t.get("quantity"))
        if t.get("exit_reason") == "OPTION_STOP_LOSS" and stop and fill and qty and fill < stop:
            slip += (stop - fill) * qty
    worst = sorted(rows, key=lambda t: peak(t) - float(t["net_pnl"]), reverse=True)[:3]
    return {"winners_peak": round(wpk), "winners_kept": round(wnet), "winners_kept_pct": round(100 * wnet / wpk) if wpk else None,
            "losers": len(loss), "losers_peak": round(sum(peak(t) for t in loss)), "losers_net": round(sum(float(t["net_pnl"]) for t in loss)),
            "giveback_by_exit": [{"exit": k, "trades": int(v[0]), "peaks": round(v[1]), "net": round(v[2]), "given_back": round(v[1] - v[2])} for k, v in sorted(by.items(), key=lambda x: x[1][2] - x[1][1])],
            "stop_fall_through_rs": round(slip), "biggest_giveback": [{"symbol": t.get("symbol"), "peak": round(peak(t)), "net": round(float(t["net_pnl"])), "exit": t.get("exit_reason")} for t in worst]}


def history_summary(history: Sequence[Mapping[str, Any]], upto: str, sessions: int = 10) -> dict[str, Any]:
    by: dict[str, float] = defaultdict(float)
    for t in history:
        d = str(t.get("entry_time"))[:10]
        if d <= upto and str(t.get("status")).upper() == "CLOSED" and _f(t.get("net_pnl")) is not None:
            by[d] += float(t["net_pnl"])
    days = sorted(by)
    return {"sessions_total": len(days), "net_total": round(sum(by.values())), "last_sessions": [(d, round(by[d])) for d in days[-sessions:]],
            "positive_sessions_last_10": sum(1 for d in days[-10:] if by[d] > 0)}


# ---------------------------------------------------------------------------------------------------------------- experiments
def load_experiments(root: Path = ROOT) -> list[dict[str, Any]]:
    try:
        return json.loads((root / "ai_supervisor" / "experiments.json").read_text(encoding="utf-8")).get("experiments", [])
    except (OSError, ValueError):
        return []


def variant_status(exp: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """Forward-only result of an exit / entry variant (trade_archive/exit_variants.csv): the days after the experiment's registration day."""
    path = root / "data" / "trade_archive" / "exit_variants.csv"
    rows = []
    try:
        with path.open(encoding="utf-8", newline="") as h:
            rows = [r for r in csv.DictReader(h) if r["variant"] == exp["key"] and r["day"] > exp["registered"]]
    except OSError:
        pass
    days, trades = len(rows), sum(int(r["trades"]) for r in rows)
    change = sum(float(r["variant_net"]) - float(r["real_net"]) for r in rows)
    pos = sum(1 for r in rows if float(r["variant_net"]) > float(r["real_net"]))
    out = {"forward_sessions": days, "forward_trades": trades, "live_net": round(sum(float(r["real_net"]) for r in rows)), "variant_net": round(sum(float(r["variant_net"]) for r in rows)),
           "change": round(change), "positive_days": pos}
    enough = days >= MIN_SESSIONS and trades >= MIN_TRADES
    out["status"] = "COLLECTING" if not enough else ("READY: meets the pass mark" if change > 0 and pos / days >= POSITIVE_DAYS_SHARE else "READY: fails the pass mark")
    return out


_TRADES: dict[str, list[dict[str, Any]]] = {}


def gate_status(exp: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """Forward-only result of a shadow rule (blocked vs allowed trades) from the scoreboard registry."""
    sys.path.insert(0, str(root))
    import shadow_scoreboard as sb

    key = str(root)
    if key not in _TRADES:                                 # loaded and enriched once for all experiments: the tick files behind the derived tags take minutes to read
        trades = sb.load_trades(root / "data" / "reports" / "paper_trade_history.json", upto=date.today().isoformat())
        sb.add_canary(trades)
        try:
            import derived_tags

            derived_tags.enrich(trades, root)
        except Exception:                                  # noqa: BLE001
            pass
        _TRADES[key] = trades
    trades = _TRADES[key]
    registry = {exp["key"]: exp["registered"]}
    rows = sb.forward_rows(trades, registry)
    if not rows:
        return {"status": "COLLECTING", "forward_blocked": 0}
    r = rows[0]
    n, days = r["blocked"]["n"], r["days_blocked"]
    change = -float(r["blocked"]["net"] or 0)
    out = {"forward_blocked": n, "forward_blocked_days": days, "blocked_net": r["blocked"]["net"], "allowed_n": r["allowed"]["n"], "allowed_net": r["allowed"]["net"],
           "change_if_enforced": round(change), "days_helped": r["days_helped"], "scoreboard_verdict": r["verdict"]}
    enough = n >= MIN_BLOCKED and days >= MIN_BLOCKED_DAYS
    out["status"] = "COLLECTING" if not enough else ("READY: meets the pass mark" if change > 0 and r["days_helped"] / max(1, days) >= POSITIVE_DAYS_SHARE else "READY: fails the pass mark")
    return out


def experiments_status(root: Path = ROOT) -> list[dict[str, Any]]:
    out = []
    for exp in load_experiments(root):
        try:
            res = variant_status(exp, root) if exp.get("kind") == "variant" else gate_status(exp, root)
        except Exception as exc:                           # noqa: BLE001 - one broken experiment must not hide the others
            res = {"status": f"ERROR: {type(exc).__name__}: {str(exc)[:80]}"}
        out.append({"id": exp.get("id"), "name": exp.get("name"), "registered": exp.get("registered"), "note": exp.get("note", ""), **res})
    return out


# ---------------------------------------------------------------------------------------------------------------- pipeline and system
def pipeline(now: datetime, root: Path = ROOT) -> dict[str, Any]:
    import pipeline_watchdog as pw

    res = pw.run_checks(now, root)
    return {"outputs": len(res), "current": sum(1 for r in res if r["status"] == "OK"), "not_current": [f"{r['name']}: {r['detail']}" for r in res if r["status"] != "OK"]}


def scheduled_tasks() -> list[str]:
    """APlus tasks whose last run did not return 0 (Windows Task Scheduler)."""
    cmd = ("Get-ScheduledTask | Where-Object { $_.TaskName -like 'APlus*' -and $_.State -ne 'Disabled' } | ForEach-Object { $i = Get-ScheduledTaskInfo $_; "
           "if ($i.LastTaskResult -ne 0 -and $i.LastTaskResult -ne 267009 -and $i.LastTaskResult -ne 267011) { $_.TaskName + ' result ' + $i.LastTaskResult + ' at ' + $i.LastRunTime } }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60).stdout
        return [x.strip() for x in out.splitlines() if x.strip()]
    except Exception as exc:                               # noqa: BLE001
        return [f"could not read the task list: {type(exc).__name__}"]


def system(root: Path = ROOT) -> dict[str, Any]:
    out: dict[str, Any] = {"disk_free_gb": round(shutil.disk_usage(root).free / 1e9, 1), "tasks_not_ok": scheduled_tasks()}
    smap = root / "data" / "reference" / "fno_sector_map.csv"
    if smap.exists():
        with smap.open(encoding="utf-8-sig", newline="") as h:
            labels = [r["sector"] for r in csv.DictReader(h)]
        out["sector_map"] = {"stocks": len(labels), "unclassified": sum(1 for x in labels if x == "UNCLASSIFIED"), "age_days": (date.today() - date.fromtimestamp(smap.stat().st_mtime)).days}
    try:
        h = json.loads((root / "data" / "intraday_movement" / "scanner_runtime_health.json").read_text(encoding="utf-8"))
        out["scanner_health"] = {"status": h.get("status"), "updated_at": h.get("updated_at"), "authorization_validation_required": h.get("authorization_validation_required")}
    except (OSError, ValueError):
        out["scanner_health"] = "not readable"
    return out


def calendar(day: str) -> dict[str, Any]:
    try:
        from trading_calendar import is_trading_day

        ok, why = is_trading_day(date.fromisoformat(day))
        return {"is_trading_day": ok, "reason": why}
    except Exception as exc:                               # noqa: BLE001
        return {"is_trading_day": None, "reason": f"{type(exc).__name__}"}


def preflight(root: Path = ROOT) -> dict[str, Any]:
    """Run the pre-flight check (read-only, a few quotes / candles) and report pass / fail with its last lines."""
    py = root / ".venv" / "Scripts" / "python.exe"
    try:
        p = subprocess.run([str(py), str(root / "aplus_preflight_check.py")], capture_output=True, text=True, timeout=120, cwd=str(root))
        tail = [x for x in (p.stdout + p.stderr).splitlines() if x.strip()][-3:]
        return {"passed": p.returncode == 0 and "PRE-FLIGHT COMPLETE" in p.stdout, "last_lines": tail}
    except Exception as exc:                               # noqa: BLE001
        return {"passed": False, "last_lines": [f"{type(exc).__name__}: {str(exc)[:100]}"]}


# ---------------------------------------------------------------------------------------------------------------- bundles
def evening(day: str, root: Path = ROOT) -> dict[str, Any]:
    import trade_archive

    history = trade_archive.load_history(root / "data" / "reports" / "paper_trade_history.json")
    return {"kind": "evening", "day": day, "generated_at": datetime.now().isoformat(timespec="seconds"), "calendar": calendar(day), "scanner": scanner_day(day, root),
            "trades": trades_day(day, history), "capture": capture_day(day, history), "price_blackouts": blackouts(day, root), "history": history_summary(history, day), "experiments": experiments_status(root),
            "pipeline": pipeline(datetime.now(), root), "system": system(root)}


def morning(day: str, root: Path = ROOT) -> dict[str, Any]:
    import trade_archive

    history = trade_archive.load_history(root / "data" / "reports" / "paper_trade_history.json")
    prior = sorted({str(t.get("entry_time"))[:10] for t in history if str(t.get("entry_time"))[:10] < day})
    return {"kind": "morning", "day": day, "generated_at": datetime.now().isoformat(timespec="seconds"), "calendar": calendar(day), "preflight": preflight(root),
            "system": system(root), "pipeline": pipeline(datetime.now(), root), "last_session": {"day": prior[-1] if prior else None, **(trades_day(prior[-1], history) if prior else {})},
            "history": history_summary(history, day), "experiments": experiments_status(root)}


def render(facts: Mapping[str, Any]) -> str:
    return f"# Supervisor facts: {facts['kind']} {facts['day']}\n\n```json\n{json.dumps(facts, indent=1, default=str)}\n```\n"


def main() -> int:
    kind = sys.argv[1] if len(sys.argv) > 1 else "evening"
    day = sys.argv[2] if len(sys.argv) > 2 else date.today().isoformat()
    facts = morning(day) if kind == "morning" else evening(day)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"facts_{kind}_{day}.json").write_text(json.dumps(facts, indent=1, default=str), encoding="utf-8")
    (OUT / f"facts_{kind}_{day}.md").write_text(render(facts), encoding="utf-8")
    print(f"written: data/ai_supervisor/facts_{kind}_{day}.json / .md")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
