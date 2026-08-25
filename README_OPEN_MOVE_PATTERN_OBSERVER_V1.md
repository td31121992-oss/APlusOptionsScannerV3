# APlus Open-Move Pattern Observer V1

Adds an observation mechanism inside every normal scanner cycle.

It detects:
- IDEA_PROGRESSIVE: persistent build from 09:15 open with follow-through, participation, retention/range strength and fresh/clean structure.
- KAYNES_REVERSAL: initial adverse move, open reclaim/reversal, acceleration, participation and new directional leadership.

It also records direction flips and one full row for every observed F&O symbol every scanner cycle, allowing reconstruction from the 09:15 open to later high/low.

Outputs:
- data/reports/open_move_patterns_latest.json
- data/open_move_pattern_history/YYYY-MM-DD/open_move_patterns.csv

The patch does not change:
- selective entry gate
- candidate actionability
- option selection
- risk
- expiry fallback
- order authority

No new Dhan/API calls are added.
