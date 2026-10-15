"""Key-level push tag (SHADOW / RESEARCH - never blocks or changes a trade).

The shape of the good paper trades of 15 Oct (ICICIBANK, HINDPETRO, BHARTIARTL, INDUSINDBK): the stock is pushing on a KEY LEVEL -
at or through the previous day's high / the opening-range high (bearish: low) - while making higher lows, trading above VWAP,
with more volume than is normal for that time of day. This module only measures that shape, for every signal and every trade,
so we can see (a) whether it predicts the move and (b) which gate is dropping signals that have it.

    kl_level          PDH | ORH | PDH+ORH | PDL | ORL | PDL+ORL | "" (not at a key level)  - at/through the level, within 0.1%
    kl_pdh_dist_pct   price vs previous-day high (bearish: low), in OUR direction (+ = beyond the level)
    kl_orh_dist_pct   price vs opening-range (09:15-09:30) high (bearish: low), in our direction
    kl_higher_lows    how many of the last 5 bars made a higher low (bearish: lower high), 0-4
    kl_vwap_pct       distance above VWAP (bearish: below), in our direction
    kl_vol_x          mean volume of the last 3 bars versus normal for that time of day ("" when unknown)
    kl_push           True when: at a key level AND kl_higher_lows >= 3 AND above VWAP AND (volume >= 1x normal or unknown)

    python key_level.py [YYYY-MM-DD]     rebuild data/shadow_rules/key_level.md for a day's signals (needs pattern_log's saved candles)
"""

from __future__ import annotations

import csv
import glob
import json
import statistics as st
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
AT_LEVEL_PCT = 0.10          # "at the level" = within 0.1% below it (or anywhere beyond it)
OR_BARS = 3                  # 09:15, 09:20, 09:25 bars form the opening range


def _g(c: Any, name: str) -> float:
    try:
        v = c[name] if isinstance(c, Mapping) else getattr(c, name)
        return float(v)
    except (KeyError, AttributeError, TypeError, ValueError):
        return 0.0


def push_tags(candles: Sequence[Any], direction: str, pdh: float | None = None, pdl: float | None = None,
              vol_x: float | None = None, ltp: float | None = None) -> dict[str, Any]:
    """candles: today's COMPLETED 5-minute candles, oldest first (objects with open/high/low/close/volume or dicts)."""
    try:
        cs = [c for c in candles if _g(c, "close") > 0]
        if len(cs) < OR_BARS + 1:
            return {}
        bull = str(direction).upper() == "BULLISH"
        sg = 1.0 if bull else -1.0
        px = float(ltp) if ltp and float(ltp) > 0 else _g(cs[-1], "close")
        orb = cs[:OR_BARS]
        or_lvl = max(_g(c, "high") for c in orb) if bull else min(_g(c, "low") for c in orb)
        lvl_pd = (pdh if bull else pdl) or 0.0

        def dist(level: float) -> float | None:
            return round(sg * (px / level - 1.0) * 100.0, 3) if level and level > 0 else None

        d_pd, d_or = dist(lvl_pd), dist(or_lvl)
        at_pd = d_pd is not None and d_pd >= -AT_LEVEL_PCT
        at_or = d_or is not None and d_or >= -AT_LEVEL_PCT and len(cs) > OR_BARS
        tag = ("PDH" if bull else "PDL") if at_pd else ""
        if at_or:
            tag = (tag + "+" if tag else "") + ("ORH" if bull else "ORL")
        last = cs[-5:]
        hl = 0
        for a, b in zip(last, last[1:]):
            if (bull and _g(b, "low") >= _g(a, "low")) or ((not bull) and _g(b, "high") <= _g(a, "high")):
                hl += 1
        tp = [(_g(c, "high") + _g(c, "low") + _g(c, "close")) / 3.0 for c in cs]
        vols = [_g(c, "volume") for c in cs]
        vwap = sum(p * v for p, v in zip(tp, vols)) / sum(vols) if sum(vols) > 0 else _g(cs[-1], "close")
        vwap_pct = round(sg * (px / vwap - 1.0) * 100.0, 3) if vwap > 0 else None
        push = bool(tag) and hl >= 3 and vwap_pct is not None and vwap_pct > 0 and (vol_x is None or vol_x >= 1.0)
        out: dict[str, Any] = {"kl_level": tag, "kl_pdh_dist_pct": d_pd if d_pd is not None else "",
                               "kl_orh_dist_pct": d_or if d_or is not None else "", "kl_higher_lows": hl,
                               "kl_vwap_pct": vwap_pct if vwap_pct is not None else "",
                               "kl_vol_x": round(vol_x, 2) if vol_x is not None else "", "kl_push": push}
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}


# ----------------------------------------------------------------------------- nightly report over every signal
def _typical(candles_path: Path, symbol: str) -> dict[int, float]:
    return {}


def _load_day(root: Path, day: str) -> dict[str, Any]:
    try:
        return json.loads((root / "data" / "pattern_log" / "candles" / f"{day}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _vol_x(sym: dict[str, Any], upto: int) -> float | None:
    typ = {int(k): float(v) for k, v in (sym.get("typical") or {}).items()}
    vols = [(m, v) for m, v in zip(sym.get("minute", []), sym.get("volume", [])) if m < upto][-3:]
    if len(vols) < 3 or not typ:
        return None
    base = [typ.get(m) for m, _ in vols]
    if any(not b for b in base):
        return None
    return (sum(v for _, v in vols) / 3.0) / (sum(base) / 3.0)


def evaluate_day(root: Path, day: str) -> list[dict[str, Any]]:
    data = _load_day(root, day)
    path = root / "data" / "missed_opportunities" / day / "option_returns.json"
    if not data or not path.exists():
        return []
    rows = []
    for r in json.loads(path.read_text(encoding="utf-8")):
        if r.get("kind") != "ATM":
            continue
        sym = (data.get("symbols") or {}).get(r["symbol"])
        if not sym:
            continue
        try:
            h, m = (int(x) for x in str(r["ready"]).split(":")[:2])
        except ValueError:
            continue
        ready = h * 60 + m
        idx = [i for i, mm in enumerate(sym["minute"]) if mm < ready]
        if len(idx) < OR_BARS + 1:
            continue
        cs = [{"open": sym["open"][i], "high": sym["high"][i], "low": sym["low"][i], "close": sym["close"][i], "volume": sym["volume"][i]}
              for i in idx]
        tags = push_tags(cs, r["dir"], sym.get("pdh"), sym.get("pdl"), _vol_x(sym, ready))
        if not tags:
            continue
        fate = str(r.get("fate") or "")
        group = ("TRADED" if fate == "TRADED" else "V2_BLOCKED" if fate.startswith("V2_BLOCKED")
                 else fate.replace("A_PLUS:", "A+ " ) if fate.startswith("A_PLUS") else fate or "OTHER")
        rows.append({"day": day, "symbol": r["symbol"], "dir": r["dir"], "ready": r["ready"], "group": group,
                     "best": float(r.get("best") or 0), "worst": float(r.get("worst") or 0), "close": float(r.get("close") or 0),
                     "stop_first": bool(r.get("stop_first")), **tags})
    return rows


def _stats(g: list[dict[str, Any]]) -> str:
    if not g:
        return "-"
    n = len(g)
    return (f"{n} | {round(100 * sum(x['best'] >= 15 for x in g) / n)}% | {round(100 * sum(x['best'] >= 30 for x in g) / n)}% | "
            f"{round(100 * sum(x['stop_first'] for x in g) / n)}% | {st.mean(x['close'] for x in g):+.1f}% | "
            f"{round(100 * sum(x['close'] > 0 for x in g) / n)}%")


def render(rows: list[dict[str, Any]], days: list[str]) -> str:
    out = ["# Key-level push (shadow)", "",
           f"{len(days)} day(s) on file. ATM option bought at each signal's first ENTRY_READY candle, hindsight, before costs. "
           "PUSH = at/through the previous-day or opening-range level + higher lows + above VWAP + normal-or-better volume.", "",
           "Columns: signals | reached +15% | reached +30% | hit the stop first | mean close | closed up", ""]
    out += ["## All signals", "", "| Group | n | +15% | +30% | stop first | mean close | up |", "|---|---|---|---|---|---|---|"]
    for lab, sel in (("PUSH", [r for r in rows if r["kl_push"]]), ("not PUSH", [r for r in rows if not r["kl_push"]])):
        out.append(f"| {lab} | {_stats(sel)} |")
    out += ["", "## By what happened to the signal", "", "| Fate | Shape | n | +15% | +30% | stop first | mean close | up |",
            "|---|---|---|---|---|---|---|---|"]
    by: dict[str, list] = defaultdict(list)
    for r in rows:
        by[r["group"]].append(r)
    for grp in sorted(by, key=lambda k: -len(by[k])):
        for lab, sel in (("PUSH", [r for r in by[grp] if r["kl_push"]]), ("not PUSH", [r for r in by[grp] if not r["kl_push"]])):
            if sel:
                out.append(f"| {grp} | {lab} | {_stats(sel)} |")
    blocked = [r for r in rows if r["kl_push"] and r["group"] != "TRADED"]
    if blocked:
        out += ["", "## Signals with the PUSH shape that we did NOT trade (newest first)", "",
                "| Day | Symbol | Dir | Ready | Level | Dropped by | Best | Worst | Close |", "|---|---|---|---|---|---|---|---|---|"]
        for r in sorted(blocked, key=lambda x: (x["day"], x["ready"]), reverse=True)[:60]:
            out.append(f"| {r['day']} | {r['symbol']} | {r['dir'][:4]} | {r['ready']} | {r['kl_level']} | {r['group']} | "
                       f"{r['best']:+.0f}% | {r['worst']:+.0f}% | {r['close']:+.0f}% |")
    out += ["", "_Research only: nothing here changes trading. Judge it over several days, not one._", ""]
    return "\n".join(out)


def write(root: Path = ROOT) -> Path | None:
    rows, days = [], []
    for p in sorted(glob.glob(str(root / "data" / "pattern_log" / "candles" / "20*.json"))):
        day = Path(p).stem
        got = evaluate_day(root, day)
        if got:
            rows.extend(got)
            days.append(day)
    if not rows:
        return None
    folder = root / "data" / "shadow_rules"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "key_level.md"
    path.write_text(render(rows, days), encoding="utf-8")
    return path


def main() -> int:
    p = write()
    print(p or "no candles / option returns on file yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
