import json
import gzip
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\Aplus\Desktop\APlusOptionsScannerV3")
OUT = ROOT / "data" / "option_response_shadow_20261026"
OBS = OUT / "option_response_observations.csv"
ENTRY = OUT / "option_chain_quote_quality_rows.csv"

observations = pd.read_csv(OBS, dtype={"option_security_id": str})
entry_quotes = pd.read_csv(ENTRY, dtype={"security_id": str})

def local_naive(series):
    return (
        pd.to_datetime(series, errors="coerce", utc=True)
        .dt.tz_convert("Asia/Kolkata")
        .dt.tz_localize(None)
    )

observations["exit_dt"] = local_naive(observations["exit_snapshot"])
observations["day"] = observations["day"].astype(str)
observations["option_security_id"] = observations["option_security_id"].astype(str)

entry_quotes["day"] = entry_quotes["day"].astype(str)
entry_quotes["security_id"] = entry_quotes["security_id"].astype(str)

entry_quotes["spread_mid_pct"] = pd.to_numeric(
    entry_quotes["spread_mid_pct"], errors="coerce"
)
entry_quotes["ask_ltp_ratio"] = pd.to_numeric(
    entry_quotes["ask_ltp_ratio"], errors="coerce"
)

entry_lookup = {}
for _, q in entry_quotes.iterrows():
    key = (str(q["day"]), str(q["symbol"]), str(q["kind"]),
           str(q["security_id"]), str(q["ready"]))
    entry_lookup[key] = q

rows = []
missing_files = []

for day in sorted(observations["day"].unique()):
    chain_path = (
        ROOT / "data" / "options_intelligence_upstox" /
        day / "option_chain_rows.csv.gz"
    )

    if not chain_path.exists():
        missing_files.append(str(chain_path))
        continue

    chain = pd.read_csv(chain_path, compression="gzip",
                        dtype={"option_security_id": str})

    required = {
        "captured_at", "option_security_id", "bid", "ask", "ltp",
        "bid_qty", "ask_qty"
    }
    if not required.issubset(chain.columns):
        raise RuntimeError(
            f"{chain_path} missing columns: {sorted(required - set(chain.columns))}"
        )

    chain["captured_dt"] = (
        pd.to_datetime(chain["captured_at"], errors="coerce", utc=True)
        .dt.tz_convert("Asia/Kolkata")
        .dt.tz_localize(None)
    )
    for col in ["bid", "ask", "ltp", "bid_qty", "ask_qty"]:
        chain[col] = pd.to_numeric(chain[col], errors="coerce")

    chain = chain.dropna(subset=["captured_dt", "option_security_id"])
    chain = chain.sort_values("captured_dt")

    day_obs = observations[observations["day"] == day]

    # Index chain snapshots by exact contract ID; select nearest snapshot
    # to each observation's exit time, allowing at most 1 minute.
    grouped = {
        str(contract): group.sort_values("captured_dt").reset_index(drop=True)
        for contract, group in chain.groupby("option_security_id", sort=False)
    }

    for _, obs in day_obs.iterrows():
        contract = str(obs["option_security_id"])
        target = obs["exit_dt"]
        group = grouped.get(contract)

        base = {
            "day": day,
            "symbol": obs["symbol"],
            "direction": obs["direction"],
            "kind": obs["kind"],
            "ready": obs["ready"],
            "security_id": contract,
            "horizon": int(obs["target_minutes"]),
            "exit_snapshot": obs["exit_snapshot"],
            "return_ask_to_bid_pct": pd.to_numeric(
                obs["option_return_ask_to_bid_pct"], errors="coerce"
            ),
            "observation_exit_bid": pd.to_numeric(
                obs["exit_bid"], errors="coerce"
            ),
            "observation_exit_ltp": pd.to_numeric(
                obs["exit_ltp"], errors="coerce"
            ),
        }

        if group is None or pd.isna(target) or group.empty:
            rows.append({**base, "quote_found": False})
            continue

        times = group["captured_dt"].values
        pos = int(np.searchsorted(times, np.datetime64(target)))

        candidates = [i for i in (pos - 1, pos) if 0 <= i < len(group)]
        if not candidates:
            rows.append({**base, "quote_found": False})
            continue

        idx = min(
            candidates,
            key=lambda i: abs(
                (group.iloc[i]["captured_dt"] - target).total_seconds()
            )
        )
        q = group.iloc[idx]
        delay = abs((q["captured_dt"] - target).total_seconds()) / 60.0

        bid, ask, ltp = q["bid"], q["ask"], q["ltp"]
        bq, aq = q["bid_qty"], q["ask_qty"]
        mid = (bid + ask) / 2 if pd.notna(bid) and pd.notna(ask) else np.nan
        spread = (
            (ask - bid) / mid * 100
            if pd.notna(mid) and mid > 0 else np.nan
        )
        inside = (
            pd.notna(ltp) and pd.notna(bid) and pd.notna(ask)
            and bid <= ltp <= ask
        )
        valid_book = (
            pd.notna(bid) and pd.notna(ask) and bid > 0 and ask >= bid
            and pd.notna(bq) and pd.notna(aq) and bq > 0 and aq > 0
        )
        clean_exit = bool(
            valid_book and inside and pd.notna(spread) and spread <= 5
        )

        reported_bid = base["observation_exit_bid"]
        bid_diff_pct = (
            abs(reported_bid - bid) / bid * 100
            if pd.notna(reported_bid) and pd.notna(bid) and bid > 0
            else np.nan
        )

        entry_key = (
            day, str(obs["symbol"]), str(obs["kind"]),
            contract, str(obs["ready"])
        )
        eq = entry_lookup.get(entry_key)

        entry_clean = False
        if eq is not None:
            ebid = pd.to_numeric(eq.get("bid"), errors="coerce")
            eask = pd.to_numeric(eq.get("ask"), errors="coerce")
            ebq = pd.to_numeric(eq.get("bid_qty"), errors="coerce")
            eaq = pd.to_numeric(eq.get("ask_qty"), errors="coerce")
            espread = pd.to_numeric(eq.get("spread_mid_pct"), errors="coerce")
            eratio = pd.to_numeric(eq.get("ask_ltp_ratio"), errors="coerce")
            entry_clean = bool(
                pd.notna(ebid) and pd.notna(eask) and ebid > 0 and eask >= ebid
                and pd.notna(ebq) and pd.notna(eaq) and ebq > 0 and eaq > 0
                and pd.notna(espread) and espread <= 5
                and pd.notna(eratio) and 1 <= eratio <= 1.10
                and str(eq.get("ltp_inside_bid_ask")) == "True"
            )

        rows.append({
            **base,
            "quote_found": delay <= 1,
            "matched_quote_timestamp": str(q["captured_dt"]),
            "delay_minutes": round(delay, 4),
            "exit_bid": bid,
            "exit_ask": ask,
            "exit_ltp": ltp,
            "exit_bid_qty": bq,
            "exit_ask_qty": aq,
            "exit_spread_mid_pct": spread,
            "exit_ltp_inside_bid_ask": bool(inside),
            "exit_valid_book": bool(valid_book),
            "exit_clean": clean_exit,
            "observation_vs_chain_bid_diff_pct": bid_diff_pct,
            "entry_clean": entry_clean,
            "both_clean": bool(entry_clean and clean_exit and delay <= 1),
        })

audit = pd.DataFrame(rows)
audit_path = OUT / "option_response_exit_quote_audit.csv"
audit.to_csv(audit_path, index=False)

matched = audit[audit["quote_found"] == True].copy()
summary = {
    "mode": "READ_ONLY_EXIT_QUOTE_DIAGNOSTIC",
    "observations": int(len(observations)),
    "exit_quotes_found_within_1_min": int(len(matched)),
    "exit_quotes_missing_or_outside_window": int(len(audit) - len(matched)),
    "exit_ltp_outside_bid_ask": int(
        (matched["exit_ltp_inside_bid_ask"] == False).sum()
    ) if "exit_ltp_inside_bid_ask" in matched else 0,
    "exit_valid_book": int(matched["exit_valid_book"].sum())
        if "exit_valid_book" in matched else 0,
    "exit_clean": int(matched["exit_clean"].sum())
        if "exit_clean" in matched else 0,
    "entry_and_exit_clean": int(matched["both_clean"].sum())
        if "both_clean" in matched else 0,
    "median_abs_observation_vs_chain_bid_diff_pct": (
        round(float(matched["observation_vs_chain_bid_diff_pct"].median()), 4)
        if "observation_vs_chain_bid_diff_pct" in matched else None
    ),
    "missing_chain_files": missing_files,
    "outputs": {"audit_csv": str(audit_path)},
    "limitations": [
        "Nearest snapshot is not proof of an executable fill.",
        "The combined clean subset is a diagnostic, not a trading rule.",
        "A one-minute match tolerance may not reproduce the original quote selection."
    ]
}

summary_path = OUT / "option_response_exit_quote_audit_summary.json"
summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

print(json.dumps(summary, indent=2))

if len(matched):
    print("\n===== BY HORIZON / OPTION TYPE =====")
    for (horizon, kind), group in matched.groupby(["horizon", "kind"]):
        print({
            "horizon_min": int(horizon),
            "kind": kind,
            "matched": int(len(group)),
            "exit_clean": int(group["exit_clean"].sum()),
            "entry_and_exit_clean": int(group["both_clean"].sum()),
            "median_return_all_pct": round(
                float(group["return_ask_to_bid_pct"].median()), 3
            ),
            "median_return_both_clean_pct": (
                round(float(group.loc[group["both_clean"],
                                      "return_ask_to_bid_pct"].median()), 3)
                if group["both_clean"].any() else None
            )
        })

print("\nREAD-ONLY EXIT QUOTE AUDIT COMPLETE")

