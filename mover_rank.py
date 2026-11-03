"""Where a stock stands among all F&O stocks by move from today's open (display / research only; never affects a trade).

ranks_from_quotes() takes {symbol: (last price, day open)} and returns, for every stock, its rank as a GAINER (1 = biggest rise from the open) and as a LOSER (1 = biggest fall).
A call is judged by its gainer rank, a put by its loser rank: a put in the 3rd biggest loser that becomes the 1st and finishes 2nd shows as 3 -> 1 -> 2.
The paper journal stores that path on each trade (rank_entry, rank_now, rank_best, rank_worst, rank_close, rank_path) so the dashboard can show it.
"""

from __future__ import annotations

from typing import Any, Mapping


def ranks_from_quotes(quotes: Mapping[str, tuple[float, float]]) -> dict[str, dict[str, Any]]:
    rows = []
    for sym, (ltp, day_open) in quotes.items():
        try:
            ltp, day_open = float(ltp), float(day_open)
        except (TypeError, ValueError):
            continue
        if ltp > 0 and day_open > 0:
            rows.append((sym, (ltp / day_open - 1.0) * 100.0))
    rows.sort(key=lambda r: (-r[1], r[0]))
    n = len(rows)
    return {sym: {"gain": i + 1, "loss": n - i, "from_open": round(mv, 3), "n": n} for i, (sym, mv) in enumerate(rows)}
