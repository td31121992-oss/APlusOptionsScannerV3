Corrections V1.1:
1) Runtime validator no longer shows a historical pre-patch safety_blocked cycle as proof_cycle.
   Proof is only taken after an actual PAPER_SAFETY_BLOCK timestamp.
2) Movement Forensics V2.3 merges full-day chart_history with later breakout_evidence,
   so a collector started at 14:36 cannot falsely label 14:40 as the day's movement start.
3) Git cleanup removes obvious accidental/generated artifacts from tracking and adds ignore rules.
No trading strategy changes.
