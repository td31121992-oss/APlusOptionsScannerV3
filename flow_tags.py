"""Three 'flow' shadow tags at entry (recorded on the candidate / trade, never used to allow or block anything).

    Gamma pressure (from the option chain: gamma x open interest per strike, calls + puts, strikes within +-GAMMA_BAND_PCT of the stock)
        fp_gamma_wall            strike with the most gamma x OI (dealers hedge hardest there, so price tends to stick / pin)
        fp_gamma_wall_dist_pct   distance from the stock to that strike, % (signed: + = above the stock)
        fp_gamma_ahead_strike    the first listed strike beyond the stock in OUR direction (below for puts, above for calls)
        fp_gamma_ahead_share     gamma x OI at that strike / the biggest strike's, 0..1 (low = no gamma pressure in our way)

    Constant OI (the traded option's own open interest, compared with our own earlier look at the same contract, 5..30 minutes back)
        fp_oi_win_min            minutes between the two looks
        fp_oi_win_pct            OI change over that window, % (near 0 = constant: moves are trading, not new positions)
        fp_oi_flat               True when |change| < OI_FLAT_PCT

    Linear CVD (from the recorded ticks, only for the symbols tick_recorder.py records; see footprint_lite.py)
        fp_cvd_r2                how straight the cumulative delta line is over the last CVD_BARS 5-minute bars (R^2 of a straight-line fit, 0..1)
        fp_cvd_dir               cumulative delta change over the window in OUR direction / traded volume, -1..1 (positive = buyers push calls, sellers push puts)
        fp_cvd_linear            True when r2 >= 0.8 and the direction agrees with ours
"""

from __future__ import annotations

import csv
import gzip
import time
from collections import deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
GAMMA_BAND_PCT = 5.0
ITM_PCT = 0.5
OI_FLAT_PCT = 1.0
OI_MIN_WINDOW_MIN, OI_MAX_WINDOW_MIN = 5.0, 30.0
CVD_BARS = 12
CVD_LINEAR_R2 = 0.8
_oi_seen: dict[tuple[str, float, str], deque] = {}


def _bull(direction: str) -> bool:
    return str(direction).upper() == "BULLISH"


def gamma_tags(snapshot: Any, direction: str, px: float) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        import greeks

        expiry = getattr(snapshot, "expiry", "")
        near = [s for s in snapshot.strikes if abs(s.strike / px - 1.0) * 100.0 <= GAMMA_BAND_PCT]
        gx: dict[float, float] = {}
        for s in near:
            for leg, kind in ((s.call, "CE"), (s.put, "PE")):
                if not leg or not (getattr(leg, "oi", 0) or 0) or not (getattr(leg, "ltp", 0) or 0):
                    continue
                g = greeks.greeks_at_entry(px, s.strike, expiry, kind, float(leg.ltp), float(getattr(leg, "iv", 0) or 0) or None)
                if g:
                    gx[s.strike] = gx.get(s.strike, 0.0) + float(g["gk_gamma"]) * float(leg.oi)
        if not gx:
            return out
        wall = max(gx, key=gx.get)
        out["fp_gamma_wall"], out["fp_gamma_wall_dist_pct"] = wall, round((wall / px - 1.0) * 100.0, 2)
        strikes = sorted(s.strike for s in snapshot.strikes)
        ahead = [k for k in strikes if (k > px if _bull(direction) else k < px)]
        if ahead:
            nxt = min(ahead) if _bull(direction) else max(ahead)
            out["fp_gamma_ahead_strike"] = nxt
            out["fp_gamma_ahead_share"] = round(gx.get(nxt, 0.0) / gx[wall], 2)
    except Exception:                                      # noqa: BLE001 - a shadow tag must never break an entry
        return {}
    return out


def oi_window_tags(snapshot: Any, direction: str, px: float, now: float | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        now = time.time() if now is None else now
        bull = _bull(direction)
        want = px * (1.0 - ITM_PCT / 100.0 if bull else 1.0 + ITM_PCT / 100.0)
        cands = [(abs(s.strike - want), s) for s in snapshot.strikes if (s.call if bull else s.put)]
        if not cands:
            return out
        st = min(cands, key=lambda x: x[0])[1]
        leg = st.call if bull else st.put
        oi = float(getattr(leg, "oi", 0) or 0)
        key = (str(getattr(snapshot, "symbol", "")), float(st.strike), "CE" if bull else "PE")
        hist = _oi_seen.setdefault(key, deque(maxlen=60))
        while hist and now - hist[0][0] > OI_MAX_WINDOW_MIN * 60:
            hist.popleft()
        old = [h for h in hist if now - h[0] >= OI_MIN_WINDOW_MIN * 60]
        if old and old[-1][1] > 0 and oi > 0:
            t0, oi0 = old[-1]
            out["fp_oi_win_min"] = round((now - t0) / 60.0, 1)
            out["fp_oi_win_pct"] = round((oi / oi0 - 1.0) * 100.0, 2)
            out["fp_oi_flat"] = bool(abs(out["fp_oi_win_pct"]) < OI_FLAT_PCT)
        if oi > 0 and (not hist or now - hist[-1][0] >= 60):
            hist.append((now, oi))
    except Exception:                                      # noqa: BLE001
        return {}
    return out


def _read_ticks(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as h:
            for r in csv.DictReader(h):
                rows.append(r)
    except (OSError, EOFError):                            # the recorder is still writing: keep what was read
        pass
    return rows


def cvd_line_stats(bars: list[dict[str, Any]], direction: str) -> dict[str, Any]:
    """bars from footprint_lite.candles_from_ticks (ascending). Uses the last CVD_BARS of them."""
    out: dict[str, Any] = {}
    last = bars[-CVD_BARS:]
    if len(last) < 4:
        return out
    cum = [float(b["cum_delta"]) for b in last]
    n = len(cum)
    mx, my = (n - 1) / 2.0, sum(cum) / n
    sxx = sum((i - mx) ** 2 for i in range(n))
    sxy = sum((i - mx) * (c - my) for i, c in enumerate(cum))
    syy = sum((c - my) ** 2 for c in cum)
    r2 = (sxy * sxy) / (sxx * syy) if sxx > 0 and syy > 0 else 0.0
    vol = sum(float(b["buy_vol"]) + float(b["sell_vol"]) for b in last)
    move = float(last[-1]["cum_delta"]) - float(last[0]["cum_delta"]) + float(last[0]["delta"])
    sign = 1.0 if _bull(direction) else -1.0
    dirn = sign * move / vol if vol > 0 else 0.0
    out["fp_cvd_r2"], out["fp_cvd_dir"] = round(r2, 2), round(dirn, 3)
    out["fp_cvd_linear"] = bool(r2 >= CVD_LINEAR_R2 and dirn > 0)
    return out


def cvd_tags(symbol: str, direction: str, day: str, root: Path = ROOT) -> dict[str, Any]:
    try:
        path = root / "data" / "ticks" / day / f"{symbol}.csv.gz"
        if not path.exists():
            return {}
        import footprint_lite

        return cvd_line_stats(footprint_lite.candles_from_ticks(_read_ticks(path), day, symbol), direction)
    except Exception:                                      # noqa: BLE001
        return {}
