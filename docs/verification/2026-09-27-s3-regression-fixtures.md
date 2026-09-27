# S3 regression fixture alignment — five-file slice

## Scope and status

Base: `53b731271b4b3a10a8558da993ecd000f03c1d58`. Tests only; production code, shared `ControlledClock`, controller policy, dependencies, and business contracts are unchanged. Independent source/test review and final report parity passed with no P1/P2. No deployment, real SDK, or user database is part of this slice; the coordinator owns local commits.

Owned test files under `tests/integration/`:

- `test_certified_production_runtime.py`
- `test_explicit_runtime_production.py`
- `test_index_permission_process_restart.py`
- `test_production_a06_matrix.py`
- `test_production_a06_process_scheduler.py`

Together with this English report and its `.zh-CN.md` counterpart, these are the seven owned paths. The other regression slice owns `test_live_pipeline_acceptance.py`, `test_runtime_crossed_market_deadline.py`, and `test_s3_index_retry_process.py`; its evidence is not claimed here.

## Baseline and failure mapping

Root's frozen full-suite run at the base commit reported **16 failed, 5695 passed, 1 skipped, 4 deselected, 1 warning in 1087.48s**. This slice addresses nine of those failures and retains the two relevant passing parameter controls:

| Test family | Original failing cases | Cause of obsolete fixture |
| --- | --- | --- |
| Certified gap budget | `[15-True]` (retain `[59-False]`) | Market-tail inline repair was intentionally replaced by bounded stock maintenance; partial startup establishes a completion +30s floor. |
| Explicit scheduled BUY | One | The first sleep is now a legitimate maintenance wake, not necessarily the original market wake. |
| Index permission process restart | `[rt_idx_min_daily]` (retain historical parameter) | A named realtime loser cannot bypass the common historical-first equal-due selection. |
| A06 mixed-family matrix | Two malformed-family and two required-index cases | Startup fetches at most one symbol; the healthy explicit family still needs its legal pending prefix before the original market evaluation. |
| A06 process scheduler | Two symbols | A fixed first-sleep oracle parked before the original market target after maintenance was added. |

Read-only RED reproductions before edits:

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_certified_production_runtime.py::test_production_deadline_repairs_only_detected_gaps_with_realtime_budget -q --tb=short
1 failed, 1 passed in 14.13s

.venv/Scripts/python.exe -m pytest tests/integration/test_explicit_runtime_production.py::test_real_monitor_composition_scheduler_dispatches_explicit_buy tests/integration/test_index_permission_process_restart.py::test_migrated_index_permissions_recheck_independently_across_processes[rt_idx_min_daily] -q --tb=short
2 failed, 1 warning in 11.98s

.venv/Scripts/python.exe -m pytest tests/integration/test_production_a06_matrix.py -q --tb=short -k 'malformed_stock_row or required_index_failure' tests/integration/test_production_a06_process_scheduler.py -k 'malformed_stock_row or required_index_failure or malformed_family_row_recovers'
6 failed, 1 warning in 11.80s
```

The last command contains two `-k` arguments; the latter was effective and selected all six intended cases. Additional failure-local diagnostics were not separate product regressions.

## Approved alignment and preserved oracles

1. **Gap budget:** keep original startup/market 10:00:15 and 10:00:59, assert zero inline current-day fetches and retain the original +30s floors (10:00:45 / 10:01:29). A real `MarketSessionScheduler` selects maintenance at 10:01:15 / 10:01:59 using its actual market window. The next market is 10:02:12: 57s admits exactly one symbol request; 13s rejects every SDK call and leaves the gap/head absent, task set unchanged, no future minutes, and exact next wake 10:02:12 +1µs. This is component evidence, not an autonomous composition claim.
2. **BUY:** locally release actual scheduled deadlines up to original 10:05:12, bounded by eight wakes. Await the original market handler's return before checking completion, unique BUY, exact target 10:05/evaluated_at 10:05:12, activation revision, runtime/runner/generation, and allowed SDK endpoints.
3. **Index processes:** preserve both successful-scope parameters and configure the other endpoint to fail before either common call. A named realtime loser has zero SDK/raw/block/rotation changes. Common order is historical then realtime, with exactly one physical call per unit, only its own latch changed, sibling raw/block unchanged, and the failed scope's 300s floor. The second clean process retains the original +100s zero-call and +600s one-call checks, schema 23, durable checkpoint, zero business writes, and clean exits. This older +600s scenario is not R17's exact-equality evidence.
4. **A06 matrix:** after the one legacy startup fetch, run at most one real `STOCK_RECOVERY` component unit for the pending explicit symbol; assert exact single SDK delta and unchanged non-minute/non-quote business rows. Keep the required-index replacement at 10:04:15 and its complete index-only retry phase; only at original 10:05:15, before market, prepare the pending explicit prefix. Do not loop to fill all requirements. Original malformed isolation, healthy-family progress, delivery, identity, exact target, and persisted index floor checks remain.
5. **A06 processes:** a child-local clock releases actual deadlines through original 10:00:12 / 10:05:12 with an eight-wake bound, then parks. Completion requires the original market handler to finish and the next future park. Startup has one legacy fetch; each maintenance unit has at most one current-day request. Preserve the two real spawned processes and all original failed/healthy family, identity, target, result, alert, and restart assertions.

Two development observation errors were corrected with explicit reviewer/root approval, not production fixes: the gap veto returns `None` because admission is rejected before a recovery result exists (initial added assertion failed: 1 failed, 1 passed in 18.72s); the BUY alert can commit before its handler returns (initial completion observation failed: 1 failed, 1 warning in 6.71s). The final tests retain the hard side-effect oracles instead of assuming the wrong return/completion point.

## Author verification

Development slices: gap **2 passed in 15.22s**; BUY **1 passed, 1 warning in 6.51s**; index process **2 passed in 8.01s** before the final sibling-state assertion; matrix **4 passed, 1 warning in 8.80s**; A06 process **2 passed, 1 warning in 12.05s**. These overlapping windows are not added together.

Final five-file command: **41 passed, 1 warning in 95.00s**.

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_certified_production_runtime.py tests/integration/test_explicit_runtime_production.py tests/integration/test_index_permission_process_restart.py tests/integration/test_production_a06_matrix.py tests/integration/test_production_a06_process_scheduler.py -q --tb=short
```

Scoped lint and whitespace checks passed:

```text
.venv/Scripts/python.exe -m ruff check tests/integration/test_certified_production_runtime.py tests/integration/test_explicit_runtime_production.py tests/integration/test_index_permission_process_restart.py tests/integration/test_production_a06_matrix.py tests/integration/test_production_a06_process_scheduler.py
git diff --check
git diff --name-only -- src
```

The last command returned no paths. All test databases and SDKs are temporary/offline. The warning is the existing Starlette/httpx deprecation warning.

## Independent verification

Astra independently ran the exact five-file pytest command above: **41 passed, 1 warning in 94.92s**. The scoped five-file Ruff command and `git diff --check` passed. Full static review found no P1/P2. The independent window sampled six source files (production/service/scheduler/composition/recovery/recovery_targets) and the five owned tests: all eleven complete SHA256 values matched before and after. This is a scoped sample, not a claim that every source file was hashed. Author and independent counts cover the same cases and are not added together.

## Frozen hashes and remaining gates

All nine SHA256 values below matched before and after the final author window:

| Path | SHA256 |
| --- | --- |
| `src/trade_plan_monitor/runtime/production.py` | `F1083412137BDD38EDC6EF2B03F9C85797C6CCEDC6A5F7030D80E1B9211DC9BC` |
| `src/trade_plan_monitor/runtime/service.py` | `FF6D119BE17A0C4C7452CC468D549F8F9E68BC3469FDF0C2B830AD760E956AC1` |
| `src/trade_plan_monitor/runtime/scheduler.py` | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| `src/trade_plan_monitor/web/monitor_composition.py` | `10BB57BC792645115AE045342E796D90FEF99F9E1ADDF6F0296B0B86E2CE6FD2` |
| `tests/integration/test_certified_production_runtime.py` | `A20F6CC67FE9545C190AF063CC467D36B0CD5F92F0EB91B64CD13D4A981945C5` |
| `tests/integration/test_explicit_runtime_production.py` | `C42DD37428A775759CFDD18BEA67A5A3DFC8922D215ADFD8F95E11198E97C278` |
| `tests/integration/test_index_permission_process_restart.py` | `750CDBCD43079FE3DEFFF2B662ED8B8C6145B28FD3605C59E66F6608A00261B3` |
| `tests/integration/test_production_a06_matrix.py` | `DF977CE2171CDEB83E6D7DC32A55C19869BAD60BF572FEE0FD99CFA42AAC5F52` |
| `tests/integration/test_production_a06_process_scheduler.py` | `DFFBA4A9A3FC245DCFE1A632761A3418B66551EBDE14AFA8206D63906BF8D887` |

Independent five-file source/test review and report parity passed. The final committed full-suite gate remains OPEN. Targeted success is not a claim that the original 16-failure full-suite gate is closed.
