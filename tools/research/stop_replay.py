"""Replay of option stop widths and profit-lock rules on closed paper trades (research only; changes nothing).

A) WIDER STOP, on trades that exited by OPTION_STOP_LOSS: same entry, stop moved to entry - k * (original distance), k in 1, 1.5, 2, 3. The price path is the per-trade tape
   (data/option_trade_tape, every few seconds, entry -> actual exit) followed by the 5-minute option-chain captures (data/options_intelligence_upstox) until 15:25.
   Survivors of the wider stop are sold at 15:25 (R1) or at the plan's first target if it is reached first (R2).
B) PROFIT LOCK, on ALL closed trades: overlay on the real result. If the option was up >= T% before the real exit and then fell back to the lock level before that exit, sell there instead.
   Uses only the fine tape up to the real exit, so no sparse-sampling bias.
Run: python tools/research/stop_replay.py   (writes E:/APlusData/stop_replay/stop_replay.txt)
"""
from __future__ import annotations

import csv
import gzip
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import agent_run  # noqa: E402

SINCE = "2026-10-21"                       # chain captures start here
OUT = Path("E:/APlusData/stop_replay")
KS = [1.0, 1.5, 2.0, 3.0]
LOCKS = [("BE after +7%", 7, 0, None), ("BE after +10%", 10, 0, None), ("lock +3% after +7%", 7, 3, None), ("lock +5% after +10%", 10, 5, None),
         ("keep 50% of peak after +7%", 7, None, 0.5), ("keep 60% of peak after +10%", 10, None, 0.6)]


def ts(s) -> datetime:
    return datetime.fromisoformat(str(s))


def read_tape(day: str, tid: str):
    p = ROOT / "data" / "option_trade_tape" / day / f"{tid}.csv"
    if not p.exists():
        return None
    out, post = [], []
    with open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                (post if r.get("status") == "POST_EXIT" else out).append((ts(r["timestamp"]), float(r["price"])))
            except (ValueError, KeyError):
                pass
    # rows written while the trade was open (fine, every few seconds) and, from 13 Nov 2026, POST_EXIT rows (every 15 s until 15:25)
    return (out, post) if out else None


def chain_paths(trades):
    """{trade_id: [(ts, ltp)]} from the 5-minute chain captures, for the trade's own contract."""
    need = defaultdict(dict)
    for t in trades:
        day = str(t["entry_time"])[:10]
        need[day][(t["symbol"], t["option_type"], str(float(t["strike"])), str(t["expiry"]))] = t["paper_trade_id"]
    paths = {}
    for day, keys in need.items():
        p = ROOT / "data" / "options_intelligence_upstox" / day / "option_chain_rows.csv.gz"
        if not p.exists():
            continue
        acc = defaultdict(list)
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    k = (r["symbol"], r["side"], str(float(r["strike"])), r["expiry"])
                except ValueError:
                    continue
                if k in keys:
                    try:
                        v = float(r["ltp"])
                    except ValueError:
                        continue
                    if v > 0:
                        acc[k].append((ts(r["captured_at"]), v))
        for k, tid in keys.items():
            if acc.get(k):
                paths[tid] = sorted(acc[k])
    return paths


def net(t, fill):
    return (fill - t["entry_price"]) * t["quantity"] - (t.get("estimated_costs") or 0.0)


def haircut(stops):
    """Typical fill below the recorded price when a stop is hit (from real stop exits that have a tape)."""
    xs = []
    for t, tape, _ in stops:
        last = tape[-1][1]
        if last > 0 and t["exit_price"] > 0:
            xs.append(1 - t["exit_price"] / last)
    return max(0.0, st.median(xs)) if xs else 0.01


def replay_stop(t, tape, chain, k, h, rule):
    entry = t["entry_price"]
    stop = max(0.05, entry - k * (entry - t["option_stop"]))
    exit_ts = ts(t["exit_time"])
    end = exit_ts.replace(hour=15, minute=25, second=0, microsecond=0)
    path = tape + [(a, b) for a, b in (chain or []) if exit_ts < a <= end]
    tgt = t.get("option_target1")
    last = path[-1][1]
    for _, p in path:
        if p <= stop:
            return net(t, p * (1 - h)), "stop"
        if rule == "R2" and tgt and p >= tgt:
            return net(t, tgt * (1 - h)), "target"
    return net(t, last * (1 - h)), "held"


def sample5(tape):
    out, nxt = [], None
    for a, p in tape:
        if nxt is None or a >= nxt:
            out.append((a, p))
            nxt = a + timedelta(minutes=5)
    return out


def money(x):
    return f"{x:+,.0f}"


def main() -> int:
    lines = []

    def P(s=""):
        lines.append(s)
        print(s)

    trades = [t for t in agent_run.load_trades(ROOT) if str(t.get("status")).upper() == "CLOSED" and str(t.get("entry_time"))[:10] >= SINCE
              and t.get("entry_price") and t.get("exit_price") and t.get("quantity")]
    withtape = []
    posts: dict = {}
    for t in trades:
        got = read_tape(str(t["entry_time"])[:10], t["paper_trade_id"])
        if got:
            withtape.append((t, got[0]))
            posts[t["paper_trade_id"]] = got[1]
    P(f"closed trades since {SINCE}: {len(trades)}; with a per-trade price tape: {len(withtape)}")
    stops = [(t, tape, None) for t, tape in withtape if t.get("exit_reason") == "OPTION_STOP_LOSS" and t.get("option_stop")]
    chain = chain_paths([t for t, _, _ in stops])
    def after_exit(t):
        """Fine POST_EXIT rows where they exist, then 5-minute chain prices only after the last fine row."""
        post = posts.get(t["paper_trade_id"]) or []
        c = chain.get(t["paper_trade_id"]) or []
        cut = post[-1][0] if post else None
        merged = post + [(a, b) for a, b in c if cut is None or a > cut]
        return merged or None

    stops = [(t, tape, after_exit(t)) for t, tape, _ in stops]
    n_fine = sum(1 for t, _, _ in stops if posts.get(t["paper_trade_id"]))
    print(f"stop-loss trades with fine POST_EXIT tape: {n_fine}")
    h = haircut(stops)
    P(f"stop-loss exits with tape: {len(stops)}; with a post-exit chain path: {sum(1 for _, _, c in stops if c)}; typical fill below the recorded price on a stop: {h*100:.2f}%")
    P(f"actual net P&L of the stop-loss trades with tape: {money(sum(t['net_pnl'] for t, _, _ in stops))}")

    # ---------- A: wider stop
    P("\n=== A. WIDER INITIAL STOP (stop-loss exits only; the rest of the book is unchanged) ===")
    use = [(t, tape, c) for t, tape, c in stops if c]
    base = {t["paper_trade_id"]: t["net_pnl"] for t, _, _ in use}
    basetot = sum(base.values())
    P(f"trades replayed (have a post-exit path): {len(use)}   actual net: {money(basetot)}")
    for rule, label in (("R1", "survivors held to 15:25"), ("R2", "survivors sold at the plan's first target, else 15:25")):
        P(f"\n  survivor rule: {label}")
        P(f"  {'stop distance':20s}{'net P&L':>11s}{'vs actual':>11s}{'stopped':>9s}{'target':>8s}{'held':>6s}{'avg loss':>10s}{'worst':>9s}{'better':>8s}")
        for k in KS:
            res = [(t, *replay_stop(t, tape, c, k, h, rule)) for t, tape, c in use]
            tot = sum(r[1] for r in res)
            cnt = defaultdict(int)
            for r in res:
                cnt[r[2]] += 1
            losses = [r[1] for r in res if r[1] < 0]
            better = sum(1 for r in res if r[1] > base[r[0]["paper_trade_id"]] + 1)
            P(f"  {('k=%.1f x original' % k):20s}{money(tot):>11s}{money(tot - basetot):>11s}{cnt['stop']:9d}{cnt['target']:8d}{cnt['held']:6d}{(st.mean(losses) if losses else 0):10.0f}{min(r[1] for r in res):9.0f}{better:8d}")

    P("\n  Where a wider stop helps or hurts (survivors held to 15:25), change in net P&L vs actual:")

    def grp(name, f):
        sub = [(t, tape, c) for t, tape, c in use if f(t)]
        if len(sub) < 4:
            return
        d = {k: sum(replay_stop(t, tape, c, k, h, "R1")[0] - t["net_pnl"] for t, tape, c in sub) for k in (1.5, 2.0)}
        P(f"    {name:36s} n={len(sub):3d}  k=1.5: {money(d[1.5]):>9s}   k=2: {money(d[2.0]):>9s}")

    grp("IV rank >= 70", lambda t: (t.get("iv_rank") or 0) >= 70)
    grp("IV rank < 70 (known)", lambda t: t.get("iv_rank") is not None and t["iv_rank"] < 70)
    grp("spread >= 1.0%", lambda t: (t.get("spread_percent") or 0) >= 1.0)
    grp("spread < 1.0%", lambda t: 0 < (t.get("spread_percent") or 0) < 1.0)
    grp("entered before 09:45", lambda t: str(t["entry_time"])[11:16] < "09:45")
    grp("entered 09:45 or later", lambda t: str(t["entry_time"])[11:16] >= "09:45")
    grp("held under 5 min before the stop", lambda t: (ts(t["exit_time"]) - ts(t["entry_time"])).total_seconds() < 300)
    grp("held 5-30 min before the stop", lambda t: 300 <= (ts(t["exit_time"]) - ts(t["entry_time"])).total_seconds() < 1800)
    grp("held over 30 min before the stop", lambda t: (ts(t["exit_time"]) - ts(t["entry_time"])).total_seconds() >= 1800)
    grp("calls (CE)", lambda t: t["option_type"] == "CE")
    grp("puts (PE)", lambda t: t["option_type"] == "PE")

    # sampling-bias check
    miss = tot_hit = 0
    for t, tape, c in use:
        for k in (2.0, 3.0):
            stop = max(0.05, t["entry_price"] - k * (t["entry_price"] - t["option_stop"]))
            if any(p <= stop for _, p in tape):
                tot_hit += 1
                if not any(p <= stop for _, p in sample5(tape)):
                    miss += 1
    P(f"\n  sampling check: inside the tape window (fine data) a 2x/3x stop was hit {tot_hit} times; 5-minute sampling would have missed {miss} of them ({100*miss/max(1,tot_hit):.0f}%).")
    P("  -> after the exit only 5-minute prices exist, so 'held' results above are OPTIMISTIC for the part of the day after the exit.")

    # ---------- B: profit lock overlay on all closed trades
    P("\n\n=== B. PROFIT LOCK overlay on ALL closed trades with a tape (real exit kept unless the lock is hit first) ===")
    base_all = sum(t["net_pnl"] for t, _ in withtape)
    P(f"trades: {len(withtape)}   actual net: {money(base_all)}")
    P(f"  {'rule':30s}{'net P&L':>11s}{'vs actual':>11s}{'changed':>9s}{'helped':>8s}{'hurt':>6s}")
    for name, trig, lock, keep in LOCKS:
        tot = 0.0
        chg = helped = hurt = 0
        for t, tape in withtape:
            entry = t["entry_price"]
            exit_ts = ts(t["exit_time"])
            peak = entry
            lvl = None
            new = None
            for a, p in tape:
                if a > exit_ts:
                    break
                if lvl is not None and p <= lvl:
                    new = net(t, p * (1 - h))
                    break
                peak = max(peak, p)
                if peak >= entry * (1 + trig / 100):
                    lvl = entry * (1 + lock / 100) if keep is None else entry + keep * (peak - entry)
            if new is None:
                tot += t["net_pnl"]
            else:
                tot += new
                if abs(new - t["net_pnl"]) > 1:
                    chg += 1
                    helped += new > t["net_pnl"]
                    hurt += new < t["net_pnl"]
        P(f"  {name:30s}{money(tot):>11s}{money(tot - base_all):>11s}{chg:9d}{helped:8d}{hurt:6d}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "stop_replay.txt").write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
