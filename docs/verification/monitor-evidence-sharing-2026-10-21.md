# Monitor evidence sharing verification

Date: 2026-10-21. Baseline: `4c71bcc`. [Specification](../specifications/backtesting/SPEC-monitor-evidence-sharing.md), [tasks](../../tasks/monitor-evidence-sharing.md), [Chinese review copy](monitor-evidence-sharing-2026-10-21.zh-CN.md). [Portable observations](evidence/2026-10-21-monitor-evidence-sharing/measurements.json).

## MSH-V01. Delivered boundary

Share only in-progress pure historical index verification. Each caller opens its own explicit-BEGIN snapshot and compares all literal head/payload fields, SQL value types, JSON bytes, missing markers and candidate count in deterministic order. No hash shortcut, completed cache, response sharing or cross-session ORM entity is used. Original typed/canonical/hash/formula/provider/head checks and verified ranking remain intact, including unselected historical candidates.

Admission is bounded to 1 physical index validator, 1 queued distinct owner, 8 owned reads and 64 MiB retained raw input including conservative object overhead. SQL fetch/comparison batches remain 128 rows. A budget fallback rescans the complete caller snapshot; completion during comparison also requires new verification. There is no extra CPU pool, API/schema change, financial calculation change, retention change or timeout increase.

Each caller retains its own clock, authority-before/after comparisons, activation-identity reread and maximum 2 attempts. Index sharing cannot certify live plan inputs or action eligibility. HTTP cancellation detaches its observer while the complete physical read remains owned; all final exceptions are consumed. The actual WAL checkpoint/database-close callbacks also pause admission by runtime generation and drain reads, covering runtime self-cleanup as well as composition shutdown. Timeout retains ownership and the pause. A successful storage close releases only its own pause; permanent shutdown stays closed. Successful composition shutdown alone enables fresh, short-lived `STOPPED` health diagnostics.

## MSH-V02. Actual request overlap

Before implementation, observe the real local service through Chrome and server-side logical/physical spans. The denominator is monitor reads starting inside each browser phase; a numerator read overlaps another read starting inside that phase. Clip intervals at phase end and count right-censored reads separately. Existing local clients remain included. These short windows establish that overlap occurs, not its prevalence across a production day.

| Journey | Before overlapping reads / starts | After overlapping reads / starts | Before / after physical assemblies |
|---|---:|---:|---:|
| Single result tab + heartbeat | 0 / 3 (0%) | 0 / 3 (0%) | 4 / 3 |
| Two result tabs + health + heartbeats | 10 / 10 (100%) | 5 / 7 (71.4%) | 14 / 7 |

Before windows are 30.047 / 54.831 seconds; after windows are 28.608 / 28.935 seconds. Right-censored reads are 1 / 6 before and 0 / 2 after. Publication can invalidate authority and cause independent retries; logical request counts must not be equated with validation counts. See the portable [before trace](evidence/2026-10-21-monitor-evidence-sharing/read-trace-before.json) and [after trace](evidence/2026-10-21-monitor-evidence-sharing/read-trace-after.json). No evidence bodies or credentials are logged.

## MSH-V03. Ten alternating controlled rounds

Windows / Python 3.14, same frozen read-only monitor copy with 2,008 historical heads and no active plans, fixed observer clock and synthetic stable absent-owner authority. Read an existing immutable backtest result concurrently where specified. SQLite connections use `mode=ro`, `query_only=ON`, explicit transactions and an 8-connection bounded pool. Original methods are extracted from baseline Git source only inside the measurement process. Alternate baseline/candidate order each round. Compare complete dashboard and result objects, including `reportHash` `8a7ea022c843627419f6d02052b085fb3008e94df7059c5dcab0f421bb98871b`.

| Scenario | Median wall before → after (s) | Median process CPU before → after (s) | CPU reduction |
|---|---:|---:|---:|
| Single monitor | 3.7594 → 3.8228 | 3.7500 → 3.7734 | -0.6% |
| 2 monitors + result | 10.0805 → 6.1316 | 10.3359 → 6.1797 | 40.2% |
| 8 monitors + result | 34.4999 → 6.8824 | 36.6328 → 8.8125 | 75.9% |

All 60 scenario executions succeed with complete output equality. In every candidate mixed scenario, exactly one traversal validates all 2,008 candidates: 1 / 7 joins instead of 4,016 / 16,064 repeated candidate validations. Authority provider calls remain 4 / 16 on the owner loop. After physical drain, owned work and retained raw bytes return to zero. Peak retained raw input is 30,826,621 bytes (29.4 MiB), below 64 MiB. The single-monitor median wall increase is 1.7%, below 10%; both mixed CPU reductions exceed 25%.

Sampled Windows working-set medians before → after: single 255.8 → 273.8 MiB; pair 275.7 → 287.3 MiB; eight 345.8 → 346.0 MiB. Working set includes allocator/process history and is separate from the hard retained-input budget. Median per-scenario maximum event-loop delay from a 25 ms ticker is single 58 → 66 ms, pair 111 → 83 ms and eight 148 → 73 ms. These are local samples, not p95, peak system memory or service guarantees. Live authority acceptance is established by deterministic tests, not the synthetic benchmark.

## MSH-V04. Experiments and corrections

The first implementation is correct but misses joins: the GIL-heavy validator finishes while SQLite's exact comparer is still progressing. In a pair-plus-result smoke it repeats 4,016 validations and uses approximately 9.45 CPU seconds. Scalar column reads alone and cooperative thread yields do not fix this. Remove the yield experiment. Finish already-waiting input comparisons before starting CPU verification, within existing admission/deadline limits. This never holds a completed proof open. The corrected smoke validates 2,008 candidates once and uses approximately 5.84 CPU seconds; the ten-round table measures this design.

The initial one-off benchmark used SQLite's in-memory URL default thread pool while opening a file through a custom read-only connector. More than its connection capacity could close connections still in use. Replace that fixture pool with the explicit bounded pool above and discard incomplete runs. No production database or pool is changed.

Regression development also catches a stopped-health compatibility requirement, runtime self-cleanup bypassing the outer drain entry, and Python 3.14's logging of exceptions from a cancelled shield observer. Preserve stopped diagnostics in a new scope; fence actual storage callbacks; use an independently owned task with an explicit observer bridge and final exception consumption. Keep existing assertions. One old generic-runtime test exposes an unintended early-shutdown call outside the new read lifecycle: restrict that early hook to services owning read shutdown. Isolated tamper fixture failures are fixed by modifying the actual revision field; clock rollback may reject before index admission and must not be forced to join.

## MSH-V05. Safety and regression results

- New/raw codec, flights, read ownership, real shared-snapshot tamper/time/authority/input checks and runtime composition: 53 pass in the final matrix, including the additional storage-pause/exception-log cases and actual runtime self-cleanup callbacks.
- Real sharing cases cover 130 historical candidates across the 128-row boundary; noncanonical text, same-size content with restored database mtime, missing payload, provider/formula mismatch, SQL BLOB type and retained-head deletion after a valid read. Differing inputs do not join. Legitimate retained-head deletion fully revalidates the remaining snapshot.
- Concurrent observers cover the 90-second boundary, five-minute target change, date change and clock rollback; configuration/generation, STOPPING/STALLED and unreadable authority; independent inventory/calendar/completion-proof reads and activation identity. Rejected or stale observations cannot expose actionable state.
- Deterministic coordinator/ownership cases cover all literal fields, storage types, missing suffixes, forced hash collision, no completed/error reuse, completion race, byte fallback, distinct queue saturation, original deadline, leader/follower/all-observer cancellation, 8 physical admissions after observer cancellation and held-worker drain timeout/retry. Actual engine disposal records zero outstanding reads.
- Old and new lifecycle/composition plus ownership rerun: 38 pass after restricting the early hook to read-owning services.
- Broader existing integrity/retention/runtime/result regression: 247 pass and 1 generic-lifecycle failure in the first 248-case run; after correcting the early hook, all 38 lifecycle/composition/ownership rerun cases pass, including that failed case. The remaining 247 assertions are retained and pass. This is not a claim of a fresh single-run 248-case result.
- Frontend: 83 files / 1,204 tests, type check and production build pass. All 8 strict workspace/runtime-root Chrome cases pass. Changed Python lint passes.

No assertion, integrity gate or retention rule is removed. Existing Starlette/httpx deprecation and Node color-environment warnings remain unsuppressed. Destructive fixtures use isolated storage only.

## MSH-V06. Real browser and history preservation

Chrome for Testing 157.0.8103.6 against the actual service: list → result → provenance → summary, then two simultaneous result tabs plus health/heartbeats. Both after-change result tabs become visible and support tab switching. Zero business writes and page errors. After-change result-detail GETs return 200.

Observed result-request durations: single 5.745 → 4.360 seconds; simultaneous pair 25.669 / 25.650 → 6.234 / 6.234 seconds. Health in the pair phase completes in approximately 5.986 seconds after change, compared with approximately 19.161 seconds before; a lightweight service probe returns 200 in 45 ms after change. Before tracing did not collect HTTP status or assert both pair tabs became visible, so do not claim those baseline UI outcomes. The live datasets/background traffic differ across time; these are journey observations, separate from the frozen comparison.

Local service restart uses unchanged configuration after checking `READ_READY`, `physicallyDrained=true`, zero active jobs and empty `authorizedJobIds`. Read-only inventory afterward still contains 5 results, 8 plan sources and 2 timeline roots. No provider command, real-data cleanup, history rewrite, migration, job submission, commit or push was performed.

After observation, remove the process-only tracing wrapper and restore the standard module entry with the same configuration. Confirm `READ_READY`, `physicallyDrained=true` and a successful complete historical report read with unchanged `reportHash`.

## MSH-V07. Reproduction and limits

From the project root use `.venv/Scripts/python.exe -m pytest` with fresh isolated `--basetemp` for `test_index_evidence.py`, `test_index_evidence_flights.py`, `test_monitor_read_ownership.py`, `test_monitor_evidence_sharing.py`, `test_runtime_status_composition.py`, plus the integrity/retention/runtime/result modules recorded in the observations. Run changed-file `.venv/Scripts/python.exe -m ruff check` and `git diff --check`.

From `web/`: `npm run test -- --run --maxWorkers=4`, `npm run type-check`, `npm run build`, `npm run test:e2e -- tests/e2e/backtest-workspace.spec.ts tests/e2e/result-read-concurrency.spec.ts`.

One-off observation scripts and frozen copies remain ignored under `.pytest_cache/monitor-sharing-implementation/` and `.pytest_cache/monitor-sharing-analysis-20261021/`. Portable JSON includes all ten rounds and selected real request spans. The benchmark precedes final cancellation/storage-lifetime corrections; the same validation/comparison path is retained and a [final output-equivalence smoke](evidence/2026-10-21-monitor-evidence-sharing/final-smoke.json) is recorded separately (all 6 scenarios pass; pair/eight candidate CPU 5.9219 / 8.9375 seconds, with 1 / 7 joins and zero retained bytes after drain). Full repository backend testing is not claimed. Non-overlapping reads still verify every historical index candidate; changed content and small histories can miss sharing. Future work must preserve these boundaries rather than cache authority or completed proofs.

## MSH-V08. Pre-push review

The user subsequently authorizes review, commit and push. Review covers correctness, evidence safety, ownership, storage shutdown, performance and scope. No blocking findings remain. Baseline/current AST comparison confirms that `_market_index_from_row` and the complete authority-after comparison expression are unchanged. New raw input includes every persisted head/payload column, and retained proof records are immutable.

Pre-push reruns: 136 targeted backend tests pass in 101.22 seconds across raw inputs/flights/ownership, canonical data, real shared snapshots, lifecycle/composition, repository projections, authority, WebSocket, result-thread ownership and pinning. Frontend rerun: 83 files / 1,204 tests, type check and production build pass; all 8 strict workspace/runtime-root browser cases pass. Changed Python lint, whitespace and paired-document identifiers/technical tokens/links pass.

A process-local mutation removes the literal-equality requirement from the join condition. The content-mismatch regression fails as expected, proving that accepting a different snapshot is caught. Production source files are never modified by this mutation. Restore the normal implementation for all passing reruns; do not weaken or skip assertions. Only source, tests, paired documents and portable observations belong in the commits; temporary scripts, frozen databases, logs, credentials and build products stay excluded.
