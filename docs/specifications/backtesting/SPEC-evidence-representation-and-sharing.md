# Evidence representation and sharing experiment specification

## ERS-S01. Scope

Isolated P0 against 850d904. Preserve existing files. No production hook or service restart. Implementation excludes commit/push; subsequent explicitly authorized submission review is separate.

## ERS-S02. Stages

A: bounded reason-specific timeline. B: typed JSON byte capture with conservative two-generation bounds. C: closed, prepaid collection-time comparison cohort. D: one metadata preflight and one ordered payload cursor. Test variants separately; keep the original full validator.

## ERS-S03. Gates

Keep 64 MiB, 8 readers, 1 physical proof, 1 queued owner, 15-second waiting and 90-second validity. Preserve independent authority, transaction, 2 attempts, exact ordered comparison, all historical validation and physical drain. Cleanup failure retains debt. Valid near-16 MiB input rejection or unproven native bounds blocks P1. After a hard failure run 3 diagnostic rounds per variant at 1/2/8 readers plus mixed reads; retain failures, no performance acceptance or p95 claim. Otherwise retain prior 10 A/A and 20 ABBA/BAAB gates, 20% mixed gain, 5% result and 10% monitor/CPU ceilings. Test tamper, Unicode/NUL/types, changed snapshots, deadlines, cancellation and cleanup. Record source/input hashes and paired report.
