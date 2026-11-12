"""Nightly trade archive, integrity check and rule history (read-only; no trading effect).

paper_trade_history.json is one big file that is rewritten all day, and paper_trade_journal.json holds only the current day. Both are single points of loss and neither says whether a
day's data is trustworthy. This job, run once after the close, does three things so the shadow rules can be judged on records that are kept and checked:

    1. Archive   data/trade_archive/<day>.json        every trade entered that day (all fields, all shadow tags), with a count and a SHA-256. Written once: if the day is archived again
                                                      and the data differs, the new copy goes to <day>.r2.json, <day>.r3.json ... so an earlier record is never overwritten.
    2. Integrity data/trade_archive/integrity_<day>.md   duplicate trade ids or entries, trades still OPEN after the close, closed trades without exit / P&L, entries outside 09:15-15:30,
                                                      impossible prices or quantities; plus a note where the sector / regime shadow tags are on only some of the day's trades.
    3. Rule history  data/trade_archive/rule_history.csv  one row per rule per day from shadow_scoreboard (blocked vs allowed, net Rs, cumulative), append-only by day, so a rule's
                                                      record can be read as a trend instead of as the latest snapshot.

    python trade_archive.py [YYYY-MM-DD]      day = the trading day (default today)
    python trade_archive.py --backfill        archive + check every day found in the history (first run), then rule history for the latest day

The shadow scoreboard itself is run from here too, so it no longer depends on the missed-opportunity job finishing first.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / "data" / "reports" / "paper_trade_history.json"
ARCHIVE = ROOT / "data" / "trade_archive"
SESSION_START, SESSION_END = "09:15", "15:30"
TAG_FIELDS = ("sf_would_block", "rgs_would_block", "sf_focus_block", "sf_stack_block")      # the sector / regime shadow tags


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _day(t: Mapping[str, Any]) -> str:
    return str(t.get("entry_time") or "")[:10]


def load_history(path: Path = HISTORY) -> list[dict[str, Any]]:
    try:
        return list(json.loads(path.read_text(encoding="utf-8")).get("paper_trades") or [])
    except (OSError, ValueError):
        return []


def trades_for(day: str, history: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = [dict(t) for t in history if _day(t) == day]
    out.sort(key=lambda t: (str(t.get("entry_time")), str(t.get("paper_trade_id"))))
    return out


def _digest(trades: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(list(trades), sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()


def archive_day(day: str, trades: Sequence[Mapping[str, Any]], folder: Path = ARCHIVE, now: datetime | None = None) -> tuple[Path, str]:
    """Write the day's trades once. Returns (path, "written" | "unchanged" | "revision"). Never overwrites an earlier copy."""
    folder.mkdir(parents=True, exist_ok=True)
    digest = _digest(trades)
    copies = sorted(folder.glob(f"{day}.json")) + sorted(folder.glob(f"{day}.r*.json"))
    for p in copies:
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("sha256") == digest:
                return p, "unchanged"
        except (OSError, ValueError):
            continue
    target = folder / f"{day}.json" if not copies else folder / f"{day}.r{len(copies) + 1}.json"
    payload = {"day": day, "written_at": (now or datetime.now()).isoformat(timespec="seconds"), "count": len(trades), "sha256": digest, "trades": list(trades)}
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(target)
    return target, "written" if not copies else "revision"


def integrity(day: str, trades: Sequence[Mapping[str, Any]], today: str | None = None) -> list[str]:
    """Problems found in one day's trades; an empty list means nothing looks wrong."""
    today = today or date.today().isoformat()
    issues: list[str] = []
    ids = Counter(str(t.get("paper_trade_id") or "") for t in trades)
    if ids.get(""):
        issues.append(f"{ids['']} trade(s) have no paper_trade_id")
    dup = sorted(k for k, v in ids.items() if k and v > 1)
    if dup:
        issues.append(f"duplicate paper_trade_id: {', '.join(dup[:5])}")
    key = Counter((t.get("symbol"), t.get("option_security_id"), str(t.get("entry_time"))[:16]) for t in trades)
    dup_entry = [f"{k[0]} @ {k[2][11:]}" for k, v in key.items() if v > 1]
    if dup_entry:
        issues.append(f"same contract entered twice in the same minute: {', '.join(dup_entry[:5])}")
    still_open = [t for t in trades if str(t.get("status")).upper() == "OPEN"]
    if still_open and day < today:
        issues.append(f"{len(still_open)} trade(s) still OPEN after the session: {', '.join(str(t.get('symbol')) for t in still_open[:6])}")
    for t in trades:
        sym = t.get("symbol")
        if str(t.get("status")).upper() == "CLOSED":
            if not t.get("exit_time"):
                issues.append(f"{sym}: CLOSED but no exit_time")
            if _f(t.get("net_pnl")) is None:
                issues.append(f"{sym}: CLOSED but no net_pnl")
        hhmm = str(t.get("entry_time") or "")[11:16]
        if hhmm and not (SESSION_START <= hhmm <= SESSION_END):
            issues.append(f"{sym}: entry at {hhmm} is outside {SESSION_START}-{SESSION_END}")
        if (_f(t.get("entry_price")) or 0) <= 0 or (_f(t.get("quantity")) or 0) <= 0:
            issues.append(f"{sym}: entry_price or quantity is not positive")
    return issues


def tag_notes(trades: Sequence[Mapping[str, Any]]) -> list[str]:
    """Shadow tags that are on some of the day's trades but not all. A tag on none of them just did not exist yet; a gap is normal where the stock's sector is not ranked
    (fewer than 4 F&O stocks, or UNCLASSIFIED), so these are notes, not integrity problems."""
    notes = []
    for field in TAG_FIELDS:
        have = sum(1 for t in trades if str(t.get(field)).strip().lower() not in ("", "none", "nan"))
        if 0 < have < len(trades):
            notes.append(f"shadow tag {field} present on {have}/{len(trades)} trades")
    return notes


def render_integrity(day: str, trades: Sequence[Mapping[str, Any]], issues: Sequence[str], archived: str, history_open: int, notes: Sequence[str] = ()) -> str:
    pnl = [x for x in (_f(t.get("net_pnl")) for t in trades) if x is not None]
    lines = [f"# Trade archive and integrity - {day}", "",
             f"- Trades entered: {len(trades)}   closed: {sum(1 for t in trades if str(t.get('status')).upper() == 'CLOSED')}   net P&L (closed): Rs {sum(pnl):,.0f}",
             f"- Archive: {archived}",
             f"- OPEN rows left in the whole history from earlier days: {history_open}", ""]
    lines += ["## Integrity", ""] + ([f"- {i}" for i in issues] if issues else ["- Nothing wrong found."])
    if notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    return "\n".join(lines) + "\n"


def rule_history_rows(day: str, gates: Sequence[Mapping[str, Any]]) -> list[list[Any]]:
    return [[day, g["rule"], g["trades_with_data"], g["blocked"]["n"], g["blocked"]["net"], g["allowed"]["n"], g["allowed"]["net"], g["change_if_enforced"], g["days_helped"],
             g["days_blocked"], int(g["enough"])] for g in gates]


RULE_HEADER = ["day", "rule", "trades_with_data", "blocked_n", "blocked_net", "allowed_n", "allowed_net", "change_if_enforced", "days_helped", "days_blocked", "enough"]


def write_rule_history(day: str, gates: Sequence[Mapping[str, Any]], path: Path) -> None:
    """Replace this day's rows (re-running a day is safe) and keep every other day as it was."""
    keep: list[list[str]] = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as h:
            keep = [r for r in csv.reader(h) if r and r[0] not in (day, "day")]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.writer(h)
        w.writerow(RULE_HEADER)
        w.writerows(keep)
        w.writerows(rule_history_rows(day, gates))


EXIT_HEADER = ["day", "variant", "trades", "real_net", "variant_net"]
FORWARD_FROM = "2026-11-10"                                  # exit variants were added on this date; "forward" results count trades entered after it


def exit_variant_rows(trades: Sequence[Mapping[str, Any]]) -> list[list[Any]]:
    """One row per (day, variant): trades that have the variant, their real net and the net under the alternative exit ladder."""
    import derived_tags

    out: list[list[Any]] = []
    for day in sorted({str(t.get("_day") or _day(t)) for t in trades}):
        today = [t for t in trades if str(t.get("_day") or _day(t)) == day]
        for name in derived_tags.FORWARD_VARIANTS:
            have = [t for t in today if _f(t.get(name)) is not None and _f(t.get("net_pnl")) is not None]
            if have:
                out.append([day, name, len(have), round(sum(float(t["net_pnl"]) for t in have), 2), round(sum(float(t[name]) for t in have), 2)])
    return out


def write_exit_variants(rows: Sequence[Sequence[Any]], path: Path) -> None:
    """Replace the days present in `rows` (re-running a day is safe) and keep every other day as it was."""
    days = {str(r[0]) for r in rows}
    keep: list[list[str]] = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as h:
            keep = [r for r in csv.reader(h) if r and r[0] not in days and r[0] != "day"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.writer(h)
        w.writerow(EXIT_HEADER)
        w.writerows(sorted(keep + [list(map(str, r)) for r in rows], key=lambda r: (r[0], r[1])))


def render_exit_variants(path: Path) -> str:
    """Totals per variant: forward-only (days after FORWARD_FROM) and over every day that has ticks."""
    if not path.exists():
        return ""
    with path.open(encoding="utf-8", newline="") as h:
        rows = [r for r in csv.DictReader(h)]
    lines = ["# Alternative exit ladders and the 5-minute wait-then-buy entry rule vs the live system (derived; nothing live is changed)", ""]
    for title, sel in (("Forward only (trades entered after " + FORWARD_FROM + ")", [r for r in rows if r["day"] > FORWARD_FROM]), ("All days with ticks (hindsight)", rows)):
        lines += [f"## {title}", "", "| Variant | Days | Trades | Live net Rs | Variant net Rs | Change Rs |", "|---|---|---|---|---|---|"]
        for name in sorted({r["variant"] for r in rows}):
            v = [r for r in sel if r["variant"] == name]
            if v:
                real, var = sum(float(r["real_net"]) for r in v), sum(float(r["variant_net"]) for r in v)
                lines.append(f"| {name} | {len(v)} | {sum(int(r['trades']) for r in v)} | {real:,.0f} | {var:,.0f} | {var - real:+,.0f} |")
        if len(lines) and lines[-1].startswith("|---"):
            lines.append("| (no days yet) | | | | | |")
        lines.append("")
    return "\n".join(lines) + "\n"


def check_day(day: str, history: Sequence[Mapping[str, Any]], root: Path = ROOT) -> tuple[list[dict[str, Any]], list[str]]:
    trades = trades_for(day, history)
    folder = root / "data" / "trade_archive"
    if not trades:
        return trades, []
    path, how = archive_day(day, trades, folder)
    issues = integrity(day, trades)
    stale = sum(1 for t in history if str(t.get("status")).upper() == "OPEN" and _day(t) < date.today().isoformat())
    (folder / f"integrity_{day}.md").write_text(render_integrity(day, trades, issues, f"{path.name} ({how})", stale, tag_notes(trades)), encoding="utf-8")
    return trades, issues


def run(day: str | None = None, root: Path = ROOT, backfill: bool = False) -> int:
    history = load_history(root / "data" / "reports" / "paper_trade_history.json")
    if not history:
        print("no trade history found")
        return 1
    days = sorted({_day(t) for t in history if _day(t)}) if backfill else [day or date.today().isoformat()]
    bad = 0
    for d in days:
        trades, issues = check_day(d, history, root)
        bad += bool(issues)
        print(f"{d}: {len(trades)} trades, {len(issues)} issue(s)")
        for i in issues[:6]:
            print(f"    - {i}")
    last = days[-1]
    try:                                                   # the scoreboard and the rule history; a failure here must not hide the archive that was just written
        import shadow_scoreboard

        trades = shadow_scoreboard.load_trades(root / "data" / "reports" / "paper_trade_history.json", upto=last)
        if trades:
            shadow_scoreboard.add_canary(trades)
            import derived_tags

            derived_tags.enrich(trades, root)
            xrows = exit_variant_rows(trades)
            write_exit_variants(xrows, root / "data" / "trade_archive" / "exit_variants.csv")
            (root / "data" / "trade_archive" / "exit_variants.md").write_text(render_exit_variants(root / "data" / "trade_archive" / "exit_variants.csv"), encoding="utf-8")
            keep = {t["paper_trade_id"]: {k: v for k, v in t.items() if k.startswith("dx_")} for t in trades if t.get("_day") == last and t.get("paper_trade_id")}
            if keep:                                       # keep the day's derived tags: the tick files they come from may be cleaned up later
                (root / "data" / "trade_archive" / f"derived_{last}.json").write_text(json.dumps(keep), encoding="utf-8")
            write_rule_history(last, shadow_scoreboard.gate_rows(trades), root / "data" / "trade_archive" / "rule_history.csv")
            shadow_scoreboard.run(last, root)
            print(f"rule history + scoreboard updated for {last}")
            try:                                           # the record of trades that never went into profit, with a post-mortem each (see never_profit_log.py)
                import never_profit_log

                print(f"never-in-profit record: {len(never_profit_log.run(history, root))} trades")
                import daily_mfe_report

                print(f"daily peak-profit report: {len(daily_mfe_report.run(history, root))} sessions")
                import exit_quality

                print(f"exit quality (what the option did after each exit): {len(exit_quality.run(history, root))} trades")
                import supervisor_facts

                supervisor_facts.OUT.mkdir(parents=True, exist_ok=True)
                facts = supervisor_facts.evening(last, root)                        # the numbers the AI Supervisor reads for its evening review
                (supervisor_facts.OUT / f"facts_evening_{last}.json").write_text(json.dumps(facts, indent=1, default=str), encoding="utf-8")
                print(f"supervisor facts: data/ai_supervisor/facts_evening_{last}.json")
                import os

                if os.getenv("ANTHROPIC_API_KEY") and os.getenv("APLUS_AGENT_NIGHTLY", "1").strip().lower() not in {"0", "false", "no", "off"}:
                    import agent_judge
                    import agent_run

                    res = agent_run.run(agent_judge.ClaudeJudge(), agent_run.load_trades(root), [last], root=root)         # the shadow AI trading agent: records only, capped per day
                    print(f"AI agent (shadow): {res}")
            except Exception as exc:                       # noqa: BLE001 - must not hide the archive that was just written
                print(f"never-in-profit record failed: {type(exc).__name__}: {str(exc)[:120]}")
    except Exception as exc:                               # noqa: BLE001
        print(f"scoreboard step failed: {type(exc).__name__}: {str(exc)[:160]}")
        return 2
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rc = run(args[0] if args else None, backfill="--backfill" in sys.argv)
    try:                                                   # copy the small irreplaceable files to the private backup repo (backup_to_github.py); never affects the archive result
        import backup_to_github

        res = backup_to_github.run()
        print(f"backup to private repo: {res['message']}")
    except Exception as exc:                               # noqa: BLE001
        print(f"backup to private repo failed: {type(exc).__name__}: {str(exc)[:120]}")
    return rc


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
