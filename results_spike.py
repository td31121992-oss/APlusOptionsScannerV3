"""Results-spike watch (SHADOW ONLY: a nightly study; nothing trades or alerts on it).

26 Oct 2026, ATHERENERG: the quarterly results were filed at 14:27:42 and the stock went from 1,409 to 1,518 in ten minutes (+10 %) and 1,611 by 15:00 (+16.8 % on the day). The scanner
logged it as a leader every minute but it never became entry-ready, so no trade; the nearest-the-money call went from about 78 to 185 (about Rs 40,000 a lot, lot 375).

For every filing made during market hours that reads like financial results (an "Outcome of Board Meeting" saying results, "financial results", "unaudited ..."), this module asks, from the recorded ticks:

    REFERENCE     the stock's price 10 minutes before the filing
    SPIKE         the first moment from 2 minutes before the filing to 15 minutes after it that the stock stands >= 2.0 % away from the reference (up = a call, down = a put)
    ENTRY         the spike moment plus one scanner cycle (60 s); the nearest-the-money option of the right side at its ask (else last price), from the chain snapshots
    OUTCOME       the option's peak %, last %, which came first of +40 % or -30 %, and the rupees of the peak / the last price on one lot
    NO SPIKE      filings where the stock never moved 2 %: recorded too, so the review shows what the average results filing does

    data/results_spike/ledger.csv   one row per (day, stock, filing)
    data/results_spike/review.md    spike entries against filings that did not spike, over all days recorded

    python results_spike.py [YYYY-MM-DD ...]   rebuild those days (default today) and the review
"""

from __future__ import annotations

import csv
import json
import re
import statistics as st
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
ANN = ("data", "news_intelligence", "announcements.jsonl")
LEDGER = ("data", "results_spike", "ledger.csv")
REVIEW = ("data", "results_spike", "review.md")
MARKET_OPEN_S, MARKET_CLOSE_S = 9 * 3600 + 20 * 60, 15 * 3600 + 20 * 60
SPIKE_PCT = 2.0
REF_BEFORE_S, WINDOW_BEFORE_S, WINDOW_AFTER_S, DELAY_S = 600, 120, 900, 60
FIELDS = ["day", "symbol", "published", "kind", "status", "direction", "spike_pct", "spike_time", "vol_x", "strike", "side", "entry", "peak_pct", "last_pct", "first", "lot", "peak_rs", "last_rs"]
RESULTS_RE = re.compile(r"financial results?|unaudited|audited results?|results for the (?:quarter|period|half)|quarter(?:ly)? results", re.I)


def is_results(row: Mapping[str, Any]) -> bool:
    """A filing that reads like financial results (the title says board-meeting outcome or results and the text names results)."""
    desc, text = str(row.get("desc") or ""), str(row.get("text") or "")
    if re.search(r"press release|investor presentation|schedule of meet|transcript|audio|analysts?/institutional", desc, re.I):
        return False
    return bool(RESULTS_RE.search(text) or (re.search(r"outcome of board meeting", desc, re.I) and re.search(r"results?", text, re.I)))


def _secs_of(iso: str) -> float | None:
    try:
        d = datetime.fromisoformat(iso).astimezone(IST)
    except (TypeError, ValueError):
        return None
    return d.hour * 3600 + d.minute * 60 + d.second


def results_filings(day: str, root: Path = ROOT) -> list[dict[str, Any]]:
    path = root.joinpath(*ANN)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        pub = str(r.get("published_at") or "")
        if not pub.startswith(day) or not r.get("symbol") or not is_results(r):
            continue
        t = _secs_of(pub)
        if t is None or not (MARKET_OPEN_S <= t <= MARKET_CLOSE_S):
            continue
        out.setdefault((str(r["symbol"]), pub[:16]), {"symbol": str(r["symbol"]), "published": pub, "t": t, "kind": str(r.get("desc") or "")[:40]})
    return sorted(out.values(), key=lambda f: f["t"])


def find_spike(series: Sequence[tuple[float, float, float]], t_pub: float, pct: float = SPIKE_PCT) -> dict[str, Any]:
    """series: (seconds, price, cumulative volume) oldest first. Returns {} when there is no price before the reference time."""
    ref = None
    for t, p, _ in series:
        if t <= t_pub - REF_BEFORE_S:
            ref = p
        else:
            break
    if not ref or ref <= 0:
        return {}
    best = 0.0
    for t, p, v in series:
        if t < t_pub - WINDOW_BEFORE_S:
            continue
        if t > t_pub + WINDOW_AFTER_S:
            break
        move = (p / ref - 1.0) * 100.0
        if abs(move) > abs(best):
            best = move
        if abs(move) >= pct:
            return {"ref": ref, "spike_pct": round(move, 2), "spike_t": t, "direction": "BULLISH" if move > 0 else "BEARISH", "best_move": round(best, 2)}
    return {"ref": ref, "best_move": round(best, 2)}


def volume_multiple(series: Sequence[tuple[float, float, float]], t: float) -> float | None:
    """Volume in the 5 minutes up to t against the average 5-minute volume of the 30 minutes before that."""
    def cum(at: float) -> float | None:
        c = None
        for ts, _, v in series:
            if ts <= at:
                c = v
            else:
                break
        return c
    a, b, c0 = cum(t), cum(t - 300), cum(t - 2100)
    if a is None or b is None or c0 is None or b <= c0:
        return None
    base = (b - c0) / 6.0
    return round((a - b) / base, 1) if base > 0 else None


def _lot_size(symbol: str, root: Path) -> float:
    try:
        import pandas as pd
        m = pd.read_csv(root / "data" / "cache" / "api-scrip-master-detailed.csv", low_memory=False, usecols=["UNDERLYING_SYMBOL", "INSTRUMENT", "LOT_SIZE"])
        v = m[(m.UNDERLYING_SYMBOL == symbol) & (m.INSTRUMENT == "OPTSTK")].LOT_SIZE.dropna()
        return float(v.iloc[0]) if len(v) else 0.0
    except Exception:                                      # noqa: BLE001 - rupees are optional
        return 0.0


def day_rows(day: str, root: Path = ROOT, series_map: Mapping[str, Sequence[tuple[float, float, float]]] | None = None) -> list[dict[str, Any]]:
    filings = results_filings(day, root)
    if not filings:
        return []
    if series_map is None:
        import rs_replay
        series_map = {}
        by: dict[str, list[tuple[float, float, float]]] = {}
        for t, sym, ltp, vol, *_ in rs_replay.load_samples(root, day):
            if not sym.startswith("#"):
                by.setdefault(sym, []).append((t, ltp, vol))
        series_map = by
    import late_runner
    chain = late_runner._chain(root, day, {f["symbol"] for f in filings})
    out = []
    for f in filings:
        base = {"day": day, "symbol": f["symbol"], "published": f["published"][11:19], "kind": f["kind"]}
        series = series_map.get(f["symbol"]) or []
        sp = find_spike(series, f["t"]) if series else {}
        if not sp:
            out.append({**base, "status": "NO_DATA"})
            continue
        if "spike_t" not in sp:
            out.append({**base, "status": "NO_SPIKE", "spike_pct": sp["best_move"]})
            continue
        et = sp["spike_t"] + DELAY_S
        hhmm = f"{int(et // 3600):02d}:{int(et % 3600 // 60):02d}"
        row = {**base, "status": "SPIKE", "direction": sp["direction"], "spike_pct": sp["spike_pct"], "spike_time": f"{int(sp['spike_t'] // 3600):02d}:{int(sp['spike_t'] % 3600 // 60):02d}:{int(sp['spike_t'] % 60):02d}",
               "vol_x": volume_multiple(series, sp["spike_t"])}
        got = late_runner.follow(chain.get(f["symbol"], []), sp["direction"], hhmm)
        if not got:
            row["status"] = "SPIKE_NO_OPTION"
        else:
            lot = _lot_size(f["symbol"], root)
            entry = got["entry"]
            peak_px, last_px = entry * (1 + got["peak_pct"] / 100), entry * (1 + got["last_pct"] / 100)
            row.update({k: got[k] for k in ("strike", "side", "entry", "peak_pct", "last_pct", "first")})
            row.update({"lot": lot or "", "peak_rs": round((peak_px - entry) * lot) if lot else "", "last_rs": round((last_px - entry) * lot) if lot else ""})
        out.append(row)
    return out


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as h:
        return list(csv.DictReader(h))


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def render(rows: Sequence[Mapping[str, Any]]) -> str:
    days = sorted({r["day"] for r in rows})
    sp = [r for r in rows if r.get("status") == "SPIKE"]
    lines = ["# Results-spike watch (shadow; nothing trades or alerts on this)", "",
             f"Days: {len(days)} ({days[0] if days else '-'} .. {days[-1] if days else '-'}). Results filings during market hours: {len(rows)}. Spike = the stock >= {SPIKE_PCT:.0f} % from its price 10 minutes before the filing, "
             f"within 2 minutes before to 15 minutes after it. Entry = spike + {DELAY_S} s, nearest-the-money option at the ask; T1 = +40 % before SL = -30 %.", "",
             "| outcome | filings |", "|---|---|"]
    for name in ("SPIKE", "SPIKE_NO_OPTION", "NO_SPIKE", "NO_DATA"):
        lines.append(f"| {name} | {sum(1 for r in rows if r.get('status') == name)} |")
    done = [r for r in sp if r.get("entry")]
    if done:
        peaks, lasts = [_f(r["peak_pct"]) for r in done], [_f(r["last_pct"]) for r in done]
        lines += ["", f"Spike entries followed: {len(done)} | +40 % first: {sum(1 for r in done if r['first'] == 'T1')} | -30 % first: {sum(1 for r in done if r['first'] == 'SL')} | "
                  f"median peak {st.median(peaks):.0f} % | median last {st.median(lasts):.0f} % | peak Rs total {sum(_f(r['peak_rs']) for r in done):,.0f} | last Rs total {sum(_f(r['last_rs']) for r in done):,.0f}", "",
                  "| day | stock | filed | spike | at | volume x | option | entry | peak % | last % | first | peak Rs | last Rs |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        lines += [f"| {r['day']} | {r['symbol']} | {r['published']} | {r['spike_pct']}% | {r['spike_time']} | {r.get('vol_x') or '-'} | {r['strike']} {r['side']} | {r['entry']} | {r['peak_pct']} | {r['last_pct']} | {r['first']} | {r.get('peak_rs') or '-'} | {r.get('last_rs') or '-'} |"
                  for r in sorted(done, key=lambda r: (r["day"], r["spike_time"]))]
    quiet = [r for r in rows if r.get("status") == "NO_SPIKE"]
    if quiet:
        lines += ["", f"Filings that did not spike: {len(quiet)}, median best move {st.median(abs(_f(r['spike_pct'])) for r in quiet):.1f} %."]
    lines += ["", "A handful of days says little: judge it by how often a spike entry keeps going, not by the best case.", ""]
    return "\n".join(lines)


def run(days: Sequence[str], root: Path = ROOT) -> Path:
    path = root.joinpath(*LEDGER)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in _read(path) if r.get("day") not in set(days)]
    for d in days:
        rows += [{k: ("" if v is None else v) for k, v in r.items()} for r in day_rows(d, root)]
    rows.sort(key=lambda r: (r["day"], r.get("published", "")))
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    out = root.joinpath(*REVIEW)
    out.write_text(render(rows), encoding="utf-8")
    return out


if __name__ == "__main__":
    ds = sys.argv[1:] or [datetime.now(IST).strftime("%Y-%m-%d")]
    print(run(ds))
    print(ROOT.joinpath(*REVIEW).read_text(encoding="utf-8"))
