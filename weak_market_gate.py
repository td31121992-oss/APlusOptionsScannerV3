"""'No calls into a weak market' gate (SHADOW by default; ENFORCE on request; nothing here ever exits a trade).

A call (CE, BULLISH) is a bet that the market and the stock go up. When the market is weak or being sold it works against us, unless the stock has its own strong reason: real buying by big
players, or fresh bullish news. Puts are not affected. Evaluated from tags the scanner already puts on the candidate:

    weak market (any one is enough)
        breadth     fewer than APLUS_WEAKMKT_BREADTH_PCT (default 45) percent of F&O stocks are above their own VWAP        (bs_breadth_pct, the share on our side of VWAP, for a call)
        Nifty       the Nifty is at or below APLUS_WEAKMKT_NIFTY_PCT (default -0.20) percent from the open                    (rule_nifty_pct_open)
        brake       the market-brake rule says the market is against the trade                                                (mb_would_block)
    override (either one lets the call through)
        NEWS        a BULLISH catalyst of HIGH or MEDIUM confidence, at most APLUS_WEAKMKT_NEWS_HOURS (default 24) hours old   (cat_dir, cat_conf, cat_age_h)
        BIG_BUYING  big prints are WITH the trade (>= APLUS_WEAKMKT_BIG_CR crore net in 15 minutes, default 1.0) and at least 3 of the 4 confirmations agree      (bp_align, bp_net15_dir_cr, bp_conf)

    wk_weak        1 when the market looks weak (calls only; blank for puts)
    wk_why         which of the three conditions fired
    wk_override    NEWS / BIG_BUYING / ""
    wk_ok          0 when the rule would block (a call in a weak market with no override), else 1.  Missing data is never "weak".
    APLUS_WEAKMKT_CE_MODE   OFF | SHADOW (default: tags only) | ENFORCE (a blocked candidate is not traded)

Evidence (1-22 Oct, 69 paper calls): calls entered with fewer than 45% of stocks above VWAP won 19% and lost Rs 37.9k (26 trades; under 30%: 12 trades, -Rs 24k). Calls ALSO lost when more than
60% of stocks were above VWAP (29 trades, 14% won, -Rs 47k): buying into an extended market is a separate problem this rule does not touch.
"""

from __future__ import annotations

import os
from typing import Any, Mapping


def mode() -> str:
    v = os.getenv("APLUS_WEAKMKT_CE_MODE", "SHADOW").strip().upper()
    return v if v in {"OFF", "SHADOW", "ENFORCE"} else "SHADOW"


def _num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in {"1", "1.0", "true", "yes"}


def evaluate(rec: Mapping[str, Any], direction: str) -> dict[str, Any]:
    """Tags for a candidate. Puts and anything without data return {} (never blocked)."""
    if str(direction).upper() != "BULLISH":
        return {}
    why = []
    breadth = _f(rec.get("bs_breadth_pct"))                       # for a call: share of stocks ABOVE their VWAP
    if breadth is not None and breadth < _num("APLUS_WEAKMKT_BREADTH_PCT", 45.0):
        why.append(f"breadth {breadth:.0f}%")
    nifty = _f(rec.get("rule_nifty_pct_open"))
    if nifty is not None and nifty <= _num("APLUS_WEAKMKT_NIFTY_PCT", -0.20):
        why.append(f"nifty {nifty:+.2f}%")
    if _truthy(rec.get("mb_would_block")):
        why.append("brake")
    out: dict[str, Any] = {"wk_weak": int(bool(why)), "wk_why": "|".join(why), "wk_override": "", "wk_ok": 1}
    if not why:
        return out
    age = _f(rec.get("cat_age_h"))
    if str(rec.get("cat_dir")).upper() == "BULLISH" and str(rec.get("cat_conf")).upper() in {"HIGH", "MEDIUM"} and (age is None or age <= _num("APLUS_WEAKMKT_NEWS_HOURS", 24.0)):
        out["wk_override"] = "NEWS"
    elif str(rec.get("bp_align")).upper() == "WITH" and (_f(rec.get("bp_net15_dir_cr")) or 0.0) >= _num("APLUS_WEAKMKT_BIG_CR", 1.0) and (_f(rec.get("bp_conf")) or 0.0) >= 3:
        out["wk_override"] = "BIG_BUYING"
    out["wk_ok"] = int(bool(out["wk_override"]))
    return out
