# Active monitor CPU attribution and isolation specification

[Chinese review copy](SPEC-active-monitor-cpu-isolation.zh-CN.md). [Proposal](PROPOSAL-active-monitor-cpu-isolation.md). User authorized execution on 2026-10-22; baseline `7a7ac88`.

## AMC-S01. Scope

P0 adds default-disabled bounded attribution and an isolated single-process feasibility experiment. P1 is conditional on measured acceptance. Preserve existing edits and exclude parallel AI extraction and daily-inventory work. No commit/push in this implementation phase. No public API, dependency, configuration format, financial semantics or historical-data change.

## AMC-S02. Attribution contract

Record authority health, delivery SQL, configuration/semantic checks, progress and dependency capture without changing synchronous order, yielding inside capture or exporting authority objects. Record index scan/collection, exact comparison, leader/follower waits, full validation, input counts/bytes and physical identity. Scan active time excludes consumer work; inclusive spans remain explicitly inclusive. Use one physical proof trace and follower links, not duplicate physical CPU. Record one aggregate event-loop-lag span per owned read, with a cancelled timer on exit and no detached task. GC profiling is optional and separate from acceptance timings.

Keep 1800 seconds, 1024 traces, 64 active, 64 spans, 128 completed records, 1 MiB files and 2 backups. Log only fixed stages, opaque IDs, timing, counts and byte lengths. Disabled, exhausted or failed diagnostics cannot authorize/reject data, alter retry/cancellation or retain evidence. Reconcile captured >=5-second requests within 5% of server elapsed time or report the gap. CPU clocks are coarse; wall-minus-CPU is not exclusively GIL waiting.

## AMC-S03. Protected semantics

Each read keeps its own authority-before/after, clock, BEGIN snapshot, activation reread, all current plan/inventory/risk/calendar/proof checks and 2-attempt budget. Keep typed parsing, all domain hashes, metadata/head/provider/formula binding, literal canonical equality, full historical traversal and ranking. Keep 8 reads, 15-second cooperative waits/checkpoints, 1 physical validator, 1 distinct queued owner, 64 MiB retained evidence, current result/metadata deadlines and in-flight-only exact-input sharing. Cancellation detaches the observer; actual work, permits, bytes, sessions and storage pauses survive until physical drain. Repeated cancellation, failure propagation and cleanup-failure fences remain intact.

## AMC-S04. Fixed experiment design

Freeze read-only monitor/result inputs before timing. Compare the unchanged pure `_latest_index_records` core in its thread against 1 Windows-spawned process, with identical full input and complete output hashes. Authority and sessions stay in the parent; no ORM, engine, credentials or live owner crosses IPC. Keep the experiment outside production. Measure cold import/startup separately, warm IPC/copies, parent and child CPU, full result completion, monitor completion and combined memory. Record all attempts and failures.

Use 10 A/A pairs and 20 alternating ABBA/BAAB blocks (40 samples per variant) for isolated monitor and staggered mixed result/monitor cases. A mixed result starts after the physical validator is submitted; do not inject sleeps into verification. Measure attribution enabled/disabled with 20 alternating ABBA/BAAB blocks on complete reads. No extending runs until a gate passes. Separate 3 fresh-process memory observations per variant; profiled times are excluded. Freeze the declared order before collection.

Supplement declared after the initial real before/after waves: the observed mixed median increased from 4.675 to 6.010 seconds across a restart. Investigate with exactly 20 alternating ABBA/BAAB blocks (40 per variant) of real mixed HTTP requests in the same running P0 process. Toggle only the diagnostic middleware window between fully drained samples; preserve the same owner, validation and input. Record process CPU, complete result hashes, statuses and all attempts. This additional investigation does not replace the original observations or relax any gate.

## AMC-S05. Gates and P1 decision

P0 attribution targets <=2% CPU / <=5% wall overhead. P1 feasibility requires >=20% mixed result median improvement, <=5% isolated result regression, <=10% monitor median and total parent + child CPU regression, complete equality and safe lifecycle. Measure actual input plus serialization and reconstructed copies against the unchanged 64 MiB boundary; do not count each copy against a separate allowance. A buffered variant exceeding that bound is a no-go even if fast. Do not silently replace it with an unmeasured streaming design. Fix a separate absolute process-memory budget before any production P1. A failed gate defers P1 and retains the current validating path.

Only after feasibility passes, specify/implement the owned production worker, then use 100 fixed attempts per variant for primary actual-owner mixed acceptance. Require >=20% p95 improvement only with >=100 successful observations per variant and disclosed uncertainty; otherwise report a coverage miss. Keep all rejections in the denominator. No worse rejection rate, new timeout/leak or weakened integrity assertion. P0 alone does not claim a production speedup.

## AMC-S06. Verification and real browser

Write failing diagnostic tests first. Exercise normal/error/exhausted/disabled traces, iterator closure and cancellation, exact shared proof links, independent authority changes, full-history tamper, time boundaries, storage-cleanup failure and physical drain. Use process-local mutations of new observation boundaries and existing authority/integrity gates. For the feasibility worker test output equality, corrupted old input, cancellation ownership, actual completion and shutdown; do not call exploratory process tests production acceptance.

Run related backend suites, scoped Ruff and frontend type checking. Run the existing dashboard, stream-completion and backtest browser suites. In the real service, capture 20 result-only and 20 active-monitor HTTP/result attempts plus live heartbeat and bounded 2/8-client journeys; retain failures and actual overlap qualification. Compare P0 tracing disabled/enabled with the same input where possible, and distinguish observed real timings from controlled overhead. Use normal startup/shutdown/drain, never clear a storage fence or historical data. Publish paired reports, portable sanitized samples, source fingerprints and a reasoned P1 decision.
