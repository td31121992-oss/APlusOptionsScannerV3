APlus PAPER Safety + Evidence V1.2

Fixes V1.1 Windows batch/PowerShell quoting bug.
The prior '^|' tokens were incorrectly passed literally into PowerShell.
V1.2 uses ordinary PowerShell pipes inside the quoted command.

Also verifies data/portfolio_state.json after startup.

Run from the extracted subfolder:
install_aplus_safety_evidence_v1_2_ONE_GO.bat
