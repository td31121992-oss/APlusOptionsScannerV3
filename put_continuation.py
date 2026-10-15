"""Put-side continuation shadow list (research only - never trades, never touches the scanner).

Candidate rule, from the 7-day strategy test on 15 Oct 2026: a stock that is down with the whole tape behind it keeps going.
A stock is on the list at the first 5-minute decision point between 10:00 and 12:30 where ALL of these hold:

    - its sector is among the 3 weakest sectors of the day so far (average move from open, sectors with 3+ stocks)
    - price is below the first-15-minute low (opening-range breakdown)
    - price is below the day's VWAP and EMA(9) is below EMA(20) on the 5-minute closes
    - the stock is down at least 1.0% from its open

For every signal it records what the ATM put did afterwards (best, worst and close of the option, whether -20% came before +15%),
and what the stock did over the next 60 minutes. Each night `run()` rebuilds the day from the saved 5-minute candles
(data/pattern_log/candles/<day>.json) and `write_summary()` rebuilds the cumulative report:

    data/shadow_rules/put_continuation/<day>.csv
    data/shadow_rules/put_continuation.md

Review bar (in the report): 30+ signals on 5+ days, mean option close positive and above 0 after removing the best day,
and at least 60% of days positive.
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
DECIDE_FROM, DECIDE_TO, STEP = 10 * 60, 12 * 60 + 30, 5
MIN_MOVE = -1.0
FWD_BARS = 12                               # 60 minutes of 5-minute bars
FIELDS = ["day", "symbol", "sector", "minute", "time", "price", "move_pct", "stock_fwd60_pct", "stock_mfe60_pct", "contract", "strike",
          "opt_entry", "opt_best_pct", "opt_worst_pct", "opt_close_pct", "stop_first"]


def _ema(values: list[float], span: int) -> float:
    a = 2.0 / (span + 1.0)
    e = values[0]
    for v in values[1:]:
        e = a * v + (1 - a) * e
    return e


def sector_map(root: Path = ROOT) -> dict[str, str]:
    try:
        rows = json.loads((root / "data" / "reports" / "fno_market_watch_latest.json").read_text(encoding="utf-8")).get("rows", [])
        return {r["symbol"]: str(r.get("sector") or "Other") for r in rows if r.get("symbol")}
    except (OSError, ValueError):
        return {}


def find_signals(symbols: dict[str, dict[str, Any]], sectors: dict[str, str]) -> list[dict[str, Any]]:
    """First qualifying decision point per stock for one day. `symbols` is the saved candles file's "symbols" mapping."""
    first: dict[str, dict[str, Any]] = {}
    for T in range(DECIDE_FROM, DECIDE_TO + 1, STEP):
        view: dict[str, tuple[list[int], dict[str, Any]]] = {}
        move: dict[str, float] = {}
        for s, d in symbols.items():
            idx = [i for i, m in enumerate(d.get("minute", [])) if m < T]
            if len(idx) < 8:
                continue
            view[s] = (idx, d)
            move[s] = (d["close"][idx[-1]] / d["open"][idx[0]] - 1.0) * 100.0
        by_sector: dict[str, list[float]] = defaultdict(list)
        for s, v in move.items():
            by_sector[sectors.get(s, "Other")].append(v)
        avg = {k: st.mean(v) for k, v in by_sector.items() if len(v) >= 3}
        weakest = set(sorted(avg, key=lambda k: avg[k])[:3])
        for s, (idx, d) in view.items():
            if s in first or move[s] > MIN_MOVE or sectors.get(s, "Other") not in weakest:
                continue
            lows = [d["low"][i] for i in idx]
            closes = [d["close"][i] for i in idx]
            vols = [max(float(d["volume"][i]), 1.0) for i in idx]
            px = closes[-1]
            if px >= min(lows[:3]):
                continue
            vwap = sum(((d["high"][i] + d["low"][i] + d["close"][i]) / 3.0) * v for i, v in zip(idx, vols)) / sum(vols)
            if px >= vwap or _ema(closes, 9) >= _ema(closes, 20):
                continue
            first[s] = {"symbol": s, "sector": sectors.get(s, "Other"), "minute": T, "price": round(px, 2), "move_pct": round(move[s], 2)}
    out = list(first.values())
    out.sort(key=lambda x: (x["minute"], x["symbol"]))
    return out


def stock_forward(d: dict[str, Any], minute: int) -> tuple[float | None, float | None]:
    """Next 60 minutes for a PUT: positive = the stock fell. (forward close move, best favourable move)."""
    fwd = [i for i, m in enumerate(d.get("minute", [])) if m >= minute]
    if len(fwd) < FWD_BARS + 1:
        return None, None
    f0 = d["close"][fwd[0]]
    seg = fwd[:FWD_BARS + 1]
    end = d["close"][seg[-1]]
    low = min(d["low"][i] for i in seg)
    return round(-(end / f0 - 1.0) * 100.0, 3), round(-(low / f0 - 1.0) * 100.0, 3)


def option_outcome(symbol: str, minute: int, price: float, day: str, fetch: Callable[..., Any] | None = None, master: Any = None) -> dict[str, Any]:
    """ATM put of the nearest expiry at the signal: entry = close of the signal candle +1%, then best / worst / close and stop-first."""
    try:
        import pandas as pd

        if master is None:
            master = pd.read_csv(ROOT / "data" / "cache" / "api-scrip-master-detailed.csv", low_memory=False,
                                 usecols=["SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL", "SM_EXPIRY_DATE", "STRIKE_PRICE", "OPTION_TYPE", "LOT_SIZE"])
        m = master[(master.UNDERLYING_SYMBOL == symbol) & (master.INSTRUMENT == "OPTSTK") & (master.OPTION_TYPE == "PE")].copy()
        m["exp"] = m.SM_EXPIRY_DATE.astype(str).str[:10]
        m = m[m.exp >= day]
        if m.empty:
            return {}
        m = m[m.exp == m.exp.min()].copy()
        m["d"] = (m.STRIKE_PRICE.astype(float) - price).abs()
        row = m.sort_values("d").iloc[0]
        bars = (fetch or _fetch_option_bars)(int(row.SECURITY_ID), day)
        at = [b for b in bars if b[0] <= minute]
        after = [b for b in bars if at and b[0] > at[-1][0]]
        if not at or len(after) < 3:
            return {}
        entry = at[-1][4] * 1.01
        if entry <= 0:
            return {}
        stop_first = False
        for b in after:
            if b[3] <= entry * 0.80:
                stop_first = True
                break
            if b[2] >= entry * 1.15:
                break
        return {"contract": f"{symbol} {int(float(row.STRIKE_PRICE)) if float(row.STRIKE_PRICE).is_integer() else row.STRIKE_PRICE} PE",
                "strike": float(row.STRIKE_PRICE), "opt_entry": round(entry, 2),
                "opt_best_pct": round((max(b[2] for b in after) / entry - 1.0) * 100.0, 1),
                "opt_worst_pct": round((min(b[3] for b in after) / entry - 1.0) * 100.0, 1),
                "opt_close_pct": round((after[-1][4] / entry - 1.0) * 100.0, 1), "stop_first": bool(stop_first)}
    except Exception:                                      # noqa: BLE001 - the option half is an extra; the stock half still records
        return {}


def _fetch_option_bars(security_id: int, day: str) -> list[tuple[int, float, float, float, float]]:
    import requests
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from dhan_auth import resolve_access_token

    cid = os.getenv("DHAN_CLIENT_ID", "").strip()
    tok = resolve_access_token(project_root=ROOT, client_id=cid, env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip())
    time.sleep(0.35)
    r = requests.post("https://api.dhan.co/v2/charts/intraday", timeout=30,
                      headers={"access-token": tok, "client-id": cid, "Accept": "application/json", "Content-Type": "application/json"},
                      json={"securityId": str(security_id), "exchangeSegment": "NSE_FNO", "instrument": "OPTSTK", "interval": "5", "oi": False,
                            "fromDate": f"{(date.fromisoformat(day) - timedelta(days=1)).isoformat()} 09:00:00", "toDate": f"{day} 15:30:00"})
    d = r.json() if r.status_code == 200 else {}
    out = []
    for t, o, h, l, c in zip(d.get("timestamp") or [], d.get("open") or [], d.get("high") or [], d.get("low") or [], d.get("close") or []):
        x = datetime.fromtimestamp(int(t), IST)
        if x.date().isoformat() == day:
            out.append((x.hour * 60 + x.minute, float(o), float(h), float(l), float(c)))
    return out


def run(day: str | None = None, root: Path = ROOT, with_options: bool = True) -> Path | None:
    day = day or date.today().isoformat()
    cf = root / "data" / "pattern_log" / "candles" / f"{day}.json"
    try:
        symbols = json.loads(cf.read_text(encoding="utf-8")).get("symbols", {})
    except (OSError, ValueError):
        return None
    sigs = find_signals(symbols, sector_map(root))
    rows = []
    for s in sigs:
        d = symbols[s["symbol"]]
        fwd, mfe = stock_forward(d, s["minute"])
        row = {"day": day, **s, "time": f"{s['minute'] // 60:02d}:{s['minute'] % 60:02d}", "stock_fwd60_pct": fwd if fwd is not None else "",
               "stock_mfe60_pct": mfe if mfe is not None else ""}
        if with_options:
            row.update(option_outcome(s["symbol"], s["minute"], s["price"], day))
        rows.append(row)
    folder = root / "data" / "shadow_rules" / "put_continuation"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.csv"
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    write_summary(root)
    return path


def _num(v: Any) -> float | None:
    try:
        return float(v) if v not in ("", None) else None
    except (TypeError, ValueError):
        return None


def load_rows(root: Path = ROOT) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in sorted(glob.glob(str(root / "data" / "shadow_rules" / "put_continuation" / "20*.csv"))):
        with open(p, encoding="utf-8", newline="") as h:
            rows.extend(csv.DictReader(h))
    return rows


def write_summary(root: Path = ROOT) -> Path | None:
    rows = load_rows(root)
    if not rows:
        return None
    days = sorted({r["day"] for r in rows})
    opt = [r for r in rows if _num(r.get("opt_close_pct")) is not None]
    stk = [r for r in rows if _num(r.get("stock_fwd60_pct")) is not None]
    out = ["# Put-side continuation shadow list", "",
           f"{len(rows)} signals on {len(days)} day(s) ({days[0]} to {days[-1]}). Rule: weakest-3 sector, below the 15-minute range low, below VWAP "
           "and EMA9 < EMA20, down 1%+ from open, first hit between 10:00 and 12:30. ATM put bought at the signal candle, held to close, "
           "hindsight, before costs.", ""]
    if stk:
        f = [_num(r["stock_fwd60_pct"]) for r in stk]
        out += [f"**Stock, next 60 minutes (positive = fell):** {len(stk)} signals, fell {100 * sum(1 for x in f if x > 0) / len(f):.0f}% of the time, "
                f"mean {st.mean(f):+.2f}%, median {st.median(f):+.2f}%.", ""]
    if opt:
        c = [_num(r["opt_close_pct"]) for r in opt]
        b = [_num(r["opt_best_pct"]) for r in opt]
        sf = sum(1 for r in opt if str(r.get("stop_first")).lower() in ("true", "1"))
        out += [f"**Option:** {len(opt)} signals priced; closed up {100 * sum(1 for x in c if x > 0) / len(c):.0f}%, reached +15% "
                f"{100 * sum(1 for x in b if x >= 15) / len(b):.0f}%, +30% {100 * sum(1 for x in b if x >= 30) / len(b):.0f}%, -20% came first "
                f"{100 * sf / len(opt):.0f}%, mean close {st.mean(c):+.1f}%.", ""]
    out += ["| Day | Signals | Priced | Closed up | Mean option close | Stock fell next 60m |", "|---|---|---|---|---|---|"]
    verdict_days = []
    for d in days:
        g = [r for r in rows if r["day"] == d]
        go = [r for r in g if _num(r.get("opt_close_pct")) is not None]
        gs = [_num(r["stock_fwd60_pct"]) for r in g if _num(r.get("stock_fwd60_pct")) is not None]
        mean = st.mean(_num(r["opt_close_pct"]) for r in go) if go else None
        if mean is not None:
            verdict_days.append((d, len(go), mean))
        out.append(f"| {d} | {len(g)} | {len(go)} | {(str(round(100 * sum(1 for r in go if _num(r['opt_close_pct']) > 0) / len(go))) + '%') if go else '-'} | "
                   f"{(f'{mean:+.1f}%' if mean is not None else '-')} | {(str(round(100 * sum(1 for x in gs if x > 0) / len(gs))) + '%') if gs else '-'} |")
    ok = False
    why = []
    if len(opt) < 30:
        why.append(f"{len(opt)} of 30 priced signals")
    if len(verdict_days) < 5:
        why.append(f"{len(verdict_days)} of 5 days")
    if verdict_days:
        pos = sum(1 for _, _, m in verdict_days if m > 0)
        if pos / len(verdict_days) < 0.6:
            why.append(f"only {pos} of {len(verdict_days)} days positive")
        best = max(verdict_days, key=lambda x: x[1] * x[2])[0]
        rest = [_num(r["opt_close_pct"]) for r in opt if r["day"] != best]
        if rest and st.mean(rest) <= 0:
            why.append(f"not positive after removing {best}")
    ok = not why and bool(opt)
    out += ["", f"**Verdict: {'supports adding it as a signal source' if ok else 'not yet'}.**" + ("" if ok else " Missing: " + "; ".join(why) + "."),
            "", "_Research only. Nothing here changes trading._", ""]
    folder = root / "data" / "shadow_rules"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "put_continuation.md"
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def main() -> int:
    import sys

    days = sys.argv[1:] or [date.today().isoformat()]
    for d in days:
        print(d, run(d))
    print(write_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
