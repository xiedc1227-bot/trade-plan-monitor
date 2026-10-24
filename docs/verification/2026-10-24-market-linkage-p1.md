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

## MLV1-06 — Permission-preserving updates (MLP1-T05)

RED: four new tests failed for missing Schema 7 compact preparation and predecessor snapshot serialization; one authority-injection test already passed. Added explicit typed Schema 7 dispatch for compact preparation, delta prompts and predecessor contexts. Permission edits change review identity and unrelated source clauses cannot authorize them; plan copies reject occurrence authority. Missing permissions remain non-executable. One test initially expected an exception rather than the existing `to_executable()` return-None contract; its assertion was corrected to test that contract.

GREEN: **95 tests passed in 2.20s**, covering exception/linked review, exception updates, delta materialization, retained evidence, prompt budgets and existing preparation updates. Full Ruff passed. MLP1-T05 accepted; MLP1-C02 still requires durable storage acceptance.

## MLV1-07 — Durable state (MLP1-T06 / MLP1-C02)

RED: storage tests failed collection before the new models existed. Added closed candidate/event models, domain hashes, terminal-transition validation, immutable event writes and revision-fenced projections. SQLite's existing kind constraint required additive migration `0026_market_exceptions`; it preserves payload bytes, adds command uniqueness and refuses a downgrade with exception evidence. Tests use disposable databases only.

GREEN: 33 source/update/new-and-old-storage tests passed in 4.41s; after adding the durable command index, 9 storage regression tests passed in 3.72s. The final 5 new storage tests also passed. Verified rollback before commit, reopen, terminal reuse, unknown versions, modified hashes, immutable events, exact legacy bytes and cross-occurrence command uniqueness. Full Ruff passed. MLP1-C02 accepts source contracts and storage only; no production approval or execution capability is claimed.

## MLV1-08 — Exact preview and explicit decision (MLP1-T07)

RED: authorization tests failed collection before the service existed. Added strict preview/decision commands, immutable previews, server-context revision binding, exact quantity validation, command replay and explicit rejection. No inventory writes occur in this service. Both routes freeze only a valid displayed quantity; missing/invalid broken-route input never defaults.

GREEN: **21 authorization/storage tests passed in 3.49s** and full Ruff passed. Covered weak exact minimum, legal broken quantities below/above half Q0, empty/zero/off-grid/over-ceiling inputs, inventory/evaluation/evidence changes, unknown capacity, risk blocks, identical retries and rejection. Production authority collection and signal creation remain assigned to MLP1-T09; no HTTP access is exposed yet.

## MLV1-09 — Terminal lifecycle and contention (MLP1-T08)

Implemented explicit revocation, server expiry/invalidation and immutable retry receipts. Initial concurrent two-connection testing exposed SQLite read-to-write snapshot contention. The service now obtains its write fence before reading command authority and maps busy contention to an explicit conflict without treating other database failures as success. Terminal command construction preceded the first new lifecycle run; the concurrency fix followed its failing test.

GREEN: **31 tests passed in 5.94s**, including approval versus approval/rejection from separate connections, fresh-process reopening, revoke/retry, rejection/expiry/invalidation retention, backdating and early-expiry rejection. Ruff passed. Execution races remain assigned to MLP1-T10. Production correction and independent-reset continuity are completed with MLP1-T09.

## MLV1-10 — Owned runtime authority (MLP1-T09 / MLP1-C03)

Added v2 decision/calculation evidence without weakening v1 validators, shared independent-occurrence admission, persistent candidates and explicit approval-to-signal creation in one caller transaction. Schema 7 now passes reviewed activation and the production index adapter. Runtime cache identity includes candidate revisions. Pending reminders carry no quantity; send/read/completion checks fence current candidate state and consumed evidence.

GREEN: 45 combined decision/authorization/concurrency/old-and-new-runtime tests passed in 13.23s. The final 10 actual-runtime cases passed in 6.94s; Ruff passed. Verified both routes, no simulation on approval, same-clock refresh, unchanged refetch, correction invalidation, clone/rejection continuity, revoked read/send masking and completion-proof invalidation. Fixture corrections used the actual index fact-request field and alert repository; unchanged provider snapshots retain their receipt timestamp.

A broader API run reported 3 expected contract-projection failures: old assertions only allow two draft variants and versions [5,6]. These remain explicitly pending MLP1-T11/T12, where exact additive changes and old projections will be verified; they are not counted as passing. MLP1-C03 accepts per-occurrence runtime authority only. Simulation consumption, public commands, UI and replay are unfinished.

## MLV1-11 — Whole simulation consumption (MLP1-T10)

RED: both route tests exposed missing approval consumption and execution after revocation; independent-connection execution/revocation races then exposed the simulation entry's read-to-write lock upgrade. Simulation now acquires the authority fence before reads, validates the current grant and consumes candidate, signal and inventory in one transaction. Re-evaluation also retains the captured linked index source.

GREEN: **39 tests passed in 19.10s**, including 12 exception simulation cases, authorization contention and old daily/linked chains. Ruff passed after import formatting. Covered full quantity, capacity loss/recovery without resize, fault injection after inventory write with complete rollback, identical-key receipt replay, different-key duplicate rejection, revoke versus execution ordering and irreversible consumed history. No real account or broker execution is involved.
