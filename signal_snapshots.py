"""Per-signal data recorder (data only - never affects a trade).

The old decision-evidence recorder stopped writing on 25 Aug 2026, so for every signal that was NOT traded we kept only its reason and outcome, not the numbers
it was judged on. This writes them from the scanner itself, once per cycle:

    data/signal_snapshots/<day>.csv         every entry-ready candidate: its status (A+ rule that held it back, V2 block, or passed) and the features it was judged on
    data/signal_snapshots/chain_<day>.csv   the option-chain summary (put/call ratio, ATM IV, open-interest walls, OI flow; see options_tags.py) for every candidate
                                            the scanner fetched a chain for - not just the ones that became trades

A row is written when a candidate's status changes, or at most every 5 minutes while it stays the same, so a signal that sits blocked for an hour is a dozen rows, not
two hundred. Any error is swallowed.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

EVERY_SECONDS = 300

SIGNAL_FIELDS = ["time", "symbol", "direction", "status", "passed", "stage", "setup_family", "selection_tier", "pivot_state", "score", "trade_quality", "movement_capture",
                 "trend_alignment", "clean_trend", "chase_risk", "ltp", "day_change_pct", "move_from_0915_pct", "gap_pct", "rel_volume", "rel_volume_15m", "tape_acc_5m",
                 "tape_acc_15m", "vwap_dist_pct", "rsi_5m", "adx_5m", "recent_5m_pct", "recent_10m_pct", "recent_15m_pct", "recent_30m_pct", "completed_5m_bars",
                 "range_position_pct", "below_day_high_pct", "above_day_low_pct", "trend_retention_pct", "atr_5m", "extension_atr", "fresh_15m", "fresh_30m", "fresh_day",
                 "opening_range_breakout", "r1", "s1", "reasons"]
CHAIN_FIELDS = ["time", "symbol", "direction", "oc_pcr_oi", "oc_pcr_vol", "oc_atm_iv", "oc_iv_skew", "oc_call_wall", "oc_call_wall_pct", "oc_put_wall", "oc_put_wall_pct",
                "oc_room_pct", "oc_wall_close", "oc_flow", "oc_flow_aligned", "oc_k_strike", "oc_k_ltp", "oc_k_spread_pct", "oc_k_vol", "oc_k_oi",
                "oc_k_oi_chg_pct", "oc_k_run_pct", "oc_k_delta", "oc_k_theta_pct_day", "oc_k_move_for_10", "oc_iv_rank",
                "fp_gamma_wall", "fp_gamma_wall_dist_pct", "fp_gamma_ahead_strike", "fp_gamma_ahead_share", "fp_oi_win_min", "fp_oi_win_pct", "fp_oi_flat"]


def _g(c: Any, name: str, default: Any = "") -> Any:
    v = getattr(c, name, default)
    return default if v is None else v


def _num(v: Any, nd: int = 3) -> Any:
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return ""


def signal_row(c: Any, when: datetime, passed: bool) -> dict[str, Any]:
    fresh = lambda a, b: int(bool(_g(c, a, False)) or bool(_g(c, b, False)))               # noqa: E731 - high or low side
    return {
        "time": when.isoformat(timespec="seconds"), "symbol": _g(c, "symbol"), "direction": _g(c, "direction"),
        "status": "PASSED_ALL_GATES" if passed else (str(_g(c, "paper_trade_status", "")) or "HELD_BACK"), "passed": int(passed),
        "stage": _g(c, "stage"), "setup_family": _g(c, "setup_family"), "selection_tier": _g(c, "selection_tier"), "pivot_state": _g(c, "pivot_state"),
        "score": _num(_g(c, "score"), 2), "trade_quality": _num(_g(c, "trade_quality_score"), 2), "movement_capture": _num(_g(c, "movement_capture_score"), 2),
        "trend_alignment": _num(_g(c, "trend_alignment_score"), 2), "clean_trend": _num(_g(c, "clean_trend_score"), 2), "chase_risk": _num(_g(c, "chase_risk_score"), 2),
        "ltp": _num(_g(c, "ltp"), 2), "day_change_pct": _num(_g(c, "day_change_percent"), 2), "move_from_0915_pct": _num(_g(c, "move_from_0915_open_percent"), 2),
        "gap_pct": _num(_g(c, "gap_percent"), 2), "rel_volume": _num(_g(c, "relative_volume"), 2), "rel_volume_15m": _num(_g(c, "recent_relative_volume_15m"), 2),
        "tape_acc_5m": _num(_g(c, "tape_volume_acceleration_5m"), 2), "tape_acc_15m": _num(_g(c, "tape_volume_acceleration_15m"), 2),
        "vwap_dist_pct": _num(_g(c, "vwap_distance_percent"), 3), "rsi_5m": _num(_g(c, "rsi14_5m"), 1), "adx_5m": _num(_g(c, "adx14_5m"), 1),
        "recent_5m_pct": _num(_g(c, "recent_move_5m_percent"), 3), "recent_10m_pct": _num(_g(c, "recent_move_10m_percent"), 3),
        "recent_15m_pct": _num(_g(c, "recent_move_15m_percent"), 3), "recent_30m_pct": _num(_g(c, "recent_move_30m_percent"), 3),
        "completed_5m_bars": _g(c, "completed_5m_bars"), "range_position_pct": _num(_g(c, "range_position_percent"), 1),
        "below_day_high_pct": _num(_g(c, "below_day_high_percent"), 2), "above_day_low_pct": _num(_g(c, "above_day_low_percent"), 2),
        "trend_retention_pct": _num(_g(c, "trend_retention_percent"), 1), "atr_5m": _num(_g(c, "atr_5m"), 3), "extension_atr": _num(_g(c, "extension_atr"), 2),
        "fresh_15m": fresh("fresh_15m_high", "fresh_15m_low"), "fresh_30m": fresh("fresh_30m_high", "fresh_30m_low"), "fresh_day": fresh("fresh_day_high", "fresh_day_low"),
        "opening_range_breakout": int(bool(_g(c, "opening_range_breakout", False))), "r1": _num(_g(c, "r1"), 2), "s1": _num(_g(c, "s1"), 2),
        "reasons": " | ".join(str(x) for x in (_g(c, "reasons", []) or []))[:240],
    }


class SnapshotWriter:
    def __init__(self, data_dir: Path | str) -> None:
        self.folder = Path(data_dir) / "signal_snapshots"
        self._last: dict[tuple[str, str, str], tuple[str, datetime]] = {}

    def _append(self, name: str, fields: list[str], rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / name
        new = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as h:
            w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerows(rows)

    def _due(self, kind: str, symbol: str, direction: str, status: str, when: datetime) -> bool:
        key = (kind, symbol, direction)
        prev = self._last.get(key)
        if prev is not None and prev[0] == status and (when - prev[1]).total_seconds() < EVERY_SECONDS:
            return False
        self._last[key] = (status, when)
        return True

    def signals(self, when: datetime, candidates: Iterable[Any], passed_keys: set[tuple[str, str]]) -> int:
        try:
            rows = []
            for c in candidates:
                passed = (str(_g(c, "symbol")), str(_g(c, "direction"))) in passed_keys
                row = signal_row(c, when, passed)
                if self._due("sig", str(row["symbol"]), str(row["direction"]), str(row["status"]), when):
                    rows.append(row)
            self._append(f"{when.date().isoformat()}.csv", SIGNAL_FIELDS, rows)
            return len(rows)
        except Exception:                                  # noqa: BLE001 - a recorder must never affect trading
            return 0

    def chain(self, when: datetime, symbol: str, direction: str, tags: dict[str, Any]) -> bool:
        try:
            if not tags or not self._due("chain", symbol, direction, "x", when):
                return False
            self._append(f"chain_{when.date().isoformat()}.csv", CHAIN_FIELDS, [{"time": when.isoformat(timespec="seconds"), "symbol": symbol, "direction": direction, **tags}])
            return True
        except Exception:                                  # noqa: BLE001
            return False
