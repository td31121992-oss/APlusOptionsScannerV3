"""Read-only price-action / Smart Money Concepts analysis.

Independent of order placement, paper-trade eligibility, portfolio risk, and scanner
gates. Consumes supplied OHLCV candles and returns descriptive features only.
"""
from __future__ import annotations
from typing import Any, Iterable

def _num(row: dict[str, Any], key: str) -> float | None:
    try:
        value = float(row[key])
        return value if value == value and abs(value) != float("inf") else None
    except (KeyError, TypeError, ValueError):
        return None

def _valid(rows: Iterable[dict[str, Any]]) -> list[dict[str, float]]:
    out = []
    for row in rows:
        o, h, l, c = (_num(row, k) for k in ("open", "high", "low", "close"))
        if None in (o, h, l, c) or h < l or h < max(o, c) or l > min(o, c):
            continue
        item = {"open": o, "high": h, "low": l, "close": c}
        v = _num(row, "volume")
        if v is not None and v >= 0:
            item["volume"] = v
        out.append(item)
    return out

def _pivots(candles: list[dict[str, float]], left: int, right: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs, lows = [], []
    # A pivot is emitted only after right candles have closed.
    for i in range(left, len(candles) - right):
        h, lo = candles[i]["high"], candles[i]["low"]
        if all(h > candles[j]["high"] for j in range(i-left, i)) and all(h >= candles[j]["high"] for j in range(i+1, i+right+1)):
            highs.append((i, h))
        if all(lo < candles[j]["low"] for j in range(i-left, i)) and all(lo <= candles[j]["low"] for j in range(i+1, i+right+1)):
            lows.append((i, lo))
    return highs, lows

def _atr(c: list[dict[str, float]], period: int = 14) -> float:
    if len(c) < 2:
        return 0.0
    trs = []
    for i, row in enumerate(c):
        prev = c[i-1]["close"] if i else row["close"]
        trs.append(max(row["high"]-row["low"], abs(row["high"]-prev), abs(row["low"]-prev)))
    sample = trs[-period:]
    return sum(sample) / len(sample) if sample else 0.0

def analyze_smc(candles: Iterable[dict[str, Any]], *, pivot_left: int = 2,
                pivot_right: int = 2, atr_period: int = 14) -> dict[str, Any]:
    """Return explainable, read-only structure, liquidity, FVG and velocity features.

    Input candles are chronological OHLC dictionaries. Pivots require left/right
    confirmation bars. SMC score is a heuristic feature score, not a probability
    or trade instruction.
    """
    rows = _valid(candles)
    if pivot_left < 1 or pivot_right < 1:
        raise ValueError("pivot_left and pivot_right must be >= 1")
    if len(rows) < pivot_left + pivot_right + 3:
        return {"ok": False, "reason": "insufficient_valid_candles", "candles_used": len(rows)}
    highs, lows = _pivots(rows, pivot_left, pivot_right)
    high_labels, low_labels = [], []
    for prev, cur in zip(highs, highs[1:]):
        high_labels.append({"index": cur[0], "price": cur[1], "label": "HH" if cur[1] > prev[1] else "LH" if cur[1] < prev[1] else "EQH"})
    for prev, cur in zip(lows, lows[1:]):
        low_labels.append({"index": cur[0], "price": cur[1], "label": "HL" if cur[1] > prev[1] else "LL" if cur[1] < prev[1] else "EQL"})
    last_high = highs[-1] if highs else None
    last_low = lows[-1] if lows else None
    close, previous_close = rows[-1]["close"], rows[-2]["close"]
    structure = "NEUTRAL"
    if high_labels and low_labels:
        hlabel, llabel = high_labels[-1]["label"], low_labels[-1]["label"]
        if hlabel == "HH" and llabel == "HL": structure = "BULLISH_HH_HL"
        elif hlabel == "LH" and llabel == "LL": structure = "BEARISH_LH_LL"
        elif hlabel == "HH" or llabel == "HL": structure = "MIXED_BULLISH"
        elif hlabel == "LH" or llabel == "LL": structure = "MIXED_BEARISH"
    bos = "NONE"
    if last_high and close > last_high[1] and previous_close <= last_high[1]: bos = "BULLISH_BOS"
    elif last_low and close < last_low[1] and previous_close >= last_low[1]: bos = "BEARISH_BOS"
    choch = "NONE"
    if bos == "BULLISH_BOS" and structure.startswith("BEARISH"): choch = "BULLISH_CHOCH_CANDIDATE"
    elif bos == "BEARISH_BOS" and structure.startswith("BULLISH"): choch = "BEARISH_CHOCH_CANDIDATE"
    atr = _atr(rows, atr_period)
    recent = rows[-min(5, len(rows)):]
    velocity = max(-5.0, min(5.0, (recent[-1]["close"] - recent[0]["close"]) / max(atr, 1e-12)))
    last = rows[-1]
    candle_range = last["high"] - last["low"]
    displacement = candle_range / max(atr, 1e-12)
    body_ratio = abs(last["close"] - last["open"]) / max(candle_range, 1e-12)
    displacement_confirmed = displacement >= 1.25 and body_ratio >= 0.60
    sweep = "NONE"
    if last_high and last["high"] > last_high[1] and close < last_high[1]: sweep = "BUY_SIDE_LIQUIDITY_SWEEP"
    elif last_low and last["low"] < last_low[1] and close > last_low[1]: sweep = "SELL_SIDE_LIQUIDITY_SWEEP"
    fvg = "NONE"
    if len(rows) >= 3:
        a, z = rows[-3], rows[-1]
        if z["low"] > a["high"]: fvg = "BULLISH_FVG"
        elif z["high"] < a["low"]: fvg = "BEARISH_FVG"
    bull, bear = 0.0, 0.0
    if structure == "BULLISH_HH_HL": bull += 30
    elif structure == "BEARISH_LH_LL": bear += 30
    elif structure == "MIXED_BULLISH": bull += 15
    elif structure == "MIXED_BEARISH": bear += 15
    if bos == "BULLISH_BOS": bull += 20
    elif bos == "BEARISH_BOS": bear += 20
    if velocity > 0: bull += min(15, velocity * 3)
    elif velocity < 0: bear += min(15, abs(velocity) * 3)
    if displacement_confirmed:
        if close > last["open"]: bull += 15
        elif close < last["open"]: bear += 15
    if sweep == "SELL_SIDE_LIQUIDITY_SWEEP": bull += 10
    elif sweep == "BUY_SIDE_LIQUIDITY_SWEEP": bear += 10
    if fvg == "BULLISH_FVG": bull += 10
    elif fvg == "BEARISH_FVG": bear += 10
    return {
        "ok": True, "analysis_mode": "READ_ONLY", "trade_decision": None,
        "candles_used": len(rows), "structure": structure,
        "confirmed_swing_highs": [{"index": i, "price": p} for i, p in highs[-5:]],
        "confirmed_swing_lows": [{"index": i, "price": p} for i, p in lows[-5:]],
        "high_structure_labels": high_labels[-5:], "low_structure_labels": low_labels[-5:],
        "bos": bos, "choch_candidate": choch, "liquidity_sweep": sweep, "fvg": fvg,
        "atr": round(atr, 6), "smc_velocity_atr_5bar": round(velocity, 3),
        "displacement_atr": round(displacement, 3), "displacement_confirmed": displacement_confirmed,
        "smc_score": {"bullish": round(min(100, bull), 1), "bearish": round(min(100, bear), 1),
                      "meaning": "heuristic_feature_score_not_probability"},
        "notes": [
            "Read-only: does not change scanner eligibility, paper-trade rules, risk limits, or order authority.",
            "Only pivots with right-side confirmation bars are labelled.",
            "SMC concepts are heuristic interpretations, not direct evidence of institutional orders."
        ]
    }
