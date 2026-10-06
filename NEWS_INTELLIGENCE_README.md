# APlus News Intelligence Layer

The news layer is an observational/context layer for Stock Analysis and "Why this stock is moving". It does not place orders, modify the trading engine, alter risk controls, or create paper trades.

## Event contract

Each event should have:
- published_at
- symbols
- title and optional summary
- direction: BULLISH, BEARISH, NEUTRAL, or MIXED
- impact: LOW, MEDIUM, HIGH, or VERY HIGH
- confidence: 0.0 to 1.0
- source_type and optional source_url

Events are stored locally at data/news_intelligence/events.jsonl.

## Historical-safety rule

Historical analysis must provide an explicit as_of timestamp. Events published after that timestamp are excluded. This prevents future-news leakage.

Do not manufacture historical news from a current feed. If a historical archive is unavailable, research must report news coverage as unavailable.

## Source priority

1. Official company/exchange/regulatory disclosures.
2. SEBI and other official regulatory publications.
3. High-quality financial/news providers where licensing and access permit.
4. Secondary sources only as supporting context.

SEBI currently publishes extensive market-related news, including press releases, orders, circulars and public-issue material.

## Stock Analysis usage

The UI should show recent relevant events, direction, impact, confidence, source and publication time. News is explanatory context only and must not independently produce BUY, SELL, ENTER or EXIT decisions.

## Future expansion

A separate ingestion job can populate the local event store. It should deduplicate by source URL or source ID, preserve publication time, retain fetch time separately, classify direction/impact/confidence, log failures without blocking the scanner, and never replace an existing event merely because a later fetch failed.

Once enough genuinely timestamped history exists, research can measure subsequent underlying behaviour at +5m, +15m, +30m, +1h and +1D. This remains separate from live trading decisions until validated.
