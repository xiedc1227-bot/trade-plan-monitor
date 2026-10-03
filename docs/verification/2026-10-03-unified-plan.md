# One Plan Workflow Verification

## V01. Scope and status

Date: 2026-10-03, Asia/Shanghai. Status: **LOCALLY_VERIFIED**. This report covers the current [U01–U08 contract](../specifications/monitoring/SPEC-unified-plan.md), not the superseded daily-plan acceptance. Baseline: `880c76fecfbf002bbc1b73d717c54d542429e7e8`. Changes are local and uncommitted; no production database, ignored configuration, credentials, live provider, deployment or external publication was changed.

Current extraction and operation use one `/plans` workspace, Schema 5 and `plan-extract-v9`. Conditions retain their periods; completed daily and completed five-minute evidence can coexist. Source-defined reminder-only rules cannot be transformed into liquidation instructions. Fundamentals remain generation-time review background. Explicit simulation applies a complete positive multiple of 100 shares, with T+1, CORE, capacity, quote, review and revision checks.

## V02. Deleted live surfaces

- Separate daily extraction module, page, workbench, route, composable and duplicated components; all `/daily-*` public operations and live plan-family selection.
- Unused live legacy/explicit editors and runtime panels; current extraction no longer dispatches to prompt v1–v7 or old candidate families.
- AI provider/secret write and connection-test HTTP operations. Configuration reads and immutable startup configuration remain.
- Real position fill/closure/confirmation and ongoing manual event-risk write operations and their orphan UI. Existing history readers and stored records remain.
- Old one-shot AI acceptance runners and their dedicated old-output tests. Their original source remains recoverable from Git baseline `880c76fecfbf002bbc1b73d717c54d542429e7e8`; previous request authorization is not rebound to a new prompt.

## V03. Concrete retained dependencies

| Dependency | Current or historical consumer | Reason for retention |
|---|---|---|
| Frozen Schema 1–4 codecs and model graphs | Existing plan/version readers and historical backtest inputs | Preserve original bytes, hash interpretation and audit evidence; old plans cannot activate or simulate as current plans. |
| `ai/daily_review.py` and `dailyMapping` fields | Current exact source/content review and historical review decoding | Shared source spans, exclusions, human supplements and review hashes; names are compatibility details, not a second extraction path. |
| `runtime/daily_service.py`, `web/daily_service.py`, `state/daily_repository.py`, `state/daily_accounting.py` | The one current evaluator and atomic simulated ledger | Reuse proven transaction, risk timing, T+1, CORE, idempotency and cause accounting without converting actual holdings. |
| Certified minute normalization/aggregation and official daily series/indicators | Current conditions and recovery | Preserve provider cutoff, completeness, adjustment and formula evidence. Daily-only rules do not require legacy minute indicators. |
| Legacy decision/index modules and explicit read DTOs | Frozen historical/backtest replay and compatible history decoding | Keep research interpretation; remove their live operation routes and actionable old-plan projections. |
| Actual-position and manual-event-risk repositories/read services | Historical record reads and isolated research/recovery evidence | Removing write UI/API does not erase or rewrite historical inventory and risk evidence. |
| Surviving bounded acceptance helpers | Market/recovery fake-provider tests and sealed historical budget guards | Retain concrete dependencies without restoring retired live extraction or renewing old authorization. |

The frozen semantic corpus continues to verify exact values, units, grouping, unsupported meaning, omissions and source-review authority through frozen domain/read validation. It does not invoke retired live extraction. Current HTTP adapter and source/review checks are tested separately against the current contract. No meaningful safety assertion is replaced by a fake successful runtime result.

## V04. Previous one-workflow acceptance (before persistent rules)

This section retains the earlier `plan-extract-v8` one-workflow results and commands. References to final source mean that earlier acceptance snapshot and do not certify U08. Current persistent-rule evidence is recorded separately in V06; overlapping reruns are not summed.

| Gate | Result |
|---|---|
| Current late simulation failure, entire SQLite dump, retry/idempotency | 2 passed: failure after accounting/signal writes and after receipt creation leaves every row unchanged. |
| Frozen Schema3 semantic source corpus | 27 passed: original source values, grouping, omissions and review blockers retained. |
| Python unit and contract gate | 2695 passed, 4 live tests deselected (`pytest tests/unit tests/contract -q -m 'not live'`, 21.68 seconds), on final source. Includes current surface checks for both HTTP monitor versions. |
| Python integration gate | 3289 passed, 1 skipped, 4 deselected in 1435.31 seconds on final source, with no ignored test files. The existing `test_cursor_key_rejects_foreign_posix_owner_before_use` skip requires POSIX ownership semantics and cannot run on Windows. The four deselected capacity cases passed separately below. Real operating-system restart, source/review binding, late activation, status proof and atomic rollback cases are included. |
| Unchanged backtest capacity gate | All four costly capacity cases passed separately: ten-symbol/252-day replay, traced heap, stable BUY/T+1 exit bytes, and large queries/100k export. The 604800 source-minute rows and existing fixed budgets are unchanged. The final integration run excludes exactly these four already verified cases. |
| Frontend unit/type/build and browser workflow | 802 unit tests passed in 56 files; type-check and production build passed. All 31 retained Playwright tests passed (55.0 seconds), including current extraction/review/activation, whole simulation, risk-reminder filtering/acknowledgement, source-edit invalidation and packaged restart. |
| Generated API/type consistency, lint and documentation | `python scripts/generate_frontend_types.py --check` passed for both monitor contract versions. `ruff check src tests scripts` and `git diff --check` passed. All 15 changed bilingual document pairs exist; U/V/H section IDs, API paths and numeric values match in the new contract/reports. The current canonical OpenAPI hash remains `4d1ff1d58e37b764aa057415cee1418298bc05bedbd360fbec60202f1f7cd255`; no proof metadata was added to the public wire. |
| Independent final review | Repaired extraction audit commit, reminder-only access beside old accounting, and preservation of earlier signals/risks and reminder activation dates. Delivery/cache/status revalidate facts and every consumed five-minute bucket against raw one-minute sources. Completion proof binds the exact immutable evaluation ID, configuration, generation, activation, calendar and applicable target; GET neither installs proof nor scans all evaluation history. Missing daily calendar or adjustment basis blocks dependent evidence. Expired reminders cannot inherit old risk in status or acquisition; genuinely latched risk can continue. Production and status share period inference, including reviewed-fact-only confirmation and minute-only reset conditions. All identified scoped defects were fixed and independently rechecked. Final affected runtime and status groups passed 160 and 28 tests respectively; these overlap the broad integration gate and are not added to its total. |

Exploratory results are not summed into the final total. The discovered stale cutoffs, overly broad minute-prefix requirements, legacy permission demand, reminder modeling, old actionability and obsolete fixture request families were corrected before the final run. Additional regressions preserve negative technical facts, every consumed composite-risk evidence ID, extraction provenance across restart and unchanged legacy accounting alongside current reminders.

Final Python commands, run from `trade-plan-monitor/`:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live'
.venv/Scripts/python.exe -u -m pytest tests/integration -v -rs -m 'not live' -k 'not ten_symbol_252_day_replays_meet_capacity_budgets and not 252_day_replay_from_ten_symbol_dataset_meets_traced_heap_budget and not each_fixture_symbol_has_stable_buy_and_t1_exit_bytes and not large_queries_and_100k_export_meet_fixed_budgets' --maxfail=15
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
.venv/Scripts/python.exe -m ruff check src tests scripts
git diff --check
```

Frontend commands, run from `trade-plan-monitor/web/`: `npm run test -- --run`, `npm run type-check`, `npm run build`, `npm run test:e2e`.

Pre-push document-maintenance recheck: 2696 unit/contract tests passed (4 live tests deselected), 37 targeted integration tests passed, frontend 802 tests and type-check passed. Frozen T059 release reports and operator guides now live under `tests/history/t059`; exact Git-source SHA-256 values are checked before the unchanged acceptance/parity/secret assertions. A changed-byte regression is added; no historical acceptance is rebound to the current workflow.

## V05. Limits

Deterministic tests use isolated temporary SQLite databases, fake SDK evidence or an HTTP mock transport through the real AI adapter. They do not certify live Tushare/AI/Webhook availability or approve any user's strategy. A read can validate only locally observed, admitted evidence; an unobserved remote daily revision becomes visible on the next acquisition. Historical release/daily reports retain their dates and acceptance scope. No historical approval is silently upgraded, and no production data migration/reset was performed. Manual NVDA and current live-environment rollout evidence are outside this local verification.


## V06. Current persistent-rule verification (U08)

Baseline: `86bb448`. This scoped change adds explicit Schema 5 `PLAN_ACTIVE`, retains the original plain `DailyValidity` union member and uses `plan-extract-v9` for new extraction. Historical v8 responses remain readable without changing candidate/mapping bytes. No load/import/save fallback or migration is introduced. Saving and reviewing a replacement leave the active version unchanged until its new review binding is explicitly activated.

| Gate | Actual result |
|---|---|
| Final Python unit/contract gate | 2728 passed, 4 live tests deselected, 21.28 seconds on frozen implementation. |
| Scoped API/runtime/status/accounting gate | 358 passed, 112.05 seconds across the 16 files listed below. Includes source/review and activation, production mixed periods, runtime status, notifications, whole-lot simulation, T+1, CORE, capacity, idempotency and latched-risk/removal boundaries. |
| Persistent production-fixture consumers | 154 passed, 249.62 seconds across the 10 files listed below. Includes send-time authority, recovery/deactivation/replacement fences, numeric oracle and channel/transport behavior with `PLAN_ACTIVE` ordinary rules. |
| Final guard/review/API recheck | 80 passed, 8.70 seconds after independent-review repairs; overlaps other gates and is not added to their totals. Includes 32 persistent-validity regressions. |
| Frontend | 804 tests passed in 56 files; `npm run type-check` and `npm run build` passed. The final historical v8 response-read test is included. |
| Real browser | 1 Playwright workflow passed, 8.8 seconds, using the isolated temporary SQLite/fake-provider server. It extracts, edits mixed conditions, saves, refreshes, reviews, explicitly activates, performs one full simulated trade, verifies reminder-only inventory isolation, and deactivates. The saved ordinary validity is exactly `{"mode":"PLAN_ACTIVE"}` and has no end-date field. |
| API artifacts/lint | Both `generate_frontend_types.py --check` monitor contracts, `ruff check src tests scripts` and `git diff --check` passed. Regeneration produced no tracked OpenAPI/type changes; the approved snapshot hash in U04 is unchanged. |
| Independent final review | Approved on frozen source with no remaining actionable findings within U08. Independent persistent validity/domain/formal API check: 50 passed. Reviewer also compared complete and incomplete historical review snapshots against the baseline byte for byte and exercised an in-memory mutation of the deadline-guard eligibility branch. |

Compatibility uses fixed values captured independently from pre-change Git `86bb448`: canonical JSON SHA-256 `937c7b062a93abb3567f04e074f8eb4d82efc467ea60e04d1e89cd12502bf741`, content hash `832a1d87b3c3bea92b12ef94c621a42790e82aaef030d4cc8d8fa2b2a23f80ee`, review evidence hash `5feb96a2bfba4c1bd84bffa2ce85a906c29e3f7a05a47b606fac1f87ac203dcd`, source hash `5ebe3212d9cfcafce2a9b5da7e293d3678bbf92145703fce6e840b95ee86ccff`, and empty issue list. The same dated payload still accepts an omitted `DATE_RANGE` mode. A direct 2027-01-04 comparison proves persistence beyond the old 2026-12-31 end date while the dated control rejects confirmation. Old signals still expire; a later date alone cannot create a signal, a reviewed independent occurrence can, and that occurrence cannot be duplicated.

Independent review repaired deadline scope: one retained SELL/activation date cannot discharge a persistent BUY deadline; a start date cannot discharge a cutoff; a single execution window cannot hide a deadline in either order or language; manual lifetime wording cannot hide a competing date/duration. Only recognized local occurrence-window phrases and pure lifecycle phrases are removed from the conservative scan. Report/evidence dates remain distinct. One source clause yields one visible deadline issue, listing all affected validity paths. Human conversion requires the exact clause quotation plus `改为持续有效` or `convert to PLAN_ACTIVE` in its scoped supplement, then a new review and explicit activation. This is a bounded guard alongside full source review, not a general language parser.

The external Chinese template `D:/Workspace/Projects/ai-quant-pilot/docs/TradingAgents/reports/新提示词.txt` received four scoped wording replacements: the input lifetime, output lifetime, self-check lifetime and tool-coupling lifetime. Single-signal expiry, four output sections, the 1500-character limit, strategy/price/position/risk/fees and other missing-parameter wording remain. That original `.txt` is outside this Git repository and has no original Git snapshot; no English copy is required.

Final unit/lint/artifact commands from `trade-plan-monitor/`:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live'
.venv/Scripts/python.exe -m pytest tests/unit/test_persistent_rule_validity.py tests/unit/test_daily_review.py tests/unit/test_daily_extraction.py tests/unit/test_unified_plan_domain.py tests/integration/test_current_plan_api.py tests/integration/test_source_treatment_review_api.py tests/integration/test_explicit_plan_review_api.py -q -m 'not live'
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
.venv/Scripts/python.exe -m ruff check src tests scripts
git diff --check
```

Scoped 358-case command:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_current_plan_api.py tests/integration/test_unified_runtime.py tests/integration/test_unified_simulation_transactions.py tests/integration/test_notification_delivery.py tests/integration/test_runtime_status_official_close.py tests/integration/test_runtime_status_composition.py tests/integration/test_runtime_status_projection.py tests/integration/test_daily_history_regression.py tests/integration/test_daily_plan_boundaries.py tests/integration/test_daily_simulation.py tests/integration/test_daily_simulation_review_regressions.py tests/integration/test_source_treatment_review_api.py tests/integration/test_source_treatment_legacy_compatibility.py tests/integration/test_ai_provider_contract.py tests/integration/test_explicit_plan_review_api.py tests/integration/test_web_api.py -q -m 'not live'
```

Persistent production-fixture 154-case command:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_delivery_admission.py tests/integration/test_explicit_plan_channel_acceptance.py tests/integration/test_explicit_plan_independent_oracle.py tests/integration/test_explicit_runtime_production.py tests/integration/test_explicit_transport.py tests/integration/test_recovered_explicit_rolling_window.py tests/integration/test_recovery_activation_fences.py tests/integration/test_runtime_pipeline_progress.py tests/integration/test_s3_startup_outcome_association.py tests/integration/test_source_treatment_inventory_isolation.py -q -m 'not live'
```

Frontend commands from `trade-plan-monitor/web/`: `npm run test -- --run`, `npm run type-check`, `npm run build`, `npm run test:e2e -- tests/e2e/condition-plan.spec.ts`. Earlier exploratory failures were corrected and are not counted as passes; the final browser rerun had clean server teardown. Python gates retain the existing FastAPI TestClient/httpx deprecation warning. The unchanged expensive backtest-capacity gate in V04 was reused and not rerun. No real provider, production database/configuration, commit, push or deployment was used for U08.
