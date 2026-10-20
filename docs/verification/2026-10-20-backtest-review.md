# Backtest result review verification — 2026-10-20

## BR-V01. Delivered scope

Implements [BR01–BR06](../specifications/backtesting/SPEC-backtest-review.md) and [BT-R01–BT-R03](../../tasks/backtest-review.md): compact overview/fills; dedicated non-trade and provenance areas; exact fill/event/sequence selection; a cause/effect panel with recorded requirement-versus-actual evidence; signed bounded relation pagination; visited-cursor Previous; URL history, cancellation and keyboard focus. The final compact table has 7 columns, with receipt/audit details disclosed on demand.

The derived `backtest_review_event` index is staged atomically with canonical detail rows, follows detail deletion, and is optional for old stores. Existing canonical payloads and report/set hashes are not rewritten. Explicit old-run maintenance uses verified retained records. Query availability, indexing readiness and known missing links remain separate. No fresh AI explanation or per-fill PnL is computed.

## BR-V02. Automated checks

All commands below ran from the project root or `web/` as appropriate, using isolated fixtures. Existing unrelated cost-display changes were preserved.

| Check | Result |
|---|---|
| `.venv/Scripts/python -m pytest tests/integration/test_backtest_review.py tests/integration/test_backtest_migrations.py tests/integration/test_monitor_loop_contract.py tests/integration/test_backtest_result_api.py -q` | 120 passed |
| `.venv/Scripts/python -m pytest tests/integration/test_backtest_review.py tests/integration/test_monitor_loop_retention.py tests/integration/test_monitor_loop_publication.py -q` | 36 passed; overlaps the 12 review tests above |
| `.venv/Scripts/python -m pytest tests/integration/test_backtest_review.py -k exact_sequence -q` | 1 passed, 11 deselected; SQLite `PRAGMA data_version` stayed unchanged across HTTP reads |
| `npm exec -- vitest run` | 80 files, 1188 tests passed |
| `npm exec -- vitest run tests/unit/BacktestReview.spec.ts tests/unit/BacktestResultTables.spec.ts` | 22 passed after the final table layout adjustment |
| `npm run type-check` | Passed |
| `npm run build` | Passed; Vite staged the packaged SPA assets |
| `.venv/Scripts/python scripts/generate_frontend_types.py --check` | Both OpenAPI documents and generated clients current |
| Ruff on changed backend modules/tests/script; `git diff --check` | Passed |

The published API fixture contains 982 events. Tests locate the last sequence directly, traverse actual causal edges in pages of 1, reject mismatched signed cursor context and invalid queries, retain a fill after detail expiry (including expiry between related pages), reject corrupted index/hash bindings, reopen old/new schemas, and compare canonical payload bytes before/after maintenance. Query-plan checks use the identity and cause indexes without a table scan.

The environment required unsandboxed local test execution for immutable-file hard links and temporary compiler-cache renames. Existing Starlette TestClient deprecation and Node color-environment warnings were non-failing. The first full browser run found two obsolete assertions expecting provenance on the former summary page; their navigation was updated and the full group then passed.

## BR-V03. Real browser checks

Pinned local Chrome executed:

- `npm exec -- playwright test tests/e2e/monitor-loop-backtest.spec.ts tests/e2e/plan-execution-diagnostics.spec.ts`: 6 passed, including real upload/review/publication, automatic preparation, four-plan continuous accounting and representative diagnostics.
- `npm exec -- playwright test tests/e2e/backtests.spec.ts --grep "covers the four backtest routes|keeps 320/768|enforces request" --output .pytest_cache/review-legacy-browser`: 3 passed, covering legacy routes, keyboard/axe, responsive/text zoom, request/DOM/polling/ECharts bounds.
- `npm exec -- playwright test tests/e2e/monitor-loop-backtest.spec.ts --grep "real upload/retry/edit/review/run" --output .pytest_cache/review-final-browser`: 1 repeated scenario passed after the final 7-column adjustment.

Verified 320/768/1024/1440px, no document horizontal overflow, selection URLs, browser Back, cause/effect controls, diagnostic Enter activation, heading focus and focus restoration. Axe reported no serious/critical WCAG violations in the reviewed result journey; the dedicated diagnostic check reported no selected-rule violations. Console/page errors were checked by the browser suites. Desktop/mobile screenshots were visually inspected and saved in this conversation's visualization artifacts.

## BR-V04. Practical limits

Old runs without lookup metadata need the explicit [maintenance procedure](../operations/backtest-review.md); original readers remain available. Full-run date/plan/reason filters, linked charts and verified single-fill PnL remain BR06 follow-ups. Browser evidence uses deterministic isolated databases, not a production-database migration. No moderated user timing study or 10000-event performance benchmark was performed; the bounded query contract and indexed query plans were verified.
