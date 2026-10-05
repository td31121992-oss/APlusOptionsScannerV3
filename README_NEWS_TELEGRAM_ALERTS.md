# APlus News Telegram Alerts

This is a read-only notification layer on top of the existing News Intelligence event store.

## What triggers a Telegram alert

- High / Very High impact market events.
- SEBI circulars, regulatory changes and important securities-market rules.
- F&O, margin, position-limit, expiry, settlement and trading-rule developments.
- Major macro events (RBI/Fed/rates/inflation/FX) and significant geopolitical/commodity events.
- Significant corporate events when the event is classified as material.

It does **not** place orders, modify signals, modify risk, or change the trading engine.

## Telegram configuration

The worker reads these environment variables and never stores credentials in Git:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

If either is missing, the worker logs a warning and continues without sending.

## Deduplication

Sent event IDs are stored in:

`data/news_intelligence/telegram_alert_state.json`

The worker never deletes the source event log. It only records notification state.

## Runtime

Run `run_news_telegram_alerts.bat`. The 24x7 supervisor can own this worker later after local verification.

## Safety

Telegram is notification-only. This worker cannot place orders and does not touch the paper-trade journal.
