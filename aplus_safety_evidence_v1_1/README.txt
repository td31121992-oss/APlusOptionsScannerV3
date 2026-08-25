APlus PAPER Safety + Evidence V1.1

Corrected packaging:
- Can be run from its extracted subfolder inside APlusOptionsScannerV3.
- Automatically targets the parent project root.
- Also works if copied directly into project root.

Implements:
1) Git initialization/baseline if git.exe is available.
2) PAPER-native portfolio_state.json updater from paper_trades_latest.json.
3) Per-trade evidence capsules under data/trade_evidence_capsules/YYYY-MM-DD/.

No scanner/trading code is modified.
No Dhan API calls are added.
