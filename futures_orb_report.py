"""Report for the futures opening-range backtest: E:\\APlusData\\top_movers_study\\orb_futures\\index.html. READ-ONLY research.

    python futures_orb_report.py      (after futures_orb_backtest.py has written grid.csv)
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

import futures_orb_backtest as fb
import top_movers_report as tr_

RES = fb.RES
GREEN, RED, BLUE, AMBER, GREY = tr_.GREEN, tr_.RED, tr_.BLUE, tr_.AMBER, tr_.GREY
BEST = {"or": 5, "n": 10, "rvol": 1.0, "stop": 0.25, "gap": 1.0}        # the best-looking plateau cell, shown as an example, not as a recommendation


def curve(series: pd.Series) -> tuple[list[float], list[float]]:
    eq = ((1 + series / 100.0).cumprod() - 1) * 100
    xs = [pd.Timestamp(str(int(d))).year + (pd.Timestamp(str(int(d))).dayofyear - 1) / 366.0 for d in eq.index]
    return xs, eq.tolist()


def main() -> str:
    warnings.simplefilter("ignore")
    cost = fb.futures_costs_bp()
    data = fb.load()
    gap = (data["o"][:, :, 0] / data["prev"] - 1) * 100
    op5 = fb.opening(data, 5)
    tr10, tr25 = fb.run_trades(data, op5, 0.10), fb.run_trades(data, op5, 0.25)
    against = (op5["dir"] * gap) <= -BEST["gap"]
    series = {}
    for slip in (0.0, 1.0, 2.0, 4.0):
        series[f"main spec, {slip:g} bp"] = fb.evaluate(data, op5, tr10, {**fb.MAIN}, slip, cost)["series"]
    best = {}
    for slip in (1.0, 2.0, 4.0):
        r = fb.evaluate(data, op5, tr25, {"or": 5, "n": BEST["n"], "rvol": 1.0, "stop": 0.25}, slip, cost, against)
        best[slip] = r
        series[f"gap-fade example, {slip:g} bp"] = r["series"]

    grid = pd.read_csv(RES / "grid.csv")
    gg = pd.read_csv(RES / "gap_against_grid.csv")
    main_tbl = grid[(grid.or_min == 5) & (grid.top_n == 20) & (grid.rvol_min == 1.0) & (grid.stop_atr == "0.1")][["slip_bp", "trades", "win_%", "avg_gross_%", "avg_net_%", "avg_net_h1_%", "avg_net_h2_%", "stopped_%", "t_stat", "sharpe", "total_%", "max_dd_%"]]
    main_tbl.index = [f"{s:g} bp per side" for s in main_tbl.slip_bp]
    main_tbl = main_tbl.drop(columns="slip_bp")
    frac = {}
    for slip in (1.0, 2.0, 4.0):
        s = gg[gg.slip == slip]
        frac[f"{slip:g} bp"] = {"cells": len(s), "net > 0": int((s.net > 0).sum()), "positive in both halves": int(((s.h1 > 0) & (s.h2 > 0)).sum()), "t >= 2": int((s.t >= 2).sum()), "median net %": s.net.median(), "median t": s.t.median()}
    plateau = pd.DataFrame(frac).T
    top = gg[gg.slip == 2.0].sort_values("t", ascending=False).head(12).rename(columns={"or": "opening range min", "gap>=": "gap >= %", "topN": "top N", "net": "net %/trade", "gross": "gross %/trade", "h1": "2021-23 net", "h2": "2024-26 net", "total": "total % (5y, unlevered)", "dd": "max drawdown %"}).set_index("opening range min")

    xs_series = [(name, *curve(s), c) for (name, s), c in zip(series.items(), [GREY, "#c9d6ef", AMBER, RED, "#7be0b0", GREEN, "#2fa36b"])]
    chart_main = tr_.svg_lines([(n, x, y, c) for n, x, y, c in xs_series if n.startswith("main")], xticks=[(y, str(y)) for y in range(2022, 2027)], ylabel="%", zero=True)
    chart_gap = tr_.svg_lines([(n, x, y, c) for n, x, y, c in xs_series if n.startswith("gap")], xticks=[(y, str(y)) for y in range(2022, 2027)], ylabel="%", zero=True)
    fm = {"trades": "{:,.0f}", "win_%": "{:.1f}", "avg_gross_%": "{:.3f}", "avg_net_%": "{:.3f}", "avg_net_h1_%": "{:.3f}", "avg_net_h2_%": "{:.3f}", "stopped_%": "{:.0f}", "t_stat": "{:.2f}", "sharpe": "{:.2f}", "total_%": "{:.1f}", "max_dd_%": "{:.1f}"}
    be = best[2.0]
    html = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Futures opening-range backtest</title><meta name='viewport' content='width=device-width,initial-scale=1'><style>{tr_.CSS}</style></head><body><div class='wrap'>"]
    html.append("<h1>Stocks in play + opening-range breakout, tested as stock futures with real costs</h1><div class='sub'>210 F&amp;O stocks, Jul 2021 - Aug 2026, 5-minute candles of the cash stock as the futures price. Read-only research - no live rule changed.</div>")
    html.append(f"""<h2>Verdict</h2><div class='find'><ul>
<li><b>The rule as published (fixed in advance):</b> 5-minute opening range, top 20 stocks by opening volume, stop at 10% of the 14-day range, flat at 15:15. It has a real but thin edge: +0.072% of the position per trade before costs, and +0.041% after the {cost:.1f} bp of statutory costs and brokerage when slippage is zero (t = 5.1, positive in both halves). It only survives if slippage stays under <b>1.4 bp per side</b>; at 2 bp it loses (-0.016% per trade). A futures trade has no spread-on-premium problem like options, but the edge is smaller than a few basis points of friction - so on its own it is not yet profitable.</li>
<li><b>One pocket looks better than the rest: the gap fade.</b> Take only the stocks whose opening candle breaks <i>against</i> a 1%+ opening gap (gap up, first candle down: short; gap down, first candle up: long). The gross edge doubles (+0.15% per trade) and it stays positive after costs at 2 bp slippage in both halves. It is not a one-off cell: across the 48 neighbouring settings, <b>41 are positive at 2 bp, 33 in both halves</b>, and the result rises steadily with the size of the gap (+0.02%, +0.05%, +0.08% per trade for gaps of 0.5, 1 and 2%). It matches the earlier study (gaps fade from the open). Example cell: {be['trades']:,} trades, +{be['avg_net_%']:.3f}% per trade, t = {be['all']['t_stat']:.1f}, +{be['all']['total_%']:.0f}% over 5 years on the notional, worst drawdown {be['all']['max_dd_%']:.1f}%.</li>
<li><b>Break-even slippage for that pocket is about 4 bp per side.</b> Liquid large-cap futures can be traded inside 1-2 bp; mid-caps cannot. That is the number that decides whether it works.</li>
<li><b>Reality check with the recorded futures quotes (section 3): it does not survive.</b> The real half-spread a market order pays is <b>4.4 bp at 09:20 for the 30 most active futures, 6.4 bp for the next 70 and 8.4 bp for the rest</b> (about 3-4.5 bp at the close), well above the 1.4 bp break-even of the published rule and about the 4 bp break-even of the gap-fade pocket. Re-running everything with these measured spreads: the published rule is negative in every setting (median -0.12% per trade), and the gap-fade pocket falls to a median of about 0 (gap &ge; 2%: +0.08% median but the 2024-26 half is weak or negative in most settings). Restricting to the most liquid names does not help. Only passive entries near the mid would change this, and that cannot be tested without fill data.</li><li><b>What this is not:</b> a proven profitable system. It is a candidate worth forward testing (paper) on real futures quotes. The next checks are on the recorded futures data (real spread and basis), slippage on stops, and survivorship (today's stock list).</li></ul></div>""")
    html.append("<h2>Cost model</h2><div class='note'>Round trip for a Rs 10 lakh position: STT 0.02% on the sell side, exchange 0.00183% each way, SEBI 0.0001% each way, stamp duty 0.002% on the buy side, brokerage Rs 20 per order, GST 18% on brokerage + exchange + SEBI = <b>__COST__ bp</b>. Slippage is added per side (a stop exit pays double), and a stop that is gapped through fills at the candle's open. Before tax on profits and margin interest.</div>".replace("__COST__", f"{cost:.1f}"))
    html.append("<h2>1. The rule as fixed in advance</h2>" + tr_.table_html(main_tbl, fm, "slippage") + "<h3>Cumulative return on the notional, % (unlevered)</h3>" + chart_main)
    html.append("<h2>2. The gap-fade pocket</h2><div class='note'>Not fixed in advance: it came out of two follow-up cases (gap with the breakout, gap against) that were motivated by the earlier top-movers study (the opening gap is the one clue, and gaps fade). 124 grid cells have now been looked at in total, so only a result that is stable across neighbours and in both halves is taken seriously.</div>"
                + "<h3>Plateau check: 48 neighbouring settings (opening range 5 / 15 min, stops, gap size, top N)</h3>" + tr_.table_html(plateau, {"cells": "{:.0f}", "net > 0": "{:.0f}", "positive in both halves": "{:.0f}", "t >= 2": "{:.0f}", "median net %": "{:.3f}", "median t": "{:.2f}"}, "slippage per side")
                + "<h3>The best 12 settings at 2 bp (shown for reference, not as a recommendation)</h3>" + tr_.table_html(top[["stop", "gap >= %", "top N", "trades", "gross %/trade", "net %/trade", "2021-23 net", "2024-26 net", "t", "total % (5y, unlevered)", "max drawdown %"]], {"trades": "{:,.0f}", "gross %/trade": "{:.3f}", "net %/trade": "{:.3f}", "2021-23 net": "{:.3f}", "2024-26 net": "{:.3f}", "t": "{:.2f}", "total % (5y, unlevered)": "{:.1f}", "max drawdown %": "{:.1f}"}, "opening range (min)")
                + f"<h3>Example cell ({BEST['or']}-minute range, top {BEST['n']}, gap against &ge; {BEST['gap']:g}%, stop {BEST['stop']:.0%} of ATR): cumulative return, % (unlevered)</h3>" + chart_gap)
    import json
    chk = json.loads((RES / "futures_check.json").read_text(encoding="utf-8"))
    sp = pd.DataFrame(chk["spread_by_tier_slot"]).pivot(index="tier", columns="slot", values="median_bp").reindex(["top 30", "31-100", "rest"])
    sp = sp[["09:15-09:30", "09:30-10:30", "10:30-14:30", "14:30-15:30"]]
    mg = pd.read_csv(RES / "measured_spread_grid.csv")
    lg = pd.read_csv(RES / "liquid_universe_grid.csv")
    summ = (lg.assign(both=((lg.h1 > 0) & (lg.h2 > 0))).groupby(["universe", "case"]).agg(settings=("net", "size"), positive=("net", lambda x: int((x > 0).sum())), both_halves=("both", "sum"), median_net=("net", "median"), best_net=("net", "max")))
    html.append("<h2>3. Reality check with the recorded futures quotes (23 and 26 Oct, minute by minute, real bid and ask)</h2><div class='note'>Half-spread = what a market order pays beyond the mid price, in basis points, for the front stock future. One lot always fits at the best price (depth was never the problem). The future tracks the cash stock with a 5-minute difference of about 12 bp (standard deviation), so the cash-price proxy is noisy but unbiased (mean 0.0 bp).</div>"
                + "<h3>Median half-spread (bp) by liquidity and time of day</h3>" + tr_.table_html(sp, {c: "{:.2f}" for c in sp.columns}, "30 / 100 / rest of the futures by turnover")
                + "<h3>The backtest repeated with these spreads (entry pays the opening spread, a normal exit the closing spread, a stop twice the mid-day spread), all 210 stocks</h3>"
                + tr_.table_html(mg.assign(both=((mg.h1 > 0) & (mg.h2 > 0))).groupby("case").agg(settings=("net", "size"), positive=("net", lambda x: int((x > 0).sum())), both_halves=("both", "sum"), median_net=("net", "median"), best_net=("net", "max")), {"settings": "{:.0f}", "positive": "{:.0f}", "both_halves": "{:.0f}", "median_net": "{:.3f}", "best_net": "{:.3f}"}, "case (net % per trade)")
                + "<h3>Restricted to the most liquid stocks</h3>" + tr_.table_html(summ, {"settings": "{:.0f}", "positive": "{:.0f}", "both_halves": "{:.0f}", "median_net": "{:.3f}", "best_net": "{:.3f}"}, "universe | case (net % per trade)"))
    html.append("<h2>Limits</h2><div class='note'><ul><li>Cash-stock prices stand in for futures (the basis is ignored); the real futures spread and fills have not been checked yet.</li><li>The stock list is today's F&amp;O universe (some survivorship).</li><li>124 settings were examined; the headline pocket is supported by its neighbours and by the earlier gap-fade finding, but it was not decided before looking.</li><li>Stops use 5-minute candle lows / highs; real intracandle paths can be worse.</li><li>Unlevered returns on the notional; margin, leverage, capital limits and intraday position limits are not modelled.</li><li>Nothing here is an order, a signal or a change to a live rule.</li></ul></div></div></body></html>")
    p = RES / "index.html"
    p.write_text("".join(html), encoding="utf-8")
    return str(p)


if __name__ == "__main__":
    print(main())
