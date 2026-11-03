"""Round-trip cost model for PAPER option trades (buy to open, sell to close).

Uses the same fee schedule as the safety gate (SafetyGateConfig defaults) so the
journal and the gate agree. Components: brokerage (per executed order), exchange
transaction charge, SEBI fee, GST on those, STT on the sell side, stamp duty on
the buy side, plus an execution-impact estimate on the EXIT side only (paper
entries already fill at the ask, so the spread is paid on the way in).
"""

from __future__ import annotations

from typing import Mapping

from safety_gate import SafetyGateConfig

_CFG = SafetyGateConfig()


def round_trip_costs(
    entry_price: float,
    exit_price: float,
    quantity: int,
    spread_percent: float = 0.0,
    config: SafetyGateConfig | None = None,
) -> dict[str, float]:
    """Return a cost breakdown in rupees; 'total' is the all-in estimate."""
    cfg = config or _CFG
    qty = max(0, int(quantity))
    buy_turnover = max(0.0, float(entry_price)) * qty
    sell_turnover = max(0.0, float(exit_price)) * qty
    turnover = buy_turnover + sell_turnover
    if qty <= 0 or turnover <= 0:
        return {"total": 0.0}

    brokerage = cfg.brokerage_per_executed_order * 2.0
    exchange = turnover * cfg.exchange_transaction_charge_percent / 100.0
    sebi = turnover * cfg.sebi_turnover_fee_percent / 100.0
    other = turnover * cfg.ipft_other_charge_percent / 100.0
    gst = (brokerage + exchange + sebi + other) * cfg.gst_percent / 100.0
    stt = sell_turnover * cfg.option_stt_sell_percent / 100.0
    stamp = buy_turnover * cfg.option_stamp_buy_percent / 100.0
    impact_pct = max(cfg.execution_impact_percent_per_side, max(0.0, float(spread_percent)) / 2.0)
    impact = sell_turnover * impact_pct / 100.0
    parts: Mapping[str, float] = {
        "brokerage": brokerage, "exchange": exchange, "sebi": sebi, "other": other,
        "gst": gst, "stt": stt, "stamp": stamp, "execution_impact": impact,
    }
    out = {k: round(v, 2) for k, v in parts.items()}
    out["total"] = round(sum(parts.values()), 2)
    return out
