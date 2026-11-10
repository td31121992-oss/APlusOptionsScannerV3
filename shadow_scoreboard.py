"""Nightly shadow scoreboard (read-only report; no trading effect).

Every shadow rule records, on each paper trade, what it WOULD have done. This puts them side by side, over all closed paper trades from the baseline day (default 1 Oct 2026, the user's valid
baseline) onward, so a decision to enforce one is a single read instead of a hunt through tags.

    A. Gates ("would block")   for each rule: the trades it would have blocked vs the trades it would have let through (count, win rate, net Rs), what enforcing it would have changed
                               (= minus the blocked trades' P&L), on how many days it would have helped, and whether there is enough data to judge (>= 15 blocked trades over >= 3 days)
    C. Forward-only evidence  the same rules judged ONLY on trades taken after the day each rule was first registered by this report (data/shadow_scoreboard/registry.json), with a 95% confidence
                               interval on each win rate. Rules were chosen by looking at past trades, so A is partly hindsight; C is the part that could not have been fitted to.
    B. Feature splits          the tag families that are not blocks (setup state, breadth, tick-burst, big-player flow, premium surge, sector alignment) split by group

    data/shadow_scoreboard/<day>.md  and  latest.md       the report
    data/shadow_scoreboard/<day>.csv                      the gate rows

    python shadow_scoreboard.py [YYYY-MM-DD]       day = the report date (default today); trades up to and including it

A rule is never judged on one day: the verdict says "collecting" until the sample is large enough, and even then it is hindsight on paper trades, before real fills.
"""

from __future__ import annotations

import csv
import json
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / "data" / "reports" / "paper_trade_history.json"
BASELINE = os.getenv("APLUS_SCOREBOARD_BASELINE", "2026-10-01")
MIN_BLOCKED, MIN_DAYS = 15, 3


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _truthy(v: Any) -> bool | None:
    s = str(v).strip().lower()
    if s in ("", "none", "nan"):
        return None
    if s in ("1", "1.0", "true", "yes"):
        return True
    if s in ("0", "0.0", "false", "no"):
        return False
    return None


def load_trades(path: Path = HISTORY, upto: str | None = None, baseline: str = BASELINE) -> list[dict[str, Any]]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8")).get("paper_trades") or []
    except (OSError, ValueError):
        return []
    out = []
    for t in rows:
        day = str(t.get("entry_time") or "")[:10]
        if str(t.get("status")).upper() == "CLOSED" and day >= baseline and (upto is None or day <= upto) and _f(t.get("net_pnl")) is not None:
            out.append({**t, "_day": day})
    out.sort(key=lambda t: str(t.get("entry_time")))
    return out


def add_canary(trades: list[dict[str, Any]]) -> None:
    """Where a trade has no recorded canary verdict (it predates the tag), work out what the canary rule would have said from the trades opened before it."""
    try:
        import canary_gate
    except Exception:                                      # noqa: BLE001
        return
    for i, t in enumerate(trades):
        if _truthy(t.get("cn_ok")) is not None:
            t["_cn_ok"] = _truthy(t.get("cn_ok"))
            continue
        try:
            when = datetime.fromisoformat(str(t.get("entry_time")))
            earlier = [x for x in trades[:i] if x["_day"] == t["_day"]]
            t["_cn_ok"] = bool(canary_gate.evaluate(earlier, str(t.get("direction")), when)["cn_ok"])
        except Exception:                                  # noqa: BLE001
            pass


# --- the rules: each returns True (would block), False (would allow) or None (no data on this trade) -------------------------------------------------------------------------------
GATES: dict[str, tuple[str, Callable[[Mapping[str, Any]], bool | None]]] = {
    "Canary (no pile-on onto a side that is not working)": ("APLUS_CANARY_MODE", lambda t: None if t.get("_cn_ok") is None else not t["_cn_ok"]),
    "Quality gate (score >= 6 of 7, max 6 a day)": ("APLUS_QUALITY_GATE_MODE", lambda t: None if _truthy(t.get("q_pass")) is None else not _truthy(t.get("q_pass"))),
    "Weak-market call gate (no CE into a weak market unless news / big buying)": ("APLUS_WEAKMKT_CE_MODE", lambda t: None if _truthy(t.get("wk_ok")) is None else not _truthy(t.get("wk_ok"))),
    "Do-not-chase check (stock already ran our way / extended market)": ("APLUS_CHASE_GATE_MODE", lambda t: None if _truthy(t.get("cg_ok")) is None else not _truthy(t.get("cg_ok"))),
    "Event gate (results within 3 trading days / bonus-split ex-date)": ("APLUS_EVENT_GATE_MODE", lambda t: None if _truthy(t.get("evg_ok")) is None else not _truthy(t.get("evg_ok"))),
    "Big-player gate (not against big prints)": ("APLUS_BIGPLAYER_GATE_MODE", lambda t: None if _truthy(t.get("bp_ok")) is None else not _truthy(t.get("bp_ok"))),
    "IV not expensive (ATM IV rank < 80 and IV < 1.5x realised volatility)": ("-", lambda t: None if _truthy(t.get("iv_expensive")) is None else bool(_truthy(t.get("iv_expensive")))),
    "Pullback-only entries (block everything but HEALTHY_PULLBACK / wait-for-retest)": ("-", lambda t: None if not t.get("setup_family") else str(t.get("setup_family")) != "HEALTHY_PULLBACK"),
    "No early non-pullback entry (before 09:45 unless HEALTHY_PULLBACK)": ("-", lambda t: None if not t.get("setup_family") or not t.get("entry_time") else (str(t.get("setup_family")) != "HEALTHY_PULLBACK" and str(t.get("entry_time"))[11:16] < "09:45")),
    "No entry before 09:45 (any setup)": ("-", lambda t: None if not t.get("entry_time") else str(t.get("entry_time"))[11:16] < "09:45"),
    "No ESTABLISHED_TREND setup": ("-", lambda t: None if not t.get("setup_family") else str(t.get("setup_family")).upper() == "ESTABLISHED_TREND"),
    "Entry rules (10:00 start, with Nifty, side cap)": ("APLUS_ENTRY_RULES_MODE", lambda t: None if not t.get("rule_verdict") else t.get("rule_verdict") == "WOULD_BLOCK"),
    "Settle window (nothing before 10:00)": ("APLUS_SETTLE_MODE", lambda t: _truthy(t.get("settle_would_block"))),
    "Market brake (market moving against the trade)": ("-", lambda t: _truthy(t.get("mb_would_block"))),
    "Breadth 70% (needs 70% of stocks on our side of VWAP)  [hypothetical]": ("-", lambda t: None if _truthy(t.get("bs_breadth70")) is None else not _truthy(t.get("bs_breadth70"))),
    "Spread gate (option bid-ask spread over 1% at entry)": ("-", lambda t: _truthy(t.get("gs_spread_wide"))),
    "Clean-trend gate (clean_trend_score under 96)": ("-", lambda t: _truthy(t.get("gs_clean_low"))),
    "Day cap (6th or later entry of the day)": ("-", lambda t: _truthy(t.get("gs_day_cap_over"))),
    "Regime + sector gate (majority side of the market AND top gainer / loser sector only)": ("-", lambda t: _truthy(t.get("rgs_would_block"))),
    "Sector focus till 10:30 (only the top-2 gaining sectors for calls / top-2 losing for puts)": ("-", lambda t: _truthy(t.get("sf_focus_block"))),
    "Sector focus till 10:30, looser (sector in either top-2 list)": ("-", lambda t: _truthy(t.get("sf_focus_any_block"))),
    "Stacking: no new trade while same sector + same side is not in profit": ("-", lambda t: _truthy(t.get("sf_stack_block"))),
    "Stacking, stricter: no new trade while ANY same-side trade is not in profit": ("-", lambda t: _truthy(t.get("sf_stack_side_block"))),
    "Sector focus + stacking combined (sector focus till 10:30 AND same-sector stacking rule)": ("-", lambda t: _truthy(t.get("sf_would_block"))),
    "Regime only (trade only the side most F&O stocks are on)": ("-", lambda t: _truthy(t.get("rgs_regime_block"))),
    "Regime 60% (the majority side must hold more than 60% of stocks)": ("-", lambda t: None if _truthy(t.get("rgs_regime60_ok")) is None else not _truthy(t.get("rgs_regime60_ok"))),
    "No put while the market is flat or falling (Nifty under +0.2% since the open)": ("-", lambda t: _truthy(t.get("gs_bear_weakmkt"))),
    "No cheap options (premium under 10)": ("-", lambda t: _truthy(t.get("gs_lowprice"))),
    "Spread cap, all history (no entry when the option spread at entry is over 1%)  [derived]": ("-", lambda t: _truthy(t.get("dx_spread_wide"))),
    "Momentum confirmation (not at / above entry price 5 minutes after the signal, or closed by then)  [derived from recorded ticks]": ("-", lambda t: _truthy(t.get("dx_mom5_block"))),
    "Spread cap + momentum confirmation together  [derived]": ("-", lambda t: _truthy(t.get("dx_would_block"))),
    "Observe till 09:45, then top-2 gaining / losing sectors only (calls in gaining, puts in losing; ranked since the open)  [derived]": ("-", lambda t: _truthy(t.get("dx_s945_block"))),
    "  ... and only the 5 strongest movers of that sector on the trade's side  [derived]": ("-", lambda t: _truthy(t.get("dx_s945_top5_block"))),
    "  ... and only the 3 strongest movers of that sector on the trade's side  [derived]": ("-", lambda t: _truthy(t.get("dx_s945_top3_block"))),
    "  ... sector must also be moving the right way (gaining sector up, losing sector down)  [derived]": ("-", lambda t: _truthy(t.get("dx_s945_abs_block"))),
    "Observe till 09:45, top-2 sectors ranked since the previous close  [derived]": ("-", lambda t: _truthy(t.get("dx_s945p_block"))),
    "  ... and only the 5 strongest movers (previous-close ranking)  [derived]": ("-", lambda t: _truthy(t.get("dx_s945p_top5_block"))),
    "Wait 11+ minutes after the stock's first entry-ready signal (entered 10 minutes or sooner = would block)  [derived]": ("-", lambda t: _truthy(t.get("dx_lag_early_block"))),
    "Enter only 11-30 minutes after the first entry-ready signal  [derived]": ("-", lambda t: _truthy(t.get("dx_lag_window_block"))),
    "Skip a quiet opening (the stock's first 5-minute volume below its 14-session average)  [derived]": ("-", lambda t: _truthy(t.get("dx_rvol_quiet_block"))),
    "Only stocks in play (first 5-minute volume at least 3x its 14-session average)  [derived]": ("-", lambda t: _truthy(t.get("dx_rvol3_block"))),
    "Fewer-better combo (any of: spread over 1%, clean score under 96, 6th+ entry of the day)": ("-", lambda t: None if _truthy(t.get("gs_q_pass")) is None else not _truthy(t.get("gs_q_pass"))),
}


def _bucket_x(v: Any) -> str | None:
    x = _f(v)
    return None if x is None else "<1x usual" if x < 1 else "1-2x usual" if x < 2 else "2x+ usual"


def _gap_event(t: Mapping[str, Any]) -> str | None:
    """Opening gap in the trade's direction (em_gap_dir, %), with 'results filed' when a results filing appeared since the previous close (ev_reported). AUBANK 26 Oct: results filed on the Saturday, a -8.8 % gap, and it did not continue."""
    gap = _f(t.get("em_gap_dir"))
    if gap is None or t.get("em_gap_dir") in ("", None):
        return None
    base = "gap with us 3%+" if gap >= 3 else "gap against us 3%+" if gap <= -3 else "gap under 3%"
    return base + (", results filed" if _truthy(t.get("ev_reported")) else "")


def _breadth_side(t: Mapping[str, Any]) -> str | None:
    """Share of F&O stocks up on the day when we entered (100 - rs_pct_down from the live ranking), by the side traded: 'PUT, market rising (>=60% up)' tests whether puts taken into a rising market lose more."""
    down = _f(t.get("rs_pct_down"))
    if down is None or t.get("rs_pct_down") in ("", None):
        return None
    side = "PUT" if str(t.get("direction") or t.get("option_type") or "").upper() in ("BEARISH", "PE", "PUT") else "CALL"
    up = 100.0 - down
    return f"{side}, " + ("market rising (>=60% up)" if up >= 60 else "market weak (<=40% up)" if up <= 40 else "market mixed (40-60% up)")


SPLITS: dict[str, Callable[[Mapping[str, Any]], str | None]] = {
    "cs_story (the stock's candle story at entry)": lambda t: t.get("cs_story") or None,
    "cs_with (the candle story supports / opposes the trade)": lambda t: None if t.get("cs_with") in (None, "") else ("story supports" if _f(t.get("cs_with")) == 1 else "story opposes" if _f(t.get("cs_with")) == -1 else "neutral story"),
    "gw_with_trade (the pre-open gap watch agrees / opposes the trade)": lambda t: None if t.get("gw_with_trade") in (None, "") else ("watch agrees" if _f(t.get("gw_with_trade")) == 1 else "watch opposes" if _f(t.get("gw_with_trade")) == -1 else "no watch view"),
    "am_pos_dir (price against the value area, in our direction)": lambda t: None if _f(t.get("am_pos_dir")) is None else ("above value with us" if _f(t.get("am_pos_dir")) > 0 else "below value against us" if _f(t.get("am_pos_dir")) < 0 else "inside value"),
    "am_ib_dir (beyond the first-hour range with / against us)": lambda t: None if _f(t.get("am_ib_dir")) is None else ("beyond IB with us" if _f(t.get("am_ib_dir")) > 0 else "beyond IB against us" if _f(t.get("am_ib_dir")) < 0 else "inside IB"),
    "am_div_dir (cumulative-delta divergence in the last 30 min)": lambda t: None if _f(t.get("am_div_dir")) is None else ("divergence favours us" if _f(t.get("am_div_dir")) > 0 else "divergence against us" if _f(t.get("am_div_dir")) < 0 else "no divergence"),
    "am_daytype (auction day type)": lambda t: t.get("am_daytype") or None,
    "dl_flip_dir (a buy/sell volume flip in the last 30 min agrees / disagrees with the trade)": lambda t: None if t.get("dl_flip_dir") in (None, "") else ("flip with us" if _f(t.get("dl_flip_dir")) == 1 else "flip against us" if _f(t.get("dl_flip_dir")) == -1 else "no recent flip"),
    "dl_imb15_dir (buyers minus sellers in the last 15 min, in our direction)": lambda t: None if _f(t.get("dl_imb15_dir")) is None else ("flow against us (< -0.15)" if _f(t.get("dl_imb15_dir")) < -0.15 else "flow with us (> +0.15)" if _f(t.get("dl_imb15_dir")) > 0.15 else "balanced"),
    "bb_fired (this stock broke a tight base against the market today)": lambda t: None if _truthy(t.get("bb_fired")) is None else ("base break fired" if _truthy(t.get("bb_fired")) else "no base break"),
    "co_top5 (chart looks like past big runs: top 5 % of chart scores)": lambda t: None if _truthy(t.get("co_top5")) is None else ("chart top 5%" if _truthy(t.get("co_top5")) else "chart not top 5%"),
    "em_core (moving with a 8x+ volume event move)": lambda t: None if _truthy(t.get("em_core")) is None else ("event momentum" if _truthy(t.get("em_core")) else "not event momentum"),
    "ml_top10 (shadow ML score in the model's own top 10 %)": lambda t: None if _truthy(t.get("ml_top10")) is None else ("ML top 10%" if _truthy(t.get("ml_top10")) else "ML not top 10%"),
    "ml_p (shadow ML win probability)": lambda t: None if _f(t.get("ml_p")) is None else ("p < 0.40" if _f(t.get("ml_p")) < 0.40 else "p 0.40-0.50" if _f(t.get("ml_p")) < 0.50 else "p 0.50+"),
    "fl_aligned (the latest filing's words agree with the trade direction)": lambda t: None if _truthy(t.get("fl_aligned")) is None else ("filing agrees" if _truthy(t.get("fl_aligned")) else "filing disagrees"),
    "iv_rank (ATM IV against this stock's own last 60 days)": lambda t: None if _f(t.get("iv_rank")) is None else ("IV rank < 40 (cheap)" if _f(t.get("iv_rank")) < 40 else "IV rank 40-80" if _f(t.get("iv_rank")) < 80 else "IV rank 80+ (dear)"),
    "iv_vs_hv (ATM IV over 20-day realised volatility)": lambda t: None if _f(t.get("iv_vs_hv")) is None else ("IV < 1.0x realised" if _f(t.get("iv_vs_hv")) < 1.0 else "1.0-1.5x" if _f(t.get("iv_vs_hv")) < 1.5 else "1.5x+ (priced for a big move)"),
    "iv_chg_day_pct (options dearer / cheaper since the first reading today)": lambda t: None if _f(t.get("iv_chg_day_pct")) is None else ("IV up 5%+ since morning" if _f(t.get("iv_chg_day_pct")) >= 5 else "IV down 5%+" if _f(t.get("iv_chg_day_pct")) <= -5 else "IV flat (within 5%)"),
    "bs_setup (breakdown / breakout setup complete)": lambda t: None if _truthy(t.get("bs_setup")) is None else ("setup complete" if _truthy(t.get("bs_setup")) else "not complete"),
    "bs_breadth70 (70% of stocks on our side)": lambda t: None if _truthy(t.get("bs_breadth70")) is None else ("breadth >= 70%" if _truthy(t.get("bs_breadth70")) else "breadth < 70%"),
    "mkt_side (market breadth at entry against the side traded)": lambda t: _breadth_side(t),
    "gap_event (opening gap in our direction, and whether results were filed since the last close)": lambda t: _gap_event(t),
    "ctx_last30_pct (stock move over the 30 min before entry, in our direction)": lambda t: None if t.get("ctx_last30_pct") in (None, "") or _f(t.get("ctx_last30_pct")) is None else ("under 0.3% (paused)" if _f(t.get("ctx_last30_pct")) < 0.3 else "0.3 - 0.8% (moving)" if _f(t.get("ctx_last30_pct")) < 0.8 else "0.8%+ (fast)"),
    "ctx_mins_since_ext (minutes since the day's extreme in our direction was set)": lambda t: None if t.get("ctx_mins_since_ext") in (None, "") or _f(t.get("ctx_mins_since_ext")) is None else ("at the extreme (<= 10 min)" if _f(t.get("ctx_mins_since_ext")) <= 10 else "10 - 45 min ago" if _f(t.get("ctx_mins_since_ext")) <= 45 else "45+ min ago"),
    "bp_align (big prints with / against us)": lambda t: t.get("bp_align") or None,
    "td_aligned (tick burst fired in our direction in the last 15 min)": lambda t: None if _truthy(t.get("td_fired")) is None else ("fired, aligned" if _truthy(t.get("td_aligned")) else "fired, against" if _truthy(t.get("td_fired")) else "no burst"),
    "px_x_avg (option premium vs usual by this time)": lambda t: _bucket_x(t.get("px_x_avg")),
    "rrg_aligned (sector rotation agrees)": lambda t: None if _truthy(t.get("rrg_aligned")) is None else ("aligned" if _truthy(t.get("rrg_aligned")) else "not aligned"),
}


def stats(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pnl = [float(t["net_pnl"]) for t in trades]
    ret = [x for x in (_f(t.get("return_percent")) for t in trades) if x is not None]
    return {"n": len(pnl), "win": round(100.0 * sum(1 for x in pnl if x > 0) / len(pnl), 0) if pnl else None, "net": round(sum(pnl), 0), "avg_ret": round(st.mean(ret), 1) if ret else None}


def gate_rows(trades: Sequence[Mapping[str, Any]], only: Sequence[str] | None = None) -> list[dict[str, Any]]:
    rows = []
    for name, (env, fn) in GATES.items():
        if only is not None and name not in only:
            continue
        known = [(t, fn(t)) for t in trades]
        known = [(t, v) for t, v in known if v is not None]
        blocked = [t for t, v in known if v]
        allowed = [t for t, v in known if not v]
        days_blocked = sorted({t["_day"] for t in blocked})
        helped = sum(1 for d in days_blocked if sum(float(t["net_pnl"]) for t in blocked if t["_day"] == d) < 0)
        b, a = stats(blocked), stats(allowed)
        enough = len(blocked) >= MIN_BLOCKED and len(days_blocked) >= MIN_DAYS
        rows.append({"rule": name, "env": env, "trades_with_data": len(known), "days_with_data": len({t["_day"] for t, _ in known}), "blocked": b, "allowed": a,
                     "change_if_enforced": -b["net"], "days_helped": helped, "days_blocked": len(days_blocked), "enough": enough})
    return rows


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson interval for a win rate, in %. None for n = 0."""
    if n <= 0:
        return None
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return round(100.0 * max(0.0, c - h), 0), round(100.0 * min(1.0, c + h), 0)


def update_registry(path: Path, gates: Sequence[Mapping[str, Any]], day: str) -> dict[str, str]:
    """rule -> the day this report first saw data for it. Forward-only evidence counts trades AFTER that day. Written once per rule, never moved."""
    try:
        reg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        reg = {}
    changed = False
    for r in gates:
        if r["trades_with_data"] and r["rule"] not in reg:
            reg[r["rule"]] = day
            changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(reg, indent=1, sort_keys=True), encoding="utf-8")
    return reg


def forward_rows(trades: Sequence[Mapping[str, Any]], registry: Mapping[str, str]) -> list[dict[str, Any]]:
    out = []
    for name in GATES:
        since = registry.get(name)
        if since is None:
            continue
        fwd = [t for t in trades if t["_day"] > since]
        r = gate_rows(fwd, only=[name])[0]
        known = [(t, GATES[name][1](t)) for t in fwd]
        blocked = [t for t, v in known if v]
        allowed = [t for t, v in known if v is not None and not v]
        bw, aw = sum(1 for t in blocked if float(t["net_pnl"]) > 0), sum(1 for t in allowed if float(t["net_pnl"]) > 0)
        r.update(since=since, blocked_ci=wilson(bw, len(blocked)), allowed_ci=wilson(aw, len(allowed)))
        r["verdict"] = forward_verdict(r)
        out.append(r)
    return out


def forward_verdict(r: Mapping[str, Any]) -> str:
    n, days = r["blocked"]["n"], r["days_blocked"]
    if n < MIN_BLOCKED or days < MIN_DAYS:
        return f"collecting ({n} blocked over {days} day(s) since {r['since']}; needs {MIN_BLOCKED}+ over {MIN_DAYS}+)"
    b, a = r["blocked_ci"], r["allowed_ci"]
    if b and a and b[1] < a[0]:
        return "HELPS: blocked trades win significantly less"
    if b and a and b[0] > a[1]:
        return "HURTS: blocked trades win significantly more"
    return "not distinguishable from chance yet"


def split_rows(trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for name, fn in SPLITS.items():
        groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for t in trades:
            g = fn(t)
            if g is not None:
                groups[g].append(t)
        out.append({"tag": name, "days": len({t["_day"] for g in groups.values() for t in g}), "groups": {g: stats(v) for g, v in sorted(groups.items())}})
    return out


def verdict(r: Mapping[str, Any]) -> str:
    if not r["blocked"]["n"]:
        return "nothing blocked yet" if r["trades_with_data"] else "no data yet"
    tail = f"{r['blocked']['n']} blocked over {r['days_blocked']} day(s), helped on {r['days_helped']}"
    if not r["enough"]:
        return f"collecting ({tail}; needs {MIN_BLOCKED}+ blocked over {MIN_DAYS}+ days)"
    return f"{'WOULD HAVE HELPED' if r['change_if_enforced'] > 0 else 'WOULD HAVE HURT'} ({tail})"


def render(day: str, trades: Sequence[Mapping[str, Any]], gates: Sequence[Mapping[str, Any]], splits: Sequence[Mapping[str, Any]], forward: Sequence[Mapping[str, Any]] | None = None) -> str:
    total = stats(trades)
    days = sorted({t["_day"] for t in trades})
    L = [f"# Shadow scoreboard - {day}", "",
         f"{total['n']} closed paper trades from {BASELINE} to {day} over {len(days)} sessions: win rate {total['win']:.0f}%, net Rs {total['net']:,.0f}. Nothing here is enforced; every row is hindsight on paper trades, before real fills.", "",
         "## A. Gates: what each rule would have done", "",
         "| Rule | Would block | Block: win / net Rs | Allowed: win / net Rs | Change if enforced | Verdict |", "|---|---|---|---|---|---|"]
    for r in gates:
        b, a = r["blocked"], r["allowed"]
        fmt = lambda s: "-" if not s["n"] else f"{s['win']:.0f}% / {s['net']:,.0f}"
        L.append(f"| {r['rule']} | {b['n']} of {r['trades_with_data']} | {fmt(b)} | {fmt(a)} | {r['change_if_enforced']:+,.0f} | {verdict(r)} |")
    L += ["", "Change if enforced = minus the blocked trades' net P&L (positive = the rule would have saved money). It ignores knock-on effects (a blocked trade changes the state the next candidate sees, and capital freed would have taken other trades), so read it as a guide, not a forecast. Enforce setting per rule: " + "; ".join(f"{r['rule'].split(' (')[0]}: {r['env']}" for r in gates if r["env"] != "-"), "",
          "## C. Forward-only evidence (trades after each rule was first registered)", ""]
    if forward:
        L += ["| Rule | Registered | Blocked fwd | Block: win (95% CI) / net Rs | Allowed: win (95% CI) / net Rs | Verdict |", "|---|---|---|---|---|---|"]
        for r in forward:
            b, a = r["blocked"], r["allowed"]
            fmt = lambda s, ci: "-" if not s["n"] else f"{s['win']:.0f}% ({ci[0]:.0f}-{ci[1]:.0f}) / {s['net']:,.0f}"
            L.append(f"| {r['rule']} | {r['since']} | {b['n']} over {r['days_blocked']} day(s) | {fmt(b, r['blocked_ci'])} | {fmt(a, r['allowed_ci'])} | {r['verdict']} |")
        L.append("")
    else:
        L += ["Nothing registered yet: a rule is registered the first night this report sees data for it, and only later trades count here.", ""]
    L += ["## B. Feature splits", ""]
    for s in splits:
        L += [f"### {s['tag']}  ({s['days']} session(s) of data)", ""]
        if not s["groups"]:
            L += ["No data yet.", ""]
            continue
        L += ["| Group | Trades | Win rate | Net Rs | Avg return % |", "|---|---|---|---|---|"]
        for g, v in s["groups"].items():
            L.append(f"| {g} | {v['n']} | {v['win']:.0f}% | {v['net']:,.0f} | {v['avg_ret'] if v['avg_ret'] is not None else '-'} |")
        L.append("")
    return "\n".join(L) + "\n"


def run(day: str | None = None, root: Path = ROOT) -> Path | None:
    day = day or date.today().isoformat()
    trades = load_trades(root / "data" / "reports" / "paper_trade_history.json", upto=day)
    if not trades:
        return None
    add_canary(trades)
    try:                                                   # derived entry-filter tags (spread cap, 5-minute momentum) from the recorded ticks; the report must not depend on them
        import derived_tags

        derived_tags.enrich(trades, root)
    except Exception:                                      # noqa: BLE001
        pass
    gates, splits = gate_rows(trades), split_rows(trades)
    folder = root / "data" / "shadow_scoreboard"
    folder.mkdir(parents=True, exist_ok=True)
    forward = forward_rows(trades, update_registry(folder / "registry.json", gates, day))
    text = render(day, trades, gates, splits, forward)
    (folder / f"{day}.md").write_text(text, encoding="utf-8")
    (folder / "latest.md").write_text(text, encoding="utf-8")
    with (folder / f"{day}.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.writer(h)
        w.writerow(["rule", "trades_with_data", "blocked_n", "blocked_win", "blocked_net", "allowed_n", "allowed_win", "allowed_net", "change_if_enforced", "days_helped", "days_blocked", "enough"])
        for r in gates:
            w.writerow([r["rule"], r["trades_with_data"], r["blocked"]["n"], r["blocked"]["win"], r["blocked"]["net"], r["allowed"]["n"], r["allowed"]["win"], r["allowed"]["net"],
                        r["change_if_enforced"], r["days_helped"], r["days_blocked"], int(r["enough"])])
    return folder / f"{day}.md"


def main() -> int:
    out = run(sys.argv[1] if len(sys.argv) > 1 else None)
    print(out or "no closed trades")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
