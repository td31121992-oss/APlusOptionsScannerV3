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

## Opt-in SEBI RSS reader

`sebi_rss_adapter.py` is an optional, one-shot reader for the official SEBI RSS
feed at `https://www.sebi.gov.in/sebirss.xml`. It retrieves only when invoked
with `--fetch`; importing it, running it without that flag, or running the
existing JSONL normalizer does not contact the source. It performs one request
per invocation, has a 15-second timeout and a 3 MiB response limit, and has no
credentials, scheduler, or continuous runtime.

```powershell
.\.venv\Scripts\python.exe .\sebi_rss_adapter.py --fetch
```

The adapter maps source, headline, summary, timezone-aware publication time,
URL, and GUID/reference into the existing record format. Items without a
usable publication timestamp are skipped; capture time is never substituted
for publication time. Retrieval/XML failures produce a safe status without
ingesting partial data. Feed entries are deduplicated by link, GUID, or title
and publication time before the existing daily-store deduplication runs.

This feed contains SEBI press releases, circulars, and orders/rulings. It does
not supply exchange-listed company symbol/sector mapping or prove that an
announcement caused a stock move. All classification remains a deterministic
keyword observation, not a causal or trading signal. Keep this use local and
retain source attribution and links; SEBI's website policy requires permission
for reproduction of site material and acknowledgment of the source. The RSS
page publishes no numeric rate limit. No scheduled collection is installed.

Official source information: <https://www.sebi.gov.in/rss.html>. No live-feed
success is implied by fixture-based tests; enable the adapter explicitly to
verify the feed in the local environment.
