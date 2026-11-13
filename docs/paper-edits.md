The oracle uses the same merge function as the server. So the simulator validates delivery (loss, duplication, reordering, skew), while the merge rules themselves are validated by the property tests. Say this in the paper.
The “15% dropped and retried” is split into 7.5% lost requests and 7.5% lost responses, plus a 50% chance that a lost response leads to resending under a new batch id.
“Share of entries edited concurrently” is implemented as the probability that an edit targets an entry created by another phone. The conflict rate we report is the measured outcome of that setting.
Section VI-B scale: write the merchants and seeds you actually ran.

Table III’s p95 column applies only to S2, because the baselines run in-process. Mark the others “n/a”.
S1 is defined as batch-key idempotency only. Row-level dedup is what the A3 ablation removes.
The hypothesis “S1 diverges under skewed clocks” becomes “plain clocks let later edits lose (inversions)”. HLC removes them by construction.
Add the “conflicts surfaced %” column and a small ablation table (A1 to A3).
The sweep over concurrent-edit share uses p_conc 0.01, 0.05 and 0.2.