# S3 missed-close discovery after an actual process kill

## Scope

This offline evidence slice adds only `tests/integration/test_s3_missed_close_kill_restart.py` and this paired report. The baseline HEAD at implementation start was `c5ca53d`. Concurrent DAILY_BARS/minute-permission work is outside this change. No production code, migration, existing test, scheduler, or recovery policy was changed. Independent review passed; this local commit is limited to these three files.

The question is whether actual composition can discover an official-close obligation after an SDK call is interrupted by a hard process kill, with no pre-existing close claim, result, or pending marker. The test does not prescribe a recovery date to production or call a recovery/evaluation service directly.

## Scenario and assertions

- SMCKR-01: Seed one legally activated legacy `003043.SZ` plan using `TRADING_DAY` for `2026-09-08`, with actual activation at `09:00 +08:00`, 200 registered shares acquired on `2026-09-07`, authoritative SSE/SZSE calendar facts, and a valid owner heartbeat. Initially there are no evaluation claims/results, risk rows/audits, alerts/attempts, pending closes, or decision heads. Existing migrations run only against the temporary SQLite file.
- SMCKR-02: Spawn P1 at `2026-09-08 14:59:30 +08:00`. Actual composition and its scheduler reach the real adapter's fake `rt_min` SDK boundary at `15:00:12`; a process event proves entry. The SDK worker blocks on a local thread event. The parent verifies zero claims/results/pending, advances only the controlled clock to `17:05`, and waits for P1 to acknowledge that time while reporting `RUNNING`. It then kills exactly that child Process object. P1 never returns from the SDK call or reaches normal `composition.stop()`; the test does not write `DEGRADED`, pending, or recovery state.
- SMCKR-03: Spawn P2 on the same database at either `2026-09-08 17:05` or `2026-09-09 17:05`, after all close attempt times. The plan's one-day policy prevents a new obligation on the following date. P2 calls only actual `create_monitor_composition(...).start()`; its clock releases zero scheduler sleeps. Startup must independently discover and commit the missing `2026-09-08` close, before any future scheduled wake can run.
- SMCKR-04: Require exactly one matching `OFFICIAL_CLOSE` claim and complete result, original plan hash/formula/symbol, activation revision 1, source time `2026-09-08T15:00:00+08:00`, 200-share evaluated inventory, one `BREACHED_PENDING_CONFIRMATION` risk row at revision 1 with close 6000, one risk audit, one `RISK_BREACH` alert, and no pending close. Result evaluation time is P2's restart time for a missed close. Stored risk.updated_at is checked against result.evaluated_at as write time, separately from the official source time. The risk audit is checked for existence and absence of duplication; its created_at is not independently asserted against the write time.
- SMCKR-05: Spawn P3 one minute after P2. Claims, complete result bytes, decision head, risk state/audits, alert records and delivery attempts must match P2 exactly; the persistent fake-channel log must also remain unchanged. Any observed send must be the single expected `RISK_BREACH` event for the original date/symbol; no stale intraday evaluation or send is allowed.
- SMCKR-06: Repeat both restart dates with P1 starting at `15:19:30`. Its real scheduler completes the `15:20` close before its next sleep. Kill this P1 too. P2 must preserve the already committed result/risk/alert, and P3 must preserve the full observed business state. The same-day missing case and both completed controls require one actual fake-channel delivery, making delivery verification non-vacuous.

## Isolation and lifecycle

Every child independently replaces SDK creation, the clock, provider pacing, and notification channels before composition starts. HTTP entry points in requests/httpx are forbidden in each child. The fake SDK supplies valid exchange-session minute rows and an official close of 60.00; its responses pass through the real adapters/controller/composition.

The parent reads only its temporary SQLite file in read-only mode. Each child has its own report pipe/events/clock. After a hard kill, the old IPC objects are not reused by P2/P3. All parent waits are bounded. Cleanup kills and joins only the exact Process objects created by the test, with no PID scan, process-name termination, real service, user database, notification service, push, or deployment.

## Verification and failure classification

1. Before adding the new test, the existing actual-composition spawn baseline `test_production_a06_process_scheduler.py` passed: **2 passed**, 1 existing Starlette/httpx deprecation warning, 11.97s. This confirmed the real composition entry point and existing child-process framework.
2. Initial runs reached P2's autonomous close commit. Three test-oracle/setup errors were corrected without production changes: the risk enum is `BREACHED_PENDING_CONFIRMATION`, not `BREACHED`; stored `risk.updated_at` is write time rather than the source cutoff (see `SPEC-runtime-recovery.md`, current-plan risk contract); and `16:00` is itself a scheduled close attempt, so the after-all-attempts clock was moved to `17:05`. None was evidence of a missing-close production failure. The source-time assertion remains on both the complete result's `source_at` and canonical snapshot's `market_data_at`.
3. The same-day prototype passed **2 tests** in 15.16s. Adding the next-day restart and one-day activation policy produced **4 passed** in 26.52s. No business RED remained; no expectation was weakened to accept a missing result, duplicate, or stale source time.
4. Final targeted/adjacent run: **33 passed**, 1 existing Starlette/httpx deprecation warning, 55.80s. This includes all 4 new scenarios, the 2 actual-composition process cases, and 27 existing missed-close cases. Targeted Ruff and whitespace checks passed; the three untracked files were also checked individually. Parallel work advanced the shared HEAD to `95feccb` by the final checks; this is current-worktree evidence, not a claim about an isolated clean checkout. Only these three files are included in the local commit.
5. Independent review passed: **4 passed** in 27.96s plus Ruff, with no P1/P2 findings; paired structure, numbers and boundaries agree. The requested report-only clarification distinguishes the risk.updated_at assertion from audit existence/deduplication checks. It changes neither tests nor production behavior.

Commands, from `trade-plan-monitor/`:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_a06_process_scheduler.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_missed_close_kill_restart.py -x -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_missed_close_kill_restart.py tests/integration/test_production_a06_process_scheduler.py tests/integration/test_missed_close_execution.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_s3_missed_close_kill_restart.py
git diff --check
```

## Interpretation and limits

The tested official-close obligation survives this kill/restart without a new pending table: existing activation/calendar/completion evidence lets startup discover it. Advancing an in-memory cursor before execution and skipping past deadlines therefore does not by itself prove this official-close restart path loses work.

This closes the specific evidence gap, not all of S3-04. It does not establish recovery of every intraday minute, fairness across many scopes, arbitrary long outages, incomplete/corrupt calendar or inventory, or crash safety at every commit/send window. The next-day missing case permits zero or one valid official-risk send, with one durable risk alert retained; zero physical sends were observed. This slice does not claim cross-day notification liveness or that all historical notifications are suppressed. It verifies no stale intraday sends and no repeated notification intent/attempt in the tested paths. Independent review is complete; the report revision clarifies the verified scope.
