from datetime import datetime, timezone

from news_intelligence.impact_engine import CompanyImpactEngine
from news_intelligence.models import NewsEvent, NewsImpact
from news_intelligence.risk_engine import PreMarketRiskEngine


def _event(**overrides):
    values = {
        "event_id": "evt-1",
        "headline": "Regulatory proposal affects company",
        "summary": "Material regulatory development",
        "symbols": ("PBFINTECH",),
        "impact": NewsImpact.HIGH,
        "event_type": "REGULATORY",
        "detected_at": datetime.now(timezone.utc),
        "pre_market": True,
        "confidence": 0.9,
        "is_verified": True,
    }
    values.update(overrides)
    return NewsEvent(**values)


def test_impact_engine_keeps_mapping_explicit():
    assessments = CompanyImpactEngine().assess(
        _event(),
        symbol_directions={"PBFINTECH": "BEARISH"},
        rationale=("explicit symbol mapping",),
    )
    assert len(assessments) == 1
    assert assessments[0].symbol == "PBFINTECH"
    assert assessments[0].direction == "BEARISH"
    assert assessments[0].paper_signal_only is True


def test_risk_engine_is_explainable_and_bounded():
    result = PreMarketRiskEngine().classify(_event())
    assert result.level in {"WATCH", "ELEVATED", "HIGH", "CRITICAL"}
    assert 0 <= result.score <= 100
    assert "source_verified" in result.reasons
    assert result.paper_signal_only is True


def test_low_confidence_event_is_capped():
    result = PreMarketRiskEngine().classify(
        _event(confidence=0.2, is_verified=False)
    )
    assert result.score <= 40
    assert "low_confidence_cap" in result.reasons
