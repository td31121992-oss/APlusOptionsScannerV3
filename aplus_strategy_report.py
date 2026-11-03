"""aplus_strategy_report.py - strategy diagnostics from paper_trades.csv (CLOSED trades)."""
import argparse
import csv
from collections import defaultdict


def f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def table(title, key, rows):
    g = defaultdict(list)
    for r in rows:
        g[key(r)].append(r)
    print("\n" + title)
    print(f"{'group':30}{'n':>4}{'win%':>6}{'net':>11}{'avg':>9}")
    for k, v in sorted(g.items(), key=lambda kv: -sum(f(x["net_pnl"]) for x in kv[1])):
        n = len(v)
        w = sum(1 for x in v if f(x["net_pnl"]) > 0)
        net = sum(f(x["net_pnl"]) for x in v)
        print(f"{str(k)[:29]:30}{n:>4}{w / n * 100:>5.0f}%{net:>11,.0f}{net / n:>9,.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-24")
    ap.add_argument("--csv", default=r"data\reports\paper_trades.csv")
    a = ap.parse_args()

    rows = []
    with open(a.csv, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("status", "")).upper() == "CLOSED" and str(r.get("generated_at", ""))[:10] >= a.since:
                rows.append(r)
    if not rows:
        print("No closed trades since", a.since)
        return

    pnl = [f(r["net_pnl"]) for r in rows]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p < 0]
    flat = len(pnl) - len(wins) - len(losses)
    gw, gl = sum(wins), -sum(losses)
    decided = len(wins) + len(losses)
    wr = len(wins) / decided if decided else 0.0
    aw = gw / len(wins) if wins else 0.0
    al = gl / len(losses) if losses else 0.0

    print("=" * 66)
    print(f"STRATEGY REPORT  closed trades since {a.since}: {len(rows)}")
    print("=" * 66)
    print(f"Wins {len(wins)}  Losses {len(losses)}  Flat {flat}  Win rate {wr * 100:.1f}%")
    print(f"Net {sum(pnl):,.0f}   Gross wins {gw:,.0f}   Gross losses {gl:,.0f}")
    print(f"Avg win {aw:,.0f}   Avg loss {al:,.0f}   Payoff ratio {aw / al if al else 0:.2f}")
    print(f"Profit factor {gw / gl if gl else 0:.2f}   Expectancy/trade {sum(pnl) / len(pnl):,.0f}")
    top2 = sum(sorted(wins, reverse=True)[:2])
    print(f"Top 2 winners = {top2 / gw * 100 if gw else 0:.0f}% of gross profit")
    print("Costs: estimated_costs is 0 in the journal, so real P&L will be lower.")

    table("BY DAY", lambda r: str(r["generated_at"])[:10], rows)
    table("BY EXIT REASON", lambda r: r.get("exit_reason") or "?", rows)
    table("BY SETUP FAMILY", lambda r: r.get("setup_family") or "?", rows)
    table("BY DIRECTION", lambda r: r.get("direction") or "?", rows)
    table("BY ENTRY HOUR", lambda r: (r.get("entry_time") or "")[11:13] or "?", rows)

    print("\nGIVEBACK ON WINNERS (peak vs captured, % of premium)")
    gb = defaultdict(list)
    for r in rows:
        pk = f(r.get("peak_gain_percent"))
        if f(r["net_pnl"]) > 0 and pk > 0:
            gb[r.get("profit_protection_v2_stage") or "NONE"].append((pk, f(r.get("return_percent"))))
    print(f"{'stage':20}{'n':>4}{'avg peak':>10}{'avg got':>9}{'kept':>7}")
    for k, v in sorted(gb.items()):
        sp = sum(x[0] for x in v)
        sr = sum(x[1] for x in v)
        print(f"{k:20}{len(v):>4}{sp / len(v):>10.1f}{sr / len(v):>9.1f}{sr / sp * 100 if sp else 0:>6.0f}%")

    faded = [r for r in rows if f(r.get("peak_gain_percent")) >= 10 and f(r["net_pnl"]) <= 0]
    print(f"\nPeaked >= +10% but closed at or below zero: {len(faded)} trades, net {sum(f(r['net_pnl']) for r in faded):,.0f}")
    for r in faded[:8]:
        print(f"  {r['symbol']:12} peak {f(r.get('peak_gain_percent')):.1f}%  exit {r.get('exit_reason')}  net {f(r['net_pnl']):,.0f}")

    done = [r for r in rows if r.get("post_exit_status") == "DONE"]
    print(f"\nPOST-EXIT (finalized trades: {len(done)})")
    if done:
        print(f"Total left on table {sum(f(r.get('post_exit_left_on_table')) for r in done):,.0f}")
        g = defaultdict(list)
        for r in done:
            g[r.get("exit_reason") or "?"].append(f(r.get("post_exit_move_percent")))
        print(f"{'exit reason':30}{'n':>4}{'avg move%':>10}{'>=15%':>7}")
        for k, v in sorted(g.items()):
            print(f"{k[:29]:30}{len(v):>4}{sum(v) / len(v):>10.1f}{sum(1 for x in v if x >= 15):>7}")

    def mins(r):
        return f(r.get("holding_seconds")) / 60.0

    if wins and losses:
        wm = [mins(r) for r in rows if f(r["net_pnl"]) > 0]
        lm = [mins(r) for r in rows if f(r["net_pnl"]) < 0]
        print(f"\nAvg holding: winners {sum(wm) / len(wm):.0f} min, losers {sum(lm) / len(lm):.0f} min")


if __name__ == "__main__":
    main()
