"""Top-10 gainers / losers of every day: what came before, how the day unfolded, how the options moved, what happened after. READ-ONLY research - touches no scanner, signal or trade.

    python top_movers_study.py equity      5-minute stock candles -> one table of every stock-day, features, and each day's top 10 gainers / losers  (stage 1)
    python top_movers_study.py options     ATM option candles for every stock-day (what an option bought at 09:20 .. 11:00 could do)             (stage 2)
    python top_movers_study.py report      statistics + charts -> index.html                                                                      (stage 3)

Inputs (already on disk): data/backtest5y/equity5m (5-minute candles, 210 F&O stocks, Jul 2021 - Aug 2026) and the expired-option candle store (options_history.py, rolling near-month
options at ATM and +-3 strikes, to 6 Oct 2026). Output goes to E:\\APlusData\\top_movers_study (C: is nearly full); override with APLUS_TOPMOVERS_OUT.

A day's "top 10 gainers / losers" = the 10 stocks with the largest close-vs-previous-close change among that day's valid stocks. Days with a corporate-action look (|change| > 25% or
|gap| > 20%) are excluded so splits and bonuses do not pose as 100% losers.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
EQ_DIR = ROOT / "data" / "backtest5y" / "equity5m"
OUT = Path(os.getenv("APLUS_TOPMOVERS_OUT", r"E:\APlusData\top_movers_study"))
IST = "Asia/Kolkata"
NB = 75                                   # 5-minute bars 09:15 .. 15:25
FIELDS = ("open", "high", "low", "close", "volume")
CHECKPOINTS = {"0930": 2, "1000": 8, "1100": 20, "1200": 32, "1300": 44, "1400": 56, "1430": 62}      # bar whose close is the clock time (bar i starts 09:15 + 5i minutes)
TOP_N = 10


def _read_equity(sym: str) -> tuple[str, np.ndarray, np.ndarray, np.ndarray] | None:
    frames = []
    for f in sorted((EQ_DIR / sym).glob("*.json.gz")):
        try:
            with gzip.open(f, "rt", encoding="utf-8") as h:
                o = json.load(h)
        except (OSError, ValueError):
            continue
        if o.get("timestamp"):
            frames.append(pd.DataFrame({k: o[k] for k in ("timestamp",) + FIELDS}))
    if not frames:
        return None
    df = pd.concat(frames).drop_duplicates("timestamp").sort_values("timestamp")
    ts = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(IST)
    day = (ts.dt.year * 10000 + ts.dt.month * 100 + ts.dt.day).to_numpy()
    bar = ((ts.dt.hour * 60 + ts.dt.minute - 555) // 5).to_numpy()
    ok = (bar >= 0) & (bar < NB)
    return sym, day[ok], bar[ok], df[list(FIELDS)].to_numpy(dtype="float32")[ok]


def build_cube(workers: int = 6) -> tuple[list[str], np.ndarray, np.ndarray]:
    """(symbols, day ints YYYYMMDD, cube[symbol, day, bar, field]) over the days at least 100 stocks traded."""
    from joblib import Parallel, delayed

    syms = sorted(p.name for p in EQ_DIR.iterdir() if p.is_dir())
    got = [g for g in Parallel(n_jobs=workers)(delayed(_read_equity)(s) for s in syms) if g]
    counts: dict[int, int] = {}
    for _, d, _, _ in got:
        for x in np.unique(d):
            counts[int(x)] = counts.get(int(x), 0) + 1
    days = np.array(sorted(d for d, n in counts.items() if n >= 100), dtype=np.int64)
    index = {int(d): i for i, d in enumerate(days)}
    cube = np.full((len(got), len(days), NB, 5), np.nan, dtype="float32")
    for si, (_, d, b, v) in enumerate(got):
        di = np.fromiter((index.get(int(x), -1) for x in d), dtype=np.int64, count=len(d))
        keep = di >= 0
        cube[si, di[keep], b[keep], :] = v[keep]
    return [g[0] for g in got], days, cube


def _first_valid(a: np.ndarray) -> np.ndarray:
    """First non-NaN value along the last axis (NaN when the whole row is NaN)."""
    ok = ~np.isnan(a)
    idx = ok.argmax(axis=-1)
    val = np.take_along_axis(a, idx[..., None], axis=-1)[..., 0]
    return np.where(ok.any(axis=-1), val, np.nan)


def _last_valid(a: np.ndarray) -> np.ndarray:
    return _first_valid(a[..., ::-1])


def daily_table(syms: list[str], days: np.ndarray, cube: np.ndarray) -> pd.DataFrame:
    """One row per stock-day with prices, volume, time-of-day checkpoints and extremes' timing (all from the 5-minute candles)."""
    o, h, l, c, v = (cube[..., i] for i in range(5))
    nbars = (~np.isnan(c)).sum(axis=-1)
    with np.errstate(all="ignore"):
        day_o, day_c = _first_valid(o), _last_valid(c)
        day_h, day_l = np.nanmax(h, axis=-1), np.nanmin(l, axis=-1)
        vol = np.nansum(v, axis=-1)
        hi_bar = np.where(nbars > 0, np.nan_to_num(h, nan=-np.inf).argmax(axis=-1), -1)
        lo_bar = np.where(nbars > 0, np.nan_to_num(l, nan=np.inf).argmin(axis=-1), -1)
    sidx, didx = np.meshgrid(np.arange(len(syms)), np.arange(len(days)), indexing="ij")
    df = pd.DataFrame({"sym": np.array(syms)[sidx.ravel()], "day_i": didx.ravel(), "day": days[didx.ravel()], "open": day_o.ravel(), "high": day_h.ravel(), "low": day_l.ravel(),
                       "close": day_c.ravel(), "volume": vol.ravel(), "nbars": nbars.ravel(), "hi_bar": hi_bar.ravel(), "lo_bar": lo_bar.ravel()})
    for name, b in CHECKPOINTS.items():
        df[f"px{name}"] = c[..., b].ravel()
    df["f15_high"] = np.nanmax(h[..., :3], axis=-1).ravel()
    df["f15_low"] = np.nanmin(l[..., :3], axis=-1).ravel()
    df = df[df.nbars >= 70].copy()
    df["date"] = pd.to_datetime(df.day.astype(str), format="%Y%m%d")
    df = df.sort_values(["sym", "date"]).reset_index(drop=True)
    g = df.groupby("sym")
    df["prev_close"] = g.close.shift(1)
    df["gap_days"] = (df.date - g.date.shift(1)).dt.days
    df.loc[df.gap_days > 6, "prev_close"] = np.nan                    # a hole in the data: no honest previous close
    return df


def _streak(chg: pd.Series) -> pd.Series:
    sign = np.sign(chg.shift(1))
    run = (sign != sign.shift()).cumsum()
    return sign * (sign.groupby(run).cumcount() + 1)


def add_returns_and_features(df: pd.DataFrame) -> pd.DataFrame:
    """Day change, gap, how the day unfolded, and what the chart looked like BEFORE the day (only data up to the previous close)."""
    p = df.prev_close
    df["chg"] = (df.close / p - 1) * 100
    df["gap"] = (df.open / p - 1) * 100
    df["from_open"] = (df.close / df.open - 1) * 100
    df["rng"] = (df.high - df.low) / p * 100
    for name in CHECKPOINTS:
        df[f"r{name}"] = (df[f"px{name}"] / p - 1) * 100            # return vs previous close at that clock time
    df["hi_min"], df["lo_min"] = df.hi_bar * 5, df.lo_bar * 5         # minutes after 09:15 when the day's high / low were made
    df["valid"] = p.notna() & (df.chg.abs() <= 25) & (df.gap.abs() <= 20)

    g = df.groupby("sym")
    cl = g.close
    for n in (1, 3, 5, 10, 20):
        df[f"pre_ret{n}"] = (cl.shift(1) / cl.shift(1 + n) - 1) * 100       # return over the n days BEFORE today
    df["pre_chg1"] = df.groupby("sym").chg.shift(1)
    df["pre_chg2"] = df.groupby("sym").chg.shift(2)
    prev_rng = g.rng.shift(1)
    df["pre_rng1"] = prev_rng
    df["pre_atr10"] = g.rng.transform(lambda s: s.shift(1).rolling(10, min_periods=7).mean())
    df["pre_atr20"] = g.rng.transform(lambda s: s.shift(1).rolling(20, min_periods=15).mean())
    df["pre_rng_ratio"] = df.pre_rng1 / df.pre_atr10                           # < 0.7: yesterday was a quiet, compressed day
    df["pre_nr7"] = g.rng.transform(lambda s: (s.shift(1) <= s.shift(1).rolling(7, min_periods=7).min()).astype(float))
    df["pre_close_pos"] = ((g.close.shift(1) - g.low.shift(1)) / (g.high.shift(1) - g.low.shift(1)).replace(0, np.nan)) * 100      # where yesterday closed inside its range
    vol = df.volume.astype("float64")
    df["pre_vol_ratio"] = g.volume.shift(1) / g.volume.transform(lambda s: s.shift(2).rolling(20, min_periods=15).mean())
    df["pre_hi20"] = g.high.transform(lambda s: s.shift(1).rolling(20, min_periods=15).max())
    df["pre_lo20"] = g.low.transform(lambda s: s.shift(1).rolling(20, min_periods=15).min())
    df["pre_hi250"] = g.high.transform(lambda s: s.shift(1).rolling(250, min_periods=120).max())
    df["pre_lo250"] = g.low.transform(lambda s: s.shift(1).rolling(250, min_periods=120).min())
    pc = g.close.shift(1)
    df["pre_from_hi20"] = (pc / df.pre_hi20 - 1) * 100            # 0 = closed on the 20-day high
    df["pre_from_lo20"] = (pc / df.pre_lo20 - 1) * 100
    df["pre_from_hi250"] = (pc / df.pre_hi250 - 1) * 100
    df["pre_from_lo250"] = (pc / df.pre_lo250 - 1) * 100
    df["pre_dma20"] = (pc / g.close.transform(lambda s: s.shift(1).rolling(20, min_periods=15).mean()) - 1) * 100
    df["pre_dma50"] = (pc / g.close.transform(lambda s: s.shift(1).rolling(50, min_periods=40).mean()) - 1) * 100
    df["pre_streak"] = g.chg.transform(_streak)                               # + days up in a row, - days down in a row, ending yesterday
    df["move_x_atr"] = df.chg.abs() / df.pre_atr20                             # how big the move was in units of the stock's own normal range

    # after: next days, measured from this day's close
    nxt = g.close.shift(-1)
    df["nx_gap"] = (g.open.shift(-1) / df.close - 1) * 100
    df["nx_chg"] = (nxt / df.close - 1) * 100
    df["nx_chg3"] = (g.close.shift(-3) / df.close - 1) * 100
    df["nx_chg5"] = (g.close.shift(-5) / df.close - 1) * 100
    return df


def rank_days(df: pd.DataFrame) -> pd.DataFrame:
    """Each day's cross-sectional ranks (valid stocks only) and the market's own move that day."""
    ok = df[df.valid]
    d = ok.groupby("day")
    df["mkt_chg"] = df.day.map(d.chg.median())
    df["n_day"] = df.day.map(d.size())
    df["rank_up"] = np.nan
    df["rank_dn"] = np.nan
    df.loc[ok.index, "rank_up"] = d.chg.rank(ascending=False, method="first")
    df.loc[ok.index, "rank_dn"] = d.chg.rank(ascending=True, method="first")
    df["top_gainer"] = df.rank_up <= TOP_N
    df["top_loser"] = df.rank_dn <= TOP_N
    # the same ranking as seen live at 10:00 and 11:00 (what the scanner could actually see)
    for name in ("0930", "1000", "1100"):
        col = f"r{name}"
        s = df[df.valid].groupby("day")[col]
        df[f"up_rank_{name}"] = np.nan
        df[f"dn_rank_{name}"] = np.nan
        df.loc[ok.index, f"up_rank_{name}"] = s.rank(ascending=False, method="first")
        df.loc[ok.index, f"dn_rank_{name}"] = s.rank(ascending=True, method="first")
    df["pre_top_gainer"] = df.groupby("sym").top_gainer.shift(1)
    df["pre_top_loser"] = df.groupby("sym").top_loser.shift(1)
    return df


def sector_map() -> dict[str, str]:
    out: dict[str, str] = {}
    base = ROOT / "data" / "chart_history"
    for d in sorted((p for p in base.iterdir() if p.is_dir()), reverse=True)[:5]:
        f = d / "market_watch_1m.csv"
        if f.exists():
            t = pd.read_csv(f, usecols=["symbol", "sector"], encoding="utf-8-sig").drop_duplicates("symbol")
            out.update(dict(zip(t.symbol, t.sector)))
            if len(out) > 150:
                break
    return out


def stage_equity() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    syms, days, cube = build_cube()
    print(f"cube {cube.shape} stocks x days x bars x fields, {len(days)} trading days {days[0]}..{days[-1]} ({time.time() - t0:.0f}s)")
    np.save(OUT / "cube.npy", cube)
    pd.Series(syms).to_csv(OUT / "cube_symbols.csv", index=False, header=False)
    np.save(OUT / "cube_days.npy", days)
    df = rank_days(add_returns_and_features(daily_table(syms, days, cube)))
    df["sector"] = df.sym.map(sector_map())
    df.to_pickle(OUT / "stock_days.pkl")
    top = df[df.top_gainer | df.top_loser].copy()
    top["list"] = np.where(top.top_gainer, "GAINER", "LOSER")
    top["rank"] = np.where(top.top_gainer, top.rank_up, top.rank_dn)
    cols = ["day", "list", "rank", "sym", "sector", "chg", "gap", "r0930", "r1000", "r1100", "close", "from_open", "hi_min", "lo_min", "rng", "pre_ret5", "pre_chg1", "pre_rng_ratio",
            "pre_vol_ratio", "pre_from_hi20", "pre_from_lo20", "nx_gap", "nx_chg", "nx_chg3", "mkt_chg"]
    top.sort_values(["day", "list", "rank"])[cols].round(2).to_csv(OUT / "daily_top10.csv", index=False)
    print(f"stock-days {len(df):,} valid {int(df.valid.sum()):,}; top-10 rows {len(top):,}; wrote {OUT} ({time.time() - t0:.0f}s)")


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# stage 2: options
ENTRIES = {"0920": 1, "0930": 3, "1000": 9, "1030": 15, "1100": 21}        # entry = open of the 5-minute bar that starts at that clock time
OFFSETS = (-3, -2, -1, 0, 1, 2, 3)
STRIKE_TYPES = ("ATM", "ITM1", "OTM1")
MIN_PREMIUM = 2.0                                                          # the scanner's own floor
SCENARIOS = {"A": (0.20, 0.20), "B": (0.40, 0.25)}                         # (target gain, stop loss) as fractions; a bar that touches both counts as the stop (pessimistic)


def monthly_expiry(day: pd.Timestamp) -> pd.Timestamp:
    """Near-month stock-option expiry: last Thursday of the month until Aug 2025, last Tuesday from Sep 2025 (NSE's change). Holiday shifts are not modelled."""
    def last(y: int, m: int) -> pd.Timestamp:
        wd = 3 if (y, m) < (2025, 9) else 1
        end = pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)
        return end - pd.Timedelta(days=(end.weekday() - wd) % 7)
    e = last(day.year, day.month)
    if day <= e:
        return e
    nm = day + pd.offsets.MonthBegin(1)
    return last(nm.year, nm.month)


def _series_arrays(symbol: str, side: str, days: np.ndarray) -> dict[str, np.ndarray] | None:
    """arrays[field][offset_index, day_index, bar] for the 7 rolling series of one side; NaN where a bar has no print."""
    import options_history as oh

    didx = {int(d): i for i, d in enumerate(days)}
    out = {k: np.full((len(OFFSETS), len(days), NB), np.nan, dtype="float32") for k in ("open", "high", "low", "close", "iv", "oi", "strike", "spot")}
    any_data = False
    for oi_, off in enumerate(OFFSETS):
        df = oh.load_series(symbol, side, offset=off)
        if df.empty:
            continue
        idx = df.index
        day = (idx.year * 10000 + idx.month * 100 + idx.day).to_numpy()
        bar = ((idx.hour * 60 + idx.minute - 555) // 5).to_numpy()
        di = np.fromiter((didx.get(int(x), -1) for x in day), dtype=np.int64, count=len(day))
        keep = (di >= 0) & (bar >= 0) & (bar < NB)
        if not keep.any():
            continue
        any_data = True
        for k in out:
            out[k][oi_, di[keep], bar[keep]] = df[k].to_numpy(dtype="float32")[keep]
    return out if any_data else None


def _follow(a: dict[str, np.ndarray], field: str, mask: np.ndarray, e: int) -> np.ndarray:
    """(day, bar) values of the fixed strike: at most one rolling series shows a given strike at a bar, so a nan-max over the offsets picks it."""
    import warnings

    x = np.where(mask, a[field][:, :, e:], np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return np.nanmax(x, axis=0)


def _entry_rows(symbol: str, side: str, days: np.ndarray, a: dict[str, np.ndarray]) -> list[pd.DataFrame]:
    """For every day x entry time x strike type: buy the contract that is ATM / one strike in / out of the money at entry, then follow THAT strike (the rolling series changes strike as the
    stock moves, so the fixed strike is picked bar by bar from whichever series currently shows it)."""
    rows = []
    zero = OFFSETS.index(0)
    itm = OFFSETS.index(-1 if side == "CALL" else 1)
    otm = OFFSETS.index(1 if side == "CALL" else -1)
    pick = {"ATM": zero, "ITM1": itm, "OTM1": otm}
    D = len(days)
    for et, e in ENTRIES.items():
        for st, oi_ in pick.items():
            K = a["strike"][oi_, :, e]                                    # the strike bought, per day
            px = a["open"][oi_, :, e]
            ok = np.isfinite(K) & np.isfinite(px) & (px >= MIN_PREMIUM)
            if not ok.any():
                continue
            mask = a["strike"][:, :, e:] == K[None, :, None]               # (offset, day, bar): which series holds that strike at each later bar
            H, L, C = (_follow(a, f, mask, e) for f in ("high", "low", "close"))
            IV, OI = _follow(a, "iv", mask, e), _follow(a, "oi", mask, e)
            with np.errstate(all="ignore"):
                maxg = np.nanmax(H, axis=1) / px - 1
                ming = np.nanmin(L, axis=1) / px - 1
                lastc = _last_valid(C)
                closeg = lastc / px - 1
                tmax = np.where(np.isfinite(H).any(axis=1), np.nan_to_num(H, nan=-np.inf).argmax(axis=1) * 5, np.nan)
                res = {}
                for name, (tgt, stp) in SCENARIOS.items():
                    hit_t = np.nan_to_num(H, nan=-np.inf) >= px[:, None] * (1 + tgt)
                    hit_s = np.nan_to_num(L, nan=np.inf) <= px[:, None] * (1 - stp)
                    ft = np.where(hit_t.any(axis=1), hit_t.argmax(axis=1), 10_000)
                    fs = np.where(hit_s.any(axis=1), hit_s.argmax(axis=1), 10_000)
                    res[name] = np.where(ft < fs, 1, np.where(fs <= ft, np.where(fs == 10_000, 0, -1), 0)).astype("int8")      # +1 target first, -1 stop first (or same bar), 0 neither
                iv_e = a["iv"][oi_, :, e]
                iv_c = _last_valid(IV)
                oi_e = a["oi"][oi_, :, e]
                oi_c = _last_valid(OI)
            f = pd.DataFrame({"day": days, "px_e": px, "strike": K, "spot_e": a["spot"][oi_, :, e], "max_g": maxg * 100, "close_g": closeg * 100, "min_g": ming * 100, "tmax": tmax,
                              "wA": res["A"], "wB": res["B"], "iv_e": iv_e, "iv_c": iv_c, "oi_e": oi_e, "oi_c": oi_c})[ok]
            f.insert(0, "sym", symbol)
            f.insert(1, "side", "CE" if side == "CALL" else "PE")
            f.insert(2, "st", st)
            f.insert(3, "et", et)
            rows.append(f)
    return rows


def _options_for_symbol(symbol: str, days: np.ndarray) -> pd.DataFrame | None:
    frames: list[pd.DataFrame] = []
    for side in ("CALL", "PUT"):
        a = _series_arrays(symbol, side, days)
        if a is not None:
            frames.extend(_entry_rows(symbol, side, days, a))
    return pd.concat(frames, ignore_index=True) if frames else None


def stage_options(workers: int = 6) -> None:
    from joblib import Parallel, delayed

    t0 = time.time()
    days = np.load(OUT / "cube_days.npy")
    syms = pd.read_csv(OUT / "cube_symbols.csv", header=None)[0].tolist()
    parts = Parallel(n_jobs=workers, verbose=5)(delayed(_options_for_symbol)(s, days) for s in syms)
    df = pd.concat([p for p in parts if p is not None], ignore_index=True)
    for c in df.select_dtypes("float64").columns:
        df[c] = df[c].astype("float32")
    d = pd.to_datetime(df.day.astype(str), format="%Y%m%d")
    uniq = {x: monthly_expiry(x) for x in d.unique()}
    df["dte"] = (d.map(uniq) - d).dt.days.astype("int16")
    df.to_pickle(OUT / "option_days.pkl")
    print(f"option rows {len(df):,} for {df.sym.nunique()} stocks; wrote option_days.pkl ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    if stage == "equity":
        stage_equity()
    elif stage == "options":
        stage_options()
    else:
        print(__doc__)
