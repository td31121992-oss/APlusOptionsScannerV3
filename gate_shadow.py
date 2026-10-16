"""Entry-gate shadow: which of four candidate gates WOULD have blocked a trade (SHADOW ONLY - recorded, never used to allow or block anything).

Found on the 81 closed trades since 1 Oct 2026 and checked on the 59 of 22-30 Sep (the 09:30 rule and a 30+ premium cap failed that check and are not here):

    gs_premium80   option bought at 80 or more                   (13% won; kept its sign on the check period)
    gs_ce_early    a CALL entered before 10:00                   (19% won; kept its sign)
    gs_chasing     the stock already moved 0.3%+ in OUR direction in the 15 minutes before entry
    gs_est_trend   setup family ESTABLISHED_TREND                (19% won; roughly neutral on the check period)
    gs_count       how many of the four apply

`tags()` is called once at entry by the scanner; `flags()` is the same logic for the nightly review (gate_review.py), which applies it to every signal.
"""

from __future__ import annotations

from typing import Any

PREMIUM_MIN = 80.0
CE_EARLY_BEFORE_MIN = 10 * 60
CHASE_PCT = 0.3


def flags(direction: str, option_price: float | None, minute_of_day: int | None, recent_move_15m_pct: float | None, setup_family: str | None = None) -> dict[str, bool | None]:
    bull = str(direction).upper() == "BULLISH"
    directional = None if recent_move_15m_pct is None else (recent_move_15m_pct if bull else -recent_move_15m_pct)
    return {
        "premium80": None if option_price is None or option_price <= 0 else bool(option_price >= PREMIUM_MIN),
        "ce_early": None if minute_of_day is None else bool(bull and minute_of_day < CE_EARLY_BEFORE_MIN),
        "chasing": None if directional is None else bool(directional > CHASE_PCT),
        "est_trend": None if setup_family in (None, "") else bool(str(setup_family).upper() == "ESTABLISHED_TREND"),
    }


def tags(direction: str, option_price: Any, minute_of_day: int | None, recent_move_15m_pct: Any, setup_family: Any) -> dict[str, Any]:
    try:
        def num(v: Any) -> float | None:
            try:
                return float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                return None

        f = flags(direction, num(option_price), minute_of_day, num(recent_move_15m_pct), str(setup_family or ""))
        out = {f"gs_{k}": v for k, v in f.items() if v is not None}
        out["gs_count"] = sum(1 for v in f.values() if v)
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}
