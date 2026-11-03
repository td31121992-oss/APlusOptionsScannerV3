# APlus Market Event Intelligence

Read-only event awareness for Stock Analysis and News Intelligence.

Includes RBI MPC schedule, major Indian IT Q2 FY27 earnings dates, official SEBI RSS monitoring, market-impact news filtering and Telegram notifications.

October 2026 seeded events:
- RBI MPC: Oct 5-7; the policy decision is represented on Oct 7.
- TCS: Oct 8
- HCLTech: Oct 12
- Tata Technologies: Oct 14
- Wipro and Tech Mahindra: Oct 15
- LTTS: Oct 19
- Infosys and Coforge: Oct 23

Dates are scheduled events, not predictions. The worker must not infer an outcome before the announcement.

Telegram uses the existing Windows CAlphaTrader:Telegram credential store first, then environment variables as fallback. No credentials are committed.

Alerts are notification-only. They never place orders, alter risk, create paper trades, or change the trading engine.

Historical analysis must use explicit as-of timestamps and exclude future events.