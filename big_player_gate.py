"""'Do not trade against the big players' gate (SHADOW by default; ENFORCE on request; nothing here ever exits a trade).

As retail traders we should not fight size. Using the live big-print totals (big_prints.py, the same data as the Big Players page) a candidate is tagged, in OUR direction (a call wants big
buying, a put wants big selling):

    bp_net15_dir_cr   big net buying (calls) / selling (puts) over the last 15 minutes in Rs crore; negative = the big prints are against us
    bp_net_dir_cr     the same for the whole day so far
    bp_n15            big prints in the last 15 minutes
    bp_align          WITH / AGAINST / NONE  (NONE: fewer than MIN_PRINTS big prints in 15 minutes, or a net smaller than AGAINST_CR either way)
    bp_conf           how many of the four independent signals agree with OUR direction: FUT (near-month future price and open interest), OPT (option premium on our side),
                      BOOK (resting bid vs ask size), TICK (net buying value by the tick rule); 0-4, blank when none could be read
    bp_ok             0 when bp_align is AGAINST (the rule would block), else 1.  Missing data never blocks.
    bp_reason         AGAINST_BIG_PLAYERS / WITH_BIG_PLAYERS / NO_BIG_PRINTS / NO_DATA

    APLUS_BIGPLAYER_GATE_MODE   OFF | SHADOW (default: tags only) | ENFORCE (a candidate with bp_ok = 0 is not traded)
    APLUS_BIGPLAYER_AGAINST_CR  0.25  (Rs crore of net big prints that counts as "against" / "with")      APLUS_BIGPLAYER_MIN_PRINTS  2

Evidence so far is one session (22 Oct, 177 detector events): with strong big-print flow behind the trade (>= Rs 1 crore net) the option reached +10% before -20% on 56% of events and was stopped
on 31%; with weak flow 44% and 56%. Only 10 events were against the flow (50 / 50), too few to judge, so this stays in SHADOW until more sessions are in.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
_LOCK = threading.Lock()
_MF: dict[str, Any] = {"at": 0.0, "day": None, "stocks": {}}


def mode() -> str:
    v = os.getenv("APLUS_BIGPLAYER_GATE_MODE", "SHADOW").strip().upper()
    return v if v in {"OFF", "SHADOW", "ENFORCE"} else "SHADOW"


def _num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def decide(net15_dir_cr: float, n15: int) -> tuple[str, str]:
    """(bp_align, bp_reason) from the 15-minute big net in OUR direction."""
    min_prints, against_cr = int(_num("APLUS_BIGPLAYER_MIN_PRINTS", 2)), _num("APLUS_BIGPLAYER_AGAINST_CR", 0.25)
    if n15 < min_prints or abs(net15_dir_cr) < against_cr:
        return "NONE", "NO_BIG_PRINTS"
    return ("WITH", "WITH_BIG_PLAYERS") if net15_dir_cr > 0 else ("AGAINST", "AGAINST_BIG_PLAYERS")


def _money_flow_stock(root: Path, day: str, symbol: str) -> Mapping[str, Any]:
    with _LOCK:
        if _MF["day"] != day or time.time() - _MF["at"] > 20:
            try:
                import money_flow

                _MF.update(day=day, at=time.time(), stocks={s["symbol"]: s for s in (money_flow.payload(window=15, root=root).get("stocks") or [])})
            except Exception:                              # noqa: BLE001
                _MF.update(day=day, at=time.time(), stocks={})
        return _MF["stocks"].get(symbol, {})


def evaluate(symbol: str, direction: str, now: datetime, root: Path = ROOT) -> dict[str, Any]:
    import big_players
    import big_prints

    day = now.date().isoformat()
    snap = big_prints.load(root, day)
    stock = ((snap or {}).get("stocks") or {}).get(symbol)
    if not stock:
        return {"bp_ok": 1, "bp_reason": "NO_DATA"}
    sign = 1.0 if str(direction).upper() == "BULLISH" else -1.0
    net15, net, n15 = sign * float(stock.get("net15_cr") or 0), sign * float(stock.get("net_cr") or 0), int(stock.get("n15") or 0)
    align, reason = decide(net15, n15)
    out: dict[str, Any] = {"bp_net15_dir_cr": round(net15, 2), "bp_net_dir_cr": round(net, 2), "bp_n15": n15, "bp_align": align, "bp_reason": reason, "bp_ok": int(align != "AGAINST")}
    try:
        import premium_flow

        side = "BUY" if sign > 0 else "SELL"
        m = _money_flow_stock(root, day, symbol)
        conf = big_players.confirmations(side, big_players.futures_state(root, day).get(symbol), big_players.premium_lean(premium_flow._load(root, day).get(symbol)),
                                         m.get("imbalance"), m.get("flow_pct"))
        out["bp_conf"] = len(conf)
        out["bp_conf_which"] = "+".join(conf)
    except Exception:                                      # noqa: BLE001 - confirmations are optional extras
        pass
    return out
