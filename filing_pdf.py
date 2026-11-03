"""Read the attached PDF of a company filing and pull out the numbers (SHADOW support for filing_text.py; never touches a trade).

NSE's feed gives a title and a 400-character summary; the real content (the results table, the order value) is in the attached PDF. This downloads the PDFs of new board-meeting outcomes, order
announcements and press releases (only from nsearchives.nseindia.com, only https, at most MAX_MB, only the first PAGES pages are read), and records what it finds in
data/news_intelligence/pdf_facts.jsonl, one line per filing:

    revenue_yoy_pct / revenue_qoq_pct    revenue (or total income) of the latest quarter against the same quarter last year / the previous quarter, %
    pat_yoy_pct / pat_qoq_pct            profit after tax, same comparison;   pat_turnaround = "loss_to_profit" / "profit_to_loss" when the sign flips (no % is meaningful then)
    order_cr                              the largest rupee amount stated in the first pages, in crore (for order / contract filings)
    status                                OK, NO_TEXT (scanned image), NO_TABLE (no recognisable results table), TOO_BIG, FETCH_FAILED

The numbers come from plain text extraction of a table, so they are approximate: the first three figures on a "Revenue from operations" / "Net profit" row are taken as (this quarter, previous
quarter, same quarter last year), which is the order Indian listed companies use. A row that does not look like that, or a change beyond +-90 % (far more likely a misread column than a result),
is left out rather than guessed.  filing_text.tags() adds the figures to the fl_ tags.
"""

from __future__ import annotations

import io
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))
HOST = "nsearchives.nseindia.com"
MAX_MB, PAGES, TIMEOUT_S = 30, 30, 60
SANE = 90.0
FACTS = ("data", "news_intelligence", "pdf_facts.jsonl")
STORE = ("data", "news_intelligence", "announcements.jsonl")
WANT_DESC = ("outcome of board meeting", "bagging/receiving", "press release", "acquisition", "financial result")
NUM = re.compile(r"\(?-?\d[\d,]*\.?\d*\)?")
FORMULA = re.compile(r"\(\s*\d+\s*(?:[-+/]|\+/-)\s*\d+\s*\)")                    # '(5-6)', '(1-2)', '(3+/-4)': column references in the row label, not figures
SERIAL = re.compile(r"^\s*[0-9]{1,2}\s+")                                           # a leading row number
SPLIT_DECIMAL = re.compile(r"(\d) (\.\d{2})\b")                                     # '146,407 .30' -> '146,407.30'
LEAD = r"^\W*(?:\(\w\)\s*|\d{1,2}\s+)?"                                             # optional '(a)' or a row number before the label
REV_LABELS = [re.compile(LEAD + p, re.I) for p in (r"(?:total )?revenues? from operations", r"total revenue", r"total income", r"net sales", r"income from operations")]       # in order of preference
PAT_LABELS = [re.compile(LEAD + p, re.I) for p in (r"net profit.{0,45}?(?:after tax|for the (?:period|quarter|year))", r"net profit\s*/?\s*\(?loss\)?", r"net profit", r"profit\s*/?\s*\(?loss\)?\s*(?:after tax|for the)", r"profit after tax", r"profit for the")]
LABEL_END = re.compile(r"(?i)(?:revenue from operations|total revenue|total income|net sales|income from operations|net profit\s*/?\s*\(?loss\)?|net profit|profit after tax|profit\s*/?\s*\(?loss\)?\s*(?:after tax|for the)\s*(?:the )?(?:period|quarter|year)?|profit for the (?:period|quarter|year))")
SKIP_LINE = re.compile(r"(?i)per share|margin|%|before|attributable|comprehensive|\bratios?\b")


def _num(tok: str) -> float | None:
    neg = tok.startswith("(") and tok.endswith(")") or tok.lstrip("(").startswith("-")
    t = tok.strip("()").replace(",", "").lstrip("-")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _clean(line: str) -> str:
    """Undo common text-extraction damage: '{' for '(' (negative figures), a space before the decimals, formula references and the row number."""
    t = line.replace("{", "(").replace("[", "(").replace("}", ")").replace("]", ")")
    t = SPLIT_DECIMAL.sub(lambda m: m.group(1) + m.group(2), t).replace("Ne t ", "Net ")
    return SERIAL.sub("", FORMULA.sub(" ", t))


def _row_numbers(lines: list[str], i: int) -> list[float]:
    """Numbers on line i after its label, or on the next two lines when the label stands alone; needs at least three figures (this quarter, previous quarter, year ago)."""
    for j in (i, i + 1, i + 2):
        if j >= len(lines):
            break
        text = _clean(lines[j])
        if j == i:
            m = LABEL_END.search(text)
            text = text[m.end():] if m else text
        elif re.search(r"[A-Za-z]{3,}", text):             # the next line is another row (a sub-item), not this row's figures
            break
        vals = [v for v in (_num(t) for t in NUM.findall(text)) if v is not None]
        if len(vals) >= 3:
            return vals
    return []


def _pct(cur: float, base: float) -> float | None:
    """% change against a positive base; None for a zero / negative base (a turnaround has no meaningful %)."""
    if base <= 0:
        return None
    return round((cur / base - 1.0) * 100.0, 1)


def parse_results(text: str) -> dict[str, Any]:
    """Revenue and profit growth from the text of a results filing. {} when no recognisable table. The label must start the row, so 'Other Operating Revenue' and ratio rows are skipped."""
    lines = [" ".join(ln.split()) for ln in text.splitlines() if ln.strip()]
    out: dict[str, Any] = {}
    for key, labels in (("revenue", REV_LABELS), ("pat", PAT_LABELS)):
        done = False
        for rx in labels:
            for i, ln in enumerate(lines):
                if not rx.search(_clean(ln)) or SKIP_LINE.search(ln):
                    continue
                v = _row_numbers(lines, i)
                if len(v) < 3:
                    continue
                cur, prev, year = v[0], v[1], v[2]
                yoy, qoq = _pct(cur, year), _pct(cur, prev)
                if (yoy is not None and abs(yoy) > SANE) or (qoq is not None and abs(qoq) > SANE):
                    continue
                if key == "pat":
                    out["pat_cur"] = cur
                    if year < 0 < cur:
                        out["pat_turnaround"] = "loss_to_profit"
                    elif cur < 0 < year:
                        out["pat_turnaround"] = "profit_to_loss"
                if yoy is None and qoq is None and not out.get("pat_turnaround"):
                    continue
                if yoy is not None:
                    out[f"{key}_yoy_pct"] = yoy
                if qoq is not None:
                    out[f"{key}_qoq_pct"] = qoq
                done = True
                break
            if done:
                break
    return out


def extract_text(content: bytes, pages: int = PAGES) -> str:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(content))
    return "\n".join((reader.pages[i].extract_text() or "") for i in range(min(pages, len(reader.pages))))


def fetch(url: str, session: Any = None, max_mb: int = MAX_MB) -> tuple[bytes | None, str]:
    """(pdf bytes, status). Refuses anything but https on the NSE archive host; stops at max_mb."""
    p = urlparse(url)
    if p.scheme != "https" or p.hostname != HOST or not p.path.lower().endswith(".pdf"):
        return None, "FETCH_FAILED"
    import requests

    s = session or requests
    try:
        r = s.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT_S, stream=True)
        if r.status_code != 200:
            return None, "FETCH_FAILED"
        size = int(r.headers.get("content-length") or 0)
        if size > max_mb * 1024 * 1024:
            return None, "TOO_BIG"
        buf = bytearray()
        for chunk in r.iter_content(1 << 20):
            buf += chunk
            if len(buf) > max_mb * 1024 * 1024:
                return None, "TOO_BIG"
        return bytes(buf), "OK"
    except Exception:                                      # noqa: BLE001
        return None, "FETCH_FAILED"


def read_filing(url: str, desc: str = "", session: Any = None) -> dict[str, Any]:
    content, status = fetch(url, session)
    if content is None:
        return {"status": status}
    try:
        text = extract_text(content)
    except Exception:                                      # noqa: BLE001 - a broken PDF is just "no text"
        return {"status": "NO_TEXT"}
    if len(text.strip()) < 80:
        return {"status": "NO_TEXT"}
    facts: dict[str, Any] = {"status": "OK"}
    d = desc.lower()
    if "bagging" in d or "order" in d or "contract" in d:
        import filing_text

        amt = filing_text.amount_cr(text)
        if amt is not None:
            facts["order_cr"] = amt
    res = parse_results(text)
    if res:
        facts.update(res)
    elif "outcome" in d and re.search(r"(?i)financial results|unaudited|audited", text):
        facts["status"] = "TABLE_UNALIGNED" if unaligned_table(text) else "NO_TABLE"
    return facts


def unaligned_table(text: str) -> bool:
    """A results table whose text layer comes out column by column (a scanned bank filing read by OCR: AU Small Finance Bank, 24 Oct 2026): a 'Particulars' header, a block of row labels, then
    a separate block of figures, so no line holds a label with its numbers and the row parser cannot work. Recorded as its own status so it reads as 'unreadable', not 'no results table'."""
    figures = len(re.findall(r"\d[\d,]*\.\d{2}", text))
    aligned = sum(1 for line in text.splitlines() if re.search(r"[A-Za-z]{4}", line) and len(re.findall(r"\d[\d,]*\.\d{2}", line)) >= 3)
    return "particulars" in text.lower() and figures >= 60 and aligned <= 2


def load_facts(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    try:
        with root.joinpath(*FACTS).open(encoding="utf-8") as h:
            for line in h:
                try:
                    d = json.loads(line)
                    out[d["id"]] = d
                except (ValueError, KeyError):
                    continue
    except OSError:
        pass
    return out


def process_new(root: Path = ROOT, limit: int = 4, now: datetime | None = None, session: Any = None, max_age_days: int = 3) -> int:
    """Read the PDFs of up to `limit` recent filings not read yet (newest first). Returns how many were processed. Meant to run after each announcement poll."""
    now = now or datetime.now(IST)
    done = load_facts(root)
    try:
        with root.joinpath(*STORE).open(encoding="utf-8") as h:
            rows = [json.loads(x) for x in h.readlines()[-3000:] if x.strip()]
    except (OSError, ValueError):
        return 0
    todo = []
    for r in rows:
        try:
            when = datetime.fromisoformat(str(r["published_at"]))
        except (KeyError, ValueError):
            continue
        d = str(r.get("desc") or "").lower()
        if r.get("id") in done or not str(r.get("url") or "").lower().endswith(".pdf") or now - when > timedelta(days=max_age_days) or not any(w in d for w in WANT_DESC):
            continue
        todo.append((when, r))
    todo.sort(key=lambda x: x[0], reverse=True)
    n = 0
    path = root.joinpath(*FACTS)
    for k, (when, r) in enumerate(todo[:limit]):
        if k and session is None:
            time.sleep(1.5)                                # NSE answers a burst of downloads with empty bodies
        facts = read_filing(str(r["url"]), str(r.get("desc") or ""), session)
        facts.update(id=r["id"], symbol=r.get("symbol"), desc=r.get("desc"), published_at=r.get("published_at"), read_at=now.isoformat(timespec="seconds"))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as h:
            h.write(json.dumps(facts) + "\n")
        n += 1
    return n
