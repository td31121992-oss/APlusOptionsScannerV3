"""
APlus Options Intelligence production runtime.

Separate, read-only service around options_intelligence_data_layer.collect_once.
It never imports order/trade APIs. It controls market hours, reconnects Dhan
after runtime failures, writes health evidence, and keeps the existing scanner
process independent.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

from config import AppConfig
from core.dhan_client import DhanClient
from core.instrument_loader import InstrumentLoader
from options_intelligence_data_layer import collect_once, resolve_symbols

ROOT = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")
DEFAULT_HEALTH = ROOT / "data" / "options_intelligence" / "runtime_health.json"


def _clock(value: str) -> clock_time:
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError("time must be HH:MM or HH:MM:SS")
    return clock_time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) == 3 else 0)


def _now() -> datetime:
    return datetime.now(IST)


def _in_session(now: datetime, start: clock_time, end: clock_time) -> bool:
    return now.weekday() < 5 and start <= now.time() < end


def _seconds_until(now: datetime, target: clock_time) -> float:
    candidate = now.replace(hour=target.hour, minute=target.minute, second=target.second, microsecond=0)
    if candidate <= now:
        candidate = candidate.replace(day=candidate.day + 1)
    while candidate.weekday() >= 5:
        candidate = candidate.replace(day=candidate.day + 1)
    return max(0.0, (candidate - now).total_seconds())


def _health(path: Path, **updates: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "service": "APlus Options Intelligence Runtime",
        "read_only": True,
        "trading_engine_untouched": True,
        "updated_at": _now().isoformat(),
        **updates,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the isolated APlus Options Intelligence collector.")
    parser.add_argument("--max-symbols", type=int, default=10)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--cycle-delay", type=float, default=60.0)
    parser.add_argument("--session-start", default="09:15")
    parser.add_argument("--session-end", default="15:30")
    parser.add_argument("--reconnect-delay", type=float, default=20.0)
    parser.add_argument("--health-file", type=Path, default=DEFAULT_HEALTH)
    args = parser.parse_args()

    if args.max_symbols < 1 or args.cycle_delay < 1:
        parser.error("max-symbols must be >= 1 and cycle-delay must be >= 1")
    start = _clock(args.session_start)
    end = _clock(args.session_end)
    if start >= end:
        parser.error("session-start must be before session-end")

    cfg = AppConfig.from_env()
    loader = InstrumentLoader(cfg).load(force_refresh=False)
    symbols = resolve_symbols(loader, args.symbols, args.max_symbols)
    if not symbols:
        _health(args.health_file, status="ERROR", error="No F&O symbols available")
        return 2

    _health(args.health_file, status="READY", session_start=args.session_start,
            session_end=args.session_end, max_symbols=args.max_symbols,
            symbols_count=len(symbols), symbols_preview=symbols[:10])

    while True:
        now = _now()
        if not _in_session(now, start, end):
            wait = _seconds_until(now, start)
            _health(args.health_file, status="WAITING", session_start=args.session_start,
                    session_end=args.session_end, max_symbols=args.max_symbols,
                    symbols_count=len(symbols), pid=None)
            time.sleep(min(max(wait, 30.0), 300.0))
            continue

        cycle = 0
        consecutive_runtime_failures = 0
        while _in_session(_now(), start, end):
            cycle += 1
            started = time.monotonic()
            try:
                _health(args.health_file, status="CONNECTING", cycle=cycle,
                        max_symbols=args.max_symbols, symbols_count=len(symbols))
                with DhanClient(cfg.dhan) as client:
                    _health(args.health_file, status="RUNNING", cycle=cycle,
                            max_symbols=args.max_symbols, symbols_count=len(symbols))
                    while _in_session(_now(), start, end):
                        cycle_started = time.monotonic()
                        result = collect_once(client, loader, symbols)
                        elapsed = time.monotonic() - cycle_started
                        consecutive_runtime_failures = 0
                        _health(
                            args.health_file,
                            status="HEALTHY",
                            cycle=cycle,
                            max_symbols=args.max_symbols,
                            symbols_count=len(symbols),
                            symbols_success=result["symbols_success"],
                            symbols_failed=result["symbols_failed"],
                            rows_written=result["rows_written"],
                            cycle_elapsed_seconds=round(elapsed, 2),
                            last_captured_at=result["captured_at"],
                            consecutive_runtime_failures=0,
                        )
                        print(
                            f"[RUNTIME CYCLE {cycle}] success={result['symbols_success']} "
                            f"failed={result['symbols_failed']} rows={result['rows_written']} "
                            f"elapsed={elapsed:.1f}s",
                            flush=True,
                        )
                        cycle += 1
                        remaining = args.cycle_delay
                        while remaining > 0 and _in_session(_now(), start, end):
                            time.sleep(min(5.0, remaining))
                            remaining -= 5.0
                _health(args.health_file, status="STOPPED_AFTER_MARKET",
                        cycle=cycle, max_symbols=args.max_symbols)
            except KeyboardInterrupt:
                _health(args.health_file, status="STOPPED_MANUALLY", max_symbols=args.max_symbols)
                return 0
            except Exception as exc:
                consecutive_runtime_failures += 1
                _health(
                    args.health_file,
                    status="RECONNECTING",
                    cycle=cycle,
                    max_symbols=args.max_symbols,
                    consecutive_runtime_failures=consecutive_runtime_failures,
                    error=f"{type(exc).__name__}: {exc}",
                )
                print(
                    f"[RUNTIME ERROR] {type(exc).__name__}: {exc}; "
                    f"reconnecting in {args.reconnect_delay:.1f}s",
                    flush=True,
                )
                time.sleep(args.reconnect_delay)
            finally:
                _ = started

        _health(args.health_file, status="MARKET_CLOSED",
                cycle=cycle, max_symbols=args.max_symbols)
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
