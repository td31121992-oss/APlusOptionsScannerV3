APlus Dhan 429 Reliability V2

Evidence behind this patch:
- CAlpha active: 11 HTTP 429 warnings in 5 APlus cycles.
- All CAlpha paused: 3 HTTP 429 warnings in 5 APlus cycles.
This proves both shared-account traffic and APlus internal spacing matter.

Infrastructure changes only:
- Market Quote capped to 0.30 req/sec (minimum ~3.33 sec between attempts).
- Historical capped to 1.50 req/sec.
- Cross-bucket data-call gap: 0.45 sec.
- Exhausted 429 cooldown: 10 sec.
- An exhausted 429 skips one cycle instead of killing the full-day scanner.

Not changed:
- trade thresholds
- selective gate
- risk
- option selection
- expiry fallback
- Leadership
- IDEA/KAYNES observer
- live-order authority
- normal scanner poll cadence

Run only:
install_aplus_dhan_429_reliability_v2_ONE_GO.bat
