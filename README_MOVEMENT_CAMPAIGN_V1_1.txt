APlus Movement Campaign Intelligence V1.1 — Direction Persistence

Problem fixed
-------------
V1 could store the first EARLY_CAMPAIGN event by symbol even when it was in the
opposite direction from the stock's eventual move. Example: ANGELONE and
ADANIENT could show an early bearish observation even though they finished as
major gainers.

V1.1
----
- maintains separate UP and DOWN campaign state
- requires 3 consecutive same-direction observations before EARLY_CAMPAIGN
- direction reversal resets the streak
- live shadow stages are explicitly EARLY_CAMPAIGN_UP / EARLY_CAMPAIGN_DOWN
- replay reports the first detection matching the stock's final direction
- opposite-direction detections are retained only as forensic evidence
- remains SHADOW ONLY
- zero Dhan calls
- zero production strategy changes

The scheduled task continues to use movement_campaign_intelligence_v1_shadow.py,
so no scheduler migration is needed.
