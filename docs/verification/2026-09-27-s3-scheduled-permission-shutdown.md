# S3 scheduled permission maintenance shutdown

## Status and dependency

The test covers one real `INDEX_HISTORICAL_MINUTES` stop representative in each of RUNNING and DEGRADED. The extension has an independent **limited pass**, with no P1/P2 findings and both modes included in the final fixed-source combined run: **82 passed, 1 warning in 16.52s**. This is not a standalone two-case timing. The earlier author **2 passed, 1 warning in 12.09s** remains an **intermediate UPD-S5 candidate** observation. Fixed-commit full regression and final integration review are still pending; C1/C3 remain OPEN. This is connected UPD-R16 acceptance, not a manufactured baseline RED or production fix; only the shutdown test and these paired reports are changed.

The extension was tested at HEAD `7abed318a3239ca529e699618a946018810c5009` plus UPD-S5 candidate source and the **uncommitted** `tests/integration/test_unified_permission_degraded.py::_degraded_composition` helper. It retains the committed S4 `_composition(..., stock=False)` helper and R17 business/checkpoint snapshot helpers. The extension must land with accepted S5 source/helper or immediately after them; it cannot land independently on that HEAD. Related-controller-floor/revoked-wait work was incomplete in the earlier author window, but is included in the final independent source window below; it is no longer a missing implementation at that checkpoint.

### Historical RUNNING-only window

Author result: **1 passed, 1 warning in 6.68s**. Independent static review and rerun: **limited pass**, **1 passed, 1 warning in 6.53s**, no P1/P2 findings for that case. The tested checkout was HEAD `54b70f6aad10770346697637386de8a22d136633` plus the UPD-S4 candidate changes in `runtime/production.py` and `web/monitor_composition.py`. The S4 shared helper was then uncommitted and used committed composition, A07 clock and proof-frame fixtures. That RUNNING test/report set subsequently landed with S4; the historical evidence below is retained, not relabeled as the new two-mode run.

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

## R16-P02 — Actual DEGRADED owner and unchanged startup deadline

1. Reuse the S5 composition fixture with only `TRADING_CALENDAR` and `INDEX_HISTORICAL_MINUTES` latches due at `2026-09-08 10:00:16+08:00`. It supplies a complete committed stock-minute prefix, legal semantics/certification and real liveness. The actual startup calendar reference is permission-blocked: startup returns DEGRADED with `REFERENCE_REFRESH_FAILED` / `REFERENCE_BLOCKED_PERMISSION`, `_accepting_work` false, zero SDK calls and unchanged seed checkpoints. The pipeline exists and the original startup retry remains `NOW + 30 seconds` (`10:00:45`).
2. Park and release only the genuine lifecycle retry wait at `10:00:16`; its fixture advances the clock and invokes real `state.heartbeat()`. The production loop first repairs calendar, then enters the historical-index proof in a real `INDEX_PERMISSION` owned task at the same clock time. Exactly `trade_cal`, then `idx_mins`, are observed in two actual maintenance duties. The test does not call a unit/deadline directly, change runtime status, enable ordinary work or register an owned task.
3. At the held historical SDK boundary, status is still DEGRADED, `_accepting_work` remains false, the installed pipeline and runtime generation are unchanged, the original startup retry is still `10:00:45`, and the normal market clock has no waits. Existing stop/generation admission is legitimately open for permission work; no new admission capability is fabricated. Calendar is now unblocked, but historical permission remains blocked with its real durable `10:05:16` reservation. Full business rows, including the already committed minute prefix, are unchanged.
4. Apply exactly the real stop, five-second grace, cancellation, late valid-proof rejection, reservation retention, physical-slot drain and engine-disposal assertions in R16-P01. No further SDK or business write occurs. Final state is STOPPED with no runner failure, runtime replacement or generation change.

This case deliberately stops before the original startup retry. It proves the DEGRADED permission-stop connection, not a subsequent DEGRADED-to-RUNNING startup recovery. The shared stop oracle is parameterized without weakening the RUNNING branch.

## Historical commands and frozen RUNNING candidate evidence

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

The shared S4 test file had changed between runs, but was stable throughout this independent window at `BA2C4F2FFA815869D480C9E2BF9A1FEF5EBC878EE45D13FBA5A1F4ACB08372E7`. This is a separate candidate window, not a replacement of the author's recorded helper hash, and the overlapping one-case counts are not added. This historical independent result covers RUNNING only and had the S4 source/helper landing dependency stated above.

## Two-mode intermediate S5 candidate evidence

From the repository directory:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_scheduled_permission_shutdown.py -q --tb=short
.venv/Scripts/ruff.exe check tests/integration/test_s3_scheduled_permission_shutdown.py
git diff --check -- tests/integration/test_s3_scheduled_permission_shutdown.py docs/verification/2026-09-27-s3-scheduled-permission-shutdown.md docs/verification/2026-09-27-s3-scheduled-permission-shutdown.zh-CN.md
```

Author target: **2 passed, 1 warning in 12.09s**. The warning is the same imported Starlette `httpx` deprecation notice. Target Ruff and scoped diff checks passed. No live request was made. Counts overlap the historical RUNNING evidence and are not added to it.

The writer coordinated a short source/helper freeze. Full before/after JSON hashes matched for all nine paths below; `Compare-Object -Property Path,Hash` returned no differences after pytest completed. Source paths are relative to `src/trade_plan_monitor/`; test paths are under `tests/integration/`.

| File | SHA-256 |
|---|---|
| `runtime/production.py` | `F1083412137BDD38EDC6EF2B03F9C85797C6CCEDC6A5F7030D80E1B9211DC9BC` |
| `web/monitor_composition.py` | `10BB57BC792645115AE045342E796D90FEF99F9E1ADDF6F0296B0B86E2CE6FD2` |
| `runtime/service.py` | `EB6EFACDE9821E7AD0D739DBB1B6FA532D744A1740C0D767C6C0F0784F796106` |
| `runtime/scheduler.py` | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| `runtime/request_control.py` | `11AC5CBEDEB85BD651A1D28C0CA84F305EB815415D3FC950A2E9657A5A11B640` |
| `state/runtime_recovery.py` | `F4F762197F9A7FEAFB6BED6D5BCE911CE6DF3A0092B7911A5A4D8E6BE5F55AF3` |
| `test_unified_permission_running.py` | `BA2C4F2FFA815869D480C9E2BF9A1FEF5EBC878EE45D13FBA5A1F4ACB08372E7` |
| `test_unified_permission_degraded.py` | `6F4F3685AD0DDC2047F19ECE9204725C83C2A08EF680842F68FC66E755609A80` |
| `test_s3_scheduled_permission_shutdown.py` | `D184921AFF0363C11120DAFEC70B7154F98ADEE568758DDD57D9C23214A0B561` |

This was not a clean-HEAD or final S5 run. The final independent section below records the required two-mode rerun after subsequent source/helper changes; the historical RUNNING-only independent review is not relabeled as approval of the DEGRADED extension.

## Final independent fixed-source verification

The independent reviewer statically reviewed both stop modes with no P1/P2 findings and ran this exact combined command:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_degraded.py tests/integration/test_runtime_lifecycle.py tests/integration/test_s3_scheduled_permission_shutdown.py -q --tb=short
```

Result: **82 passed, 1 warning in 16.52s**: 29 DEGRADED cases, 51 lifecycle cases and these 2 stop modes. The warning is the existing Starlette `httpx` deprecation notice. This is the combined duration, not a separately timed two-case stop run. Ruff and scoped diff checks passed. These overlapping observations are not added to earlier counts.

The reviewer confirmed complete before/after JSON hashes were identical for exactly these ten paths. This independent sample contains `runtime/recovery.py` and `runtime/recovery_targets.py`, not the author-only `runtime/request_control.py` / `state/runtime_recovery.py` sample. Source paths are relative to `src/trade_plan_monitor/`; test paths are under `tests/integration/`.

| File | SHA-256 |
|---|---|
| `runtime/production.py` | `F1083412137BDD38EDC6EF2B03F9C85797C6CCEDC6A5F7030D80E1B9211DC9BC` |
| `runtime/service.py` | `FF6D119BE17A0C4C7452CC468D549F8F9E68BC3469FDF0C2B830AD760E956AC1` |
| `runtime/scheduler.py` | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| `web/monitor_composition.py` | `10BB57BC792645115AE045342E796D90FEF99F9E1ADDF6F0296B0B86E2CE6FD2` |
| `runtime/recovery.py` | `E9F6D412042A4CB6A8A65ED8ED3E9FC4A9D1C9971186F8646AAD5581A2B9C051` |
| `runtime/recovery_targets.py` | `C19139108C4C7B2192AF10B7391F0A4899E821685B40705FE0A6FBB9A32618BD` |
| `test_unified_permission_degraded.py` | `DBF72BC1BA54121CC522DB37243588DE2FBFDA04F5CE908295BE30AE7743C125` |
| `test_runtime_lifecycle.py` | `6095D74B06D6718DAA26D100AD332F2175222319F9B07277F5E545E2C608D159` |
| `test_s3_scheduled_permission_shutdown.py` | `D184921AFF0363C11120DAFEC70B7154F98ADEE568758DDD57D9C23214A0B561` |
| `test_unified_permission_running.py` | `BA2C4F2FFA815869D480C9E2BF9A1FEF5EBC878EE45D13FBA5A1F4ACB08372E7` |

The final window includes the related-floor/revoked-wait corrections and the final DEGRADED tests, while the stop test is unchanged from the author's two-mode hash. It verifies both stop representatives against that accepted S5 candidate; it is not fixed-commit aggregate acceptance and does not close C1/C3. Source/helper landing, fixed-HEAD full regression and final independent integration approval remain separate gates.

## Limits

One independently reviewed historical-index permission stop representative in each of RUNNING and DEGRADED. This report does not by itself close all eight scope combinations, UPD-S5, C1/C3 or the overall S3 gate. Existing component cancellation, stock-recovery stop and broader S4/S5 tests retain their own acceptance scope, even when included in one command; their counts are not added here. Only temporary SQLite and local fake SDK data are used. No source/unrelated-test edits, new stop policy, forced SDK termination, hot reload, real service, real user database, notification, deployment or commit is part of this extension.
