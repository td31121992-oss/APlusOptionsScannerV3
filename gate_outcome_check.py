"""What did the stocks the A+ gate REJECTED do afterwards? (RESEARCH ONLY - reads recorded data, changes nothing).  .venv\\Scripts\\python gate_outcome_check.py

Every scanner cycle records each analysed candidate with its verdict (data/signal_snapshots/<day>.csv: PASSED_ALL_GATES, or the reason it was held: A_PLUS_WAIT_LATE_VWAP_EXTENSION, PIVOT_TO_R1, ...).
For each (stock, side, verdict) the FIRST snapshot in every 30-minute block is kept (so one long episode does not count 20 times) and the stock's own tick path from the recorded ticks
(data/ticks/<day>/<SYMBOL>.csv.gz, last price per minute; a file cut short is read as far as it goes) gives what happened next, in the trade's direction:
   fwd30 / fwd60 / close  directional stock return from the snapshot price after 30 / 60 minutes and at 15:10
   mfe60 / mae60          best / worst directional excursion inside the next 60 minutes
   win   +1.0% before -0.7% (an option with delta ~0.5 and ~16 option-% per stock-% hits roughly +16% / -11%: a plain stop-and-target race, no ladder)
Hurdle: an option buyer needs about 0.25% of stock move just to pay the costs, so the 'after cost' column is fwd60 - 0.25.
Output: E:\\APlusData\\top_movers_study\\gate_outcome_check.txt  (+ gate_outcome_rows.csv)
"""

from __future__ import annotations

import glob
import gzip
import io
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = Path(r"E:\APlusData\top_movers_study")
HURDLE = 0.25
UP, DN = 1.0, 0.7
lines: list[str] = []


def say(s: str = "") -> None:
    print(s)
    lines.append(s)


def minute_path(day: str, sym: str) -> pd.Series | None:
    f = ROOT / "data" / "ticks" / day / f"{sym}.csv.gz"
    if not f.exists():
        return None
    raw = bytearray()
    try:
        with gzip.open(f, "rb") as h:
            while True:
                c = h.read(4096)
                if not c:
                    break
                raw += c
    except Exception:                                    # noqa: BLE001 - a file cut short is read as far as it goes
        pass
    if not raw:
        return None
    try:
        d = pd.read_csv(io.StringIO(raw.decode("utf-8", "ignore")), on_bad_lines="skip", engine="python", usecols=["ts", "ltp"])
    except Exception:                                    # noqa: BLE001
        return None
    d["ltp"] = pd.to_numeric(d.ltp, errors="coerce")
    d = d[d.ltp > 0]
    hms = d.ts.astype(str).str[:8]
    d = d[hms.str.match(r"^\d\d:\d\d:\d\d$")]
    if d.empty:
        return None
    m = d.ts.astype(str).str[:2].astype(int) * 60 + d.ts.astype(str).str[3:5].astype(int)
    s = d.groupby(m.values).ltp.last()
    return s.reindex(range(9 * 60 + 15, 15 * 60 + 31)).ffill()


def outcome(path: pd.Series, minute: int, sign: int) -> dict | None:
    if minute not in path.index or np.isnan(path.get(minute, np.nan)):
        return None
    p0 = float(path[minute])
    fut = path[(path.index > minute) & (path.index <= 15 * 60 + 10)].dropna()
    if len(fut) < 15:
        return None
    ret = sign * (fut / p0 - 1) * 100
    w60 = ret[ret.index <= minute + 60]

    def at(k: int) -> float:
        s = ret[ret.index <= minute + k]
        return float(s.iloc[-1]) if len(s) else np.nan
    win = None
    for v in w60:
        if v >= UP:
            win = 1
            break
        if v <= -DN:
            win = 0
            break
    return {"fwd30": at(30), "fwd60": at(60), "close": float(ret.iloc[-1]), "mfe60": float(w60.max()), "mae60": float(w60.min()), "win": win}


def market_series(day: str) -> pd.DataFrame | None:
    """Per minute: median move of all stocks since 09:20 and the share above their 09:20 price."""
    cols = {}
    for f in sorted((ROOT / "data" / "ticks" / day).glob("*.csv.gz")):
        p = minute_path(day, f.name[:-7])
        if p is not None and not np.isnan(p.get(9 * 60 + 20, np.nan)):
            cols[f.name[:-7]] = p
    if len(cols) < 50:
        return None
    m = pd.DataFrame(cols)
    base = m.loc[9 * 60 + 20]
    mv = (m / base - 1) * 100
    return pd.DataFrame({"mkt_move": mv.median(axis=1), "breadth_up": (mv > 0).mean(axis=1) * 100})


def main() -> None:
    rows = []
    for f in sorted(glob.glob(str(ROOT / "data" / "signal_snapshots" / "2026-*.csv"))):
        day = Path(f).stem
        s = pd.read_csv(f, low_memory=False)
        s["t"] = pd.to_datetime(s.time.astype(str).str[:19], errors="coerce")
        s = s.dropna(subset=["t"])
        s["minute"] = s.t.dt.hour * 60 + s.t.dt.minute
        s = s[(s.minute >= 9 * 60 + 25) & (s.minute <= 14 * 60 + 30)]
        s["block"] = s.minute // 30
        s = s.sort_values("t").drop_duplicates(["symbol", "direction", "status", "block"])
        paths: dict[str, pd.Series | None] = {}
        mk = market_series(day)
        for r in s.itertuples():
            if r.symbol not in paths:
                paths[r.symbol] = minute_path(day, r.symbol)
            p = paths[r.symbol]
            if p is None:
                continue
            o = outcome(p, int(r.minute), 1 if str(r.direction).upper() == "BULLISH" else -1)
            if o:
                mm = mk.loc[int(r.minute)] if mk is not None and int(r.minute) in mk.index else None
                mkt = float(mm.mkt_move) if mm is not None else np.nan
                sign = 1 if str(r.direction).upper() == "BULLISH" else -1
                rows.append({"mkt_move": mkt, "breadth_up": float(mm.breadth_up) if mm is not None else np.nan, "with_mkt": ("flat" if abs(mkt) < 0.10 else "with" if sign * mkt > 0 else "against") if mm is not None and not np.isnan(mkt) else "",
                             **{"day": day, "symbol": r.symbol, "direction": r.direction, "status": r.status, "minute": r.minute, "setup": r.setup_family, "vwap_dist": r.vwap_dist_pct,
                             "recent10": r.recent_10m_pct, "chase": r.chase_risk, "pivot": r.pivot_state, **o}})
    d = pd.DataFrame(rows)
    ledger = OUT / "gate_outcome_rows.csv"
    if ledger.exists():
        old = pd.read_csv(ledger)
        old = old[~old.day.isin(d.day.unique())] if not d.empty else old                 # days recomputed now replace their old rows; days whose ticks are gone are kept
        d = pd.concat([old, d], ignore_index=True)
    d.to_csv(ledger, index=False)
    d["status"] = d.status.str.replace("A_PLUS_WAIT_", "WAIT_")
    say(f"# What happened after each gate verdict  ({len(d)} signal episodes, {d.day.nunique()} days {d.day.min()}..{d.day.max()}, {d.symbol.nunique()} stocks)")
    say("")
    say("Directional stock returns from the snapshot price. 'After cost' = fwd60 minus 0.25%. 'Win' = +1.0% before -0.7% within 60 minutes.")
    say("")
    say("| Verdict | Episodes | Avg fwd30 % | Avg fwd60 % | After cost % | Avg to 15:10 % | Win (+1.0 before -0.7) | Avg best 60m % | Avg worst 60m % |")
    say("|---|---|---|---|---|---|---|---|---|")
    g = d.groupby("status")
    for k, x in sorted(g, key=lambda kv: -kv[1].fwd60.mean()):
        w = x.win.dropna()
        say(f"| {k} | {len(x)} | {x.fwd30.mean():+.2f} | {x.fwd60.mean():+.2f} | {x.fwd60.mean() - HURDLE:+.2f} | {x.close.mean():+.2f} | {w.mean() * 100:.0f}% ({len(w)}) | {x.mfe60.mean():+.2f} | {x.mae60.mean():+.2f} |")
    say("")
    # per-day consistency of the interesting groups
    say("Consistency: average fwd60 % by day")
    say("")
    days = sorted(d.day.unique())
    say("| Verdict | " + " | ".join(x[5:] for x in days) + " |")
    say("|---|" + "---|" * len(days))
    for k, x in g:
        if len(x) < 25:
            continue
        cells = [f"{x[x.day == dd].fwd60.mean():+.2f} ({(x.day == dd).sum()})" if (x.day == dd).any() else "-" for dd in days]
        say(f"| {k} | " + " | ".join(cells) + " |")
    say("")
    # direction split for the main groups
    say("By direction (fwd60 %)")
    say("")
    say("| Verdict | Bullish | Bearish |")
    say("|---|---|---|")
    for k, x in g:
        if len(x) < 25:
            continue
        b, r = x[x.direction == "BULLISH"], x[x.direction == "BEARISH"]
        say(f"| {k} | {b.fwd60.mean():+.2f} ({len(b)}) | {r.fwd60.mean():+.2f} ({len(r)}) |")
    if "with_mkt" in d and (d.with_mkt.fillna("") != "").any():
        say("")
        say("Market direction at the signal (median stock move since 09:20; 'with' = the trade's side agrees with the market, 'against' = it fights it, flat = |move| under 0.10%). Average fwd60 %, episodes in brackets")
        say("")
        say("| Verdict | With market | Against market | Flat |")
        say("|---|---|---|---|")
        for k, x in g:
            if len(x) < 25:
                continue
            cells = []
            for w in ("with", "against", "flat"):
                y = x[x.with_mkt == w]
                cells.append(f"{y.fwd60.mean():+.2f} ({len(y)})" if len(y) else "-")
            say(f"| {k} | " + " | ".join(cells) + " |")
        say("")
        say("Market move at the signal against the result (all verdicts together, directional fwd60 %)")
        say("")
        say("| Market since 09:20 | Episodes | Bullish signals fwd60 % | Bearish signals fwd60 % |")
        say("|---|---|---|---|")
        bins = pd.cut(d.mkt_move, [-9, -0.5, -0.2, 0.2, 0.5, 9], labels=["below -0.5%", "-0.5 to -0.2%", "within 0.2%", "+0.2 to +0.5%", "above +0.5%"])
        for lab, x in d.groupby(bins, observed=True):
            b, r = x[x.direction == "BULLISH"], x[x.direction == "BEARISH"]
            say(f"| {lab} | {len(x)} | {b.fwd60.mean():+.2f} ({len(b)}) | {r.fwd60.mean():+.2f} ({len(r)}) |")
    (OUT / "gate_outcome_check.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
    try:                                  # nightly shadow report of the regime + sector gate for the latest tick day (see regime_sector_report.py); never affects the check above
        import regime_sector_report
        regime_sector_report.main(sorted(d.name for d in regime_sector_report.TICKS.iterdir() if d.is_dir() and d.name[:2] == "20")[-1:])
    except Exception as exc:              # noqa: BLE001
        print("regime_sector_report skipped:", exc)
