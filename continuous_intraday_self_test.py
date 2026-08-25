"""Offline self-test for full-session PAPER CE/PE signal generation."""

from __future__ import annotations

import os
import sys
import tempfile
import types
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("DHAN_CLIENT_ID", "SELFTEST")
os.environ.setdefault("DHAN_ACCESS_TOKEN", "SELFTEST_TOKEN")

if "dhanhq" not in sys.modules:
    try:
        __import__("dhanhq")
    except Exception:
        module = types.ModuleType("dhanhq")
        class DhanContext:  # noqa: D101
            def __init__(self, *args, **kwargs):
                pass
        class dhanhq:  # noqa: N801,D101
            def __init__(self, *args, **kwargs):
                pass
        module.DhanContext = DhanContext
        module.dhanhq = dhanhq
        sys.modules["dhanhq"] = module

from config import OpeningMomentumConfig
from intraday_movement_engine import IntradayMovementEngine, QuoteTape
from opening_momentum_scanner import OpeningMomentumScanner
from paper_trade_journal import PaperTradeJournal

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class C:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class Settings:
    quote_tape_minutes = 65
    minimum_recent_move_15m_percent = 0.45
    minimum_recent_volume_acceleration = 1.30


def candle_series(start: datetime, first: float, step: float, count: int, volume: int = 1000):
    rows = []
    price = first
    for i in range(count):
        nxt = price + step
        rows.append(C(
            start + timedelta(minutes=5 * i),
            price,
            max(price, nxt) + abs(step) * 0.25 + 0.05,
            min(price, nxt) - abs(step) * 0.25 - 0.05,
            nxt,
            volume + i * 20,
        ))
        price = nxt
    return rows


def strong_features(direction: str) -> dict[str, object]:
    bullish = direction == "BULLISH"
    return {
        "chase_risk_score": 10.0,
        "recent_relative_volume_15m": 1.9,
        "tape_volume_acceleration_5m": 2.2,
        "tape_volume_acceleration_15m": 1.8,
        "trend_alignment_score": 78.0,
        "clean_trend_score": 76.0,
        "fresh_breakout": True,
        "healthy_pullback": False,
        "continuation_breakout": False,
        "recent_move_15m_percent": 0.95 if bullish else -0.95,
        "fresh_15m_high": bullish,
        "fresh_15m_low": not bullish,
    }


def assert_actionable(scanner: OpeningMomentumScanner, when: datetime, direction: str) -> None:
    stage, actionable, reason = scanner._stage_and_actionability(
        now=when,
        direction=direction,
        score=82.0,
        completed_bars=30,
        first_alignment=True,
        first_body_ratio=0.70,
        aligned_vwap=True,
        relative_volume=1.8,
        opening_range_breakout=True,
        opening_direction_confirmed=True,
        extension_atr=1.1,
        vwap_distance_percent=0.8 if direction == "BULLISH" else -0.8,
        risk_percent=0.6,
        features=strong_features(direction),
    )
    assert actionable, (when, stage, reason)
    assert "NO_NEW_ENTRY" not in stage, (when, stage, reason)


def main() -> int:
    cfg = OpeningMomentumConfig()
    assert cfg.session_start == time(9, 15)
    assert cfg.session_stop == time(15, 30)
    assert cfg.paper_trade_rearm_minutes >= 5

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)

        # Quote tape still detects a stock that wakes up later in the day.
        tape = QuoteTape(tmp / "tape.json", keep_minutes=65)
        base = datetime(2026, 8, 6, 12, 30, tzinfo=IST)
        cumulative = 100_000
        price = 100.0
        for minute in range(36):
            when = base + timedelta(minutes=minute)
            if minute >= 25:
                price += 0.18
                cumulative += 10_000
            else:
                cumulative += 1_000
            metrics = tape.observe(symbol="TEST", when=when, ltp=price, volume=cumulative)
        assert metrics.move_10m_percent > 1.0, metrics
        assert metrics.volume_acceleration_5m > 2.0, metrics

        # 5m/15m features + pivots still work.
        engine = IntradayMovementEngine(state_dir=tmp / "state", settings=Settings())
        previous_day = date(2026, 8, 5)
        current_day = date(2026, 8, 6)
        prev = candle_series(datetime(2026, 8, 5, 9, 15, tzinfo=IST), 1260.0, -0.05, 20, 800)
        today = candle_series(datetime(2026, 8, 6, 9, 15, tzinfo=IST), 1255.0, -1.0, 24, 1600)
        grouped = {previous_day: prev, current_day: today}
        features = engine.analyse(
            symbol="LODHA_TEST", direction="BEARISH", price=1230.0, vwap=1240.0,
            completed=today, grouped=grouped, current_date=current_day,
            now=datetime(2026, 8, 6, 11, 20, tzinfo=IST),
            range_position_percent=5.0, trend_retention_percent=95.0,
            extension_atr=1.2, vwap_distance_percent=-0.8,
        )
        assert features.trend_alignment_score >= 55.0, features
        assert features.clean_trend_score >= 60.0, features
        assert features.pivot_state != "PIVOT_UNKNOWN", features

        # No arbitrary intraday cutoff: strong PAPER setups can become actionable
        # at the open, midday, afternoon and late session.
        scanner = object.__new__(OpeningMomentumScanner)
        scanner.settings = cfg
        assert_actionable(scanner, datetime(2026, 8, 6, 9, 30, tzinfo=IST), "BEARISH")
        assert_actionable(scanner, datetime(2026, 8, 6, 13, 15, tzinfo=IST), "BULLISH")
        assert_actionable(scanner, datetime(2026, 8, 6, 15, 10, tzinfo=IST), "BEARISH")
        assert_actionable(scanner, datetime(2026, 8, 6, 15, 25, tzinfo=IST), "BULLISH")
        assert scanner._new_entries_allowed(datetime(2026, 8, 6, 15, 25, tzinfo=IST))
        assert not scanner._new_entries_allowed(datetime(2026, 8, 6, 15, 31, tzinfo=IST))

        # Before a first completed 5-minute candle, rejection is data-readiness,
        # not "entry window closed".
        stage, actionable, reason = scanner._stage_and_actionability(
            now=datetime(2026, 8, 6, 9, 17, tzinfo=IST), direction="BULLISH",
            score=95.0, completed_bars=0, first_alignment=True,
            first_body_ratio=0.9, aligned_vwap=True, relative_volume=3.0,
            opening_range_breakout=True, opening_direction_confirmed=True,
            extension_atr=0.8, vwap_distance_percent=0.5, risk_percent=0.5,
            features=strong_features("BULLISH"),
        )
        assert not actionable and stage == "WAITING_FOR_FIRST_5M_CLOSE", (stage, reason)
        assert "window" not in reason.lower(), reason

        # Paper journal: one generated trade is persisted and duplicate cycles
        # are suppressed until the setup becomes non-actionable again.
        journal = PaperTradeJournal(
            state_dir=tmp / "journal_state", report_dir=tmp / "reports", rearm_minutes=20
        )
        when = datetime(2026, 8, 6, 10, 0, tzinfo=IST)
        assert journal.can_generate(symbol="CROMPTON", direction="BEARISH", when=when)
        plan = {
            "symbol": "CROMPTON", "direction": "BEARISH",
            "stage": "OPENING_BEARISH_ENTRY_READY", "setup_family": "OPENING_MOMENTUM",
            "selection_tier": "ENTRY_READY", "momentum_score": 92.0,
            "movement_capture_score": 80.0, "trend_alignment_score": 76.0,
            "clean_trend_score": 78.0, "chase_risk_score": 10.0,
            "pivot_state": "S2_TO_S1", "recent_move_15m_percent": -1.2,
            "underlying": {"entry": 260.0, "stop_loss": 262.0, "target1": 258.0,
                           "target2": 256.0, "target3": 254.0, "risk_percent": 0.77},
            "option_contract": {"transaction": "BUY", "option_type": "PE",
                                "security_id": "123", "trading_symbol": "CROMPTON-PE",
                                "expiry": "2026-08-27", "strike": 260.0, "ltp": 8.0,
                                "bid": 7.9, "ask": 8.1, "limit_price": 8.15,
                                "stop_loss": 6.1, "target1": 10.2, "target2": 11.7,
                                "target3": 13.2, "lot_size": 250, "lots": 1,
                                "quantity": 250, "total_premium": 2037.5,
                                "total_risk": 512.5, "oi": 10000, "volume": 2000,
                                "iv": 28.0, "spread_percent": 2.47,
                                "selection_score": 88.0},
            "safety_gate": {"decision": "WARN", "block_reasons": [], "warnings": ["paper"]},
        }
        candidate = {"symbol": "CROMPTON", "direction": "BEARISH"}
        record = journal.record_trade(plan=plan, candidate=candidate, when=when)
        assert record["option_type"] == "PE", record
        assert not journal.can_generate(
            symbol="CROMPTON", direction="BEARISH", when=when + timedelta(minutes=1)
        )
        journal.observe_candidate(
            symbol="CROMPTON", direction="BEARISH", stage="BEARISH_TREND_WAIT_FOR_PULLBACK",
            actionable=False, when=when + timedelta(minutes=5),
        )
        assert journal.can_generate(
            symbol="CROMPTON", direction="BEARISH", when=when + timedelta(minutes=6)
        )
        journal.flush()
        assert (tmp / "reports" / "paper_trades.csv").exists()
        assert (tmp / "reports" / "paper_trades_latest.json").exists()

    print("PASS: quote-tape fresh acceleration detection")
    print("PASS: 5m/15m trend + pivot features")
    print("PASS: 09:30 quality-gated PAPER entry eligibility")
    print("PASS: 13:15 quality-gated PAPER entry eligibility")
    print("PASS: 15:10 and 15:25 PAPER entry eligibility -- no clock cutoff")
    print("PASS: pre-first-candle gate is data readiness, not time cutoff")
    print("PASS: persistent CE/PE paper-trade journal + duplicate suppression")
    print("ALL FULL-SESSION PAPER TRADE SELF-TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
