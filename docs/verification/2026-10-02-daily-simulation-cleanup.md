# Daily simulation cleanup verification — 2026-10-02

Canonical English; paired user review copy: `2026-10-02-daily-simulation-cleanup.zh-CN.md`. Status: COMPLETE. The scoped cleanup, independent review and offline verification gate are complete.

## V01. Scope and authority

The user explicitly authorized removal of the daily monitor's broker order execution tracking. Monitoring does not submit orders. A reminder does not change positions. A separate explicit simulation either applies the entire current authorized quantity or changes nothing. The current contract is [Daily simulation cleanup](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/030075c4946bf34833a0155fde6b4deda3c79055/tasks/2026-10-02-daily-plan-simulation-cleanup.md), with [SPEC-daily-plan](../specifications/monitoring/SPEC-daily-plan.md) DP-A01–DP-A20 retained.

The prior [2026-10-01 verification](2026-10-01-daily-plan.md) and [independent review](2026-10-01-daily-plan-independent-review.md) describe the superseded scope. Their 6065-pass result is historical evidence and is not a result for this cleanup.

## V02. Required result

- Delete daily execution-report APIs, broker order identities/statuses, partial fills, uncertain orders, reservations, client allocation controls and the corresponding generated contracts, UI and tests.
- Use positive multiples of 100 shares for whole simulated trades; all position quantities are zero or multiples of 100. Ordinary consumption is zero or the whole planned quantity.
- Keep simulation positions separate from shared actual-position tables. Retain only the internal acquisition-date batches needed for T+1 and strategy debit order.
- Preserve current source review, technical facts, confirmed risk obligations, ordinary expiry, CORE protection, maximum position, durable deduplication, outbox eligibility and production recovery. Fundamentals remain excluded. Existing index behavior and Schema 1/2/3 remain unchanged.
- Preserve obsolete development evidence and reject incompatible simulation operations explicitly; do not convert broker reports into simulated trades.

Current acceptance traces below identify permanent tests; overlapping files are not independent test counts. Full-suite completion is recorded separately in V03.

| Criterion | Permanent evidence |
|---|---|
| DP-A01 | Existing `test_plan_domain.py`, `test_ai_plan_extraction_v4.py`, `test_explicit_plan_review.py`, legacy decision/backtest suites; daily model compatibility in `test_daily_plan.py`. |
| DP-A02–03 | `test_daily_extraction.py::test_historical_source_stays_partial_and_ai_cannot_supply_human_authority`, `test_daily_review.py::test_complete_review_has_no_issues_and_semantic_edit_invalidates_supplements`, public source/review/activation in `test_daily_plan_chain.py`, both Chrome journeys. |
| DP-A04 | `test_daily_plan.py::test_daily_zone_never_defaults_endpoints_or_accepts_empty_ticks`, `test_daily_conditions.py::test_daily_all_any_missing_retains_each_evidence`, `test_daily_lifecycle.py::test_holiday_calendar_and_included_endpoints_do_not_allow_chasing`. |
| DP-A05–09 | `test_daily_lifecycle.py`, `test_daily_plan_chain.py::test_daily_public_review_confirmation_next_session_and_expiry`, `test_daily_plan_chain.py::test_same_completed_date_can_reevaluate_current_quote_reentry`, `test_daily_plan_boundaries.py::test_unconsumed_expiry_restart_later_close_requires_new_independent_evidence`. |
| DP-A10 | `test_daily_plan_boundaries.py::test_real_sell_pressure_never_sells_core_and_complete_tactical_simulation`, `test_daily_safety_boundaries.py` ordinary SELL/CORE/T+1 cases, explicit aggregate initialization in `test_daily_simulation.py`. |
| DP-A11 | `test_daily_simulation.py::test_full_simulation_retry_restart_tplusone_and_no_actual_tables`, `test_invalid_or_partial_quantity_is_zero_mutation`, `test_planned200_partial100_is_rejected_with_zero_mutation`, `test_two_distinct_confirmation_keys_cannot_consume_one_signal`; reminder/acknowledgement assertions in the full simulation test and Chrome. |
| DP-A12 | `test_daily_simulation.py::test_current200_plus_buy100_reaches_max300_and_blocks_independent_new_buy`, `test_removed_order_endpoint_and_editor_fields`, T+1/full simulation and ordinary CORE protection above; `test_daily_simulation_contract.py`. |
| DP-A13–14 | `test_daily_risk.py`, `test_daily_plan_chain.py::test_ordinary_rebound_below_line_confirms_then_executes_next_session`, technical severe timing in `test_daily_safety_boundaries.py` and the full risk browser flow. |
| DP-A15 | `test_daily_source_exclusions.py`, `test_daily_scope_exclusion.py`, `test_daily_scope_http.py` exact background/source/relabelled/nested/API rejection oracles. |
| DP-A16 | `test_daily_safety_boundaries.py::test_risk_aggregate_offer_preserves_core_and_tplusone_unavailable` and its reviewed target/scope/unknown-input cases, `test_daily_simulation.py::test_risk_simulation_keeps_tplusone_obligation_then_fulfills_without_reviving_buy`, expiry/restart in `test_daily_simulation_review_regressions.py`. |
| DP-A17 | `test_daily_conditions.py::test_raw_or_incoherent_daily_basis_cannot_be_admitted`, `test_v2_histogram_doubles_v1_without_changing_dif_dea`, `test_daily_plan.py::test_500_bar_contract_counts_condition_and_reference_offsets`, `test_daily_sparse_calendar_regression.py`. |
| DP-A18 | `test_daily_simulation.py` rollback/concurrent-key/idempotency/retry/obsolete-data oracles; `test_daily_simulation_review_regressions.py` current-fact delivery, old outbox/ACTIVE isolation, real composition restart and post-simulation invalidation. |
| DP-A19 | `test_daily_scope_http.py::test_background_rebound_review_preserves_same_technical_runtime_result`, `test_daily_safety_boundaries.py::test_confirmed_technical_risk_survives_unknown_quantity_and_missing_auxiliary_close`, latched-risk auxiliary-data and shared legacy/index suites. |
| DP-A20 | `web/tests/e2e/daily-plan.spec.ts`, `web/tests/e2e/daily-review-batches.spec.ts`, `test_daily_production_reevaluation.py`, frontend `dailySimulation.spec.ts`, `dailyAlertCompatibility.spec.ts`, `plansApi.spec.ts`. |

Backend test filenames above resolve in `tests/unit/` or `tests/integration/`; names following a module's full node refer to that same module. C1–C7 permanent fixes are in `tests/integration/test_daily_simulation_review_regressions.py`; C6 also has actual before/after API fixtures in `web/tests/unit/fixtures/` and strict parser assertions in `plansApi.spec.ts`.

## V03. Verification results

Implementation is frozen and independently reviewed. The fresh full backend run finished with one outdated exact-field test expectation. Its strict contract assertion was corrected and independently reviewed; the remaining offline suite then passed. The final coverage gate combines that passing recheck with the eight unchanged capacity/acceptance tests already passed in the full run. No earlier full-suite count is reused. Frontend checks use the final generated contracts and corrected real daily review-response parser.

| Check / executor | Observed result and boundary |
|---|---|
| Sol UI helper: `npm run test -- --run` | 62 files, 865 passed in 6.21s. Raw log: `../../../Temp/daily-simulation-ui-final-c6-reviewed/frontend-units-final-schema.log`. |
| Sol UI helper: `npm run type-check` | Exit 0. Raw log: `../../../Temp/daily-simulation-ui-final-c6-reviewed/frontend-type-final-schema.log`. |
| Sol UI helper: `npm run build`, `npm run build:runtime-status-preview`, `npm run build:legacy-test` | All exit 0, run sequentially after final contract generation; logs `build-standard-final-schema.log`, `build-runtime-status-final-schema.log`, `build-legacy-test-final-schema.log` in the same directory. |
| Sol UI helper: `npm run test:e2e -- tests/e2e/daily-plan.spec.ts tests/e2e/daily-review-batches.spec.ts --project=chrome` | 2 passed in 14.0s; no audited console warning/error or failed request. Real offline APIs and temporary SQLite, full BUY100, T+1, risk SELL200, retry/rejection and two supplement batches with reload. Runner-only NO_COLOR warning. Raw log: `../../../Temp/daily-simulation-ui-final-c6-reviewed/browser-daily-final-schema.log`. |
| Coordinator: `.venv/Scripts/python.exe -m ruff check --no-cache src tests` | Exit 0, all checks passed. |
| Coordinator: `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | Exit 0: canonical monitor v2 and compatibility monitor v1 snapshots/types both current. |
| Coordinator: cleanup-baseline and documentation audit | Eight selected shared-inventory/runtime/indicator/condition/scope/composition files have unchanged SHA-256; ten paired document checks have matching stable section IDs and checkbox states. Initial 122 and final 146 local Markdown links all resolve; all 18 full test-node references in V02 exist. Cleanup checkpoints are complete. Frozen source/test/asset manifest saved separately before full completion. Final `git diff --check` exits 0; only existing LF/CRLF conversion notices remain. |
| Coordinator: `.venv/Scripts/python.exe -m pytest -q -m "not live"` | Exit 1: **6081 passed, 1 failed, 1 skipped, 4 deselected, 1 warning in 3279.22s (0:54:39)**. Only failure: `test_web_api.py::test_plan_versions_are_paginated_and_details_revalidate_canonical_identity` omitted the new nullable `obsoleteReason` from its exact summary-field set. The full capacity group passed. Raw log: `../../../Temp/daily-simulation-cleanup-final-backend.log`. |
| Sol implementation helper: `.venv/Scripts/python.exe -m pytest tests/integration/test_web_api.py tests/integration/test_openapi_snapshot.py -q --tb=short` | **160 passed, 1 warning in 19.70s**, after the three-line test-only correction. The exact set now includes `obsoleteReason`; normal summary/detail values must be `None`. All previous canonical-identity, pagination, missing-resource and service-call assertions remain. Targeted Ruff passed; Astra independently accepted this diff. |
| Coordinator: `.venv/Scripts/python.exe -m pytest -q -m "not live" --ignore=tests/integration/test_backtest_acceptance.py` | Exit 0: **6074 passed, 1 skipped, 4 deselected, 1 warning in 1204.62s (0:20:04)**. The only omitted file contains the eight unchanged capacity/acceptance tests already passed in the complete run; collection independently confirmed eight tests. Raw log: `../../../Temp/daily-simulation-cleanup-final-backend-recheck.log`. |

The 851-file freeze comparison, repeated after the passing recheck, identified only `tests/integration/test_web_api.py` as changed, with no missing frozen file. No business source, generated contract or frontend asset changed after the full run. The follow-up retains the already passing capacity evidence according to the plan's no-repeat boundary for test-only corrections. The required offline coverage gate is satisfied. This is not a single all-green full-suite run, and overlapping targeted counts must not be added. The warning is the existing Starlette/httpx TestClient deprecation.

The helper inspected the browser screenshots. The coordinator additionally inspected the earlier BUY/T+1 and risk200 screenshots. Final browser evidence and logs are under `../../../Temp/daily-simulation-ui-final-c6-reviewed/`; assertions are permanent in the two listed browser tests. Earlier frontend/browser runs are intermediate evidence, not added to the final count.

## V04. Independent review

See the separately owned [independent review](2026-10-02-daily-simulation-independent-review.md). Astra independently closed C1–C7 after final source/parser inspection and found no remaining material findings. Its independent 79-test daily group, 89-test shared-alert group and 8-test final quantity check all passed; actual unreviewed and reviewed API responses passed the real Vite SSR parser. These overlapping targeted counts are not summed into a whole-suite count. The coordinator completed the coverage gate above; Astra also independently accepted the final three-line strict test-contract correction.

## V05. Operational boundaries

Validation uses offline synthetic plans/providers, temporary SQLite databases and the local browser fixture. No production database, live market or AI provider, external notification, real order, commit, push or deployment is part of this task. The historical user plan is not activated or approved by these tests.

## V06. Subsequent publication handoff

On 2026-10-02 the user separately authorized organizing the changes, removing unused test files and committing/pushing to GitHub. The redundant single-test `test_daily_risk_allocations.py` file was removed; its valid full aggregate-offer/CORE/T+1 oracle was moved unchanged to `test_daily_safety_boundaries.py`, with identical function AST and assertions. Four obsolete broker-order fields were removed from the lifecycle fixture. No useful regression was deleted. Historical commands/results above retain their original filenames; DP-A16 now points to the surviving test.

After this test-only consolidation, all **23 current daily test files passed 229 tests, 1 existing warning in 51.56s**, exit 0. The command enumerated `tests/unit/test_daily*.py` and `tests/integration/test_daily*.py` and ran `.venv/Scripts/python.exe -m pytest <files> -q --tb=short`; log: `../../../Temp/daily-simulation-publication-tests.log`. Ruff over `src tests` and both generated-contract checks passed again. Business source/assets and generated contracts still match the accepted freeze. Staged whitespace checks additionally removed only blank-line whitespace from two tests and one Vue file, preserving Python AST and Vue content. No repeated capacity run is required for this unchanged test oracle. Runtime data, secrets, caches, builds and temporary reproductions are excluded from the publication; the staged path and credential-pattern audit passed.
