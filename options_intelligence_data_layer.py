"""
APlus Options Intelligence Data Layer
-------------------------------------
Read-only collector for Dhan option-chain snapshots.

This module deliberately does NOT import or call any order/trading engine code.
It stores raw and normalized option-chain observations for later research,
feature engineering, backtesting, and validation.

Storage:
  data/options_intelligence/YYYY-MM-DD/
    option_chain_snapshots.jsonl   # one complete raw/normalized snapshot per call
    option_chain_rows.csv          # strike/side normalized observations
    collector_manifest.json        # run metadata and counters

Dhan's option-chain endpoint is intentionally throttled by the existing
DhanClient at ~0.34 requests/sec (~1 request every 3 seconds).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from config import AppConfig
from core.dhan_client import DhanClient
from core.instrument_loader import InstrumentLoader

ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data" / "options_intelligence"

CSV_FIELDS = (
    "captured_at",
    "symbol",
    "underlying_security_id",
    "expiry",
    "spot",
    "strike",
    "side",
    "option_security_id",
    "ltp",
    "average_price",
    "oi",
    "previous_oi",
    "oi_change",
    "volume",
    "previous_volume",
    "iv",
    "delta",
    "gamma",
    "theta",
    "vega",
    "bid",
    "bid_qty",
    "ask",
    "ask_qty",
    "previous_close",
)


def _num(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not x == x or x in (float("inf"), float("-inf")):
        return None
    return int(x) if x.is_integer() else x


def _chain_data(raw: Any) -> dict[str, Any]:
    """Find the nested Dhan mapping containing the option-chain 'oc' field."""
    if not isinstance(raw, dict):
        return {}
    queue: list[dict[str, Any]] = [raw]
    visited: set[int] = set()
    while queue:
        current = queue.pop(0)
        identity = id(current)
        if identity in visited:
            continue
        visited.add(identity)
        if isinstance(current.get("oc"), dict):
            return current
        for key, value in current.items():
            if isinstance(value, dict):
                queue.append(value)
    return {}


def _normalize_rows(
    *,
    captured_at: str,
    symbol: str,
    underlying_security_id: str,
    expiry: str,
    data: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    spot = _num(data.get("last_price"))
    chain = data.get("oc") or {}

    for raw_strike, entry in chain.items():
        try:
            strike = float(raw_strike)
        except (TypeError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue

        for side_key, side in (("ce", "CE"), ("pe", "PE")):
            leg = entry.get(side_key)
            if not isinstance(leg, dict):
                continue
            greeks = leg.get("greeks")
            greeks = greeks if isinstance(greeks, dict) else {}
            oi = _num(leg.get("oi"))
            previous_oi = _num(leg.get("previous_oi"))
            rows.append(
                {
                    "captured_at": captured_at,
                    "symbol": symbol,
                    "underlying_security_id": str(underlying_security_id),
                    "expiry": expiry,
                    "spot": spot,
                    "strike": strike,
                    "side": side,
                    "option_security_id": str(leg.get("security_id") or ""),
                    "ltp": _num(leg.get("last_price")),
                    "average_price": _num(leg.get("average_price")),
                    "oi": oi,
                    "previous_oi": previous_oi,
                    "oi_change": (
                        oi - previous_oi
                        if isinstance(oi, (int, float))
                        and isinstance(previous_oi, (int, float))
                        else None
                    ),
                    "volume": _num(leg.get("volume")),
                    "previous_volume": _num(leg.get("previous_volume")),
                    "iv": _num(leg.get("implied_volatility")),
                    "delta": _num(greeks.get("delta")),
                    "gamma": _num(greeks.get("gamma")),
                    "theta": _num(greeks.get("theta")),
                    "vega": _num(greeks.get("vega")),
                    "bid": _num(leg.get("top_bid_price")),
                    "bid_qty": _num(leg.get("top_bid_quantity")),
                    "ask": _num(leg.get("top_ask_price")),
                    "ask_qty": _num(leg.get("top_ask_quantity")),
                    "previous_close": _num(leg.get("previous_close_price")),
                }
            )
    return rows


def _write_snapshot(
    day_dir: Path,
    *,
    raw: Any,
    normalized_rows: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> None:
    day_dir.mkdir(parents=True, exist_ok=True)

    with (day_dir / "option_chain_snapshots.jsonl").open(
        "a", encoding="utf-8"
    ) as handle:
        handle.write(
            json.dumps(
                {
                    "metadata": metadata,
                    "data": raw,
                    "rows": normalized_rows,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )

    csv_path = day_dir / "option_chain_rows.csv"
    exists = csv_path.exists() and csv_path.stat().st_size > 0
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if not exists:
            writer.writeheader()
        for row in normalized_rows:
            writer.writerow({field: row.get(field) for field in CSV_FIELDS})


def _update_manifest(day_dir: Path, updates: dict[str, Any]) -> None:
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / "collector_manifest.json"
    current: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
        except Exception:
            current = {}
    current.update(updates)
    current["updated_at"] = datetime.now().astimezone().isoformat()
    path.write_text(
        json.dumps(current, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def collect_once(
    client: DhanClient,
    loader: InstrumentLoader,
    symbols: list[str],
) -> dict[str, Any]:
    captured_at = datetime.now().astimezone().isoformat()
    day_dir = DATA_ROOT / captured_at[:10]
    successes = 0
    failures = 0
    rows_written = 0
    errors: list[dict[str, str]] = []

    for symbol in symbols:
        symbol = symbol.strip().upper()
        if not symbol:
            continue

        underlying = loader.get(symbol)
        if underlying is None:
            failures += 1
            errors.append({"symbol": symbol, "error": "Not in F&O universe"})
            continue

        expiries = sorted(
            {
                str(getattr(contract, "expiry", "") or "")
                for contract in (getattr(underlying, "contracts", []) or [])
                if str(getattr(contract, "expiry", "") or "")
            }
        )
        if not expiries:
            failures += 1
            errors.append({"symbol": symbol, "error": "No active expiry"})
            continue

        today = date.today().isoformat()
        active_expiries = [item for item in expiries if item >= today]
        expiry = active_expiries[0] if active_expiries else expiries[-1]
        try:
            raw = client.get_option_chain(
                int(underlying.security_id),
                expiry,
                underlying.exchange_segment,
            )
            data = _chain_data(raw)
            rows = _normalize_rows(
                captured_at=captured_at,
                symbol=symbol,
                underlying_security_id=underlying.security_id,
                expiry=expiry,
                data=data,
            )
            if not rows:
                raise RuntimeError("Dhan returned no usable option-chain rows")

            _write_snapshot(
                day_dir,
                raw=raw,
                normalized_rows=rows,
                metadata={
                    "captured_at": captured_at,
                    "symbol": symbol,
                    "underlying_security_id": str(underlying.security_id),
                    "underlying_segment": underlying.exchange_segment,
                    "expiry": expiry,
                    "row_count": len(rows),
                },
            )
            successes += 1
            rows_written += len(rows)
            print(
                f"[OK] {symbol} expiry={expiry} "
                f"rows={len(rows)} captured_at={captured_at}",
                flush=True,
            )
        except Exception as exc:
            failures += 1
            errors.append(
                {
                    "symbol": symbol,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            print(
                f"[ERROR] {symbol}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )

    result = {
        "captured_at": captured_at,
        "symbols_requested": len(symbols),
        "symbols_success": successes,
        "symbols_failed": failures,
        "rows_written": rows_written,
        "errors": errors[-50:],
    }
    _update_manifest(
        day_dir,
        {
            "collector": "APlus Options Intelligence Data Layer",
            "schema_version": 1,
            "read_only": True,
            "symbols_requested": len(symbols),
            "last_cycle": result,
        },
    )
    return result


def resolve_symbols(
    loader: InstrumentLoader,
    raw_symbols: str,
    maximum: int,
) -> list[str]:
    if raw_symbols.strip():
        requested = [
            item.strip().upper()
            for item in raw_symbols.split(",")
            if item.strip()
        ]
        return list(dict.fromkeys(requested))

    universe = [item.symbol for item in loader.get_universe()]
    return universe[:maximum]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect read-only APlus option-chain intelligence data."
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols. Empty = first --max-symbols from F&O universe.",
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=30,
        help="Maximum symbols when --symbols is omitted.",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=1,
        help="Number of collection cycles. Use 0 for continuous collection.",
    )
    parser.add_argument(
        "--cycle-delay",
        type=float,
        default=15.0,
        help="Seconds between completed cycles.",
    )
    args = parser.parse_args()

    if args.max_symbols < 1:
        parser.error("--max-symbols must be >= 1")
    if args.cycles < 0:
        parser.error("--cycles must be >= 0")

    cfg = AppConfig.from_env()
    loader = InstrumentLoader(cfg).load(force_refresh=False)
    symbols = resolve_symbols(loader, args.symbols, args.max_symbols)
    if not symbols:
        print("No F&O symbols available.", file=sys.stderr)
        return 2

    print(
        f"APlus Options Intelligence Collector: {len(symbols)} symbols",
        flush=True,
    )
    print(
        "Read-only mode: no order/trade APIs are called.",
        flush=True,
    )

    with DhanClient(cfg.dhan) as client:
        cycle = 0
        while args.cycles == 0 or cycle < args.cycles:
            cycle += 1
            started = time.monotonic()
            result = collect_once(client, loader, symbols)
            elapsed = time.monotonic() - started
            print(
                f"[CYCLE {cycle}] success={result['symbols_success']} "
                f"failed={result['symbols_failed']} "
                f"rows={result['rows_written']} elapsed={elapsed:.1f}s",
                flush=True,
            )
            if args.cycles and cycle >= args.cycles:
                break
            time.sleep(max(0.0, args.cycle_delay))


if __name__ == "__main__":
    raise SystemExit(main())
