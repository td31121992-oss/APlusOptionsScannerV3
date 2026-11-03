#!/usr/bin/env python3
"""Read-only reconciliation of option-response entries against report and chain snapshots.

Reads:
  data/option_response_shadow_20261026/option_response_observations.csv
  data/missed_opportunities/<day>/option_returns.json
  data/options_intelligence_upstox/<day>/option_chain_rows.csv.gz

Writes only diagnostic CSV/JSON outputs under data/option_response_shadow_20261026/.
No scanner, strategy, ledger, or source data is modified.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
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
        s = str(v).strip().replace("Z", "+00:00")
        x = datetime.fromisoformat(s)
        return x.replace(tzinfo=None) if x.tzinfo else x
    except (ValueError, TypeError):
        return None


def norm(v: Any) -> str:
    return str(v or "").strip().upper()


def side_for(row: dict[str, str]) -> str:
    side = norm(row.get("side"))
    if side in {"CE", "PE"}:
        return side
    direction = norm(row.get("direction") or row.get("dir"))
    return "CE" if direction in {"BULLISH", "CALL", "CE"} else "PE"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS)
    p.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    p.add_argument("--large-diff-pct", type=float, default=10.0)
    p.add_argument("--snapshot-window-minutes", type=float, default=6.0)
    args = p.parse_args()
    if not args.observations.is_file():
        p.error(f"Observation CSV not found: {args.observations}")

    observations = read_csv(args.observations)
    # Keep one row per signal-contract for reconciliation; horizon repeats are expected.
    unique: dict[tuple[str, ...], dict[str, str]] = {}
    for r in observations:
        k = tuple(str(r.get(c, "")).strip() for c in (
            "day", "symbol", "direction", "kind", "strike", "expiry",
            "option_security_id", "ready",
        ))
        unique.setdefault(k, r)
    observations = list(unique.values())

    days = sorted({str(r.get("day", "")).strip() for r in observations if r.get("day")})
    report_rows: dict[str, list[dict[str, Any]]] = {}
    chain_rows: dict[str, list[dict[str, str]]] = {}
    chain_headers: dict[str, list[str]] = {}

    for day in days:
        report_path = ROOT / "data" / "missed_opportunities" / day / "option_returns.json"
        if report_path.is_file():
            try:
                report_rows[day] = json.loads(report_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                report_rows[day] = []
        chain_path = ROOT / "data" / "options_intelligence_upstox" / day / "option_chain_rows.csv.gz"
        if not chain_path.is_file():
            continue
        selected_symbols = {norm(r.get("symbol")) for r in observations if r.get("day") == day}
        selected = []
        with gzip.open(chain_path, "rt", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            chain_headers[day] = list(reader.fieldnames or [])
            for c in reader:
                if norm(c.get("symbol")) in selected_symbols:
                    selected.append(c)
        chain_rows[day] = selected

    report_match_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    classifications: defaultdict[str, int] = defaultdict(int)
    no_report: list[dict[str, Any]] = []
    no_chain: list[dict[str, Any]] = []

    for r in observations:
        day = str(r.get("day", "")).strip()
        sym = norm(r.get("symbol"))
        direction = norm(r.get("direction"))
        side = side_for(r)
        kind = norm(r.get("kind"))
        strike = num(r.get("strike"))
        expiry = str(r.get("expiry", "")).strip()[:10]
        ready = str(r.get("ready", "")).strip()
        entry_snapshot = dt(r.get("entry_snapshot"))
        report_entry = num(r.get("report_entry_price"))
        chain_ask = num(r.get("entry_ask"))
        chain_ltp = num(r.get("entry_ltp"))
        obs_id = str(r.get("option_security_id", "")).strip()
        diff = num(r.get("report_entry_vs_chain_ask_pct"))
        key_base = {
            "day": day, "symbol": sym, "direction": direction, "side_expected": side,
            "kind": kind, "strike_expected": strike, "expiry_expected": expiry,
            "ready": ready, "entry_snapshot": r.get("entry_snapshot", ""),
            "option_security_id_expected": obs_id, "report_entry": report_entry,
            "observation_chain_ask": chain_ask, "observation_chain_ltp": chain_ltp,
            "report_vs_ask_abs_diff_pct": abs(diff) if diff is not None else None,
        }

        same_report = [
            x for x in report_rows.get(day, [])
            if norm(x.get("symbol")) == sym
            and norm(x.get("dir")) == direction
            and norm(x.get("kind")) == kind
            and str(x.get("ready", "")).strip() == ready
            and num(x.get("strike")) is not None and strike is not None
            and abs(num(x.get("strike")) - strike) < 1e-6
        ]
        if same_report:
            # If duplicates exist, preserve all entries in diagnostic output.
            for rr in same_report:
                report_match_rows.append({
                    **key_base, "report_match_count": len(same_report),
                    "report_json_entry": num(rr.get("entry")),
                    "report_entry_abs_diff_pct": (
                        round(abs(report_entry / num(rr.get("entry")) - 1) * 100, 4)
                        if report_entry is not None and num(rr.get("entry")) not in (None, 0) else None
                    ),
                    "report_json_best_pct": rr.get("best", ""),
                    "report_json_worst_pct": rr.get("worst", ""),
                    "report_json_close_pct": rr.get("close", ""),
                    "report_json_t_target": rr.get("t_target", ""),
                    "report_json_stop_first": rr.get("stop_first", ""),
                })
        else:
            no_report.append({**key_base, "reason": "no exact report row matched by day/symbol/dir/kind/strike/ready"})

        rows = chain_rows.get(day, [])
        if not rows:
            no_chain.append({**key_base, "reason": "chain file missing or no rows for symbol"})
            continue
        matching = []
        same_symbol = []
        for c in rows:
            if norm(c.get("symbol")) != sym:
                continue
            stamp = dt(c.get("captured_at") or c.get("timestamp") or c.get("time"))
            if stamp is None:
                continue
            if entry_snapshot is not None and abs((stamp-entry_snapshot).total_seconds()) > args.snapshot_window_minutes * 60:
                continue
            cstrike = num(c.get("strike"))
            cside = side_for(c)
            cexpiry = str(c.get("expiry", "")).strip()[:10]
            same_symbol.append((c, stamp, cstrike, cside, cexpiry))
            if strike is not None and cstrike is not None and abs(cstrike-strike) < 1e-6 and cside == side and cexpiry == expiry:
                matching.append((c, stamp, cstrike, cside, cexpiry))

        def emit_candidate(item, rank: str):
            c, stamp, cstrike, cside, cexpiry = item
            ask, bid, ltp = num(c.get("ask")), num(c.get("bid")), num(c.get("ltp"))
            report_to_ask = (round((report_entry/ask-1)*100, 4)
                             if report_entry is not None and ask not in (None, 0) else None)
            candidate_rows.append({
                **key_base, "candidate_rank": rank,
                "candidate_security_id": c.get("option_security_id", ""),
                "candidate_side": cside, "candidate_strike": cstrike,
                "candidate_expiry": cexpiry, "candidate_captured_at": stamp.isoformat(),
                "minutes_from_entry_snapshot": round((stamp-entry_snapshot).total_seconds()/60, 2) if entry_snapshot else None,
                "candidate_bid": bid, "candidate_ask": ask, "candidate_ltp": ltp,
                "candidate_report_entry_vs_ask_pct": report_to_ask,
                "candidate_spot": c.get("spot", ""),
            })

        if matching:
            matching.sort(key=lambda x: abs((x[1]-entry_snapshot).total_seconds()) if entry_snapshot else 0)
            for i, item in enumerate(matching[:5], 1):
                emit_candidate(item, f"EXACT_CONTRACT_NEAREST_{i}")
            classifications["exact_contract_snapshot_found"] += 1
        else:
            classifications["exact_contract_snapshot_not_found"] += 1
            # Show nearest same symbol + side + strike candidates first, then nearest same symbol/side.
            alternatives = [x for x in same_symbol if x[3] == side and strike is not None and x[2] is not None and abs(x[2]-strike)<1e-6]
            if not alternatives:
                alternatives = [x for x in same_symbol if x[3] == side]
            alternatives.sort(key=lambda x: abs((x[1]-entry_snapshot).total_seconds()) if entry_snapshot else 0)
            for i, item in enumerate(alternatives[:10], 1):
                emit_candidate(item, f"ALTERNATIVE_SAME_SIDE_NEAREST_{i}")

    args.outdir.mkdir(parents=True, exist_ok=True)
    candidates_path = args.outdir / "option_entry_reconciliation_candidates.csv"
    reports_path = args.outdir / "option_entry_reconciliation_report_rows.csv"
    no_report_path = args.outdir / "option_entry_reconciliation_unmatched_reports.csv"
    no_chain_path = args.outdir / "option_entry_reconciliation_missing_chain.csv"
    summary_path = args.outdir / "option_entry_reconciliation_summary.json"
    write_csv(candidates_path, candidate_rows)
    write_csv(reports_path, report_match_rows)
    write_csv(no_report_path, no_report)
    write_csv(no_chain_path, no_chain)

    large = [r for r in observations if (num(r.get("report_entry_vs_chain_ask_pct")) is not None
                                         and abs(num(r.get("report_entry_vs_chain_ask_pct"))) > args.large_diff_pct)]
    summary = {
        "mode": "READ_ONLY_SHADOW_AUDIT",
        "observations_rows": len(read_csv(args.observations)),
        "unique_signal_contracts": len(observations),
        "days": days,
        "chain_rows_loaded_by_day": {d: len(v) for d, v in chain_rows.items()},
        "chain_columns_by_day": chain_headers,
        "large_entry_discrepancies_unique_contracts": len(large),
        "report_json_exact_matches": len(report_match_rows),
        "unique_observations_without_report_match": len(no_report),
        "unique_observations_without_chain_rows": len(no_chain),
        "chain_match_classifications": dict(classifications),
        "candidate_rows_written": len(candidate_rows),
        "outputs": {
            "candidate_contracts": str(candidates_path),
            "report_row_comparison": str(reports_path),
            "unmatched_report_rows": str(no_report_path),
            "missing_chain_rows": str(no_chain_path),
        },
        "warnings": [
            "A chain snapshot is not proof of an executable fill.",
            "Report entry may be derived from a five-minute candle and slippage, while chain ask is a separate quote source.",
            "Do not compare these prices as if they were necessarily the same timestamp or fill definition.",
            "No production logic, input data, paper-trade ledger, or trade record was modified.",
        ],
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("===== OPTION ENTRY RECONCILIATION =====")
    print(json.dumps(summary, indent=2))
    print("\n===== LARGEST ENTRY MISMATCHES: NEAREST CHAIN CANDIDATES =====")
    shown = 0
    for row in candidate_rows:
        if row.get("candidate_rank") not in {"ALTERNATIVE_SAME_SIDE_NEAREST_1", "EXACT_CONTRACT_NEAREST_1"}:
            continue
        d = row.get("report_vs_ask_abs_diff_pct")
        if d is not None and num(d) is not None and num(d) > args.large_diff_pct:
            print(json.dumps(row, ensure_ascii=False))
            shown += 1
            if shown >= 20:
                break
    print(f"\nSummary JSON: {summary_path}")
    print("READ-ONLY RECONCILIATION COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
