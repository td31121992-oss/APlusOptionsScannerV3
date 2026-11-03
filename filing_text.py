"""What a company filing SAYS, not just what it is called (SHADOW tags: never blocks or changes a trade).

announcement_feed.py grades a filing HIGH / MEDIUM / LOW from its title (the "desc": "Outcome of Board Meeting", "Press Release" ...). The title alone cannot say whether the news is good: a board
meeting can approve a buyback or a fund raise, a press release can announce an order or a fraud. NSE also gives a short summary text with every filing (up to 400 characters, kept in
data/news_intelligence/announcements.jsonl); this reads title + summary with plain keyword rules and records, for the stock being considered:

    fl_kind          what it is: ORDER_WIN, RESULTS_UP, RESULTS_DOWN, BUYBACK, DIVIDEND, BONUS_SPLIT, FUND_RAISE, ACQUISITION, RESULTS_FLAT, RATING_UP, RATING_DOWN, REGULATORY_ACTION, FRAUD_DEFAULT, KEY_EXIT,
                     CAPACITY, FDA_NEGATIVE, FDA_POSITIVE, TAX_DEMAND, OTHER (the newest filing with a view; blank when no such filing in the last 24 hours)
    fl_polarity      +1 good for the share price, -1 bad, 0 no view from the words
    fl_amount_cr     a rupee amount in the text, in crore, when one is stated (order size, fund raise ...)
    fl_age_min       minutes since the filing was published
    fl_aligned       1 when the polarity agrees with the trade direction (+1 for a call, -1 for a put), 0 when it disagrees; blank when there is no view
    fl_n_24h         filings by this company in the last 24 hours

Where the filing's PDF has been read (filing_pdf.py, run after each announcement poll) its numbers replace the keyword guess for results: fl_pat_yoy / fl_pat_qoq / fl_rev_yoy (% change), fl_pat_turnaround
(loss_to_profit / profit_to_loss) and fl_amount_cr from an order letter; profit after tax up 10 %+ on the year (revenue not falling) is RESULTS_UP, down 10 %+ RESULTS_DOWN, otherwise RESULTS_FLAT.

Limits, stated plainly: the words are keyword matches on a 400-character summary, and the PDF numbers come from plain text extraction of a table, so they are approximate and a scanned or oddly laid-out
filing gives none. The nightly scoreboard splits trades by fl_aligned so we can see whether any of it helps.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
STORE = ("data", "news_intelligence", "announcements.jsonl")
HOURS = 24
_CACHE: dict[str, Any] = {"mtime": None, "path": None, "rows": []}

# (kind, polarity, regex on lower-cased "title summary"). Checked in order; the first match wins, so the specific / severe ones come first.
RULES: list[tuple[str, int, re.Pattern[str]]] = [(k, p, re.compile(rx)) for k, p, rx in [
    ("FRAUD_DEFAULT", -1, r"\bfraud|\bdefault(ed|s)? (on|in) (payment|repayment|interest|its)|\bnclt\b.{0,40}(admit|commenc).{0,40}(against the company|the company)|forensic audit|siphon|embezzle|money laundering|search and seizure|\bcbi\b"),
    ("FDA_NEGATIVE", -1, r"form 483|warning letter|\boai\b|import alert|observations? (issued|by).{0,30}(usfda|fda)|usfda.{0,40}observation"),
    ("REGULATORY_ACTION", -1, r"show cause|penalty|penalt(ies)? (of|imposed)|fine of|order(s)? passed.{0,40}(sebi|rbi|nclt|cci)|sebi order|rbi (imposed|action)|ban on (trading|operations|sale)|suspend(ed)? (the )?(license|licence|operations)"),
    ("TAX_DEMAND", -1, r"(gst|income tax|customs|tax) (demand|notice|order|assessment).{0,60}(crore|cr\b|lakh|rs)|demand notice|demand of rs"),
    ("KEY_EXIT", -1, r"resign(ed|ation)? .{0,40}(ceo|cfo|md\b|managing director|chief|chairman|auditor)|(ceo|cfo|managing director|chief .{0,20}officer|auditor).{0,40}resign|cessation of (ceo|cfo|managing)"),
    ("RATING_DOWN", -1, r"(rating|outlook).{0,50}(downgrade|lowered|revised downward|negative|watch with negative)|downgrade[sd]?.{0,40}rating"),
    ("RATING_UP", 1, r"(rating|outlook).{0,50}(upgrade|raised|revised upward|positive)|upgrade[sd]?.{0,40}rating"),
    ("FDA_POSITIVE", 1, r"(usfda|us fda).{0,40}(approv|nod|clearance)|(approv|nod).{0,40}(usfda|us fda)|eir received|no (action indicated|nai)\b|\bnai\b status"),
    ("ORDER_WIN", 1, r"bagging|receiving of order|received.{0,30}(order|contract|loa|letter of award)|letter of (award|intent)|order(s)? (worth|valued|of|for)|secured.{0,30}(order|contract)|awarded.{0,30}(order|contract)|\bwon\b.{0,30}(order|contract|bid)"),
    ("BUYBACK", 1, r"buy ?back"),
    ("BONUS_SPLIT", 1, r"\bbonus (issue|shares)|sub-?division|stock split|split of (equity|face)"),
    ("CAPACITY", 1, r"capacity expansion|capex|commission(ed|ing) of (the )?(new )?(plant|unit|line)|new (plant|facility|unit) (commenc|start)|commercial production"),
    ("FUND_RAISE", -1, r"qualified institutions? placement|\bqip\b|preferential (issue|allot)|rights issue|fund ?raising|rais(e|ing) (of )?(funds|capital)|issue of (equity|shares) (on|via) preferential"),
    ("ACQUISITION", 0, r"acquisition|acquire|amalgamation|merger|demerger|scheme of arrangement|takeover|open offer"),
    ("DIVIDEND", 1, r"(interim|final|special) dividend|declar(ed|ation of) .{0,20}dividend|dividend of rs"),
    ("RESULTS_UP", 1, r"(net profit|profit after tax|pat|revenue|net sales|total income|ebitda).{0,70}(increase|increased|rose|grew|growth|up by|higher|improv|jump|surge|record)|\b(record|highest)\b.{0,30}(profit|revenue)"),
    ("RESULTS_DOWN", -1, r"(net profit|profit after tax|pat|revenue|net sales|total income|ebitda).{0,70}(decrease|decreased|declin|fell|fall|down by|lower|drop|loss|dipped)|net loss|(loss|losses) (for|during) the (quarter|year|period|half)"),
]]
AMOUNT = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(crore|cr\b|lakh|lac|million|mn|billion|bn)?", re.I)


def amount_cr(text: str) -> float | None:
    """The largest rupee amount in the text, converted to crore (1 crore = 10 million = 100 lakh), None when there is none."""
    best = None
    for m in AMOUNT.finditer(text or ""):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = (m.group(2) or "").lower()
        cr = v if unit in ("crore", "cr") else v / 100.0 if unit in ("lakh", "lac") else v / 10.0 if unit in ("million", "mn") else v * 100.0 if unit in ("billion", "bn") else v / 1e7
        if best is None or cr > best:
            best = cr
    return None if best is None else round(best, 2)


def read(desc: str, text: str = "") -> tuple[str, int]:
    """(kind, polarity) for one filing; ('OTHER', 0) when no rule matches."""
    if "monitoring agency" in (desc or "").lower():                 # a report on how an earlier raise was spent, not a new raise
        return "OTHER", 0
    s = f"{desc or ''} {text or ''}".lower()
    for kind, pol, rx in RULES:
        if rx.search(s):
            return kind, pol
    return "OTHER", 0


def _rows(root: Path) -> list[dict[str, Any]]:
    path = root.joinpath(*STORE)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    if _CACHE["mtime"] != mtime or _CACHE["path"] != str(path):
        rows = []
        try:
            with path.open(encoding="utf-8") as h:
                for line in h.readlines()[-6000:]:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            return []
        _CACHE.update(mtime=mtime, path=str(path), rows=rows)
    return _CACHE["rows"]


PAT_MOVE_PCT = 10.0            # profit after tax up / down this much on the year (and revenue not falling) is called good / bad news
_FACTS: dict[str, Any] = {"mtime": None, "path": None, "data": {}}


def _facts(root: Path) -> dict[str, dict[str, Any]]:
    """Numbers read from the filings' PDFs (filing_pdf.py), by announcement id; cached until the file changes."""
    path = root / "data" / "news_intelligence" / "pdf_facts.jsonl"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _FACTS["mtime"] != mtime or _FACTS["path"] != str(path):
        import filing_pdf

        _FACTS.update(mtime=mtime, path=str(path), data=filing_pdf.load_facts(root))
    return _FACTS["data"]


def from_facts(f: Mapping[str, Any], kind: str, pol: int) -> tuple[str, int]:
    """Results kind and polarity from the PDF's numbers: profit after tax up / down 10 %+ on the year, a loss turning to profit / profit to loss. Unchanged when the PDF had no usable table."""
    yoy, rev, turn = f.get("pat_yoy_pct"), f.get("revenue_yoy_pct"), f.get("pat_turnaround")
    if turn == "loss_to_profit" or (yoy is not None and yoy >= PAT_MOVE_PCT and (rev is None or rev > -5)):
        return "RESULTS_UP", 1
    if turn == "profit_to_loss" or (yoy is not None and yoy <= -PAT_MOVE_PCT):
        return "RESULTS_DOWN", -1
    if yoy is not None or rev is not None:
        return "RESULTS_FLAT", 0
    return kind, pol


def tags(symbol: str, direction: str, now: datetime, root: Path = ROOT) -> dict[str, Any]:
    """The fl_ tags for a candidate. {} when the stock has no filing in the last 24 hours (or the store is missing)."""
    try:
        now = now if now.tzinfo else now.replace(tzinfo=IST)
        mine = []
        for r in _rows(root):
            if str(r.get("symbol") or "").upper() != symbol.upper():
                continue
            try:
                when = datetime.fromisoformat(str(r["published_at"]))
            except (KeyError, ValueError):
                continue
            if timedelta(0) <= now - when <= timedelta(hours=HOURS):
                mine.append((when, r))
        if not mine:
            return {}
        mine.sort(key=lambda x: x[0], reverse=True)
        facts = _facts(root)
        reads = []
        for w, r in mine:
            kind, pol = read(str(r.get("desc") or ""), str(r.get("text") or ""))
            f = facts.get(str(r.get("id"))) or {}
            if f.get("status") == "OK" and kind in ("OTHER", "RESULTS_UP", "RESULTS_DOWN"):
                kind, pol = from_facts(f, kind, pol)
            reads.append((w, r, kind, pol, f))
        pick = next((x for x in reads if x[3] != 0), None) or next((x for x in reads if x[2] != "OTHER"), None)
        out: dict[str, Any] = {"fl_n_24h": len(mine)}
        if pick is None:
            return out
        when, r, kind, pol, f = pick
        out.update(fl_kind=kind, fl_polarity=pol, fl_age_min=int((now - when).total_seconds() // 60))
        for src, dst in (("pat_yoy_pct", "fl_pat_yoy"), ("pat_qoq_pct", "fl_pat_qoq"), ("revenue_yoy_pct", "fl_rev_yoy"), ("pat_turnaround", "fl_pat_turnaround")):
            if f.get(src) is not None:
                out[dst] = f[src]
        amt = f.get("order_cr")
        if amt is None:
            amt = amount_cr(f"{r.get('desc') or ''} {r.get('text') or ''}")
        if amt is not None:
            out["fl_amount_cr"] = amt
        if pol != 0:
            out["fl_aligned"] = int((pol > 0) == (str(direction).upper() == "BULLISH"))
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}
