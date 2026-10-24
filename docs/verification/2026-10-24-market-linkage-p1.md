# Verification: market-linkage-p1

## MLV1-01 — Scope and authorization

The user approved MLP1-D01–MLP1-D06 and ordered staged implementation on 2026-10-24. Baseline `dbeff32`. This report records executed checks, not proposed results. [Specification](../specifications/monitoring/SPEC-market-linkage-p1.md) · [tasks](../../tasks/market-linkage-p1.md) · [Chinese copy](2026-10-24-market-linkage-p1.zh-CN.md).

## MLV1-02 — Baseline and boundary inventory

MLP1-T01: actual domain/draft/codec/hash/review/runtime/state/API/replay boundaries inspected; recorded in the paired [contract inventory](../specifications/monitoring/CONTRACT-market-linkage-p1.md). No user database or external provider was accessed.

Executed V01 from `trade-plan-monitor/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_linkage_contract.py tests/unit/test_market_regime.py tests/unit/test_relative_strength.py tests/unit/test_confirmation_selection.py tests/unit/test_quantity_policy.py -q
```

Result: **91 passed in 1.20s**. The Python launcher emitted its existing installation-location diagnostic but the tests completed successfully with exit code 0. No P1 functional acceptance is claimed by this baseline. Remaining task results will be appended only after execution.

## MLV1-03 — Strict Schema 7 contracts (MLP1-T02)

RED: initial contract tests produced 9 failures / 1 pass for missing Schema 7 models/dispatch. New incomplete-draft and common-draft-constructor checks then failed twice before implementation. GREEN: 52 exception/linked/unified domain tests passed in 1.58s; 176 old plan/daily/bounded-codec tests passed in 0.45s. The unknown-version fixture now uses 8 because 7 is explicitly supported; the rejection assertion is retained. Targeted Ruff and whitespace checks passed.

The first expanded invocation named nonexistent `test_daily_plan_domain.py`; it ran no tests and was corrected to the actual test files. The default temporary directory failed initialization. An explicit workspace temporary directory fixed that issue; subsequent stack capture localized the remaining wait to Windows `asyncio` socketpair creation. Rerunning offline tests with local communication permitted succeeded. No application logic was changed to bypass the environment restriction.

Accepted commands (temporary paths are invocation-specific):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_exception_contract.py tests/unit/test_market_linkage_contract.py tests/unit/test_unified_plan_domain.py -q --basetemp .test-tmp/p1-t02-accepted
.\.venv\Scripts\python.exe -m pytest tests/unit/test_plan_domain.py tests/unit/test_daily_plan.py tests/unit/test_bounded_validation_codec.py -q --basetemp .test-tmp/p1-t02-legacy-fixed
```

This accepts the strict domain/draft/codec/hash slice only. Source review, activation, runtime, approval and execution integration remain unchecked tasks.

## MLV1-04 — Pure eligibility and quantity (MLP1-T03 / MLP1-C01)

Added independent route/quantity fixtures before implementation; the missing module failed collection as expected. The quantity slice passed 24 tests. Two additional tests exposed a BROKEN candidate with no legal quantity under Q0; after adding grid feasibility admission, the combined V01–V03 suite passed **144 tests in 1.33s**, with targeted Ruff passing. Both P0 state/strength/confirmation equalities and the new exception boundaries are included.

Exact minimum substitution, no automatic broken-route quantity, legal choices on either side of half Q0, capacity/unknown/invalid-input blocks and ordinary-route independence are verified. Pure policies always return zero authorized quantity, even when eligible. MLP1-Q12's persisted stale/foreign approval scenarios remain assigned to authorization integration; no pure test is claimed as persistence acceptance.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_exception_policy.py tests/unit/test_market_exception_quantity.py tests/unit/test_market_exception_contract.py tests/unit/test_market_linkage_contract.py tests/unit/test_market_regime.py tests/unit/test_relative_strength.py tests/unit/test_confirmation_selection.py tests/unit/test_quantity_policy.py -q
```

MLP1-C01 accepts contracts and arithmetic only. Subsequent authority, runtime, UI and replay tasks remain incomplete.

## MLV1-05 — Source-bound extraction (MLP1-T04)

Schema 7 extraction now uses `plan-extract-v10`, requires complete exception definitions and per-route source permission, and cannot manufacture an approval. Negated permissions are checked for literal as well as interpreted bindings. Chinese and English definitions retain the same boundaries. Existing v8/v9 records remain readable.

RED: the expanded schema exposed a real 50,000-character input-limit regression; two prompt-budget tests failed. Shared identical schema definitions fixed the regression without increasing the limit or removing validation constraints. The final focused extraction, review, security and prompt-budget run passed **73 tests in 2.55s**; default-version regression tests passed **63 tests in 0.97s**. Full `ruff check src tests` passed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_current_plan_extraction_security.py tests/integration/test_market_exception_review.py tests/integration/test_market_linkage_review.py tests/unit/test_current_review_contract.py tests/unit/test_preparation_prompt_budget.py -q --basetemp .test-tmp/p1-t04-verified
```

MLP1-T04 is accepted. Update/preparation, durable authority and all later checkpoints remain pending.
