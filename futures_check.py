"""Check the futures opening-range idea against the RECORDED futures quotes (data/futures/<day>.csv.gz, one row per contract per minute with bid / ask / last / spot). READ-ONLY research.

    python futures_check.py            prints the tables and writes E:\\APlusData\\top_movers_study\\orb_futures\\futures_check.json

What it measures (the backtest assumed 1-4 bp of slippage per side and used cash prices for futures):
  1. the real half-spread (what a market order pays beyond the mid) by stock liquidity and by time of day;
  2. how deep the top of the book is against one lot (can a lot be filled at the best price?);
  3. how closely the future tracks the cash price over 5 minutes (the proxy error in the backtest);
  4. what an entry at 09:20 / exit at 15:15 would have paid on the days recorded (a sanity check of the mechanics; two full days is NOT evidence about profitability).
Files cut short (a recorder killed by a full disk) are read as far as they go.
"""

from __future__ import annotations

import glob
import gzip
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

import futures_orb_backtest as fb

ROOT = Path(__file__).resolve().parent
OUT = fb.RES
SLOTS = ((9 * 60 + 15, 9 * 60 + 30, "09:15-09:30"), (9 * 60 + 30, 10 * 60 + 30, "09:30-10:30"), (10 * 60 + 30, 14 * 60 + 30, "10:30-14:30"), (14 * 60 + 30, 15 * 60 + 30, "14:30-15:30"))


def read_day(path: str) -> pd.DataFrame:
    """Read a (possibly truncated) gzip file; keep everything decoded before the damage."""
    raw = bytearray()
    try:
        with gzip.open(path, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                raw += chunk
    except (OSError, EOFError, Exception):               # noqa: BLE001 - BadGzipFile, EOFError, zlib.error: keep what was read
        pass
    df = pd.read_csv(io.StringIO(raw.decode("utf-8", errors="ignore")), on_bad_lines="skip", engine="python")
    df = df[pd.to_numeric(df.get("fut_ltp"), errors="coerce").notna()].copy()
    for c in ("dte", "lot", "fut_ltp", "spot", "basis_pct", "oi", "volume", "bid", "bid_qty", "ask", "ask_qty", "open", "high", "low", "prev_close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["t"] = pd.to_datetime(df.captured_at.astype(str).str[:19], errors="coerce")
    df = df[df.t.notna()]
    df["min"] = df.t.dt.hour * 60 + df.t.dt.minute
    df["day"] = df.t.dt.strftime("%Y-%m-%d")
    return df


def front(df: pd.DataFrame) -> pd.DataFrame:
    """The contract a trader would use: the current-month future while it has 2+ days left, otherwise the next one (the recorder's NEAR)."""
    s = df[(df.kind == "STK") & (df.contract == "NEAR")].copy()
    s["mid"] = (s.bid + s.ask) / 2.0
    s = s[(s.bid > 0) & (s.ask >= s.bid) & (s.mid > 0)]
    s["half_bp"] = (s.ask - s.bid) / 2.0 / s.mid * 1e4
    s["lot_value"] = s.lot * s.mid
    s["slot"] = ""
    for a, b, name in SLOTS:
        s.loc[(s["min"] >= a) & (s["min"] < b), "slot"] = name
    return s[s.slot != ""]


def main() -> dict:
    days = {}
    for f in sorted(glob.glob(str(ROOT / "data" / "futures" / "2026-*.csv.gz"))):
        d = read_day(f)
        if len(d):
            days[Path(f).name[:10]] = d
    report: dict = {"days": {k: {"rows": int(len(v)), "from": v.t.min().strftime("%H:%M"), "to": v.t.max().strftime("%H:%M")} for k, v in days.items()}}
    print("days read:", report["days"])
    full = {k: v for k, v in days.items() if v.t.max().hour * 60 + v.t.max().minute >= 15 * 60 + 25}
    print("complete days:", list(full))
    use = pd.concat([front(v) for v in full.values()])
    # liquidity tier = futures volume traded by mid-day (shares), in rupees
    noon = use[(use["min"] >= 12 * 60) & (use["min"] < 12 * 60 + 5)].groupby(["day", "symbol"]).agg(turn=("volume", "max"), price=("mid", "mean"))
    noon["value_cr"] = noon.turn * noon.price / 1e7
    tier = noon.groupby("symbol").value_cr.mean().rank(ascending=False)
    use["tier"] = use.symbol.map(lambda s: "top 30" if tier.get(s, 999) <= 30 else ("31-100" if tier.get(s, 999) <= 100 else "rest"))
    tbl = use.groupby(["tier", "slot"]).half_bp.agg(["median", lambda x: x.quantile(.75), lambda x: x.quantile(.9), "size"]).round(2)
    tbl.columns = ["median_bp", "p75_bp", "p90_bp", "rows"]
    print("\n1. HALF-SPREAD (bp of the price; a market order pays this beyond the mid) - front stock future, complete days only"); print(tbl.to_string())
    share = use.assign(le1=use.half_bp <= 1, le2=use.half_bp <= 2, le3=use.half_bp <= 3, le5=use.half_bp <= 5).groupby("tier")[["le1", "le2", "le3", "le5"]].mean().mul(100).round(0)
    print("\n   share of minute-quotes with half-spread <= 1 / 2 / 3 / 5 bp (%):"); print(share.to_string())
    report["spread_by_tier_slot"] = tbl.reset_index().to_dict("records")

    # 2. depth against one lot
    use["lot_fits_ask"] = use.ask_qty >= use.lot
    use["lot_fits_bid"] = use.bid_qty >= use.lot
    depth = use.groupby("tier")[["lot_fits_ask", "lot_fits_bid"]].mean().mul(100).round(0)
    lotval = use.groupby("tier").lot_value.median().div(1e5).round(1)
    print("\n2. DEPTH: share of quotes where the best ask / bid holds at least one full lot (%), and the median value of one lot (Rs lakh)")
    print(pd.concat([depth, lotval.rename("lot_value_lakh")], axis=1).to_string())
    report["depth"] = pd.concat([depth, lotval.rename("lot_value_lakh")], axis=1).reset_index().to_dict("records")

    # 3. tracking: future vs cash over 5 minutes
    track = []
    for k, v in full.items():
        s = v[(v.kind == "STK") & (v.contract == "NEAR") & (v.spot > 0) & (v.fut_ltp > 0)].sort_values(["symbol", "t"])
        s = s[(s["min"] >= 9 * 60 + 20) & (s["min"] <= 15 * 60 + 15)]
        s5 = s[s["min"] % 5 == 0].drop_duplicates(["symbol", "min"])
        s5["rf"] = s5.groupby("symbol").fut_ltp.pct_change()
        s5["rs"] = s5.groupby("symbol").spot.pct_change()
        track.append(((s5.rf - s5.rs) * 1e4).dropna())
    tr = pd.concat(track)
    print("\n3. TRACKING: 5-minute return of the future minus the cash stock (bp): mean %.2f, std %.2f, 90%% of the time within +-%.1f" % (tr.mean(), tr.std(), tr.abs().quantile(.9)))
    report["tracking_bp"] = {"mean": float(tr.mean()), "std": float(tr.std()), "abs_p90": float(tr.abs().quantile(.9))}
    # open-to-1515 move: future vs cash, per stock
    cmp = []
    for k, v in full.items():
        s = v[(v.kind == "STK") & (v.contract == "NEAR") & (v.spot > 0) & (v.fut_ltp > 0)]
        a = s[(s["min"] >= 9 * 60 + 20) & (s["min"] < 9 * 60 + 22)].groupby("symbol").agg(f0=("fut_ltp", "first"), s0=("spot", "first"))
        b = s[(s["min"] >= 15 * 60 + 14) & (s["min"] < 15 * 60 + 16)].groupby("symbol").agg(f1=("fut_ltp", "last"), s1=("spot", "last"))
        j = a.join(b, how="inner")
        cmp.append(((j.f1 / j.f0 - 1) - (j.s1 / j.s0 - 1)) * 1e4)
    cm = pd.concat(cmp)
    print("   09:20 -> 15:15 move, future minus cash (bp): mean %.2f, std %.2f, abs p90 %.1f" % (cm.mean(), cm.std(), cm.abs().quantile(.9)))
    report["day_move_gap_bp"] = {"mean": float(cm.mean()), "std": float(cm.std()), "abs_p90": float(cm.abs().quantile(.9))}

    # 4. break-even check against the backtest
    med_all = float(use.half_bp.median())
    top = use[use.tier == "top 30"].half_bp.median()
    print("\n4. WHAT THIS MEANS FOR THE BACKTEST: it assumed 1-4 bp per side; the recorded median half-spread is %.1f bp overall and %.1f bp for the 30 most active futures (one side pays it, a stop-out pays about double)." % (med_all, top))
    report["median_half_spread_bp"] = {"all": med_all, "top30": float(top)}
    (OUT / "futures_check.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report


if __name__ == "__main__":
    main()


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# the backtest again with the MEASURED spreads instead of a flat slippage
def measured_slippage() -> dict:
    """Half-spread by liquidity tier and slot from the recorded complete days: entry at 09:20 pays the 09:15-09:30 spread, a normal exit at 15:15 the 14:30-15:30 spread, a stop 2x the mid-day spread."""
    rep = json.loads((OUT / "futures_check.json").read_text(encoding="utf-8"))
    t = {(r["tier"], r["slot"]): r["median_bp"] for r in rep["spread_by_tier_slot"]}
    return {tier: {"in": t[(tier, "09:15-09:30")], "out": t[(tier, "14:30-15:30")], "stop": 2.0 * t[(tier, "10:30-14:30")]} for tier in ("top 30", "31-100", "rest")}


def evaluate_real(data, op, tr, cfg, cost_bp, in_bp, out_bp, stop_bp, extra=None):
    ok = data["valid"] if extra is None else (data["valid"] & extra)
    ok = ok & np.isfinite(op["rvol"]) & (op["dir"] != 0) & np.isfinite(tr["exit"]) & np.isfinite(op["entry"]) & (op["rvol"] >= cfg["rvol"])
    order = (-np.where(ok, op["rvol"], -np.inf)).argsort(axis=0).argsort(axis=0)
    sel = ok & (order < cfg["n"])
    d = op["dir"]
    e = op["entry"] * (1 + d * in_bp[:, None] / 1e4)
    xbp = np.where(tr["stopped"], stop_bp[:, None], out_bp[:, None])
    x = tr["exit"] * (1 - d * xbp / 1e4)
    net = (d * (x / e - 1)) * 100.0 - cost_bp / 100.0
    days = data["days"]
    per_day = pd.Series(np.where(sel, net, 0.0).sum(axis=0) / cfg["n"], index=days)
    h1 = days < fb.SPLIT
    st = fb.daily_stats(per_day[sel.any(axis=0)], days)
    return {"trades": int(sel.sum()), "net": float(net[sel].mean()), "h1": float(net[sel & h1[None, :]].mean()), "h2": float(net[sel & ~h1[None, :]].mean()), "t": st.get("t_stat", np.nan), "total": st.get("total_%", np.nan)}


def rerun_with_measured_spreads() -> pd.DataFrame:
    import warnings
    warnings.simplefilter("ignore")
    ms = measured_slippage()
    print("\n5. THE BACKTEST WITH THE MEASURED SPREADS (entry at 09:20 pays the opening spread; normal exit the closing spread; a stop 2x the mid-day spread)")
    print("   half-spread used (bp):", {k: v for k, v in ms.items()})
    cost = fb.futures_costs_bp()
    data = fb.load()
    # tier of every stock from the recorded days (turnover rank); stocks not in the recorded days fall into 'rest'
    tiers = {}
    for k, v in {Path(f).name[:10]: read_day(f) for f in sorted(glob.glob(str(ROOT / "data" / "futures" / "2026-10-2[36].csv.gz")))}.items():
        s = v[(v.kind == "STK") & (v.contract == "NEAR") & (v["min"] >= 12 * 60) & (v["min"] < 12 * 60 + 5) & (v.bid > 0)].groupby("symbol").agg(vol=("volume", "max"), px=("fut_ltp", "mean"))
        tiers[k] = (s.vol * s.px)
    turn = pd.concat(tiers.values(), axis=1).mean(axis=1).rank(ascending=False)
    name = lambda sym: "top 30" if turn.get(sym, 999) <= 30 else ("31-100" if turn.get(sym, 999) <= 100 else "rest")        # noqa: E731
    syms = data["syms"]
    in_bp = np.array([ms[name(s)]["in"] for s in syms]); out_bp = np.array([ms[name(s)]["out"] for s in syms]); stop_bp = np.array([ms[name(s)]["stop"] for s in syms])
    print("   stocks per tier:", pd.Series([name(s) for s in syms]).value_counts().to_dict())
    gap = (data["o"][:, :, 0] / data["prev"] - 1) * 100
    rows = []
    for m in (5, 15):
        op = fb.opening(data, m)
        for stop in (0.10, 0.25, None):
            tr = fb.run_trades(data, op, stop)
            for case, extra in (("rule as published", None), ("gap fade >= 1%", (op["dir"] * gap) <= -1.0), ("gap fade >= 2%", (op["dir"] * gap) <= -2.0)):
                for n in (10, 20):
                    r = evaluate_real(data, op, tr, {"n": n, "rvol": 1.0}, cost, in_bp, out_bp, stop_bp, extra)
                    rows.append({"or_min": m, "stop": "none" if stop is None else stop, "case": case, "top_n": n, **r})
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "measured_spread_grid.csv", index=False)
    for case in ("rule as published", "gap fade >= 1%", "gap fade >= 2%"):
        s = d[d.case == case]
        print(f"   {case}: {len(s)} settings | net>0: {(s.net > 0).sum()} | positive in both halves: {((s.h1 > 0) & (s.h2 > 0)).sum()} | median net {s.net.median():.3f}% | best net {s.net.max():.3f}% (t {s.loc[s.net.idxmax(), 't']:.2f})")
    print(d.sort_values("net", ascending=False).head(6).round(3).to_string(index=False))
    return d


if __name__ == "__main__" and False:
    pass
