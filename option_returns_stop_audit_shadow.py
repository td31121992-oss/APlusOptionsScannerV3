"""
APlusOptionsScannerV3: read-only option stop/target shadow audit.

This script does NOT modify production trading rules or overwrite the original
option_returns.json/.md. It fetches historical option candles via the existing
local Dhan auth resolver and writes uniquely named shadow reports.

Run from the project root:
  .venv\Scripts\python.exe option_returns_stop_audit_shadow.py --day 2026-10-26

Notes:
- OHLC candles cannot establish exact intrabar order or executable fills.
- Timestamp convention is not presumed. Two sensitivity scenarios are emitted.
- ENTRY_SLIP is an explicit 1% premium uplift assumption, not measured spread.
- Existing option_returns reports are read for comparison only.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
RATE_SLEEP = 0.80
ENTRY_SLIP = 1.01
TARGET = 0.30
STOP = 0.25
SCENARIOS = ("timestamp_is_candle_start", "timestamp_is_candle_end")


def classify(candles: list[dict[str, Any]], ready_minute: int, scenario: str) -> dict[str, Any]:
    """
    Sensitivity scenarios:
    - timestamp_is_candle_start: timestamp labels candle open; enter at OPEN of
      first candle whose label is >= signal-ready time. Include that candle's
      high/low in exit checks because entry is assumed at its open.
    - timestamp_is_candle_end: timestamp labels candle close; enter at CLOSE of
      first candle whose label is >= signal-ready time. Only later candles are
      used for exit checks.
    Neither convention is asserted as verified by this script.
    """
    candidates = [c for c in candles if c["minute"] >= ready_minute]
    if not candidates:
        return empty_result(scenario, "NO_CANDLE_AT_OR_AFTER_SIGNAL")

    entry_candle = candidates[0]
    if scenario == "timestamp_is_candle_start":
        entry_field = "open"
        rest = candidates
    else:
        entry_field = "close"
        rest = candidates[1:]

    entry_raw = float(entry_candle[entry_field])
    if entry_raw <= 0 or not rest:
        return {
            **empty_result(scenario, "INVALID_ENTRY_OR_TOO_FEW_POST_ENTRY_CANDLES"),
            "entry_time": entry_candle["time"],
        }

    entry = entry_raw * ENTRY_SLIP
    target_px = entry * (1 + TARGET)
    stop_px = entry * (1 - STOP)
    best = max(float(c["high"]) for c in rest) / entry - 1
    worst = min(float(c["low"]) for c in rest) / entry - 1

    for c in rest:
        hit_target = float(c["high"]) >= target_px
        hit_stop = float(c["low"]) <= stop_px
        if hit_target and hit_stop:
            return {
                "timing_scenario": scenario,
                "status": "SAME_CANDLE_AMBIGUOUS",
                "entry": round(entry, 4),
                "entry_time": entry_candle["time"],
                "exit_time": c["time"],
                "exit_reason": "STOP_AND_TARGET_TOUCHED_IN_SAME_CANDLE",
                "return_pct": None,
                "best_after_entry_pct": round(best * 100, 2),
                "worst_after_entry_pct": round(worst * 100, 2),
            }
        if hit_stop:
            return {
                "timing_scenario": scenario,
                "status": "STOP_BEFORE_TARGET",
                "entry": round(entry, 4),
                "entry_time": entry_candle["time"],
                "exit_time": c["time"],
                "exit_reason": "STOP",
                "return_pct": round(-STOP * 100, 2),
                "best_after_entry_pct": round(best * 100, 2),
                "worst_after_entry_pct": round(worst * 100, 2),
            }
        if hit_target:
            return {
                "timing_scenario": scenario,
                "status": "TARGET_BEFORE_STOP",
                "entry": round(entry, 4),
                "entry_time": entry_candle["time"],
                "exit_time": c["time"],
                "exit_reason": "TARGET",
                "return_pct": round(TARGET * 100, 2),
                "best_after_entry_pct": round(best * 100, 2),
                "worst_after_entry_pct": round(worst * 100, 2),
            }

    last = rest[-1]
    close_return = (float(last["close"]) / entry - 1) * 100
    return {
        "timing_scenario": scenario,
        "status": "NEITHER_HIT",
        "entry": round(entry, 4),
        "entry_time": entry_candle["time"],
        "exit_time": last["time"],
        "exit_reason": "LAST_AVAILABLE_CANDLE_CLOSE",
        "return_pct": round(close_return, 2),
        "best_after_entry_pct": round(best * 100, 2),
        "worst_after_entry_pct": round(worst * 100, 2),
    }


def empty_result(scenario: str, detail: str) -> dict[str, Any]:
    return {
        "timing_scenario": scenario,
        "status": "DATA_INSUFFICIENT",
        "entry": None,
        "entry_time": None,
        "exit_time": None,
        "exit_reason": detail,
        "return_pct": None,
        "best_after_entry_pct": None,
        "worst_after_entry_pct": None,
    }


def next_output_path(folder: Path, stem: str, suffix: str) -> Path:
    candidate = folder / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = folder / f"{stem}_{stamp}{suffix}"
    n = 2
    while candidate.exists():
        candidate = folder / f"{stem}_{stamp}_{n}{suffix}"
        n += 1
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default="2026-10-26")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    day = args.day
    date.fromisoformat(day)

    folder = root / "data" / "missed_opportunities" / day
    signals_path = folder / "signals.csv"
    original_json = folder / "option_returns.json"
    master_path = root / "data" / "cache" / "api-scrip-master-detailed.csv"

    missing = [str(p) for p in (signals_path, master_path) if not p.exists()]
    if missing:
        print("Required input missing:")
        for item in missing:
            print(" -", item)
        return 2

    with signals_path.open(encoding="utf-8-sig", newline="") as f:
        signals = list(csv.DictReader(f))
    signals = [s for s in signals if s.get("symbol") and s.get("direction") and s.get("first_ready")]

    original_rows: list[dict[str, Any]] = []
    if original_json.exists():
        try:
            original_rows = json.loads(original_json.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"Could not parse original report for comparison: {type(exc).__name__}: {exc}")
            return 2
    original_lookup = {
        (str(r.get("symbol", "")).upper(), str(r.get("dir", "")).upper(), str(r.get("kind", "")).upper()): r
        for r in original_rows
    }

    master = pd.read_csv(
        master_path,
        low_memory=False,
        usecols=["SECURITY_ID", "INSTRUMENT", "UNDERLYING_SYMBOL", "SM_EXPIRY_DATE", "STRIKE_PRICE", "OPTION_TYPE"],
    )
    master = master[master["INSTRUMENT"].astype(str).eq("OPTSTK")].copy()
    master["exp"] = master["SM_EXPIRY_DATE"].astype(str).str[:10]
    master["UNDERLYING_SYMBOL"] = master["UNDERLYING_SYMBOL"].astype(str).str.upper()
    master["OPTION_TYPE"] = master["OPTION_TYPE"].astype(str).str.upper()

    load_dotenv(root / ".env")
    sys.path.insert(0, str(root))
    from dhan_auth import resolve_access_token

    client_id = os.getenv("DHAN_CLIENT_ID", "").strip()
    token = resolve_access_token(
        project_root=root,
        client_id=client_id,
        env_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip(),
    )
    if not client_id or not token:
        print("Dhan authentication could not be resolved locally. No credentials were displayed.")
        return 3

    headers = {
        "access-token": token,
        "client-id": client_id,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    session = requests.Session()
    last_call = [0.0]
    cache: dict[str, list[dict[str, Any]]] = {}
    result_rows: list[dict[str, Any]] = []
    fetched_contracts = 0

    def fetch(security_id: int) -> list[dict[str, Any]]:
        nonlocal fetched_contracts
        key = str(security_id)
        if key in cache:
            return cache[key]
        for attempt in range(4):
            time.sleep(max(0.0, RATE_SLEEP - (time.time() - last_call[0])))
            last_call[0] = time.time()
            try:
                response = session.post(
                    "https://api.dhan.co/v2/charts/intraday",
                    headers=headers,
                    timeout=35,
                    json={
                        "securityId": key,
                        "exchangeSegment": "NSE_FNO",
                        "instrument": "OPTSTK",
                        "interval": "5",
                        "oi": False,
                        "fromDate": f"{day} 09:00:00",
                        "toDate": f"{(date.fromisoformat(day) + timedelta(days=1)).isoformat()} 15:30:00",
                    },
                )
            except requests.RequestException:
                if attempt == 3:
                    cache[key] = []
                    return []
                time.sleep(2 * (attempt + 1))
                continue
            if response.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            if response.status_code != 200:
                cache[key] = []
                return []
            try:
                data = response.json()
                idx = pd.to_datetime(data.get("timestamp") or [], unit="s", utc=True).tz_convert("Asia/Kolkata")
                candles = []
                for ts, op, hi, lo, cl in zip(
                    idx,
                    data.get("open", []),
                    data.get("high", []),
                    data.get("low", []),
                    data.get("close", []),
                ):
                    if ts.date().isoformat() == day:
                        candles.append({
                            "minute": int(ts.hour * 60 + ts.minute),
                            "time": ts.strftime("%H:%M"),
                            "open": float(op),
                            "high": float(hi),
                            "low": float(lo),
                            "close": float(cl),
                        })
                candles.sort(key=lambda c: c["minute"])
                cache[key] = candles
                fetched_contracts += 1
                return candles
            except (ValueError, TypeError, KeyError):
                cache[key] = []
                return []
        cache[key] = []
        return []

    for idx, signal in enumerate(signals, 1):
        symbol = str(signal["symbol"]).upper()
        direction = str(signal["direction"]).upper()
        side = "CE" if direction == "BULLISH" else "PE"
        try:
            spot = float(signal["entry_price"])
            hh, mm = (int(v) for v in signal["first_ready"].split(":"))
            ready_minute = hh * 60 + mm
        except (ValueError, TypeError, AttributeError):
            for kind in ("ATM", "OTM1"):
                result_rows.append({
                    "symbol": symbol, "dir": direction, "kind": kind,
                    "ready": signal.get("first_ready", ""),
                    "status": "DATA_INSUFFICIENT", "detail": "INVALID_SIGNAL_FIELDS",
                })
            continue

        sub = master[
            master["UNDERLYING_SYMBOL"].eq(symbol) & master["OPTION_TYPE"].eq(side)
        ]
        expiries = sorted(e for e in sub["exp"].unique() if e >= day and e not in ("", "nan", "None"))
        if not expiries:
            for kind in ("ATM", "OTM1"):
                result_rows.append({
                    "symbol": symbol, "dir": direction, "kind": kind,
                    "ready": signal["first_ready"], "status": "DATA_INSUFFICIENT",
                    "detail": "NO_ELIGIBLE_OPTION_EXPIRY",
                })
            continue

        sub = sub[sub["exp"].eq(expiries[0])]
        strikes = sorted(float(x) for x in sub["STRIKE_PRICE"].dropna().unique())
        if not strikes:
            continue
        atm = min(strikes, key=lambda strike: abs(strike - spot))
        strike_index = strikes.index(atm)
        otm = strikes[min(strike_index + 1, len(strikes) - 1)] if side == "CE" else strikes[max(strike_index - 1, 0)]

        for kind, strike in (("ATM", atm), ("OTM1", otm)):
            contract = sub[sub["STRIKE_PRICE"].astype(float).eq(float(strike))]
            common = {
                "day": day, "symbol": symbol, "dir": direction, "fate": signal.get("fate", ""),
                "ready": signal["first_ready"], "strike": strike, "kind": kind,
                "signal_entry_price": spot,
                "original_report_entry": original_lookup.get((symbol, direction, kind), {}).get("entry"),
                "original_report_best_pct": original_lookup.get((symbol, direction, kind), {}).get("best"),
                "original_report_worst_pct": original_lookup.get((symbol, direction, kind), {}).get("worst"),
                "original_report_close_pct": original_lookup.get((symbol, direction, kind), {}).get("close"),
                "original_report_target_time": original_lookup.get((symbol, direction, kind), {}).get("t_target"),
                "original_report_stop_first": original_lookup.get((symbol, direction, kind), {}).get("stop_first"),
            }
            if contract.empty:
                result_rows.append({**common, "status": "DATA_INSUFFICIENT", "detail": "CONTRACT_NOT_FOUND"})
                continue
            security_id = int(contract.iloc[0]["SECURITY_ID"])
            candles = fetch(security_id)
            if len(candles) < 2:
                result_rows.append({
                    **common, "security_id": security_id, "status": "DATA_INSUFFICIENT",
                    "detail": "NO_OR_TOO_FEW_HISTORICAL_CANDLES",
                })
                continue

            for scenario in SCENARIOS:
                outcome = classify(candles, ready_minute, scenario)
                result_rows.append({
                    **common,
                    "security_id": security_id,
                    "timestamp_convention_verified": False,
                    "entry_uplift_assumption_pct": (ENTRY_SLIP - 1) * 100,
                    "target_pct": TARGET * 100,
                    "stop_pct": STOP * 100,
                    "fees_and_bid_ask_included": False,
                    **outcome,
                })
        if idx % 10 == 0:
            print(f"Processed {idx}/{len(signals)} signals; unique option contracts fetched: {fetched_contracts}")

    # Make new names every run; never overwrite original or previous shadow reports.
    stem = "option_returns_stop_audit_shadow"
    json_path = next_output_path(folder, stem, ".json")
    csv_path = next_output_path(folder, stem, ".csv")
    md_path = next_output_path(folder, stem, ".md")

    json_path.write_text(json.dumps(result_rows, indent=2), encoding="utf-8")
    pd.DataFrame(result_rows).to_csv(csv_path, index=False, encoding="utf-8-sig")

    statuses: dict[str, int] = {}
    for row in result_rows:
        status = str(row.get("status", "UNKNOWN"))
        statuses[status] = statuses.get(status, 0) + 1
    lines = [
        f"# Shadow option stop/target audit — {day}",
        "",
        "**Research-only audit.** Production strategy was not modified. Original option-return reports were read for comparison and not overwritten.",
        "",
        "## Limitations",
        "- Timestamp convention is not verified by this script; two interpretations are reported as sensitivity scenarios.",
        "- A 1% entry uplift is an assumption, not a measured spread or guaranteed fill.",
        "- OHLC candles cannot establish intrabar order if stop and target are touched in the same candle.",
        "- Fees, taxes, market impact, liquidity and bid/ask execution are not included.",
        "- Results are simulations, not realized P&L or trading advice.",
        "",
        "## Status counts",
        "",
        "| Status | Rows |",
        "|---|---:|",
    ]
    for status, count in sorted(statuses.items()):
        lines.append(f"| {status} | {count} |")
    lines += [
        "",
        "## Contract-level results",
        "",
        "| Symbol | Direction | Kind | Ready | Timing scenario | Status | Entry | Exit time | Return % | Original best % | Original worst % |",
        "|---|---|---|---|---|---|---:|---|---:|---:|---:|",
    ]
    for r in result_rows:
        lines.append(
            f"| {r.get('symbol','')} | {r.get('dir','')} | {r.get('kind','')} | {r.get('ready','')} | "
            f"{r.get('timing_scenario','-')} | {r.get('status','')} | {r.get('entry','')} | "
            f"{r.get('exit_time','')} | {r.get('return_pct','')} | "
            f"{r.get('original_report_best_pct','')} | {r.get('original_report_worst_pct','')} |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "Do not promote any rule based on this audit alone. First verify the broker's timestamp convention, reconcile all signals and contracts, then validate the same exit rules on a larger out-of-sample dataset and a complete paper-trade ledger.",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\nSHADOW AUDIT COMPLETE")
    print(f"Signals read: {len(signals)}")
    print(f"Unique option contracts fetched: {fetched_contracts}")
    print(f"Result rows: {len(result_rows)}")
    print("Status counts:")
    for status, count in sorted(statuses.items()):
        print(f"  {status}: {count}")
    print(f"\nJSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print(f"MD:   {md_path}")
    print("\nOriginal option_returns.json/.md were not modified.")
    print("Timestamp convention remains explicitly unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
