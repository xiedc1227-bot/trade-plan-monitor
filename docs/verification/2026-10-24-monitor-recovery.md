# Monitor stop and recovery investigation — 2026-10-24

## Historical evidence and limits

The previous retained health response identifies runtime `3ba3c81e-5740-4748-8538-b7e0d4c83b4a`, started at `2026-10-23T22:34:09.800563+08:00` and stopped at `2026-10-23T22:34:42.945912+08:00`. Its WAL checkpoint completed immediately before the stop timestamp; HTTP and WebSocket continued serving that stopped owner's state. This establishes resource cleanup, not a process crash or an indefinitely connecting socket.

Available local logs and snapshots do not preserve the exception or stop initiator. Heartbeat failure is a plausible path, not a proven historical attribution. The old health response cannot prove that its startup state was `DEGRADED`, either. Do not retroactively claim that this incident was conclusively caused by the defect below.

## Reproduced defect and correction

`RuntimeLifecycleService.run()` previously marked an exit unexpected only when its captured successful startup result was `RUNNING`. A lifecycle successfully admitted as `DEGRADED` owns a live, read-only recovery loop too. When its heartbeat or retry loop failed, cleanup completed, but `unexpected_run_exit` stayed false. The Web supervisor saw a stopped owner and returned without restarting it.

The exit classification now includes successfully admitted `DEGRADED` lifecycles. After successful cleanup, the existing supervisor may construct a fresh owner and repeat all startup/admission/capability checks. It does not reuse the stopped owner or certify missing data as valid.

The existing limits remain: at most three replacements with `1`, `2`, `4` second delays; no automatic retry of explicit stop, caller cancellation, startup/configuration/migration failure or cleanup failure. Historical interruption admission, review, activation, condition validation and inventory behavior are unchanged. The bilingual LPC006 specification clarifies the admitted read-only recovery scope.

## Diagnostics

Heartbeat failures now emit closed codes for known liveness revision conflicts, backwards clock, expired interruption and invalid storage; unknown failures emit only a generic code. The supervisor records unexpected exceptions, cancellation, invalid health/exit flags, cleanup failure, configuration restart requirement, scheduled replacement, absent replacement factory, exhausted budget and replacement startup failure/success.

Logs contain no raw exception messages, traceback, credentials or provider payloads. The tests inject a private-looking error body and verify it is absent. These diagnostics help attribute subsequent stops; they cannot recover missing historical evidence.

## Verification

- Before the fix: both degraded heartbeat-failure and retry-failure reproductions failed because no replacement started; explicit-stop regression passed.
- After the fix: 5 new tests pass, including fresh-owner recovery, exact restart-budget exhaustion, explicit stop, sanitized logs and a real production composition with offline temporary SQLite/configuration. The production test verifies that reads bind to the new generation while missing capabilities remain blocked.
- Related lifecycle/composition/status suite: 92 tests passed. Changed Python files pass Ruff.
- All unit tests: 3,508 passed. The complete directly related runtime selection passed 205 tests: `tests/integration/test_runtime*.py`, `test_monitor_production_composition.py`, `test_anytime_runtime_recovery.py` and `test_degraded_runtime_supervision.py` (expand the file pattern before passing it to pytest). These totals overlap the focused/new regression runs; they are not additional unique test counts.
- A single combined backend invocation could not collect the existing duplicate `test_backtest_service_contract.py` module names in unit/integration directories. Splitting directories resolved that collection conflict. Extra broad integration selections were stopped during long-running backtest capacity and monitor-loop replay checks; neither is claimed as a full-suite pass. No tests or thresholds were edited to bypass these limitations. A fresh workspace `--basetemp` avoided an unrelated system temporary-directory permission error. Only offline tests were run; live-provider tests were not requested.

## Protected scope

The investigation uses isolated test databases for fault injection. The real local service is restarted only to load the verified code, after checking the listener identity and waiting for port release. No real fault is injected into the user's database.

Target draft: `3c426adf-09d2-48ca-af3d-177caa4f8f65`, plan `605296-SS-WATCH-20261023`. No review confirmation, plan activation, inventory initialization or simulated trade is authorized or performed. Evidence is retained in [this task's directory](evidence/2026-10-24-monitor-recovery/); local databases and configuration secrets are excluded.

The repaired local process started at `2026-10-24T00:15:50.551432+08:00`. Read-only observations at `00:16:32.757128` and `00:19:34.666689` (UTC+08:00) retained generation `0d1b20b3-b38a-4ab2-848d-dcb6e320b0e9`, `RUNNING / STANDBY / NO_ACTIVE_PLANS`, with no stopped timestamp. This confirms several heartbeat cycles, not an unlimited uptime guarantee.

Protected before/after snapshots are identical: all three plan histories, all review histories, the target draft/provenance, activation and inventory tables, risk/manual-event state, this symbol's daily records, storage constraint and configuration hash. The draft remains unreviewed `DRAFT` with exactly 1 technical alert, 0 ordinary rules and 0 risk branches. No reminder delivery test activated the draft. The investigation stage did not commit or push changes. During the separately authorized commit preparation, the 92 related regression tests and Ruff passed again. Archived evidence uses LF line endings, enforced by a directory-scoped `.gitattributes`; `verification.json` hashes the archived bytes so they remain verifiable across platforms.
