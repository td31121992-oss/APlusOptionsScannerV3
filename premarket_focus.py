"""Pre-market focus list: what the overnight and after-market news says, ready before the 09:15 open (READ-ONLY; display, Telegram and shadow tags - never a trade rule).

Built at 08:50 on trading days from what the system already collects:
    catalyst.bulk()                       news + NSE filings of the last 48 hours turned into a direction / confidence / type per stock (catalyst.py)
    data/safety/corporate_events.csv      results and board meetings due today, and the day before (after-hours results react at today's open)
    data/safety/announcement_events.csv   live NSE announcements

    data/news_focus/<day>.json   latest.json          the list, for the dashboard page /focus and the entry tags (nf_rank, nf_dir)
    Telegram                                          one message at 08:50 (the same text as the page)

Why it is a "where to look" list and not a trade rule: a first replay of the mornings gave encouraging numbers, but it let later news leak into earlier mornings (fixed in
catalyst.py on 17 Oct 2026), so those numbers were thrown away. Without the leak only 15 stock-days of clean history exist, which is too few to say anything. Friday 16 Oct
as it would have looked at 08:50: BHEL, ANGELONE, IRFC and TECHM flagged UP; TECHM rose 8.5% but ANGELONE (profit +45%) fell 4%, and WIPRO's results were not classified at all.
So the list says where to look; the open (gap and volume) decides whether the market is accepting the news. nightly reports will measure the hit rate from now on.

    python premarket_focus.py [--dry-run] [--force] [--day YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
TOP_N = 15
CONF_W = {"HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.2}
TYPE_BONUS = {"RESULTS": 1.0, "ORDER_WIN": 0.6, "RATING": 0.4, "CORPORATE_ACTION": 0.3, "REGULATORY": 0.6, "M_AND_A": 0.4}
CAUTION = "News says where to look. Trade only if the 09:15-09:25 gap and volume agree with it."


def _events(root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for name in ("corporate_events.csv", "announcement_events.csv"):
        p = root / "data" / "safety" / name
        try:
            with p.open(encoding="utf-8-sig", newline="") as h:
                rows += list(csv.DictReader(h))
        except OSError:
            continue
    return rows


def previous_day(day: str, root: Path) -> str | None:
    try:
        from trading_calendar import is_trading_day

        d = date.fromisoformat(day) - timedelta(days=1)
        for _ in range(7):
            if is_trading_day(d)[0]:
                return d.isoformat()
            d -= timedelta(days=1)
    except Exception:                                      # noqa: BLE001
        pass
    d = date.fromisoformat(day) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def rank_score(c: dict[str, Any]) -> float:
    base = abs(float(c.get("score") or 0.0)) * CONF_W.get(str(c.get("confidence")), 0.2)
    return round(base + TYPE_BONUS.get(str(c.get("type")), 0.0) + (0.5 if c.get("event_risk") else 0.0), 2)


def build(day: str | None = None, root: Path = ROOT, now: datetime | None = None, bulk_fn: Callable[..., dict] | None = None,
          items_fn: Callable[..., dict] | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    now = now or datetime.fromisoformat(f"{day}T08:50:00").replace(tzinfo=IST)
    sys.path.insert(0, str(root))
    import catalyst

    reads = (bulk_fn or catalyst.bulk)(root, now)
    prev = previous_day(day, root)
    ev_today: dict[str, dict[str, str]] = {}
    ev_prev: dict[str, dict[str, str]] = {}
    for r in _events(root):
        sym, ed = str(r.get("symbol", "")).strip().upper(), str(r.get("event_date", ""))
        if "RESULT" not in str(r.get("event_type", "")).upper():
            continue
        if ed == day:
            ev_today[sym] = r
        elif prev and ed == prev:
            ev_prev[sym] = r
    focus = []
    for sym, c in reads.items():
        if c.get("direction") not in ("BULLISH", "BEARISH") or c.get("confidence") not in ("HIGH", "MEDIUM"):
            continue
        focus.append({"symbol": sym, "direction": c["direction"], "confidence": c["confidence"], "type": c.get("type", ""), "age_h": c.get("age_h"),
                      "score": c.get("score"), "event_risk": bool(c.get("event_risk")), "rank_score": rank_score(c),
                      "results_today": sym in ev_today, "results_yesterday": sym in ev_prev})
    focus.sort(key=lambda x: -x["rank_score"])
    focus = focus[:TOP_N]
    for i, f in enumerate(focus, 1):
        f["rank"] = i
        try:
            items = (items_fn or catalyst.for_symbol)(f["symbol"], root, now)
            f["headline"] = next((it["title"] for it in items.get("items", []) if it.get("dir")), "")[:140]
        except Exception:                                  # noqa: BLE001
            f["headline"] = ""
    in_focus = {f["symbol"] for f in focus}
    mixed = [{"symbol": s, "direction": c["direction"], "type": c.get("type", "")} for s, c in reads.items()
             if c.get("direction") == "MIXED" and s not in in_focus][:8]
    return {"day": day, "built_at": now.isoformat(timespec="minutes"), "previous_day": prev, "caution": CAUTION, "focus": focus, "mixed": mixed,
            "results_today": sorted(ev_today), "results_prev_evening": sorted(s for s in ev_prev if s not in in_focus)}


def telegram_text(p: dict[str, Any]) -> str:
    d = datetime.fromisoformat(p["day"]).strftime("%a %d %b")
    out = [f"\U0001F50E PRE-MARKET FOCUS - {d}", "", p["caution"], ""]
    if not p["focus"]:
        out.append("No stock has a clear overnight news direction.")
    for f in p["focus"]:
        arrow = "\U0001F7E2 UP" if f["direction"] == "BULLISH" else "\U0001F534 DOWN"
        tag = " [RESULTS TODAY]" if f["results_today"] else (" [RESULTS LAST EVENING]" if f["results_yesterday"] else "")
        age = "" if f.get("age_h") is None else f", {f['age_h']:.0f}h ago"
        out.append(f"{f['rank']}. {f['symbol']} {arrow} ({f['confidence'].title()}, {str(f['type']).replace('_', ' ').lower()}{age}){tag}")
        if f.get("headline"):
            out.append(f"   {f['headline']}")
    if p["results_today"]:
        out += ["", "Results due today: " + ", ".join(p["results_today"][:30])]
    if p["results_prev_evening"]:
        out += ["", "Results last evening (reacts at today's open): " + ", ".join(p["results_prev_evening"][:30])]
    if p["mixed"]:
        out += ["", "Conflicting news: " + ", ".join(m["symbol"] for m in p["mixed"])]
    return "\n".join(out)[:3900]


def save(p: dict[str, Any], root: Path = ROOT) -> Path:
    folder = root / "data" / "news_focus"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{p['day']}.json"
    text = json.dumps(p, ensure_ascii=False, indent=1)
    path.write_text(text, encoding="utf-8")
    (folder / "latest.json").write_text(text, encoding="utf-8")
    return path


def payload(root: Path = ROOT) -> dict[str, Any]:
    try:
        return {"ok": True, **json.loads((root / "data" / "news_focus" / "latest.json").read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        try:
            return {"ok": True, **build(None, root, datetime.now(IST))}
        except Exception as exc:                           # noqa: BLE001
            return {"ok": False, "error": type(exc).__name__, "focus": []}


def entry_tags(symbol: str, direction: str, root: Path = ROOT) -> dict[str, Any]:
    """Shadow tags for a trade: was the stock on today's focus list, at what rank, and did the trade agree with the news direction."""
    try:
        p = json.loads((root / "data" / "news_focus" / "latest.json").read_text(encoding="utf-8"))
        if p.get("day") != date.today().isoformat():
            return {}
        for f in p.get("focus", []):
            if f["symbol"] == symbol.strip().upper():
                bull = str(direction).upper() == "BULLISH"
                return {"nf_rank": f["rank"], "nf_dir": f["direction"], "nf_aligned": bool((f["direction"] == "BULLISH") == bull)}
        return {"nf_rank": 0}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}


def review(day: str, root: Path = ROOT) -> Path | None:
    """Nightly: how did the stocks on this morning's list do? gap in the news direction, open->close and 09:25->close (stock moves, no options), appended to
    data/shadow_rules/news_focus_review.md. The hit rate is what decides whether the list is ever more than 'where to look'."""
    import glob
    import statistics as st

    try:
        p = json.loads((root / "data" / "news_focus" / f"{day}.json").read_text(encoding="utf-8"))
        cur = json.loads((root / "data" / "pattern_log" / "candles" / f"{day}.json").read_text(encoding="utf-8")).get("symbols", {})
    except (OSError, ValueError):
        return None
    prev_days = sorted(Path(x).stem for x in glob.glob(str(root / "data" / "pattern_log" / "candles" / "20*.json")) if Path(x).stem < day)
    prev: dict[str, Any] = {}
    if prev_days:
        try:
            prev = json.loads((root / "data" / "pattern_log" / "candles" / f"{prev_days[-1]}.json").read_text(encoding="utf-8")).get("symbols", {})
        except (OSError, ValueError):
            prev = {}
    rows = []
    for f in p.get("focus", []):
        d, pv = cur.get(f["symbol"]), prev.get(f["symbol"])
        if not d or not d.get("close") or not pv or not pv.get("close"):
            continue
        sg = 1 if f["direction"] == "BULLISH" else -1
        o, c, pc_ = float(d["open"][0]), float(d["close"][-1]), float(pv["close"][-1])
        idx = [i for i, m in enumerate(d["minute"]) if m <= 9 * 60 + 25]
        p0 = float(d["close"][idx[-1]]) if idx else o
        rows.append({"symbol": f["symbol"], "dir": f["direction"], "conf": f["confidence"], "type": f["type"], "gap": sg * (o / pc_ - 1) * 100,
                     "oc": sg * (c / o - 1) * 100, "from925": sg * (c / p0 - 1) * 100})
    if not rows:
        return None
    path = root / "data" / "shadow_rules" / "news_focus_review.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    head = ("# Pre-market focus: how the listed stocks did (stock moves in the news direction; research only)\n\n"
            "| Day | Listed | Gap agreed (>0.3%) | Mean open to close | Closed in the news direction | Mean 09:25 to close |\n|---|---|---|---|---|---|\n")
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = [ln for ln in old.splitlines() if ln.startswith("| 20") and not ln.startswith(f"| {day} ")]
    n = len(rows)
    lines.append(f"| {day} | {n} | {sum(r['gap'] > 0.3 for r in rows)} of {n} | {st.mean(r['oc'] for r in rows):+.2f}% | {sum(r['oc'] > 0 for r in rows)} of {n} | {st.mean(r['from925'] for r in rows):+.2f}% |")
    path.write_text(head + "\n".join(sorted(lines)) + "\n\n_Hindsight; a stock-move check only, not an option result._\n", encoding="utf-8")
    return path


FOCUS_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>APlus Pre-market Focus</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0b1020;--panel:#121a2d;--line:#27334d;--text:#e7eefc;--muted:#8ea0bd;--green:#19d38a;--red:#ff4d6a;--amber:#f5b942}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 -apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:12px 14px 40px}a{color:#4c8dff;text-decoration:none;font-weight:700}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px;margin:10px 0}.muted{color:var(--muted)}
.row{display:flex;gap:10px;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--line)}.row:last-child{border:0}
.sym{font-weight:900;min-width:110px}.up{color:var(--green)}.dn{color:var(--red)}.tag{background:#2b3552;border-radius:6px;padding:1px 7px;font-size:11px;margin-left:6px;color:var(--amber)}
.hl{color:var(--muted);font-size:12.5px;display:block;margin-top:2px}
</style></head><body><div class="wrap">
<div><a href="/">&larr; Dashboard</a> &nbsp; <a href="/premium">Premium Tracker</a> &nbsp; <a href="/xray">Market X-Ray</a></div>
<h1 style="margin:10px 0 0;font-size:24px">Pre-market focus</h1><div class="muted" id="sub">loading...</div>
<div class="card" id="caution"></div><div class="card" id="list"></div><div class="card" id="extra"></div>
</div><script>
function esc(s){return String(s==null?"":s).replace(/[&<>]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;"}[c]})}
fetch("/api/premarket-focus",{cache:"no-store"}).then(function(r){return r.json()}).then(function(d){
 document.getElementById("sub").textContent=(d.day?"For "+d.day+" - built "+(d.built_at||""):"");
 document.getElementById("caution").innerHTML="<b>"+esc(d.caution||"")+"</b>";
 var f=d.focus||[];
 document.getElementById("list").innerHTML=f.length?f.map(function(x){var up=x.direction==="BULLISH";
  return '<div class="row"><span class="sym">'+x.rank+'. '+esc(x.symbol)+'</span><span class="'+(up?"up":"dn")+'"><b>'+(up?"UP (calls)":"DOWN (puts)")+'</b></span><span class="muted">'+esc(x.confidence)+' &middot; '+esc(String(x.type).replace("_"," ").toLowerCase())+(x.age_h!=null?" &middot; "+Math.round(x.age_h)+"h ago":"")+'</span>'
   +(x.results_today?'<span class="tag">results today</span>':'')+(x.results_yesterday?'<span class="tag">results last evening</span>':'')
   +(x.headline?'<span class="hl" style="flex-basis:100%">'+esc(x.headline)+'</span>':'')+'</div>'}).join(""):'<span class="muted">No stock has a clear overnight news direction.</span>';
 var e=[];if((d.results_today||[]).length)e.push("<b>Results due today:</b> "+d.results_today.map(esc).join(", "));
 if((d.results_prev_evening||[]).length)e.push("<b>Results last evening (react at today's open):</b> "+d.results_prev_evening.map(esc).join(", "));
 if((d.mixed||[]).length)e.push("<b>Conflicting news:</b> "+d.mixed.map(function(m){return esc(m.symbol)}).join(", "));
 document.getElementById("extra").innerHTML=e.join("<br><br>")||'<span class="muted">Nothing else flagged.</span>'});
</script></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="run on a non-trading day / send again")
    ap.add_argument("--day")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                      # noqa: BLE001
        pass
    sys.path.insert(0, str(ROOT))
    day = args.day or date.today().isoformat()
    if not args.force:
        from trading_calendar import is_trading_day

        if not is_trading_day(date.fromisoformat(day))[0]:
            print("not a trading day")
            return 0
        if (ROOT / "data" / "news_focus" / f"sent_{day}.flag").exists():
            print("already sent today")
            return 0
    p = build(day, ROOT)
    text = telegram_text(p)
    if args.dry_run:
        print(text)
        return 0
    print(save(p, ROOT))
    from announcement_feed import send_telegram

    ok, detail = send_telegram(text)
    print("sent" if ok else f"send failed: {detail}")
    if ok:
        (ROOT / "data" / "news_focus" / f"sent_{day}.flag").write_text(datetime.now(IST).isoformat(), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
