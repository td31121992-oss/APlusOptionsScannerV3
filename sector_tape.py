"""Intraday sector-index tape for two SHADOW tags (nothing here changes a trade).

1. At entry: how the stock's sector index is doing right now - its change over the last 15 minutes in OUR direction, and how far it
   is below its day high (bullish trade) / above its day low (bearish trade). The hypothesis: do not buy a stock when its sector has
   already turned or is stalling off its high (on 15 Oct IT peaked at 09:45 and faded 0.6% while four IT trades were open).
2. After entry: the "secfade" shadow exit - the sector gave back 0.4% from its best level since our entry AND the stock is below our
   entry price. The journal records what that would have done; the trade is untouched.

One Dhan IDX_I quote call per cycle (at most every 15 seconds) for the sector indices listed in sector_rrg.INDICES.
"""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from typing import Any

import sector_rrg

ROOT = Path(__file__).resolve().parent
FADE_FROM_HIGH_PCT = 0.4
FADE_CHG15_PCT = -0.2
POLL_SECONDS = 15.0


def _f(v: Any) -> float:
    try:
        x = float(v)
        return x if x == x else 0.0
    except (TypeError, ValueError):
        return 0.0


class SectorTape:
    def __init__(self, root: Path = ROOT, fetch=None) -> None:
        self.root = Path(root)
        self._fetch = fetch or self._fetch_quotes
        self._hist: dict[str, deque] = {}
        self._high: dict[str, float] = {}
        self._low: dict[str, float] = {}
        self._last_poll = -1e12
        self.ltps: dict[str, float] = {}

    def _fetch_quotes(self) -> dict[int, dict[str, float]]:
        import index_strip
        import requests

        ids = sorted(set(sector_rrg.INDICES.values()))
        r = requests.post("https://api.dhan.co/v2/marketfeed/quote", headers=index_strip._headers(self.root),
                          json={"IDX_I": ids}, timeout=6)
        if r.status_code != 200:
            raise RuntimeError(f"quote HTTP {r.status_code}")
        data = ((r.json() or {}).get("data") or {}).get("IDX_I") or {}
        return {int(k): {"ltp": _f((v or {}).get("last_price"))} for k, v in data.items()}

    def update(self, now_ts: float | None = None, force: bool = False) -> bool:
        now_ts = time.time() if now_ts is None else now_ts
        if not force and now_ts - self._last_poll < POLL_SECONDS:
            return False
        self._last_poll = now_ts
        try:
            quotes = self._fetch()
        except Exception:                                  # noqa: BLE001 - a shadow tape must never affect trading
            return False
        by_id = {v: k for k, v in sector_rrg.INDICES.items()}
        for sid, q in quotes.items():
            name, ltp = by_id.get(int(sid)), _f(q.get("ltp"))
            if not name or ltp <= 0:
                continue
            self._hist.setdefault(name, deque(maxlen=2000)).append((now_ts, ltp))
            self._high[name] = max(self._high.get(name, ltp), ltp)
            self._low[name] = min(self._low.get(name, ltp), ltp)
            self.ltps[name] = ltp
        return True

    def _ago(self, name: str, minutes: float) -> float | None:
        h = self._hist.get(name)
        if not h:
            return None
        cutoff = h[-1][0] - minutes * 60
        older = [p for t, p in h if t <= cutoff]
        return older[-1] if older else None

    def tags_for(self, sector_label: str, direction: str) -> dict[str, Any]:
        idx = sector_rrg.index_for(sector_label)
        if not idx or idx not in self.ltps:
            return {}
        now = self.ltps[idx]
        bull = str(direction).upper() == "BULLISH"
        out: dict[str, Any] = {"sec_idx": idx, "sec_entry_ltp": round(now, 2)}
        prev = self._ago(idx, 15)
        chg = None
        if prev:
            chg = ((now / prev - 1.0) * 100.0) * (1 if bull else -1)
            out["sec_chg15_pct"] = round(chg, 3)
        away = ((self._high[idx] - now) / self._high[idx] * 100.0) if bull else ((now - self._low[idx]) / self._low[idx] * 100.0)
        out["sec_from_extreme_pct"] = round(away, 3)
        out["sec_state"] = "FADING" if (away >= FADE_FROM_HIGH_PCT or (chg is not None and chg <= FADE_CHG15_PCT)) else "OK"
        return out
