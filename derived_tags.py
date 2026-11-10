"""Derived shadow tags, worked out after the close from what was recorded (read-only; no trading effect; the scanner is not touched).

Two entry filters from the 10 Nov 2026 replay (entry_filter_replay.py) are tracked forward, so they collect evidence next to the other rules instead of being judged on the same trades they were
chosen from:

    dx_spread_wide   the option's bid-ask spread at entry was over 1% of the price (recorded on every trade as spread_percent)
    dx_mom5_block    five minutes after the entry signal the option was NOT at or above the entry price, or the trade was already closed by then (it would not have been taken).
                     Worked out from the option ticks the recorder saved in data/option_ticks/<day>/; None when no ticks exist for the contract.
    dx_would_block   either of the two (the "both" filter)

Nothing here blocks anything; shadow_scoreboard.py lists them as rules ("would block") and the registry date gives the forward-only evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from entry_filter_replay import load_ticks, seconds_of

ROOT = Path(__file__).resolve().parent
SPREAD_LIMIT = 1.0                                           # percent
WAIT_MINUTES = 5


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def spread_wide(trade: Mapping[str, Any]) -> bool | None:
    s = _f(trade.get("spread_percent"))
    return None if s is None else s > SPREAD_LIMIT


def momentum_block(trade: Mapping[str, Any], ticks: Sequence[tuple[float, float, float]] | None, wait: int = WAIT_MINUTES) -> bool | None:
    """True = would not have been taken (closed before the check, or not at/above the entry price at the check); False = confirmed; None = cannot tell."""
    entry = _f(trade.get("entry_price"))
    t0 = seconds_of(trade.get("entry_time"))
    if not ticks or entry is None or entry <= 0 or t0 is None:
        return None
    check = t0 + wait * 60
    t_exit = seconds_of(trade.get("exit_time"))
    if t_exit is not None and t_exit <= check and str(trade.get("exit_time"))[:10] == str(trade.get("entry_time"))[:10]:
        return True
    upto = [x for x in ticks if x[0] <= check]
    if not upto or not any(x[0] >= check for x in ticks):
        return None
    return upto[-1][1] < entry


def tags_for(trade: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    day = str(trade.get("entry_time") or "")[:10]
    wide = spread_wide(trade)
    block = momentum_block(trade, load_ticks(str(trade.get("option_security_id")), day, root) if day else None)
    out: dict[str, Any] = {"dx_spread_wide": wide, "dx_mom5_block": block}
    known = [v for v in (wide, block) if v is not None]
    out["dx_would_block"] = None if not known else any(known)
    return out


def enrich(trades: Sequence[MutableMapping[str, Any]], root: Path = ROOT) -> None:
    """Add the derived tags to each trade dict in place. A trade whose tags cannot be worked out is left without them."""
    for t in trades:
        try:
            t.update(tags_for(t, root))
        except Exception:                                    # noqa: BLE001 - a missing / damaged tick file must never stop the report
            continue
