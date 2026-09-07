# WEBF13 Route and New-Backtest Acceptance

**Status:** `PASS`

> Canonical English evidence record. The Chinese review copy is `webf13-acceptance.zh-CN.md`; both documents must remain semantically equivalent.

## Scope and Evidence Boundary

WEBF13 documents existing real production routing, closes the missing browser-level new-backtest journey evidence, and records the follow-up plan-workspace layout. Initial evidence was collected on 2026-09-04 (Asia/Shanghai). The environment was Windows with CPython 3.14.7, Node 24.13.1, npm 11.8.0, and the pinned Playwright 1.62.1 Chromium project.

The temporary WEBF13 dashboard-503 Health-fallback slice is historical only and is superseded by `SPEC-live-production-chain`, ADR 0004, and `live-production-chain-acceptance.md`. This record makes no current projection-availability acceptance claim.

## Route Evidence

Required route map: `/`, `/stocks/:symbol`, `/plans`, `/plans/:id`, `/alerts`, `/system`, `/backtests`, `/backtests/new`, `/backtests/data`, and `/backtests/:runId`. The former five placeholders `/`, `/stocks/:symbol`, `/plans/:id`, `/alerts`, and `/system` must resolve to real lazy SFC route views; the static backtest children must precede `:runId`.

- `rg -n "createRoutePlaceholder" web/src` found no reference.
- `BacktestRouter.spec.ts` fixes the exact ordered 10-route surface and lazy-loads each of the five former placeholders plus the existing plan workbench and four backtest views. Its focused run passed `12 tests`.
- The full deterministic browser suite passed `20 tests`. Existing production-router journeys cover `/`, `/stocks/:symbol`, `/plans/:id`, and `/alerts`; the new `/system` route case uses the real router and `GET /api/v1/health`, asserts the route title/heading, and reports no console, failed-request, unexpected-API, or external-request finding.

## Plan Workspace Layout Evidence

The plan page presents one compact creation area before the persisted version workspace. Structured JSON/YAML import and optional AI extraction are mutually visible creation modes rather than two full workflows stacked vertically. Switching modes preserves unfinished local input; parsing, validation, draft creation, activation eligibility, and lifecycle decisions remain backend-authoritative.

- Initial RED: the focused Vue test failed because no creation-mode controls or isolated panels existed. GREEN adds an accessible tablist, places AI extraction first and selects it by default, preserves unfinished input through `v-show`, and supports Left/Right/Home/End keyboard selection.
- Browser RED measured the import panel at `698 px` high and the persisted workspace at only `894 px` wide in the desktop fixture. GREEN keeps the import panel below `400 px` and both major regions above `90%` of the route width without changing request payloads or backend calls.
- Responsive RED found `81 px` horizontal overflow at a `320 px` viewport. The final browser gate reports no route-level horizontal overflow at `320`, `768`, `1024`, or `1440 px`; narrow headers/actions stack, technical enum values can wrap, and the creation controls remain keyboard-accessible. The plan journey's WCAG 2.1 A/AA serious/critical axe result is empty.

## Historical Availability Note

The temporary WEBF13 dashboard-503 Health fallback is superseded by the live-production-chain typed availability contract. Its old browser observations are not current acceptance evidence; new results belong exclusively in `live-production-chain-acceptance.md`.

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

- All browser APIs were intercepted by deterministic same-origin fakes. The backtest and system-route audits recorded no unexpected request, external request, failed request, API failure, console warning/error, or overlapping request. The temporary dashboard-503 availability audit is superseded by the live-production-chain contract and is not current acceptance evidence.
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

Results: The historical WEBF13 results remain limited to the original route and backtest scope. The superseded availability follow-up adds no current result count; live-production-chain evidence is recorded only in `live-production-chain-acceptance.md`. Historical Schema v1 data, backtest results, and hashes remain unchanged.

## Residual Risks

- Deterministic fake acceptance does not prove live Tushare, DeepSeek, broker, or other supplier availability or semantics; those remain separately authorized gates.
- The Windows run skips the POSIX file-ownership case and does not replace that platform-specific evidence.
- Manual NVDA and fresh performance profiling were not rerun for this layout slice; automated keyboard, responsive, and axe evidence does not replace those separate manual gates.
