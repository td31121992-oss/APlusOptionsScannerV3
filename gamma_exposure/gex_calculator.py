"""Read-only GEX calculations for normalized APlus option-chain rows.

This module deliberately has no broker, order, strategy, or live-trading imports.

Sign convention:
- gross_gex is unsigned exposure magnitude.
- scenario_net_gex uses an explicit research convention: CE=+1, PE=-1.
  This is a scenario, NOT observed dealer inventory or proof of dealer positioning.
- oi_change_gex_proxy uses the same scenario signs on OI change. OI change alone
  cannot distinguish opening from closing trades or identify aggressor side.

GEX units: INR notional gamma exposure for a 1% underlying move:
    gamma * OI * lot_size * spot**2 * 0.01
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import math
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0


@dataclass(frozen=True, slots=True)
class GEXConfig:
    call_sign: float = 1.0
    put_sign: float = -1.0
    risk_free_rate: float = 0.065
    dividend_yield: float = 0.0
    flip_scan_low_pct: float = 0.80
    flip_scan_high_pct: float = 1.20
    flip_scan_steps: int = 161

    def __post_init__(self) -> None:
        if self.call_sign not in (-1.0, 1.0) or self.put_sign not in (-1.0, 1.0):
            raise ValueError("call_sign and put_sign must be -1 or +1")
        if not 0 < self.flip_scan_low_pct < self.flip_scan_high_pct:
            raise ValueError("invalid gamma-flip scan range")
        if self.flip_scan_steps < 3:
            raise ValueError("flip_scan_steps must be >= 3")


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _side_sign(side: str, config: GEXConfig) -> float:
    normalized = str(side or "").strip().upper()
    if normalized in {"CE", "CALL"}:
        return config.call_sign
    if normalized in {"PE", "PUT"}:
        return config.put_sign
    raise ValueError(f"unsupported option side: {side!r}")


def _expiry_year_fraction(expiry: Any, captured_at: Any) -> float | None:
    try:
        expiry_date = date.fromisoformat(str(expiry)[:10])
        captured = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=IST)
        expiry_close = datetime.combine(expiry_date, time(15, 30), tzinfo=IST)
        seconds = (expiry_close - captured.astimezone(IST)).total_seconds()
        return max(0.0, seconds / SECONDS_PER_YEAR)
    except (TypeError, ValueError, OverflowError):
        return None


def _normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def _bs_gamma(spot: float, strike: float, years: float, iv: float,
              risk_free_rate: float, dividend_yield: float) -> float | None:
    if spot <= 0 or strike <= 0 or years <= 0 or iv <= 0:
        return None
    sigma_root_t = iv * math.sqrt(years)
    if sigma_root_t <= 0:
        return None
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate - dividend_yield + 0.5 * iv * iv) * years
    ) / sigma_root_t
    return math.exp(-dividend_yield * years) * _normal_pdf(d1) / (spot * sigma_root_t)


def _iv_decimal(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None
    # Providers commonly expose IV as either 0.22 or 22.0.
    result = value / 100.0 if value > 3.0 else value
    return result if 0 < result < 5.0 else None


def _flip_price(rows: list[dict[str, Any]], spot: float,
                captured_at: Any, config: GEXConfig) -> float | None:
    """Model-based zero crossing using Black-Scholes gamma at hypothetical spots.

    Requires IV and expiry. This is a model estimate, not an observed dealer level.
    """
    prepared: list[tuple[float, float, float, float, float]] = []
    for row in rows:
        strike = _number(row.get("strike"))
        iv = _iv_decimal(_number(row.get("iv")))
        years = _expiry_year_fraction(row.get("expiry"), captured_at)
        oi = _number(row.get("oi"))
        lot = _number(row.get("lot_size"))
        if None in (strike, iv, years, oi, lot) or years <= 0 or oi <= 0 or lot <= 0:
            continue
        sign = _side_sign(str(row.get("side", "")), config)
        prepared.append((strike, iv, years, oi * lot, sign))
    if not prepared:
        return None

    def net_at(candidate_spot: float) -> float:
        total = 0.0
        for strike, iv, years, units, sign in prepared:
            gamma = _bs_gamma(candidate_spot, strike, years, iv,
                              config.risk_free_rate, config.dividend_yield)
            if gamma is not None:
                total += sign * gamma * units * candidate_spot * candidate_spot * 0.01
        return total

    points = [
        spot * (
            config.flip_scan_low_pct
            + (config.flip_scan_high_pct - config.flip_scan_low_pct)
            * index / (config.flip_scan_steps - 1)
        )
        for index in range(config.flip_scan_steps)
    ]
    values = [net_at(point) for point in points]
    crossings: list[float] = []
    for index in range(len(points) - 1):
        left_value, right_value = values[index], values[index + 1]
        if left_value == 0:
            crossings.append(points[index])
        elif left_value * right_value < 0:
            # Linear interpolation is adequate for locating the sampled zero crossing.
            fraction = abs(left_value) / (abs(left_value) + abs(right_value))
            crossings.append(points[index] + fraction * (points[index + 1] - points[index]))
    return min(crossings, key=lambda item: abs(item - spot)) if crossings else None


def calculate_snapshot(
    rows: Iterable[Mapping[str, Any]],
    *,
    config: GEXConfig | None = None,
) -> dict[str, Any]:
    """Calculate one symbol/timestamp snapshot across all supplied expiries.

    Each row must include spot, strike, side, expiry, gamma, OI and lot_size.
    Incomplete rows are counted and excluded; no lot-size default is invented.
    """
    cfg = config or GEXConfig()
    source_rows = [dict(row) for row in rows]
    if not source_rows:
        return {"status": "NO_DATA", "row_count": 0, "valid_rows": 0}

    first = source_rows[0]
    symbol = str(first.get("symbol") or "")
    captured_at = str(first.get("captured_at") or "")
    spot = _number(first.get("spot"))
    if spot is None or spot <= 0:
        return {
            "status": "INVALID_SPOT", "symbol": symbol,
            "captured_at": captured_at, "row_count": len(source_rows),
            "valid_rows": 0, "excluded_rows": len(source_rows),
        }

    totals = {
        "gross_gex": 0.0,
        "scenario_net_gex": 0.0,
        "call_gex_scenario": 0.0,
        "put_gex_scenario": 0.0,
        "oi_change_gex_proxy": 0.0,
    }
    by_strike: dict[float, dict[str, float]] = {}
    by_expiry: dict[str, dict[str, float]] = {}
    valid_rows = 0
    excluded_rows = 0

    for row in source_rows:
        row_spot = _number(row.get("spot"))
        strike = _number(row.get("strike"))
        gamma = _number(row.get("gamma"))
        oi = _number(row.get("oi"))
        lot_size = _number(row.get("lot_size"))
        oi_change = _number(row.get("oi_change"))
        if (
            row_spot is None or strike is None or gamma is None
            or oi is None or lot_size is None
            or row_spot <= 0 or strike <= 0 or gamma < 0 or oi < 0 or lot_size <= 0
        ):
            excluded_rows += 1
            continue
        side = str(row.get("side") or "").upper()
        try:
            sign = _side_sign(side, cfg)
        except ValueError:
            excluded_rows += 1
            continue

        gross = gamma * oi * lot_size * row_spot * row_spot * 0.01
        scenario = gross * sign
        flow_proxy = (
            gamma * oi_change * lot_size * row_spot * row_spot * 0.01 * sign
            if oi_change is not None else 0.0
        )
        valid_rows += 1
        totals["gross_gex"] += abs(gross)
        totals["scenario_net_gex"] += scenario
        totals["oi_change_gex_proxy"] += flow_proxy
        if side in {"CE", "CALL"}:
            totals["call_gex_scenario"] += scenario
        else:
            totals["put_gex_scenario"] += scenario

        strike_bucket = by_strike.setdefault(strike, {"gross_gex": 0.0, "scenario_net_gex": 0.0})
        strike_bucket["gross_gex"] += abs(gross)
        strike_bucket["scenario_net_gex"] += scenario
        expiry = str(row.get("expiry") or "UNKNOWN")
        expiry_bucket = by_expiry.setdefault(expiry, {"gross_gex": 0.0, "scenario_net_gex": 0.0})
        expiry_bucket["gross_gex"] += abs(gross)
        expiry_bucket["scenario_net_gex"] += scenario

    if valid_rows == 0:
        return {
            "status": "INSUFFICIENT_DATA", "symbol": symbol,
            "captured_at": captured_at, "spot": spot,
            "row_count": len(source_rows), "valid_rows": 0,
            "excluded_rows": excluded_rows,
        }

    call_rows = [
        (abs(_number(row.get("gamma")) or 0.0)
         * (_number(row.get("oi")) or 0.0)
         * (_number(row.get("lot_size")) or 0.0)
         * (_number(row.get("spot")) or 0.0) ** 2 * 0.01, _number(row.get("strike")))
        for row in source_rows if str(row.get("side") or "").upper() in {"CE", "CALL"}
        and _number(row.get("strike")) is not None
    ]
    put_rows = [
        (abs(_number(row.get("gamma")) or 0.0)
         * (_number(row.get("oi")) or 0.0)
         * (_number(row.get("lot_size")) or 0.0)
         * (_number(row.get("spot")) or 0.0) ** 2 * 0.01, _number(row.get("strike")))
        for row in source_rows if str(row.get("side") or "").upper() in {"PE", "PUT"}
        and _number(row.get("strike")) is not None
    ]
    call_wall = max(call_rows, default=(0.0, None), key=lambda item: item[0])[1]
    put_wall = max(put_rows, default=(0.0, None), key=lambda item: item[0])[1]

    return {
        "status": "OK",
        "symbol": symbol,
        "captured_at": captured_at,
        "spot": spot,
        "row_count": len(source_rows),
        "valid_rows": valid_rows,
        "excluded_rows": excluded_rows,
        **totals,
        "call_wall_strike": call_wall,
        "put_wall_strike": put_wall,
        "gamma_flip_model": _flip_price(source_rows, spot, captured_at, cfg),
        "strike_exposure": by_strike,
        "expiry_exposure": by_expiry,
        "sign_convention": f"CE={cfg.call_sign:+.0f},PE={cfg.put_sign:+.0f}",
        "positioning_note": "Scenario estimate only; open interest does not identify dealer inventory.",
        "flow_note": "OI-change proxy only; OI change does not identify opening/closing side or aggressor.",
        "gex_unit": "INR gamma-notional sensitivity per 1% underlying move",
    }
