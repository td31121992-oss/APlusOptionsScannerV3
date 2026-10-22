"""Isolated Black-Scholes Greeks and dealer-signed gamma-flip research.
Research-only: this module is not imported by production scanner code.
Open interest alone does not reveal dealer positioning, so a gamma-flip estimate is unavailable unless each contract supplies an explicit dealer position sign (+1 long gamma, -1 short gamma).
"""
from __future__ import annotations
from math import erf, exp, isfinite, log, pi, sqrt
from typing import Any, Iterable, Mapping

def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))

def _normal_pdf(value: float) -> float:
    return exp(-0.5 * value * value) / sqrt(2.0 * pi)

def _iv_decimal(value: Any) -> float:
    """Accept decimal IV (0.25) or percent IV (25); return decimal IV."""
    iv = float(value)
    if iv > 3.0:
        iv /= 100.0
    if not isfinite(iv) or iv <= 0.0:
        raise ValueError("iv must be positive and finite")
    return iv

def black_scholes_greeks(*, spot: float, strike: float, iv: float, time_years: float, option_type: str, rate: float = 0.06) -> dict[str, float]:
    """Return theoretical delta and gamma; IV may be decimal or percent.
    Rate is an explicit annual continuously-compounded assumption.
    """
    spot, strike, time_years, rate = map(float, (spot, strike, time_years, rate))
    volatility = _iv_decimal(iv)
    kind = str(option_type).strip().upper()
    if kind in {"CE", "C", "CALL"}:
        kind = "CALL"
    elif kind in {"PE", "P", "PUT"}:
        kind = "PUT"
    else:
        raise ValueError("option_type must be CALL/CE or PUT/PE")
    if not all(isfinite(v) for v in (spot, strike, time_years, rate)):
        raise ValueError("inputs must be finite")
    if spot <= 0.0 or strike <= 0.0 or time_years <= 0.0:
        raise ValueError("spot, strike, and time_years must be positive")
    root_t = sqrt(time_years)
    denominator = volatility * root_t
    d1 = (log(spot / strike) + (rate + 0.5 * volatility * volatility) * time_years) / denominator
    delta = _normal_cdf(d1) if kind == "CALL" else _normal_cdf(d1) - 1.0
    gamma = _normal_pdf(d1) / (spot * denominator)
    return {"delta": delta, "gamma": gamma}

def estimate_gamma_flip(contracts: Iterable[Mapping[str, Any]], spot_grid: Iterable[float], *, rate: float = 0.06) -> dict[str, Any]:
    """Find a net-gamma zero crossing using explicitly signed positions.
    Each contract needs strike, iv, time_years, option_type, open_interest,
    lot_size and dealer_position_sign (+1 long / -1 short dealer position).
    Missing/invalid data returns UNAVAILABLE instead of guessing.
    """
    rows = [dict(row) for row in contracts]
    spots = sorted({float(value) for value in spot_grid})
    if not rows:
        return {"status": "UNAVAILABLE", "reason": "no_contracts", "flip_level": None}
    if len(spots) < 2 or any(not isfinite(s) or s <= 0 for s in spots):
        return {"status": "UNAVAILABLE", "reason": "invalid_spot_grid", "flip_level": None}
    required = ("strike", "iv", "time_years", "option_type", "open_interest", "lot_size", "dealer_position_sign")
    for index, row in enumerate(rows):
        if any(row.get(key) is None for key in required):
            return {"status": "UNAVAILABLE", "reason": "missing_required_or_dealer_position_sign", "contract_index": index, "flip_level": None}
        try:
            sign = int(row["dealer_position_sign"])
            oi, lot_size = float(row["open_interest"]), float(row["lot_size"])
            strike, time_years = float(row["strike"]), float(row["time_years"])
            iv = _iv_decimal(row["iv"])
            if sign not in (-1, 1) or oi < 0 or lot_size <= 0 or strike <= 0 or time_years <= 0:
                raise ValueError
            row["_sign"], row["_oi"], row["_lot"] = sign, oi, lot_size
            row["_strike"], row["_time"], row["_iv"] = strike, time_years, iv
            row["_kind"] = str(row["option_type"])
        except (TypeError, ValueError, OverflowError):
            return {"status": "UNAVAILABLE", "reason": "invalid_contract_inputs", "contract_index": index, "flip_level": None}
    curve = []
    for spot in spots:
        net = 0.0
        for row in rows:
            greek = black_scholes_greeks(spot=spot, strike=row["_strike"], iv=row["_iv"], time_years=row["_time"], option_type=row["_kind"], rate=rate)
            net += row["_sign"] * row["_oi"] * row["_lot"] * greek["gamma"] * spot * spot * 0.01
        curve.append({"spot": spot, "net_gamma_exposure_proxy": net})
    crossings = []
    for left, right in zip(curve, curve[1:]):
        y1, y2 = left["net_gamma_exposure_proxy"], right["net_gamma_exposure_proxy"]
        if y1 == 0.0:
            crossings.append(left["spot"])
        elif y1 * y2 < 0.0:
            crossings.append(left["spot"] + (0.0 - y1) * (right["spot"] - left["spot"]) / (y2 - y1))
    if curve[-1]["net_gamma_exposure_proxy"] == 0.0:
        crossings.append(curve[-1]["spot"])
    return {"status": "ESTIMATED" if crossings else "NO_CROSSING_IN_GRID", "reason": None if crossings else "no_zero_crossing_in_supplied_spot_grid", "flip_level": crossings[0] if crossings else None, "crossings": crossings, "curve": curve, "contract_count": len(rows), "assumptions": {"greeks": "Black-Scholes model", "risk_free_rate": rate, "dealer_position_signs": "caller-supplied; not inferable from OI alone", "exposure": "OI x lot_size x gamma x spot^2 x 1%"}}
