# DNA V2.1 Timezone Fix

The failure was caused by mixing:
- scanner.log timestamps such as `2026-08-25 09:xx:xx` (naive IST)
- report timestamps such as `...+05:30` (offset-aware)

Python cannot sort/compare those directly.

V2.1 converts every aware timestamp to Asia/Kolkata and then removes tzinfo,
so all comparisons use the same IST wall-clock representation.

No strategy threshold, scoring rule, trading logic, Dhan call, or paper/live
execution path is changed.

Run:
`install_and_rerun_dna_v2_1.bat`
