"""Offline, spread-aware hypothetical option replay for scanner snapshots.

This research utility reads existing local signal snapshots and option-chain
captures only. It does not import broker, scanner, strategy, or order modules;
it makes no network requests and writes no data.

Policy: at each snapshot, choose the nearest listed unexpired expiry and the
strike nearest the captured spot, buying a call for BULLISH or a put for
BEARISH at the observed ask. Mark that same contract at the latest quote at or
before each requested horizon using its bid. Where an exact lot size is
available, estimate one-lot net returns with the local paper round-trip fee
model and require displayed size for one lot on both sides. These remain
hypothetical marks, not fills or realized trades. Repeated snapshots overlap.

Example:
    python option_selection_replay.py --date 2026-10-26
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import statistics
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

import intraday_selection_replay as stock_replay
from trade_costs import round_trip_costs


HORIZONS_MIN = (15, 30, 60)
MAX_QUOTE_AGE_SECONDS = 150


def _chain_path(root: Path, day: str) -> Path | None:
    candidates = (
        root / "data" / "options_intelligence_upstox" / day / "option_chain_rows.csv.gz",
        root / "data" / "options_intelligence" / day / "option_chain_rows.csv",
    )
    return next((path for path in candidates if path.is_file()), None)


def _open_csv(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def _load_lot_sizes(root: Path) -> dict[str, int]:
    """Load exact contract lot sizes from the already-cached Upstox master."""
    path = root / "data" / "cache" / "upstox_NSE.json.gz"
    if not path.is_file():
        return {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            rows = json.load(handle)
    except (OSError, EOFError, json.JSONDecodeError):
        return {}
    lot_sizes = {}
    for row in rows if isinstance(rows, list) else []:
        if row.get("segment") != "NSE_FO" or not row.get("instrument_key"):
            continue
        try:
            lot_size = int(row.get("lot_size") or 0)
        except (TypeError, ValueError):
            continue
        if lot_size > 0:
            lot_sizes[str(row["instrument_key"]).split("|")[-1]] = lot_size
    return lot_sizes


def _load_chains(path: Path) -> tuple[dict[tuple[str, datetime], list[dict[str, Any]]], dict[str, list[tuple[datetime, float | None]]]]:
    snapshots: dict[tuple[str, datetime], list[dict[str, Any]]] = defaultdict(list)
    by_contract: dict[str, list[tuple[datetime, float | None, float | None]]] = defaultdict(list)
    with _open_csv(path) as handle:
        for raw in csv.DictReader(handle):
            captured = stock_replay._timestamp(raw.get("captured_at"))
            symbol = str(raw.get("symbol") or "").strip().upper()
            security_id = str(raw.get("option_security_id") or "").strip()
            expiry = str(raw.get("expiry") or "").strip()
            try:
                expiry_day = date.fromisoformat(expiry[:10])
            except ValueError:
                expiry_day = None
            if captured is None or not symbol or not security_id:
                continue
            row = {
                "security_id": security_id,
                "expiry": expiry_day,
                "strike": stock_replay._float(raw.get("strike")),
                "spot": stock_replay._float(raw.get("spot")),
                "side": str(raw.get("side") or "").upper(),
                "bid": stock_replay._float(raw.get("bid")),
                "ask": stock_replay._float(raw.get("ask")),
                "bid_qty": stock_replay._float(raw.get("bid_qty")),
                "ask_qty": stock_replay._float(raw.get("ask_qty")),
            }
            snapshots[(symbol, captured)].append(row)
            by_contract[security_id].append((captured, row["bid"], row["bid_qty"]))
    for rows in by_contract.values():
        rows.sort(key=lambda point: point[0])
    return snapshots, by_contract


def _summarize(values: list[float]) -> str:
    if not values:
        return "n=0"
    return (
        f"n={len(values)}; median={statistics.median(values):+.2f}%; "
        f"mean={statistics.fmean(values):+.2f}%; hit={sum(x > 0 for x in values) / len(values):.1%}"
    )


def run(root: Path, day: str) -> str:
    path = _chain_path(root, day)
    if path is None:
        return f"{day}: no local option-chain rows; no option outcomes can be estimated."

    prices = stock_replay._load_market_quotes(root, day)
    observations = stock_replay._load_snapshots(root, day, prices)
    chains, by_contract = _load_chains(path)
    lot_sizes = _load_lot_sizes(root) if path.suffix == ".gz" else {}
    chain_times: dict[str, list[datetime]] = defaultdict(list)
    for symbol, captured in chains:
        chain_times[symbol].append(captured)
    for times in chain_times.values():
        times.sort()
    contract_times = {
        security_id: [point[0] for point in rows]
        for security_id, rows in by_contract.items()
    }

    matched = Counter()
    outcomes: dict[tuple[int, str], list[float]] = defaultdict(list)
    by_direction: dict[tuple[int, str, str], list[float]] = defaultdict(list)
    net_lot_outcomes: dict[tuple[int, str], list[float]] = defaultdict(list)
    spread_pct: list[float] = []
    quote_age_seconds: list[float] = []
    matched_obs = 0
    valid_entry_quotes = 0
    lot_size_matches = 0
    depth_valid_entry_quotes = 0
    for observation in observations:
        symbol = observation["symbol"]
        times = chain_times.get(symbol, [])
        index = bisect_right(times, observation["time"]) - 1
        if index < 0:
            matched["no_prior_snapshot"] += 1
            continue
        captured = times[index]
        quote_age = (observation["time"] - captured).total_seconds()
        if quote_age > MAX_QUOTE_AGE_SECONDS:
            matched["stale_entry_snapshot"] += 1
            continue
        matched_obs += 1
        side = "CE" if observation["direction"] == "BULLISH" else "PE"
        candidates = [
            row for row in chains[(symbol, captured)]
            if row["side"] == side
            and row["expiry"] is not None
            and row["expiry"] >= date.fromisoformat(day)
            and row["strike"] is not None
            and row["spot"] is not None
        ]
        if not candidates:
            matched["no_eligible_contract"] += 1
            continue
        nearest_expiry = min(row["expiry"] for row in candidates)
        candidates = [row for row in candidates if row["expiry"] == nearest_expiry]
        contract = min(candidates, key=lambda row: (abs(row["strike"] - row["spot"]), row["strike"]))
        ask, bid = contract["ask"], contract["bid"]
        if ask is None or bid is None or ask <= 0 or bid <= 0 or ask < bid:
            matched["invalid_entry_quote"] += 1
            continue
        valid_entry_quotes += 1
        lot_size = lot_sizes.get(contract["security_id"])
        ask_qty = contract["ask_qty"]
        if lot_size:
            lot_size_matches += 1
            if ask_qty is not None and ask_qty >= lot_size:
                depth_valid_entry_quotes += 1
        spread_pct.append((ask - bid) / ((ask + bid) / 2) * 100)
        quote_age_seconds.append(quote_age)
        if observation["source"] == "signal":
            group = "actionable" if observation["passed"] else "signal-held"
        else:
            group = observation["source"]
        security_id = contract["security_id"]
        times_for_contract = contract_times[security_id]
        quotes_for_contract = by_contract[security_id]
        for horizon in HORIZONS_MIN:
            target = observation["time"] + timedelta(minutes=horizon)
            # Use the most recent quote at or before the horizon. This avoids
            # using information that arrived after the simulated decision time.
            future_index = bisect_right(times_for_contract, target) - 1
            if future_index < 0:
                matched[f"no_{horizon}m_quote"] += 1
                continue
            future_time, exit_bid, exit_bid_qty = quotes_for_contract[future_index]
            if (target - future_time).total_seconds() > MAX_QUOTE_AGE_SECONDS:
                matched[f"no_{horizon}m_quote"] += 1
                continue
            if exit_bid is None or exit_bid <= 0:
                matched[f"invalid_{horizon}m_exit_bid"] += 1
                continue
            outcomes[(horizon, group)].append((exit_bid / ask - 1.0) * 100.0)
            by_direction[(horizon, group, observation["direction"])].append((exit_bid / ask - 1.0) * 100.0)
            if (
                lot_size
                and ask_qty is not None
                and ask_qty >= lot_size
                and exit_bid_qty is not None
                and exit_bid_qty >= lot_size
            ):
                costs = round_trip_costs(ask, exit_bid, lot_size)
                gross_pnl = (exit_bid - ask) * lot_size
                net_lot_outcomes[(horizon, group)].append(
                    (gross_pnl - costs["total"]) / (ask * lot_size) * 100.0
                )
            matched[f"priced_{horizon}m"] += 1

    lines = [
        f"Offline hypothetical option replay - {day}",
        f"Chain file: {path.relative_to(root)}; observations: {len(observations)}; symbols with chain data: {len(chain_times)}",
        f"Matched entry snapshots <= {MAX_QUOTE_AGE_SECONDS}s old: {matched_obs}; valid two-sided ATM entry quotes: {valid_entry_quotes}",
        "Entry policy: buy nearest-expiry ATM CE for bullish or PE for bearish at ask; mark the same security ID at the latest quote at or before each horizon using bid.",
        "Gross returns use bid/ask. Net one-lot estimates use the local paper round-trip fee model and require displayed size for one lot at entry and exit. No guaranteed fills or stop/target path. Snapshots overlap.",
    ]
    if spread_pct:
        lines.append(
            f"Entry quote diagnostics: median quoted spread/mid={statistics.median(spread_pct):.2f}%; "
            f"median quote age={statistics.median(quote_age_seconds):.0f}s."
        )
    for horizon in HORIZONS_MIN:
        lines.append(f"\n{horizon}-minute option horizon:")
        for group in ("actionable", "signal-held", "analysed", "radar_only", "cycle_report"):
            values = outcomes.get((horizon, group), [])
            if values:
                lines.append(f"  {group}: {_summarize(values)}")
        for group in ("actionable", "signal-held"):
            for direction in ("BULLISH", "BEARISH"):
                values = by_direction.get((horizon, group, direction), [])
                if values:
                    lines.append(f"  {direction.lower()} {group}: {_summarize(values)}")
        for group in ("actionable", "signal-held", "analysed", "radar_only", "cycle_report"):
            values = net_lot_outcomes.get((horizon, group), [])
            if values:
                lines.append(f"  {group} (1-lot net, quote depth verified): {_summarize(values)}")
    if lot_sizes:
        lines.append(
            f"Lot-size/depth coverage: exact lot size found for {lot_size_matches}/{valid_entry_quotes} valid entry contracts; "
            f"ask depth >= 1 lot for {depth_valid_entry_quotes} entry quotes. Net groups also require bid depth >= 1 lot at exit."
        )
    elif path.suffix == ".gz":
        lines.append("Lot-size/depth-adjusted costs unavailable: no readable local Upstox instrument master.")
    else:
        lines.append("Lot-size/depth-adjusted costs unavailable: this chain source has no matching verified local lot-size mapping.")
    lines.append(f"Coverage/failure counts: {dict(sorted(matched.items()))}")
    lines.append("These estimates are candidate-level research marks, not evidence of actual order execution or profitability.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Trading date in YYYY-MM-DD format")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent, help="APlus project root")
    args = parser.parse_args()
    try:
        day = date.fromisoformat(args.date).isoformat()
    except ValueError:
        parser.error("--date must be a valid YYYY-MM-DD trading date")
    print(run(args.root.resolve(), day))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
