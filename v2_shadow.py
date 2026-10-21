"""Shadow test for the V2 gate's top-5 limit: what would pass if the limit were top-10?

Live trading is NOT affected. Each scan the scanner re-runs the V2 gate on the same candidates with a top-10 mover
ranking; any candidate that passes top-10 but not the live top-5 is logged once per day (first time seen) to
data/shadow_v2/<date>.csv. `report()` joins those signals with the nightly option returns (missed_option_returns) to compare,
per day and cumulatively, the extra top-10 passes against the live trades and the rest of the V2-blocked signals.
"""

from __future__ import annotations

import csv
import json
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "shadow_v2"
FIELDS = ["scenario", "time", "symbol", "direction", "ltp", "top10_rank", "stage", "setup_family", "from_open_pct"]


def log_new(extra: Iterable[Any], shadow_rank: dict[str, Any], when: datetime, seen: set[tuple[str, str]],
            out_dir: Path = OUT, scenario: str = "top10") -> int:
    """Append candidates that pass top-10 but not top-5, once per symbol/direction per day. Returns rows written."""
    ranks: dict[tuple[str, str], tuple[int, float]] = {}
    for side, key in (("BULLISH", "top_up"), ("BEARISH", "top_down")):
        for row in shadow_rank.get(key, []) or []:
            ranks[(str(row.get("symbol")), side)] = (int(row.get("v2_rank") or 0), float(row.get("from_open_pct") or 0.0))
    rows = []
    for c in extra:
        key = (str(getattr(c, "symbol", "")).upper(), str(getattr(c, "direction", "")).upper())
        if not key[0] or key in seen:
            continue
        seen.add(key)
        rank, from_open = ranks.get(key, (0, 0.0))
        rows.append({"scenario": scenario, "time": when.strftime("%H:%M:%S"), "symbol": key[0], "direction": key[1],
                     "ltp": getattr(c, "ltp", ""), "top10_rank": rank, "stage": getattr(c, "stage", ""),
                     "setup_family": getattr(c, "setup_family", ""), "from_open_pct": from_open})
    if rows:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{when.date().isoformat()}.csv"
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            if new:
                writer.writeheader()
            writer.writerows(rows)
    return len(rows)


PULLBACK_REASONS = {"CURRENT_5M_REVERSING", "NO_FRESH_CONTINUATION"}


def pullback_pass(candidates: Iterable[Any], blocked: Iterable[dict[str, Any]], max_dip_pct: float = 0.5) -> list[Any]:
    """Pullback scenario (SHADOW): candidates V2 rejected ONLY for the 5-minute-reversal / continuation-vote rules (so they
    are in the top 5 and pass session move, participation and retention) whose current 5m dip is at most `max_dip_pct`
    and which still sit on the right side of VWAP. Tests "buy the dip in a leader" against the strict reversal rule."""
    by_key = {(str(b.get("symbol", "")).upper(), str(b.get("direction", "")).upper()): b for b in blocked}
    kept = []
    for c in candidates:
        key = (str(getattr(c, "symbol", "")).upper(), str(getattr(c, "direction", "")).upper())
        b = by_key.get(key)
        if not b:
            continue
        cats = {re.sub(r"\(.*", "", str(r)) for r in (b.get("reasons") or [])}
        if not cats or not cats <= PULLBACK_REASONS:
            continue
        try:
            d5 = float(b.get("directional_5m_pct") or 0.0)
            vwap = float(getattr(c, "vwap_distance_percent", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        sign = 1.0 if key[1] == "BULLISH" else -1.0
        if d5 >= -max_dip_pct and vwap * sign > 0:
            kept.append(c)
    return kept


class FreshTracker:
    """Rolling last-price snapshots of every F&O stock (one per scan cycle) so the move over the LAST 15 / 30 minutes can be ranked,
    instead of the move since the open that V2 ranks by (the top 5 since the open are, by construction, the stocks that already moved most)."""

    def __init__(self, keep_minutes: int = 45) -> None:
        self.keep = keep_minutes * 60
        self.hist: dict[str, deque[tuple[float, float]]] = {}

    def update(self, quotes: dict[str, float], now: datetime) -> None:
        ts = now.timestamp()
        for sym, px in quotes.items():
            if px and px > 0:
                d = self.hist.setdefault(sym, deque())
                if not d or ts - d[-1][0] >= 20:            # at most one snapshot per 20 s
                    d.append((ts, float(px)))
                while d and ts - d[0][0] > self.keep:
                    d.popleft()

    def move_pct(self, sym: str, ltp: float, now: datetime, window_min: int, day_open: float) -> float:
        """% move over `window_min` minutes. Before that much history exists the move since the open stands in (it is the
        fresh move at that point of the day)."""
        d = self.hist.get(sym)
        target = now.timestamp() - window_min * 60
        ref = None
        if d and d[0][0] <= target + 20:
            for ts, px in d:                                 # newest snapshot that is at least `window` old
                if ts <= target:
                    ref = px
                else:
                    break
        if ref is None:
            ref = day_open
        return (ltp / ref - 1.0) * 100.0 if ref and ref > 0 else 0.0


def rank_fresh(universe: Any, quote_map: dict[str, Any], tracker: FreshTracker, now: datetime, window_min: int = 15,
               top_n: int = 5) -> dict[str, Any]:
    """Same output shape as stock_selection_v2.rank_raw_movers, ranked by the move over the last `window_min` minutes."""
    segment = quote_map.get("NSE_EQ", {}) if isinstance(quote_map, dict) else {}
    rows, prices = [], {}
    for item in universe:
        sid = str(getattr(item, "security_id", "") or "")
        sym = str(getattr(item, "symbol", "") or "").strip().upper()
        raw = segment.get(sid) if sid else None
        if raw is None and sid:
            try:
                raw = segment.get(int(sid))
            except (TypeError, ValueError):
                raw = None
        if not isinstance(raw, dict) or not sym:
            continue
        ohlc = raw.get("ohlc") if isinstance(raw.get("ohlc"), dict) else {}
        ltp, day_open = float(raw.get("last_price") or 0), float(ohlc.get("open") or 0)
        if ltp <= 0 or day_open <= 0:
            continue
        prices[sym] = ltp
        rows.append({"symbol": sym, "ltp": ltp, "from_open_pct": round((ltp / day_open - 1) * 100, 4),
                     "fresh_pct": round(tracker.move_pct(sym, ltp, now, window_min, day_open), 4)})
    tracker.update(prices, now)
    up = sorted((r for r in rows if r["fresh_pct"] > 0), key=lambda r: -r["fresh_pct"])[:max(1, top_n)]
    down = sorted((r for r in rows if r["fresh_pct"] < 0), key=lambda r: r["fresh_pct"])[:max(1, top_n)]
    for i, r in enumerate(up, 1):
        r["v2_rank"] = i
    for i, r in enumerate(down, 1):
        r["v2_rank"] = i
    return {"top_n_per_side": top_n, "top_up": up, "top_down": down, "symbols": [r["symbol"] for r in up + down], "universe_rows_ranked": len(rows)}


def _stats(values: list[float], best: list[float]) -> str:
    if not values:
        return "n=0"
    s = sorted(values)
    return (f"n={len(values)} | mean close {sum(values) / len(values):+.1f}% (about {sum(values) / len(values) - 1.5:+.1f}% after costs) | "
            f"median {s[len(s) // 2]:+.1f}% | winners {100 * sum(v > 0 for v in values) // len(values)}% | reached +30%: {sum(b >= 30 for b in best)}")


def report(root: Path = ROOT) -> Path | None:
    """Writes data/shadow_v2/summary.md comparing outcomes (ATM option, hindsight, entry at first-ready candle +1%)."""
    groups: dict[str, tuple[list[float], list[float]]] = {"extra": ([], []), "norank_only": ([], []), "other_v2_blocked": ([], []), "traded": ([], []),
                                                         "est_trend": ([], []), "pullback": ([], []),
                                                         "fresh15": ([], []), "fresh30": ([], []),
                                                         "bounce10": ([], []), "bounce20": ([], []), "bounce30": ([], [])}
    per_day = []
    for csv_path in sorted((root / "data" / "shadow_v2").glob("20*.csv")):
        day = csv_path.stem
        returns = root / "data" / "missed_opportunities" / day / "option_returns.json"
        if not returns.exists():
            continue
        try:
            opts = {(r["symbol"], r["dir"]): r for r in json.loads(returns.read_text(encoding="utf-8")) if r["kind"] == "ATM"}
            logged = list(csv.DictReader(csv_path.open(encoding="utf-8")))
            extra = {(r["symbol"], r["direction"]) for r in logged if r.get("scenario", "top10") == "top10"}
            norank = {(r["symbol"], r["direction"]) for r in logged if r.get("scenario") == "norank"} - extra
            est = {(r["symbol"], r["direction"]) for r in logged if r.get("scenario") == "est_trend"}
            pb = {(r["symbol"], r["direction"]) for r in logged if r.get("scenario") == "pullback"}
            fr = {n: {(r["symbol"], r["direction"]) for r in logged if r.get("scenario") == n} for n in ("fresh15", "fresh30", "bounce10", "bounce20", "bounce30")}
        except (OSError, ValueError, KeyError):
            continue
        day_extra = ([], [])
        for key, r in opts.items():
            fate = str(r.get("fate", ""))
            if key in extra:
                group = "extra"
            elif key in norank:
                group = "norank_only"
            elif fate.startswith("V2_BLOCKED"):
                group = "other_v2_blocked"
            elif fate == "TRADED":
                group = "traded"
            else:
                continue
            groups[group][0].append(float(r["close"]))
            groups[group][1].append(float(r["best"]))
            if key in est and fate.startswith("V2_BLOCKED"):
                groups["est_trend"][0].append(float(r["close"]))
                groups["est_trend"][1].append(float(r["best"]))
            for n, members in fr.items():
                if key in members and fate.startswith("V2_BLOCKED"):
                    groups[n][0].append(float(r["close"]))
                    groups[n][1].append(float(r["best"]))
            if key in pb and fate.startswith("V2_BLOCKED"):
                groups["pullback"][0].append(float(r["close"]))
                groups["pullback"][1].append(float(r["best"]))
            if group == "extra":
                day_extra[0].append(float(r["close"]))
                day_extra[1].append(float(r["best"]))
        per_day.append((day, day_extra))
    if not per_day:
        return None
    lines = ["# V2 top-10 shadow test", "",
             "Compares the signals that would pass if the V2 limit were top-10 (but not top-5) with the live trades and the other V2-blocked signals.",
             "Outcome = at-the-money option bought at the first-ready candle +1% and held to the close; hindsight, before real fills.", "",
             f"- **Extra top-10 passes:** {_stats(*groups['extra'])}",
             f"- **Extra with NO rank rule at all (beyond top-10):** {_stats(*groups['norank_only'])}",
             f"- **Established-trend setups V2 blocked (the proposed widening, before the 3-per-side cap):** {_stats(*groups['est_trend'])}",
             f"- **Pullback leaders (top-5 stocks V2 rejected only for a <=0.5% 5m dip, still on the right side of VWAP):** {_stats(*groups['pullback'])}",
             f"- **Fresh-movement ranking, last 15 min, top 5 per side (V2-blocked signals it would let in):** {_stats(*groups['fresh15'])}",
             f"- **Fresh-movement ranking, last 30 min, top 5 per side:** {_stats(*groups['fresh30'])}",
             f"- **5m bounce limit loosened 0.06% -> 0.10% (top-N and every other V2 rule unchanged):** {_stats(*groups['bounce10'])}",
             f"- **5m bounce limit loosened to 0.20%:** {_stats(*groups['bounce20'])}",
             f"- **5m bounce limit loosened to 0.30%:** {_stats(*groups['bounce30'])}",
             f"- **Other V2-blocked:** {_stats(*groups['other_v2_blocked'])}",
             f"- **Live trades:** {_stats(*groups['traded'])}", "", "| Day | Extra top-10 passes |", "|---|---|"]
    lines += [f"| {day} | {_stats(*vals)} |" for day, vals in per_day]
    out = root / "data" / "shadow_v2" / "summary.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
