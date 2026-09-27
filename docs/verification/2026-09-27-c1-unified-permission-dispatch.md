# C1 UPD-S3 — Unified permission dispatch

## Status and scope

The paired `2026-09-27-c1-unified-permission-dispatch-contract` is approved. This implementation starts from UPD-S2 `9796b15469b8e3bc9aa12a3425aae053e56bebfc`. Final author and independent source/test verification and bilingual report parity passed with no remaining P1/P2. This is not C1 completion or automatic RUNNING/DEGRADED eight-scope recovery acceptance.

The slice changes only `src/trade_plan_monitor/runtime/production.py`, adds `tests/integration/test_unified_permission_dispatch.py`, narrowly migrates existing stock-minute/daily-limits/index-daily permission tests, and adds this report pair. Provider, controller, scheduler, service, composition, startup and proof parsers are unchanged. R17 clean-process tests/reports have a separate author and review record; they require this common entry point and are not an independent clean-HEAD implementation.

Exact owned paths:

- `src/trade_plan_monitor/runtime/production.py`
- `tests/integration/test_unified_permission_dispatch.py`
- `tests/integration/test_production_stock_minute_permission_execution.py`
- `tests/integration/test_production_daily_limits_permission_maintenance.py`
- `tests/integration/test_production_index_daily_permission_maintenance.py`
- `docs/verification/2026-09-27-c1-unified-permission-dispatch.md`
- `docs/verification/2026-09-27-c1-unified-permission-dispatch.zh-CN.md`

Tests use offline SDK responses, actual certified wrappers/controllers and temporary SQLite. No live services, user database, dependency upgrade, deployment or push. Root retains commit authority.

## Implementation boundary

`run_permission_maintenance_unit()` and all eight named compatibility entry points share one invocation-local original Task/Event and `_permission_maintenance_lock`. The common selector chooses one global raw-due/RR winner; a named loser cannot run that winner or prepare another scope. Private held bodies do not reacquire the lock. Durable `on_reserved` remains the only acknowledgement; one unit has at most one reservation/SDK call. Existing O/F and independent stock-symbol cursor rules remain intact.

Unavailable due scopes receive fixed local checks, while ready unselected siblings remain due. A shared pure-memory effective-floor helper includes both old index fields, the local map, raw permission floor and shared cooldown. The cheap getter performs no clock, file or SQL I/O. Slow unavailable checks use a fresh completion observation for a future 30-second local wake; repeated not-due calls do not slide it. This does not recapture or extend the frozen 15-second start window or shorten an established concrete retry floor.

DAILY_BARS participates with a synthetic scope rank, then performs exactly one fresh preparation (one historical page and at most ten receipt checks). The same immutable preparation is passed to its held body. Tests prove broad symbol A with no demand can produce actual symbol B's legitimate receipt; absence of a broad anchor still reaches one preparation. Global authority revocation raises `RecoveryAdmissionChangedError` before ordinary generation retirement; a still-authorized obsolete generation skips without reservation. Retirement during selected preparation unwinds only its own newly written timing value, not earlier valid checks of other scopes. Held-body candidate/authority/anchor reads also check that same ordered admission gate before interpreting unavailable evidence. SQL exceptions still propagate; post-request DEFERRED/FAILED outcomes are not converted into normal retirement.

The remaining five owners now recheck original owner cancellation after final authority I/O, and daily-limits/index-daily also guard after response SQL. Worker cancellation checks use the invocation Event, never Task inspection; existing authority I/O and scope-specific physical-start fences remain, with no worker SQL. Cancellation releases the maintenance lock but not a still-running physical slot; late success cannot clear permission. Only `BLOCKED_PERMISSION`, `RATE_LIMITED`, `TRANSIENT`, `TIMEOUT`, `INVALID_RESPONSE` become `FAILED`, preserving a concrete `next_retry_at`. `ERROR`, `CLOSED`, `QUEUE_FULL`, storage/callback/program failures propagate. The ordinary `_request(TRADING_CALENDAR)` inline recheck is removed; it cannot reserve or probe permission.

## RED history and fixture distinctions

Target command throughout:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_dispatch.py -q --tb=short
```

- Initial four cases: **4 failed, 1 warning, 2.98s** (missing common API and ordinary calendar inline probe), then **4 passed, 1 warning, 3.07s**.
- Final-authority cancellation, fatal propagation and global admission controls failed before their implementation. An intermediate expanded run mixed product failures with invalid index-daily response/argument fixtures and missing required exception `attempts`; those fixture failures are not product fixes. The isolated concrete-floor command with `-k concrete_error_retry_floor` gave **5 failed, 29 deselected, 1 warning, 5.18s**. The corrected 34-case checkpoint passed **34 tests, 1 warning, 24.83s**.
- Selected preparation retirement: `-k selected_preparation_retires`, **4 failed, 34 deselected, 1 warning, 4.38s**, then **4 passed, 34 deselected, 1 warning, 4.30s** after the approved immutable transfer/post-preparation gate.
- Old index fields omitted by the common fast-path produced two formal `legacy_index_floor` failures. Slow B1 and UNKNOWN preparation produced two formal `slow_unavailable` failures: **2 failed, 2 passed, 41 deselected, 1 warning, 2.53s** in the combined synthetic-rank window. A DAILY_BARS harness initially lacked its durable repository; binding the real temporary repository was fixture setup, not a production change. The resulting full checkpoint passed **45 tests, 1 warning, 30.61s**.
- Actual resolver/SDK-held cancellation, real provider classifications and common/named acknowledgement: **36 passed, 45 deselected, 1 warning, 30.39s**. The next full checkpoint was **87 passed, 1 warning, 66.30s**; this predates the later held-preparation authority controls and is not final acceptance.
- A further self-review found authority loss inside held-body preparation. Corrected formal `-k held_preparation_authority --tb=line`: **10 failed, 87 deselected, 1 warning, 9.36s**, then **10 passed, 87 deselected, 1 warning, 9.83s** (`--tb=short`). The preceding run accidentally included DAILY_BARS instead of INDEX_DAILY in two parameters; it is not the clean ten-case RED window. Six actual selected-anchor SQL controls and one simultaneous SQL-error/retirement control passed **7 tests, 97 deselected, 1 warning, 6.30s** (`-k 'selected_real_anchor or preparation_sql_failure'`).
- Independent review confirmed the same remaining P2 in both stock-minute held pre-controller checks and both DAILY_BARS held certification checks. Formal `-k prepared_owner_certification_io --tb=line`: **8 failed, 104 deselected, 1 warning, 7.88s**, then **8 passed, 104 deselected, 1 warning, 8.21s** (`--tb=short`). Each invokes the real authority validator, prepares once, retains raw floor/SDK-zero/ack-zero and adds no defer for ordinary retirement. Three owner-thread boolean checks now run the ordered global gate before interpreting local false; controller admission, worker, response and already-reserved outcomes are unchanged. The reviewer's separate stdin diagnostic is not counted as pytest RED.

The original five-file adjacent run had **3 failed, 320 passed, 1 warning, 94.91s**. Sol/root approved two narrow migrations: the sparse stock-minute test now distinguishes one common-selection transaction from the original two execution transactions, retaining exact 1001 dates/five chunks/one response snapshot/no `_work`; the unavailable named DAILY_LIMITS loser expects SKIPPED while retaining fixed local timing, unchanged raw floor/cursor, SDK zero and its eligible index sibling. These two controls passed **2 tests, 1 warning, 2.29s**. The generation-false index-daily assertion stayed SKIPPED and was fixed by source admission logic.

The subsequent adjacent window had **4 failed, 319 passed, 1 warning, 96.24s**: old DAILY_LIMITS revocation/generation expectations and two queued CLOSED expectations conflicted with the approved typed-revocation/normal-retirement/fatal-propagation boundary. Sol/root approved only these expectation migrations: repeated restored-file revocation remains typed; obsolete generation adds no defer; queued stop propagates original CLOSED (operation and zero physical attempts checked). Queue-abort remains DEFERRED. Original raw/floor/block/cursor/SDK-zero controls remain. Focused two-file `-k 'restored_stock or no_authority or stop'`: **5 passed, 47 deselected, 1 warning, 4.05s**, including the unchanged index generation control. These are policy-alignment fixtures, not new production fixes.

## Final verification

Before the last P2 fix, source `89E6821719286359D33D3640E2D381FACBA9A80030770DC9B015D6AA3BC3E68D` passed **106 tests, 1 warning, 87.47s** (104 common controls plus 2 R17) and **323 adjacent tests, 1 warning, 98.65s**. Independent target verification on that same old window passed **106 tests, 1 warning, 86.75s**, with 11 hashes unchanged. These are explicitly pre-fix results, not final acceptance. Overlapping counts must not be added. The existing warning is Starlette's `httpx` deprecation.

Final author results on the frozen hashes below: **114 passed, 1 warning, 94.52s** (112 common controls plus 2 R17); **323 adjacent passed, 1 warning, 98.89s**. The source/test hashes remained unchanged during both runs.

Final target includes the separately authored R17 cases:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_dispatch.py tests/integration/test_s3_permission_reservation_process.py -q --tb=short
```

Frozen source/test SHA256:

| File | SHA256 |
|---|---|
| `production.py` | `E20702C1E50C07F8E5FA20E03F49AFB31FF721BA560169BC13DB11338E42A47E` |
| `test_unified_permission_dispatch.py` | `7738D92C7CCC26D1F59C94260430CD86E67A65F9B759C8BF06EED4CBBBC93584` |
| `test_production_stock_minute_permission_execution.py` | `3D6ECFFDD110B07EE0EA93F24AE583637D5612EBCA29549ACB216389EE7C1791` |
| `test_production_daily_limits_permission_maintenance.py` | `9C41C3B8C2B0DE75F92A1D5475B18F67830994846ACE5C24A8D4A92F10768D79` |
| `test_production_index_daily_permission_maintenance.py` | `8CC53070DE0C0CC120995C5EC07AD68438C6466729F94B2C0DF1C5DB4C63F1A3` |

Direct adjacent command:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_legacy_owners.py tests/integration/test_production_stock_minute_permission_execution.py tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_daily_limits_permission_maintenance.py tests/integration/test_production_index_daily_permission_maintenance.py -q --tb=short
```

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/production.py tests/integration/test_unified_permission_dispatch.py tests/integration/test_production_stock_minute_permission_execution.py tests/integration/test_production_daily_limits_permission_maintenance.py tests/integration/test_production_index_daily_permission_maintenance.py
git diff --check
```

Both checks passed. Source diff size is mainly removal of one lock indentation level from existing owner bodies; `git diff -w` isolates the logical changes. No parallel source writer changed this fixed author window.

## Independent review and remaining work

Sol independently ran the exact final two-file target command above: **114 passed, 1 warning, 95.33s**. The exact five-file adjacent command above independently passed **323 tests, 1 warning, 98.45s**. After both commands exited, all 11 complete source/test SHA256 values matched the pre-run JSON: the five owned values above, unchanged scheduler/service/recovery/recovery-targets/composition, and R17 test `C634BB3D21E01FCAE2E559FE42A6055C9D9DD9F431ABC5E4210289E256F18B4A`. Six-path scoped Ruff (production, dispatch, minute, limits, index-daily, R17) and `git diff --check` passed. The three pre-reservation gate locations are fixed, and independent source/test review found no remaining P1/P2. Bilingual report parity passed. The two independent counts are separate, not an added test total.

The prior S2 cancellation and calendar work-key P2 regressions are retained in the adjacent suite. R17's separate `2026-09-27-s3-permission-reservation-process` report owns its real sequential-process evidence: its original independent 2-case window used source `1AD6922F...`, not the final source above. The final 114-case window includes those two cases; it does not relabel the old independent result. Private component tests do not substitute for R18 automatic recovery.

S4/S5 still own scheduler/composition/common getter wiring, the `INDEX_PERMISSION` dispatch branch, actual RUNNING/DEGRADED eight-scope wakeups, lifecycle/restart/no-busy-loop acceptance and complete UPD-R01..18 closure. No new loop or default automatic common invocation is introduced here.

Implementation uses the approved contract and installed code. Python documents [asyncio lock ownership](https://docs.python.org/3.14/library/asyncio-sync.html#lock) and [Task cancellation counts](https://docs.python.org/3.14/library/asyncio-task.html#asyncio.Task.cancelling); cancellation inspection remains on the owner loop. Existing provider proof semantics and physical-start windows are not generalized across operations.
