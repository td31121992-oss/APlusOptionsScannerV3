from __future__ import annotations

import csv
import json
import time
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "data" / "reports"
RESEARCH = ROOT / "data" / "research" / "top_bottom_from_open"
REPORTS.mkdir(parents=True, exist_ok=True)
RESEARCH.mkdir(parents=True, exist_ok=True)

SOURCE = REPORTS / "fno_market_watch_latest.json"
LATEST_JSON = REPORTS / "top_bottom_from_open_latest.json"
LATEST_CSV = REPORTS / "top_bottom_from_open_events_latest.csv"

TOP_N = 5
POLL_SECONDS = 5

def load_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def atomic_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

class RankHistory:
    def __init__(self) -> None:
        self.day = datetime.now(IST).date().isoformat()
        self.day_dir = RESEARCH / self.day
        self.stock_dir = self.day_dir / "stocks"
        self.stock_dir.mkdir(parents=True, exist_ok=True)

        self.events: list[dict[str, Any]] = []
        self.snapshots: list[dict[str, Any]] = []
        self.current_top: dict[str, int] = {}
        self.current_bottom: dict[str, int] = {}
        self.first_seen: dict[tuple[str, str], str] = {}
        self.best_rank: dict[tuple[str, str], int] = {}
        self.total_cycles: dict[tuple[str, str], int] = {}
        self.last_generated_at = ""

    def emit(self, now: datetime, symbol: str, side: str, event: str, rank: int | None,
             row: dict[str, Any], previous_rank: int | None = None) -> None:
        key = (symbol, side)
        ts = now.isoformat()
        if key not in self.first_seen and event in ("ENTER", "RE_ENTER"):
            self.first_seen[key] = ts

        if rank:
            self.best_rank[key] = min(rank, self.best_rank.get(key, rank))

        ev = {
            "date": self.day,
            "time": now.strftime("%H:%M:%S"),
            "timestamp": ts,
            "symbol": symbol,
            "sector": str(row.get("sector") or "Other/Industrial"),
            "side": side,
            "event": event,
            "rank": rank or "",
            "previous_rank": previous_rank or "",
            "from_open_pct": float(row.get("from_open_pct") or 0),
            "ltp": float(row.get("ltp") or 0),
            "open_0915": float(row.get("open_0915") or 0),
            "day_high": float(row.get("day_high") or 0),
            "day_low": float(row.get("day_low") or 0),
            "gap_pct": float(row.get("gap_pct") or 0),
            "first_seen_time": self.first_seen.get(key, ""),
            "best_rank": self.best_rank.get(key, rank or ""),
        }
        self.events.append(ev)

        p = self.stock_dir / f"{symbol}.json"
        old = load_json(p)
        arr = old.get("events", []) if isinstance(old, dict) else []
        arr.append(ev)
        atomic_json(p, {"date": self.day, "symbol": symbol, "events": arr})

        print(
            ev["time"], side, event, symbol,
            f"rank={rank if rank else '-'}",
            f"move={ev['from_open_pct']:+.2f}%"
        )

    def process(self, now: datetime, rows: list[dict[str, Any]]) -> None:
        by_symbol = {str(r.get("symbol") or "").upper(): r for r in rows if r.get("symbol")}
        ranked_up = sorted(rows, key=lambda x: float(x.get("from_open_pct") or 0), reverse=True)[:TOP_N]
        ranked_dn = sorted(rows, key=lambda x: float(x.get("from_open_pct") or 0))[:TOP_N]

        new_top = {str(r.get("symbol") or "").upper(): i + 1 for i, r in enumerate(ranked_up)}
        new_bottom = {str(r.get("symbol") or "").upper(): i + 1 for i, r in enumerate(ranked_dn)}

        # TOP side
        for sym, rank in new_top.items():
            key = (sym, "TOP_FROM_OPEN")
            self.total_cycles[key] = self.total_cycles.get(key, 0) + 1
            old_rank = self.current_top.get(sym)
            if old_rank is None:
                event = "RE_ENTER" if key in self.first_seen else "ENTER"
                self.emit(now, sym, "TOP_FROM_OPEN", event, rank, by_symbol[sym])
            elif old_rank != rank:
                self.emit(now, sym, "TOP_FROM_OPEN", "RANK_CHANGE", rank, by_symbol[sym], old_rank)

        for sym, old_rank in list(self.current_top.items()):
            if sym not in new_top:
                self.emit(now, sym, "TOP_FROM_OPEN", "EXIT", None, by_symbol.get(sym, {}), old_rank)

        # BOTTOM side
        for sym, rank in new_bottom.items():
            key = (sym, "BOTTOM_FROM_OPEN")
            self.total_cycles[key] = self.total_cycles.get(key, 0) + 1
            old_rank = self.current_bottom.get(sym)
            if old_rank is None:
                event = "RE_ENTER" if key in self.first_seen else "ENTER"
                self.emit(now, sym, "BOTTOM_FROM_OPEN", event, rank, by_symbol[sym])
            elif old_rank != rank:
                self.emit(now, sym, "BOTTOM_FROM_OPEN", "RANK_CHANGE", rank, by_symbol[sym], old_rank)

        for sym, old_rank in list(self.current_bottom.items()):
            if sym not in new_bottom:
                self.emit(now, sym, "BOTTOM_FROM_OPEN", "EXIT", None, by_symbol.get(sym, {}), old_rank)

        self.current_top = new_top
        self.current_bottom = new_bottom

        snap = {
            "time": now.strftime("%H:%M:%S"),
            "timestamp": now.isoformat(),
            "top_from_open": [
                {
                    "rank": i + 1,
                    "symbol": str(r.get("symbol") or "").upper(),
                    "sector": str(r.get("sector") or "Other/Industrial"),
                    "from_open_pct": float(r.get("from_open_pct") or 0),
                    "ltp": float(r.get("ltp") or 0),
                }
                for i, r in enumerate(ranked_up)
            ],
            "bottom_from_open": [
                {
                    "rank": i + 1,
                    "symbol": str(r.get("symbol") or "").upper(),
                    "sector": str(r.get("sector") or "Other/Industrial"),
                    "from_open_pct": float(r.get("from_open_pct") or 0),
                    "ltp": float(r.get("ltp") or 0),
                }
                for i, r in enumerate(ranked_dn)
            ],
        }
        self.snapshots.append(snap)
        if len(self.snapshots) > 5000:
            self.snapshots = self.snapshots[-5000:]

    def save(self, now: datetime) -> None:
        payload = {
            "generated_at": now.isoformat(),
            "date": self.day,
            "top_n": TOP_N,
            "current_top_from_open": self.snapshots[-1]["top_from_open"] if self.snapshots else [],
            "current_bottom_from_open": self.snapshots[-1]["bottom_from_open"] if self.snapshots else [],
            "events": self.events[-2000:],
            "snapshot_count": len(self.snapshots),
        }
        atomic_json(LATEST_JSON, payload)
        atomic_json(self.day_dir / "rank_history.json", payload)
        atomic_json(self.day_dir / "rank_snapshots.json", {"date": self.day, "snapshots": self.snapshots})

        fields = [
            "date", "time", "symbol", "sector", "side", "event",
            "rank", "previous_rank", "from_open_pct", "ltp", "open_0915",
            "day_high", "day_low", "gap_pct", "first_seen_time", "best_rank"
        ]
        with LATEST_CSV.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(self.events[-2000:])

    def run(self) -> None:
        print("=" * 84)
        print("APlus Top/Bottom From Open Rank History")
        print("Tracks membership changes separately all day. No extra Dhan calls.")
        print("=" * 84)

        while True:
            now = datetime.now(IST)
            if now.date().isoformat() != self.day:
                return
            if now.time() < dtime(9, 15):
                time.sleep(POLL_SECONDS)
                continue
            if now.time() > dtime(15, 35):
                self.save(now)
                return

            obj = load_json(SOURCE)
            rows = obj.get("rows", []) if isinstance(obj, dict) else []
            generated = str(obj.get("generated_at") or "") if isinstance(obj, dict) else ""
            if not rows or generated == self.last_generated_at:
                time.sleep(POLL_SECONDS)
                continue

            self.last_generated_at = generated
            self.process(now, [r for r in rows if isinstance(r, dict)])
            self.save(now)
            time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    RankHistory().run()
