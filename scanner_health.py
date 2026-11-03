"""Daily scanner-health stamp: was the scanner really running for the whole session?

Every scanner cycle writes data/reports/intraday_movement_<YYYYMMDD>_<HHMMSS>.json, so the cycle times of a day are read from the file
names only (cheap, no file is opened). A day is

  CLEAN        started by 09:20, ran to 15:25 or later, covered at least 90% of the 09:15-15:30 minutes, no gap over 5 minutes,
               and was not double-run
  PARTIAL      anything else, with the reasons: LATE_START, EARLY_END, GAPS, LOW_COVERAGE, DOUBLE_RUN
  IN_PROGRESS  today, before 15:30 (judged on what has run so far: only the start and any gaps are checked)

    python scanner_health.py              # last 12 days
    python scanner_health.py --day 2026-10-13
"""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_FILE = re.compile(r"intraday_movement_(\d{8})_(\d{6})\.json$")
OPEN_MIN, CLOSE_MIN = 9 * 60 + 15, 15 * 60 + 30
SESSION_MINUTES = CLOSE_MIN - OPEN_MIN
LATE_AFTER, EARLY_BEFORE, GAP_LIMIT, COVER_MIN, MAX_DENSITY = 9 * 60 + 20, 15 * 60 + 25, 5.0, 0.90, 1.5


def cycle_times(day: str, root: Path | str = ROOT) -> list[float]:
    """Seconds after midnight of every cycle of `day`, sorted."""
    compact = day.replace("-", "")
    out = []
    folder = Path(root) / "data" / "reports"
    if not folder.is_dir():
        return out
    for p in folder.glob(f"intraday_movement_{compact}_*.json"):
        m = _FILE.search(p.name)
        if m and m.group(1) == compact:
            hh, mm, ss = int(m.group(2)[:2]), int(m.group(2)[2:4]), int(m.group(2)[4:])
            out.append(hh * 3600 + mm * 60 + ss)
    return sorted(out)


def _hm(seconds: float) -> str:
    return f"{int(seconds // 3600):02d}:{int(seconds % 3600 // 60):02d}"


def analyse(times: list[float], day: str, now: datetime | None = None) -> dict[str, Any]:
    if not times:
        return {"day": day, "status": "NO_DATA", "reasons": ["NO_CYCLES"], "cycles": 0}
    now = now or datetime.now()
    live = day == now.date().isoformat() and (now.hour * 60 + now.minute) < CLOSE_MIN
    inside = [t for t in times if OPEN_MIN * 60 <= t <= CLOSE_MIN * 60]
    first, last = times[0], times[-1]
    gaps = [(b - a, a) for a, b in zip(times, times[1:])]
    longest, longest_at = max(gaps, default=(0.0, first))
    # only count gaps inside the session window; a gap that spans the open/close is not a scanner outage
    session_gaps = [(g, a) for g, a in gaps if OPEN_MIN * 60 <= a <= CLOSE_MIN * 60 and g / 60 > GAP_LIMIT]
    minutes = {int(t // 60) for t in inside}
    end_min = (now.hour * 60 + now.minute) if live else CLOSE_MIN
    span = max(1, min(CLOSE_MIN, end_min) - OPEN_MIN)
    covered = sum(1 for m in range(OPEN_MIN, min(CLOSE_MIN, end_min) + 1) if m in minutes)
    coverage = min(1.0, covered / span)
    near_dupes = sum(1 for g, _ in gaps if g < 10)
    reasons = []
    if first > LATE_AFTER * 60:
        reasons.append("LATE_START")
    if not live and last < EARLY_BEFORE * 60:
        reasons.append("EARLY_END")
    if session_gaps:
        reasons.append("GAPS")
    if not live and coverage < COVER_MIN:
        reasons.append("LOW_COVERAGE")
    density = len(inside) / max(1, covered)                  # cycles per covered minute: about 1 for one scanner, about 2 for two
    if len(times) > 20 and (near_dupes / len(times) > 0.3 or density > MAX_DENSITY):
        reasons.append("DOUBLE_RUN")
    status = "IN_PROGRESS" if live and not reasons else ("CLEAN" if not reasons else "PARTIAL")
    if live and reasons:
        status = "PARTIAL"
    return {"day": day, "status": status, "reasons": reasons, "cycles": len(times), "first": _hm(first), "last": _hm(last),
            "coverage_pct": round(coverage * 100), "longest_gap_min": round(longest / 60, 1), "longest_gap_at": _hm(longest_at),
            "outage_gaps": len(session_gaps), "missing_min": sum(round(g / 60) for g, _ in session_gaps),
            "near_duplicate_cycles": near_dupes, "cycles_per_minute": round(density, 2), "live": live}


def day_health(day: str, root: Path | str = ROOT, now: datetime | None = None) -> dict[str, Any]:
    return analyse(cycle_times(day, root), day, now)


def line(h: dict[str, Any]) -> str:
    if h.get("status") == "NO_DATA":
        return "**Scanner health:** NO DATA - no scanner cycles were recorded for this day."
    why = {"LATE_START": f"started {h['first']} (late)", "EARLY_END": f"stopped {h['last']} (early)",
           "GAPS": f"{h['outage_gaps']} gap(s) over {int(GAP_LIMIT)} min, longest {h['longest_gap_min']:g} min at {h['longest_gap_at']}",
           "LOW_COVERAGE": f"only {h['coverage_pct']}% of session minutes covered",
           "DOUBLE_RUN": f"{h['cycles_per_minute']:g} cycles per minute (two scanners running?)"}
    head = {"CLEAN": "CLEAN", "PARTIAL": "PARTIAL", "IN_PROGRESS": "IN PROGRESS"}[h["status"]]
    detail = f"{h['first']} to {h['last']}, {h['cycles']} cycles, coverage {h['coverage_pct']}%, longest gap {h['longest_gap_min']:g} min"
    if h["reasons"]:
        detail += " | " + "; ".join(why.get(r, r) for r in h["reasons"])
    return f"**Scanner health: {head}** - {detail}"


def recent_days(root: Path | str = ROOT, limit: int = 12) -> list[str]:
    days = set()
    folder = Path(root) / "data" / "reports"
    for p in folder.glob("intraday_movement_2*.json"):
        m = _FILE.search(p.name)
        if m:
            days.add(f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}")
    return sorted(days)[-limit:]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day")
    ap.add_argument("--last", type=int, default=12)
    a = ap.parse_args()
    for d in ([a.day] if a.day else recent_days(limit=a.last)):
        print(d, date.fromisoformat(d).strftime("%a"), "|", line(day_health(d)).replace("**", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
