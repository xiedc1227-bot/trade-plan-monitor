# S3 stock recovery execution — F3-B

## SRE-01 — Status and boundaries

Base `05487b4` contains accepted F3-A. The approved [startup-minute repair contract](2026-09-27-s3-startup-minute-repair-contract.md), including F3-09, governs this slice. Design and two narrow interface clarifications are approved. Independent Sol implementation review and final hash check are complete: approved, with no P1/P2.

Five candidate files: `src/trade_plan_monitor/runtime/production.py`, `src/trade_plan_monitor/runtime/recovery.py`, `tests/integration/test_s3_stock_recovery_execution.py`, and this paired report. Root retains commit authority. No scheduler/service/composition default wiring, provider/controller policy, schema, dependency, global scope limit, startup acquisition count or original A07 file changed. No push, deployment, live request or real user database was used.

`run_stock_recovery_unit()` is a **directly invoked component**, not autonomous-recovery acceptance. Startup retains F2's at-most-10 transition and has no maintenance reserve. F3-C must still wire lifecycle/scheduler ownership, reduce startup to at most one properly accounted ticket, preserve the startup incomplete completion+30 floor, and close the two original A07 progress RED cases. Index-only operation must not acquire new stock authorization requirements.

## SRE-02 — Single-unit ownership and outcome matrix

- Each unit synchronizes bounded local requirements, claims at most one round-robin ticket, recaptures its exact scope, performs at most one current-day physical request, and reconciles afterward. Cached F3-A facts are not acquisition/commit authority. A replacement activation/target or same-minute clock rewind cannot transfer an old ticket to fresh work; unknown target at an expired local retry is normal zero-fetch retargeting.
- Complete committed prefixes need zero requests. Valid empty/partial responses preserve facts and retry at completion + 30 seconds. Partial facts survive a new owner, and F2's fresh missing-now transaction protects existing rows. One failed symbol does not starve the other nine; physical starts retain shared 1.25-second pacing.
- Only RATE_LIMITED/TRANSIENT/TIMEOUT become provider RETRY, at `max(completion + 30 seconds, next_retry_at)`. An accompanying `retarget_required` and a late target replacement cannot erase that floor. Actual HTTP 429 blocks sibling/index requests through the shared controller.
- BLOCKED_PERMISSION retains the existing authoritative block and F3-A frozen revision. The business unit does not probe or clear it. Local reservation/window rejection is not fabricated as provider failure or cooldown; it receives a concrete local wake.
- ERROR/QUEUE_FULL/CLOSED/INVALID_RESPONSE controller failures propagate the original `RequestControlError`, preserving object identity, attempts and cause, even with retargeting. Local malformed responses without an original request exception raise a fixed sanitized F3-owner `RuntimeError`. Storage/programming/protocol exceptions are not turned into partial data or retry.
- Only an obsolete `_generation_current()` with unchanged non-revoked authority/binding retires normally. Configuration/certification failure, authority Event/epoch/source change and already recorded fatal/storage faults still propagate. `_admission_revoked` is not an ordinary-stop shortcut. A permitted provider retry is accounted before retirement closes the cached wake. Cancellation still propagates after physical drain; owned tickets are not released early.

The approved `ScopedRecoveryResult.request_error` extension is a trailing optional field with `repr=False, compare=False`; only the existing `except RequestControlError` stores the original object. Generic `recover_scope` still returns its existing classifications and the controller is unchanged. This exception is internal only: it is not added to public responses, persistence or reports. `repr=False` is not a general serialization redaction guarantee.

## SRE-03 — Physical boundary and retained startup behavior

Maintenance reuses `_FrozenPermissionMarketWindow`, the existing 31.25-second reserve and inclusive 15-second latest-start bound. A tie yields to market work. The optional invocation-local `_recover_frozen_scope(..., physical_start_guard=...)` checks before waiting, at worker/provider entry after queueing, and after the real certified wrapper/resolver immediately before SDK invocation. Only immutable market times, the thread-safe clock and F2 memory/token fences are used at the worker guard; no worker SQL or asyncio Task inspection is added. Hooks are never stored on a provider/controller or shared across calls.

Tests prove the exact reserve boundary, a real wrapper crossing it with SDK zero, a real controller queue crossing it with SDK zero, and the inclusive latest-start boundary. Already admitted calls may finish later but remain bounded by F2 persistence fences. Startup's default guard remains absent; original C2 still admits its real 10:00:59→10:01:13 call and rejects the future minute. Maintenance's own activity does not count as a new realtime task.

Direct execution and real composition shutdown controls cover wrapper-not-yet-entered-SDK and already-entered-SDK windows. `begin_shutdown` sets the attempt token synchronously before cancellation, keeps the database and physical slot until drain, and allows zero late writes. Cancellation retains late permission-failure accounting and then rethrows. Real SDK-wait reactivation rejects old rows; a later newly captured scope can recover. These are component/ownership controls, not F3-C scheduler progress claims.

## SRE-04 — TDD evidence

TDD/incremental/security/Git discipline kept changes within the approved slice. Fixture-only corrections (calendar cache hydration and using the adapter's recognized requests connection exception rather than a built-in exception) are not product fixes.

| Window | Evidence |
| --- | --- |
| Missing unit entry | 4 failed, 1 warning, 2.16s; then 4 passed, 1 warning, 1.94s |
| Exact reserve and real wrapper crossing | 3 failed, 5 passed, 1 warning, 2.91s; then 8 passed, 1 warning, 2.59s |
| Original request exception / retry+retarget | 14 failed, 9 passed, 1 warning, 5.61s; then 23 passed, 1 warning, 4.87s |
| Root-identified same-minute rewind + approved obsolete-owner termination | 4 failed, 32 passed, 1 warning, 8.28s; then 36 passed, 1 warning, 7.92s |
| Unknown target's retry expires between sync and claim | AttributeError RED: 1 failed, 57 deselected, 1 warning, 1.72s; guarded GREEN: 1 passed, 57 deselected, 1 warning, 1.49s |

Root and independent Sol approved the request-error preservation seam and the narrowly constrained retirement predicate before implementation. No generic error policy was widened. Intermediate 47/53/57 runs preceded the final unknown-target guard and are not final acceptance evidence.

## SRE-05 — Final author verification

Commands run from `trade-plan-monitor`; offline SDKs and temporary databases only. Runs are separate, not additive.

```powershell
.venv/Scripts/python.exe -c "import builtins, pytest; original = builtins.__import__; builtins.__import__ = lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError('A07 is not a committed dependency')) if name == 'test_s3_startup_minute_coverage' else original(name, *args, **kwargs); raise SystemExit(pytest.main(['tests/integration/test_s3_stock_recovery_execution.py', '-q', '--tb=short']))"
```

**58 passed, 1 warning, 13.05s**. The import blocker confirms no dependency on untracked A07; helpers come from committed F2/F3-A and existing fixtures.

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_frozen_startup_recovery.py tests/integration/test_s3_stock_recovery_owner.py tests/integration/test_runtime_recovery_coverage.py tests/integration/test_runtime_recovery_storage.py tests/unit/test_runtime_reconciliation.py tests/unit/test_recovery_targets.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_minute_coverage.py -q --tb=short
```

Direct adjacent: **184 passed, 1 warning, 41.83s**. Original A07: **11 passed, 2 failed, 11.98s**, only A-empty/B-missing-0931 autonomous progress remain RED. All original cutoff/oracle controls pass; assertions were not weakened, skipped or xfailed.

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/production.py src/trade_plan_monitor/runtime/recovery.py tests/integration/test_s3_stock_recovery_execution.py
git diff --check
```

Both pass, scoped rather than full-project. The existing Starlette/httpx deprecation warning remains. No unrelated 350-test permission matrix was rerun.

## SRE-06 — Frozen candidate and independent review

Independent Sol review and final hash check approved the five-file candidate with no P1/P2. Its separate A07-import-blocked run passed **182 tests, 1 warning, 52.58s**: 58 F3-B execution, 35 F3-A owner, 65 F2 frozen recovery and 24 pure schedule tests. The exact independent command was:

```powershell
.venv/Scripts/python.exe -c "import builtins, pytest; original = builtins.__import__; builtins.__import__ = lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError('A07 is not a committed dependency')) if name == 'test_s3_startup_minute_coverage' else original(name, *args, **kwargs); raise SystemExit(pytest.main(['tests/integration/test_s3_stock_recovery_execution.py', 'tests/integration/test_s3_stock_recovery_owner.py', 'tests/integration/test_s3_frozen_startup_recovery.py', 'tests/unit/test_runtime_reconciliation.py', '-q', '--tb=short']))"
```

Scoped Ruff on the three source/test paths and scoped diff checks passed. The reviewer did not independently rerun original A07; SRE-05's 11 passed / 2 failed remains author evidence only. Source/test hashes remained unchanged through review. No implementation-writer commit; root retains commit authority.

| Path | SHA256 |
| --- | --- |
| `src/trade_plan_monitor/runtime/production.py` | `CD1DDCE27C7C1C42BBABE0029039B334A921CE4C5B0836AE231FA5877E66B7E6` |
| `src/trade_plan_monitor/runtime/recovery.py` | `E9F6D412042A4CB6A8A65ED8ED3E9FC4A9D1C9971186F8646AAD5581A2B9C051` |
| `tests/integration/test_s3_stock_recovery_execution.py` | `FF468865FD618D51231B4B9DB84815CD6276346BB393CD732376337E951E9AA3` |

Remaining F3-C work includes real same-generation autonomous prefix repair and 10:05:12 evaluation, maintenance market-cursor/elapsed-review wiring, startup ticket accounting, index-only compatibility and public non-actionable state before legitimate evaluation. C1 and generalized dispatcher/policy changes remain out of scope.
