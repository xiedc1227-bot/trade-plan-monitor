# C1 UPD-S4 — RUNNING permission scheduling

## Status and scope

The paired unified-permission contract is approved. This slice starts from S3/R17 `f4be66ed0a9c7c7815106a0e9de1892e10e5f4a5`; current base `54b70f6` adds only progress documentation. Independent implementation review and final report parity passed with no remaining P1/P2. S5/DEGRADED, complete R18, C1/C3 and the final full-suite gate remain open.

Only two production seams change: `src/trade_plan_monitor/web/monitor_composition.py` adapts `next_index_permission_at()` directly to the eight-scope pure cached getter (absent pipeline returns `None`); `src/trade_plan_monitor/runtime/production.py` sends `INDEX_PERMISSION` to the common unit, preserving authorized stock-recovery synchronization and the early return. No scheduler/service/provider/controller/startup changes, new loop, or policy relaxation. F3's existing two-cursor maintenance handling and delivery exclusion are retained.

New coverage is `tests/integration/test_unified_permission_running.py`. The separately authored scheduled permission shutdown test/report pair belongs to its own evidence record. Everything uses offline SDK boundaries and temporary SQLite; no live service, user database, deployment, push or dependency upgrade. Root retains commit authority.

Exact seven owned paths (the separate shutdown slice owns three additional paths):

- `src/trade_plan_monitor/runtime/production.py`
- `src/trade_plan_monitor/web/monitor_composition.py`
- `tests/integration/test_unified_permission_running.py`
- `tests/integration/test_production_index_historical_permission_probe.py`
- `tests/integration/test_production_index_realtime_permission_probe.py`
- `docs/verification/2026-09-27-c1-permission-running.md`
- `docs/verification/2026-09-27-c1-permission-running.zh-CN.md`

## Connected evidence

- Actual RUNNING composition/scheduler executes all eight scopes in round-robin order; the index-only control executes its three index scopes without stock authority or stock SDK calls. Every permission duty is an actual `INDEX_PERMISSION` owned task, with exactly one SDK call and durable acknowledgement, only its own permission cleared, unchanged runtime/runner/generation, and no runner fault at every released wake.
- Each permission branch compares complete rows of every application table except migration metadata, runtime liveness and provider checkpoints. Business coordinator execution and `dispatch_pending` are forbidden inside that branch. Legitimate market work is observed separately, not mislabeled as permission side effects.
- The pipeline/composition timing getters remain pure before and after due time; clock, authority, session, old index getter and B1 access are forbidden. Absent pipeline never bootstraps.
- A real equal-time market deadline executes first; permission follows at `+1us`, retaining the market cursor and original bar target. A real controller queue holds the permission request for 8 seconds: capture age remains within 15 seconds, but time to the actual market deadline is below 31.25 seconds. The SDK is not entered; the durable 300-second reservation and exactly one acknowledgement remain, and the original market target subsequently runs.
- Actual SDK entry starts more than 31.25 seconds before the next real market deadline. Held SDK release then crosses one fresh deadline (one original target, age 13 seconds), multiple deadlines (no replay), or the final morning target past 90 seconds (no stale replay). Both the progress cursor and elapsed-review lower bound retain their original values through maintenance. The real same-owner heartbeat is published before bounded virtual wakes/held-response release; no health, admission, generation or scheduler-window result is fabricated.

## RED history and fixture distinctions

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_running.py -q --tb=short
```

The first scaffold had two observation mistakes: the runner belongs to composition, and `_running_deadline` is boolean `False`, not `None`. These are fixture corrections, not product fixes. With the corrected test, temporarily restoring only the two original source seams produced **3 failed, 1 passed, 1 warning in 4.15s**: the actual permission duty returned `SKIPPED` instead of probing, and two pure-adapter checks reached the old authority getters. Restoring the minimal implementation produced **4 passed, 1 warning in 4.43s**. The expanded core passed **10 tests, 1 warning in 6.72s**; Ruff passed. Existing Starlette `httpx` deprecation accounts for the warning.

The first direct-adjacent run produced **4 failed, 245 passed, 1 warning in 36.44s**. Three historical direct-owner fixtures did not expect S3's approved typed authority-revocation error; their `stopping` parameter actually sets `admission_revoked=True`, not merely an obsolete generation. One realtime fixture expected `SKIPPED` instead of S3's `DEFERRED` at 09:35 while the known opening deadline is 09:35:12. Sol/root approved only narrow test alignment: three typed expectations and one DEFERRED expectation, retaining raw/block/cursor/SDK-zero/business controls, and asserting the exact 09:35:12 local map and adapter deadline rather than generic +30 seconds. Ordinary generation retirement remains unchanged. No source change was needed. These are S3 direct-entry policy-alignment omissions, not S4 product RED.

The focused command passed **8 tests, 63 deselected in 3.01s**, without warnings:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_index_realtime_permission_probe.py -k 'stale_authority_or_cooldown or first_current_day_five' -q --tb=short
```

## Verification commands and frozen source

Direct adjacent command:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_runtime_lifecycle.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/unit/test_monitor_runtime.py -q --tb=short
```

Final author adjacent result: **249 passed, 1 warning in 36.92s**. Scoped Ruff and `git diff --check` passed; the two source files and new test retained their hashes throughout. Counts from overlapping windows are not added.

Current frozen SHA256:

| File | SHA256 |
| --- | --- |
| `src/trade_plan_monitor/runtime/production.py` | `F1083412137BDD38EDC6EF2B03F9C85797C6CCEDC6A5F7030D80E1B9211DC9BC` |
| `src/trade_plan_monitor/web/monitor_composition.py` | `A716E8B068919E5C2AD2D68F19CA65BB115F616795E1CB7E7B2B6822D6B00567` |
| `tests/integration/test_unified_permission_running.py` | `BA2C4F2FFA815869D480C9E2BF9A1FEF5EBC878EE45D13FBA5A1F4ACB08372E7` |
| `tests/integration/test_production_index_historical_permission_probe.py` | `CC343D8880097AB98400E9630FCCBABBBD446C48A51A9340E502A9F64B03648B` |
| `tests/integration/test_production_index_realtime_permission_probe.py` | `91AD3514D5B3CFD3E7EE125E159EA24280EFC3A543499E49505D2CAB9521285E` |

## Independent verification

Sol independently ran the exact single-file target command above: **10 passed, 1 warning in 6.72s**. That window retained all eight observed hashes (six runtime/composition sources, the RUNNING test and the separately authored shutdown test). The shutdown case was run separately and is recorded in its own paired report, not combined into an invented 11-case run.

Sol then ran the exact six-file adjacent command above after the approved fixture migrations: **249 passed, 1 warning in 36.05s**. Complete pre/post JSON hashes matched for all ten observed paths (the same eight plus the historical/realtime fixtures). Scoped Ruff covered the two changed sources and RUNNING/historical/realtime/shutdown tests; `git diff --check` passed. Static review confirmed both source seams and the narrow fixture changes with no remaining P1/P2. Final report parity passed.

Historical S3/R17 results are not presented as S4 automatic scheduling acceptance, and these RUNNING results do not establish S5/DEGRADED behavior.
