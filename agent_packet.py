"""The candidate packet: exactly what the AI trading agent sees about a trade (read-only; no trading effect).

A packet holds only facts that were known at the moment of entry: the setup and its scores, the option's price / spread / IV, the market and sector picture, flow, and where the trade sits in the
day. Nothing from after the entry can get in: no peak, no exit, no P&L, no confirm / shadow / opt5 fields, none of the derived tags that look at the later price path. PACKET_FIELDS is the
whole list (a trade record has 600+ fields; most are research tags, some are hindsight), and forbidden() is checked on every packet.

    packet(trade, sectors) -> dict                       the facts, nulls dropped, numbers rounded
    digest(packet) -> str                                a short hash of the packet (stored in the ledger)
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Mapping

PACKET_FIELDS = (
    # what the scanner saw
    "symbol", "option_type", "direction", "setup_family", "stage", "selection_tier", "pivot_state", "selection_score", "momentum_score", "movement_capture_score",
    "trend_alignment_score", "clean_trend_score", "chase_risk_score", "recent_move_15m_percent", "underlying_risk_percent",
    # the option
    "entry_price", "spread_percent", "iv", "iv_rank", "oi", "volume", "strike", "lot_size", "capital_deployed", "option_stop", "option_target1", "gk_delta", "gk_theta_day", "gk_days",
    # market and regime
    "rgs_regime", "day_regime", "breadth_pct_with", "breadth_tag", "rule_nifty_pct_open", "mb_nifty_open_dir", "mtf_agree", "mtf_all_agree",
    # flow and stock-specific
    "tk_buy_pct15", "fut_flow", "fut_confirms", "px_x_avg", "mv_in_play", "em_rvol", "event_like", "nd_vol_x",
    # where the trade sits in the day (earlier trades only)
    "day_entry_rank", "nt_wins", "nt_losses",
)
DERIVED = ("sector", "entry_minute", "weekday", "days_to_expiry", "opening_volume_x", "minutes_since_first_signal", "sector_in_0945_picks")
FORBIDDEN_PREFIXES = ("shadow_", "confirm", "opt5", "dx_x_", "dx_e_", "dx_mom", "mfe", "mae", "exit", "net_", "gross", "realized", "unrealized", "total_pnl", "highest", "lowest",
                      "stock_move", "stock_fav", "runner", "target1_hit", "target2_hit", "target3_hit", "holding", "return_percent", "result", "last_", "watch", "alert_")


def forbidden(keys) -> list[str]:
    """Keys of a packet that start with a hindsight prefix; empty when the packet is clean."""
    return sorted(k for k in keys if str(k).startswith(FORBIDDEN_PREFIXES))


def _clean(v: Any) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        return None if v != v else round(v, 3)
    if isinstance(v, (int, str)):
        s = v.strip() if isinstance(v, str) else v
        return None if s in ("", "nan", "None") else s
    return None                                            # nested objects are not part of a packet


def packet(trade: Mapping[str, Any], sectors: Mapping[str, str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in PACKET_FIELDS:
        v = _clean(trade.get(k))
        if v is not None:
            out[k] = v
    when = str(trade.get("entry_time") or "")
    try:
        t = datetime.fromisoformat(when)
        out["entry_minute"] = t.strftime("%H:%M")
        out["weekday"] = t.strftime("%A")
        exp = str(trade.get("expiry") or "")[:10]
        if exp:
            out["days_to_expiry"] = (date.fromisoformat(exp) - t.date()).days
    except ValueError:
        pass
    sym = str(trade.get("symbol") or "").upper()
    if sectors and sectors.get(sym):
        out["sector"] = sectors[sym]
    for src, dst in (("dx_rvol", "opening_volume_x"), ("dx_lag_min", "minutes_since_first_signal")):
        v = _clean(trade.get(src))
        if v is not None:
            out[dst] = v
    block = trade.get("dx_s945_block")
    if block is not None and out.get("entry_minute", "00:00") >= "09:45":
        out["sector_in_0945_picks"] = not bool(block)
    bad = forbidden(out)
    if bad:
        raise ValueError(f"hindsight fields in a packet: {bad}")
    return out


def digest(p: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(p, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
