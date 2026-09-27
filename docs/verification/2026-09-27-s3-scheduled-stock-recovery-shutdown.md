# S3 scheduled stock recovery shutdown evidence

## Status and scope

TEST-ONLY connected acceptance for the S3-07 `STOCK_RECOVERY` shutdown boundary. The author and independent runs passed in coordinated source-stable windows; independent review approved all three files with no P1/P2. This is one representative connection test, not approval of C1 UPD-S2, the full S3-07 matrix or the overall integration gate.

Owned files: `tests/integration/test_s3_scheduled_stock_recovery_shutdown.py` and this paired report. No production source or existing test was changed by this slice; no commit, push, deployment, live service, real provider, real notification or user database was used. The test reuses the committed A07 `_running`/`_DeadlineClock` composition fixture and the committed identity test's complete-row snapshot helper. SQLite repositories, request control, recovery, scheduling, stop/cancel/drain and database disposal remain real. Only external SDK/notification boundaries are offline fakes; the fixture prohibits HTTP.

## SSR-01 — Real scheduled owner, cancellation and physical drain

Test: `test_scheduled_stock_recovery_stop_revokes_then_drains_before_database_disposal`.

1. Start a real composition at 10:00:15 with one active legacy plan and a partial prefix missing 09:31. Startup performs one stock acquisition and leaves existing minute/latest_quote rows. Release actual scheduler sleeps until its next stock recovery physically enters the fake SDK worker. At the held boundary, assert the actual deadline kind is `STOCK_RECOVERY`, its unfinished task belongs to `runtime._work_tasks`, and `stock-prefix:003043.SZ` is in progress. There is exactly one active, unrevoked recovery token and one occupied controller slot. A transparent observer forwards the original deadline unchanged; it neither chooses a deadline nor calls recovery directly or manually registers an owned task.
2. Call real `composition.stop()`. A synchronous observer immediately after the real `begin_shutdown()` verifies that the token is revoked while both the owned task and runner have zero cancellation requests. Preserve the default five-second graceful drain period, then wait for the lifecycle's actual owned-task cancellation. While the physical SDK is still held, stop and its owner remain unfinished, the controller retains exactly one active slot and zero waiters, the database remains open/READY, and no actual engine disposal has occurred. No new SDK call, notification send or snapshotted fact/business write occurs. Runtime instance, runner and generation remain unchanged, with no runner-failure/restart flag.
3. Release the SDK. Its real fake-provider response contains the missing 09:31 source row, so rejection is not explained by an empty response. Assert exact equality of all minute/latest_quote rows, including received_at, and the snapshotted evaluation/ledger/head/risk/audit/alert/HOLD/eligibility/attempt/pending-close/explicit-rule records. The useful late response cannot commit new facts or overwrite existing ones. No send or additional SDK call occurs.
4. Observe actual SQLAlchemy `engine_disposed`, not a replacement close callback. The order is token-before-cancel, SDK return, database disposal. At disposal the physical slot, waiter and token counts are zero and the owned task is done. After stop, owned tasks/tokens/active deadlines are empty, no recovery scope remains in progress or schedules another retry, database/lifecycle are STOPPED, and the original runtime generation remains. There is no unexpected runner exit, cleanup failure or replacement generation.

The complete-row comparison intentionally excludes heartbeat and request-control bookkeeping, whose legitimate drain/cleanup updates are not business writes. Alert/HOLD/attempt rows are absent controls, not pre-existing delivery fixtures. The 45-second fixture watchdog, 15-second worker barrier and bounded observation waits constrain only the test, not production timing policy.

## Execution evidence

Commands, from `trade-plan-monitor/`:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_scheduled_stock_recovery_shutdown.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_s3_scheduled_stock_recovery_shutdown.py
git diff --check
```

Result: **1 passed in 7.07s**; Ruff and `git diff --check` passed. The surrounding HEAD observations were `39ab6f4fe9237fb62e3debe8e29e4835feac7676` before execution and `2518c32152865decafea0a92a197947c5b2e10ea` during report preparation afterward; unrelated shared-workspace commits continued. The run included the S2 writer's uncommitted minimal wrapper checkpoint. This is source-stable candidate evidence, not a fixed clean-HEAD claim or approval of that unrelated S2 change. All seven SHA256 values were identical immediately before and after the test:

| File | SHA256 |
|---|---|
| runtime/production.py | `6BF2CE8DAA3B797896B39EF4A6201DAEDD8DC3E7C33F2A044339527F9C76A7E7` |
| runtime/service.py | `1FBF2D7C6731F46A4104F0C55C1EC1CB89F3C961482E55D9D87FB7C83FAB84C5` |
| runtime/scheduler.py | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| web/monitor_composition.py | `3030F227DE0DA8EF02C69BF04996FCE92AF10546C577B10D955CED51AA339C68` |
| test_s3_scheduled_stock_recovery_shutdown.py | `C60D72167FD81745C354D417AC1816C3138C937E5837E75C5C384596CFBF0542` |
| test_s3_startup_minute_coverage.py | `93E459A2B2D85A975895F4A374CE59F52BA44EF44C0AC4A5CCA16D153B0387EF` |
| test_s3_stock_recovery_identity.py | `9E47CBB6E5F69D5273647F71E1EA90D9096C2230B8B2098DD48CF59C9FA99ED1` |

This is newly added acceptance coverage of already implemented behavior. It passed on its first execution; no product RED or artificial pre-fix baseline is claimed. A prior line-length-only Ruff failure was corrected before execution. No production repair was needed.

## Independent verification

Independent Sol reran the exact standalone pytest command above: **1 passed in 7.09s**, without warnings. Six source and three test hashes were identical before/after this coordinated S2 checkpoint window. `production.py` was `522560DDFB708A0DA31B6C5321611E96E0D700B5DF7AF9AB6B391ACED27658A7`; the other source and test entries in the author table were unchanged. Target Ruff, static review and bilingual parity passed. The reviewer approved these three paths for local submission; no S2 implementation approval or fixed-commit full-suite result is implied. The author and independent counts overlap and are not additive.

## Limits

This independently reviewed case closes only the missing representative connection between real scheduler ownership and the existing recovery-token/lifecycle stop protocol. It does not repeat late provider-failure/cancellation variants, notification send/receipt ambiguity, process kill/restart, storage/cleanup failures, explicit-rule semantics or the full F1/F2 matrix. Those retain their separate evidence. Later source changes require a coordinated final rerun; this one passing file does not close C1 or the overall S3 gate.
