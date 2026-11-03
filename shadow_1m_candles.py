"""Offline 1-minute bars from APlus DATA-ONLY tick recordings.

This module does not connect to a broker or change the scanner. Stock and
option tick recorders continue to own collection; this builder is run after a
session to create separate shadow research artifacts. Volume-weighted LTP is
an estimate because a feed packet can summarize multiple trades.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

IST = timezone(timedelta(hours=5, minutes=30))
FIELDS = (
    "day", "symbol", "security_id", "bar_minute", "open", "high", "low",
    "close", "volume_delta", "volume_weighted_ltp_estimate", "tick_count",
    "quote_ticks", "crossed_quote_ticks", "last_valid_bid", "last_valid_ask",
    "last_valid_mid", "quality_flags",
)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _minute(value: Any) -> int | None:
    """Parse the recorder's local receive time (HH:MM:SS[.mmm]) to minute of day."""
    raw = str(value or "").strip()
    for fmt in ("%H:%M:%S.%f", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            pass
    return None


def aggregate_ticks(
    rows: Iterable[Mapping[str, Any]],
    *,
    day: str,
    symbol: str,
    security_id: str = "",
) -> list[dict[str, Any]]:
    """Aggregate observed ticks without filling gaps or inventing prices."""
    buckets: dict[int, dict[str, Any]] = {}
    for row in rows:
        minute = _minute(row.get("ts"))
        ltp = _number(row.get("ltp"))
        if minute is None or ltp is None or ltp <= 0:
            continue
        bar = buckets.get(minute)
        if bar is None:
            bar = {
                "day": day,
                "symbol": symbol,
                "security_id": security_id,
                "bar_minute": f"{minute // 60:02d}:{minute % 60:02d}",
                "open": ltp,
                "high": ltp,
                "low": ltp,
                "close": ltp,
                "volume_delta": 0.0,
                "_turnover": 0.0,
                "tick_count": 0,
                "quote_ticks": 0,
                "crossed_quote_ticks": 0,
                "last_valid_bid": None,
                "last_valid_ask": None,
                "last_valid_mid": None,
                "_flags": set(),
            }
            buckets[minute] = bar
        bar["high"] = max(bar["high"], ltp)
        bar["low"] = min(bar["low"], ltp)
        bar["close"] = ltp
        bar["tick_count"] += 1

        delta = _number(row.get("tq"))
        if delta is not None and delta >= 0:
            bar["volume_delta"] += delta
            bar["_turnover"] += ltp * delta
        elif row.get("tq") not in (None, ""):
            bar["_flags"].add("INVALID_VOLUME_DELTA")

        bid, ask = _number(row.get("bid")), _number(row.get("ask"))
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            if ask < bid:
                bar["crossed_quote_ticks"] += 1
            else:
                bar["quote_ticks"] += 1
                bar["last_valid_bid"] = bid
                bar["last_valid_ask"] = ask
                bar["last_valid_mid"] = (bid + ask) / 2.0

    result: list[dict[str, Any]] = []
    for minute in sorted(buckets):
        bar = buckets[minute]
        volume = bar["volume_delta"]
        bar["volume_weighted_ltp_estimate"] = bar["_turnover"] / volume if volume > 0 else None
        if volume <= 0:
            bar["_flags"].add("NO_RECORDED_VOLUME_DELTA")
        if bar["quote_ticks"] == 0:
            bar["_flags"].add("NO_VALID_BID_ASK")
        if bar["crossed_quote_ticks"]:
            bar["_flags"].add("CROSSED_QUOTES_OMITTED")
        for key in ("open", "high", "low", "close", "volume_delta", "volume_weighted_ltp_estimate",
                    "last_valid_bid", "last_valid_ask", "last_valid_mid"):
            value = bar.get(key)
            bar[key] = round(value, 6) if isinstance(value, (int, float)) else ""
        bar["quality_flags"] = ";".join(sorted(bar.pop("_flags")))
        bar.pop("_turnover")
        result.append(bar)
    return result


def _read_csv_gzip(path: Path) -> tuple[list[dict[str, str]], int, int]:
    """Read with tick_gz's non-mutating recovery path; return rows/members/damage."""
    import tick_gz

    text, members, damaged = tick_gz.read_text(path)
    return list(csv.DictReader(io.StringIO(text))), members, damaged


def _read_stream(folder: Path, day: str, stream: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    files = list(folder.glob("*.csv.gz")) if folder.exists() else []
    damaged_files = 0
    source_rows = 0
    skipped = 0
    for path in sorted(files):
        if stream == "stock":
            symbol, security_id = path.name[:-7], ""
        else:
            stem = path.name[:-7]
            security_id, sep, symbol = stem.partition("_")
            if not sep:
                security_id, symbol = "", stem
        try:
            rows, _members, damaged = _read_csv_gzip(path)
        except (OSError, EOFError, ValueError):
            damaged_files += 1
            continue
        if damaged:
            damaged_files += 1
        source_rows += len(rows)
        made = aggregate_ticks(rows, day=day, symbol=symbol, security_id=security_id)
        bars.extend(made)
        skipped += max(0, len(rows) - sum(int(b["tick_count"]) for b in made))
    bars.sort(key=lambda row: (row["symbol"], row["bar_minute"], row["security_id"]))
    return bars, {"files": len(files), "source_rows": source_rows, "bars": len(bars), "invalid_rows": skipped, "damaged_files": damaged_files}


def session_collection_complete(day: str, now: datetime) -> bool:
    """Whether the session's recorders should have closed their files."""
    if now.tzinfo is None or now.utcoffset() != timedelta(hours=5, minutes=30):
        raise ValueError("now must be timezone-aware IST")
    return date.fromisoformat(day) < now.date() or (date.fromisoformat(day) == now.date() and (now.hour, now.minute) >= (15, 33))


def build_day(root: Path, day: str, *, allow_partial: bool = False, now: datetime | None = None) -> Path:
    """Build closed-session files once; refuse to overwrite existing output."""
    date.fromisoformat(day)  # validate the supplied session date before any I/O
    current = now or datetime.now(IST)
    if not session_collection_complete(day, current) and not allow_partial:
        raise ValueError("Today's tick files may still be open; run after 15:33 IST or explicitly allow a partial snapshot")
    stock, stock_meta = _read_stream(root / "data" / "ticks" / day, day, "stock")
    options, option_meta = _read_stream(root / "data" / "option_ticks" / day, day, "option")
    if not stock and not options:
        raise FileNotFoundError(f"No usable tick data found for {day}")

    output = root / "data" / "shadow_1m" / day
    output.mkdir(parents=True, exist_ok=False)
    for name, rows in (("stocks_1m.csv", stock), ("options_1m.csv", options)):
        with (output / name).open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    (output / "manifest.json").write_text(json.dumps({"day": day, "timezone": "Asia/Kolkata", "source": "recorded receive-time ticks",
                                                       "volume_weighted_ltp_is_estimate": True,
                                                       "volume_delta_may_undercount_after_recorder_restart": True,
                                                       "stocks": stock_meta, "options": option_meta}, indent=2), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("day", nargs="?", default=date.today().isoformat(), help="Session date YYYY-MM-DD")
    parser.add_argument("--allow-partial", action="store_true", help="Allow reading today's still-open tick files")
    args = parser.parse_args()
    try:
        print(build_day(Path(__file__).resolve().parent, args.day, allow_partial=args.allow_partial))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
