# APlus Incident Diagnostic

This diagnostic is **read-only with respect to the running scanner**. It collects:

- Matching Python/CMD/PowerShell process inventory
- Relevant Scheduled Task state, actions, and last result
- Key market-watch, safety-agent, watchdog, and portfolio-state file metadata
- JSON validity for small JSON files
- Recent file activity under monitored data folders
- Initial evidence-based findings

## Run on Windows

From the project root:

```powershell
.\tools\diagnostics\run_aplus_incident_diagnostic.bat
```

The report is written to:

```text
data\reports\incident_diagnostics\latest.json
data\reports\incident_diagnostics\incident_YYYYMMDD_HHMMSS.json
```

## Safety boundaries

The diagnostic does not:

- Stop, kill, or restart processes
- Change Scheduled Tasks
- Modify strategy logic or thresholds
- Place, force, or close trades
- Delete or repair production state files
- Change permissions or ACLs

The findings are indicators, not an automatic root-cause verdict. The report should be reviewed before any recovery action.
