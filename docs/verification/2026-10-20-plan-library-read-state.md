# Plan library read-state verification — 2026-10-20

## PL-R01. Incident evidence

The local `backtest-preparation.sqlite3` contained 19 preparation records, including 8 `SINGLE` / `REVIEWED` versions. The result store contained 5 run records and 14,800 detail records. Counts were obtained using SQLite `mode=ro` and `PRAGMA query_only=ON`; no plan text was exported. These counts demonstrate retained records, not an audit proving every historical record is intact.

The running library and run-list endpoints returned HTTP `503`. `/api/v1/backtest-service` reported `DEGRADED`, `canRead: false`, `physicallyDrained: true`, and `SERVICE_REPAIR_REQUIRED`. The component incorrectly combined that read failure with its empty-list message. Direct read-only library projection and response validation successfully returned all 8 reviewed versions. Initialization of metadata on an isolated SQLite backup also succeeded. The isolated asynchronous lifecycle diagnostic did not finish within the observation period; its two helper processes were stopped. The initial exception or timeout that caused the running service to degrade was not captured, so its original trigger remains unconfirmed.

## PL-R02. Recovery and scope

An explicit request to `/api/v1/backtest-service/recovery-requests` used `RETRY_PREPARATION` and `resumeJobIds: []`. It returned `202`; the service became `READ_READY` with `canRead: true`, and the library returned 8 reviewed versions. The existing Chrome page then displayed 2 timelines with 4 updates each. No replay job was resumed, and no business-record deletion, plan recreation or source-text rewrite was performed.

The UI now separates failure from empty results, explains HTTP `503` recovery, hides old errors during retry, and retains the last successful list and selection with an explicit stale-data label after refresh failure. Paired operational guidance is recorded in `docs/operations/plan-reuse.md` and `docs/operations/plan-reuse.zh-CN.md`, section `PR-O10`.

## PL-R03. Validation

- `npm test -- --run tests/unit/PlanLibrary.spec.ts tests/unit/PlanLibraryPagination.spec.ts`: 22 passed, including 3 new regressions that failed before the fix.
- `npm run type-check` and `npm run build`: passed; packaged frontend assets updated.
- `npx playwright test tests/e2e/plan-library-versions.spec.ts`: 3 passed in Chrome. The new journey exercises HTTP `503`, explicit list retry, 8-version recovery, refresh failure preserving the selected endpoint, and a confirmed empty response; it observes no mutation requests. Existing 200% text and 30-timeline pagination journeys also passed.
- The actual local page was separately checked in Chrome: 2 timelines and 8 versions rendered. Screenshot: `plan-library-restored.png` in this chat's visualization directory.

The running service's original degradation trigger and a broader redesign of the creation page remain outside this verified fix. Existing working-tree changes were preserved.
