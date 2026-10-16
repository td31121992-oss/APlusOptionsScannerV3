"""Catalyst layer: Stock -> News -> Catalyst -> Direction -> Confidence -> Option impact (READ-ONLY, display + shadow tags).

It does not fetch anything. It reads what the two listeners already store:
    data/news_intelligence/announcements.jsonl   NSE corporate filings for F&O stocks (24x7 announcement service)
    data/news_intelligence/events.jsonl          headlines the news collector keeps per stock (category STOCK_<SYMBOL>)
and turns the items of the last 48 hours for one stock into a single read:

    direction    BULLISH | BEARISH | MIXED | NEUTRAL (nothing that matters)
    confidence   HIGH   a clear NSE filing, or two or more independent sources agreeing
                 MEDIUM one clear headline
                 LOW    weak or ambiguous wording
    type         the biggest catalyst: RESULTS, ORDER_WIN, RATING, REGULATORY, MANAGEMENT, CORPORATE_ACTION, FUNDRAISE, M_AND_A, EVENT
    event_risk   a results / board-meeting event is due or has just happened (option premiums carry event volatility)
    impact       plain-language option impact (which side the catalyst supports)

The classification is keyword rules, not a model: every item carries the rule that fired, so a reading can be checked by eye.
Older items count less (half weight every 24 hours). Routine filings (certificates, newspaper copies, ESOP, ...) are ignored.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
WINDOW_HOURS = 48
HALF_LIFE_H = 24.0
IST = timezone(timedelta(hours=5, minutes=30))

NOISE_DESC = ("certificate under sebi", "copy of newspaper publication", "esop", "shareholders meeting", "trading window", "loss of share",
              "duplicate share", "notice of", "compliance", "reg. 74", "reg 74", "disclosure under sebi", "voting results")

# (regex, type, direction, weight, label) - first match for the item wins. Order: most specific / most serious first.
RULES: list[tuple[str, str, int, float, str]] = [
    (r"fraud|default|arrest|insolvency|\bcirp\b|nclt|winding up|bankrupt", "REGULATORY", -1, 3.0, "fraud / default / insolvency"),
    (r"sebi (order|penalty|ban|probe|notice)|penalty|\bprobe\b|\braid\b|show.?cause|ed (raid|summons)|\bbanned\b|f&o ban", "REGULATORY", -1, 2.5, "regulatory action"),
    (r"profit warning|guidance cut|cuts? guidance|lowers? guidance|production halt|plant (shut|closure)|recall|fire at|disruption", "EVENT", -1, 2.5, "operational negative"),
    (r"net loss|loss widens|swings? to (a )?loss|slips? into loss", "RESULTS", -1, 3.0, "loss"),
    (r"(net )?profit (falls?|fell|declines?|declined|slumps?|drops?|dropped|dips?|plunges?|down|slides?|tumbles?|sinks?)|profit.{0,12}\bdown\b|"
     r"(revenue|sales|ebitda|margins?) (falls?|declines?|dips?|drops?|slips?|contracts?)|misses? (street |market )?estimates|below (street )?estimates|weak (q\d|results|quarter)",
     "RESULTS", -1, 3.0, "results weaker"),
    (r"(net )?profit (jumps?|rises?|rose|surges?|soars?|climbs?|grows?|up|spikes?|doubles?|more than doubles?)|profit.{0,12}\b(up|higher)\b|record (profit|revenue|quarter|sales)|"
     r"beats? (street |market )?estimates|above (street )?estimates|strong (q\d|results|quarter|earnings)|(revenue|sales|ebitda|margins?) (rises?|jumps?|surges?|grows?|expands?)",
     "RESULTS", 1, 3.0, "results stronger"),
    (r"downgrade|cuts? (target|rating)|target price (cut|lowered|reduced)|\bsell\b rating|underperform|reduce rating", "RATING", -1, 2.0, "rating cut"),
    (r"upgrade|raises? (target|rating)|target price (raised|hiked|increased)|initiates? coverage with (a )?buy|\bbuy\b rating|outperform|overweight", "RATING", 1, 2.0, "rating raised"),
    (r"bagging|receiving of order|awarding of order|wins? (an )?order|bags? (an )?order|order (worth|win|inflow)|letter of (intent|award)|secures? (an )?(order|contract)", "ORDER_WIN", 1, 2.5, "order win"),
    (r"buy ?back|bonus|stock split|sub-?division|special dividend|capacity expansion|capex (plan|approved)|new plant", "CORPORATE_ACTION", 1, 1.5, "shareholder-friendly / expansion"),
    (r"dividend", "CORPORATE_ACTION", 1, 0.8, "dividend"),
    (r"qualified institutional placement|\bqip\b|rights issue|preferential (issue|allotment)|fund raising|fund.?raise|stake sale|promoter (sells|pledge)", "FUNDRAISE", -1, 1.2, "dilution / stake sale"),
    (r"open offer|takeover", "M_AND_A", 1, 1.5, "takeover / open offer"),
    (r"acquisition|acquires?|amalgamation|merger|demerger|scheme of arrangement", "M_AND_A", 0, 1.0, "M&A (direction depends on the deal)"),
    (r"resign", "MANAGEMENT", -1, 1.5, "resignation"),
    (r"credit rating (upgrade|upgraded)|rating (upgraded|raised)", "RATING", 1, 1.0, "credit rating up"),
    (r"credit rating (downgrade|downgraded)|rating (downgraded|lowered)|outlook (negative|lowered)", "RATING", -1, 1.5, "credit rating down"),
]
EVENT_UPCOMING = re.compile(r"board meeting|to consider (and approve )?(the )?(unaudited |audited )?(standalone |consolidated )?(financial )?results|"
                            r"intimation of board|financial results for the (quarter|half|year)|earnings (call|date)|q\d ?fy\d+ results (on|date)", re.I)
RESULTS_DESC = re.compile(r"outcome of board meeting|financial results", re.I)
KEY_ROLE = re.compile(r"\b(ceo|cfo|md|managing director|chief|auditor|chairman)\b", re.I)


def _parse_time(value: Any) -> datetime | None:
    s = str(value or "").strip()
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=IST)
    except ValueError:
        pass
    try:
        d = parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def classify_text(text: str, desc: str = "") -> tuple[str, int, float, str] | None:
    """(type, direction, weight, label) or None when it is noise / nothing recognisable."""
    t = f"{desc} {text}".lower()
    if any(k in (desc or "").lower() for k in NOISE_DESC):
        return None
    for pattern, ctype, direction, weight, label in RULES:
        if re.search(pattern, t):
            if ctype == "MANAGEMENT" and not KEY_ROLE.search(t):
                weight = 0.6
            return ctype, direction, weight, label
    if RESULTS_DESC.search(desc or ""):
        return "RESULTS", 0, 1.0, "results / board outcome (read the filing)"
    return None


def _load_jsonl(path: Path, tail: int = 20000) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            lines = handle.readlines()[-tail:]
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


_CACHE: dict[str, Any] = {"key": None, "at": 0.0, "by": {}}


def _aliases(announcements: list[dict[str, Any]]) -> dict[str, set[str]]:
    """symbol -> lowercase name fragments that identify the company in a headline."""
    out: dict[str, set[str]] = {}
    for a in announcements:
        sym = str(a.get("symbol") or "").upper()
        name = re.sub(r"\b(limited|ltd\.?|corporation|corp\.?|industries|india|company|co\.?)\b", " ", str(a.get("company") or "").lower())
        words = [w for w in re.split(r"[^a-z0-9&]+", name) if len(w) >= 4]
        if sym:
            s = out.setdefault(sym, {sym.lower()})
            if words:
                s.add(" ".join(words[:2]))
                s.add(words[0])
    return out


def _items(root: Path, now: datetime) -> dict[str, list[dict[str, Any]]]:
    nd = root / "data" / "news_intelligence"
    key = None
    try:
        key = (nd / "announcements.jsonl").stat().st_mtime, (nd / "events.jsonl").stat().st_mtime
    except OSError:
        pass
    live = abs((datetime.now(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()) < 600     # a replay of an earlier moment must not use the live cache
    if live and _CACHE["key"] == key and key is not None and time.time() - _CACHE["at"] < 60:
        return _CACHE["by"]
    cutoff = now - timedelta(hours=WINDOW_HOURS)
    latest = now + timedelta(minutes=5)                       # nothing published after `now` can be known at `now`
    by: dict[str, list[dict[str, Any]]] = {}
    ann = _load_jsonl(nd / "announcements.jsonl")
    for a in ann:
        when = _parse_time(a.get("published_at"))
        sym = str(a.get("symbol") or "").upper()
        if not sym or when is None or when < cutoff or when > latest:
            continue
        desc, text = str(a.get("desc") or ""), str(a.get("text") or "")
        base = {"time": when, "source": "NSE filing", "kind": "FILING", "title": text or desc, "desc": desc, "url": str(a.get("url") or "")}
        c = classify_text(text, desc)
        upcoming = bool(EVENT_UPCOMING.search(f"{desc} {text}")) and not RESULTS_DESC.search(desc) and "outcome" not in desc.lower()
        if c:
            ctype, d, w, label = c
            by.setdefault(sym, []).append({**base, "type": ctype, "dir": d, "weight": w, "rule": label, "event": ctype == "RESULTS"})
        elif upcoming:
            by.setdefault(sym, []).append({**base, "type": "EVENT", "dir": 0, "weight": 0.0, "rule": "results / board meeting due", "event": True})
    alias = _aliases(ann)
    try:                                                     # the company-profile table knows every F&O name, filings or not
        import company_profiles

        for sym, prof in company_profiles.PROFILES.items():
            name = re.sub(r"\b(limited|ltd\.?|india|corporation|corp\.?|industries|company|co\.?)\b", " ", str(prof.get("name") or prof.get("company") or "").lower())
            words = [w for w in re.split(r"[^a-z0-9&]+", name) if len(w) >= 4]
            s = alias.setdefault(sym.upper(), {sym.lower()})
            if words:
                s.add(" ".join(words[:2]))
                s.add(words[0])
    except Exception:                                      # noqa: BLE001 - aliases from the filings still work
        pass
    for e in _load_jsonl(nd / "events.jsonl"):
        cat = str(e.get("category") or "")
        if not cat.startswith("STOCK_"):
            continue
        sym = cat[6:].upper()
        when = _parse_time(e.get("published_at_raw"))
        if when is None or when < cutoff or when > latest:
            continue
        title = re.sub(r"<[^>]+>", " ", str(e.get("title") or ""))
        names = alias.get(sym, {sym.lower()})
        if not any(n and n in title.lower() for n in names | {sym.lower()}):
            continue                                             # the search bucket returned a story about another company
        c = classify_text(title)
        src = str(e.get("source") or "news")
        base = {"time": when, "source": src, "kind": "HEADLINE", "title": title.strip(), "desc": "", "url": str(e.get("url") or "")}
        if c:
            ctype, d, w, label = c
            by.setdefault(sym, []).append({**base, "type": ctype, "dir": d, "weight": w, "rule": label, "event": ctype == "RESULTS"})
    for sym in by:
        by[sym].sort(key=lambda x: x["time"], reverse=True)
    if live:
        _CACHE.update({"key": key, "at": time.time(), "by": by})
    return by


def read(items: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Aggregate one stock's items into direction / confidence / type / impact."""
    if not items:
        return {"direction": "NEUTRAL", "confidence": "LOW", "type": "", "score": 0.0, "age_h": None, "event_risk": False,
                "impact": "No fresh catalyst in the last 48 hours.", "items": []}
    pos = neg = 0.0
    top = None
    for it in items:
        age_h = max(0.0, (now - it["time"]).total_seconds() / 3600.0)
        w = it["weight"] * (0.5 ** (age_h / HALF_LIFE_H))
        it["age_h"] = round(age_h, 1)
        it["eff"] = round(w, 2)
        if it["dir"] > 0:
            pos += w
        elif it["dir"] < 0:
            neg += w
        if top is None or w > top["eff"]:
            top = it
    clear_pos, clear_neg = pos >= 1.5, neg >= 1.5
    if clear_pos and clear_neg:
        direction = "MIXED"
    elif clear_pos:
        direction = "BULLISH"
    elif clear_neg:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"
    sides = {it["dir"] for it in items if it["dir"] and it["eff"] >= 0.5}
    sources = {it["source"] for it in items if it["dir"] and it["eff"] >= 0.5}
    filing_clear = any(it["kind"] == "FILING" and it["dir"] and it["eff"] >= 1.5 for it in items)
    if direction in ("BULLISH", "BEARISH"):
        agree = len(sides) == 1
        confidence = "HIGH" if (filing_clear and agree) or (agree and len(sources) >= 2 and max(pos, neg) >= 3) else "MEDIUM"
    elif direction == "MIXED":
        confidence = "LOW"
    else:
        confidence = "LOW"
    event_risk = any(it.get("event") and it["age_h"] <= 36 for it in items)
    newest = min(it["age_h"] for it in items)
    if direction == "BULLISH":
        impact = "Supports calls (CE). A put trade would be against the news."
    elif direction == "BEARISH":
        impact = "Supports puts (PE). A call trade would be against the news."
    elif direction == "MIXED":
        impact = "Conflicting news: no side is supported, expect a sharp but unreliable move."
    else:
        impact = "No directional catalyst."
    if event_risk:
        impact += " Results / board-meeting event is due or just out: premiums carry event volatility and can lose IV after the news."
    return {"direction": direction, "confidence": confidence, "type": (top or {}).get("type", ""), "score": round(pos - neg, 2),
            "age_h": newest, "event_risk": bool(event_risk), "impact": impact, "items": items}


def for_symbol(symbol: str, root: Path = ROOT, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(IST)
    r = read(_items(root, now).get(symbol.strip().upper(), []), now)
    out = {**r, "symbol": symbol.strip().upper(), "items": [
        {"time": it["time"].astimezone(IST).strftime("%d %b %H:%M"), "age_h": it["age_h"], "source": it["source"], "kind": it["kind"],
         "type": it["type"], "dir": it["dir"], "rule": it["rule"], "title": it["title"][:220], "url": it["url"]} for it in r["items"][:12]]}
    return out


def bulk(root: Path = ROOT, now: datetime | None = None) -> dict[str, dict[str, Any]]:
    """symbol -> compact read for every stock that has at least one classified item (market-watch chips, entry tags)."""
    now = now or datetime.now(IST)
    out = {}
    for sym, items in _items(root, now).items():
        r = read([dict(i) for i in items], now)
        if r["direction"] != "NEUTRAL" or r["event_risk"]:
            out[sym] = {"direction": r["direction"], "confidence": r["confidence"], "type": r["type"], "age_h": r["age_h"],
                        "event_risk": r["event_risk"], "score": r["score"]}
    return out


def attach(rows: list[dict[str, Any]], root: Path = ROOT) -> None:
    """Adds `catalyst` to every market-watch row that has one."""
    try:
        reads = bulk(root)
    except Exception:                                      # noqa: BLE001 - an extra column must never break the page
        return
    for r in rows:
        c = reads.get(str(r.get("symbol") or "").upper())
        if c:
            r["catalyst"] = c


def entry_tags(symbol: str, direction: str, root: Path = ROOT) -> dict[str, Any]:
    """Shadow tags at entry: what the news said when the trade was taken, and whether it agreed with the trade."""
    try:
        c = bulk(root).get(symbol.strip().upper())
        if not c:
            return {"cat_dir": "NONE"}
        bull = str(direction).upper() == "BULLISH"
        aligned = (c["direction"] == "BULLISH" and bull) or (c["direction"] == "BEARISH" and not bull)
        against = (c["direction"] == "BULLISH" and not bull) or (c["direction"] == "BEARISH" and bull)
        return {"cat_dir": c["direction"], "cat_conf": c["confidence"], "cat_type": c["type"], "cat_age_h": c["age_h"],
                "cat_event_risk": c["event_risk"], "cat_aligned": bool(aligned), "cat_against": bool(against)}
    except Exception:                                      # noqa: BLE001 - a shadow tag must never affect trading
        return {}
