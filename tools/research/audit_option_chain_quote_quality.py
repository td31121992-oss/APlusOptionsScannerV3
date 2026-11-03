#!/usr/bin/env python3
"""Read-only quote-quality audit for option-response study contracts.

Reads the option-response observations and raw compressed option-chain snapshots.
Writes diagnostics only under data/option_response_shadow_20261026/.
No scanner, strategy, ledger, or source market-data file is modified.

The rules are diagnostic flags, not trading rules. LTP can be stale and need not
always sit between the current bid and ask; such cases require review, not
automatic claims of bad data.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OBSERVATIONS = ROOT / "data/option_response_shadow_20261026/option_response_observations.csv"
DEFAULT_OUTDIR = ROOT / "data/option_response_shadow_20261026"


def num(v: Any) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def dt(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        x = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        return x.replace(tzinfo=None) if x.tzinfo else x
    except (TypeError, ValueError):
        return None


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b <= 0:
        return None
    return 100 * (a / b - 1)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS)
    p.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    p.add_argument("--quote-window-minutes", type=float, default=1.0)
    p.add_argument("--wide-spread-pct", type=float, default=20.0)
    p.add_argument("--ask-ltp-ratio", type=float, default=1.5)
    args = p.parse_args()
    if not args.observations.is_file():
        p.error(f"Observation CSV not found: {args.observations}")

    all_observations = read_csv(args.observations)
    by_contract: dict[tuple[str, ...], dict[str, str]] = {}
    for r in all_observations:
        k = tuple(str(r.get(c, "")).strip() for c in (
            "day", "symbol", "direction", "kind", "strike", "expiry",
            "option_security_id", "ready",
        ))
        by_contract.setdefault(k, r)
    observations = list(by_contract.values())

    days = sorted({r.get("day", "") for r in observations if r.get("day")})
    chains: dict[str, list[dict[str, str]]] = {}
    for day in days:
        path = ROOT / "data/options_intelligence_upstox" / day / "option_chain_rows.csv.gz"
        if not path.is_file():
            continue
        ids = {str(r.get("option_security_id", "")).strip() for r in observations if r.get("day") == day}
        selected: list[dict[str, str]] = []
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if str(row.get("option_security_id", "")).strip() in ids:
                    selected.append(row)
        chains[day] = selected

    quote_rows: list[dict[str, Any]] = []
    summary_by_contract: list[dict[str, Any]] = []
    flags = Counter()
    day_counts = Counter()
    missing_chain = []

    for obs in observations:
        day = str(obs.get("day", "")).strip()
        secid = str(obs.get("option_security_id", "")).strip()
        snap = dt(obs.get("entry_snapshot"))
        if day not in chains:
            missing_chain.append({"day": day, "symbol": obs.get("symbol"), "security_id": secid})
            continue
        possible = []
        for c in chains[day]:
            if str(c.get("option_security_id", "")).strip() != secid:
                continue
            stamp = dt(c.get("captured_at"))
            if stamp is None:
                continue
            delta = abs((stamp-snap).total_seconds()) / 60 if snap else 999999
            if delta <= args.quote_window_minutes:
                possible.append((delta, c, stamp))
        possible.sort(key=lambda x: x[0])
        if not possible:
            missing_chain.append({"day": day, "symbol": obs.get("symbol"), "security_id": secid,
                                  "entry_snapshot": obs.get("entry_snapshot"),
                                  "reason": "no same-security snapshot within configured window"})
            continue

        for rank, (delay, c, stamp) in enumerate(possible, 1):
            bid, ask, ltp = num(c.get("bid")), num(c.get("ask")), num(c.get("ltp"))
            bq, aq = num(c.get("bid_qty")), num(c.get("ask_qty"))
            iv, delta_val, theta = num(c.get("iv")), num(c.get("delta")), num(c.get("theta"))
            mid = (bid + ask) / 2 if bid is not None and ask is not None and bid > 0 and ask > 0 else None
            spread_mid_pct = 100 * (ask - bid) / mid if mid and bid is not None and ask is not None else None
            ask_ltp_ratio = ask / ltp if ask is not None and ltp is not None and ltp > 0 else None
            ltp_inside = bool(bid is not None and ask is not None and ltp is not None and bid <= ltp <= ask)
            row_flags = []
            if bid is None or bid <= 0: row_flags.append("NONPOSITIVE_BID")
            if ask is None or ask <= 0: row_flags.append("NONPOSITIVE_ASK")
            if bid is not None and ask is not None and bid > ask: row_flags.append("CROSSED_MARKET")
            if spread_mid_pct is not None and spread_mid_pct > args.wide_spread_pct: row_flags.append("WIDE_SPREAD")
            if ask_ltp_ratio is not None and ask_ltp_ratio > args.ask_ltp_ratio: row_flags.append("ASK_OVER_LTP_RATIO_HIGH")
            if bid is not None and ltp is not None and bid > ltp: row_flags.append("BID_ABOVE_LTP")
            if ask is not None and ltp is not None and ask < ltp: row_flags.append("ASK_BELOW_LTP")
            if not ltp_inside: row_flags.append("LTP_OUTSIDE_QUOTE")
            if bq is None or bq <= 0: row_flags.append("NO_BID_SIZE")
            if aq is None or aq <= 0: row_flags.append("NO_ASK_SIZE")
            for flag in set(row_flags):
                flags[flag] += 1
                day_counts[(day, flag)] += 1
            quote_rows.append({
                "day": day, "symbol": obs.get("symbol"), "direction": obs.get("direction"),
                "kind": obs.get("kind"), "ready": obs.get("ready"),
                "security_id": secid, "strike": obs.get("strike"), "expiry": obs.get("expiry"),
                "expected_entry_snapshot": obs.get("entry_snapshot"), "quote_timestamp": stamp.isoformat(),
                "delay_minutes_abs": round(delay, 3), "candidate_rank": rank,
                "bid": bid, "ask": ask, "ltp": ltp, "bid_qty": bq, "ask_qty": aq,
                "mid": round(mid, 4) if mid is not None else None,
                "spread_mid_pct": round(spread_mid_pct, 3) if spread_mid_pct is not None else None,
                "ask_ltp_ratio": round(ask_ltp_ratio, 3) if ask_ltp_ratio is not None else None,
                "ltp_inside_bid_ask": ltp_inside, "iv": iv, "delta": delta_val, "theta": theta,
                "spot": c.get("spot", ""), "volume": c.get("volume", ""), "oi": c.get("oi", ""),
                "flags": ";".join(row_flags),
            })

    # Summarize the nearest snapshot for each unique signal-contract.
    nearest: dict[tuple[str, ...], dict[str, Any]] = {}
    for q in quote_rows:
        key = tuple(str(q.get(c, "")) for c in ("day", "symbol", "direction", "kind", "security_id", "ready"))
        if key not in nearest or q["delay_minutes_abs"] < nearest[key]["delay_minutes_abs"]:
            nearest[key] = q
    for q in nearest.values():
        summary_by_contract.append(q)

    outdir = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    qpath = outdir / "option_chain_quote_quality_rows.csv"
    cpath = outdir / "option_chain_quote_quality_contract_summary.csv"
    mpath = outdir / "option_chain_quote_quality_summary.json"
    misspath = outdir / "option_chain_quote_quality_missing.csv"
    write_csv(qpath, quote_rows)
    write_csv(cpath, summary_by_contract)
    write_csv(misspath, missing_chain)

    spreads = [r["spread_mid_pct"] for r in summary_by_contract if r.get("spread_mid_pct") is not None]
    ask_ratios = [r["ask_ltp_ratio"] for r in summary_by_contract if r.get("ask_ltp_ratio") is not None]
    ltp_outside = sum(not r.get("ltp_inside_bid_ask", False) for r in summary_by_contract)
    summary = {
        "mode": "READ_ONLY_DIAGNOSTIC_NOT_TRADING_RULE",
        "unique_signal_contracts_requested": len(observations),
        "nearest_contract_quotes_found": len(summary_by_contract),
        "missing_nearby_contract_quotes": len(missing_chain),
        "all_nearby_quote_rows": len(quote_rows),
        "quote_window_minutes": args.quote_window_minutes,
        "nearest_snapshot_abs_delay_median_minutes": round(median([r["delay_minutes_abs"] for r in summary_by_contract]), 3) if summary_by_contract else None,
        "nearest_snapshot_abs_delay_max_minutes": max([r["delay_minutes_abs"] for r in summary_by_contract], default=None),
        "nearest_quotes_with_ltp_outside_bid_ask": ltp_outside,
        "nearest_quotes_with_wide_spread": sum("WIDE_SPREAD" in str(r.get("flags", "")) for r in summary_by_contract),
        "nearest_quotes_with_ask_ltp_ratio_high": sum("ASK_OVER_LTP_RATIO_HIGH" in str(r.get("flags", "")) for r in summary_by_contract),
        "nearest_spread_mid_pct_median": round(median(spreads), 3) if spreads else None,
        "nearest_ask_ltp_ratio_median": round(median(ask_ratios), 3) if ask_ratios else None,
        "flag_counts_all_nearby_rows": dict(flags),
        "outputs": {"all_quotes": str(qpath), "contract_summary": str(cpath), "missing": str(misspath)},
        "limitations": [
            "Flags are diagnostics only and do not establish that a quote is erroneous.",
            "LTP may be stale and may lie outside the current bid/ask.",
            "A snapshot does not prove an executable fill; quantity, latency, and order-book depth matter.",
            "Theta cannot be isolated from option premium changes without controlling for spot, IV, and quote quality.",
            "No source data, scanner rules, strategy, or paper-trade ledger is modified."
        ]
    }
    mpath.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("===== OPTION CHAIN QUOTE QUALITY AUDIT =====")
    print(json.dumps(summary, indent=2))
    print("\n===== EXAMPLE FLAGGED CONTRACTS =====")
    for r in sorted(summary_by_contract, key=lambda x: len(str(x.get("flags", "")).split(";")), reverse=True)[:20]:
        print(json.dumps({k: r.get(k) for k in (
            "day", "symbol", "kind", "security_id", "ready", "bid", "ask", "ltp",
            "spread_mid_pct", "ask_ltp_ratio", "bid_qty", "ask_qty", "flags"
        )}, ensure_ascii=False))
    print(f"\nSummary JSON: {mpath}")
    print("READ-ONLY QUOTE QUALITY AUDIT COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
