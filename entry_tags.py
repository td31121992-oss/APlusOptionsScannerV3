"""Entry-quality tags (SHADOW only: nothing here blocks or changes a trade).

Candidate entry filters from the Oct 2026 study looked good on the days they were chosen on and failed out-of-sample, so they are only
recorded here, per trade, to be judged on forward data:

  entry_minute        minutes after midnight of the entry (time-of-day bucket)
  entry_premium       option entry price
  f_time_0945         True if the entry is at or after 09:45
  f_premium_5         True if the option premium is >= Rs 5
  f_all               both of the above
  day_regime          market regime at entry (BULL / BEAR / CHOP / UNKNOWN) from market_context, to test a "chop-day" gate
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def evaluate(entry_price: Any, when: datetime, regime: str | None = None) -> dict[str, Any]:
    minute = when.hour * 60 + when.minute
    premium = _f(entry_price)
    t_ok = minute >= 9 * 60 + 45
    p_ok = premium >= 5.0
    return {"entry_minute": minute, "entry_premium": round(premium, 2), "f_time_0945": t_ok, "f_premium_5": p_ok,
            "f_all": bool(t_ok and p_ok), "day_regime": str(regime or "UNKNOWN").upper()}


def regime_of(context: Mapping[str, Any] | None) -> str:
    return str((context or {}).get("regime") or "UNKNOWN").upper()
