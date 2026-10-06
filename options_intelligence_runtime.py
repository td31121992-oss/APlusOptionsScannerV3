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
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config import AppConfig
from core.dhan_client import DhanClient
from core.instrument_loader import InstrumentLoader
from options_intelligence_data_layer import MAX_SYMBOLS_LIMIT, _safe_error, collect_once, resolve_symbols

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
    target_day = now.date()
    candidate = datetime.combine(target_day, target, tzinfo=IST)
    if candidate <= now:
        target_day += timedelta(days=1)
        candidate = datetime.combine(target_day, target, tzinfo=IST)
    while candidate.weekday() >= 5:
        target_day += timedelta(days=1)
        candidate = datetime.combine(target_day, target, tzinfo=IST)
    return max(0.0, (candidate - now).total_seconds())


def _cycle_status(successes: int, failures: int) -> str:
    if successes > 0 and failures == 0:
        return "HEALTHY"
    if successes > 0:
        return "DEGRADED"
    return "FAILED"


def _should_reconnect_after_failed_cycle(consecutive_failed_cycles: int, errors: list[dict[str, Any]]) -> bool:
    transient = {"NETWORK", "TIMEOUT", "EMPTY_RESPONSE"}
    return consecutive_failed_cycles >= 2 and any(
        item.get("failure_type") in transient for item in errors
    )


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

    if args.max_symbols < 1 or args.max_symbols > MAX_SYMBOLS_LIMIT or args.cycle_delay < 1:
        parser.error(f"max-symbols must be 1..{MAX_SYMBOLS_LIMIT} and cycle-delay must be >= 1")
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
            symbols_count=len(symbols), symbols_requested=len(symbols),
            symbols_preview=symbols[:10], consecutive_runtime_failures=0,
            consecutive_failed_cycles=0, last_successful_capture=None)

    consecutive_failed_cycles = 0
    consecutive_runtime_failures = 0
    last_successful_capture = None
    while True:
        now = _now()
        if not _in_session(now, start, end):
            wait = _seconds_until(now, start)
            _health(args.health_file, status="WAITING", session_start=args.session_start,
                    session_end=args.session_end, max_symbols=args.max_symbols,
                    symbols_count=len(symbols), symbols_requested=len(symbols), pid=None,
                    consecutive_runtime_failures=consecutive_runtime_failures,
                    consecutive_failed_cycles=consecutive_failed_cycles,
                    last_successful_capture=last_successful_capture)
            time.sleep(min(max(wait, 30.0), 300.0))
            continue

        cycle = 0
        consecutive_runtime_failures = 0
        consecutive_failed_cycles = 0
        while _in_session(_now(), start, end):
            cycle += 1
            started = time.monotonic()
            try:
                _health(args.health_file, status="CONNECTING", cycle=cycle,
                        max_symbols=args.max_symbols, symbols_count=len(symbols),
                        symbols_requested=len(symbols))
                with DhanClient(cfg.dhan) as client:
                    _health(args.health_file, status="RUNNING", cycle=cycle,
                            max_symbols=args.max_symbols, symbols_count=len(symbols),
                            symbols_requested=len(symbols))
                    while _in_session(_now(), start, end):
                        cycle_started = time.monotonic()
                        result = collect_once(client, loader, symbols)
                        elapsed = time.monotonic() - cycle_started
                        if result["symbols_success"] > 0:
                            consecutive_failed_cycles = 0
                            consecutive_runtime_failures = 0
                            last_successful_capture = result.get("last_successful_capture") or result["captured_at"]
                        else:
                            consecutive_failed_cycles += 1
                        cycle_status = _cycle_status(result["symbols_success"], result["symbols_failed"])
                        _health(
                            args.health_file,
                            status=cycle_status,
                            cycle=cycle,
                            max_symbols=args.max_symbols,
                            symbols_count=len(symbols),
                            symbols_requested=result["symbols_requested"],
                            symbols_success=result["symbols_success"],
                            symbols_failed=result["symbols_failed"],
                            rows_written=result["rows_written"],
                            failure_classifications=result["failure_classifications"],
                            symbol_failures=result["errors"],
                            cycle_elapsed_seconds=round(elapsed, 2),
                            last_captured_at=result["captured_at"],
                            last_successful_capture=last_successful_capture,
                            consecutive_runtime_failures=consecutive_runtime_failures,
                            consecutive_failed_cycles=consecutive_failed_cycles,
                        )
                        print(
                            f"[RUNTIME CYCLE {cycle}] status={cycle_status} requested={result['symbols_requested']} "
                            f"success={result['symbols_success']} "
                            f"failed={result['symbols_failed']} rows={result['rows_written']} "
                            f"elapsed={elapsed:.1f}s",
                            flush=True,
                        )
                        if _should_reconnect_after_failed_cycle(consecutive_failed_cycles, result.get("errors", [])):
                            raise RuntimeError("two consecutive zero-success collection cycles; reconnecting client")
                        cycle += 1
                        remaining = args.cycle_delay
                        while remaining > 0 and _in_session(_now(), start, end):
                            time.sleep(min(5.0, remaining))
                            remaining -= 5.0
                _health(args.health_file, status="STOPPED_AFTER_MARKET",
                        cycle=cycle, max_symbols=args.max_symbols)
            except KeyboardInterrupt:
                _health(args.health_file, status="STOPPED_MANUALLY", max_symbols=args.max_symbols,
                        last_successful_capture=last_successful_capture)
                return 0
            except Exception as exc:
                consecutive_runtime_failures += 1
                _health(
                    args.health_file,
                    status="RECONNECTING",
                    cycle=cycle,
                    max_symbols=args.max_symbols,
                    symbols_count=len(symbols),
                    symbols_requested=len(symbols),
                    consecutive_runtime_failures=consecutive_runtime_failures,
                    error=_safe_error(exc),
                    last_successful_capture=last_successful_capture,
                )
                print(
                    f"[RUNTIME ERROR] {_safe_error(exc)}; "
                    f"reconnecting in {args.reconnect_delay:.1f}s",
                    flush=True,
                )
                time.sleep(args.reconnect_delay)
            finally:
                _ = started

        _health(args.health_file, status="MARKET_CLOSED",
                cycle=cycle, max_symbols=args.max_symbols,
                consecutive_runtime_failures=consecutive_runtime_failures,
                consecutive_failed_cycles=consecutive_failed_cycles,
                last_successful_capture=last_successful_capture)
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
