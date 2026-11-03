"""Tick replay of the exit ladder (RESEARCH ONLY - touches no trade). python ladder_tick_replay.py

For every paper trade whose option contract was recorded tick by tick (data/option_ticks, from 26 Oct) it replays the exit rules on the real price path and compares variants of the ladder's
FIRST step. Live rule (paper_trade_journal.user_ladder_floor): initial stop (the trade's own option_stop), then once the best price reaches +5% the stop moves to -15%, +10% -> +3%, +20% -> +13%,
+30% -> +22% (+2 more per further +5%). The best price updates first, then the stop is compared with the same tick, exactly as the journal does. A stop fills at the tick that crossed it.
Open trades are marked at their last tick; closed trades end at the replayed exit or, when the live trade exited for another reason (manual, session end), at its real exit price.
Costs: the trade's own recorded cost is added to every variant, so only the exit price changes.
"""

from __future__ import annotations

import glob
import gzip
import io
import json
from pathlib import Path

import pandas as pd

import paper_trade_journal as pj

ROOT = Path(__file__).resolve().parent
START_LOCK = {"live (+5% -> -15%)": -15.0, "+5% -> -10%": -10.0, "+5% -> -5%": -5.0, "+5% -> cost (0%)": 0.0}


def ladder_floor(entry: float, high: float, first: float) -> float:
    gain = round((high / entry - 1.0) * 100.0, 6)
    if gain >= 30.0:
        lock = 22.0 + 2.0 * int((gain - 30.0) // 5.0)
    elif gain >= 20.0:
        lock = 13.0
    elif gain >= 10.0:
        lock = 3.0
    elif gain >= 5.0:
        lock = first
    else:
        return 0.0
    return entry * (1.0 + lock / 100.0)


def load_trades() -> list[dict]:
    j = json.loads((ROOT / "data" / "intraday_movement" / "paper_trade_journal.json").read_text(encoding="utf-8")).get("trades", [])
    h = json.loads((ROOT / "data" / "reports" / "paper_trade_history.json").read_text(encoding="utf-8"))
    h = h.get("paper_trades", h)
    by = {t["paper_trade_id"]: t for t in h}
    by.update({t["paper_trade_id"]: t for t in j})
    return [t for t in by.values() if str(t.get("paper_trade_id", "")).startswith(("PT-20261026", "PT-20261027", "PT-20261028"))]


def ticks(t: dict) -> pd.DataFrame | None:
    day = str(t["entry_time"])[:10]
    fs = glob.glob(str(ROOT / "data" / "option_ticks" / day / f"{t.get('option_security_id')}_*.csv.gz"))
    if not fs:
        return None
    raw = bytearray()
    try:
        with gzip.open(fs[0], "rb") as f:
            while True:
                c = f.read(4096)
                if not c:
                    break
                raw += c
    except Exception:                                    # noqa: BLE001 - a file cut short is read as far as it goes
        pass
    if not raw:
        return None                                       # an empty or unreadable file (the recorder was cut off): the trade is left out
    try:
        df = pd.read_csv(io.StringIO(raw.decode("utf-8", "ignore")), on_bad_lines="skip", engine="python")
    except Exception:                                    # noqa: BLE001
        return None
    if "ltp" not in df or "ts" not in df:
        return None
    df["ltp"] = pd.to_numeric(df.ltp, errors="coerce")
    df = df[df.ltp > 0].copy()
    df["hms"] = df.ts.astype(str).str[:8]
    return df


def replay(t: dict, df: pd.DataFrame, first: float) -> tuple[float, str, bool]:
    entry = float(t["entry_price"])
    stop0 = float(t.get("option_stop") or 0) or entry * 0.8
    since = str(t["entry_time"])[11:19]
    end = "15:25:00"
    high = entry
    last = entry
    for hms, p in zip(df.hms, df.ltp):
        if hms <= since:
            continue
        if hms > end:
            break
        high = max(high, p)
        stop = max(stop0, ladder_floor(entry, high, first))
        last = p
        if p <= stop:
            return p, "stop", True
    return last, "open/end", False


def main() -> None:
    rows = []
    for t in load_trades():
        df = ticks(t)
        if df is None or not str(t.get("entry_price")):
            continue
        entry, qty = float(t["entry_price"]), float(t["quantity"])
        closed = str(t.get("status")).upper() == "CLOSED"
        cost = float(t.get("gross_pnl") or 0) - float(t.get("net_pnl") or 0) if closed else 0.0
        real_exit = float(t["exit_price"]) if closed else float(t.get("last_option_price") or entry)
        row = {"trade": t["paper_trade_id"][12:], "symbol": t["symbol"], "closed": closed, "entry": entry, "qty": qty, "real_exit": real_exit, "real_pnl": (real_exit - entry) * qty - cost}
        for name, first in START_LOCK.items():
            px, how, hit = replay(t, df, first)
            if not hit and closed:
                px = real_exit                           # the live trade left for another reason (session end, manual, other rule): keep its real exit
            row[name] = (px - entry) * qty - cost
        rows.append(row)
    d = pd.DataFrame(rows)
    print(f"{len(d)} trades replayed from recorded ticks (26-28 Oct)")
    tot = {"real (journal)": d.real_pnl.sum(), **{k: d[k].sum() for k in START_LOCK}}
    print({k: round(v) for k, v in tot.items()})
    return d


if __name__ == "__main__":
    main()
