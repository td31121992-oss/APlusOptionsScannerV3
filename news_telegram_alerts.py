from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
EVENTS_PATH = ROOT / "data" / "news_intelligence" / "events.jsonl"
STATE_PATH = ROOT / "data" / "news_intelligence" / "telegram_alert_state.json"
LOG_PATH = ROOT / "data" / "logs" / "news_telegram_alerts.log"

HIGH_IMPACT = {"VERY HIGH", "HIGH"}
SEBI_TERMS = (
    "sebi", "securities and exchange board", "circular", "regulation",
    "regulatory", "position limit", "margin", "derivatives", "f&o",
    "futures", "options", "broker", "exchange", "clearing", "settlement",
    "trading hours", "expiry", "surveillance", "penalty",
)
MARKET_TERMS = (
    "rbi", "repo rate", "interest rate", "inflation", "cpi", "wpi", "gdp",
    "fed", "federal reserve", "ecb", "boj", "tariff", "sanction", "war",
    "crude", "oil", "gold", "rupee", "usd", "india", "nifty", "sensex",
    "bank nifty", "market crash", "circuit", "default", "downgrade",
    "upgrade", "earnings", "results", "guidance", "merger", "acquisition",
    "fraud", "investigation", "resignation", "rating",
)

def _log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")

def _load_state() -> dict:
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}

def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_PATH)

def _event_is_alertworthy(event: dict) -> bool:
    title = str(event.get("title") or "").lower()
    summary = str(event.get("summary") or "").lower()
    blob = f"{title} {summary}"
    impact = str(event.get("impact") or "").upper()
    source_type = str(event.get("source_type") or event.get("source") or "").lower()
    category = str(event.get("category") or "").lower()

    if impact in HIGH_IMPACT:
        return True
    if "sebi" in blob or "securities and exchange board" in blob:
        return True
    if any(term in blob for term in SEBI_TERMS) and (
        category in {"regulatory", "india regulatory", "market", "f&o", "corporate"}
        or "sebi" in source_type
    ):
        return True
    if any(term in blob for term in MARKET_TERMS):
        return impact != "LOW"
    return False

def _telegram_credentials() -> tuple[str, str]:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("TELEGRAM_CHAT_ID", "").strip()

def _send_telegram(text: str) -> bool:
    token, chat_id = _telegram_credentials()
    if not token or not chat_id:
        _log("Telegram credentials missing; notification skipped")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urlencode({"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}).encode()
    try:
        with urlopen(Request(url, data=payload, method="POST"), timeout=15) as response:
            body = json.loads(response.read().decode("utf-8", errors="replace"))
        ok = bool(body.get("ok"))
        if not ok:
            _log("Telegram API rejected notification")
        return ok
    except Exception as exc:
        _log(f"Telegram send failed: {type(exc).__name__}: {exc}")
        return False

def _format_event(event: dict) -> str:
    title = str(event.get("title") or "Market news")
    summary = str(event.get("summary") or "").strip()
    impact = str(event.get("impact") or "UNKNOWN").upper()
    category = str(event.get("category") or "market").strip()
    published = str(event.get("published_at") or event.get("published") or "unknown")
    source = str(event.get("source") or event.get("source_type") or "unknown")
    url = str(event.get("url") or "").strip()

    lines = [
        f"🚨 APlus Market News — {impact}",
        f"Category: {category}",
        f"Time: {published}",
        f"Source: {source}",
        f"📰 {title}",
    ]
    if summary:
        lines.append(summary[:900])
    if url:
        lines.append(url)
    lines.append("Read-only news alert • No trade/order action taken")
    return "\n".join(lines)

def process_once() -> int:
    if not EVENTS_PATH.exists():
        return 0
    state = _load_state()
    sent = state.setdefault("sent_event_ids", {})
    changed = False
    count = 0
    lines = EVENTS_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-500:]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_id = str(event.get("event_id") or "").strip()
        if not event_id or event_id in sent or not _event_is_alertworthy(event):
            continue
        if _send_telegram(_format_event(event)):
            sent[event_id] = datetime.now(timezone.utc).isoformat()
            count += 1
            changed = True
    if len(sent) > 5000:
        state["sent_event_ids"] = dict(list(sent.items())[-4000:])
        changed = True
    if changed:
        _save_state(state)
    return count

def main() -> int:
    interval = max(30, int(os.getenv("APLUS_NEWS_TELEGRAM_INTERVAL", "60")))
    once = os.getenv("APLUS_NEWS_TELEGRAM_ONCE", "").strip().lower() in {"1", "true", "yes"}
    _log("News Telegram alert worker started")
    while True:
        try:
            count = process_once()
            if count:
                _log(f"Sent {count} news notification(s)")
        except Exception as exc:
            _log(f"Worker cycle failed: {type(exc).__name__}: {exc}")
        if once:
            return 0
        time.sleep(interval)

if __name__ == "__main__":
    raise SystemExit(main())
