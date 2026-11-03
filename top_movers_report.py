"""Builds E:\\APlusData\\top_movers_study\\index.html from the stage 1 / 2 tables (stage 3 of top_movers_study.py). READ-ONLY research.

    python top_movers_report.py            all sections
The 'Key findings' block at the top is read from findings.html in the same folder (written by hand after reading the numbers); everything else is generated.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

import top_movers_analysis as ta
import top_movers_study as tm

OUT = tm.OUT
GREEN, RED, BLUE, GREY, AMBER = "#27c281", "#ff6b6b", "#4c8dff", "#8ea0bd", "#f5b942"


# svg helpers --------------------------------------------------------------------------------------------------------------------------------------------------------------
def _scale(lo: float, hi: float, a: float, b: float):
    span = (hi - lo) or 1.0
    return lambda x: a + (x - lo) / span * (b - a)


def svg_lines(series: Sequence[tuple[str, Sequence[float], Sequence[float], str]], w: int = 760, h: int = 260, xticks: Sequence[tuple[float, str]] = (), ylabel: str = "%",
              zero: bool = True, bands: Sequence[tuple[Sequence[float], Sequence[float], Sequence[float], str]] = ()) -> str:
    xs = [x for _, X, _, _ in series for x in X]
    ys = [y for _, _, Y, _ in series for y in Y if np.isfinite(y)] + [y for _, lo, hi, _ in bands for y in list(lo) + list(hi) if np.isfinite(y)]
    if not xs or not ys:
        return ""
    L, R, T, B = 46, 12, 12, 26
    sx, sy = _scale(min(xs), max(xs), L, w - R), _scale(min(ys + [0]), max(ys + [0]), h - B, T)
    o = [f'<svg viewBox="0 0 {w} {h}" class="chart" xmlns="http://www.w3.org/2000/svg">']
    lo_y, hi_y = min(ys + [0]), max(ys + [0])
    for i in range(5):
        v = lo_y + (hi_y - lo_y) * i / 4
        o.append(f'<line x1="{L}" x2="{w - R}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" stroke="#1b2640"/><text x="4" y="{sy(v) + 4:.1f}" fill="{GREY}" font-size="10">{v:.1f}{ylabel}</text>')
    if zero:
        o.append(f'<line x1="{L}" x2="{w - R}" y1="{sy(0):.1f}" y2="{sy(0):.1f}" stroke="#3a4a6e" stroke-dasharray="4 3"/>')
    for x, lab in xticks:
        o.append(f'<text x="{sx(x):.1f}" y="{h - 8}" fill="{GREY}" font-size="10" text-anchor="middle">{html.escape(lab)}</text>')
    for X, lo, hi, color in bands:
        pts = [f"{sx(x):.1f},{sy(a):.1f}" for x, a in zip(X, hi) if np.isfinite(a)] + [f"{sx(x):.1f},{sy(a):.1f}" for x, a in zip(reversed(list(X)), reversed(list(lo))) if np.isfinite(a)]
        o.append(f'<polygon points="{" ".join(pts)}" fill="{color}" opacity="0.13"/>')
    for i, (lab, X, Y, color) in enumerate(series):
        pts = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in zip(X, Y) if np.isfinite(y))
        o.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{pts}"/>')
        o.append(f'<text x="{L + 8 + i * 170}" y="{T + 11}" fill="{color}" font-size="11">&#9632; {html.escape(lab)}</text>')
    o.append("</svg>")
    return "".join(o)


def svg_bars(labels: Sequence[str], values: Sequence[float], w: int = 760, h: int = 230, base: float = 1.0, fmt: str = "{:.2f}x") -> str:
    n = len(values)
    if not n:
        return ""
    L, B, T = 8, 74, 16
    top = max(max(values), base * 1.2)
    bw = (w - L * 2) / n
    o = [f'<svg viewBox="0 0 {w} {h}" class="chart" xmlns="http://www.w3.org/2000/svg">']
    yb = h - B - (base / top) * (h - B - T)
    for i, (lab, val) in enumerate(zip(labels, values)):
        bh = max(1.0, (val / top) * (h - B - T))
        col = GREEN if val >= base * 1.15 else (RED if val <= base * 0.87 else GREY)
        x = L + i * bw
        o.append(f'<rect x="{x + 4:.1f}" y="{h - B - bh:.1f}" width="{bw - 8:.1f}" height="{bh:.1f}" fill="{col}" opacity="0.85"/>')
        o.append(f'<text x="{x + bw / 2:.1f}" y="{h - B - bh - 4:.1f}" fill="#e7eefc" font-size="10" text-anchor="middle">{fmt.format(val)}</text>')
        o.append(f'<text transform="translate({x + bw / 2:.1f},{h - B + 10}) rotate(35)" fill="{GREY}" font-size="9.5">{html.escape(lab)}</text>')
    o.append(f'<line x1="{L}" x2="{w - L}" y1="{yb:.1f}" y2="{yb:.1f}" stroke="{AMBER}" stroke-dasharray="4 3"/>')
    o.append("</svg>")
    return "".join(o)


def mini_chart(path: np.ndarray, prev_close: float, cut: int, w: int = 230, h: int = 84, color: str = GREEN) -> str:
    """Three sessions of 5-minute closes (the day before, the move day, the day after) as % of the day-before's close; the move day is shaded and 10:00 marked."""
    ser = pd.Series(path)
    if ser.first_valid_index() is None:
        return ""
    ser = ser.loc[ser.first_valid_index():ser.last_valid_index()].ffill()          # no line where there is no data (e.g. the day after the last day)
    y = (ser.to_numpy() / prev_close - 1) * 100
    lo, hi = min(np.nanmin(y), 0), max(np.nanmax(y), 0)
    sx, sy = _scale(0, len(path) - 1, 2, w - 2), _scale(lo, hi, h - 4, 4)
    pts = " ".join(f"{sx(i):.1f},{sy(v):.1f}" for i, v in zip(ser.index, y))
    o = [f'<svg viewBox="0 0 {w} {h}" class="mini" xmlns="http://www.w3.org/2000/svg">']
    o.append(f'<rect x="{sx(NB):.1f}" y="0" width="{sx(2 * NB) - sx(NB):.1f}" height="{h}" fill="{color}" opacity="0.09"/>')
    o.append(f'<line x1="2" x2="{w - 2}" y1="{sy(0):.1f}" y2="{sy(0):.1f}" stroke="#3a4a6e" stroke-dasharray="3 3"/>')
    o.append(f'<line x1="{sx(NB + 9):.1f}" x2="{sx(NB + 9):.1f}" y1="0" y2="{h}" stroke="{AMBER}" stroke-width="0.8" stroke-dasharray="2 2"/>')
    o.append(f'<polyline fill="none" stroke="{color}" stroke-width="1.3" points="{pts}"/>')
    o.append("</svg>")
    return "".join(o)


NB = tm.NB


# tables -------------------------------------------------------------------------------------------------------------------------------------------------------------------
def table_html(df: pd.DataFrame, fmt: dict[str, str] | None = None, index_name: str = "", cls: str = "") -> str:
    fmt = fmt or {}
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in [index_name] + list(df.columns))
    rows = []
    for idx, r in df.iterrows():
        cells = [f'<td class="l">{html.escape(" | ".join(str(i) for i in idx) if isinstance(idx, tuple) else str(idx))}</td>']
        for c in df.columns:
            val = r[c]
            if isinstance(val, (float, np.floating)):
                txt = "-" if not np.isfinite(val) else (fmt.get(c, "{:,.2f}").format(val))
            else:
                txt = html.escape(str(val))
            cells.append(f'<td{" class=pos" if _signed(c, val) == 1 else (" class=neg" if _signed(c, val) == -1 else "")}>{txt}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="tw"><table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _signed(col: Any, val: Any) -> int:
    col = str(col)
    if not isinstance(val, (float, np.floating)) or not np.isfinite(val):
        return 0
    if col.endswith(("ev_%", "_net", "net_A", "close_avg_%", "close_med_%")) or "net" in col:
        return 1 if val > 0 else (-1 if val < 0 else 0)
    return 0


def two_list_lift(v: pd.DataFrame, col: str, min_n: int) -> pd.DataFrame:
    """Gainer and loser lift (and both halves) per category in one flat table."""
    g, l = ta.categorical_lift(v, col, "top_gainer", min_n), ta.categorical_lift(v, col, "top_loser", min_n)
    out = pd.DataFrame({"n": g.n, "gainer rate %": g.rate, "gainer lift": g.lift, "2021-23": g.lift_h1, "2024-26": g.lift_h2,
                        "loser rate %": l.rate.reindex(g.index), "loser lift": l.lift.reindex(g.index), "2021-23 ": l.lift_h1.reindex(g.index), "2024-26 ": l.lift_h2.reindex(g.index)})
    return out.sort_values("gainer lift", ascending=False)


def lift_section(v: pd.DataFrame, flag: str, title: str) -> str:
    out = [f"<h3>{title}</h3>"]
    for f, (label, _) in ta.FEATURES.items():
        lt = ta.lift_table(v, f, flag)
        out.append(f"<h4>{html.escape(label)}</h4>")
        out.append(svg_bars([str(i) for i in lt.index], lt.lift.tolist(), h=200))
        t = lt[["n", "rate", "lift", "lift_h1", "lift_h2", "verdict"]].rename(columns={"rate": "top-10 rate %", "lift": "lift (vs same-volatility stocks)", "lift_h1": "lift 2021-23", "lift_h2": "lift 2024-26"})
        out.append(table_html(t, {"n": "{:,.0f}", "top-10 rate %": "{:.2f}", "lift (vs same-volatility stocks)": "{:.2f}", "lift 2021-23": "{:.2f}", "lift 2024-26": "{:.2f}"}, "bucket"))
    return "".join(out)


# gallery ------------------------------------------------------------------------------------------------------------------------------------------------------------------
def gallery(v: pd.DataFrame, cube: np.ndarray, syms: list[str], opt: pd.DataFrame | None, last_days: int = 20) -> str:
    sidx = {s: i for i, s in enumerate(syms)}
    days = sorted(v.day.unique())[-last_days:]
    o = []
    optk = None
    if opt is not None:
        a = opt[(opt.et == "1000") & (opt.st == "ATM")]
        optk = {(s, d, sd): r for s, d, sd, r in zip(a.sym, a.day, a.side, a.itertuples())}
    for day in reversed(days):
        d = v[v.day == day]
        o.append(f'<h3>{pd.to_datetime(str(day)).strftime("%a %d %b %Y")} <span class="sub">market median {d.mkt_chg.iloc[0]:+.2f}% | each chart: day before, <b>the move day</b> (shaded), day after; orange line = 10:00</span></h3>')
        for flag, name, color, side in (("top_gainer", "Top 10 gainers", GREEN, "CE"), ("top_loser", "Top 10 losers", RED, "PE")):
            rows = d[d[flag]].sort_values("rank_up" if flag == "top_gainer" else "rank_dn")
            o.append(f'<div class="gal"><div class="gt">{name}</div>')
            for r in rows.itertuples():
                di, si = int(r.day_i), sidx[r.sym]
                parts = [cube[si, k, :, 3] if 0 <= k < cube.shape[1] else np.full(NB, np.nan) for k in (di - 1, di, di + 1)]
                path = np.concatenate(parts).astype("float64")
                ref = parts[0][np.isfinite(parts[0])]
                base = float(ref[-1]) if len(ref) else float(r.prev_close)
                opt_txt = ""
                if optk is not None and (r.sym, r.day, side) in optk:
                    x = optk[(r.sym, r.day, side)]
                    opt_txt = f'<div class="ot">{side} ATM bought 10:00 at &#8377;{x.px_e:.1f}: best {x.max_g:+.0f}% | close {x.close_g:+.0f}%</div>'
                o.append(f'<div class="cell"><div class="ct"><b>{html.escape(r.sym)}</b> {r.chg:+.1f}% <span class="sub">gap {r.gap:+.1f}% | 10:00 {r.r1000:+.1f}%</span></div>{mini_chart(path, base, 0, color=color)}{opt_txt}</div>')
            o.append("</div>")
    return "".join(o)


CSS = """
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--blue:#4c8dff;--green:#27c281;--red:#ff6b6b;--amber:#f5b942}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:18px 16px 80px}h1{font-size:24px;margin:6px 0}h2{font-size:19px;margin:34px 0 8px;padding-top:10px;border-top:1px solid var(--line)}h3{font-size:15px;margin:22px 0 6px}h4{font-size:13px;margin:14px 0 2px;color:#c9d6ef}
.sub{color:var(--muted);font-weight:400;font-size:12px}p{margin:6px 0}.note{background:#14213a;border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:10px 0}
.find{background:#0f2a22;border:1px solid #1f6b50;border-radius:10px;padding:12px 16px;margin:12px 0}.find li{margin:5px 0}.warn{background:#2a2310;border:1px solid #6b5a1f;border-radius:10px;padding:10px 14px;margin:10px 0}
.tw{overflow-x:auto;margin:6px 0}table{border-collapse:collapse;background:var(--panel);border:1px solid var(--line);font-size:12px}th,td{padding:4px 9px;text-align:right;border-bottom:1px solid #1b2640;white-space:nowrap}th{color:var(--muted);background:#0f1729;font-size:11px}
td.l,th:first-child{text-align:left}td.pos{color:var(--green)}td.neg{color:var(--red)}.chart{width:100%;max-width:780px;background:#0e1527;border:1px solid var(--line);border-radius:8px}
.mini{width:100%;height:auto;display:block}.gal{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:8px;margin:6px 0 14px}.gt{grid-column:1/-1;font-weight:800;color:#c9d6ef}
.cell{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:5px 6px}.ct{font-size:12px}.ot{font-size:11px;color:#9fd9c1}nav a{color:var(--blue);margin-right:14px;text-decoration:none;font-weight:700}
@media(max-width:700px){.wrap{padding:12px 10px}}
"""


def build() -> Path:
    df = pd.read_pickle(OUT / "stock_days.pkl")
    v = ta.prepare(df)
    cube = np.load(OUT / "cube.npy", mmap_mode="r")
    syms = pd.read_csv(OUT / "cube_symbols.csv", header=None)[0].tolist()
    opt = None
    j = None
    if (OUT / "option_days.pkl").exists():
        opt = pd.read_pickle(OUT / "option_days.pkl")
        j = ta.join_options(opt, v)
    findings = (OUT / "findings.html").read_text(encoding="utf-8") if (OUT / "findings.html").exists() else "<p>(findings not written yet)</p>"
    n_days, n_sym = v.day.nunique(), v.sym.nunique()
    d0, d1 = pd.to_datetime(str(v.day.min())).strftime("%d %b %Y"), pd.to_datetime(str(v.day.max())).strftime("%d %b %Y")
    h = [f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Top movers study</title><meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style></head><body><div class="wrap">']
    h.append(f'<h1>Every day\'s top-10 gainers and losers - what came before, how the day went, how the options moved, what came after</h1><div class="sub">{n_sym} F&amp;O stocks, {n_days:,} trading days ({d0} to {d1}), 5-minute candles; options: rolling near-month ATM / one strike in / one strike out. Read-only research - no live rule was changed.</div>')
    h.append('<nav><a href="#findings">Findings</a><a href="#before">1 Before</a><a href="#during">2 During</a><a href="#options">3 Options</a><a href="#after">4 After</a><a href="#types">5 Day types</a><a href="#gallery">6 Charts by day</a><a href="#method">Method</a></nav>')
    h.append(f'<h2 id="findings">Key findings</h2><div class="find">{findings}</div>')

    # 1 before
    h.append('<h2 id="before">1. Before the move: which stocks become top movers</h2><div class="note">Each bar is the chance of landing in the top-10 list (gainers or losers) for stocks with that feature, divided by the chance for stocks of the same normal range that day (so jumpy stocks do not look special just for being jumpy). 1.00x = no effect. Green/red = holds in <b>both</b> halves of the history (2021-23 and 2024-26) and is at least 15% off. Everything here is known before the move (yesterday or the opening gap).</div>')
    h.append(lift_section(v, "top_gainer", "Top-10 GAINERS"))
    h.append(lift_section(v, "top_loser", "Top-10 LOSERS"))
    h.append("<h3>Was the stock in yesterday's top 10?</h3>" + table_html(ta.prior_listing(v).set_index(["today", "yesterday_in", "answer"]), {"n": "{:,.0f}"}, "today / yesterday / was it"))
    h.append("<h3>Which sectors fill the lists</h3>" + table_html(two_list_lift(v[v.sector.notna()], "sector", 400), {"n": "{:,.0f}"}, "sector"))
    h.append("<h3>Market day type</h3>" + table_html(two_list_lift(v, "mkt_type", 200), {"n": "{:,.0f}"}, "market that day (median stock)"))

    # 2 during
    w = ta.when_it_happens(v)
    h.append('<h2 id="during">2. During the day: when the move happens, and can you see it early?</h2>')
    h.append("<h3>How much of the final move is done by each clock time (median of the top-10 stocks)</h3>" + table_html(w["timing"], {}, ""))
    xt = [(i, lab) for i, lab in enumerate(w["extreme_hist"].index) if i % 2 == 0]
    h.append("<h3>When the day's high (gainers) or low (losers) was made, % of cases</h3>" + svg_lines([("gainers: high", range(len(w["extreme_hist"])), w["extreme_hist"].iloc[:, 0], GREEN), ("losers: low", range(len(w["extreme_hist"])), w["extreme_hist"].iloc[:, 1], RED)], xticks=xt, ylabel="%", zero=False))
    paths = ta.intraday_paths(v, np.asarray(cube), syms)
    x = list(range(NB))
    clock = [(i, f"{9 + (15 + 5 * i) // 60}:{(15 + 5 * i) % 60:02d}") for i in range(0, NB, 12)]
    h.append("<h3>Average path of the top-10 lists through the day (return vs yesterday's close; band = middle half of the stocks)</h3>" + svg_lines(
        [("gainers (mean)", x, paths["gainers"][0], GREEN), ("losers (mean)", x, paths["losers"][0], RED)], xticks=clock, bands=[(x, paths["gainers"][1], paths["gainers"][2], GREEN), (x, paths["losers"][1], paths["losers"][2], RED)]))
    ev = ta.early_visibility(v)
    h.append("<h3>If a stock is already near the top at 09:30 / 10:00 / 11:00 - how often does it finish in the top 10, and what is left of the move?</h3><div class='note'>'left' = stock move from that clock time to the close, counted positive when it goes the same way as the list (a gainer keeps rising / a loser keeps falling). If chasing worked, the left-over would be clearly positive.</div>" + table_html(ev.set_index(["list", "seen_at", "ranked_in_top"]), {"n": "{:,.0f}"}, "list / clock / ranked in top"))
    edges = [-np.inf, -4, -3, -2, -1, 1, 2, 3, 4, np.inf]
    rows = []
    for clk in ("0930", "1000", "1100"):
        s = v[v[f"px{clk}"].notna()].copy()
        s["left"] = (s.close / s[f"px{clk}"] - 1) * 100
        for b, g in s.groupby(pd.cut(s[f"r{clk}"], edges), observed=True):
            rows.append({"clock": clk, "already moved (vs yesterday's close, %)": str(b), "n": len(g), "avg move left to close %": g.left.mean(), "up %": (g.left > 0).mean() * 100,
                         "2021-23 avg": g[g.half == 1].left.mean(), "2024-26 avg": g[g.half == 2].left.mean()})
    h.append("<h3>Any stock, any day: the move that is left, by how far it has already moved</h3>" + table_html(pd.DataFrame(rows).set_index(["clock", "already moved (vs yesterday's close, %)"]), {"n": "{:,.0f}", "avg move left to close %": "{:.3f}", "2021-23 avg": "{:.3f}", "2024-26 avg": "{:.3f}", "up %": "{:.1f}"}, "clock / already moved"))
    ce = ta.ceiling(v)
    h.append("<h3>Can a trained model see it? (trained on 2021-23, tested on 2024-26, using everything known by 10:00)</h3><div class='note'>Gradient-boosted model with the gap, the move so far, the market's move, volume, range, trend, distance from highs/lows, expiry distance. If it found a pattern, its top-10 picks would finish in the real top 10 clearly more often than picks made by simply ranking the 10:00 move.</div>"
             + table_html(ce["classify"], {"AUC (model)": "{:.3f}", "model picks that finish in the top 10 (%)": "{:.1f}", "picks by simply ranking the 10:00 move (%)": "{:.1f}", "random pick (%)": "{:.1f}"}, "target")
             + f"<div class='note'>The tradeable question - does it predict the move still to come from 10:00 to the close? Correlation between prediction and the real move left: <b>{ce['corr']:.3f}</b> over {ce['n_test']:,} test stock-days (0 = nothing, 1 = perfect). Average move left, by the model's rank that day:</div>"
             + table_html(ce["left_by_decile"], {"n": "{:,.0f}", "avg move left to close %": "{:.3f}", "median %": "{:.3f}"}, "model's rank of the stock that day"))
    gp = []
    for name, m in (("gap > +2%", v.gap > 2), ("gap +1..2%", (v.gap > 1) & (v.gap <= 2)), ("gap -1..-2%", (v.gap < -1) & (v.gap >= -2)), ("gap < -2%", v.gap < -2)):
        s = v[m]
        gp.append({"opening gap": name, "n": len(s), "avg close-vs-open %": s.from_open.mean(), "up from open %": (s.from_open > 0).mean() * 100, "2021-23 avg": s[s.half == 1].from_open.mean(), "2024-26 avg": s[s.half == 2].from_open.mean(),
                   "ends in a top-10 list %": (s.top_gainer.mean() if "+" in name else s.top_loser.mean()) * 100})
    h.append("<h3>The opening gap: does the move continue after 09:15?</h3>" + table_html(pd.DataFrame(gp).set_index("opening gap"), {"n": "{:,.0f}", "avg close-vs-open %": "{:.3f}", "2021-23 avg": "{:.3f}", "2024-26 avg": "{:.3f}", "up from open %": "{:.1f}", "ends in a top-10 list %": "{:.1f}"}, "opening gap"))

    # 3 options
    h.append('<h2 id="options">3. The options: how they moved, and what could actually be captured</h2>')
    if j is None:
        h.append("<p>(option statistics not built yet)</p>")
    else:
        h.append(f'<div class="note">Every figure is the move of the option bought at the stated clock time (open of that 5-minute candle), followed on the <b>same strike</b> to the end of the day. "close" = hold to 15:25; "touch +20%" = the best price reached at least +20% at some point; A = take +20% / stop -20%, B = take +40% / stop -25% (a candle touching both counts as the stop). "net" subtracts {ta.COST_PCT:.0f}% of the premium for round-trip cost. Prices are candle prints, not bid/ask. Calls are matched to gainers, puts to losers.</div>')
        fm = {"n": "{:,.0f}", "avg_premium": "{:.1f}"}
        h.append("<h3>Hindsight: the matching option on each day's top-10 (what the best possible picking would have earned)</h3>" + table_html(ta.hindsight_table(j), fm, "case"))
        h.append("<h3>Control: the same option on EVERY stock, no picking (the bar to beat)</h3>" + table_html(ta.control_table(j), fm, "case"))
        h.append("<h3>Rules a scanner could really apply (information known at the entry time only)</h3>" + table_html(ta.rule_table(j), fm, "rule"))
        h.append("<h3>Hindsight trades by days to expiry (ATM, entered 10:00)</h3>" + table_html(ta.by_dte(j), fm, "days to expiry"))

    # 4 after
    h.append('<h2 id="after">4. After the move</h2><div class="note">Measured from the move day\'s close, positive = the move continues in the same direction.</div>')
    h.append(table_html(ta.after_the_move(v).set_index(["list", "subset"]), {"n": "{:,.0f}"}, "list / subset"))
    ep = ta.event_paths(df, v)
    xs = list(range(-10, 6))
    h.append("<h3>Average daily close path around the move day (0 = yesterday's close; the jump at day 0 is the move itself)</h3>" + svg_lines(
        [("gainers (mean)", xs, ep["gainers"].reindex(xs).tolist(), GREEN), ("losers (mean)", xs, ep["losers"].reindex(xs).tolist(), RED)], xticks=[(k, f"{k:+d}d") for k in range(-10, 6, 2)]))

    # 5 day types
    m = v[v.top_gainer | v.top_loser].copy()
    m["type"] = ta.classify(m)
    m["list"] = np.where(m.top_gainer, "gainers", "losers")
    tt = m.groupby(["list", "type"]).agg(n=("chg", "size"), final_move=("chg", "median"), gap=("gap", "median"), move_at_10=("r1000", "median"), from_open=("from_open", "median"), next_day=("nx_chg", "median")).round(2)
    tt["share %"] = (tt.n / tt.groupby(level=0).n.transform("sum") * 100).round(1)
    h.append('<h2 id="types">5. Day types of the top movers</h2><div class="note">Every top-10 stock-day is given the first matching label: gap-driven (gap is the main part of the move), recovery (first went against the list by 0.8%+, then reversed), late surge (over 40% of the move after 13:00), early trend (a third done by 10:00), otherwise mid-day build.</div>' + table_html(tt, {"n": "{:,.0f}"}, "list / type"))
    if j is not None:
        g = j[(j.et == "1000") & (j.st == "ATM")].merge(m[["sym", "day", "type"]], on=["sym", "day"])
        g = g[((g.side == "CE") & g.top_gainer) | ((g.side == "PE") & g.top_loser)]
        h.append("<h3>The matching ATM option bought at 10:00, by day type (hindsight)</h3>" + table_html(ta.table_rows({k: x for k, x in g.groupby("type")})[["n", "close_avg_%", "close_win_%", "max_avg_%", "touch_+20_%", "A_win_%", "A_net_ev_%", "close_net_ev_%"]], {"n": "{:,.0f}"}, "day type"))

    # 6 gallery
    h.append('<h2 id="gallery">6. Charts: before and after, for the last 20 trading days in the data</h2><div class="note">Top-10 gainers (green) and losers (red) of each day with the day before, the day itself and the day after. Under each chart: the matching ATM option bought at 10:00 - the best price it reached and where it closed. The full list of all days is in <b>daily_top10.csv</b> (25,000 rows) next to this page.</div>')
    h.append(gallery(v, cube, syms, opt))

    h.append('<h2 id="method">Method and limits</h2><div class="note"><ul>'
             '<li>Top 10 = largest close-vs-previous-close change among the day\'s valid stocks (about 200). Days that look like corporate actions (move &gt; 25% or gap &gt; 20%) are dropped.</li>'
             '<li>"Before" features use only data up to yesterday\'s close (and today\'s opening gap, known at 09:15). Lift is compared with stocks of the same normal range that day and shown for both halves of the history.</li>'
             '<li>Option series are the exchange\'s rolling near-month contracts (ATM and +-3 strikes). The strike bought is fixed at entry and followed bar by bar; if the stock moves so far that the strike leaves the +-3 window, later candles are missing for that trade and the trade is judged on what exists.</li>'
             '<li>Candle prints are not tradable quotes: real fills are at the ask and the exit at the bid. The cost haircut is a rough stand-in. Days to expiry use the standard monthly expiry rule (holiday shifts not modelled).</li>'
             '<li>History ends 28 Aug 2026 for stocks and 6 Oct 2026 for options; September-October 2026 is not in these tables.</li></ul></div></div></body></html>')
    p = OUT / "index.html"
    p.write_text("".join(h), encoding="utf-8")
    return p


if __name__ == "__main__":
    print(build())
