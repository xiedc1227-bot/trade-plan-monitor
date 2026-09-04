# WEBF13 Route and New-Backtest Acceptance

**Status:** `PASS`

> Canonical English evidence record. The Chinese review copy is `webf13-acceptance.zh-CN.md`; both documents must remain semantically equivalent.

## Scope and Evidence Boundary

WEBF13 documents existing real production routing and closes the missing browser-level new-backtest journey evidence. Evidence was collected on 2026-09-04 (Asia/Shanghai) from `main` at `8171a7d8b7815b587a6a6f1ff9f92ee2c83735fb`; the working tree was clean before this slice. The environment was Windows with CPython 3.14.7, Node 24.13.1, npm 11.8.0, and the pinned Playwright 1.62.1 Chromium project.

This slice changes tests and paired documentation only. It changes no production source, REST path, OpenAPI field, generated TypeScript type, database schema, Schema v1 data, hash formula, provider boundary, token handling, or historical result.

## Route Evidence

Required route map: `/`, `/stocks/:symbol`, `/plans`, `/plans/:id`, `/alerts`, `/system`, `/backtests`, `/backtests/new`, `/backtests/data`, and `/backtests/:runId`. The former five placeholders `/`, `/stocks/:symbol`, `/plans/:id`, `/alerts`, and `/system` must resolve to real lazy SFC route views; the static backtest children must precede `:runId`.

- `rg -n "createRoutePlaceholder" web/src` found no reference.
- `BacktestRouter.spec.ts` fixes the exact ordered 10-route surface and lazy-loads each of the five former placeholders plus the existing plan workbench and four backtest views. Its focused run passed `12 tests`.
- The full deterministic browser suite passed `20 tests`. Existing production-router journeys cover `/`, `/stocks/:symbol`, `/plans/:id`, and `/alerts`; the new `/system` route case uses the real router and `GET /api/v1/health`, asserts the route title/heading, and reports no console, failed-request, unexpected-API, or external-request finding.

## New-Backtest Journey Evidence

Required deterministic browser chain: select a backend-listed immutable plan version and verified dataset; submit one idempotent run command; navigate to `/backtests/:runId?jobId=<jobId>`; poll the matching `BACKTEST_RUN` job; remove `jobId` only after `COMPLETED`; then render the materialized result. Failed or cancelled jobs retain their job identity and never fabricate a result.

- Initial RED: the new focused Chromium test failed `1 test` because the fake contract did not yet accept `POST /api/v1/backtest-runs`; the URL correctly remained `/backtests/new`.
- GREEN: the deterministic fake now returns the exact `202`, `Location`, and `Retry-After: 2` contract. The browser test asserts the exact generated request body, JSON content type, one bounded idempotency key, navigation to the matching `runId`/`jobId`, a first authoritative `RUNNING` job, two non-overlapping polls, canonical removal of `jobId` only after `COMPLETED`, and the final materialized result view. The focused test passed `1 test`, the affected two-file browser gate passed `8 tests`, and the final complete browser gate passed `20 tests`.
- The backend production-fake node `test_fake_production_journey_is_complete_offline_and_live_state_is_unchanged` separately passed `1 test` for `sync → verify → submit → poll → result → pin → export` with unchanged live state. The broader focused API/composition collection passed `284 tests`, skipped one POSIX-ownership-only case on Windows, and emitted only the existing Starlette `TestClient`/httpx2 deprecation warning.

## Contract Evidence

The frozen contract remains exactly 42 REST paths: 27 live paths and 15 backtest paths. `openapi.json` and `web/src/api/generated.ts` must remain current together; WEBF13 must not create a contract diff.

- `openapi.json` contains exactly `42` paths. `tests/integration/test_openapi_snapshot.py` passed `14 tests`.
- `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` reported `OpenAPI snapshot and frontend types are current`.
- Neither `openapi.json` nor `web/src/api/generated.ts` is in the diff.

## Security and Isolation Evidence

The browser uses generated-contract validation and the backend remains authoritative for plan eligibility/snapshots, dataset coverage, run identity, job state, and materialized results. Verification must use deterministic local fixtures: no token read, provider request, broker call, notification delivery, or external network access is permitted.

- All browser APIs were intercepted by deterministic same-origin fakes. The backtest audit recorded no unexpected request, external request, failed request, API failure, console warning/error, or overlapping request. The new system-route audit recorded the same clean boundary.
- No `.env` or credential value was read, no token was printed or returned, and no Tushare, DeepSeek, broker, notification, or other supplier request was made.
- Vue submits only the generated `BacktestRunCommand` with `planVersionId`; it does not send a plan snapshot or make plan-eligibility, dataset, job-completion, or result-availability decisions. Existing backend integration evidence remains the authority for those decisions.

## Required Offline Commands

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest tests/unit/test_backtest_api_schemas.py tests/unit/test_backtest_api_pagination.py tests/integration/test_backtest_run_api.py tests/integration/test_backtest_job_api.py tests/integration/test_backtest_production_composition.py tests/integration/test_openapi_snapshot.py -q -rs
.\.venv\Scripts\python.exe -m pytest tests/integration/test_backtest_acceptance.py::test_fake_production_journey_is_complete_offline_and_live_state_is_unchanged -q
.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check
npm --prefix web run test -- --run
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e
git diff --check
```

Results: Ruff passed; the focused backend collection passed `284` with `1` documented platform skip; the production-fake journey passed `1`; the OpenAPI snapshot passed `14`; generation consistency passed; Vitest passed `40 files / 580 tests`; `vue-tsc` passed; Vite production build passed; Chromium passed `20 tests`; and `git diff --check` passed. Vite retained its existing advisory that a generated chunk exceeds 500 kB after minification; this slice changes no production bundle source. Historical acceptance reports and hashes remain unchanged.

## Residual Risks

- Deterministic fake acceptance does not prove live Tushare, DeepSeek, broker, or other supplier availability or semantics; those remain separately authorized gates.
- The Windows run skips the POSIX file-ownership case and does not replace that platform-specific evidence.
- Manual NVDA and fresh performance profiling were not rerun for this test/documentation-only slice; the existing historical evidence remains unchanged and is not relabeled as new WEBF13 evidence.
