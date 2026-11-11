"""Check an AI Supervisor review against the facts it was written from (read-only; no trading effect).

A model can slip: leave a section out, quote a number that is not in the facts, call a failed pre-flight "READY". This catches those before the review is sent. It checks structure (required sections,
a verdict line, a short Telegram summary), consistency with the facts (trade count, net, every experiment listed, no "READY" claim when none is ready, a morning verdict that fits the pre-flight and
scanner health) and nothing else; it does not judge the quality of the writing.

    python review_check.py data/ai_supervisor/review_evening_2026-11-11.md        prints the problems, exit code 0 = fine, 3 = problems
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
EVENING_SECTIONS = ("## The day in numbers", "## What went right and wrong", "## Experiments", "## Issues found", "## Open items", "## Telegram summary")
MORNING_SECTIONS = ("## Checks", "## Last session", "## Open items", "## Telegram summary")
MAX_SUMMARY_LINES = {"evening": 8, "morning": 6}
MAX_SUMMARY_CHARS = 1500


def parse_name(path: Path) -> tuple[str, str] | None:
    m = re.match(r"review_(evening|morning)_(\d{4}-\d{2}-\d{2})\.md$", path.name)
    return (m.group(1), m.group(2)) if m else None


def summary_section(text: str) -> str:
    m = re.search(r"^##\s*Telegram summary\s*$(.*?)(?=^##\s|\Z)", text, re.S | re.M)
    return (m.group(1) if m else "").strip()


def check(text: str, facts: Mapping[str, Any], kind: str) -> list[str]:
    """Problems found; an empty list means the review passes."""
    problems: list[str] = []
    head = "\n".join(text.splitlines()[:8])
    if facts.get("calendar", {}).get("is_trading_day") is False:
        return [] if re.search(r"^#\s", text, re.M) and re.search(r"not a trading day|market (is )?closed|holiday", text, re.I) else ["market closed today but the review does not say so"]
    for s in (EVENING_SECTIONS if kind == "evening" else MORNING_SECTIONS):
        if s not in text:
            problems.append(f"missing section: {s}")
    verdicts = ("GREEN", "AMBER", "RED") if kind == "evening" else ("NOT READY", "CHECK", "READY")
    m = re.search(r"\*\*Verdict:\s*([A-Z ]+?)\*\*" if kind == "evening" else r"\*\*(NOT READY|CHECK|READY)\b", head)
    verdict = m.group(1).strip() if m else None
    if verdict not in verdicts:
        problems.append("no verdict line (" + " / ".join(verdicts) + ") near the top")
    summary = summary_section(text)
    if not summary:
        problems.append("the Telegram summary is empty")
    elif len(summary.splitlines()) > MAX_SUMMARY_LINES[kind] or len(summary) > MAX_SUMMARY_CHARS:
        problems.append(f"the Telegram summary is too long ({len(summary.splitlines())} lines, {len(summary)} characters)")
    if kind == "evening":
        t = facts.get("trades", {})
        if t.get("closed"):
            if str(t["closed"]) not in text:
                problems.append(f"the number of closed trades ({t['closed']}) is not in the review")
            if f"{abs(int(t['net'])):,}" not in text:
                problems.append(f"the day's net (Rs {abs(int(t['net'])):,}) is not in the review")
            if f"{abs(int(t['net'])):,}" not in summary:
                problems.append("the Telegram summary does not give the day's net")
        for exp in facts.get("experiments", []):
            if str(exp.get("id")) not in text:
                problems.append(f"experiment {exp.get('id')} is not listed")
        ready = [e for e in facts.get("experiments", []) if str(e.get("status", "")).startswith("READY")]
        if not ready and re.search(r"READY: (meets|fails)", text):
            problems.append("the review says an experiment is READY but none is in the facts")
        if ready and not re.search(r"decid", text, re.I):
            problems.append("an experiment is READY in the facts but the review does not ask the user to decide")
        if facts.get("pipeline", {}).get("not_current") and "not current" not in text.lower() and "stale" not in text.lower():
            problems.append("outputs are not current in the facts but the review does not mention it")
        if verdict == "GREEN" and (facts.get("scanner", {}).get("failed_cycles", 0) > 5 or facts.get("scanner", {}).get("auth_problems", 0) > 0):
            problems.append("verdict GREEN with failed cycles or authorisation problems in the facts")
    else:
        pre, health = facts.get("preflight", {}), facts.get("system", {}).get("scanner_health", {})
        if verdict == "READY" and pre.get("passed") is False:
            problems.append("verdict READY but the pre-flight failed")
        if verdict == "READY" and isinstance(health, dict) and health.get("status") not in (None, "HEALTHY"):
            problems.append(f"verdict READY but the scanner health is {health.get('status')}")
        if verdict == "READY" and facts.get("pipeline", {}).get("not_current"):
            problems.append("verdict READY but outputs are not current in the facts")
    return problems


def check_file(path: Path, root: Path = ROOT) -> list[str]:
    parsed = parse_name(path)
    if parsed is None:
        return [f"unexpected file name: {path.name}"]
    kind, day = parsed
    facts_path = root / "data" / "ai_supervisor" / f"facts_{kind}_{day}.json"
    try:
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"the facts file is missing or unreadable: {facts_path.name}"]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ["the review file is not readable"]
    return check(text, facts, kind)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: review_check.py <review.md>")
        return 2
    problems = check_file(Path(sys.argv[1]))
    for p in problems:
        print("-", p)
    print("review check:", "PASSED" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 3


if __name__ == "__main__":
    raise SystemExit(main())
