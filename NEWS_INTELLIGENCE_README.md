# APlus News Intelligence (read-only foundation)

`news_intelligence_data_layer.py` accepts locally supplied JSON Lines records. It does not fetch news, call Dhan, or feed the scanner/trading engine.

Each input line must be an object with `source` and `headline`. Optional source fields are `published_at`, `summary`, `url` or `reference`, `symbols`, `sectors`, `entities`, and `geography`. Optional `observations` are retained as historical research evidence (`price_reaction`, `technical_state`, `option_state`, and `subsequent_movement`); the layer does not create missing observations.

Example invocation:

```powershell
.\.venv\Scripts\python.exe .\news_intelligence_data_layer.py --input .\local_news.jsonl
```

The default output is partitioned by publication date (or capture date when no valid publication time is supplied):

```text
data/news_intelligence/YYYY-MM-DD/
  news_events.jsonl
  stock_events.jsonl
  sector_events.jsonl
  intelligence_manifest.json
```

Classifications are deterministic keyword matches over the supplied headline and summary. Each match records its category, event type, matched terms, and evidence text. The manifest records per-file SHA-256 values. Repeated source URLs (or source/headline pairs when no URL exists) are deduplicated within the daily event stream.

Stock-to-sector edges use only explicit source symbols and the local F&O market-watch symbol/sector mapping. Source-provided sectors are retained as explicit sector edges. No entity recognition, current-event facts, or causal price explanations are invented. The Stock Analysis explanation labels news and sector context as reported or possible drivers and discloses missing evidence.

No news provider/feed is configured in this repository, so the local store remains empty until a user supplies source records. No predictive value is claimed.
