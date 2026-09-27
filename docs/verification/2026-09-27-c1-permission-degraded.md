# C1 UPD-S5 — DEGRADED permission maintenance

## Status and scope

Implementation against source baseline `2dfa902`; current HEAD `7abed31` adds task documentation only. Independent source/test review and final report parity passed without remaining P1/P2. This is the approved [UPD-07/08](2026-09-27-c1-unified-permission-dispatch-contract.md) slice, not closure of C1/C3 or the final full-suite gate.

Six writer-owned paths: `runtime/service.py`, `web/monitor_composition.py` under `src/trade_plan_monitor/`; `tests/integration/test_unified_permission_degraded.py`; the narrowly migrated `tests/integration/test_runtime_lifecycle.py`; and this paired report. The separately owned [scheduled permission shutdown](2026-09-27-s3-scheduled-permission-shutdown.md) test/report adds the DEGRADED stop representative. No pipeline, scheduler, provider, schema, public status, threshold, dependency, live service or user database changes; no push/deployment.

## Invariants and implementation

- The optional `next_permission_maintenance_at` callback defaults to `None` timing and preserves falsey callable objects. Production binds the same pure composition getter as RUNNING. Invalid callback/results remain programming errors.
- The existing lifecycle owner fixes startup timing from actual completion using 30/60/120/300 seconds. Permission wakes do not advance attempts, shorten or slide startup timing, or redefine public `next_retry_at`. Both due means one startup first, then at most one eligible permission after normal failure; overrun causes one overdue startup, not replay or parallel work.
- Later shared cooldown and only genuinely related operation floors can extend the fixed deadline. A private bounded enum set records actual retryable `RequestControlError.operation` values, including both initial reference/recovery failures. It does not infer operations from missing capabilities or scan unrelated raw floors. Complete reference plus recovery success clears prior dependencies; a new RUNNING→DEGRADED episode replaces them; clearing cannot shorten an already-fixed deadline. No exception objects are retained.
- Permission work uses the existing `_execute_deadline` and `_work_tasks`. It never enables `_accepting_work`, invokes ordinary market work while DEGRADED, or independently changes DEGRADED to RUNNING. Only a due complete startup succeeds. Existing pipeline, lock, local defers, global/O-F/two-symbol cursor state and generation are retained.
- A real heartbeat may publish NEEDS_RESTART during an outstanding retry wait. The initial read-only run branch now uses the existing explicit-stop wait before returning. An already-requested stop remains immediately releasable. Fatal errors and cancellation retain existing cleanup; no background coordinator is added.

Task ownership/cancellation follow the local Python 3.14 implementation and the official [asyncio task documentation](https://docs.python.org/3.14/library/asyncio-task.html#asyncio.create_task) and [Event documentation](https://docs.python.org/3.14/library/asyncio-sync.html#asyncio.Event). No dependency upgrade was used.

## RED evidence and fixture distinctions

The first four lifecycle tests produced **4 failed in 0.98s**: delayed entry slid the published startup deadline, and the optional permission clock was absent. The minimal clock/callback implementation produced **4 passed in 0.78s**; expansion produced **18 passed in 0.77s**. These are historical component windows, not final integration totals.

Real related/unrelated controller tests produced **1 failed, 1 passed in 2.38s**: calendar permission failure at +1 durably extended its raw floor to +301, but the relevant startup still waited only +30. An unrelated history floor correctly left startup unchanged. The independently approved bounded dependency set closes this P2. Initial dual-error/None-floor/dependency-clear controls first produced **3 failed in 1.42s**, then passed with the fix.

Real token-file drift validated on a worker, followed by the actual heartbeat publishing BLOCKED before releasing the old retry wait, produced **1 failed in 1.84s**: the runner exited without explicit stop. The approved early-return correction closes this P2. An earlier fixture attempt combined manual and actual heartbeat writes and encountered a liveness-revision conflict; that fixture error is not the product RED above. The final case uses only the actual heartbeat loop at that boundary.

The first actual eight-scope fixture lacked a committed stock prefix, correctly triggering the existing blocked startup recovery failure. It was corrected with valid temporary-DB prefix facts; no product gate was weakened. Existing lifecycle fixtures were independently approved for clock consistency: only a real default TIMEOUT advances their virtual clock by its requested delay, plus one explicit before-shutdown TIMEOUT case. SHUTDOWN/cancellation and all original stop/error assertions remain. The migrated file alone passed **51 tests in 1.17s**.

## Candidate verification

All commands run from the repository root with offline fake SDKs and temporary SQLite.

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_degraded.py tests/integration/test_runtime_lifecycle.py tests/integration/test_s3_scheduled_permission_shutdown.py -q --tb=short
```

Final author target: **82 passed, 1 warning in 16.64s** (29 S5 cases + 51 existing lifecycle cases + 2 actual stop modes). Actual DEGRADED composition exercises all eight scopes through owned INDEX_PERMISSION wakes, one SDK per unit, own-scope clearing, exact zero permission-path business changes, unchanged owner/generation and later full-startup restoration. After all proofs, actual public health remains DEGRADED/read-only with the original startup retry time; dashboard and websocket remain non-actionable/not live until a legitimate evaluation. Real both-due failure and 429 cases preserve the new durable 300-second floor; a real fatal ERROR reaches cleanup. Small-clock tests cover progression, ties, overrun, malformed callbacks and fatal-error identity.

The final tests-only addition drives a legitimate unconfigured composition with no pipeline through startup retries at +30/+90 and the next +210 deadline, with unchanged configuration/owner, getter `None`, zero SDK and zero maintenance. It does not introduce or promise online certification installation: initial legal bootstrap is the existing start path; adding a new semantic revision to a frozen absent-revision baseline still requires restart. The two added/strengthened checks first passed **2 tests in 2.91s**. Before this addition the same source target was **81 passed, 1 warning in 16.36s**, with test hash `53B2AB4794E84F7C36A2292096363BC6A126A90535FE14A2BFBDC647C13D29A2`; keep that historical window separate.

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_running.py tests/integration/test_production_a04_retry_timeline.py tests/integration/test_s3_installed_runtime_read_liveness.py tests/integration/test_monitor_production_composition.py tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/unit/test_monitor_runtime.py -q --tb=short
```

Author: **161 passed, 1 warning in 31.47s**, on the final source but before the tests-only addition above. This includes the committed pure absent-pipeline adapter test and real offline DEGRADED composition health test. Do not add counts from separate windows or attribute the later target hash to this earlier window.

```text
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/service.py src/trade_plan_monitor/web/monitor_composition.py tests/integration/test_runtime_lifecycle.py tests/integration/test_unified_permission_degraded.py tests/integration/test_s3_scheduled_permission_shutdown.py
git diff --check
```

Both passed. The warning is the existing Starlette/httpx deprecation. Full SHA256 values below matched before and after the final author 82-target window. The earlier 81/161 window matched the same values except for the explicitly recorded earlier target-test hash:

| Path | SHA256 |
| --- | --- |
| `src/trade_plan_monitor/runtime/service.py` | `FF6D119BE17A0C4C7452CC468D549F8F9E68BC3469FDF0C2B830AD760E956AC1` |
| `src/trade_plan_monitor/web/monitor_composition.py` | `10BB57BC792645115AE045342E796D90FEF99F9E1ADDF6F0296B0B86E2CE6FD2` |
| `tests/integration/test_runtime_lifecycle.py` | `6095D74B06D6718DAA26D100AD332F2175222319F9B07277F5E545E2C608D159` |
| `tests/integration/test_unified_permission_degraded.py` | `DBF72BC1BA54121CC522DB37243588DE2FBFDA04F5CE908295BE30AE7743C125` |
| `tests/integration/test_s3_scheduled_permission_shutdown.py` | `D184921AFF0363C11120DAFEC70B7154F98ADEE568758DDD57D9C23214A0B561` |

## Independent review and remaining gate

The two narrow fixes were independently approved before implementation. The reviewer reported the same commands above on the pre-addition test window: target **81 passed, 1 warning in 16.38s**, adjacent **161 passed, 1 warning in 31.52s**, ten related source/test hashes stable, Ruff/diff passed, and no remaining source P1/P2.

Final independent target, using the exact three-file command above: **82 passed, 1 warning in 16.52s**. Six sources (`production`, `service`, `scheduler`, `composition`, `recovery`, `recovery_targets`) plus four tests (`lifecycle`, `degraded`, `scheduled permission shutdown`, `running`) matched complete pre/post SHA256 JSON; the target hash was `DBF72BC1BA54121CC522DB37243588DE2FBFDA04F5CE908295BE30AE7743C125`. Ruff for the five listed paths and `git diff --check` passed. Source/test review, including the appended absent-pipeline/public-read controls, has no remaining P1/P2. Final bilingual report parity passed. C1/C3 and the fixed full-suite gate remain separately open.
