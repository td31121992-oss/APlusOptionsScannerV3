"""What the ATM and one-strike-OTM options of every scanner signal did after the signal (read-only, hindsight).

    python missed_option_returns.py [--day YYYY-MM-DD]

For each stock/direction in data/missed_opportunities/<day>/signals.csv this fetches the 5-minute candles of the
near-month ATM and next-OTM option from Dhan (one read-only call each, ~1.4 calls/s), assumes entry at the first
candle after the signal plus 1%, and records best / worst / close return, when +30% was first reached and whether
a 25% stop would have been hit first. Writes option_returns.json and option_returns.md next to the day's report.
These are best-case, hindsight numbers - not achievable P&L.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
ENTRY_SLIP = 1.01
RATE_SLEEP = 0.7


def option_metrics(candles: list[dict], ready_minute: int, target: float = 0.30, stop: float = 0.25) -> dict[str, Any] | None:
    """candles: [{'minute': minutes since midnight, 'high','low','close'}] in time order."""
    after = [c for c in candles if c["minute"] >= ready_minute]
    if len(after) < 2 or after[0]["close"] <= 0:
        return None
    entry = after[0]["close"] * ENTRY_SLIP
    rest = after[1:]
    best = max(c["high"] for c in rest) / entry - 1
    worst = min(c["low"] for c in rest) / entry - 1
    t_hit, stop_first = None, None
    for c in rest:
        if c["low"] <= entry * (1 - stop) and t_hit is None:
            stop_first = True
        if c["high"] >= entry * (1 + target):
            t_hit = c["minute"]
            stop_first = bool(stop_first)
            break
    return {"entry": round(entry, 2), "best": round(best * 100, 1), "worst": round(worst * 100, 1),
            "close": round((rest[-1]["close"] / entry - 1) * 100, 1),
            "t_target": f"{t_hit // 60:02d}:{t_hit % 60:02d}" if t_hit is not None else "", "stop_first": stop_first}


def summarize(rows: list[dict]) -> list[dict]:
    out = []
    for kind in ("ATM", "OTM1"):
        sel = [r for r in rows if r["kind"] == kind]
        if not sel:
            continue
        hitters = [r for r in sel if r["best"] >= 30]
        out.append({"kind": kind, "n": len(sel), "hit30": len(hitters), "hit40": sum(r["best"] >= 40 for r in sel),
                    "hit100": sum(r["best"] >= 100 for r in sel), "close30": sum(r["close"] >= 30 for r in sel),
                    "stop_first_of_hitters": sum(1 for r in hitters if r.get("stop_first")),
                    "fell_25": sum(r["worst"] <= -25 for r in sel)})
    return out


def render(day: str, rows: list[dict]) -> str:
    lines = [f"# Option returns of today's signals - {day}", "",
             "Hindsight, best-case: entry = first 5-min candle after the signal +1%. Not achievable P&L.", ""]
    for s in summarize(rows):
        lines.append(f"- **{s['kind']}** ({s['n']} options): reached +30% {s['hit30']} | +40% {s['hit40']} | +100% {s['hit100']} | "
                     f"closed the day at +30% or more {s['close30']} | of the +30% hitters, a 25% stop would have hit first in "
                     f"{s['stop_first_of_hitters']} | fell to -25% at some point {s['fell_25']}")
    by_fate: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["kind"] == "ATM":
            by_fate[r["fate"].split(":")[0]].append(r)
    lines += ["", "## ATM by decision at the time", "", "| fate | n | reached +30% | median best | median close |", "|---|---:|---:|---:|---:|"]
    for fate, v in sorted(by_fate.items(), key=lambda kv: -len(kv[1])):
        b, c = sorted(r["best"] for r in v), sorted(r["close"] for r in v)
        lines.append(f"| {fate} | {len(v)} | {sum(r['best'] >= 30 for r in v)} ({sum(r['best'] >= 30 for r in v) * 100 // len(v)}%) | "
                     f"{b[len(b) // 2]:+.0f}% | {c[len(c) // 2]:+.0f}% |")
    top = sorted((r for r in rows if r["kind"] == "ATM"), key=lambda r: -r["best"])[:12]
    lines += ["", "## Best ATM options", "", "| symbol | dir | ready | strike | best | worst | close | +30% at | fate |", "|---|---|---|---|---:|---:|---:|---|---|"]
    lines += [f"| {r['symbol']} | {r['dir'][:4]} | {r['ready']} | {r['strike']:g} | {r['best']:+.0f}% | {r['worst']:+.0f}% | "
              f"{r['close']:+.0f}% | {r['t_target'] or '-'} | {r['fate']} |" for r in top]
    return "\n".join(lines) + "\n"


def run(day: str, root: Path = ROOT) -> Path | None:
    sig_path = root / "data" / "missed_opportunities" / day / "signals.csv"
    if not sig_path.exists():
        return None
    import pandas as pd
    import requests
    from dotenv import load_dotenv

    sys.path.insert(0, str(root))
    load_dotenv(root / ".env")
    from dhan_auth import resolve_access_token

    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    token = resolve_access_token(project_root=root, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    headers = {"access-token": token, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"}
    signals = list(csv.DictReader(sig_path.open(encoding="utf-8")))
    master = pd.read_csv(root / "data" / "cache" / "api-scrip-master-detailed.csv", low_memory=False,
                         usecols=["SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL", "SM_EXPIRY_DATE", "STRIKE_PRICE", "OPTION_TYPE"])
    master = master[master.INSTRUMENT == "OPTSTK"].copy()
    master["exp"] = master.SM_EXPIRY_DATE.astype(str).str[:10]
    session, last = requests.Session(), [0.0]

    def fetch(security_id: int) -> list[dict]:
        for attempt in range(4):
            time.sleep(max(0.0, RATE_SLEEP - (time.time() - last[0])))
            last[0] = time.time()
            r = session.post("https://api.dhan.co/v2/charts/intraday", headers=headers, timeout=30, json={
                "securityId": str(security_id), "exchangeSegment": "NSE_FNO", "instrument": "OPTSTK", "interval": "5",
                "oi": False, "fromDate": f"{day} 09:15:00", "toDate": f"{day} 15:30:00"})
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code != 200:
                return []
            d = r.json()
            idx = pd.to_datetime(d.get("timestamp") or [], unit="s", utc=True).tz_convert("Asia/Kolkata")
            return [{"minute": t.hour * 60 + t.minute, "high": float(h), "low": float(lo), "close": float(c)}
                    for t, h, lo, c in zip(idx, d.get("high", []), d.get("low", []), d.get("close", []))]
        return []

    rows: list[dict] = []
    for s in signals:
        sym, direction = s["symbol"], s["direction"]
        side = "CE" if direction == "BULLISH" else "PE"
        sub = master[(master.UNDERLYING_SYMBOL == sym) & (master.OPTION_TYPE == side)]
        expiries = sorted(e for e in sub.exp.unique() if e >= day)
        if not expiries:
            continue
        sub = sub[sub.exp == expiries[0]]
        strikes = sorted(sub.STRIKE_PRICE.unique())
        spot = float(s["entry_price"])
        atm = min(strikes, key=lambda k: abs(k - spot))
        i = strikes.index(atm)
        otm = strikes[min(i + 1, len(strikes) - 1)] if side == "CE" else strikes[max(i - 1, 0)]
        hh, mm = (int(x) for x in s["first_ready"].split(":"))
        for kind, strike in (("ATM", atm), ("OTM1", otm)):
            candles = fetch(int(sub[sub.STRIKE_PRICE == strike].iloc[0].SECURITY_ID))
            m = option_metrics(candles, hh * 60 + mm)
            if m:
                rows.append({"symbol": sym, "dir": direction, "fate": s["fate"], "ready": s["first_ready"],
                             "strike": strike, "kind": kind, **m})
    folder = root / "data" / "missed_opportunities" / day
    (folder / "option_returns.json").write_text(json.dumps(rows), encoding="utf-8")
    (folder / "option_returns.md").write_text(render(day, rows), encoding="utf-8")
    return folder


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", default=date.today().isoformat())
    args = ap.parse_args()
    folder = run(args.day)
    print(f"{args.day}: {'no signals file' if folder is None else folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
