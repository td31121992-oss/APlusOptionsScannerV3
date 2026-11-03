"""Entry-gate shadow: which of four candidate gates WOULD have blocked a trade (SHADOW ONLY - recorded, never used to allow or block anything).

Found on the 81 closed trades since 1 Oct 2026 and checked on the 59 of 22-30 Sep (the 09:30 rule and a 30+ premium cap failed that check and are not here):

    gs_premium80   option bought at 80 or more                   (13% won; kept its sign on the check period)
    gs_ce_early    a CALL entered before 10:00                   (19% won; kept its sign)
    gs_chasing     the stock already moved 0.3%+ in OUR direction in the 15 minutes before entry
    gs_est_trend   setup family ESTABLISHED_TREND                (19% won; roughly neutral on the check period)
    gs_daily_weak  the DAILY trend is not at least 0.6 in the trade's direction (added 16 Oct 2026 from the daily-alignment test: on traded signals
                   daily 0.6+ closed +14.0% (24 trades, 7 of 8 days positive) against -1.2% (58 trades) below it; on all signals the effect was small)
    gs_daily_signed the signed daily score itself
    gs_count       how many of the four original gates apply (gs_daily_weak is counted separately)

Quality gates added 28 Oct 2026 ("fewer, better trades": on the 280 closed paper trades the all-in friction is ~3.6% of the premium per trade, so a trade must earn clearly more than that):

    gs_spread_pct / gs_spread_wide   the option's bid-ask spread at entry, % of the ask; wide = more than 1.0% (the live selector allows 2%). Trades entered at 0.5-1% netted -1.4% (14 trades,
                                     50% won) against -5.6% at 1.5-2% (41 trades, 32% won)
    gs_clean_low                     clean_trend_score below 96 (its top fifth on those trades: +0.8% gross, 41% won, against 32% overall)
    gs_early945                      the entry was before 09:45 (added 28 Oct 2026: 78 trades from 6-27 Oct lost -1,320 each, 23% won, t=-3.4, negative in both halves of the period; any setup, either side)
    gs_day_cap_over                  this was the 6th or later entry of the day (set by the journal once the day's entry order is known; 13 entries a day on average, up to 46)
    gs_q_block                       how many of the three quality gates would have blocked the entry (the cap is counted when it is known); gs_q_pass = none of them
Added 29 Oct 2026:

    gs_lowprice                      the option was bought below 10 (302 closed paper trades: under 10 averaged -1,128 a trade, 24% won, 68 trades, against -588 at 10-20; thin, cheap options are the ones the live
                                     selector often cannot find an executable contract for, e.g. SAIL)
    gs_why / gs_why_n                the names of every shadow gate that applies to the trade (premium80, ce_early, chasing, est_trend, daily_weak, early945, spread_wide, clean_low, lowprice, day_cap_over)
                                     and how many - the "which gate would have blocked this trade" column for judging each gate trade by trade
    gs_mkt_pct / gs_bear_weakmkt     Nifty's % move since the open at entry, and whether this is a PUT while the market is flat or falling (Nifty below +0.2%). On 6 days of signal episodes (gate_outcome_check,
                                     19-28 Oct, 1,629 episodes) bearish signals in a flat / falling market moved against the trade by about 1.2-1.9% in the following hour (212 and 63 episodes, 2-3 days, so
                                     a lead from a bounce regime, not a proven rule); 153 of the 225 trades that passed every live gate were bearish
All three are SHADOW: nothing is blocked. Judge them on forward data (about 10 trading days) by comparing the net result of "pass" and "blocked" trades.

`tags()` is called once at entry by the scanner; `flags()` is the same logic for the nightly review (gate_review.py), which applies it to every signal.
"""

from __future__ import annotations

from typing import Any

PREMIUM_MIN = 80.0
CE_EARLY_BEFORE_MIN = 10 * 60
CHASE_PCT = 0.3
DAILY_MIN = 0.6
SPREAD_MAX_PCT = 1.0
CLEAN_MIN = 96.0
DAY_CAP = 5
EARLY_BEFORE_MIN = 9 * 60 + 45
LOWPRICE_MAX = 10.0
BEAR_WEAK_MKT_BELOW = 0.2
WHY_GATES = ("premium80", "ce_early", "chasing", "est_trend", "daily_weak", "early945", "spread_wide", "clean_low", "lowprice", "bear_weakmkt", "day_cap_over")


def why(tag_dict: Any) -> dict[str, Any]:
    """gs_why / gs_why_n from a dict that carries the gs_* tags (a trade record or the output of tags()); re-run when the day-cap tag arrives later."""
    names = [g for g in WHY_GATES if tag_dict.get(f"gs_{g}") is True]
    return {"gs_why": "+".join(names), "gs_why_n": len(names)}


def over_cap(day_entry_rank: Any) -> bool | None:
    """True when this entry is later than the DAY_CAP-th of the day (None when the rank is not known)."""
    try:
        return bool(int(float(day_entry_rank)) > DAY_CAP)
    except (TypeError, ValueError):
        return None


def quality_tags(bid: Any, ask: Any, clean_score: Any) -> dict[str, Any]:
    """The two quality gates that can be judged at entry time (the day cap is added later by the journal)."""
    out: dict[str, Any] = {}

    def num(v: Any) -> float | None:
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None
    b, a, cs = num(bid), num(ask), num(clean_score)
    wide = low = None
    if b is not None and a is not None and a > 0 and a >= b > 0:
        sp = (a - b) / a * 100.0
        out["gs_spread_pct"] = round(sp, 2)
        wide = out["gs_spread_wide"] = bool(sp > SPREAD_MAX_PCT)
    if cs is not None:
        low = out["gs_clean_low"] = bool(cs < CLEAN_MIN)
    known = [v for v in (wide, low) if v is not None]
    if known:
        out["gs_q_block"] = int(sum(known))
        out["gs_q_pass"] = bool(not any(known))
    return out


def flags(direction: str, option_price: float | None, minute_of_day: int | None, recent_move_15m_pct: float | None, setup_family: str | None = None) -> dict[str, bool | None]:
    bull = str(direction).upper() == "BULLISH"
    directional = None if recent_move_15m_pct is None else (recent_move_15m_pct if bull else -recent_move_15m_pct)
    return {
        "premium80": None if option_price is None or option_price <= 0 else bool(option_price >= PREMIUM_MIN),
        "ce_early": None if minute_of_day is None else bool(bull and minute_of_day < CE_EARLY_BEFORE_MIN),
        "chasing": None if directional is None else bool(directional > CHASE_PCT),
        "est_trend": None if setup_family in (None, "") else bool(str(setup_family).upper() == "ESTABLISHED_TREND"),
    }


def tags(direction: str, option_price: Any, minute_of_day: int | None, recent_move_15m_pct: Any, setup_family: Any, daily_score: Any = None,
         bid: Any = None, ask: Any = None, clean_score: Any = None, nifty_pct_open: Any = None) -> dict[str, Any]:
    try:
        def num(v: Any) -> float | None:
            try:
                return float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                return None

        f = flags(direction, num(option_price), minute_of_day, num(recent_move_15m_pct), str(setup_family or ""))
        out = {f"gs_{k}": v for k, v in f.items() if v is not None}
        out["gs_count"] = sum(1 for v in f.values() if v)             # the four original gates only: the tags below are counted separately
        if minute_of_day is not None:
            out["gs_early945"] = bool(minute_of_day < EARLY_BEFORE_MIN)
        ds = num(daily_score)
        if ds is not None:
            signed = ds if str(direction).upper() == "BULLISH" else -ds
            out["gs_daily_signed"] = round(signed, 3)
            out["gs_daily_weak"] = bool(signed < DAILY_MIN)
        op = num(option_price)
        if op is not None and op > 0:
            out["gs_lowprice"] = bool(op < LOWPRICE_MAX)
        npo = num(nifty_pct_open)
        if npo is not None:
            out["gs_mkt_pct"] = round(npo, 3)
            out["gs_bear_weakmkt"] = bool(str(direction).upper() == "BEARISH" and npo < BEAR_WEAK_MKT_BELOW)
        out.update(quality_tags(bid, ask, clean_score))
        out.update(why(out))
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}
