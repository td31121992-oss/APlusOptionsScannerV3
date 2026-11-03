import pattern_log, key_level, sys
for d in ("2026-10-14","2026-10-13","2026-10-12","2026-10-09","2026-10-08","2026-10-07","2026-10-06","2026-10-01"):
    try:
        print(d, pattern_log.run(d), flush=True)
    except Exception as e:
        print(d, "failed", e, flush=True)
    print("key level:", key_level.write(), flush=True)
