# Business step 3: final offline lifecycle gate

## Status and fixed scope

**Full regression PASSED; independent source/matrix review approved the limited completion of business step 3 and C1/C3. Final four-document parity verification PASSED.** Tested source/test HEAD: `e35f3442b874d0766229b5a511fba38e89b02fed`. The coordinator froze source and tests before collection; these four documentation paths were drafted in parallel with the run. HEAD remained unchanged and the post-run source/test diff was empty.

The intended acceptance is business step 3 offline lifecycle integration and C1/C3. The initiative remains **IN PROGRESS**; step 1 retains its limited historical-recovery acceptance. C2, legacy RR004/RR006/RR014 checkboxes, step 4 UI/protocol and C4, and step 5 complete release acceptance and C5 are not automatically closed by this gate. The S3-09 heavy-backtest exclusion is retained; this is not all proposal section 7 release gates.

Only temporary SQLite, fake SDK/transport/channel boundaries and controlled clocks are used. No live provider, real external notification, real user database, push or deployment is included. Configuration changes require safe stop → manual edit → a new process. There is no hot reload. The 120-hour rule uses the legal owner's durable `last_alive_at`, not quote age. Serial restart evidence does not establish an OS-level multiple-instance lock; uncertain sends do not establish external exactly-once delivery.

## S3 evidence and fault matrix

Linked reports retain their original candidate identities, results and limitations. This table maps their evidence to the final combined gate; historical scoped passes are not independently a final gate pass.

| Gate | Exercised boundary and retained requirement | Evidence |
| --- | --- | --- |
| S3-01 / A04 | Four transient failures retain the owner/generation, local reads and 30/60/120/300-second floors; recovery does not exhaust crash supervision. | [Installed retry timeline](2026-09-24-a04-installed-retry-timeline.md), [degraded reads](2026-09-27-s3-degraded-read-health.md) |
| S3-02 / A05 | Conservative legacy `INDEX_MINUTES` inheritance blocks `idx_mins` and `rt_idx_min_daily` separately; each proof clears only its own scope. Durable 300-second reservations, shared 429 and 1.25-second pacing survive sequential processes, including exact due equality in R17. | [Scope migration](2026-09-24-a05-index-permission-scope-migration.md), [provider evidence](2026-09-25-c1-provider-recovery-evidence.md), [R17](2026-09-27-s3-permission-reservation-process.md) |
| S3-03 / C1 | Common bounded permission selection covers all eight scopes, RUNNING scheduling and DEGRADED maintenance. Startup and permission clocks remain independent; permission proof cannot open business admission. | [Common dispatcher](2026-09-27-c1-unified-permission-dispatch.md), [RUNNING](2026-09-27-c1-permission-running.md), [DEGRADED](2026-09-27-c1-permission-degraded.md) |
| S3-04 / A03/A07/A10 | Empty/partial minutes do not prove readiness; same-generation repair is bounded. Session/crossed-deadline behavior and four missed-close kill/restart cases preserve obligations within their tested scope. Full unrestricted historical recovery remains separate. | [Startup coverage](2026-09-27-s3-startup-minute-coverage.md), [bounded recovery](2026-09-27-s3-stock-recovery-wiring.md), [missed close](2026-09-27-s3-missed-close-kill-restart.md), [scheduler fixtures](2026-09-27-s3-scheduler-fixtures.md) |
| S3-05 / A06 | Malformed stock/index dependencies isolate affected plans; healthy plan families progress. Actual sequential-process index recovery retains its floor and performs no stock work or business sends inside the index-only unit. | [Index process](2026-09-27-s3-index-retry-process.md), [A06 fixture evidence](2026-09-27-s3-regression-fixtures.md), [scheduler fixtures](2026-09-27-s3-scheduler-fixtures.md) |
| S3-06 / A09 | F1 exact identity, F2 frozen capture-to-commit fences and F3 bounded same-generation repair reject stale authority. Configuration drift requires explicit stop and a new process; metadata-only refresh remains harmless. | [Identity](2026-09-27-s3-stock-recovery-identity.md), [frozen startup](2026-09-27-s3-frozen-startup-minute-recovery.md), [recovery wiring](2026-09-27-s3-stock-recovery-wiring.md), [DEGRADED drift](2026-09-27-c1-permission-degraded.md) |
| S3-07 / A08/D5 | Four notification commit/send kill windows each use four sequential processes. Actual stock maintenance and RUNNING/DEGRADED permission work stop while SDK work is held; cancellation cannot accept late proof, and physical work drains before database disposal. Lost external receipts can repeat an effect. | [Notification kills](2026-09-27-s3-notification-kill-restart.md), [stock stop](2026-09-27-s3-scheduled-stock-recovery-shutdown.md), [permission stop](2026-09-27-s3-scheduled-permission-shutdown.md) |
| S3-08 / A11 | Installed lunch standby differs from overdue progress. Durable heartbeat cannot make stalled business work healthy; permission/fact repair alone cannot make a decision actionable. This is backend evidence, not the full page/protocol acceptance. | [Installed liveness](2026-09-27-s3-installed-runtime-read-liveness.md), [degraded reads](2026-09-27-s3-degraded-read-health.md), [stock delivery/read boundary](2026-09-27-s3-stock-recovery-delivery.md), [DEGRADED](2026-09-27-c1-permission-degraded.md) |
| S3-09 / C3 | Aggregate lifecycle, migration/rollback, stop/drain and commit/crash/send evidence must pass the fixed-HEAD regression and independent final integration review. | Results and review below; [task order](../../tasks/runtime-recovery-todo.md) |

Migration/backup coverage in the completed aggregate is traceable to [scope migration tests](../../tests/integration/test_index_permission_scope_migration.py) (child-process interruption rolls back the split; downgrade refuses retained new-scope state), [recovery storage tests](../../tests/integration/test_runtime_recovery_storage.py) (pending-state downgrade refusal and empty downgrade path), and [SQLite backup tests](../../tests/integration/test_sqlite_backup.py) (online backup includes uncheckpointed WAL writes and restores to a readable temporary database). Related 120-hour/liveness/expiry evidence: [runtime liveness tests](../../tests/integration/test_runtime_liveness.py) and [plan expiry tests](../../tests/integration/test_runtime_plan_expiry.py). This is the existing offline test inventory, not a new backup operation.

## Completed slices and historical failures

`53b731271b4b3a10a8558da993ecd000f03c1d58` completes UPD-S5: fixed 30/60/120/300-second startup timing, independent eight-scope maintenance, extension only for related startup operations/shared cooldown, retained pipeline/owner and explicit-stop waiting on source drift. Final author target: **82 passed, 1 warning in 16.64s**; independent target: **82 passed, 1 warning in 16.52s** (29 DEGRADED + 51 lifecycle + 2 scheduled permission-stop cases). The separate adjacent window is recorded in the [DEGRADED report](2026-09-27-c1-permission-degraded.md), not added to this count.

The earlier `453cc0c` aggregate remains **18 failed, 4778 passed, 1 skipped, 4 deselected, 1 warning in 670.06s**, as recorded in the [historical regression report](2026-09-27-s3-offline-regression.md). The later full run at `53b731271b4b3a10a8558da993ecd000f03c1d58`, using the full command below, remains **16 failed, 5695 passed, 1 skipped, 4 deselected, 1 warning in 1087.48s**. Neither result is rewritten as passing.

Those 16 failures were obsolete test premises after approved bounded startup, common permission ordering and additional maintenance wakes. Two independently reviewed test-only corrections preserve production source and execute the original downstream business assertions without deleted tests, added skips/xfails or weakened business checks:

- `2dc2919a1fe8b2f38b1dce9843ad16b70e80eab2`: three scheduler fixture files; author **24 passed, 1 warning in 30.91s**, independent **24 passed, 1 warning in 31.21s**. [Evidence](2026-09-27-s3-scheduler-fixtures.md).
- `e35f3442b874d0766229b5a511fba38e89b02fed`: five regression fixture files; author **41 passed, 1 warning in 95.00s**, independent **41 passed, 1 warning in 94.92s**. [Evidence](2026-09-27-s3-regression-fixtures.md).

The two groups cover 65 distinct cases; repeated author/reviewer windows and the full-suite count are not additive.

## Fixed-HEAD gate results

```text
.venv/Scripts/python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short
.venv/Scripts/python.exe -m ruff check src tests scripts
git diff --check
```

| Gate | Actual observation |
| --- | --- |
| Collection at `e35f3442b874d0766229b5a511fba38e89b02fed` | 5712/5716 tests collected, 4 deselected, 2.12s |
| Full S3-09 regression | **5711 passed, 1 skipped, 4 deselected, 1 warning in 1074.18s (17:54)**; exit code 0 |
| Ruff `src tests scripts` | Passed before and after the full run |
| Diff whitespace | Passed before and after the full run; final documentation check passed |
| Source/test stability | Post-run `git diff --name-only -- src tests` returned no paths; HEAD unchanged; working-tree changes limited to the four documentation paths |
| Final independent integration review and bilingual parity | Astra approved source/matrix and limited step 3/C1/C3 closure with no P1/P2; final four-document parity **PASSED** |

The four deselections are live tests. The single Windows/POSIX-semantic skip is `test_backtest_production_composition::test_cursor_key_rejects_foreign_posix_owner_before_use`. The heavy `tests/integration/test_backtest_acceptance.py` exclusion comes from S3-09. The warning is the existing Starlette/httpx deprecation; no dependency change is part of this gate.

## Review and completion boundary

Bounded implementation used `gpt-6-sol` / `high`; conditional migration-plan review used `gpt-6-sol` / `xhigh`. Final integration review used `gpt-6-astra` / `xhigh`; settled documentation uses `gpt-6-sol` / `medium`. Astra approved source/matrix closure after assessing the fixed-HEAD full pass, pre/post checks, independently reviewed 65-case fixture correction and evidence matrix: no P1/P2 or additional unmet gate within approved step 3 remains. The earlier pending-document parity review passed; final four-document parity **PASSED**. The coordinator alone records the final local documentation commit after review; its identity must be distinguished from the tested source/test HEAD above.

Business step 3 and C1/C3 are complete only within this approved offline lifecycle scope. No statement here certifies real-service permissions, an OS-level multiple-instance lock, every historical fault scenario, step 4 or step 5. The initiative remains IN PROGRESS.
