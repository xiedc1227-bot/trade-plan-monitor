# S3 scheduled permission maintenance shutdown

## Status and dependency

Author result: **1 passed, 1 warning in 6.68s**. Independent static review and rerun: **limited pass**, **1 passed, 1 warning in 6.53s**, no P1/P2 findings for this case. This is a new UPD-R16 connected acceptance case, not a baseline RED or production fix. Only `tests/integration/test_s3_scheduled_permission_shutdown.py` and these paired reports were added.

The tested checkout is HEAD `54b70f6aad10770346697637386de8a22d136633` plus the UPD-S4 candidate changes in `runtime/production.py` and `web/monitor_composition.py`. The test imports the stable `_composition(..., stock=False)` helper from the **uncommitted** `tests/integration/test_unified_permission_running.py`. It also reuses committed R17 snapshot helpers in `test_s3_permission_reservation_process.py`; the S4 helper uses the committed composition, A07 clock and proof-frame fixtures. This test/report set must land with accepted S4 source/helper or immediately after them, not independently onto the stated HEAD.

## R16-P01 — Actual RUNNING owner and late proof

1. Create a genuine index-only composition, temporary SQLite, legal liveness, current/open SSE calendar and completed historical anchor. Seed only an `INDEX_HISTORICAL_MINUTES` latch due at `2026-09-08 10:00:16+08:00`. This seed is fixture input, not the measured reservation. Startup is RUNNING with zero SDK calls and unchanged checkpoints.
2. Park and release the original scheduler's actual first wait. Its `INDEX_PERMISSION` duty enters the common path in a task already owned by `runtime._work_tasks`; the test never invokes a private unit or `run_deadline` directly and never registers its own work task. The permission lock is held and `_running_deadline` remains false.
3. Hold the actual fake `idx_mins` SDK body in its worker thread. Exactly one SDK call has entered; the real controller has durably replaced the seed with `10:05:16` (`actual due + 300 seconds`) and advanced the original scope cursor. The physical slot count is 1 and queued count is 0.
4. Call real `composition.stop()`. A transparent observation after the original synchronous `begin_shutdown` confirms `business_commit_admission_open` and the captured generation admission are false, the controller is closed, and neither the owner nor runner has yet been cancelled. This asserts existing permission admission revocation, not a stock-recovery token protocol.
5. Retain the real **5.0-second** grace period; assert at least five monotonic seconds before actual owned-task cancellation. After cancellation the logical permission lock is free, but the shielded proof remains pending, the SDK is still held, physical count remains 1, the database is open/READY, disposal has not occurred, and stop is unfinished. There is no additional SDK call or business/checkpoint mutation.
6. Release the SDK. A complete valid 48-row historical response passes the real provider proof function, but final cancelled-owner validation rejects it as `RequestControlError(INVALID_RESPONSE)`. It cannot clear the original permission latch or erase/change the durable reservation. This is final owner rejection, not a claim that the frame was malformed.
7. The actual SQLAlchemy `engine_disposed` event occurs only after release, physical/queued counts 0, permission rechecks 0 and the owner done. Stop completes with the original runner done, owned tasks empty, controller slots/rechecks empty, database STOPPED and the same runtime generation; no runner failure, replacement or cleanup failure occurs.

The hard-observed boundary sequence is:

```text
admission-before-cancel
owner-cancelled
sdk-returned
valid-proof-returned
database-disposed
```

Full application-table rows, including timestamps, are compared from before the maintenance duty through held/cancelled/released/stopped boundaries. Schema metadata, runtime liveness and provider-recovery bookkeeping are excluded from that business snapshot; provider checkpoints are separately compared exactly. Evaluation/risk/HOLD/delivery/audit state, market facts, quotes and index snapshots remain unchanged. Real market-window checks, controller pacing, timeout, liveness and stop/drain implementations are retained.

## Commands and frozen candidate evidence

From the repository directory:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_scheduled_permission_shutdown.py -q --tb=short
.venv/Scripts/ruff.exe check tests/integration/test_s3_scheduled_permission_shutdown.py
git diff --no-index --check -- NUL tests/integration/test_s3_scheduled_permission_shutdown.py
git diff --no-index --check -- NUL docs/verification/2026-09-27-s3-scheduled-permission-shutdown.md
git diff --no-index --check -- NUL docs/verification/2026-09-27-s3-scheduled-permission-shutdown.zh-CN.md
```

Author target: **1 passed, 1 warning in 6.68s**. The warning is the imported FastAPI/Starlette test client's existing `httpx` deprecation notice; no live request was made. Target Ruff passed. Whitespace checks passed with only Git's ordinary LF/CRLF notices.

The source writer froze the two source seams and the shared helper interface for this run. Full JSON hashes were recorded before/after pytest, with `Compare-Object -Property Path,Hash` finding no differences across these six source files and two test files:

| File | SHA-256 |
|---|---|
| `runtime/production.py` | `F1083412137BDD38EDC6EF2B03F9C85797C6CCEDC6A5F7030D80E1B9211DC9BC` |
| `web/monitor_composition.py` | `A716E8B068919E5C2AD2D68F19CA65BB115F616795E1CB7E7B2B6822D6B00567` |
| `runtime/service.py` | `1FBF2D7C6731F46A4104F0C55C1EC1CB89F3C961482E55D9D87FB7C83FAB84C5` |
| `runtime/scheduler.py` | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| `runtime/request_control.py` | `11AC5CBEDEB85BD651A1D28C0CA84F305EB815415D3FC950A2E9657A5A11B640` |
| `state/runtime_recovery.py` | `F4F762197F9A7FEAFB6BED6D5BCE911CE6DF3A0092B7911A5A4D8E6BE5F55AF3` |
| `test_unified_permission_running.py` | `8DEB7456B0FC71A8B2C4B8871246EC6A1EC00C6E6F8F3B407234558F3E50E173` |
| `test_s3_scheduled_permission_shutdown.py` | `77985619DB2B059145A6F44EBE0645C2D85586176364524625E3B3B302BFFFDD` |

Source paths are relative to `src/trade_plan_monitor/`; both test paths are under `tests/integration/`. This is coherent candidate evidence, not a clean-HEAD run or full S4 approval. Further source/helper changes require a fresh coherent final window.

### Independent verification

The independent reviewer read the complete test and reran the same target command above: **1 passed, 1 warning in 6.53s**, with the same Starlette `httpx` deprecation warning. No P1/P2 finding was identified in the actual scheduler/owned-task, admission-before-cancel, five-second grace, late-proof rejection or drain-before-disposal boundaries. Target/shared-helper Ruff and diff checks passed.

Complete before/after JSON hashes matched for the independent eight-path sample: `runtime/production.py`, `runtime/scheduler.py`, `runtime/service.py`, `runtime/recovery.py`, `runtime/recovery_targets.py`, `web/monitor_composition.py`, the shared S4 test and the shutdown test. Production, scheduler, service, composition and shutdown-test hashes match the author table. The independent source sample includes the following two files instead of the author's `runtime/request_control.py` and `state/runtime_recovery.py`; those author-only files are not relabeled as independently sampled:

| File | SHA-256 |
|---|---|
| `runtime/recovery.py` | `E9F6D412042A4CB6A8A65ED8ED3E9FC4A9D1C9971186F8646AAD5581A2B9C051` |
| `runtime/recovery_targets.py` | `C19139108C4C7B2192AF10B7391F0A4899E821685B40705FE0A6FBB9A32618BD` |

The shared S4 test file had changed between runs, but was stable throughout this independent window at `BA2C4F2FFA815869D480C9E2BF9A1FEF5EBC878EE45D13FBA5A1F4ACB08372E7`. This is a separate candidate window, not a replacement of the author's recorded helper hash, and the overlapping one-case counts are not added. S4 source/helper landing dependencies and the RUNNING-only limitation remain unchanged.

## Limits

One RUNNING historical-index permission representative only. This closes neither DEGRADED stop integration, all eight scope combinations, UPD-S4/S5, C1 nor the overall S3 gate. Existing component cancellation and stock-recovery stop tests remain separate evidence; their counts are not added here. Only temporary SQLite and local fake SDK data are used. No source/old-test edits, new stop policy, forced SDK termination, hot reload, real service, real user database, notification, deployment or commit is part of this change.
