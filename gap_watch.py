"""Gap watch: what we can know before the open about tomorrow's gap (SHADOW ONLY: tags and a nightly review; nothing trades on it).

A stock's opening gap is mostly news after the close (results, orders, rating actions, a regulator) plus a small tendency to mean-revert after a stretched close. For every stock the watch combines, using ONLY
information available before 09:15 on the day:

    FILINGS   the filings published between the previous session's 15:30 and 09:15 (data/news_intelligence/announcements.jsonl), read by filing_text.py (keywords on the title and summary, and the numbers from
              the PDF where filing_pdf.py has read it: profit up / down 10 %+ on the year, a loss turning to profit ...): polarity +1 good for the share price, -1 bad. The latest filing with a view counts.
    STRETCH   where the previous session closed in its range (data/stock_study): at the high -> -0.5 (the next gap averaged -0.22 %, 44 % gapped down 0.3 %+ against 22 % up on 88 days of history), at the low
              -> +0.5 (+0.18 %), in between 0
    score = polarity + stretch;  watch direction +1 / -1 when |score| >= 0.5 (STRONG when >= 1: a filing view backed by the stretch or a view on its own, WEAK when the stretch is all there is)

    gw_dir          the direction the watch expects the gap in (+1 up, -1 down, 0 none)        gw_strength   STRONG / WEAK        gw_score   the number
    gw_with_trade   1 when the watch direction agrees with the trade (call = up), -1 when it opposes it, 0 no view            gw_filing   the polarity from filings, gw_kind its kind
    gw_big_risk     1 when the previous session was a LATE_SURGE (the 88-day history: 36 % of those stocks gap 1 %+ the next day against 17.6 % normally)

    data/gap_watch/ledger.csv    every (day, stock) the watch was scored with the gap that really came (the stock's own part: its gap minus the median stock's gap that morning)
    data/gap_watch/review.md     the nightly summary: did the watch direction beat the market's own coin flip, split by STRONG / WEAK and by what drove it

    python gap_watch.py          rebuild the ledger and the review now
"""

from __future__ import annotations

import csv
import json
import statistics as st
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
CLOSE_T = (15, 30)
OPEN_T = (9, 15)
STRETCH = 0.5
THRESH_WEAK, THRESH_STRONG = 0.5, 1.0
MIN_N = 20
LEDGER = ("data", "gap_watch", "ledger.csv")
FIELDS = ["day", "symbol", "score", "dir", "strength", "filing", "kind", "stretch", "late_surge", "gap_pct", "idio_gap"]
_ANN: dict[str, Any] = {"mtime": None, "rows": []}


def _announcements(root: Path) -> list[dict[str, Any]]:
    path = root / "data" / "news_intelligence" / "announcements.jsonl"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    if _ANN["mtime"] != mtime:
        rows = []
        try:
            with path.open(encoding="utf-8") as h:
                for line in h:
                    try:
                        r = json.loads(line)
                        r["_t"] = datetime.fromisoformat(str(r["published_at"]))
                        rows.append(r)
                    except (ValueError, KeyError):
                        continue
        except OSError:
            return []
        _ANN.update(mtime=mtime, rows=rows)
    return _ANN["rows"]


def filing_view(root: Path, symbol: str, start: datetime, end: datetime) -> tuple[int, str]:
    """(polarity, kind) of the latest filing with a view by `symbol` published in [start, end]; (0, '') when none."""
    import filing_text

    facts = filing_text._facts(root)
    best = None
    for r in _announcements(root):
        if r.get("symbol") != symbol or not (start <= r["_t"] <= end):
            continue
        kind, pol = filing_text.read(str(r.get("desc") or ""), str(r.get("text") or ""))
        f = facts.get(str(r.get("id"))) or {}
        if f.get("status") == "OK" and kind in ("OTHER", "RESULTS_UP", "RESULTS_DOWN"):
            kind, pol = filing_text.from_facts(f, kind, pol)
        if pol != 0 and (best is None or r["_t"] > best[0]):
            best = (r["_t"], pol, kind)
    return (best[1], best[2]) if best else (0, "")


def score(polarity: int, close_pos: float | None) -> tuple[float, int, str, float]:
    """(score, direction, strength, stretch part) from the filing polarity and where the last session closed in its range."""
    stretch = 0.0
    if close_pos is not None:
        stretch = -STRETCH if close_pos >= 0.9 else STRETCH if close_pos <= 0.1 else 0.0
    s = polarity + stretch
    direction = 1 if s >= THRESH_WEAK else -1 if s <= -THRESH_WEAK else 0
    strength = "" if direction == 0 else "STRONG" if abs(s) >= THRESH_STRONG else "WEAK"
    return s, direction, strength, stretch


def _window(prev_day: str, day: str) -> tuple[datetime, datetime]:
    p, d = date.fromisoformat(prev_day), date.fromisoformat(day)
    return (datetime(p.year, p.month, p.day, *CLOSE_T, tzinfo=IST), datetime(d.year, d.month, d.day, *OPEN_T, tzinfo=IST))


def tags(symbol: str, direction: str, now: datetime, root: Path = ROOT) -> dict[str, Any]:
    """gw_ tags for a candidate at (or after) the open: the watch for TODAY's gap from information published before 09:15."""
    try:
        prof = json.loads(root.joinpath("data", "stock_study", "profiles.json").read_text(encoding="utf-8"))["stocks"].get(symbol)
        if not prof:
            return {}
        t = prof["today"]
        prev_day = str(t["day"])
        if prev_day >= now.date().isoformat():
            return {}                                          # the profile already holds today's row: yesterday's session is no longer 'last'
        start, end = _window(prev_day, now.date().isoformat())
        pol, kind = filing_view(root, symbol, start, end)
        s, d, strength, stretch = score(pol, float(t.get("close_pos")) if t.get("close_pos") not in (None, "") else None)
        sign = 1 if str(direction).upper() == "BULLISH" else -1
        return {"gw_dir": d, "gw_strength": strength, "gw_score": round(s, 2), "gw_filing": pol, "gw_kind": kind, "gw_with_trade": 0 if d == 0 else (1 if d == sign else -1),
                "gw_big_risk": int(str(t.get("pattern")) == "LATE_SURGE")}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}


def _f(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_ledger(root: Path = ROOT) -> list[dict[str, Any]]:
    import stock_study

    rows = stock_study.read_daily(root)
    by_day: dict[str, dict[str, dict[str, Any]]] = {}
    for r in rows:
        by_day.setdefault(str(r["day"]), {})[str(r["symbol"])] = r
    days = sorted(by_day)
    out: list[dict[str, Any]] = []
    for prev_day, day in zip(days, days[1:]):
        gaps = [_f(r["gap_pct"]) for r in by_day[day].values() if _f(r["gap_pct"]) is not None]
        if len(gaps) < 50:
            continue
        med = st.median(gaps)
        start, end = _window(prev_day, day)
        for sym, r in by_day[day].items():
            p = by_day[prev_day].get(sym)
            g = _f(r["gap_pct"])
            if p is None or g is None:
                continue
            pol, kind = filing_view(root, sym, start, end)
            cp = _f(p["close_pos"])
            s, d, strength, stretch = score(pol, cp)
            out.append({"day": day, "symbol": sym, "score": round(s, 2), "dir": d, "strength": strength, "filing": pol, "kind": kind, "stretch": stretch, "late_surge": int(str(p["pattern"]) == "LATE_SURGE"),
                        "gap_pct": round(g, 3), "idio_gap": round(g - med, 3)})
    return out


def review(root: Path = ROOT) -> Path | None:
    rows = build_ledger(root)
    if not rows:
        return None
    folder = root / "data" / "gap_watch"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "ledger.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    def stats(g: Sequence[Mapping[str, Any]]) -> str:
        if not g:
            return "0 | - | - | - | -"
        sgn = [r["dir"] * r["idio_gap"] for r in g]                      # the gap in the watch's direction
        up = 100 * sum(1 for x in sgn if x > 0.3) / len(g)
        dn = 100 * sum(1 for x in sgn if x < -0.3) / len(g)
        return f"{len(g)} | {st.mean(sgn):+.2f}% | {up:.0f}% | {dn:.0f}% | {st.mean(abs(r['idio_gap']) for r in g):.2f}%"

    watched = [r for r in rows if r["dir"] != 0]
    days = sorted({r["day"] for r in rows})
    L = ["# Gap watch review (research only; nothing here trades)", "",
         f"{len(rows)} stock-days over {len(days)} days ({days[0]}..{days[-1]}); the watch had a direction on {len(watched)}. Gap in the watch's direction = the stock's gap minus the median stock's gap that morning, "
         "signed so that positive = the gap the watch expected. 'Right' = 0.3 %+ that way, 'wrong' = 0.3 %+ the other way. Filings come from the announcement feed (kept since about 13 Oct), so filing-driven rows are few.", "",
         "| Group | Stock-days | Mean gap in the watch direction | Gap came the right way (0.3 %+) | Gap came the wrong way | Mean absolute gap |", "|---|---|---|---|---|---|"]
    groups = [("All watched", watched), ("STRONG", [r for r in watched if r["strength"] == "STRONG"]), ("WEAK (stretch only)", [r for r in watched if r["strength"] == "WEAK"]),
              ("Filing view good (+1)", [r for r in rows if r["filing"] == 1]), ("Filing view bad (-1)", [r for r in rows if r["filing"] == -1]),
              ("Closed at the high yesterday", [r for r in rows if r["stretch"] < 0]), ("Closed at the low yesterday", [r for r in rows if r["stretch"] > 0])]
    for name, g in groups:
        if name.startswith("Filing view") or name.startswith("Closed"):
            sgn = [(1 if (name.endswith("(+1)") or name.endswith("low yesterday")) else -1) * r["idio_gap"] for r in g]
            n = len(g)
            L.append(f"| {name} | {n} | {(st.mean(sgn) if n else 0):+.2f}% | {(100 * sum(1 for x in sgn if x > 0.3) / n if n else 0):.0f}% | {(100 * sum(1 for x in sgn if x < -0.3) / n if n else 0):.0f}% | "
                     f"{(st.mean(abs(r['idio_gap']) for r in g) if n else 0):.2f}% |")
        else:
            L.append(f"| {name} | {stats(g)} |")
    base = [abs(r["idio_gap"]) for r in rows]
    surge = [abs(r["idio_gap"]) for r in rows if r["late_surge"]]
    L += ["", f"All stock-days: mean absolute stock-specific gap {st.mean(base):.2f}%. After a LATE_SURGE session: {st.mean(surge) if surge else 0:.2f}% over {len(surge)} stock-days.", "",
          f"A verdict needs at least {MIN_N} STRONG watches over several days; so far {len(groups[1][1])}."]
    out = folder / "review.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    return out


def run(day: str, root: Path = ROOT) -> None:
    review(root)


def main() -> int:
    print(review(ROOT) or "nothing to review (run stock_study.py backfill first)")
    return 0


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
