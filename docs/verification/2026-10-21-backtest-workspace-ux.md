# Backtest workspace verification — 2026-10-21

## BW-V01. Delivered scope

Contract: [SPEC-backtest-workspace-ux](../specifications/backtesting/SPEC-backtest-workspace-ux.md). Tasks: [backtest-workspace-ux](../../tasks/backtest-workspace-ux.md). Baseline: `2be0a8b`. Existing proposal documents and creation/cause-review behavior were preserved.

P0 and existing-interface P1 cover compact run discovery, collapsed date filters, clear conditions, visited previous/first/next pages, return-row focus, a truthful verified-data catalog, accepted-task browsing, confirmed advanced service stop, compact audit evidence, effective-version selection, equity layer/range controls, exact-value disclosure and supported result actions. Known task/data failures have readable explanations with raw evidence retained. No API/schema/migration was added. Global inventory/audit-date filtering, chart-to-fill linkage and P2 remain deferred.

## BW-V02. Automated evidence

- Frontend: final pre-commit `npm run test -- --run --maxWorkers=4` passed 82 files / 1,201 tests in 20.57 seconds. Worker count bounds local CPU contention; no test threshold was reduced.
- `npm run type-check` and `npm run build` passed. The packaged local web distribution was rebuilt.
- Backend: `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_workspace_reads.py tests/integration/test_backtest_review.py tests/integration/test_monitor_loop_result_api.py tests/integration/test_backtest_retention.py -q --basetemp=.tmp/workspace-ux-green-20261021c` passed 42 tests in 412.47 seconds. The existing Starlette/httpx deprecation warning remains. Ruff passed on all changed Python files.
- Compatibility: `.venv/Scripts/python.exe -m pytest tests/unit/test_backtest_run_input.py tests/unit/test_monitor_loop_continuity_fixture.py -q` passed 33 tests, including run identity and frozen canonical fixture compatibility.
- The new backend regression failed before optimization and passed after it. A temporary inversion of the timeout-generation guard caused the new deadline test to fail; the original source was restored and the tests passed. This checks that the timeout assertion detects a real behavioral defect.
- `npm run test:e2e -- tests/e2e/backtest-workspace.spec.ts` passed all 7 Chrome journeys in 23.2 seconds in the final pre-commit rerun: 30-record run/data pagination; filter clear and return focus; empty catalog and accepted failed-task inspection; version selection and responsive layout; delayed reading; timeout/retry without submission; keyboard equity controls and exact table. Browser fixtures must explicitly declare equity availability; an initially unavailable fixture was corrected without relaxing production validation.
- Original upload/review/run/cause, extraction cancellation, automatic data preparation, four-plan continuity and plan-library journeys were checked using isolated fixture storage. Changed selectors follow the new stop confirmation and version buttons; domain assertions remain intact.
- All 9 distinct existing journeys passed across the full run and corrected targeted reruns: `npm run test:e2e -- tests/e2e/monitor-loop-backtest.spec.ts tests/e2e/plan-library-versions.spec.ts`, then `--grep "real upload|four complete"` and the final `--grep "four complete"`. The last complete four-plan journey passed in 3.9 minutes, including exact costs, cash, inventory, historical re-read, equity records and small-screen layout. Together with the new workspace suite this covers 16 distinct Chrome journeys.
- Final review found and reproduced an interrupted-refresh URL-normalization race, then fixed and verified it with a new unit test. The complete continuity browser journey also exposed page overflow when the exact equity table was expanded at 320px. A minimum-width correction keeps scrolling inside the table region; the quick browser regression now checks the expanded table at all 4 widths. Canvas legend clicks cannot diverge from the keyboard layer controls.

## BW-V03. Performance diagnosis

The same completed local run contains 2,961 audit events and frozen inputs spanning 39 day files. Initial detail API observations were 9.638 and 4.732 seconds. A separate profiled store read took 9.347 seconds: diagnostics consumed 5.095 seconds and publication/input reading consumed 3.227 seconds. Canonical serialization appeared repeatedly in the diagnostics stack; profiler timings overlap and include instrumentation overhead.

The implementation moves exact JSON primitive handling before repeated model/ABC checks, and validates decoded stored audit rows without reconstructing publication models. Typed payload/envelope checks, artifact hashes, event-set validation, frozen-input checks and retention behavior remain active. No persistent result cache or altered financial calculation was introduced.

Alternating warm reads in the same process with identical input produced:

| Measurement | Before, seconds | After, seconds |
|---|---|---|
| 1 | 5.158 | 4.754 |
| 2 | 5.016 | 4.379 |
| 3 | 4.611 | 4.223 |
| Median | 5.016 | 4.379 |

The measured store median improved by 12.7%; report identity and canonical diagnostics were identical. This local comparison is not an API latency guarantee. Real API reads after restart still varied from 5.457 to 13.154 seconds. Chrome also observed a 25.4-second wait for response headers under concurrent runtime/monitor reads, followed by prompt rendering. The dominant wait occurs before the response, rather than after data arrives in Vue. Monitor-read concurrency is a remaining contributor to investigate, not a proven sole cause.

The UI now explains waits at 10 seconds, ends its read observer at 30 seconds and permits retry. This does not stop a server-side job or guarantee cancellation of already executing server work. Same-query refresh preserves labelled previous rows/summary; failed refresh cannot imply current success. Full evidence validation still costs seconds on this dataset; further latency work needs separate concurrent-load profiling before considering a bounded, correctly invalidated projection/cache.

## BW-V04. Browser and historical evidence

The real local application at `http://127.0.0.1:8765` still lists 5 completed runs and 8 reviewed source records in 2 timelines. The legacy verified-dataset catalog is empty; that catalog does not represent all preparation history. No history deletion, backfill or provider download was performed for this work. The local service was restarted only after verifying no active jobs, to load the changed result reader.

Real-page screenshots record run discovery, the four-version provenance view and the truthful empty catalog. Fixture browser checks exercise widths 320/768/1024/1440 with 200% text, no document-level overflow, keyboard disclosures/controls and axe `wcag2a`, `wcag2aa`, `wcag21aa` checks with zero violations. At 1440 × 900, the first run begins at approximately y=857 without scrolling. Read-only workspace journeys assert zero business writes.

A final read-only check of the real run/data pages also returned zero axe violations and no page exceptions/business writes. The real data page had document widths exactly 320/768/1024/1440 at those viewport widths with 200% text. Its plan-history entry selected timeline mode (`aria-pressed=true`). Direct reads reconfirmed 5 runs and 8 reviewed source records.

- [Run records](C:/Users/xiedc/.codex/visualizations/2026/10/20/01a15810-0738-7f02-b3b1-8100372be616/backtest-workspace-runs-final.png)
- [Effective-version provenance](C:/Users/xiedc/.codex/visualizations/2026/10/20/01a15810-0738-7f02-b3b1-8100372be616/backtest-workspace-provenance-final.png)
- [Verified-data catalog](C:/Users/xiedc/.codex/visualizations/2026/10/20/01a15810-0738-7f02-b3b1-8100372be616/backtest-workspace-data-final.png)

## BW-V05. Boundaries

This verifies local UI behavior and related result integrity, not live provider availability, manual screen-reader use or production capacity. Browsing accepted tasks does not resume the browser-owned preparation chain. Unknown/expired/unrecorded evidence remains explicit. Supported legacy exports remain; continuous-loop results explain their current export limitation. Existing changes were retained. The user subsequently authorized review, commit and push on 2026-10-21.

## BW-V06. Pre-commit review

Review covered correctness, asynchronous races, evidence validation, bounded reads, interface boundaries, dependency changes and staged-file hygiene. One additional defect was reproduced: an unknown diagnostic code such as `constructor` could resolve an inherited object property instead of a neutral explanation. Lookup now uses `Object.hasOwn`; two regression tests cover registered contextual codes, unknown codes and inherited names. The new test failed before the fix and the complete suite passed after it.

The final type check, production build and all 7 workspace Chrome journeys passed again. The previously verified backend code and its 75 passing checks are unchanged. No blocking finding remains. The concurrent result-read latency described in BW-V03 remains an explicit limitation. Commits exclude databases, credentials, ignored measurement files and build outputs; implementation and verification remain split by concern.
