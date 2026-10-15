"""Futures premium and open-interest flow for every F&O stock (SHADOW tags; nothing here trades).

The near-month future of each stock rides on the quote call the scanner already makes (one extra block of ids, no extra request).
Every cycle a snapshot of the future's price, open interest and the cash price is kept, so that at entry a trade can record:

  fut_premium_pct         future / cash - 1, in %
  fut_premium_chg_pct     that premium now minus its first reading today (a shrinking premium while the stock rises = weak)
  fut_oi_chg_day_pct      open interest vs the previous session's last reading (state file), in %
  fut_oi_chg_30m_pct      open interest vs ~30 minutes ago
  fut_price_chg_30m_pct   the future's price change over the same window
  fut_flow                LONG_BUILDUP (price up, OI up), SHORT_COVERING (price up, OI down), SHORT_BUILDUP (price down, OI up),
                          LONG_UNWINDING (price down, OI down), or NEUTRAL when either move is tiny
  fut_confirms            a call with LONG_BUILDUP or a put with SHORT_BUILDUP: fresh positions are entering in our direction
"""

from __future__ import annotations

import json
import os
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
MASTER = ROOT / "data" / "cache" / "api-scrip-master-detailed.csv"
MIN_PRICE_MOVE_PCT = 0.10
MIN_OI_MOVE_PCT = 0.30


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


def load_future_ids(master_csv: Path = MASTER, today: date | None = None, min_days: int = 2) -> dict[str, str]:
    """symbol -> Dhan security id of the nearest stock future that is at least `min_days` from expiry."""
    import csv

    today = today or date.today()
    best: dict[str, tuple[date, str]] = {}
    with Path(master_csv).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("INSTRUMENT") or "") != "FUTSTK":
                continue
            try:
                exp = datetime.fromisoformat(str(row.get("SM_EXPIRY_DATE") or "")[:10]).date()
            except ValueError:
                continue
            if (exp - today).days < min_days:
                continue
            sym = str(row.get("UNDERLYING_SYMBOL") or "").strip().upper()
            sid = str(int(float(row.get("SECURITY_ID") or 0)))
            if sym and sid != "0" and (sym not in best or exp < best[sym][0]):
                best[sym] = (exp, sid)
    return {s: v[1] for s, v in best.items()}


class FuturesFlow:
    def __init__(self, data_dir: Path | str, master_csv: Path = MASTER, keep_minutes: int = 50) -> None:
        self.state_path = Path(data_dir) / "cache" / "futures_oi_state.json"
        self.master_csv = Path(master_csv)
        self.keep = keep_minutes * 60
        self.ids: dict[str, str] = {}
        self.ids_day: date | None = None
        self.hist: dict[str, deque[tuple[float, float, float, float]]] = {}   # ts, future ltp, oi, cash ltp
        self.prev_oi: dict[str, float] = {}
        self.first_premium: dict[str, float] = {}
        self.day: str = ""
        self._saved_at = 0.0

    # ---------------------------------------------------------------- ids
    def request_ids(self, today: date | None = None, symbols: Sequence[str] | None = None) -> list[str]:
        """Security ids of the near-month futures to add to the quote request (only for `symbols` when given)."""
        today = today or date.today()
        if self.ids_day != today or not self.ids:
            try:
                ids = load_future_ids(self.master_csv, today)
                if symbols:
                    keep = {str(s).upper() for s in symbols}
                    ids = {s: v for s, v in ids.items() if s in keep}
                self.ids = ids
            except Exception:                              # noqa: BLE001 - tags are optional
                self.ids = {}
            self.ids_day = today
        return sorted(self.ids.values())

    # ---------------------------------------------------------------- state across days
    def _load_state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _roll_day(self, day: str) -> None:
        if self.day == day:
            return
        st = self._load_state()
        self.prev_oi = {k: float(v) for k, v in (st.get("last_oi") or {}).items()} if st.get("day") and st.get("day") != day else \
                       {k: float(v) for k, v in (st.get("prev_oi") or {}).items()}
        self.hist.clear()
        self.first_premium.clear()
        self.day = day

    def _save_state(self, now_ts: float, last_oi: Mapping[str, float]) -> None:
        if now_ts - self._saved_at < 300:
            return
        self._saved_at = now_ts
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"day": self.day, "last_oi": dict(last_oi), "prev_oi": self.prev_oi}), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError:
            pass

    # ---------------------------------------------------------------- per cycle
    def update(self, quote_map: Mapping[str, Any], cash_prices: Mapping[str, float], now: datetime) -> int:
        self._roll_day(now.date().isoformat())
        seg = quote_map.get("NSE_FNO", {}) if isinstance(quote_map, Mapping) else {}
        ts = now.timestamp()
        n, last_oi = 0, {}
        for sym, sid in self.ids.items():
            raw = seg.get(sid) if isinstance(seg, Mapping) else None
            if raw is None and isinstance(seg, Mapping):
                try:
                    raw = seg.get(int(sid))
                except (TypeError, ValueError):
                    raw = None
            if not isinstance(raw, Mapping):
                continue
            fut, oi, cash = _f(raw.get("last_price")), _f(raw.get("oi")), _f(cash_prices.get(sym))
            if fut <= 0 or cash <= 0:
                continue
            d = self.hist.setdefault(sym, deque())
            if not d or ts - d[-1][0] >= 20:
                d.append((ts, fut, oi, cash))
            while d and ts - d[0][0] > self.keep:
                d.popleft()
            self.first_premium.setdefault(sym, (fut / cash - 1.0) * 100.0)
            if oi > 0:
                last_oi[sym] = oi
            n += 1
        if last_oi:
            self._save_state(ts, last_oi)
        return n

    # ---------------------------------------------------------------- tags
    def tags_for(self, symbol: str, direction: str, window_min: int = 30) -> dict[str, Any]:
        try:
            d = self.hist.get(str(symbol).upper())
            if not d:
                return {}
            ts, fut, oi, cash = d[-1]
            target = ts - window_min * 60
            ref = next((x for x in reversed(d) if x[0] <= target), None)
            out: dict[str, Any] = {"fut_premium_pct": round((fut / cash - 1.0) * 100.0, 3)}
            fp = self.first_premium.get(str(symbol).upper())
            if fp is not None:
                out["fut_premium_chg_pct"] = round(out["fut_premium_pct"] - fp, 3)
            prev = self.prev_oi.get(str(symbol).upper())
            if prev and oi > 0:
                out["fut_oi_chg_day_pct"] = round((oi / prev - 1.0) * 100.0, 2)
            if ref is not None and ref[1] > 0 and ref[2] > 0 and oi > 0:
                pchg = (fut / ref[1] - 1.0) * 100.0
                ochg = (oi / ref[2] - 1.0) * 100.0
                out["fut_price_chg_30m_pct"], out["fut_oi_chg_30m_pct"] = round(pchg, 3), round(ochg, 2)
                if abs(pchg) < MIN_PRICE_MOVE_PCT or abs(ochg) < MIN_OI_MOVE_PCT:
                    flow = "NEUTRAL"
                elif pchg > 0:
                    flow = "LONG_BUILDUP" if ochg > 0 else "SHORT_COVERING"
                else:
                    flow = "SHORT_BUILDUP" if ochg > 0 else "LONG_UNWINDING"
                out["fut_flow"] = flow
                bull = str(direction).upper() == "BULLISH"
                out["fut_confirms"] = bool((bull and flow == "LONG_BUILDUP") or ((not bull) and flow == "SHORT_BUILDUP"))
            return out
        except Exception:                                  # noqa: BLE001
            return {}
