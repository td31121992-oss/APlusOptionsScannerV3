"""Replay of the "observe until 09:45, then trade only the top-2 gaining / top-2 losing sectors" strategy (read-only research; no trading effect).

The rule (user, 10 Nov 2026), turned into exact steps:
  1. No trade before 09:45: let the market settle.
  2. At 09:45 rank the F&O sectors by the median move of their stocks since the 09:15 open (sectors with at least 4 stocks; UNCLASSIFIED left out).
     The 2 best sectors are the "gaining" sectors, the 2 worst the "losing" sectors.
  3. Calls (CE) only in stocks of the gaining sectors, puts (PE) only in stocks of the losing sectors; inside the sector only the strongest movers on that side (top 3 / top 5 / all).
  4. Stacking: a new trade on the same side in the same sector is taken only while every already-open same-side same-sector trade is in profit.

Every closed paper trade since the baseline day is checked against that rule (the scanner decides what is traded; this only tests which of those trades the rule would have allowed).
The 09:45 ranking is rebuilt from the stored 5-minute candles (data/pattern_log/candles/<day>.json), sectors from the market-watch report.

    python sector_focus_replay.py
"""

from __future__ import annotations

import random
import statistics as st
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
from sector_rank945 import CUT_MIN, MIN_SECTOR, OPEN_MIN, load_day, moves_at_cut, rank_sectors, sector_labels      # noqa: E402,F401


def summary(pnls: list[float]) -> str:
    if not pnls:
        return "n=  0"
    random.seed(11)
    lo = hi = float("nan")
    if len(pnls) >= 8:
        m = sorted(sum(random.choices(pnls, k=len(pnls))) / len(pnls) for _ in range(2000))
        lo, hi = m[50], m[1950]
    return f"n={len(pnls):3d} win={100 * sum(1 for x in pnls if x > 0) / len(pnls):3.0f}% net={sum(pnls):9,.0f} avg={st.mean(pnls):6.0f} (95% {lo:6.0f}..{hi:6.0f})"


def main() -> int:
    sys.path.insert(0, str(ROOT))
    import shadow_scoreboard as sb
    from entry_filter_replay import load_ticks, seconds_of

    trades = sb.load_trades(upto=date.today().isoformat())
    sectors = sector_labels()
    day_files = sorted(p.stem for p in (ROOT / "data" / "pattern_log" / "candles").glob("*.json"))
    ranking: dict[str, dict[str, Any]] = {}
    prev_close: dict[str, float] = {}
    for day in day_files:
        symbols = load_day(day)
        fo, fp = moves_at_cut(symbols, prev_close)
        entry: dict[str, Any] = {}
        for label, mv in (("open", fo), ("prev", fp)):
            order, med = rank_sectors(mv, sectors)
            if len(order) >= 5:
                top_by_sector: dict[str, list[str]] = {}
                for sec in order:
                    members = [s for s in mv if sectors.get(s) == sec]
                    top_by_sector[sec] = sorted(members, key=lambda s: -mv[s])                   # strongest gainer first
                entry[label] = {"gain": order[:2], "lose": order[-2:], "stocks": top_by_sector, "med": med}
        ranking[day] = entry
        prev_close = {sym.upper(): d["close"][-1] for sym, d in symbols.items() if d.get("close")}

    usable = [t for t in trades if t["_day"] in ranking and ranking[t["_day"]].get("open")]
    print(f"{len(trades)} closed trades since {trades[0]['_day']}; {len(usable)} on the {len(ranking)} days with candles ({len({t['_day'] for t in usable})} days)\n")
    print("Sector picks at 09:45 (move since the open), last 6 sessions:")
    for day in sorted(ranking)[-6:]:
        r = ranking[day].get("open")
        if r:
            print(f"  {day}  gaining: {', '.join(f'{s} {r['med'][s]:+.2f}%' for s in r['gain'])}   losing: {', '.join(f'{s} {r['med'][s]:+.2f}%' for s in r['lose'])}")
    print()

    def minute(t: dict[str, Any]) -> int:
        h, m = str(t["entry_time"])[11:16].split(":")
        return int(h) * 60 + int(m)

    def side(t: dict[str, Any]) -> str:
        return str(t.get("option_type") or "").upper()

    def sector_ok(t: dict[str, Any], basis: str, top_n: int | None) -> bool:
        r = ranking[t["_day"]].get(basis)
        sym = str(t["symbol"]).upper()
        if not r or minute(t) < CUT_MIN:
            return False
        sec = sectors.get(sym, "")
        if side(t) == "CE" and sec in r["gain"]:
            order = r["stocks"][sec]
        elif side(t) == "PE" and sec in r["lose"]:
            order = r["stocks"][sec][::-1]                                                        # strongest faller first
        else:
            return False
        return top_n is None or sym in order[:top_n]

    pnl = lambda t: float(t["net_pnl"])                                                           # noqa: E731
    days = sorted({t["_day"] for t in usable})
    first = set(days[: len(days) // 2])

    def report(label: str, rule: Callable[[dict[str, Any]], bool], pool: list[dict[str, Any]] = usable) -> list[dict[str, Any]]:
        kept = [t for t in pool if rule(t)]
        gone = [t for t in pool if not rule(t)]
        a, b = [pnl(t) for t in kept if t["_day"] in first], [pnl(t) for t in kept if t["_day"] not in first]
        per_day = len(kept) / max(1, len({t["_day"] for t in pool}))
        print(f"{label:46s} kept {summary([pnl(t) for t in kept])} | removed n={len(gone):3d} net={sum(pnl(t) for t in gone):9,.0f} | halves {sum(a):8,.0f} / {sum(b):8,.0f} | {per_day:4.1f} trades/day")
        return kept

    print("RULE VARIANTS (ranking = move since the 09:15 open)")
    report("all trades (no rule)", lambda t: True)
    report("1. no trade before 09:45", lambda t: minute(t) >= CUT_MIN)
    report("2. + only top-2 gaining / losing sectors", lambda t: sector_ok(t, "open", None))
    report("3. + only the top 5 movers in that sector", lambda t: sector_ok(t, "open", 5))
    report("4. + only the top 3 movers in that sector", lambda t: sector_ok(t, "open", 3))
    print("\nSAME, ranking by move since the PREVIOUS CLOSE")
    usable_p = [t for t in usable if ranking[t["_day"]].get("prev")]
    report("2p. top-2 sectors only", lambda t: sector_ok(t, "prev", None), usable_p)
    report("3p. + top 5 movers", lambda t: sector_ok(t, "prev", 5), usable_p)

    print("\nSTACKING (new same-side, same-sector trade only while every open one is in profit; days with recorded ticks)")
    tick_days = {t["_day"] for t in usable if load_ticks(str(t.get("option_security_id")), t["_day"], ROOT)}
    pool = [t for t in usable if t["_day"] in tick_days]
    cache: dict[tuple[str, str], Any] = {}

    def ticks(t: dict[str, Any]):
        k = (str(t.get("option_security_id")), t["_day"])
        if k not in cache:
            cache[k] = load_ticks(k[0], k[1], ROOT)
        return cache[k]

    def stacked(base_rule: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
        taken: list[dict[str, Any]] = []
        for t in sorted(pool, key=lambda x: (x["_day"], str(x["entry_time"]))):
            if not base_rule(t):
                continue
            t0 = seconds_of(t["entry_time"])
            ok = True
            for o in taken:
                if o["_day"] != t["_day"] or side(o) != side(t) or sectors.get(str(o["symbol"]).upper()) != sectors.get(str(t["symbol"]).upper()):
                    continue
                t_exit = seconds_of(o.get("exit_time")) if str(o.get("exit_time"))[:10] == o["_day"] else None
                if t_exit is not None and t_exit <= t0:
                    continue                                                                      # that one is already closed
                tk = ticks(o)
                upto = [x for x in tk if x[0] <= t0] if tk else []
                if not upto or (upto[-1][1] - float(o["entry_price"])) * float(o["quantity"]) <= 0:
                    ok = False                                                                    # not in profit (or unknown): wait
                    break
            if ok:
                taken.append(t)
        return taken

    print(f"  ({len(pool)} trades on {len(tick_days)} days with ticks)")
    report("all trades on these days", lambda t: True, pool)
    report("2. top-2 sectors (no stacking rule)", lambda t: sector_ok(t, "open", None), pool)
    kept2 = stacked(lambda t: sector_ok(t, "open", None))
    ids2 = {id(t) for t in kept2}
    report("2 + stacking rule", lambda t: id(t) in ids2, pool)
    kept3 = stacked(lambda t: sector_ok(t, "open", 5))
    ids3 = {id(t) for t in kept3}
    report("3 (top 5 movers) + stacking rule", lambda t: id(t) in ids3, pool)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
