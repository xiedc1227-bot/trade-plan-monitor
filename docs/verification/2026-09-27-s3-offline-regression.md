# S3 offline regression checkpoint

> Canonical English. Paired review copy: `2026-09-27-s3-offline-regression.zh-CN.md`.

## Scope

The coordinator ran the planned offline regression at source HEAD `453cc0c` after the DAILY_BARS internal permission wiring was committed. Existing source and test files were held unchanged during the run. New documentation and `tests/integration/test_s3_startup_minute_coverage.py` were added concurrently after collection; that new test file is **not included** in this result. Subsequent SDK-boundary corrections also require their own evidence.

Only offline tests were selected. No live-provider test, real notification service, user-database migration, push, or deployment was performed. The heavy backtest file was excluded exactly as specified by the S3-09 command; this is not an unrestricted all-tests run.

## Executed commands and results

| Command | Observed result |
| --- | --- |
| `.venv/Scripts/python -m pytest -m 'not live' --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | **18 failed, 4778 passed, 1 skipped, 4 deselected, 1 warning**, 670.06 seconds; exit code 1 |
| `.venv/Scripts/python -m ruff check src tests scripts` | All checks passed on the source checkpoint, before the new startup-coverage files were added |

The warning was the existing Starlette/httpx TestClient deprecation. Passing targeted slices do not override the failed aggregate gate. Counts from overlapping earlier commands must not be added to this count.

## Failure inventory

| File | Failed cases | Observed failure, not yet a final root-cause classification |
| --- | ---: | --- |
| `tests/integration/test_position_production_composition.py` | 3 | Position creation returned HTTP 409 rather than the expected 200 in calendar-authority, create/replay, and closure/replay cases. |
| `tests/integration/test_r13_channel_acceptance.py` | 3 | Explicit BUY, SELL, and RISK_ALERT scenarios recorded zero delivery attempts rather than one. |
| `tests/unit/test_r14_bounded_acceptance.py` | 1 | `test_ai_guard_allows_only_one_approved_prompt_and_counts_failed_attempt` raised `BudgetDenied` before the fake transport. Earlier paired foundation evidence records the mock's missing required `temperature=0`; this run did not repair or waive it. |
| `tests/unit/test_r17_failure_diagnostics.py` | 11 | Eight failure-category cases and three exception-redaction cases raised `AttributeError`: their `Pipeline` test double has no `_stock_semantics`, accessed by `refresh_references`. |

A read-only diagnosis is assigned to determine fixture drift versus actual product regression, using response bodies, durable records, and supported production contracts. No safety guard or assertion is to be weakened merely to obtain a passing result. Historical passing reports and historical failures are evidence from their own checkpoints, not proof that every failure above is pre-existing.

## Independent boundary finding

Independent review separately reproduced an SDK-start admission gap using the actual certification wrapper, a fake SDK, and a controlled clock: capture at `10:00:00`, latest start `10:00:15`, provider callback/S at `10:00:14`, then two seconds of wrapper certification work before the inner SDK starts at `10:00:16`. The old S/R proof can still pass. This inline reproduction was not a test added to the aggregate run. The reviewed per-invocation boundary correction and its dedicated RED-to-GREEN matrix remain separate work.

## Gate status

**S3-09, C1, C3, and business step 3 remain OPEN.** This checkpoint is failed-regression evidence, not final acceptance. The startup minute coverage matrix, SDK boundary repair, minute-owner execution, unified scheduler integration, and broader lifecycle/fault gates are not certified by the passing subset. Real-service validation, step 4 UI work, and step 5 release acceptance remain outside this checkpoint.
