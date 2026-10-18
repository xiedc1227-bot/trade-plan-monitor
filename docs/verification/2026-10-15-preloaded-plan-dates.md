# Preloaded plan date workflow verification — 2026-10-15

Canonical English; Chinese review copy: [2026-10-15-preloaded-plan-dates.zh-CN.md](2026-10-15-preloaded-plan-dates.zh-CN.md).

## PD-V01. Scope and behavior

Implements [ML19](../specifications/backtesting/PROPOSAL-monitor-loop-backtest.md#ml19-preloaded-plans-with-dates-extracted-from-text-2026-10-15). New single/collection preparations accept a variable count of 1–256 UTF-8 TXT/MD files. Saving extracts a clear effective trading date from each source; fully resolved new text-only batches are ordered by date. Missing years, invalid/conflicting dates and relative dates remain unresolved until confirmation. Dates in observations, retrospective examples or conditional future actions are not a general source of applicability.

The form no longer requests authoring or historical availability timestamps. Unknown source fields remain null. Extraction, successor materialization, review, freeze and replay resolve an omitted availability boundary to 09:30 Asia/Shanghai on the effective trading day. Explicit legacy timestamps, source binding, idempotent receipts and frozen historical inputs retain their semantics. The UI distinguishes an unextracted source from an invalid candidate and identifies duplicate dates. It discloses the preloaded-plan execution assumption.

`plans.json` and `entry-fields.json` are not plan inputs or sources of supplemental facts. Existing research files and operational databases were not edited. Test databases reside in isolated temporary directories.

## PD-V02. Executed checks

| Check | Result |
|---|---|
| Backend unit suite: `python -m pytest tests/unit -m 'not live'` | 3,065 passed; one existing Starlette/httpx deprecation warning. |
| Related integration suites: `test_plan_preparation_*.py`, `test_monitor_loop_*.py`, `test_preparation_date_flow.py` | 540 passed; one existing Starlette/httpx deprecation warning. |
| Frontend suite: `npm run test -- --run` | 1,033 passed across 64 files. |
| Real Chrome: `npm run test:e2e -- tests/e2e/monitor-loop-backtest.spec.ts` | 3 passed in 4.2 minutes. |
| Frontend types: `npm run type-check` | Passed. |
| Production bundle: `npm run build` | Passed; packaged into the Python web distribution. |
| API snapshots/types: `python scripts/generate_frontend_types.py --check` | Canonical monitor v2 and compatibility monitor v1 current. |
| Changed Python files: Ruff; whitespace: `git diff --check` | Passed. |

New focused cases cover 21 date expressions, 1/5/17-file persistence, reversed selection order, manual confirmation, idempotent replay, null provenance, one-source freeze and multi-source predecessor/freeze bindings. The schedule rejects activation before 09:30. Existing explicit-time and frozen-input regression cases remain in the suites. An in-memory mutation accepting multiple distinct dates was caught by the conflicting-date test; source files were not mutated.

## PD-V03. Browser evidence and test corrections

Real Chrome exercises single-source upload/retry/edit/review/replay, unknown extraction cancellation recovery and a multi-source continuous account replay. The four-source fixture is one sample count, not a product requirement. Its effective dates are embedded in the supplied text, with no timestamps submitted and no manual date entry. Assertions cover server-resolved dates, suffix invalidation after editing, retry with preserved predecessors, one frozen chain, one run, two fills, final cash 1,019,000 fen, zero remaining shares and seven equity points. Input/result layouts are checked at 320/768/1024/1440 pixels.

After the successful browser run, screenshot review found one remaining historical-availability label in the version calendar. It was changed to execution start, followed by the result component tests and a rebuilt production bundle; the full browser replay was not repeated for this text-only correction.

Initial browser attempts exposed a test save-response race and an ambiguous status locator; waits now bind the actual create response and preparation-progress region. Later attempts completed all business assertions but failed a blanket console-error assertion: serial extraction legitimately advanced the revision before revision-bound detail reads. The test now accepts only GET item responses with HTTP 409 and exactly `PREPARATION_REVISION_CONFLICT`, matched by URL to the browser console entry. Other errors still fail; later successful loading and completed replay remain mandatory.

## PD-V04. Limits and use

Tests use fake AI/market services and do not certify a live model's extraction quality or real provider availability. The original sample documents that omit a year still need effective-date confirmation; no year is guessed from the clock, directory or filename. Plan semantics and opening-account completeness still require review.

A whole-tree pytest attempt encountered existing duplicate test module names; importlib mode was incompatible with existing unqualified cross-test imports. Suites were therefore run separately. A broad integration run was interrupted during an unrelated ten-symbol/252-day performance experiment; it is not recorded as passed. Validation focuses on the changed preparation and monitoring-loop paths. Windows sandbox restrictions on sockets/build filesystem access required local test execution outside that sandbox.

Restart the existing application process and refresh the browser to load the changed backend and built assets. Existing unresolved preparations can be edited and saved to infer or confirm dates; previously frozen inputs are not rewritten.
