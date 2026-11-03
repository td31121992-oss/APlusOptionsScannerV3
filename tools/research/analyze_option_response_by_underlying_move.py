import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\Aplus\Desktop\APlusOptionsScannerV3")
OUT = ROOT / "data" / "option_response_shadow_20261026"

OBS = OUT / "option_response_observations.csv"
AUDIT = OUT / "option_response_exit_quote_audit.csv"

obs = pd.read_csv(OBS, dtype={"option_security_id": str})
audit = pd.read_csv(AUDIT, dtype={"security_id": str})

def numcol(df, col):
    df[col] = pd.to_numeric(df[col], errors="coerce")

for c in [
    "target_minutes",
    "direction_adjusted_underlying_move_pct",
    "option_return_ask_to_bid_pct",
    "entry_iv",
    "exit_iv",
]:
    numcol(obs, c)

obs["iv_change"] = obs["exit_iv"] - obs["entry_iv"]
obs["day"] = obs["day"].astype(str)
obs["option_security_id"] = obs["option_security_id"].astype(str)

for c in ["horizon", "return_ask_to_bid_pct"]:
    numcol(audit, c)

audit["day"] = audit["day"].astype(str)
audit["security_id"] = audit["security_id"].astype(str)
audit["both_clean"] = (
    audit["both_clean"].astype(str).str.lower().eq("true")
)

# One audit row per signal-contract and holding horizon.
keys = [
    "day", "symbol", "kind", "option_security_id",
    "ready", "target_minutes"
]
audit_keys = [
    "day", "symbol", "kind", "security_id",
    "ready", "horizon"
]
audit_small = audit[
    audit_keys + ["both_clean", "exit_clean", "quote_found"]
].copy()
audit_small.columns = keys + ["both_clean", "exit_clean", "quote_found"]

merged = obs.merge(
    audit_small,
    on=keys,
    how="left",
    validate="one_to_one"
)

merged = merged[
    merged["option_return_ask_to_bid_pct"].notna()
    & merged["direction_adjusted_underlying_move_pct"].notna()
].copy()

def move_bucket(x):
    if pd.isna(x):
        return "UNKNOWN"
    if x <= -0.5:
        return "ADVERSE <= -0.5%"
    if x < 0:
        return "ADVERSE -0.5% TO 0%"
    if x <= 0.5:
        return "FAVOURABLE 0% TO 0.5%"
    return "FAVOURABLE > 0.5%"

merged["move_bucket"] = merged[
    "direction_adjusted_underlying_move_pct"
].apply(move_bucket)

merged["sample"] = np.where(
    merged["both_clean"].fillna(False),
    "BOTH_ENTRY_EXIT_CLEAN",
    "ALL_MATCHED"
)

def summarize(group, dimensions):
    r = group["option_return_ask_to_bid_pct"].dropna()
    m = group["direction_adjusted_underlying_move_pct"].dropna()
    iv = group["iv_change"].dropna()

    result = {d: group.iloc[0][d] for d in dimensions}
    result.update({
        "observations": int(len(r)),
        "positive_return_pct": round(float((r > 0).mean() * 100), 2)
            if len(r) else None,
        "median_option_return_pct": round(float(r.median()), 3)
            if len(r) else None,
        "mean_option_return_pct": round(float(r.mean()), 3)
            if len(r) else None,
        "median_direction_adjusted_move_pct": round(float(m.median()), 3)
            if len(m) else None,
        "median_iv_change_points": round(float(iv.median()), 3)
            if len(iv) else None,
    })
    return result

# Main table: all matched observations, grouped by date, horizon, option type,
# and the direction-adjusted underlying move bucket.
dims = ["day", "target_minutes", "kind", "move_bucket"]
main_rows = []
for _, g in merged.groupby(dims, dropna=False, sort=True):
    main_rows.append(summarize(g, dims))
main = pd.DataFrame(main_rows)

# Quality comparison: all matched vs. both-entry-and-exit-clean samples.
quality_rows = []
for sample_name, g0 in [
    ("ALL_MATCHED", merged),
    ("BOTH_ENTRY_EXIT_CLEAN", merged[merged["both_clean"].fillna(False)])
]:
    dims2 = ["day", "target_minutes", "kind", "move_bucket"]
    for _, g in g0.groupby(dims2, dropna=False, sort=True):
        row = summarize(g, dims2)
        row["sample"] = sample_name
        quality_rows.append(row)

quality = pd.DataFrame(quality_rows)

# Horizon-level overview, to compare ATM and OTM1 without move buckets.
overview_rows = []
for _, g in merged.groupby(
    ["day", "target_minutes", "kind"], dropna=False, sort=True
):
    overview_rows.append(
        summarize(g, ["day", "target_minutes", "kind"])
    )
overview = pd.DataFrame(overview_rows)

main_path = OUT / "option_response_underlying_move_analysis.csv"
quality_path = OUT / "option_response_underlying_move_quality_comparison.csv"
overview_path = OUT / "option_response_underlying_move_overview.csv"
summary_path = OUT / "option_response_underlying_move_analysis_summary.json"

main.to_csv(main_path, index=False)
quality.to_csv(quality_path, index=False)
overview.to_csv(overview_path, index=False)

summary = {
    "mode": "READ_ONLY_SHADOW_ANALYSIS",
    "source_observations": int(len(obs)),
    "joined_observations": int(len(merged)),
    "both_entry_exit_clean": int(merged["both_clean"].fillna(False).sum()),
    "move_bucket_definition": {
        "adverse_strong": "direction-adjusted move <= -0.5%",
        "adverse_weak": "-0.5% < direction-adjusted move < 0%",
        "favourable_weak": "0% <= direction-adjusted move <= 0.5%",
        "favourable_strong": "direction-adjusted move > 0.5%"
    },
    "outputs": {
        "by_move_bucket": str(main_path),
        "quality_comparison": str(quality_path),
        "horizon_overview": str(overview_path)
    },
    "limitations": [
        "The sample covers only 2026-10-22 and 2026-10-23.",
        "Holding horizons from the same signal overlap and are not independent.",
        "Direction-adjusted movement is not a measure of the full price path.",
        "IV change is descriptive and does not isolate theta.",
        "Quote filters are diagnostics, not trading rules.",
        "Quote snapshots do not prove executable fills or account for costs."
    ]
}
summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

print("===== ANALYSIS SUMMARY =====")
print(json.dumps(summary, indent=2))

print("\n===== OVERVIEW BY DAY / HORIZON / TYPE =====")
if len(overview):
    print(overview.to_string(index=False))

print("\n===== MOVE-BUCKET RESULTS: ALL MATCHED =====")
if len(main):
    print(main.to_string(index=False))

print("\n===== READ-ONLY SHADOW ANALYSIS COMPLETE =====")
