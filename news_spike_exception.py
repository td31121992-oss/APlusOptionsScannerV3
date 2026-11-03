"""News-spike exception to the overextension check (SHADOW ONLY: the check still rejects the candidate; this only records what an exception would have caught).

The scanner's overextension check (EXTENDED_NO_ENTRY: chase score >= 45, more than 3.375 ATR or 3.375 % from VWAP) rejected ATHERENERG all through its 26 Oct results spike
(1,409 -> 1,518 in ten minutes, the call from about 78 to 185). Rejecting a stock that has just jumped is the check doing its job, so this asks, without changing it, whether
a CONFIRMED news spike deserves an exception. When the check rejects a candidate that also has

    NEWS      a filing for the stock published in the last 20 minutes that is a results filing or a HIGH-severity announcement,
    SPIKE     the stock up (down) 2.0 % or more in our direction over the last 15 minutes, and
    VOLUME    the last 15 minutes' volume at least 3 times normal,

one row is written (at most one per stock and direction every 5 minutes) to data/news_spike_exception/<day>.csv with the numbers the check judged it on. Nothing else changes.

    data/news_spike_exception/ledger.csv   nightly: the first row per (day, stock, direction) followed on the nearest-the-money option at the ask (peak %, last %, +40 % / -30 % first, Rs on a lot)
    data/news_spike_exception/review.md    the exception's entries over all days recorded

    python news_spike_exception.py [YYYY-MM-DD ...]   rebuild those days (default today) and the review
"""

from __future__ import annotations

import csv
import json
import statistics as st
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
FOLDER = ("data", "news_spike_exception")
NEWS_WINDOW_MIN = 20
MIN_MOVE_PCT = 2.0
MIN_VOLUME_X = 3.0
EVERY_SECONDS = 300
FIELDS = ["time", "symbol", "direction", "ltp", "filing", "filing_min_ago", "move_15m_pct", "volume_x", "ext_atr", "vwap_dist_pct", "chase"]
LEDGER_FIELDS = ["day", "symbol", "direction", "time", "filing", "filing_min_ago", "move_15m_pct", "volume_x", "ext_atr", "vwap_dist_pct", "chase", "strike", "side", "entry", "peak_pct", "last_pct", "first", "lot", "peak_rs", "last_rs"]
_ANN: dict[str, Any] = {"mtime": None, "path": None, "rows": []}
_LAST: dict[tuple[str, str], float] = {}


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def _announcements(root: Path) -> list[dict[str, Any]]:
    path = root.joinpath("data", "news_intelligence", "announcements.jsonl")
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    if _ANN["mtime"] != mtime or _ANN["path"] != str(path):
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines()[-4000:]:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        _ANN.update(mtime=mtime, path=str(path), rows=rows)
    return _ANN["rows"]


def recent_filing(symbol: str, now: datetime, root: Path = ROOT) -> tuple[str, float] | None:
    """The newest results / HIGH-severity filing of the stock in the last NEWS_WINDOW_MIN minutes: (its title, minutes ago)."""
    import results_spike
    best = None
    if now.tzinfo is None:                                 # the scanner's clock is Indian time
        now = now.replace(tzinfo=IST)
    for r in _announcements(root):
        if r.get("symbol") != symbol:
            continue
        try:
            at = datetime.fromisoformat(str(r.get("published_at")))
        except (TypeError, ValueError):
            continue
        ago = (now - at).total_seconds() / 60.0
        if -1.0 <= ago <= NEWS_WINDOW_MIN and (results_spike.is_results(r) or str(r.get("severity")).upper() == "HIGH"):
            if best is None or ago < best[1]:
                best = (str(r.get("desc") or "")[:40], round(max(ago, 0.0), 1))
    return best


def check(symbol: str, direction: str, now: datetime, features: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any] | None:
    """Would a confirmed news spike have excused the overextension check? None when it would not."""
    sign = 1.0 if str(direction).upper() == "BULLISH" else -1.0
    move = sign * _f(features.get("recent_move_15m_percent"))
    vol = _f(features.get("recent_relative_volume_15m"))
    if move < MIN_MOVE_PCT or vol < MIN_VOLUME_X:
        return None
    news = recent_filing(symbol, now, root)
    if not news:
        return None
    return {"filing": news[0], "filing_min_ago": news[1], "move_15m_pct": round(move, 2), "volume_x": round(vol, 1)}


def observe(root: Path, symbol: str, direction: str, now: datetime, ltp: float, features: Mapping[str, Any], extension_atr: float, vwap_distance_percent: float) -> bool:
    """Called where the overextension check rejects a candidate. Writes the row when a confirmed news spike is present. Never raises, never changes the rejection."""
    try:
        hit = check(symbol, direction, now, features, root)
        if not hit:
            return False
        key = (symbol, str(direction))
        if (now if now.tzinfo else now.replace(tzinfo=IST)).timestamp() - _LAST.get(key, 0.0) < EVERY_SECONDS:
            return False
        _LAST[key] = (now if now.tzinfo else now.replace(tzinfo=IST)).timestamp()
        path = root.joinpath(*FOLDER, f"{now.date().isoformat()}.csv")
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as h:
            w = csv.DictWriter(h, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow({"time": now.isoformat(timespec="seconds"), "symbol": symbol, "direction": direction, "ltp": round(_f(ltp), 2), **hit, "ext_atr": round(_f(extension_atr), 2),
                        "vwap_dist_pct": round(_f(vwap_distance_percent), 2), "chase": round(_f(features.get("chase_risk_score")), 1)})
        return True
    except Exception:                                      # noqa: BLE001 - a shadow record must never touch a candidate
        return False


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as h:
        return list(csv.DictReader(h))


def day_rows(day: str, root: Path = ROOT) -> list[dict[str, Any]]:
    import late_runner
    import results_spike
    rows = _read(root.joinpath(*FOLDER, f"{day}.csv"))
    first: dict[tuple[str, str], dict[str, str]] = {}
    for r in rows:
        first.setdefault((r["symbol"], r["direction"]), r)
    chain = late_runner._chain(root, day, {k[0] for k in first})
    out = []
    for (sym, direction), r in first.items():
        got = late_runner.follow(chain.get(sym, []), direction, r["time"][11:16])
        if not got:
            continue
        lot = results_spike._lot_size(sym, root)
        entry = got["entry"]
        peak_px, last_px = entry * (1 + got["peak_pct"] / 100), entry * (1 + got["last_pct"] / 100)
        out.append({"day": day, "symbol": sym, "direction": direction, "time": r["time"][11:19], **{k: r[k] for k in ("filing", "filing_min_ago", "move_15m_pct", "volume_x", "ext_atr", "vwap_dist_pct", "chase")},
                    **{k: got[k] for k in ("strike", "side", "entry", "peak_pct", "last_pct", "first")}, "lot": lot or "",
                    "peak_rs": round((peak_px - entry) * lot) if lot else "", "last_rs": round((last_px - entry) * lot) if lot else ""})
    return out


def render(rows: Sequence[Mapping[str, Any]]) -> str:
    days = sorted({r["day"] for r in rows})
    lines = ["# News-spike exception to the overextension check (shadow; the check still rejects these)", "",
             f"Days: {len(days)} ({days[0] if days else '-'} .. {days[-1] if days else '-'}), entries: {len(rows)}. An entry = the check rejected the stock while a results / HIGH filing was under {NEWS_WINDOW_MIN} minutes old, "
             f"the stock was {MIN_MOVE_PCT:.0f} %+ up (down) in 15 minutes and 15-minute volume was {MIN_VOLUME_X:.0f}x normal. Option: nearest-the-money at the ask from the first chain row after the row; T1 = +40 % before SL = -30 %.", ""]
    if rows:
        peaks, lasts = [_f(r["peak_pct"]) for r in rows], [_f(r["last_pct"]) for r in rows]
        lines += [f"+40 % first: {sum(1 for r in rows if r['first'] == 'T1')} | -30 % first: {sum(1 for r in rows if r['first'] == 'SL')} | median peak {st.median(peaks):.0f} % | median last {st.median(lasts):.0f} % | "
                  f"peak Rs {sum(_f(r['peak_rs']) for r in rows):,.0f} | last Rs {sum(_f(r['last_rs']) for r in rows):,.0f}", "",
                  "| day | stock | dir | time | filing | min ago | move 15m | volume x | ext ATR | VWAP dist | option | entry | peak % | last % | first | last Rs |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        lines += [f"| {r['day']} | {r['symbol']} | {str(r['direction'])[:4]} | {r['time']} | {r['filing']} | {r['filing_min_ago']} | {r['move_15m_pct']}% | {r['volume_x']} | {r['ext_atr']} | {r['vwap_dist_pct']}% | {r['strike']} {r['side']} | {r['entry']} | {r['peak_pct']} | {r['last_pct']} | {r['first']} | {r.get('last_rs') or '-'} |"
                  for r in rows]
    else:
        lines.append("No entries yet.")
    lines += ["", "Judge it only on forward days; the exception has to keep going after entry, not just show one big winner.", ""]
    return "\n".join(lines)


def run(days: Sequence[str], root: Path = ROOT) -> Path:
    path = root.joinpath(*FOLDER, "ledger.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in _read(path) if r.get("day") not in set(days)]
    for d in days:
        rows += [{k: ("" if v is None else v) for k, v in r.items()} for r in day_rows(d, root)]
    rows.sort(key=lambda r: (r["day"], r["time"]))
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=LEDGER_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    out = root.joinpath(*FOLDER, "review.md")
    out.write_text(render(rows), encoding="utf-8")
    return out


if __name__ == "__main__":
    ds = sys.argv[1:] or [datetime.now(IST).strftime("%Y-%m-%d")]
    print(run(ds))
    print(ROOT.joinpath(*FOLDER, "review.md").read_text(encoding="utf-8"))
