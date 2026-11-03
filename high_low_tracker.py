"""Remember WHEN each paper trade made its highest and lowest option price.

The journal stores the highest/lowest PRICE of every trade. Newer scanner builds also store the exact
time (highest_option_price_at / lowest_option_price_at); for trades without those fields this tracker
notes the time at which the dashboard first SAW each new high/low (accurate to one scan cycle) and
persists it, so it survives dashboard restarts.

Time labels: "10:41" = known; "before 11:05" = the extreme happened before tracking began;
"entry" is never shown as a label - when the extreme equals the entry price the time is the entry time.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

EPS = 1e-6


def _num(value: Any) -> float:
    try:
        out = float(value)
        return out if out == out else 0.0
    except (TypeError, ValueError):
        return 0.0


def _hhmm(value: Any) -> str:
    text = str(value or "")
    return text[11:16] if len(text) >= 16 and text[10] in "T " else ""


class HighLowTracker:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._state: dict[str, dict[str, Any]] = {}
        self._dirty = False
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self._state = loaded
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        if not self._dirty:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state), encoding="utf-8")
            os.replace(tmp, self.path)
            self._dirty = False
        except OSError:
            pass

    def update(self, trade: Mapping[str, Any], now: datetime) -> dict[str, Any]:
        """Return {'high','high_time','low','low_time'} for one trade dict (journal row)."""
        tid = str(trade.get("paper_trade_id") or trade.get("trade_id") or "")
        entry = _num(trade.get("entry_price"))
        high = _num(trade.get("highest_option_price"))
        low = _num(trade.get("lowest_option_price"))
        entry_hhmm = _hhmm(trade.get("entry_time"))
        now_hhmm = now.strftime("%H:%M")
        out = {"high": high, "high_time": "", "low": low, "low_time": ""}
        if not tid or (high <= 0 and low <= 0):
            return out

        with self._lock:
            st = self._state.get(tid)
            if st is None:
                st = {"high": high, "low": low, "high_at": "", "low_at": "", "since": now_hhmm}
                self._state[tid] = st
                self._dirty = True
            else:
                if high > st["high"] + EPS:
                    st["high"], st["high_at"] = high, now_hhmm
                    self._dirty = True
                if low > 0 and (st["low"] <= 0 or low < st["low"] - EPS):
                    st["low"], st["low_at"] = low, now_hhmm
                    self._dirty = True
            self._save()

        for kind, price in (("high", high), ("low", low)):
            exact = _hhmm(trade.get(f"{'highest' if kind == 'high' else 'lowest'}_option_price_at"))
            if exact:
                label = exact
            elif entry > 0 and abs(price - entry) <= EPS and entry_hhmm:
                label = entry_hhmm                       # never moved beyond the entry price
            elif st.get(f"{kind}_at"):
                label = st[f"{kind}_at"]
            else:
                label = f"before {st['since']}" if st.get("since") else ""
            out[f"{kind}_time"] = label
        return out
