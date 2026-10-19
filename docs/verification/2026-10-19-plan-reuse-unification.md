# Plan reuse unification verification, 2026-10-19

Final review: PR-V07 records the scoped pre-commit review. Cancellation audits and narrow layouts are resolved (PR-V05–PR-V06); earlier sections retain their historical evidence and separate wider-suite limits.

## PR-V01. Scope and authority

The user approved the first increment and explicitly requested deletion of the JSON/YAML import API. [PRU01–PRU11](../specifications/backtesting/SPEC-plan-reuse-unification.md) define the boundary; [operations](../operations/plan-reuse.md) describe the resulting workflow. All data used here is synthetic/offline. No production database, real plan approval, live AI/market provider, deployment or Git push was used.

Workbench versions retain their original source, review identity and executable snapshot. Historical context is separately confirmed and frozen; accepted runs copy it into result-owned inputs. Existing source preparation and continuous multi-plan replay remain available. Only one immutable selection table is added to the preparation store. Trading engines, report formulas, market providers, prompts and task/read-thread limits are unchanged.

## PR-V02. Automated checks

| Check | Result |
|---|---|
| Focused API/store/workbench/import removal/OpenAPI matrix | 236 passed; later selection/contract additions are covered below |
| Final selection and both-profile compatibility matrix | 28 passed, including concurrency, strict Origin/context, sanitized SQLITE_BUSY, real prior single/collection store formats and restart with missing source store |
| Frontend full unit suite | 1121 passed across 75 files (`--maxWorkers=2`; original timeouts unchanged) |
| Frontend type check and production build | Passed |
| Ruff (`src tests`) and both-profile generated-contract check | Passed |
| Actual Chrome original preparation journeys | 5 passed, including four-plan continuous account replay and automatic history preparation |
| Scoped Chrome workbench submission/history/context checks | Complete submission and historical decision rendering passed in the final 3-test run. The context layout/axe assertions passed, but its strict audit recorded one aborted initial catalog GET; the same context test passed independently after the scoped grid fix. |
| Wider affected backend functional matrix | Initial run: 1671 passed, 1 Windows/POSIX owner-check skip, 6 contract assertion failures. Those exact contract cases were corrected and passed in the final 28-test matrix; no trading/history test failed. |

Backend API matrix command: `.venv/Scripts/python.exe -m pytest tests/unit/test_workbench_selection_context.py tests/integration/test_workbench_plan_selection.py tests/integration/test_plan_production_composition.py tests/integration/test_openapi_snapshot.py tests/integration/test_plan_preparation_store.py tests/integration/test_current_plan_api.py tests/integration/test_web_api.py -q`. Final selection/compatibility command: `.venv/Scripts/python.exe -m pytest tests/integration/test_workbench_plan_selection.py tests/integration/test_backtest_service_contract.py tests/integration/test_monitor_loop_contract.py -q`. Frontend commands: `npm --prefix web test -- --run --maxWorkers=2`, `npm --prefix web run type-check`, `npm --prefix web run build`. Static contracts: `.venv/Scripts/python.exe -m ruff check --no-cache src tests` and `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`.

Browser commands: `npm --prefix web run test:e2e -- tests/e2e/monitor-loop-backtest.spec.ts` and `npm --prefix web run test:e2e -- tests/e2e/backtests.spec.ts --grep 'workbench structured|submits a complete|historical typed'`. Chrome verifies the new context at 320/1440 pixels and 200% text, field bounds, serious/critical axe violations, actual request bodies, original idempotency keys and historical typed decision rendering. The structured form's intrinsic grid overflow was fixed locally; no AppShell CSS changed.

The separately collected service-boundary unit module also passed (18 tests) (see the command `pytest tests/unit/test_backtest_service_contract.py -q`).

## PR-V03. Compatibility evidence

- Compare both OpenAPI profiles against pre-change `81aae039`: every retained component schema is identical. Only `PlanDocumentFormat` and `PlanImportCommand` disappear. Two selection routes are added, `/api/v1/plan-imports` is removed, and only data-check/run/result unions change. Existing operation/schema comparisons remain enforced after accounting for these exact extensions. U27 records both generated snapshot hashes.
- Test actual persisted inactive workbench approval; reject unreviewed or changed references. `FOLLOW_REMINDERS` produces the expected fill and `OBSERVE_ONLY` produces none through the existing real worker.
- Same-key selection retries survive restart; concurrent freezes produce one resource/receipt. Same-key run retries keep one run/job; changed intent conflicts. After acceptance, the original reader is disabled and the preparation database is renamed. Execution, complete result/fills reads and a fresh app restart succeed without recreating that source database.
- Upgrade both valid previous preparation formats and preserve exact document/receipt rows. Existing single-plan and scheduled codecs and prepared-chain lineage/account assertions are retained. New workbench input identity binds the full selection without changing old input/hash domains.
- The four-plan Chrome fixture explicitly supplies its historical KNOWN cash account on the first review. This retains its original exact cash/equity/fee assertions while current preparation defaults remain `POSITION_LIMIT_ONLY`; production review/default logic is untouched. The retained scripted-research form's 19 tests move to a test-only harness because the normal page now uses structured workbench context.
- Pre-existing unrelated working changes are preserved. Only the existing bilingual unified-plan specification receives the necessary current-API list/U27 additions; other pre-existing file hashes are checked unchanged.

## PR-V04. Limits and wider-suite findings

The complete default backend collection has duplicate unit/integration module basenames (`test_backtest_service_contract.py`); affected modules were run explicitly without changing import rules. A large 10-symbol/252-day capacity benchmark was stopped during unchanged market-data seeding. No performance threshold, execution limit or test was weakened, and no fresh capacity certification is claimed.

The wider backtest-page Chrome run initially finished **5 passed / 5 failed**. Failures include strict request-audit reports of `net::ERR_ABORTED` during refresh/navigation and a 320px/200% layout observation. The audit was kept strict; request failures were not filtered to get a green run. Subsequent scoped workbench/history/context checks are reported separately above. This is not a claim that every global browser regression passes, and unrelated shared-shell/navigation behavior was not broadened into this change. Earlier full frontend timing failures were rerun without changing the original timeout.

No production store was opened or migrated. Tagged preparation schema 2 is not readable by older binaries; the operations guide records rollback implications. No claim is made about live AI/Tushare availability, production load or deployment readiness.

## PR-V05. Cancellation-audit follow-up

The user requested diagnosis and repair of the remaining cancellation audits without lowering gates. The installed Chrome `155.0.8059.80` reproduces [Chromium issue 568852319](https://issues.chromium.org/issues/568852319/dupes): a fully read no-store response can finish with `Network.loadingFailed`/`net::ERR_ABORTED` when EOF arrives separately from its last data. The official [fix 8508456](https://chromium-review.googlesource.com/c/chromium/src/+/8508456), commit `62473ad0f747e245e514c93e741bb8e168a2a207`, main revision `1712735`, records the terminal state before notifying the consumer. Public [Chrome for Testing metadata](https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json), checked on 2026-10-19, identifies pinned Beta `157.0.8103.6` at revision `1717349` as containing that change; Stable 155's branch base is earlier.

Evidence before the fix: a minimal page completed all 1000 parsed responses, but only 985 request-finished events arrived in the production-reader regression. The unchanged wider browser suite reproduced 9 passes / 2 failures (one cancellation audit, one narrow-layout failure). Real HTTP and alternate reader experiments reduced frequency but did not eliminate the defect; all such experimental application/test-handler edits were withdrawn.

The final change only pins an isolated test browser, adds its explicit setup script/cache ignore, and adds `streamCompletion.spec.ts`. `backtests.spec.ts`, `monitor-loop-backtest.spec.ts`, all `src/` and `web/src/` files, generated contracts and historical fixtures match the follow-up's starting hashes. `expect(audit.requestFailures).toEqual([])`, all other existing audit/quantity/metric assertions, viewports, `expect.timeout=5000`, `retries=0`, npm/Python package versions and production behavior are unchanged. System Chrome remains `155.0.8059.80`.

| Follow-up check | Result |
|---|---|
| `streamCompletion.spec.ts --repeat-each 3` | 9 passed; 3000/3000 JSON responses and request-finished events, zero cancellation errors; separated EOF succeeds; true caller abort still reports `net::ERR_ABORTED` with no request-finished event |
| Original `backtests.spec.ts` and `monitor-loop-backtest.spec.ts` | 15 passed / 1 pre-existing layout failure; all 5 real preparation/continuous journeys and historical result checks passed, with no cancellation-audit failures |
| Existing frontend unit suite, original timeout | 1121 passed across 75 files (`--maxWorkers=2`) |
| Historical input/report/continuity/research-input checks | 61 passed |
| Type check, production build, setup-script Ruff and cached setup repeat | Passed |

The downloaded Windows archive is 210043639 bytes, SHA-256 `128c0f5f1f7e894d9b416c28f1e8db08698a7fd57945495c216589f75ae4e5b8`. Only the local ignored test cache contains the browser binary. Setup commands are in operations PR-O04; Linux/macOS package paths are supported by the setup script but were not executed in this Windows verification. The remaining 320px/200%-text layout observation is retained as a separate failure, not skipped or relaxed by this cancellation fix.


## PR-V06. Narrow-layout follow-up

The user requested repair of the remaining narrow-layout failure while preserving the original test gates, multi-plan replay and historical results. The unchanged layout test reproduced a 477px document scroll width in a 320px viewport with a computed root font size of 32px (200%). Existing R13 DOM measurements and screenshots localized the overflow to the three `DatasetScopeForm.vue` filter inputs: each extended from x=82 to x=477 (395px), while its label/form container was only 156px wide. The other three backtest routes measured 320px document width. The navigation list extends inside its existing local scroll container; it does not cause document overflow.

The entire application change is one scoped CSS rule on `.dataset-filters__fields input`: `min-width: 0; width: 100%`. This lets each input shrink with its existing grid/flex container. No global overflow clipping, font reduction, new breakpoints or content removal is used. Scripts, templates, filter validation/events, AppShell, APIs, trading/account calculations, persisted results and all original test/configuration bytes are unchanged from this follow-up's starting hashes. Generated ignored build output is excluded from the source comparison.

| Follow-up check | Result |
|---|---|
| Original layout gate: 320/768/1024/1440px × four backtest routes, 200% root text | Passed all 16 combinations; original `scrollWidth <= clientWidth` assertion unchanged |
| Existing R13 immediate/settled diagnostics | Passed; all four routes settle at 320px document width; no uncontained element extends past the viewport; before/after screenshots reviewed |
| Original backtest, real continuous replay and stream-completion browser suites | 19 passed (7.1m), including all 5 real preparation/continuous journeys and historical-result checks; no cancellation-audit failures. The four-plan fixture retains 2 fills, final cash 1019000 fen, fees 1000 fen, realized PnL 19000 fen and the original 7-point equity/cash sequence. |
| Existing frontend unit suite | 1121 passed across 75 files; original timeouts unchanged (`--maxWorkers=2`) |
| Frontend type check and production build | Passed |

Commands: `npm --prefix web run test:e2e -- tests/e2e/backtests.spec.ts --grep 'keeps 320/768/1024/1440|R13 records' --reporter=json`, `npm --prefix web run test:e2e -- tests/e2e/backtests.spec.ts tests/e2e/monitor-loop-backtest.spec.ts tests/e2e/streamCompletion.spec.ts`, `npm --prefix web test -- --run --maxWorkers=2`, `npm --prefix web run type-check`, `npm --prefix web run build`.

The pinned browser, zero request-failure assertions, five-second expectations, zero retries, request/DOM/polling/ECharts bounds and original account/cash/equity/history assertions are retained. This follow-up does not add capacity certification or production-data/deployment verification; the unrelated PR-V04 limits remain.


## PR-V07. Final review and commit boundary

The user requested a final review of plan-source unification and both follow-up repairs, with explicit preservation of multi-plan continuous replay and historical results, followed by a scoped commit. Review covers the exact candidate tree after excluding the pre-existing retention-wording changes (nine whole files and the U22 paragraph in both unified-plan specifications). The current API list and U27 additions remain included. `.tmp/`, browser binaries/cache, generated build output and unrelated edits are excluded.

Independent backend review confirmed that old single/scheduled input models, codec branches and hash formulas remain unchanged; prepared multi-plan execution retains its existing account transition and executor. The preparation-store upgrade preserves real old single/collection documents and idempotency receipts. Accepted runs own complete copied inputs; execution, restart, historical reports and exports do not require the mutable original plan store.

One review finding was fixed before commit: the first workbench reader call could leak a SQLAlchemy-wrapped SQLite BUSY/LOCKED exception into a generic 500. Only that new call now unwraps `OperationalError.orig` and maps BUSY/LOCKED to sanitized 503 plus `Retry-After: 1`; other database errors keep their existing failure behavior. Six API fault cases cover raw/wrapped BUSY, LOCKED and IOERR, no private-path leakage, same-key recovery and persisted idempotent replay. The red run produced four busy-lock failures / two non-busy passes; after the fix the complete selection module passes. Independent re-review closed the finding; no blocking findings remain.

A temporary inversion of the new frontend research-context equality guard caused the existing exact-response test to fail; the original bytes were restored before normal verification. The retained scripted-research suite is a detected rename with unchanged behavioral assertions, apart from the approved removed client member and current selector wording. No retry, timeout, audit, layout, account, cash/equity or history threshold was relaxed.

| Final check | Result |
|---|---|
| Complete offline backend unit suite | 3331 passed |
| Post-review context, legacy loop input and service-boundary units | 47 passed |
| Complete workbench selection integration suite, including six new fault cases | 15 passed |
| Original-source, old-store, replay, result/export and both-profile contract integration matrix | 526 passed (359.34s), with no skips or failures |
| Complete frontend unit suite | 1121 passed across 75 files |
| Backtest pages, five real preparation/continuous journeys and stream-completion browser suites | 19 passed (6.0m), including all 5 real preparation/continuous journeys, original four-plan account/cash/equity values and historical results; no cancellation or layout failures. |
| Ruff, both generated contract profiles, Vue type check and production build | Passed |

Unit commands: `.venv/Scripts/python.exe -m pytest tests/unit -q -m 'not live'`; `.venv/Scripts/python.exe -m pytest tests/unit/test_workbench_selection_context.py tests/unit/test_monitor_loop_input.py tests/unit/test_backtest_service_contract.py -q`; `.venv/Scripts/python.exe -m pytest tests/integration/test_workbench_plan_selection.py -q`. Frontend, browser and static commands are those in PR-V02/PR-V06. The integration matrix explicitly covers `test_current_plan_api`, `test_plan_production_composition`, `test_plan_preparation_store`, `test_plan_preparation_review`, `test_single_plan_library`, `test_backtest_service_contract`, `test_monitor_loop_contract`, `test_openapi_snapshot`, `test_monitor_loop_input_store`, `test_monitor_loop_submission`, `test_monitor_loop_result_api`, `test_monitor_loop_retention`, `test_monitor_loop_plan_switch`, `test_monitor_loop_parity`, `test_loop_position_funding`, `test_unified_replay`, `test_unified_replay_parity`, `test_unified_replay_boundaries`, `test_backtest_compatibility`, `test_backtest_result_api`, `test_backtest_exports` and `test_web_api` under `tests/integration/`, with `-q -m 'not live'`.

Review is limited to this functional change and its stated regression evidence. It does not certify live providers, deployment or the previously uncompleted capacity benchmark. Unrelated working edits remain outside the commit and are preserved byte for byte.
