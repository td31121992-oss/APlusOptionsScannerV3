"""Implied-volatility shadow tags for a candidate (SHADOW: records only, never blocks or changes a trade).

An option bought when implied volatility (IV) is already high is bought dear: if the move comes but IV falls back, the premium gains less than the stock suggests (or loses). This records, at the
moment a candidate is seen, how dear the option is by four measures, all from the option chain snapshot the scanner already has plus our own history:

    iv_atm            ATM implied volatility, % (average of the call and put at the strike nearest the spot)
    iv_rank           where it sits among this stock's last 60 recorded days, 0 (cheapest) .. 100 (dearest); blank until 10 days exist (iv_history.py)
    iv_vs_hv          ATM IV divided by the stock's 20-day realised volatility (annualised, from the NSE daily closes): 1.0 = fairly priced, above 1.5 = options priced for a bigger move than usual
    iv_chg_day_pct    ATM IV now against the first ATM IV recorded today, %: positive = options got dearer since the morning (a jump around news, or fear)
    iv_skew           put IV minus call IV at the ATM strike, vol points: positive = puts dearer than calls (protection being bought)
    iv_expensive      1 when iv_rank >= 80 or iv_vs_hv >= 1.5 (either one); 0 otherwise; blank when neither could be worked out
    iv_vs_dir         the skew in our direction: positive = the market is paying up for protection on the side we are betting on (put dearer for a put, call dearer for a call)

The nightly shadow scoreboard splits trades by iv_expensive (and treats it as a would-block rule), so after a few weeks it says whether paying up for IV hurt.
"""

from __future__ import annotations

import csv
import math
import statistics as st
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
RANK_HIGH, HV_HIGH = 80.0, 1.5
HV_DAYS = 20
_HV: dict[str, Any] = {"root": None, "day": "", "data": {}}


def _closes(root: Path) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = {}
    try:
        with (root / "data" / "nse_daily" / "stock_daily.csv").open(encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                try:
                    out.setdefault(r["symbol"], []).append((r["day"], float(r["close"])))
                except (KeyError, ValueError):
                    continue
    except OSError:
        pass
    return {k: sorted(v) for k, v in out.items()}


def realised_vol(symbol: str, today: str, root: Path = ROOT) -> float | None:
    """Annualised 20-day realised volatility, % (std of daily log returns x sqrt(252)), from closes before `today`. None with fewer than 15 returns."""
    if _HV["root"] != str(root) or _HV["day"] != today:
        _HV.update(root=str(root), day=today, data=_closes(root))
    v = [c for d, c in _HV["data"].get(symbol, []) if d < today][-(HV_DAYS + 1):]
    r = [math.log(b / a) for a, b in zip(v, v[1:]) if a > 0 and b > 0]
    if len(r) < 15:
        return None
    return st.pstdev(r) * math.sqrt(252) * 100.0


def tags(snapshot: Any, direction: str, px: float, root: Path = ROOT, today: str | None = None) -> dict[str, Any]:
    """The iv_ tags for a chain snapshot (the object options_tags already holds: .strikes with .call / .put legs carrying .iv, .symbol). {} when no IV is available."""
    try:
        today = today or date.today().isoformat()
        strikes = [s for s in snapshot.strikes if s.call or s.put]
        if not strikes or px <= 0:
            return {}
        atm = min(strikes, key=lambda s: abs(s.strike - px))
        civ = float(getattr(atm.call, "iv", 0) or 0) if atm.call else 0.0
        piv = float(getattr(atm.put, "iv", 0) or 0) if atm.put else 0.0
        iv = (civ + piv) / 2.0 if civ > 0 and piv > 0 else max(civ, piv) or float(getattr(snapshot, "atm_iv_hint", 0) or 0)
        if iv <= 0:
            return {}
        out: dict[str, Any] = {"iv_atm": round(iv, 2)}
        sym = str(getattr(snapshot, "symbol", "") or "")
        bull = str(direction).upper() == "BULLISH"
        if civ > 0 and piv > 0:
            skew = piv - civ
            out["iv_skew"] = round(skew, 2)
            out["iv_vs_dir"] = round(-skew if bull else skew, 2)
        rank = hv = None
        if sym:
            import iv_history

            rank = iv_history.rank(sym, iv, root=root)
            if rank is not None:
                out["iv_rank"] = rank
            hist = iv_history.load(sym, root)
            first_today = next((v for d, v in hist if d == today), None)
            if first_today and first_today > 0:
                out["iv_chg_day_pct"] = round((iv / first_today - 1.0) * 100.0, 1)
            hv = realised_vol(sym, today, root)
            if hv:
                out["iv_vs_hv"] = round(iv / hv, 2)
        if rank is not None or hv:
            out["iv_expensive"] = int((rank is not None and rank >= RANK_HIGH) or (hv is not None and iv / hv >= HV_HIGH))
        return out
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}
