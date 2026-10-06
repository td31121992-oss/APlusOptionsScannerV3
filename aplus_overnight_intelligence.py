from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
OUT_DIR = PROJECT_ROOT / "data" / "news_intelligence"
EVENTS = OUT_DIR / "events.jsonl"
HEALTH = OUT_DIR / "overnight_intelligence_health.json"
LOG = PROJECT_ROOT / "data" / "logs" / "overnight_intelligence.log"
UNIVERSE = PROJECT_ROOT / "data" / "reports" / "fno_market_watch_latest.json"

TOPIC_QUERIES = [
    ("GLOBAL_MARKETS", "S&P 500 Nasdaq Dow Jones global markets"),
    ("US_MACRO", "Federal Reserve CPI jobs inflation interest rates"),
    ("OIL_GOLD_FX", "crude oil OPEC gold dollar rupee"),
    ("ASIA_MARKETS", "Asia markets Japan China Hong Kong"),
    ("INDIA_MARKETS", "Nifty Sensex Indian stock market"),
    ("INDIA_REGULATORY", "SEBI NSE BSE RBI market"),
    ("INDIA_MACRO", "India GDP inflation RBI interest rates"),
    ("FNO", "India futures options derivatives F&O"),
    ("CORPORATE", "India stocks earnings results corporate action"),
]

USER_AGENT = "APlusOptionsScannerV3-OvernightIntelligence/1.0"
TIMEOUT = 12


def log(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat()}] {message}\n")


def rss_url(query: str) -> str:
    params = urllib.parse.urlencode({"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    return "https://news.google.com/rss/search?" + params


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def text(el: ET.Element | None) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext()).strip()) if el is not None else ""


def parse_feed(raw: bytes, category: str) -> list[dict]:
    root = ET.fromstring(raw)
    events = []
    for item in root.findall(".//item"):
        title = text(item.find("title"))
        link = text(item.find("link"))
        pub = text(item.find("pubDate"))
        desc = text(item.find("description"))
        source = text(item.find("source")) or "Google News"
        if not title or not link:
            continue
        event_id = hashlib.sha256(link.encode("utf-8")).hexdigest()[:24]
        events.append({
            "event_id": event_id,
            "published_at_raw": pub,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "source_type": "news_aggregator_rss",
            "category": category,
            "title": title,
            "summary": desc[:1000],
            "url": link,
            "read_only": True,
            "trading_engine_untouched": True,
        })
    return events


def universe_symbols() -> list[str]:
    if not UNIVERSE.exists():
        return []
    try:
        obj = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    except Exception:
        return []
    found: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                key = str(k).lower()
                if key in {"symbol", "tradingsymbol", "security_symbol", "ticker"} and isinstance(v, str):
                    s = v.strip().upper()
                    if re.fullmatch(r"[A-Z][A-Z0-9&.-]{1,19}", s):
                        found.add(s)
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return sorted(found)[:40]


def load_seen() -> set[str]:
    if not EVENTS.exists():
        return set()
    seen = set()
    try:
        with EVENTS.open(encoding="utf-8") as f:
            for line in f:
                try:
                    seen.add(str(json.loads(line).get("event_id", "")))
                except Exception:
                    pass
    except Exception:
        pass
    return seen


def collect_once() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    seen = load_seen()
    queries = list(TOPIC_QUERIES)
    queries.extend((f"STOCK_{s}", f"{s} stock shares results news") for s in universe_symbols())
    added = 0
    failed = 0

    with EVENTS.open("a", encoding="utf-8") as out:
        for category, query in queries:
            try:
                for event in parse_feed(fetch(rss_url(query)), category):
                    if event["event_id"] in seen:
                        continue
                    out.write(json.dumps(event, ensure_ascii=False) + "\n")
                    seen.add(event["event_id"])
                    added += 1
            except Exception as exc:
                failed += 1
                log(f"FETCH_FAIL category={category} error={type(exc).__name__}: {exc}")

    health = {
        "service": "APlus Overnight Intelligence Collector",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "events_added": added,
        "feeds_failed": failed,
        "universe_symbols_checked": len(universe_symbols()),
        "events_path": str(EVENTS),
        "mode": "read_only_context",
        "dhan_dependency": False,
        "trading_engine_untouched": True,
    }
    HEALTH.write_text(json.dumps(health, indent=2), encoding="utf-8")
    return health


def main() -> int:
    log("collector started")
    while True:
        try:
            h = collect_once()
            log(f"cycle complete added={h['events_added']} failed={h['feeds_failed']}")
        except Exception as exc:
            log(f"CYCLE_FAIL {type(exc).__name__}: {exc}")
        time.sleep(1800)


if __name__ == "__main__":
    raise SystemExit(main())
