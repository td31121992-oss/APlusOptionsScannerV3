"""Entry quality gate: take only the few best setups of the day (SHADOW by default, ENFORCE on request; nothing here ever exits a trade).

Each candidate gets a score out of 7 from tags that already exist at entry:

    +2  rrg_aligned           the stock's sector rotation (RRG quadrant) agrees with the trade's direction          (REQUIRED when APLUS_QUALITY_REQUIRE_RRG=1, the default)
    +1  chase risk is 0       the scanner's own chase_risk_score is zero
    +1  not at the extreme    the stock is not sitting in the last 10% of the day's range in our direction (ctx_range_pos <= 0.9)
    +1  higher timeframes     3 or more of 15m / 30m / 1h / daily agree with the trade (tr_htf_n >= 3)
    +1  tape agrees           the last 5 minutes of aggressor volume favour us (tk_delta5_dir > 0)
    +1  market not against    the Nifty brake would not block it (mb_would_block == 0)

A candidate passes when the score is at least APLUS_QUALITY_MIN_SCORE (default 6) AND (rrg required) its sector rotation is aligned AND fewer than APLUS_QUALITY_MAX_PER_DAY
(default 6) passing trades have already been opened today. A missing tag earns no point.

    APLUS_QUALITY_GATE_MODE   OFF | SHADOW (default: tags only) | ENFORCE (a candidate that does not pass is not traded)
    q_score, q_pass, q_missing, q_rank_today are recorded on the candidate / trade.

History behind the defaults (5 days, 77 trades with the first three tags): the strict version (rrg + chase 0 + range <= 0.9) kept 9 trades (+Rs 15.9k, 67% won, 78% reached
+10%) and blocked 68 (-Rs 110.8k). On 22 Oct a score of 6+ would have passed 7 of 21 trades, closed -Rs 9.9k against -Rs 52.7k for all of them. Small samples: shadow first.
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Mapping


def mode() -> str:
    v = os.getenv("APLUS_QUALITY_GATE_MODE", "SHADOW").strip().upper()
    return v if v in {"OFF", "SHADOW", "ENFORCE"} else "SHADOW"


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _true(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "1.0")


def score(rec: Mapping[str, Any]) -> tuple[int, list[str]]:
    pts, missing = 0, []

    def earn(ok: bool | None, n: int, name: str) -> None:
        nonlocal pts
        if ok:
            pts += n
        elif ok is None:
            missing.append(name)

    earn(_true(rec.get("rrg_aligned")) if rec.get("rrg_aligned") not in (None, "") else None, 2, "rrg")
    cr = _f(rec.get("chase_risk_score"))
    earn(None if cr is None else cr == 0, 1, "chase")
    rp = _f(rec.get("ctx_range_pos"))
    earn(None if rp is None else rp <= 0.9, 1, "range")
    hn = _f(rec.get("tr_htf_n"))
    earn(None if hn is None else hn >= 3, 1, "htf")
    td = _f(rec.get("tk_delta5_dir"))
    earn(None if td is None else td > 0, 1, "tape")
    mb = _f(rec.get("mb_would_block"))
    earn(None if mb is None else mb == 0, 1, "market")
    return pts, missing


def passes_so_far(trades: Iterable[Mapping[str, Any]], day: str) -> int:
    return sum(1 for t in trades if str(t.get("entry_time") or "")[:10] == day and _true(t.get("q_pass")))


def evaluate(rec: Mapping[str, Any], opened_today_passing: int) -> dict[str, Any]:
    sc, missing = score(rec)
    need_rrg = os.getenv("APLUS_QUALITY_REQUIRE_RRG", "1").strip() != "0"
    ok = sc >= _int("APLUS_QUALITY_MIN_SCORE", 6) and (_true(rec.get("rrg_aligned")) or not need_rrg) and opened_today_passing < _int("APLUS_QUALITY_MAX_PER_DAY", 6)
    return {"q_score": sc, "q_pass": int(ok), "q_missing": "|".join(missing), "q_rank_today": opened_today_passing + 1}
