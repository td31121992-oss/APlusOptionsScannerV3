"""Review of the two exit shadows we are deciding on: your LADDER and the stock BURST-OVER exit (research only - changes nothing).

For every closed or open paper trade since the shadows started recording (15 Oct 2026) it adds up what each shadow rule would have
changed in rupees versus the real exit, per day and cumulatively, and prints a plain verdict.

    python exit_review.py [first_day]      writes data/shadow_rules/exit_review.md and prints it

Shadows compared (all from the trade journal's d_<name> fields, rupees versus the real exit):
    user_ladder   +5% -> stop -15%, +10% lock +3%, +20% lock +13%, +30% lock +22%, +2 per +5%
    sbg60         stock gave back 60% of its best move (after +0.5%)  <- "burst over"
    sbg40         stock gave back 40% of its best move
    sstall10      stock made no new best for 10 minutes
    half10        half booked at +10%, rest on the normal exits
Verdict rule: a rule "supports enforcing" when it has at least 4 busy days (3+ trades) AND its cumulative rupee change is positive AND it helped on at least 60% of those days AND no single day lost more than the best day gained. Otherwise "not yet".
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
FIRST_DAY = "2026-10-15"
RULES = (("user_ladder", "Your ladder"), ("sbg60", "Burst over (gave back 60%)"), ("sbg40", "Burst over (gave back 40%)"),
         ("sstall10", "Stock stalled 10 min"), ("half10", "Half booked at +10%"))
MIN_TRADES_DAY = 3
MIN_BUSY_DAYS = 4          # never call a rule "supported" on fewer busy days than this


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def load(root: Path = ROOT, first_day: str = FIRST_DAY) -> list[dict[str, Any]]:
    import trade_journal

    return [t for t in trade_journal.payload("", "", root)["trades"] if str(t.get("day")) >= first_day]


def summarize(trades: Iterable[dict[str, Any]]) -> dict[str, Any]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        by_day[str(t.get("day"))].append(t)
    days = sorted(by_day)
    out: dict[str, Any] = {"days": days, "trades": sum(len(v) for v in by_day.values()),
                           "real": round(sum(_f(t.get("net")) for v in by_day.values() for t in v)), "rules": {}}
    for name, label in RULES:
        key = f"d_{name}"
        have = [t for v in by_day.values() for t in v if key in t]
        if not have:
            continue
        per_day = []
        for d in days:
            g = [t for t in by_day[d] if key in t]
            per_day.append({"day": d, "n": len(by_day[d]), "real": round(sum(_f(t.get("net")) for t in by_day[d])),
                            "delta": round(sum(_f(t.get(key)) for t in g)),
                            "acted": sum(1 for t in g if _f(t.get(f"hit_{name}"))),
                            "helped": sum(1 for t in g if _f(t.get(key)) > 0), "hurt": sum(1 for t in g if _f(t.get(key)) < 0)})
        total = sum(p["delta"] for p in per_day)
        big_days = [p for p in per_day if p["n"] >= MIN_TRADES_DAY]
        helped_days = sum(1 for p in big_days if p["delta"] > 0)
        best = max((p["delta"] for p in per_day), default=0)
        worst = min((p["delta"] for p in per_day), default=0)
        ok = len(big_days) >= MIN_BUSY_DAYS and total > 0 and helped_days / len(big_days) >= 0.6 and abs(worst) <= max(best, 0)
        out["rules"][name] = {"label": label, "per_day": per_day, "total": total, "days_helped": helped_days, "days_counted": len(big_days),
                              "best_day": best, "worst_day": worst, "supports": ok,
                              "acted": sum(p["acted"] for p in per_day), "trades_hurt": sum(p["hurt"] for p in per_day),
                              "trades_helped": sum(p["helped"] for p in per_day)}
    return out


def render(s: dict[str, Any]) -> str:
    days = s["days"]
    out = ["# Exit review: your ladder and the burst-over exit (shadow)", "",
           f"{len(days)} day(s) on file ({days[0] if days else '-'} to {days[-1] if days else '-'}), {s['trades']} trades, real net "
           f"**{s['real']:+,}**. Each number is rupees versus what the real exits made (positive = the rule would have made more).", ""]
    if not s["rules"]:
        return "\n".join(out + ["No shadow fields on file yet.", ""])
    out += ["| Rule | Total vs real | New total | Days helped (days with 3+ trades) | Best day | Worst day | Trades helped / hurt | Verdict |",
            "|---|---|---|---|---|---|---|---|"]
    for name, r in s["rules"].items():
        out.append(f"| {r['label']} | {r['total']:+,} | {s['real'] + r['total']:+,} | {r['days_helped']} of {r['days_counted']} | "
                   f"{r['best_day']:+,} | {r['worst_day']:+,} | {r['trades_helped']} / {r['trades_hurt']} | "
                   f"{'**supports enforcing**' if r['supports'] else ('needs more days (%d of %d)' % (r['days_counted'], MIN_BUSY_DAYS) if r['days_counted'] < MIN_BUSY_DAYS else 'not yet')} |")
    for name in ("user_ladder", "sbg60"):
        r = s["rules"].get(name)
        if not r:
            continue
        out += ["", f"## {r['label']} by day", "", "| Day | Trades | Real net | Rule changes | Acted on | Helped | Hurt |", "|---|---|---|---|---|---|---|"]
        for p in r["per_day"]:
            out.append(f"| {p['day']} | {p['n']} | {p['real']:+,} | {p['delta']:+,} | {p['acted']} | {p['helped']} | {p['hurt']} |")
    out += ["", "_Research only. A rule 'supports enforcing' when it is positive in total, helped on 60%+ of the busy days and no day "
            "lost more than the best day gained. That is a prompt for a decision, not a decision._", ""]
    return "\n".join(out)


def write(root: Path = ROOT, first_day: str = FIRST_DAY) -> Path:
    s = summarize(load(root, first_day))
    folder = root / "data" / "shadow_rules"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "exit_review.md"
    path.write_text(render(s), encoding="utf-8")
    return path


def main() -> int:
    first = sys.argv[1] if len(sys.argv) > 1 else FIRST_DAY
    path = write(ROOT, first)
    print(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
