# S3 regression fixture alignment

> Canonical English. Paired Chinese review copy: `2026-09-27-s3-regression-fixture-alignment.zh-CN.md`.

## SFA-01 Scope and baseline

Status: **test-only alignment implemented / targeted verification passed / independent code review passed / six-file local commit authorized**.

The aggregate offline checkpoint at source `453cc0c`, recorded by documentation commit `e9c6ac5` in [the regression report](2026-09-27-s3-offline-regression.md), had **18 failed, 4778 passed, 1 skipped, 4 deselected, 1 warning**. This slice aligns the four affected test files with existing supported production contracts. It does not change production behavior or waive that aggregate failure.

The author reproduced all 18 failures before editing. Runs used the shared working tree based on `3c22bff`; another writer's SDK-boundary source edits were present, so these are not results for an isolated clean committed revision. This author changed only the four files below and this paired report. `production.py`, providers, controller, shared fixtures, scripts, and the separate startup-minute-coverage tests were not edited by this slice.

All runs used temporary SQLite, fake SDK/HTTP, and controlled clocks. No real service, real notification channel, user database, push, or deployment was used. No skip/xfail or production safety relaxation was introduced.

## SFA-02 Changes and preserved assertions

| File | Fixture alignment | Preserved behavior |
| --- | --- | --- |
| `tests/integration/test_position_production_composition.py` | Freeze composition `SystemClock.now()` at `_FIXED_NOW` and provide cancellable sleeping. After schema upgrade and before any active plan, use the real `RuntimeLivenessRepository.initialize_empty(_FIXED_NOW)`. Assert the existing sample remains Schema 1, MANUAL, `max_qty=200`. | The original three failing tests retain calendar authority, idempotent create/closure replay, maximum quantity, missing active plan, T+1, remaining quantity, stale revision, and recovery-audit assertions. No forced health or certification bypass. |
| `tests/integration/test_r13_channel_acceptance.py` | Supply real `CurrentDeliveryAdmission` with the same sessions and `pipeline.evaluations._runtime_generation`; leave the shared pipeline fixture unchanged. | Keep original DELIVERED, event identity, result hash, quantity, and console/webhook envelope assertions. A second dispatch produces no duplicate attempt. Do not require every delivery receipt to become ELIGIBLE: actionable delivery is checked per attempt. |
| `tests/unit/test_r14_bounded_acceptance.py` | Add required `temperature: 0` to the otherwise approved fake AI payload. | The fake HTTP 503 still consumes exactly one physical attempt, and exhausted-budget/unapproved-model rejection remains. The real harness guard is unchanged. |
| `tests/unit/test_r17_failure_diagnostics.py` | Complete the two fake Pipeline interfaces with non-None `_stock_semantics` and `recovery_issues()` returning `()`. | Retain all eight request-error category/retry/recovery cases and all three untrusted-exception redaction cases, including SECRET non-disclosure. |

An AST comparison against the original four files retained all **157 original assert statements**: 52 position, 21 R13, 51 R14, and 33 R17. All **29 original test functions** remain; parameterization produced 46 baseline cases. No assertion was removed or changed to make the fixture pass. This structural check supplements the executed tests; it is not a substitute for their behavioral evidence.

## SFA-03 Negative controls

| ID | Observed protection |
| --- | --- |
| SFA-N01 | Omit liveness initialization: health remains `BLOCKED` with `LEGACY_PLANS_REQUIRE_REVIEW`, GET health returns 200, position POST returns 409, liveness stays absent, and complete position/idempotency/audit row snapshots remain unchanged. |
| SFA-N02 | Before delivery, each BUY/SELL/RISK_ALERT fixture has exactly one persisted event and one explicit evaluation ledger row, with a `HOLD / RECOVERY_REQUIRED` receipt. The old dispatcher without admission produces zero attempts. Real admission then delivers once; another dispatch remains empty and persisted attempt count stays one. |
| SFA-N03 | After producing the same three alert kinds, delete the persisted `PositionInventoryConfirmation` before dispatch. Real admission keeps the receipt HOLD and produces zero attempts; the original event and evaluation ledger each remain present once. |
| SFA-N04 | Missing and nonzero temperature are both rejected before the inner MockTransport; sent-request count and `totalAttempts` remain zero. |
| SFA-N05 | With `_stock_semantics=None`, reference refresh never enters the fake Pipeline and produces no stage error, retry deadline, or failure callback. |

The final suite adds seven parameterized cases: one missing-liveness case, three inventory-revocation cases, two temperature cases, and one missing-STOCK-binding case. The no-admission and duplicate-delivery checks strengthen the existing R13 cases. These negative controls pass against existing safety behavior; they are not claimed as new production RED-to-GREEN fixes.

## SFA-04 Executed verification

The author ran the same four-file command before and after fixture edits:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/integration/test_position_production_composition.py tests/integration/test_r13_channel_acceptance.py tests/unit/test_r14_bounded_acceptance.py tests/unit/test_r17_failure_diagnostics.py --tb=short
```

| Stage | Actual result |
| --- | --- |
| Initial reproduction | **18 failed, 28 passed, 1 warning**, 14.51 seconds, exit 1. Failures: position 3, R13 3, R14 1, R17 11. |
| Initial fixture alignment plus first controls | **49 passed, 1 warning**, 14.38 seconds, exit 0. |
| Final four-file run including all controls | **53 passed, 1 warning**, 22.47 seconds, exit 0. |

Adjacent verification command:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/integration/test_runtime_liveness.py tests/integration/test_runtime_plan_expiry.py tests/integration/test_position_lot_recovery_audit.py tests/integration/test_delivery_admission.py tests/integration/test_recovery_alert_eligibility.py tests/integration/test_notification_delivery.py tests/integration/test_explicit_runtime_production.py tests/integration/test_r14_offline_wiring.py tests/unit/test_r17_bounded_acceptance.py --tb=short
```

Adjacent result: **172 passed, 1 warning**, 89.71 seconds, exit 0.

```powershell
.venv/Scripts/python.exe -m ruff check tests/integration/test_position_production_composition.py tests/integration/test_r13_channel_acceptance.py tests/unit/test_r14_bounded_acceptance.py tests/unit/test_r17_failure_diagnostics.py
git diff --check
```

Ruff and diff whitespace checks passed after correcting one import-order issue in the edited R13 file. The warning in pytest was the existing Starlette/httpx TestClient deprecation. Counts from successive or overlapping runs must not be added together.

The coordinator separately reported an Astra read-only in-process feasibility run of 46 passing original cases and additional negative-control observations. Those supported the diagnosis but are not the author's executed results above and do not replace formal review of these on-disk changes.

The coordinator subsequently reported independent Sol/xhigh final approval: no P1/P2 in the four test files or paired report. The reviewer independently ran the four-file suite: **53 passed, 1 warning**, 22.42 seconds. A separate same-process check of clock-fixture method identity restoration passed **1 test**. Reviewer Ruff and diff checks passed; all four reviewed file hashes remained stable during review. The reviewer confirmed all original **157 asserts / 29 test functions** were retained, with the final files containing **193 asserts / 33 test functions / 53 cases**. These independent observations are separate from the author's runs and must not be added to their counts. Review used HEAD `3c22bff` with another writer's uncommitted source changes; it is not a clean-revision full-suite pass.

## SFA-05 Remaining gates

Independent code review passed and the coordinator authorized a local commit containing exactly these four test files and two report files. A new aggregate offline run on the final integrated revision is still required; the earlier failed aggregate checkpoint is not reclassified as passing by these focused results.

The separate startup-minute-coverage RED cases, SDK-boundary repair, minute-owner implementation, unified scheduler, and broader S3-09/C1/C3/business-step-3 acceptance remain outside this test-fixture alignment. No claim is made that these gates are complete.
