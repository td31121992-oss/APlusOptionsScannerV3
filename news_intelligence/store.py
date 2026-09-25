"""Local persistence for normalized news events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import NewsEvent


class NewsEventStore:
    """Persist one normalized event per JSON file."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def write(self, event: NewsEvent) -> Path:
        target = self.directory / f"{event.event_id}.json"
        target.write_text(
            json.dumps(event.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        return target

    def write_many(self, events: Iterable[NewsEvent]) -> list[Path]:
        return [self.write(event) for event in events]
