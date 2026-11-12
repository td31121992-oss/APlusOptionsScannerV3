"""Sanity checks on tools/research/stop_replay.py results (research only)."""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_run  # noqa: E402
import stop_replay as sr  # noqa: E402


def main() -> None:
    trades = [t for t in agent_run.load_trades(ROOT) if str(t.get("status")).upper() == "CLOSED" and str(t.get("entry_time"))[:10] >= sr.SINCE
              and t.get("entry_price") and t.get("exit_price") and t.get("quantity")]
    wt = []
    for t in trades:
        got = sr.read_tape(str(t["entry_time"])[:10], t["paper_trade_id"])
        if got:
            wt.append((t, got[0]))
    stops = [(t, tape, None) for t, tape in wt if t.get("exit_reason") == "OPTION_STOP_LOSS" and t.get("option_stop")]
    chain = sr.chain_paths([t for t, _, _ in stops])
    use = [(t, tape, chain[t["paper_trade_id"]]) for t, tape, _ in stops if t["paper_trade_id"] in chain]
    base = {t["paper_trade_id"]: t["net_pnl"] for t, _, _ in use}

    print("1) tape noise: share of consecutive tape ticks that move more than 3% / 8%")
    big3 = big8 = n = 0
    for _, tape in wt:
        for (a, p), (b, q) in zip(tape, tape[1:]):
            if p > 0:
                n += 1
                m = abs(q / p - 1)
                big3 += m > 0.03
                big8 += m > 0.08
    print(f"   ticks {n:,}; >3% jump {100*big3/n:.2f}%; >8% jump {100*big8/n:.2f}%")

    print("\n2) 5-minute sampling miss rate vs the fine tape, at the depths a wider stop would sit (drawdown from entry), all 389 tapes")
    for d in (0.15, 0.20, 0.25, 0.30, 0.40):
        fine = miss = 0
        for t, tape in wt:
            lvl = t["entry_price"] * (1 - d)
            if any(p <= lvl for _, p in tape):
                fine += 1
                if not any(p <= lvl for _, p in sr.sample5(tape)):
                    miss += 1
        print(f"   drawdown {int(d*100)}%: fine tape hit {fine} trades; 5-min sampling misses {miss} ({100*miss/max(1,fine):.0f}%)")

    print("\n3) extra spread/slippage on 'held' and 'target' exits (survivors held to 15:25), change vs actual")
    for hx in (0.0, 0.01, 0.02, 0.03):
        row = []
        for k in (1.5, 2.0, 3.0):
            tot = 0.0
            for t, tape, c in use:
                v, how = sr.replay_stop(t, tape, c, k, 0.0, "R1")
                if how == "held":
                    v = sr.net(t, (v + (t.get("estimated_costs") or 0) + t["entry_price"] * t["quantity"]) / t["quantity"] * (1 - hx))
                tot += v - base[t["paper_trade_id"]]
            row.append(f"k={k}: {tot:+,.0f}")
        print(f"   extra haircut {int(hx*100)}%  " + "   ".join(row))

    print("\n4) is it a few days or the whole period? (k=1.5, held to 15:25) change vs actual by entry day")
    byday = defaultdict(lambda: [0, 0.0, 0.0])
    for t, tape, c in use:
        d = str(t["entry_time"])[:10]
        v = sr.replay_stop(t, tape, c, 1.5, 0.0, "R1")[0]
        byday[d][0] += 1
        byday[d][1] += v - t["net_pnl"]
        byday[d][2] += t["net_pnl"]
    pos = 0
    for d in sorted(byday):
        n, delta, act = byday[d]
        pos += delta > 0
        print(f"   {d}  trades {n:2d}  actual {act:+9,.0f}  change {delta:+9,.0f}")
    print(f"   days where wider stop helped: {pos} of {len(byday)}")
    tot = sum(v[1] for v in byday.values())
    top2 = sum(sorted((v[1] for v in byday.values()), reverse=True)[:2])
    print(f"   total change {tot:+,.0f}; the two best days contribute {top2:+,.0f}")

    print("\n5) market drift: what did the stock do after the stop? share of stopped trades whose option was above the STOP price again at 15:25, calls vs puts")
    for side in ("CE", "PE"):
        sub = [(t, c) for t, _, c in use if t["option_type"] == side]
        up = sum(1 for t, c in sub if c[-1][1] > t["option_stop"])
        above_entry = sum(1 for t, c in sub if c[-1][1] > t["entry_price"])
        print(f"   {side}: {len(sub)} stopped; option back above the stop at the close in {up}; above ENTRY at the close in {above_entry}")

    print("\n6) profit-lock: what do trades that were up >= 7% do afterwards? (all 389, real result)")
    ups = [(t, tape) for t, tape in wt if max(p for _, p in tape) >= t["entry_price"] * 1.07]
    fin = [t["net_pnl"] for t, _ in ups]
    print(f"   trades that reached +7%: {len(ups)}; of those finished net > 0: {sum(1 for x in fin if x > 0)}; net < 0: {sum(1 for x in fin if x < 0)}; total net {sum(fin):+,.0f}")
    big = [(t, tape) for t, tape in wt if max(p for _, p in tape) >= t["entry_price"] * 1.10]
    fin = [t["net_pnl"] for t, _ in big]
    print(f"   reached +10%: {len(big)}; finished > 0: {sum(1 for x in fin if x > 0)}; < 0: {sum(1 for x in fin if x < 0)}; total net {sum(fin):+,.0f}")
    gave = [(t, tape) for t, tape in ups if t["net_pnl"] < 0]
    print(f"   gave it all back and lost money: {len(gave)} trades, {sum(t['net_pnl'] for t, _ in gave):+,.0f}")
    other = [t["net_pnl"] for t, _ in ups if t["net_pnl"] >= 0]
    print(f"   the winners among them made {sum(other):+,.0f} (avg {st.mean(other):+,.0f}); a lock that clips them early costs that")


if __name__ == "__main__":
    main()
