from __future__ import annotations

import csv, json, math, time
from dataclasses import asdict, dataclass
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "data" / "reports"
STATE = ROOT / "data" / "research" / "btst"
REPORTS.mkdir(parents=True, exist_ok=True)
STATE.mkdir(parents=True, exist_ok=True)

MARKET_WATCH = REPORTS / "fno_market_watch_latest.json"
INTRADAY = REPORTS / "intraday_movement_latest.json"
PAPER = REPORTS / "paper_trades_latest.json"

@dataclass
class BtstCandidate:
    trading_date: str
    captured_at: str
    symbol: str
    sector: str
    direction: str
    option_side: str
    ltp: float
    open_0915: float
    previous_close: float
    from_open_pct: float
    from_prev_close_pct: float
    gap_pct: float
    day_high: float
    day_low: float
    range_position_pct: float
    distance_from_extreme_pct: float
    score: float
    status: str
    reasons: list[str]

def num(v: Any, d=0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d

def load_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def candidate_score(r: dict[str, Any], direction: str) -> tuple[float, list[str]]:
    move = num(r.get("from_open_pct"))
    prev = num(r.get("from_prev_close_pct"))
    rng = num(r.get("range_position_pct"), 50.0)
    gap = num(r.get("gap_pct"))
    reasons = []

    if direction == "BULLISH":
        session = move
        prev_move = prev
        extreme = max(0.0, 100.0-rng)
        if session > 0: reasons.append(f"session +{session:.2f}%")
        if rng >= 75: reasons.append(f"near day high ({rng:.0f}% range)")
        if prev_move > 0: reasons.append(f"vs prev close +{prev_move:.2f}%")
    else:
        session = -move
        prev_move = -prev
        extreme = max(0.0, rng)
        if session > 0: reasons.append(f"session -{session:.2f}%")
        if rng <= 25: reasons.append(f"near day low ({rng:.0f}% range)")
        if prev_move > 0: reasons.append(f"vs prev close -{prev_move:.2f}%")

    score = 0.0
    score += min(40.0, max(0.0, session) * 12.0)
    score += min(20.0, max(0.0, prev_move) * 5.0)
    score += max(0.0, 20.0 - extreme * 0.35)
    score += min(10.0, abs(gap) * 2.0)

    # Late-session bias: only genuine closes near extreme qualify.
    if session >= 1.0:
        score += 5.0
    if extreme <= 10.0:
        score += 5.0

    return round(min(100.0, score), 2), reasons

def build_candidates() -> dict[str, Any]:
    mw = load_json(MARKET_WATCH)
    rows = mw.get("rows", []) if isinstance(mw, dict) else []
    now = datetime.now(IST)
    today = now.date().isoformat()

    bulls, bears = [], []
    for r in rows:
        sym = str(r.get("symbol") or "").strip().upper()
        if not sym:
            continue
        move = num(r.get("from_open_pct"))
        rng = num(r.get("range_position_pct"), 50.0)

        if move > 0:
            score, reasons = candidate_score(r, "BULLISH")
            extreme = max(0.0, 100.0-rng)
            status = "QUALIFIED" if score >= 70 and move >= 0.8 and rng >= 70 else "WATCH"
            bulls.append(BtstCandidate(
                today, now.isoformat(), sym, str(r.get("sector") or "UNCLASSIFIED"),
                "BULLISH", "CE", num(r.get("ltp")), num(r.get("open_0915")),
                num(r.get("previous_close")), move, num(r.get("from_prev_close_pct")),
                num(r.get("gap_pct")), num(r.get("day_high")), num(r.get("day_low")),
                rng, extreme, score, status, reasons
            ))
        elif move < 0:
            score, reasons = candidate_score(r, "BEARISH")
            extreme = max(0.0, rng)
            status = "QUALIFIED" if score >= 70 and move <= -0.8 and rng <= 30 else "WATCH"
            bears.append(BtstCandidate(
                today, now.isoformat(), sym, str(r.get("sector") or "UNCLASSIFIED"),
                "BEARISH", "PE", num(r.get("ltp")), num(r.get("open_0915")),
                num(r.get("previous_close")), move, num(r.get("from_prev_close_pct")),
                num(r.get("gap_pct")), num(r.get("day_high")), num(r.get("day_low")),
                rng, extreme, score, status, reasons
            ))

    bulls.sort(key=lambda x: x.score, reverse=True)
    bears.sort(key=lambda x: x.score, reverse=True)

    top_bulls = bulls[:5]
    top_bears = bears[:5]
    qualified = [x for x in top_bulls + top_bears if x.status == "QUALIFIED"]

    payload = {
        "generated_at": now.isoformat(),
        "trading_date": today,
        "mode": "PAPER_RESEARCH_ONLY",
        "window": "14:45-15:20",
        "rule": "Top 5 bullish + Top 5 bearish late-session BTST candidates; CE for bullish, PE for bearish",
        "top_bullish": [asdict(x) for x in top_bulls],
        "top_bearish": [asdict(x) for x in top_bears],
        "qualified": [asdict(x) for x in qualified],
    }
    return payload

def save_payload(payload: dict[str, Any]) -> None:
    latest = REPORTS / "btst_candidates_latest.json"
    latest.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    csv_path = REPORTS / "btst_candidates_latest.csv"
    rows = payload.get("top_bullish", []) + payload.get("top_bearish", [])
    fields = [
        "trading_date","captured_at","symbol","sector","direction","option_side",
        "ltp","open_0915","previous_close","from_open_pct","from_prev_close_pct",
        "gap_pct","day_high","day_low","range_position_pct",
        "distance_from_extreme_pct","score","status","reasons"
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            rr = dict(row)
            rr["reasons"] = " | ".join(rr.get("reasons", []))
            w.writerow(rr)

    daydir = STATE / payload["trading_date"]
    daydir.mkdir(parents=True, exist_ok=True)
    (daydir / f"btst_snapshot_{datetime.now(IST):%H%M%S}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

def main():
    print("="*76)
    print("APlus BTST Candidate Scanner")
    print("PAPER / RESEARCH ONLY")
    print("Window: 14:45-15:20 IST")
    print("No live orders. No option buys are placed.")
    print("="*76)

    while True:
        now = datetime.now(IST)
        if now.time() > dtime(15,20):
            payload = build_candidates()
            save_payload(payload)
            print("Final BTST snapshot saved.")
            return
        if now.time() < dtime(14,45):
            wait = min(60, max(5, int((datetime.combine(now.date(), dtime(14,45), tzinfo=IST)-now).total_seconds())))
            time.sleep(wait)
            continue
        payload = build_candidates()
        save_payload(payload)
        q = payload.get("qualified", [])
        print(now.strftime("%H:%M:%S"), "qualified", len(q),
              "bull", [x["symbol"] for x in payload.get("top_bullish", [])],
              "bear", [x["symbol"] for x in payload.get("top_bearish", [])])
        time.sleep(60)

if __name__ == "__main__":
    main()
