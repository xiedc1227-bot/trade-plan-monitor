# Task List: market-index-context

> Canonical English task list. The Chinese review copy is `todo.zh-CN.md`; IDs, files, commands, and acceptance criteria stay aligned.

## Foundation

- [x] `IDX001` — Implement closed board-index identity mapping.
  - Acceptance: five mappings and all invalid/fallback cases are deterministic; bindings are immutable and recomputable.
  - Verify: `python -m pytest tests/unit/test_market_index_identity.py -q`.
  - Files: `tests/unit/test_market_index_identity.py`, `src/trade_plan_monitor/market_index/identity.py`, `src/trade_plan_monitor/market_index/__init__.py`.
- [x] `IDX002` — Implement index bars, canonical hashes, formulas, and health.
  - Acceptance: exact completed-bar validation, SMA/lookback/return goldens, issue codes, and content hashes match specs.
  - Verify: `python -m pytest tests/unit/test_market_index_data.py -q`.
  - Files: `tests/unit/test_market_index_data.py`, `market_index/models.py`, `market_index/canonical.py`, `market_index/formulas.py`.
- [x] `IDX003` — Implement provider boundary and shared cutoff snapshot coordinator.
  - Acceptance: unioned requests fetch once; concurrent equal keys share; board failures isolate; no provider secret leaks.
  - Verify: `python -m pytest tests/integration/test_market_index_snapshots.py -q`.
  - Files: `tests/integration/test_market_index_snapshots.py`, `market_index/provider.py`, `market_index/requirements.py`, `market_index/snapshots.py`.

## Plan Evaluation

- [x] `IDX004` — Add explicit Schema v2 binding and six condition models.
  - Acceptance: v1 rejects new fields/leaves without hash drift; v2 requires a recomputed binding and exact bounds.
  - Verify: `python -m pytest tests/unit/test_plan_index_conditions.py tests/unit/test_plan_domain.py -q`.
  - Files: `tests/unit/test_plan_index_conditions.py`, `domain/plan_models.py`, `domain/plan_validation.py`, `domain/plan_codec.py`.
- [x] `IDX005` — Evaluate index leaves with exact plan paths and missing evidence.
  - Acceptance: equality, all roots, three-valued composition, two-plan divergence, and no-condition behavior pass.
  - Verify: `python -m pytest tests/unit/test_plan_index_conditions.py tests/unit/test_decision_engine.py tests/replay/test_decision_replay.py -q`.
  - Files: `decision/models.py`, `decision/conditions.py`, `decision/episodes.py`, `decision/risk.py`, `tests/unit/test_plan_index_conditions.py`.

## Monitoring

- [x] `IDX006` — Inject shared snapshots into live evaluation and keep latest shared/plan projections separate.
  - Acceptance: one snapshot per cutoff/index, no-condition failure isolation, and runtime evidence persistence pass.
  - Verify: `python -m pytest tests/integration/test_market_index_runtime.py tests/integration/test_ten_symbol_runtime.py -q`.
  - Files: `tests/integration/test_market_index_runtime.py`, `runtime/service.py`, `runtime/symbol_service.py`, `web/lifespan.py`.
- [x] `IDX007` — Add monitoring API, history endpoint, invalidation, OpenAPI, and generated types.
  - Acceptance: bounded safe schemas/endpoints/events and nullable migration fields pass contract tests.
  - Verify: `python -m pytest tests/integration/test_market_index_web.py tests/integration/test_openapi_snapshot.py tests/integration/test_websocket.py -q`; `python scripts/generate_frontend_types.py --check`.
  - Files: `web/schemas.py`, `web/routers/market_indexes.py`, `web/app.py`, `web/websocket.py`, generated contracts/tests.
- [x] `IDX008` — Add monitoring Vue components and series composable test-first.
  - Acceptance: shared data and plan outcomes are visually separate; loading/failure/not-used/keyboard/responsive states pass.
  - Verify: `npm --prefix web run type-check`; `npm --prefix web run test -- --run`.
  - Files: `web/src/components/market-index/*`, `web/src/composables/useMarketIndexSeries.ts`, dashboard/detail views, unit tests.

## Backtesting

- [x] `IDX009` — Add v2 index artifacts, dynamic coverage/warm-up, shared replay snapshots, and v3 run identity.
  - Acceptance: no lookahead, live/replay byte parity, old goldens unchanged, no-condition coverage isolation, zero network.
  - Verify: `python -m pytest tests/unit/test_backtest_index_data.py tests/integration/test_backtest_index_dataset.py tests/integration/test_backtest_runner.py -q`.
  - Files: `backtest/index_data.py`, `backtest/dataset.py`, `backtest/market_store.py`, `backtest/runner.py`, tests.
- [x] `IDX010` — Persist/project backtest index evidence, add series API, and version formal export.
  - Acceptance: nullable old runs, exact identities/counts, 512-point bound, retained details, and stable export pass.
  - Verify: `python -m pytest tests/integration/test_backtest_index_api.py tests/integration/test_backtest_export_api.py -q`; OpenAPI check.
  - Files: `backtest/results.py`, `web/backtest_schemas.py`, `web/routers/backtest_results.py`, `web/backtest_export.py`, tests/generated contracts.
- [x] `IDX011` — Add backtest index form/summary/tab components test-first.
  - Acceptance: backend coverage is read-only, summaries/path identities match, all availability states and accessibility pass.
  - Verify: `npm --prefix web run type-check`; `npm --prefix web run test -- --run`; targeted Playwright.
  - Files: backtest index components/composable, new/detail views, API adapter, unit/e2e tests.

## Completion

- [x] `IDX012` — Finish paired README/API/test report and run all offline gates.
  - Acceptance: bilingual parity, documented provider limitation, complete file/test/risk report, clean secret scan, all required gates green.
  - Verify: full commands in `tasks/plan.md`, `git diff --check`, `git status --short`.
  - Files: `README.md`, `README.zh-CN.md`, `docs/README*`, paired verification report, `openapi.json`, generated TypeScript.

## WEBF13 Route and Journey Closure

- [x] `WEBF13` — Prove the real production-route/new-backtest journey boundary and record offline acceptance evidence without changing the frozen contract.
  - Acceptance: paired specifications identify the former placeholder routes `/`, `/stocks/:symbol`, `/plans/:id`, `/alerts`, and `/system` as real lazy SFCs; the exact 10-route map and `submit → run+job URL → poll → remove jobId → materialized result` chain have unit, browser, and backend-fake evidence; OpenAPI remains exactly 42 paths (27 live plus 15 backtest); the paired report is `PASS`.
  - Verify: focused backend pytest plus the production-fake journey; Ruff; OpenAPI snapshot and generated-TypeScript consistency; full Vitest, `vue-tsc`, build, and Chromium suites; `git diff --check`.
  - Files: `README*`, `docs/README*`, paired local-Web/backtest/API/ADR specifications, `tasks/plan*`, `tasks/todo*`, `docs/verification/webf13-acceptance*`, `web/tests/unit/BacktestRouter.spec.ts`, `web/tests/e2e/backtests.spec.ts`, and `web/tests/e2e/accessibility.spec.ts`.
