"""Option greeks at entry (SHADOW / RESEARCH - never blocks or changes a trade).

Black-Scholes (European, no dividend) from the contract's strike / expiry, the stock price and the option price. The implied
volatility is solved from the option's own price (the feed's IV is used only when the price cannot be solved), so the numbers are
model-derived and approximate - good for comparing trades with each other, not for exact pricing.

    gk_iv_pct              implied volatility, % a year
    gk_delta               option price change per Rs 1 stock move
    gk_gamma               change of delta per Rs 1 stock move
    gk_theta_day           premium lost per calendar day if nothing moves (Rs per share, negative)
    gk_theta_pct_day       the same as % of the premium - the "option melting" speed
    gk_vega_1pt            premium change per 1 point of IV (Rs per share)
    gk_days                calendar days to expiry
    gk_move_pct_to_10pct   stock move (%) in our direction needed for a +10% option gain, delta-gamma estimate
    gk_breakeven_move_pct  stock move (%) needed just to cover one day of theta
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

RATE = 0.07


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_price(spot: float, strike: float, t: float, vol: float, call: bool, rate: float = RATE) -> float:
    if t <= 0 or vol <= 0:
        return max(0.0, (spot - strike) if call else (strike - spot))
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    if call:
        return spot * _cdf(d1) - strike * math.exp(-rate * t) * _cdf(d2)
    return strike * math.exp(-rate * t) * _cdf(-d2) - spot * _cdf(-d1)


def implied_vol(price: float, spot: float, strike: float, t: float, call: bool) -> float | None:
    intrinsic = max(0.0, (spot - strike) if call else (strike - spot))
    if price <= intrinsic + 1e-6 or t <= 0:
        return None
    lo, hi = 0.01, 4.0
    if bs_price(spot, strike, t, hi, call) < price:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if bs_price(spot, strike, t, mid, call) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def greeks_at_entry(spot: float, strike: float, expiry: str, option_type: str, price: float, feed_iv_pct: float | None = None,
                    today: date | None = None, direction_bull: bool | None = None) -> dict[str, Any]:
    try:
        spot, strike, price = float(spot), float(strike), float(price)
        if spot <= 0 or strike <= 0 or price <= 0:
            return {}
        exp = datetime.fromisoformat(str(expiry)[:10]).date()
        days = max(0.5, (exp - (today or date.today())).days + 0.5)      # expiry day itself counts as half a day
        t = days / 365.0
        call = str(option_type).upper().startswith("C")
        vol = implied_vol(price, spot, strike, t, call)
        if vol is None and feed_iv_pct:
            vol = float(feed_iv_pct) / 100.0
        if not vol or vol <= 0:
            return {}
        d1 = (math.log(spot / strike) + (RATE + 0.5 * vol * vol) * t) / (vol * math.sqrt(t))
        d2 = d1 - vol * math.sqrt(t)
        delta = _cdf(d1) if call else _cdf(d1) - 1.0
        gamma = _pdf(d1) / (spot * vol * math.sqrt(t))
        vega = spot * _pdf(d1) * math.sqrt(t)
        theta_year = (-spot * _pdf(d1) * vol / (2.0 * math.sqrt(t))
                      - (RATE * strike * math.exp(-RATE * t) * _cdf(d2) if call else -RATE * strike * math.exp(-RATE * t) * _cdf(-d2)))
        theta_day = theta_year / 365.0
        sign = 1.0 if (direction_bull if direction_bull is not None else call) else -1.0
        # stock move (in rupees, in our direction) for +10% on the premium: solve delta*m + 0.5*gamma*m^2 = 0.10*price
        target = 0.10 * price
        a, b = 0.5 * gamma, abs(delta)
        move = target / b if a <= 0 else (-b + math.sqrt(b * b + 4 * a * target)) / (2 * a) if b * b + 4 * a * target >= 0 else target / b
        be = (-theta_day / abs(delta)) if abs(delta) > 1e-9 else None
        return {"gk_iv_pct": round(vol * 100.0, 1), "gk_delta": round(delta, 3), "gk_gamma": round(gamma, 5),
                "gk_theta_day": round(theta_day, 3), "gk_theta_pct_day": round(theta_day / price * 100.0, 2),
                "gk_vega_1pt": round(vega / 100.0, 3), "gk_days": round(days, 1),
                "gk_move_pct_to_10pct": round(move / spot * 100.0, 2), "gk_breakeven_move_pct": round(be / spot * 100.0, 3) if be else ""}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}
