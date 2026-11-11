"""Send the short summary of an AI Supervisor review to Telegram (read-only for the trading system; it only sends one message).

A review (data/ai_supervisor/review_<kind>_<day>.md) ends with a section "## Telegram summary" of a few lines. This sends that section, through the same CAlphaTrader sender as the 09:10 health message.
Set APLUS_SUPERVISOR_TELEGRAM=0 in .env to switch the message off (the review file is still written).

    python supervisor_notify.py data/ai_supervisor/review_evening_2026-11-11.md [--dry-run]
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAX_CHARS = 1500


def summary_of(text: str) -> str:
    """The text under the '## Telegram summary' heading (up to the next heading), trimmed to MAX_CHARS; empty when there is none."""
    m = re.search(r"^##\s*Telegram summary\s*$(.*?)(?=^##\s|\Z)", text, re.S | re.M)
    body = (m.group(1) if m else "").strip()
    return body[:MAX_CHARS]


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("usage: supervisor_notify.py <review.md> [--dry-run]")
        return 2
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    text = summary_of(Path(args[0]).read_text(encoding="utf-8"))
    if not text:
        print("no '## Telegram summary' section found; nothing sent")
        return 1
    if "--dry-run" in sys.argv:
        print(text)
        return 0
    if os.getenv("APLUS_SUPERVISOR_TELEGRAM", "1").strip().lower() in {"0", "false", "no", "off"}:
        print("Telegram message switched off (APLUS_SUPERVISOR_TELEGRAM=0)")
        return 0
    sys.path.insert(0, str(ROOT))
    import pipeline_watchdog

    ok, detail = pipeline_watchdog.send_telegram(text)
    print("sent" if ok else f"NOT sent: {detail[:160]}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
