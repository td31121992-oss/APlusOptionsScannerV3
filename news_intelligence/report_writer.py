"""Write explainable, paper-only news intelligence reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .impact_engine import ImpactAssessment
from .models import NewsEvent
from .risk_engine import PreMarketRisk


class NewsReportWriter:
    """Serialize events and derived assessments for review."""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        report_name: str,
        *,
        events: Iterable[NewsEvent],
        impacts: Iterable[ImpactAssessment] = (),
        risks: Iterable[PreMarketRisk] = (),
    ) -> Path:
        event_list = list(events)
        impact_list = list(impacts)
        risk_list = list(risks)
        payload = {
            "paper_signal_only": True,
            "events": [event.to_dict() for event in event_list],
            "impacts": [self._as_dict(item) for item in impact_list],
            "risks": [self._as_dict(item) for item in risk_list],
        }
        target = self.output_dir / report_name
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        return target

    @staticmethod
    def _as_dict(value: object) -> dict[str, object]:
        return {
            key: getattr(value, key)
            for key in getattr(value, "__dataclass_fields__", {})
        }
