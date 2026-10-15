"""No-trade day verdict (SHADOW / RESEARCH - never blocks or changes a trade).

At every entry we ask the question a human trader asks: "is today a day to be trading at all?" and RECORD the answer with its reasons,
so later we can see whether trades taken under NO_TRADE / CAUTION did worse than the rest, and tune the thresholds from data.

    nt_verdict   TRADE | CAUTION | NO_TRADE
    nt_reasons   "|"-joined reasons
    nt_losses    closed paper trades today that lost
    nt_wins      closed paper trades today that won
    nt_day_pct   today's P&L (realized + open) as % of account capital

Reasons (each one is an observation, not a verdict by itself):
    LOSS_STREAK_3      three or more losing closes today and no winner yet           -> NO_TRADE
    LOSSES_2_NO_WIN    two losing closes today and no winner yet                     -> CAUTION
    BREADTH_WEAK       < 35% of the market's stocks move with the trade direction    -> NO_TRADE
    BREADTH_LOW        < 42% of the market with the trade direction                  -> CAUTION
    AGAINST_INDEX      Nifty is moving against the trade by more than 0.15%           -> CAUTION
    FLAT_INDEX         Nifty within +/-0.10% of the open after 10:00 (no direction)   -> CAUTION
    DAY_DRAWDOWN       today's P&L is below -1.5% of capital                          -> NO_TRADE
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def _f(v: Any, default: float | None = None) -> float | None:
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def evaluate(trades_today: Iterable[Mapping[str, Any]], direction: str, minute_of_day: int, nifty_pct_open: Any = None,
             breadth_pct_with: Any = None, capital: float = 500000.0) -> dict[str, Any]:
    try:
        wins = losses = 0
        pnl = 0.0
        for t in trades_today:
            val = _f(t.get("total_pnl"))
            if val is None:
                val = _f(t.get("net_pnl"))
            if val is None:
                val = _f(t.get("realized_pnl"), 0.0)
            pnl += val or 0.0
            if str(t.get("status") or "").upper() == "CLOSED":
                if (val or 0.0) < 0:
                    losses += 1
                elif (val or 0.0) > 0:
                    wins += 1
        reasons: list[str] = []
        level = 0                                            # 0 TRADE, 1 CAUTION, 2 NO_TRADE
        if losses >= 3 and wins == 0:
            reasons.append("LOSS_STREAK_3")
            level = 2
        elif losses >= 2 and wins == 0:
            reasons.append("LOSSES_2_NO_WIN")
            level = max(level, 1)
        bp = _f(breadth_pct_with)
        if bp is not None:
            if bp < 35:
                reasons.append("BREADTH_WEAK")
                level = 2
            elif bp < 42:
                reasons.append("BREADTH_LOW")
                level = max(level, 1)
        nf = _f(nifty_pct_open)
        if nf is not None:
            bull = str(direction).upper() == "BULLISH"
            if (bull and nf < -0.15) or ((not bull) and nf > 0.15):
                reasons.append("AGAINST_INDEX")
                level = max(level, 1)
            elif minute_of_day >= 600 and abs(nf) <= 0.10:
                reasons.append("FLAT_INDEX")
                level = max(level, 1)
        day_pct = pnl / capital * 100.0 if capital else 0.0
        if day_pct <= -1.5:
            reasons.append("DAY_DRAWDOWN")
            level = 2
        return {"nt_verdict": ("TRADE", "CAUTION", "NO_TRADE")[level], "nt_reasons": "|".join(reasons), "nt_losses": losses,
                "nt_wins": wins, "nt_day_pct": round(day_pct, 2)}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}
