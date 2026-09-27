# S3 frozen startup minute recovery — F2 implementation

## F2-IMPL-01 — Status and boundary

2026-09-27. Approved design: paired `2026-09-27-s3-startup-minute-repair-contract` A07-F2 / VERIFY-02 / VERIFY-05, plus the independently approved narrow token-before-cancel seam. Independent implementation review passed with no P1/P2; writer and independent evidence are separated below. Final follow-up candidate base: `4b1c823a40a7b4fd8e0b85eca78920dfa08f5710`, plus this uncommitted slice.

Scope: `runtime/production.py`, `runtime/recovery.py`, `runtime/recovery_targets.py`, `runtime/service.py`, `web/monitor_composition.py`, new `tests/integration/test_s3_frozen_startup_recovery.py`, and this report pair. Reuses committed business SDK hook `e7c6d8f`; no provider, controller, scheduler or UoW changes. No push, deployment, real service, real user database, schema change, permission reset, or new business recovery loop.

F3 is not implemented: transitional startup still permits at most 10 symbols, each with at most 240 required minute ends. Startup retarget/yield remains a startup failure under the existing transitional error policy; it is not F3's normal maintenance outcome handling. No maintenance reserve is added to startup. Existing official-close ordering and policy remain intact. Explicit current-day prefetch is not a new legacy-prefix readiness requirement for explicit evaluation.

## F2-IMPL-02 — Implemented contract

- Immutable `RecoveryCapture` retains the original target/cutoff, exact prefix, canonical payload/hash/version/activation identity, configuration and semantic revisions, source object identities, runtime generation, epoch and revoked Event identity.
- `recover_scope` accepts invocation-local persistence, business-fetch and admission callbacks plus a thread-safe attempt token. The generic compatibility path still calls `current_day_minutes(symbol)`. Production binds the concrete provider's `_physical_start` after real wrapper preparation; there is no shared callback replacement, worker SQL, or worker Task inspection.
- Capture and response persistence use separate short owned transactions. Final persistence rereads exact identity, calendar and committed required ends, then inserts only response rows still in `missing_now`. A concurrent legal minute and its latest_quote contribution are preserved even when the older request receives a later normalization timestamp.
- External validation and repository staging/flush occur outside the baseline `RLock`. Inside are the fresh memory/clock predicate and synchronous commit. A failed fence rolls back minute and latest_quote together. A real two-connection stale read snapshot produces `SQLITE_BUSY_SNAPSHOT`; there is no old-capture retry.
- Guard changes are typed retarget outcomes at both coverage reads and persistence. Recognized storage failures retain the original exception in a non-repr result field, and startup propagates that exception. Programming errors and cancellation propagate; cancellation publishes the attempt token before draining the owned physical call.

## F2-IMPL-03 — Authority and source evidence

Both actual composition worker setters `_revoke_configuration` / `_revoke_semantics` publish Event and increment epoch under the shared baseline `RLock`, then notify the owner loop after release. Actual `_open_database_sync` places only the READY / WAL READY assignments under that lock; migration and disposal remain outside. Final admission retains the old lifecycle's `_stopping`, `_cleanup_complete`, `_cleanup_failed`, `_liveness_failed` and generation/database-readiness checks; it does not add `_accepting_work`. Other audited authority changes remain owner-loop publications. Moving scoped persistence to a worker would invalidate this proof.

Local versions: Python `3.14.7`, SQLite `3.50.4`, SQLAlchemy `2.0.52`; dependencies were not upgraded. The existing engine uses `isolation_level=None` and a begin listener that emits `BEGIN`, so this slice adds no second BEGIN. This matches the official [SQLAlchemy SQLite transaction recipe](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#enabling-non-legacy-sqlite-transactional-modes-with-the-sqlite3-or-aiosqlite-driver); the website currently documents `2.0.54`, not the installed patch.

Installed `sqlalchemy/orm/session.py` `_prepare_impl` / `commit` dispatch before/after-commit events and flush pending work. The application registers no application commit/flush callbacks (`rg` finds only engine connect/begin listeners); repository minute/latest_quote staging is already flushed before the lock. Do not generalize this into “SQLAlchemy never invokes callbacks.” See [Session flushing](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#flushing). The integration test asserts a clean session before commit, SQL only on the owner outside the authority lock, and three separate explicit transactions for pre-read/final-write/post-read.

Real stale-snapshot and lock-order tests follow [SQLite snapshot isolation](https://www.sqlite.org/isolation.html) and [Python 3.14 RLock semantics](https://docs.python.org/3.14/library/threading.html#rlock-objects). Tests cover revoke-first rollback, commit-first completion followed by revocation, actual worker notifications outside the lock, and synchronous validation-triggered revocation without deadlock. No same-lock worker is joined inside the lock.

## F2-IMPL-04 — RED and pre-token-follow-up writer verification

All commands run from `trade-plan-monitor` against temporary offline databases.

The 108 / 247 / 350 counts in this section are the **pre-token-follow-up window**, observed on base `9548f7a65f26172c486e315b2a81f98353e17982` plus the earlier candidate. They are not reused as final follow-up evidence; see F2-IMPL-05.

Initial original A07 control:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_minute_coverage.py -q --tb=short -k 'real_provider_filters or frozen_acquisition_cutoff or new_real_acquisition'
```

Result before F2: **1 failed, 2 passed, 10 deselected, 3.58s**. C2 wrote an extra `10:01` row after the real `10:00:59` → `10:01:13` SDK call. C1 future filtering and C3 a new later capture were positive controls. Initial new seam tests also observed three genuine REDs (missing per-call persistence and two swallowed programming errors), then a missing business-fetch callback RED, three missing capture/persistence API REDs, and a capture-authority silent-skip RED before their corresponding fixes.

Test packaging was corrected before final verification: the original A07 test is untracked and must not be a dependency of this slice. Blocking that module through `builtins.__import__` initially produced **no tests collected, 1 import error**. The new composition fixture is now local and references only already-committed helpers. The unchanged A07 test/report pair is not part of this slice. Fixture-only corrections (calendar required field, composition state access and a valid replacement SDK object) are not product defect fixes.

Pre-follow-up target and direct adjacent checks, with the A07 import explicitly forbidden:

```powershell
.venv/Scripts/python.exe -c "import builtins, pytest; original = builtins.__import__; builtins.__import__ = lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError('A07 is not a committed dependency')) if name == 'test_s3_startup_minute_coverage' else original(name, *args, **kwargs); raise SystemExit(pytest.main(['tests/integration/test_s3_frozen_startup_recovery.py', 'tests/integration/test_runtime_recovery_coverage.py', 'tests/unit/test_recovery_targets.py', '-q', '--tb=short']))"
```

**108 passed, 1 warning, 33.01s**, including **52 new F2 cases**. Covers immutable exact identity/prefix, concurrent callback isolation/default compatibility, both typed coverage-read guards, original storage cause, real wrapper delay/revocation/source replacement, before/after-SDK cancellation and drain, final fence mutations, actual composition authority writers, all four lifecycle admission flags, no added accepting-work dependency, true two-connection reactivation rollback, and the real provider-wait concurrent minute/latest_quote winner.

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_stock_minute_permission_execution.py tests/integration/test_production_stock_minute_permission_preparation.py tests/unit/test_current_day_business_sdk_boundary.py tests/unit/test_stock_minute_permission_proofs.py -q --tb=short
```

**350 passed, 1 warning, 29.74s**.

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_runtime_recovery_storage.py tests/integration/test_runtime_lifecycle.py tests/integration/test_recovery_activation_fences.py tests/integration/test_live_pipeline_acceptance.py tests/integration/test_explicit_runtime_production.py tests/integration/test_production_semantic_gate.py tests/unit/test_recovery_coordinator.py tests/unit/test_monitor_runtime.py tests/unit/test_request_recovery_admission.py tests/unit/test_production_historical_recovery.py tests/integration/test_s3_missed_close_kill_restart.py -q --tb=short
```

Pre-follow-up rerun: **247 passed, 1 warning, 113.26s**, including the four actual official-close kill/restart windows and lifecycle/manual-stop/liveness coverage. The preceding identical 11-file command also passed 247 cases in 112.53s.

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_minute_coverage.py -q --tb=short
```

**2 failed, 11 passed, 12.62s**. Only the unchanged F3 autonomous-progress cases (`A-empty`, `B-missing-0931`) remain RED. C2 and all three oracle controls pass; no skipped/xfail tests, weakened assertions, or suppressed startup calls were introduced. This is not complete A07 acceptance and does not rely on supervisor replacement for recovery.

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/recovery.py src/trade_plan_monitor/runtime/recovery_targets.py src/trade_plan_monitor/runtime/production.py src/trade_plan_monitor/web/monitor_composition.py tests/integration/test_s3_frozen_startup_recovery.py
git diff --check
```

Both pass. The test warning is the existing Starlette/httpx deprecation.

## F2-IMPL-05 — Token-before-cancel follow-up

The pipeline's owner-loop registry holds each attempt Event from before its first await until physical drain completes. `revoke_active_recovery_attempts` only sets these Events. It does not cancel, clear, join, query SQL, take the authority lock, or modify the shared baseline revocation flag. A late attempt registers, rechecks current admission/generation before its first await, sets its token and exits with `RecoveryAdmissionChangedError` if invalid. The existing cancellation fallback remains.

Composition forwards the synchronous callback, including a no-op before a pipeline exists. `RuntimeLifecycleService` validates the optional callable and preserves a valid falsey callable. `begin_shutdown` publishes `_stopping` / `_accepting_work`, then invokes revocation before dispatcher/controller shutdown or any task cancellation. Callback failures are latched and enter existing stop cleanup instead of escaping this synchronous entry. Successful repeats cannot erase an unreported failure. Only after `stop` / `_observe_stop_result` reports it may a later successful callback allow the existing cleanup retry to consume it. Drain failures retain their original primary exception and `__cause__`; `recovery_revocation_error` separately retains the revoker exception. Database disposal still waits for drain.

New RED evidence: the two real before/after-SDK `begin_shutdown` tests plus the repeated-stop failure latch initially produced **3 failed, 52 deselected, 3.31s**, then **3 passed, 52 deselected, 2.78s**. The valid falsey callable separately failed, then passed in **1.18s**. These controls make synchronous assertions immediately after `begin_shutdown`, without await/sleep: token set, task not cancelled, worker not drained, database still READY. Additional controls cover heartbeat/dispatcher/provider drain causes, late attempts, unpublished pipeline-less candidates, repeated stop, new-generation token isolation and noncallable constructor rejection. The final F2 file contains **65 cases**.

Final follow-up runs use the exact four commands in F2-IMPL-04, after the falsey fix with all five source files and the test frozen:

- Forbidden-A07 target/direct-adjacent three files: **121 passed, 1 warning, 37.29s** (65 F2 cases).
- Permission/SDK four files: **350 passed, 1 warning, 29.84s**.
- Lifecycle/recovery eleven files: **247 passed, 1 warning, 113.70s**.
- Full original A07: **11 passed, 2 failed, 12.84s**, only the two F3 autonomous-progress cases; C2 and all oracle controls remain GREEN.

The intermediate pre-falsey window (120 passed in 36.85s, 350 passed in 29.22s, 247 passed in 113.24s, and A07 11 passed / 2 failed in 12.38s) is historical, not reused as final evidence. The earlier 108 / 247 / 350 window in F2-IMPL-04 preceded the entire token follow-up.

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/recovery.py src/trade_plan_monitor/runtime/recovery_targets.py src/trade_plan_monitor/runtime/production.py src/trade_plan_monitor/web/monitor_composition.py src/trade_plan_monitor/runtime/service.py tests/integration/test_s3_frozen_startup_recovery.py
git diff --check
```

Both final checks pass. All six source/test hashes remained stable through the final verification window.

## F2-IMPL-06 — Handoff

Independent Sol review passed with no remaining P1/P2 and closed the token-ordering item. Its exact final command was:

```powershell
.venv/Scripts/python.exe -c "import builtins, pytest; original = builtins.__import__; builtins.__import__ = lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError('A07 is not a committed dependency')) if name == 'test_s3_startup_minute_coverage' else original(name, *args, **kwargs); raise SystemExit(pytest.main(['tests/integration/test_s3_frozen_startup_recovery.py', 'tests/integration/test_runtime_lifecycle.py', 'tests/integration/test_monitor_production_composition.py', '-q', '--tb=short']))"
```

Independent result: **138 passed, 1 warning, 36.57s**. Independent full original A07 command from F2-IMPL-04: **11 passed, 2 failed, 12.00s**, again only F3 progress. Independent Ruff was limited to the five changed source files plus the new test (not full-repository lint); it and `git diff --check` passed. The reviewer confirmed all six source/test hashes stable.

The packaging dependency and literal token-ordering gaps are historical and closed. Stop uncommitted for root-coordinated report-parity confirmation and an exact eight-file local commit; no push. F3 autonomous recovery and later C1 calendar/history owner wiring remain separate approved slices, so this is not complete A07 acceptance.
