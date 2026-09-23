# Legacy missing-heartbeat maintenance — 2026-09-23

## Scope and result

The approved D8/A13 missing-heartbeat resolution is connected through the production Web composition and system page. Active plans with no heartbeat enter `BLOCKED`, not an endlessly stale/recovering display or an automatic plan replay. The Web service remains available, but monitor tasks, provider requests, heartbeat and alert dispatch do not start; ordinary HTTP mutations return `409`. A preview lists exact active plan identities and a fingerprint. A separately checked confirmation atomically invalidates those plans, clears/audits pending closes, suppresses existing delivery eligibility and records a batch audit. Holdings and confirmed trades are not changed. The operator restarts the tool before creating new plans.

## Evidence

- Meaningful RED tests first failed on the missing manual-invalidation module, missing typed blocked admission and missing HTTP endpoint. The implementation then passed those cases.
- Temporary SQLite tests cover preview fingerprint drift, a heartbeat appearing after preview, rollback when the second deactivation fails, retained 1,000-unit holding, duplicate confirmation without duplicate audit, blocked ordinary write, no provider request/task during blocked startup, and a fresh app lifecycle in the same interpreter after invalidation returning `DEGRADED` with no old plans. A separate spawned process was killed after its first in-transaction plan deactivation: reopening showed both plans/pending closes and no audit; a second process completed the exact preview once, retaining the holding.
- `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_plan_expiry.py tests/integration/test_runtime_liveness.py tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py tests/integration/test_web_api.py -q --tb=short` — 218 passed, one existing Starlette/httpx deprecation warning. An earlier run exposed four WebSocket failures from the new global dependency's HTTP-only parameter; using `HTTPConnection` fixed all four without changing WebSocket behavior.
- `npm test -- --run` — 670 passed across 46 files, including 14/14 in `SystemView.spec.ts` and the ambiguous lost-response case. `npm run type-check` and `npm run build` passed. `npm run test:e2e -- tests/e2e/legacy-maintenance.spec.ts` passed in isolated Chrome after a test-fixture-only missing dashboard stub was fixed. The 375 px system-page screenshot was visually reviewed: no horizontal overflow or lost confirmation control. Browser console/request audit and WCAG 2.1 A/AA axe scan passed.
- `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` passed after generating the 51-path OpenAPI/frontend contract. All reads and writes used temporary databases; no live provider, real notification, user database, deployment or GitHub push was involved.

## Remaining gates

V1d still needs durable terminal receipts for old unsent alerts without existing eligibility rows and a complete safety review. V1c/RR009 still has bounded historical proof and production recovery integration obligations. This slice does not close business step 1 or authorize production migration. Broader end-to-end process-restart and notification-failure acceptance remains open.
