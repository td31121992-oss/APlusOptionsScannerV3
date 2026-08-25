"""
analytics/market_structure.py

Market structure analysis for APlus Options Scanner V3.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import MarketStructure, OptionChainSnapshot


class MarketStructureEngine:
    """Analyzes option-chain structure."""

    def analyze(self, snapshot: OptionChainSnapshot) -> MarketStructure:
        if not snapshot.strikes:
            raise ValueError(f"No strikes available for {snapshot.symbol}")

        ltp = snapshot.underlying_ltp

        atm = min(snapshot.strikes, key=lambda s: abs(s.strike - ltp))

        call_wall = max(
            snapshot.strikes,
            key=lambda s: s.call.oi if s.call else -1,
        )

        put_wall = max(
            snapshot.strikes,
            key=lambda s: s.put.oi if s.put else -1,
        )

        support = max(
            (
                s for s in snapshot.strikes
                if s.strike <= ltp and s.put
            ),
            key=lambda s: s.put.oi,
            default=put_wall,
        )

        resistance = max(
            (
                s for s in snapshot.strikes
                if s.strike >= ltp and s.call
            ),
            key=lambda s: s.call.oi,
            default=call_wall,
        )

        return MarketStructure(
            atm_strike=atm.strike,
            call_wall=call_wall.strike,
            put_wall=put_wall.strike,
            support=support.strike,
            resistance=resistance.strike,
        )
