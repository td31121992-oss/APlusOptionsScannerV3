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

    dx_e_wait5       net P&L (Rs) under "wait 5 minutes after the signal, buy at the ask only if the option is at or above the signal price" (0.0 = the rule would not have taken it).
                     Taken from the journal's live record (opt5 / opt5_ask, set by paper_trade_journal.record_opt5) when present, otherwise from the recorded ticks.
    dx_s945_block / dx_s945_top5_block / dx_s945_top3_block / dx_s945_abs_block / dx_s945p_block / dx_s945p_top5_block
                     the "observe until 09:45" strategy (sector_rank945.py, 10 Nov 2026): True = the strategy would NOT have taken the trade (before 09:45, wrong side for its sector, or not
                     among the strongest N movers). s945 = sectors ranked by the move since the 09:15 open, s945p = since the previous close; top5 / top3 = only the strongest 5 / 3 movers of the
                     sector on the trade's side; abs = the sector must also be moving the right way. None when the day has no candle file yet.

    dx_lag_min / dx_lag_early_block / dx_lag_window_block
                     minutes from the stock's FIRST entry-ready signal of the day (data/missed_opportunities/<day>/signals.csv, column first_ready) to this trade's entry. 10 Nov 2026 study of
                     311 trades: entered within 10 minutes of the first signal lost (-Rs 91,700 over 160 trades), 11-30 minutes after made +Rs 34,123 (84 trades), later lost a little.
                     early_block = entered 10 minutes or less after the first signal; window_block = not entered 11-30 minutes after it. None when there is no signal row for the trade.

    dx_rvol / dx_rvol_quiet_block / dx_rvol3_block
                     relative opening volume (rvol_replay.py, 10 Nov 2026): the traded stock's first 5-minute volume divided by its average over the previous 14 sessions (known from 09:20).
                     quiet_block = RVOL below 1.0 (a quiet opening: 193 trades lost Rs 164,681 in the study); rvol3_block = RVOL below 3 (only "stocks in play" kept: 64 trades, +Rs 48,191).
                     The opening bars come from data/cache/rvol_first_bars.json (Sep-Nov history) plus each day's stored candle file; None when the history is too short.

Nothing here blocks anything; shadow_scoreboard.py lists them as rules ("would block") and the registry date gives the forward-only evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from entry_filter_replay import load_ticks, seconds_of
from ladder_search import ladder_exit
from sector_rank945 import allowed, day_picks, sector_labels

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


_LABELS: dict[str, dict[str, str]] = {}
_AGENT: dict[str, dict[str, str]] = {}


def ai_skip_tag(trade: Mapping[str, Any], root: Path = ROOT, agent: str = "claude") -> bool | None:
    """True when the shadow AI trading agent (agent_run.py, ledger data/ai_agent/decisions.jsonl) said SKIP for this trade, False for TAKE, None when it has not judged it."""
    key = f"{root}|{agent}"
    if key not in _AGENT:
        import json

        decisions: dict[str, str] = {}
        try:
            for line in (root / "data" / "ai_agent" / "decisions.jsonl").read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                if r.get("agent") == agent and r.get("decision") in ("TAKE", "SKIP"):
                    decisions[str(r.get("paper_trade_id"))] = r["decision"]
        except (OSError, ValueError):
            pass
        _AGENT[key] = decisions
    d = _AGENT[key].get(str(trade.get("paper_trade_id")))
    return None if d is None else d == "SKIP"
_OPENING: dict[str, dict[str, dict[str, dict[str, float]]]] = {}


def opening_history(root: Path = ROOT) -> dict[str, dict[str, dict[str, float]]]:
    """symbol -> day -> {v5, o5, c5, v15}: the cached Sep-Nov opening bars, extended with the first bars found in each stored 5-minute candle file (data/pattern_log/candles)."""
    key = str(root)
    if key in _OPENING:
        return _OPENING[key]
    import json

    hist: dict[str, dict[str, dict[str, float]]] = {}
    try:
        hist = json.loads((root / "data" / "cache" / "rvol_first_bars.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    folder = root / "data" / "pattern_log" / "candles"
    for p in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            symbols = json.loads(p.read_text(encoding="utf-8")).get("symbols", {})
        except (OSError, ValueError):
            continue
        for sym, d in symbols.items():
            mins, vols = d.get("minute") or [], d.get("volume") or []
            if 555 not in mins or len(vols) != len(mins):
                continue
            i = mins.index(555)
            hist.setdefault(sym.upper(), {})[p.stem] = {"v5": float(vols[i] or 0), "o5": float((d.get("open") or [0] * (i + 1))[i]), "c5": float((d.get("close") or [0] * (i + 1))[i]),
                                                        "v15": float(sum(vols[j] or 0 for j, m in enumerate(mins) if 555 <= m <= 565))}
    _OPENING[key] = hist
    return hist


def rvol_tags(trade: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    from rvol_replay import rvol

    day, sym = str(trade.get("entry_time") or "")[:10], str(trade.get("symbol") or "").upper()
    r = rvol(opening_history(root).get(sym, {}), day) if day and sym else None
    return {"dx_rvol": None if r is None else round(r, 2), "dx_rvol_quiet_block": None if r is None else r < 1.0, "dx_rvol3_block": None if r is None else r < 3.0}
_SIGNALS: dict[tuple[str, str], dict[tuple[str, str], int]] = {}
LAG_EARLY_MAX = 10                                           # minutes: entered this soon after the first signal counts as early
LAG_WINDOW = (11, 30)                                        # minutes: the window that was profitable in the 10 Nov study


def first_ready_minutes(day: str, root: Path = ROOT) -> dict[tuple[str, str], int]:
    """(SYMBOL, BULLISH|BEARISH) -> minute of day of the first entry-ready signal, from the day's signals.csv; empty when the file is not there (yet)."""
    key = (str(root), day)
    if key in _SIGNALS:
        return _SIGNALS[key]
    out: dict[tuple[str, str], int] = {}
    try:
        import csv

        with (root / "data" / "missed_opportunities" / day / "signals.csv").open(encoding="utf-8", newline="") as h:
            for row in csv.DictReader(h):
                try:
                    hh, mm = str(row["first_ready"]).split(":")[:2]
                    k = (str(row["symbol"]).upper(), str(row["direction"]).upper())
                    out[k] = min(out.get(k, 99999), int(hh) * 60 + int(mm))
                except (KeyError, ValueError):
                    continue
    except OSError:
        return {}                                             # not written yet: do not cache, a later run may find it
    _SIGNALS[key] = out
    return out


def lag_tags(trade: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    none = {"dx_lag_min": None, "dx_lag_early_block": None, "dx_lag_window_block": None}
    day, hhmm = str(trade.get("entry_time") or "")[:10], str(trade.get("entry_time") or "")[11:16]
    direction = str(trade.get("direction") or "").upper() or {"CE": "BULLISH", "PE": "BEARISH"}.get(str(trade.get("option_type") or "").upper(), "")
    try:
        entered = int(hhmm[:2]) * 60 + int(hhmm[3:5])
    except ValueError:
        return none
    first = first_ready_minutes(day, root).get((str(trade.get("symbol") or "").upper(), direction)) if day else None
    if first is None or entered < first:
        return none
    lag = entered - first
    return {"dx_lag_min": lag, "dx_lag_early_block": lag <= LAG_EARLY_MAX, "dx_lag_window_block": not (LAG_WINDOW[0] <= lag <= LAG_WINDOW[1])}


def sector_tags(trade: Mapping[str, Any], root: Path = ROOT) -> dict[str, bool | None]:
    day, hhmm = str(trade.get("entry_time") or "")[:10], str(trade.get("entry_time") or "")[11:16]
    names = ("dx_s945_block", "dx_s945_top5_block", "dx_s945_top3_block", "dx_s945_abs_block", "dx_s945p_block", "dx_s945p_top5_block")
    try:
        minute = int(hhmm[:2]) * 60 + int(hhmm[3:5])
    except ValueError:
        return {n: None for n in names}
    labels = _LABELS.setdefault(str(root), sector_labels(root))
    picks = day_picks(day, root, labels) if day else {}
    sym, side = str(trade.get("symbol") or ""), str(trade.get("option_type") or "")

    def block(basis: str, top_n: int | None, absolute: bool = False) -> bool | None:
        ok = allowed(sym, side, minute, picks.get(basis), labels, top_n, absolute)
        return None if ok is None else not ok

    return dict(zip(names, (block("open", None), block("open", 5), block("open", 3), block("open", None, True), block("prev", None), block("prev", 5))))


FORWARD_VARIANTS = tuple(EXIT_VARIANTS) + ("dx_e_wait5",)


def wait5_pnl(trade: Mapping[str, Any], ticks: Sequence[tuple[float, float, float]] | None, wait: int = WAIT_MINUTES) -> float | None:
    """Rs the trade would have made under 'wait 5 minutes after the signal, buy at the ask only if the option is at or above the signal price, sell where the trade really ended':
    0.0 when the rule would not have taken it, None when that cannot be told. Uses the journal's own live record (opt5 / opt5_ask) when there is one, else the recorded ticks."""
    entry, qty, exit_px = _f(trade.get("entry_price")), _f(trade.get("quantity")), _f(trade.get("exit_price"))
    if not entry or not qty or not exit_px or entry <= 0 or qty <= 0 or exit_px <= 0:
        return None
    gross, net = _f(trade.get("gross_pnl")), _f(trade.get("net_pnl"))
    cost = gross - net if gross is not None and net is not None else 214.0
    live = str(trade.get("opt5") or "").upper()
    if live == "FAILED":
        return 0.0
    if live == "HELD":
        ask = _f(trade.get("opt5_ask")) or _f(trade.get("opt5_price"))
        return None if not ask else round((exit_px - ask) * qty - cost, 2)
    block = momentum_block(trade, ticks, wait)
    if block is None:
        return None
    if block:
        return 0.0
    t0 = seconds_of(trade.get("entry_time"))
    after = [x for x in (ticks or []) if t0 is not None and x[0] >= t0 + wait * 60]
    return round((exit_px - after[0][2]) * qty - cost, 2) if after else None


def tags_for(trade: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    day = str(trade.get("entry_time") or "")[:10]
    wide = spread_wide(trade)
    ticks = load_ticks(str(trade.get("option_security_id")), day, root) if day else None
    block = momentum_block(trade, ticks)
    out: dict[str, Any] = {"dx_spread_wide": wide, "dx_mom5_block": block, **exit_variants(trade, ticks), "dx_e_wait5": wait5_pnl(trade, ticks), **sector_tags(trade, root), **lag_tags(trade, root), **rvol_tags(trade, root), "dx_ai_skip": ai_skip_tag(trade, root)}
    known = [v for v in (wide, block) if v is not None]
    out["dx_would_block"] = None if not known else any(known)
    return out


CROWD_NTH = 4                                        # the 4th trade of a day on the same side in one NSE sector is "crowded" (replay 22 Sep - 12 Nov: 57 trades, -Rs 54k; 10 of 13 days lost)
EARLY_BEFORE = "09:35"                               # entered before this = "too early" (replay: 106 trades, -Rs 96.9k, 25% wins)


def crowd_tags(trades: Sequence[MutableMapping[str, Any]], root: Path = ROOT) -> None:
    """dx_crowd4: this is the 4th+ trade of the day on the same side in the same NSE sector (earlier trades counted in entry order). dx_early0935: entered before 09:35.
    Both are would-block shadow tags: nothing is blocked. Counted among the trades passed in, so the figure is exact for the full history and a lower bound for a partial list."""
    try:
        labels = _LABELS.setdefault(str(root), sector_labels(root))
    except Exception:                                                       # noqa: BLE001
        labels = {}
    seen: dict[tuple[str, str, str], int] = {}
    for t in sorted(trades, key=lambda x: str(x.get("entry_time") or "")):
        day, hhmm = str(t.get("entry_time") or "")[:10], str(t.get("entry_time") or "")[11:16]
        sector = labels.get(str(t.get("symbol") or ""))
        if not day or not sector:
            t["dx_crowd4"] = None
        else:
            key = (day, str(t.get("option_type") or ""), str(sector))
            seen[key] = seen.get(key, 0) + 1
            t["dx_crowd4"] = seen[key] >= CROWD_NTH
        t["dx_early0935"] = (hhmm < EARLY_BEFORE) if hhmm else None


def enrich(trades: Sequence[MutableMapping[str, Any]], root: Path = ROOT) -> None:
    """Add the derived tags to each trade dict in place. A trade whose tags cannot be worked out is left without them."""
    for t in trades:
        try:
            t.update(tags_for(t, root))
        except Exception:                                    # noqa: BLE001 - a missing / damaged tick file must never stop the report
            continue
    try:
        crowd_tags(trades, root)
    except Exception:                                        # noqa: BLE001
        pass
