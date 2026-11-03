"""Option run-up at entry (SHADOW ONLY: a nightly study; nothing trades on it).

The six trades on 26 Oct that never showed a rupee of profit (TATACONSUM, CDSL, MARUTI, PIDILITIND, AMBER, DMART) were all bought after the stock and its option had already run:
the stock had moved 0.2 - 2.7 % our way in the previous 15 minutes and the option had risen +97 % (MARUTI) / +365 % (TATACONSUM) in that time, bought at 81 - 87 % of the contract's
day high. The scanner has no history of the traded contract at entry, so this is measured afterwards: for every paper trade of the day, the 5-minute candles of the contract that was
traded (Dhan intraday chart, any expiry) up to the entry minute, and

    run15_pct       the entry price against the contract's close 15 minutes earlier, %
    run30_pct       the same over 30 minutes
    from_low_pct    the entry price against the contract's low so far today, %
    vs_high_pct     the entry price as a share of the contract's high so far today, %  (100 = bought at the day's high)

    data/option_runup/ledger.csv   one row per trade: the numbers above, the trade's best profit (peak Rs), result (Rs) and whether it never showed a profit
    data/option_runup/review.md    trades split by how far the option had already run: count, zero-peak count, median best profit, total result

    python option_runup.py [YYYY-MM-DD]   rebuild that day (default today) and the review
"""

from __future__ import annotations

import csv
import json
import os
import statistics as st
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
JOURNAL = ("data", "intraday_movement", "paper_trade_journal.json")
LEDGER = ("data", "option_runup", "ledger.csv")
REVIEW = ("data", "option_runup", "review.md")
RATE_SLEEP = 0.25
ZERO_PEAK_RS = 30.0
BUCKETS = (("run15 under 25 %", None, 25.0), ("run15 25 - 75 %", 25.0, 75.0), ("run15 75 % and over", 75.0, None))
FIELDS = ["day", "symbol", "direction", "time", "contract", "entry", "run15_pct", "run30_pct", "from_low_pct", "vs_high_pct", "peak_rs", "result_rs", "zero_peak"]


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def metrics(candles: Sequence[Mapping[str, float]], entry_minute: int, entry: float) -> dict[str, Any]:
    """candles: 5-minute bars {minute (start), high, low, close}. Only bars that started before the entry minute are used."""
    bars = sorted((c for c in candles if c["minute"] < entry_minute), key=lambda c: c["minute"])
    if entry <= 0 or len(bars) < 2:
        return {}

    def close_before(back: int) -> float | None:
        old = [c for c in bars if c["minute"] <= entry_minute - back]
        return old[-1]["close"] if old else None

    out: dict[str, Any] = {}
    for name, back in (("run15_pct", 15), ("run30_pct", 30)):
        ref = close_before(back)
        if ref and ref > 0:
            out[name] = round((entry / ref - 1) * 100, 1)
    low, high = min(c["low"] for c in bars), max(c["high"] for c in bars)
    if low > 0:
        out["from_low_pct"] = round((entry / low - 1) * 100, 1)
    if high > 0:
        out["vs_high_pct"] = round(entry / max(high, entry) * 100, 1)
    return out


def bucket(run15: Any) -> str:
    v = _f(run15, float("nan"))
    if v != v:
        return "no history"
    for name, lo, hi in BUCKETS:
        if (lo is None or v >= lo) and (hi is None or v < hi):
            return name
    return "no history"


def trade_row(trade: Mapping[str, Any], candles: Sequence[Mapping[str, float]], day: str) -> dict[str, Any] | None:
    when = str(trade.get("entry_time") or "")
    entry, qty = _f(trade.get("entry_price")), _f(trade.get("quantity"))
    if not when.startswith(day) or entry <= 0:
        return None
    peak_rs = round(max((_f(trade.get("highest_option_price")) - entry) * qty, 0.0), 0)
    result = _f(trade.get("net_pnl") if trade.get("status") == "CLOSED" else trade.get("unrealized_pnl"))
    m = metrics(candles, int(when[11:13]) * 60 + int(when[14:16]), entry)
    return {"day": day, "symbol": trade.get("symbol"), "direction": trade.get("direction"), "time": when[11:16], "contract": trade.get("trading_symbol"), "entry": entry,
            **{k: m.get(k, "") for k in ("run15_pct", "run30_pct", "from_low_pct", "vs_high_pct")}, "peak_rs": peak_rs, "result_rs": round(result), "zero_peak": int(peak_rs <= ZERO_PEAK_RS)}


def fetch_factory(root: Path) -> Callable[[str, str], list[dict[str, float]]]:
    import pandas as pd
    import requests
    from dotenv import load_dotenv

    sys.path.insert(0, str(root))
    load_dotenv(root / ".env")
    from dhan_auth import resolve_access_token

    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    token = resolve_access_token(project_root=root, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    headers = {"access-token": token, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"}
    session, last = requests.Session(), [0.0]

    def fetch(security_id: str, day: str) -> list[dict[str, float]]:
        for attempt in range(4):
            time.sleep(max(0.0, RATE_SLEEP - (time.time() - last[0])))
            last[0] = time.time()
            r = session.post("https://api.dhan.co/v2/charts/intraday", headers=headers, timeout=30, json={
                "securityId": str(security_id), "exchangeSegment": "NSE_FNO", "instrument": "OPTSTK", "interval": "5", "oi": False,
                "fromDate": f"{day} 09:00:00", "toDate": f"{(date.fromisoformat(day) + timedelta(days=1)).isoformat()} 15:30:00"})
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code != 200:
                return []
            d = r.json()
            idx = pd.to_datetime(d.get("timestamp") or [], unit="s", utc=True).tz_convert("Asia/Kolkata")
            return [{"minute": t.hour * 60 + t.minute, "high": float(h), "low": float(lo), "close": float(c)}
                    for t, h, lo, c in zip(idx, d.get("high", []), d.get("low", []), d.get("close", [])) if t.date().isoformat() == day]
        return []

    return fetch


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as h:
        return list(csv.DictReader(h))


def render(rows: Sequence[Mapping[str, Any]]) -> str:
    days = sorted({r["day"] for r in rows})
    lines = ["# Option run-up at entry (shadow; nothing trades on this)", "",
             f"Days: {len(days)} ({days[0] if days else '-'} .. {days[-1] if days else '-'}), trades: {len(rows)}. run15 = the traded option's entry price against its close 15 minutes earlier. "
             f"Zero-peak = the option never gave a profit of {ZERO_PEAK_RS:.0f} Rs after entry.", "",
             "| run-up before entry | trades | zero-peak | median best profit Rs | result Rs |", "|---|---|---|---|---|"]
    for name in [b[0] for b in BUCKETS] + ["no history"]:
        g = [r for r in rows if bucket(r.get("run15_pct")) == name]
        if g:
            lines.append(f"| {name} | {len(g)} | {sum(int(_f(r['zero_peak'])) for r in g)} | {st.median(_f(r['peak_rs']) for r in g):.0f} | {sum(_f(r['result_rs']) for r in g):,.0f} |")
    hi = [r for r in rows if _f(r.get("vs_high_pct")) >= 90]
    lo = [r for r in rows if r.get("vs_high_pct") not in ("", None) and _f(r.get("vs_high_pct")) < 90]
    lines += ["", "| bought at | trades | zero-peak | median best profit Rs | result Rs |", "|---|---|---|---|---|"]
    for name, g in (("90 % or more of the contract's day high", hi), ("under 90 % of the day high", lo)):
        if g:
            lines.append(f"| {name} | {len(g)} | {sum(int(_f(r['zero_peak'])) for r in g)} | {st.median(_f(r['peak_rs']) for r in g):.0f} | {sum(_f(r['result_rs']) for r in g):,.0f} |")
    lines += ["", "Judge it on forward days only; a filter has to beat the other bucket over many days, not one.", ""]
    return "\n".join(lines)


def run(day: str, root: Path = ROOT, fetch: Callable[[str, str], list[dict[str, float]]] | None = None) -> Path | None:
    try:
        trades = json.loads(root.joinpath(*JOURNAL).read_text(encoding="utf-8")).get("trades") or []
    except (OSError, ValueError):
        return None
    todays = [t for t in trades if str(t.get("entry_time", "")).startswith(day)]
    if not todays:
        return None
    fetch = fetch or fetch_factory(root)
    cache: dict[str, list[dict[str, float]]] = {}
    new = []
    for t in todays:
        sid = str(t.get("option_security_id") or "")
        if not sid:
            continue
        if sid not in cache:
            cache[sid] = fetch(sid, day)
        row = trade_row(t, cache[sid], day)
        if row:
            new.append(row)
    path = root.joinpath(*LEDGER)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in _read(path) if r.get("day") != day] + new
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    out = root.joinpath(*REVIEW)
    out.write_text(render(rows), encoding="utf-8")
    return out


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else datetime.now(IST).strftime("%Y-%m-%d")
    print(run(d))
    print(ROOT.joinpath(*REVIEW).read_text(encoding="utf-8"))
