# Pre-allocation global byte admission experiment specification

## GBA-S01. Scope

P0 is an isolated experiment under scripts/experiments against 1748555. Preserve all production code and existing analysis. No service restart or live-data change. Implementation itself does not commit or push; a subsequent submission review may do so after explicit user authorization. P1 requires every feasibility gate.

## GBA-S02. Admission

One injected ledger covers retained inputs, transport, SQL/conversion work and metadata across readers and draining proofs. Keep 64 MiB, 8 readers, 1 physical validator and 1 queued owner. Reserve before payload execute. Reserve 128 KiB metadata per scanner, use 32-row metadata pages and initially 1 MiB scan work. Size all selected columns using typeof and octet_length in the original explicit transaction. Check UTF-8 capability. Bound payload queries by admitted row locators. Never replace exact comparison or original validation with metadata. Native/internal allocation remains an independently measured gate.

## GBA-S03. Ownership

Reserve progress before pinning a proof; leaders do not wait for unadmitted comparisons. Release comparison rows/cursors and pins before queueing a mismatching owner. Preserve each request transaction, before/after authority and activation checks, 2 attempts, 15-second waiting deadline and 90-second eligibility. Keep leases through generator carry-over, cancellation and child DRAINED/confirmed exit. Cleanup failure fences the ledger. No post-submit fallback, completed-proof cache or refreshed deadline. Oversized retained input may use fully validating budgeted streaming before submission; an unadmittable single row fails closed and fails the availability gate.

## GBA-S04. Frozen gates

Input budget stays 64 MiB. Freeze experimental aggregate working-set ceiling at 768 MiB and private-commit ceiling at 2560 MiB before sampling, based on earlier 506.63 MiB / 1938.95 MiB process observations with headroom. These are experimental ceilings, not a deployment memory guarantee. Require complete proof/output equality, independent authority, no deadlock or early cleanup, and no new rejection of valid fixtures. Include near-16 MiB supported input and malformed oversized values. If any hard gate fails, P1 is no-go and fixed performance acceptance stops; collect 5 diagnostic rounds for 1/2/8-reader comparisons and 5 alternating mixed pairs instead, clearly excluded from performance acceptance. Do not replace failures or loosen limits.

## GBA-S05. Performance

If hard gates pass, use 10 A/A pairs and 20 ABBA/BAAB blocks per pairwise workload for original thread, budgeted thread and budgeted process, including isolated and mixed reads. Require at least 20% mixed result improvement for process integration, at most 5% isolated result regression and 10% monitor/total CPU regression. Record admission waits, SQL count, shares, mismatches, leases, failures and full completion. Parent/child synchronized memory is separate from Python allocations. Unproven native bounds or unspecified deployment ownership still block P1; browser/real-owner acceptance is conditional on integration, with 100 attempts per variant and no p95 claim below 100 successes.

## GBA-S06. Verification

Test exact byte boundaries, acquire-before-execute, type/length round trips, old/missing/canonical corruption, changed snapshots, 8-reader progress, queued-owner pressure, deadlines, repeated cancellation and cleanup failure. Reuse unchanged authority/retention/ownership regressions and exercise process transport drain. Mutation checks must detect missing reservation, early release and bypassed literal comparison. Publish paired reports with source/input fingerprints, all diagnostic attempts and explicit limitations.
