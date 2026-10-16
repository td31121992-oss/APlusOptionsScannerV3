"""Does a fully aligned DAILY trend separate good signals from bad ones? (research only; changes nothing)

Question (16 Oct 2026): TCS, the only winner of the day, had its daily trend fully with the trade (score +1.0) while the losers were against, mixed or marginal.
The scan/daily tags exist only for the last two days, so this rebuilds the daily score for every signal on file from daily candles:

    score  = the same DAILY gauge the trade page uses (stock_trend.analyse: ADX, MACD, RSI, SuperTrend, EMA 5/10/20/50/100/200 votes), computed on the
             daily candles BEFORE the signal's day, signed in the trade's direction (+1 = every vote with the trade, -1 = every vote against)

Signals come from data/missed_opportunities/<day>/option_returns.json (ATM option bought at the signal, held to close, hindsight, before costs). Output:
    data/shadow_rules/daily_alignment.md   and   data/shadow_rules/daily_alignment.csv

It also tests the idea behind today's question: "let a signal through when the daily trend is fully aligned, even if a gate would block it".

    python daily_alignment_review.py            (fetches 213 daily histories - run after the market)
"""

from __future__ import annotations

import csv
import glob
import json
import os
import statistics as st
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
BUCKETS = (("fully aligned (0.9 to 1.0)", 0.9, 1.01), ("strong (0.6 to 0.9)", 0.6, 0.9), ("moderate (0.2 to 0.6)", 0.2, 0.6),
           ("neutral (-0.2 to 0.2)", -0.2, 0.2), ("against (below -0.2)", -1.01, -0.2))


def fetch_daily(security_id: int, until: str, tries: int = 4) -> list[tuple[str, float, float, float, float, float]]:
    import requests
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from dhan_auth import resolve_access_token

    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    tok = resolve_access_token(project_root=ROOT, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    for attempt in range(tries):
        time.sleep(0.35 * (attempt + 1))
        try:
            r = requests.post("https://api.dhan.co/v2/charts/historical", timeout=40, headers={"access-token": tok, "client-id": cid, "Content-Type": "application/json"},
                              json={"securityId": str(int(security_id)), "exchangeSegment": "NSE_EQ", "instrument": "EQUITY", "expiryCode": 0, "oi": False,
                                    "fromDate": (date.fromisoformat(until) - timedelta(days=330)).isoformat(), "toDate": until})
        except requests.RequestException:
            continue
        if r.status_code == 200:
            d = r.json() or {}
            return [(datetime.fromtimestamp(int(t), IST).date().isoformat(), float(d["open"][i]), float(d["high"][i]), float(d["low"][i]), float(d["close"][i]),
                     float((d.get("volume") or [0] * len(d["close"]))[i] or 0)) for i, t in enumerate(d.get("timestamp") or [])]
        if r.status_code not in (429, 500, 502, 503, 504, 805):
            break
    return []


def daily_score(candles: list[tuple[str, float, float, float, float, float]], day: str) -> float | None:
    """DAILY gauge score from the candles strictly before `day` (bullish minus bearish votes over all votes)."""
    import stock_trend

    past = [c for c in candles if c[0] < day]
    if len(past) < 25:
        return None
    a = stock_trend.analyse([c[1] for c in past], [c[2] for c in past], [c[3] for c in past], [c[4] for c in past], [c[5] for c in past], 0, "DAILY", use_vwap=False)
    return float(a["score"]) if a.get("bullish", 0) + a.get("bearish", 0) + a.get("neutral", 0) else None


def build_rows(signals_by_day: dict[str, list[dict[str, Any]]], history: dict[str, list[tuple]]) -> list[dict[str, Any]]:
    rows = []
    for day, sigs in sorted(signals_by_day.items()):
        cache: dict[str, float | None] = {}
        for r in sigs:
            s = r["symbol"]
            if s not in history:
                continue
            if s not in cache:
                cache[s] = daily_score(history[s], day)
            sc = cache[s]
            if sc is None:
                continue
            signed = sc if r.get("dir") == "BULLISH" else -sc
            rows.append({"day": day, "symbol": s, "dir": r.get("dir"), "ready": r.get("ready"), "fate": str(r.get("fate") or "").split(":")[0],
                         "entry": r.get("entry"), "close": r.get("close"), "best": r.get("best"), "stop_first": int(bool(r.get("stop_first"))),
                         "daily_signed": round(signed, 3)})
    return rows


def _f(v: Any) -> float | None:
    try:
        return float(v) if v not in ("", None) else None
    except (TypeError, ValueError):
        return None


def _line(label: str, g: list[dict[str, Any]]) -> str:
    g = [r for r in g if _f(r.get("close")) is not None]
    if not g:
        return f"| {label} | 0 | | | | |"
    days = defaultdict(list)
    for r in g:
        days[r["day"]].append(_f(r["close"]))
    c = [_f(r["close"]) for r in g]
    return (f"| {label} | {len(g)} | {st.mean(c):+.1f}% | {100 * sum(x > 0 for x in c) / len(c):.0f}% | "
            f"{100 * sum(1 for r in g if _f(r.get('best')) is not None and _f(r['best']) >= 15) / len(g):.0f}% | {sum(1 for v in days.values() if st.mean(v) > 0)}/{len(days)} |")


def write_report(rows: list[dict[str, Any]], root: Path = ROOT) -> Path:
    head = "| Bucket | Signals | Mean close | Up | Hit +15% | Days + |\n|---|---|---|---|---|---|"
    out = ["# Daily-trend alignment vs signal outcome (research only)", "",
           f"{len(rows)} signals on {len({r['day'] for r in rows})} days. Score = daily trend gauge in the TRADE's direction (+1 all votes with it), computed on candles before the day. "
           "ATM option held to close, hindsight, before costs.", ""]
    for scope, sub in (("All signals", rows), ("Calls", [r for r in rows if r["dir"] == "BULLISH"]), ("Puts", [r for r in rows if r["dir"] == "BEARISH"]),
                       ("Signals we traded", [r for r in rows if r["fate"] == "TRADED"])):
        out += [f"## {scope}", "", head]
        out += [_line(label, [r for r in sub if lo <= r["daily_signed"] < hi]) for label, lo, hi in BUCKETS]
        out.append("")
    import gate_shadow as gsh

    out += ["## Override test", "", "Signals the premium/chasing/call-early gates would NOT have blocked vs. signals a gate would block but the daily trend is fully aligned (0.9+):", "", head]
    out += [_line("Gates would block, daily NOT fully aligned", [r for r in rows if r.get("blocked") == 1 and r["daily_signed"] < 0.9]),
            _line("Gates would block, daily fully aligned (override)", [r for r in rows if r.get("blocked") == 1 and r["daily_signed"] >= 0.9]),
            _line("Gates would not block", [r for r in rows if r.get("blocked") == 0]), ""]
    out += ["_Hindsight and small samples; nothing here changes trading._", ""]
    path = root / "data" / "shadow_rules" / "daily_alignment.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def attach_gate_flags(rows: list[dict[str, Any]], root: Path = ROOT) -> None:
    """Add blocked = 1/0 from the nightly gate review rows (premium80, ce_early, chasing) for the same signals."""
    flags: dict[tuple[str, str, str, str], int] = {}
    for p in glob.glob(str(root / "data" / "shadow_rules" / "gate_review" / "20*.csv")):
        with open(p, encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                vals = [r.get(k) for k in ("premium80", "ce_early", "chasing")]
                if all(v in ("", None) for v in vals):
                    continue
                flags[(r["day"], r["symbol"], r["dir"], r["ready"])] = int(any(v == "1" for v in vals))
    for r in rows:
        k = flags.get((r["day"], r["symbol"], r["dir"], r["ready"]))
        if k is not None:
            r["blocked"] = k


def main() -> int:
    from order_book_recorder import _universe

    signals: dict[str, list[dict[str, Any]]] = {}
    for p in sorted(glob.glob(str(ROOT / "data" / "missed_opportunities" / "2026-10-*" / "option_returns.json"))):
        day = Path(p).parent.name
        signals[day] = [r for r in json.loads(Path(p).read_text(encoding="utf-8")) if r.get("kind") == "ATM"]
    until = (date.fromisoformat(max(signals)) + timedelta(days=1)).isoformat()
    history: dict[str, list[tuple]] = {}
    symbols = sorted({r["symbol"] for v in signals.values() for r in v})
    uni = _universe()
    for i, s in enumerate(symbols):
        if s in uni:
            history[s] = fetch_daily(uni[s], until)
        if i % 40 == 0:
            print(i, len(history), flush=True)
    rows = build_rows(signals, history)
    attach_gate_flags(rows)
    with open(ROOT / "data" / "shadow_rules" / "daily_alignment.csv", "w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=["day", "symbol", "dir", "ready", "fate", "entry", "close", "best", "stop_first", "daily_signed", "blocked"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(write_report(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
