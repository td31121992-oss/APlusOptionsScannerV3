"""Run the AI trading agent as a SHADOW judge, keep its decisions in a ledger and grade them forward (read-only; no trading effect; paper only).

Nothing here touches the scanner or a trade. For each trade the scanner took, the agent is shown the facts known at entry (agent_packet.py) and answers TAKE or SKIP. Its answers are appended to
data/ai_agent/decisions.jsonl and graded against what the trades really did. Because a packet holds nothing from after the entry, a day can be judged after the close with no hindsight, and a
past day can be judged the same way (backfill) to get an early read before any forward evidence exists.

    python agent_run.py run --agent mock [--day YYYY-MM-DD | --backfill] [--limit N] [--workers 4]
    python agent_run.py run --agent claude --day 2026-11-12       needs ANTHROPIC_API_KEY (in .env or the environment) and costs money (capped per day)
    python agent_run.py grade --agent claude                      TAKE vs SKIP: win rate, net, what enforcing it would have changed, AUC, by day
"""

from __future__ import annotations

import json
import random
import statistics as st
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "ai_agent"


def ledger_path(root: Path = ROOT) -> Path:
    return root / "data" / "ai_agent" / "decisions.jsonl"


def read_ledger(root: Path = ROOT) -> list[dict[str, Any]]:
    try:
        return [json.loads(l) for l in ledger_path(root).read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        return []


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def base_stats(trades: Sequence[Mapping[str, Any]], before_day: str) -> dict[str, Any]:
    """Base rates of the closed trades entered before `before_day` (what the agent is told, so no hindsight)."""
    rows = [t for t in trades if str(t.get("entry_time"))[:10] < before_day and _f(t.get("net_pnl")) is not None]
    if not rows:
        return {"n": 0}
    pnl = [float(t["net_pnl"]) for t in rows]
    wins, losses = [x for x in pnl if x > 0], [x for x in pnl if x <= 0]
    return {"n": len(rows), "win_pct": 100 * len(wins) / len(rows), "avg_win": st.mean(wins) if wins else 0.0, "avg_loss": st.mean(losses) if losses else 0.0,
            "never_pct": 100 * sum(1 for t in rows if (_f(t.get("mfe_amount")) or 0) <= 0) / len(rows)}


def load_trades(root: Path = ROOT) -> list[dict[str, Any]]:
    """Every closed paper trade, with the derived tags the packet uses (sector picks, opening volume, lag)."""
    import derived_tags
    import trade_archive

    trades = [dict(t) for t in trade_archive.load_history(root / "data" / "reports" / "paper_trade_history.json") if str(t.get("status")).upper() == "CLOSED" and _f(t.get("net_pnl")) is not None]
    derived_tags.enrich(trades, root)
    return sorted(trades, key=lambda t: str(t.get("entry_time")))


def run(agent: Any, trades: Sequence[Mapping[str, Any]], days: Sequence[str] | None = None, root: Path = ROOT, limit: int | None = None, workers: int = 4) -> dict[str, Any]:
    """Judge the trades of `days` (all days if None) that this agent has not judged yet; append to the ledger. Returns counts and spend."""
    import agent_packet
    from sector_rank945 import sector_labels

    sectors = sector_labels(root)
    done = {(r["paper_trade_id"], r["agent"]) for r in read_ledger(root)}
    todo = [t for t in trades if (days is None or str(t.get("entry_time"))[:10] in days) and (t.get("paper_trade_id"), agent.name) not in done]
    if limit:
        todo = todo[:limit]
    stats_by_day: dict[str, dict[str, Any]] = {}
    lock = threading.Lock()
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = {"judged": 0, "errors": 0, "usd": 0.0, "take": 0, "skip": 0}

    def work(t: Mapping[str, Any]) -> None:
        day = str(t.get("entry_time"))[:10]
        with lock:
            stats = stats_by_day.setdefault(day, base_stats(trades, day))
        p = agent_packet.packet(t, sectors)
        d = agent.decide(p, stats)
        row = {"paper_trade_id": t.get("paper_trade_id"), "day": day, "entry_time": str(t.get("entry_time"))[:19], "symbol": t.get("symbol"), "side": t.get("option_type"),
               "agent": agent.name, "model": agent.model, "packet": agent_packet.digest(p), "created_at": datetime.now().isoformat(timespec="seconds"), **d}
        with lock:
            counts["usd"] += d.get("usd", 0.0) or 0.0
            if d["decision"] == "ERROR":
                counts["errors"] += 1
                if d.get("stop_reason") in ("cap",):
                    return                                           # over the daily cap: nothing is recorded, the trade is judged on a later run
            else:
                counts["judged"] += 1
                counts["take" if d["decision"] == "TAKE" else "skip"] += 1
                with path.open("a", encoding="utf-8") as h:
                    h.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    if workers > 1 and len(todo) > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(work, todo))
    else:
        for t in todo:
            work(t)
    counts["pending"] = len(todo) - counts["judged"] - counts["errors"]
    counts["candidates"] = len(todo)
    return counts


def auc(scores: Sequence[float], labels: Sequence[bool]) -> float | None:
    """Probability that a random winner has a higher score than a random loser (0.5 = no information)."""
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def grade(agent_name: str, trades: Sequence[Mapping[str, Any]], root: Path = ROOT) -> str:
    by_id = {t.get("paper_trade_id"): t for t in trades}
    rows = [(r, by_id[r["paper_trade_id"]]) for r in read_ledger(root) if r["agent"] == agent_name and r["decision"] in ("TAKE", "SKIP") and r["paper_trade_id"] in by_id]
    if not rows:
        return f"# AI agent '{agent_name}': no graded decisions yet\n"
    net = lambda t: float(t["net_pnl"])                                                                      # noqa: E731
    take = [t for r, t in rows if r["decision"] == "TAKE"]
    skip = [t for r, t in rows if r["decision"] == "SKIP"]
    allp = [t for _, t in rows]

    def line(name: str, ts: Sequence[Mapping[str, Any]]) -> str:
        if not ts:
            return f"| {name} | 0 | | | | |"
        p = [net(t) for t in ts]
        return (f"| {name} | {len(ts)} | {100 * sum(1 for x in p if x > 0) / len(p):.0f}% | {sum(p):,.0f} | {st.mean(p):,.0f} | "
                f"{100 * sum(1 for t in ts if (_f(t.get('mfe_amount')) or 0) >= 3000) / len(ts):.0f}% |")

    days = sorted({r["day"] for r, _ in rows})
    helped = sum(1 for d in days if sum(net(t) for r, t in rows if r["day"] == d and r["decision"] == "SKIP") < 0)
    scores = [r["p_win"] for r, _ in rows if r.get("p_win") is not None]
    labels = [net(t) > 0 for r, t in rows if r.get("p_win") is not None]
    a = auc(scores, labels)
    p_value = None
    if a is not None and len(scores) >= 30:
        random.seed(5)
        better = sum((auc(random.sample(scores, len(scores)), labels) or 0.5) >= a for _ in range(500))
        p_value = (better + 1) / 501
    lines = [f"# AI agent '{agent_name}' graded against what the trades really did", "",
             f"{len(rows)} decisions on {len(days)} day(s) ({days[0]} .. {days[-1]}); the agent saw only facts known at entry. Hindsight-free, but a small sample: read with the ranges in mind.", "",
             "| Decision | Trades | Win rate | Net Rs | Avg per trade Rs | Touched Rs 3,000 |", "|---|---|---|---|---|---|", line("all judged", allp), line("TAKE", take), line("SKIP", skip), "",
             f"- Enforcing the agent (skipping its SKIPs) would have changed the net by **Rs {-sum(net(t) for t in skip):+,.0f}**; the SKIPs lost money on {helped} of {len(days)} day(s).",
             f"- AUC of its win probability: {a:.3f}" + (f" (random shuffles do as well or better {100 * p_value:.0f}% of the time)" if p_value is not None else "") + " - 0.5 means no information." if a is not None else "- AUC: not enough data.",
             f"- Cost so far: ${sum((r.get('usd') or 0) for r, _ in rows):.2f}.", ""]
    return "\n".join(lines) + "\n"


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] not in ("run", "grade"):
        print(__doc__)
        return 2
    cmd = args[0]
    opt = lambda name, default=None: (args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default)        # noqa: E731
    agent_name = opt("--agent", "mock")
    sys.path.insert(0, str(ROOT))
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    trades = load_trades()
    if cmd == "grade":
        text = grade(agent_name, trades)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"grade_{agent_name}.md").write_text(text, encoding="utf-8")
        print(text)
        return 0
    import agent_judge

    if agent_name == "claude":
        import os

        if not os.getenv("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY is not set (add it to .env). Nothing was called. Use --agent mock to try the pipeline for free.")
            return 3
    judge = agent_judge.judge(agent_name)
    days = None if "--backfill" in args else [opt("--day", date.today().isoformat())]
    result = run(judge, trades, days, limit=int(opt("--limit", 0) or 0) or None, workers=int(opt("--workers", 4)))
    print(f"agent {judge.name} ({judge.model}): {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
