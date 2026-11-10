"""Derived shadow tags, worked out after the close from what was recorded (read-only; no trading effect; the scanner is not touched).

Two entry filters from the 10 Nov 2026 replay (entry_filter_replay.py) are tracked forward, so they collect evidence next to the other rules instead of being judged on the same trades they were
chosen from:

    dx_spread_wide   the option's bid-ask spread at entry was over 1% of the price (recorded on every trade as spread_percent)
    dx_mom5_block    five minutes after the entry signal the option was NOT at or above the entry price, or the trade was already closed by then (it would not have been taken).
                     Worked out from the option ticks the recorder saved in data/option_ticks/<day>/; None when no ticks exist for the contract.
    dx_would_block   either of the two (the "both" filter)
    dx_x_wide25 / dx_x_wide25_t30g30 / dx_x_wide25_t30g40
                     net P&L (Rs, after the trade's own round-trip cost) the trade WOULD have made under an alternative exit ladder, replayed tick by tick from the recorded option
                     ticks (ladder_search.py, 10 Nov 2026): a -25% initial stop with no break-even step and no trail (wide25), or with a late trail that starts at +30% and gives back
                     at most 30% / 40% of the peak gain. The live ladder is not changed; trade_archive.py totals these against the real result, forward from 10 Nov.

Nothing here blocks anything; shadow_scoreboard.py lists them as rules ("would block") and the registry date gives the forward-only evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from entry_filter_replay import load_ticks, seconds_of
from ladder_search import ladder_exit

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


EXIT_VARIANTS: dict[str, tuple[float, float | None, tuple[float, float] | None]] = {          # name -> (initial stop %, break-even trigger %, trail (start %, give-back share))
    "dx_x_wide25": (25.0, None, None),
    "dx_x_wide25_t30g30": (25.0, None, (30.0, 0.30)),
    "dx_x_wide25_t30g40": (25.0, None, (30.0, 0.40)),
}


def exit_variants(trade: Mapping[str, Any], ticks: Sequence[tuple[float, float, float]] | None) -> dict[str, float | None]:
    """Rs the trade would have made under each alternative ladder, or None for each when the ticks cannot say."""
    entry, qty, t0 = _f(trade.get("entry_price")), _f(trade.get("quantity")), seconds_of(trade.get("entry_time"))
    if not ticks or not entry or entry <= 0 or not qty or qty <= 0 or t0 is None:
        return {name: None for name in EXIT_VARIANTS}
    path = [(sec, ltp) for sec, ltp, _ in ticks if sec >= t0]
    if len(path) < 3:
        return {name: None for name in EXIT_VARIANTS}
    gross, net = _f(trade.get("gross_pnl")), _f(trade.get("net_pnl"))
    cost = gross - net if gross is not None and net is not None else 214.0
    return {name: round((ladder_exit(entry, path, stop, be, trail) - entry) * qty - cost, 2) for name, (stop, be, trail) in EXIT_VARIANTS.items()}


def tags_for(trade: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    day = str(trade.get("entry_time") or "")[:10]
    wide = spread_wide(trade)
    ticks = load_ticks(str(trade.get("option_security_id")), day, root) if day else None
    block = momentum_block(trade, ticks)
    out: dict[str, Any] = {"dx_spread_wide": wide, "dx_mom5_block": block, **exit_variants(trade, ticks)}
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
