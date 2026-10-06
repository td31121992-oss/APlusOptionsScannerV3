# APlus 24x7 Resilience

## Goal

Keep APlus alive continuously while making Dhan a market-session dependency only.

### Market session

The existing APlus intraday scanner remains the market-data consumer. It is started only after the Dhan profile and Data API preflight passes. The unattended startup loop retries through the startup/session window instead of giving up after ten attempts.

The current scanner launcher advertises 09:15-15:30 IST. This reliability layer does not change the trading engine's market-hours logic.

### Mid-session token refresh

APlus_MidSession_Token_Refresh.ps1 calls the existing CAlphaTrader tools/dhan_auto_token.py mechanism. It never creates a replacement credential system.

It:
1. refreshes and validates the Dhan token;
2. requires DHAN_TOKEN_REFRESH_OK and a changed CAlphaTrader .env timestamp;
3. restarts the scanner only when exactly one matching scanner process is identified;
4. never terminates a process when multiple scanner matches are present;
5. verifies the scanner after restart.

### 24x7 overnight intelligence

aplus_overnight_intelligence.py is independent of Dhan. It collects timestamped read-only news context into data/news_intelligence/events.jsonl and maintains a health snapshot.

It covers:
- global markets;
- US macro;
- oil/gold/FX;
- Asia markets;
- India markets;
- SEBI/NSE/BSE/RBI;
- India macro;
- F&O/derivatives;
- corporate events;
- up to 40 symbols discovered from the local F&O market-watch report.

Temporary Internet failures are logged and retried on the next cycle. Existing events are not deleted when a fetch fails.

This is an ingestion foundation, not an order or trade-decision engine. News source publication time is retained as raw metadata; no historical news is fabricated.

### Recovery model

Windows Task Scheduler starts the supervisor and overnight collector at user logon and is configured for delayed start/restart. The supervisor also detects and starts the overnight collector if it is missing.

The Dhan token task remains in the user's interactive context because the existing CAlphaTrader token generator uses the user's Windows credential-store context.

### Safety

This layer does not:
- generate or replace Dhan credentials outside CAlphaTrader;
- modify the trading strategy/order engine;
- fabricate P&L;
- force-close paper positions;
- blindly kill duplicate processes.

Before installing tasks, existing task definitions are exported under data/backups/scheduled_tasks.
