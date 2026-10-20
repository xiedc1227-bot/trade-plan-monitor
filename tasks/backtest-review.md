# Backtest review implementation tasks

## BT-R01. Contract and index

- [x] Freeze paired [BR01–BR06](../docs/specifications/backtesting/SPEC-backtest-review.md) and component boundaries before code.
- [x] Add derived metadata, same-transaction staging and explicit bounded old-run maintenance. Verify publication isolation, reopen and deletion/hash behavior.
- [x] Add strict context API, signed relation pagination and regenerated clients. Verify selector validation, missing identities and expiry.

Dependencies: existing completed-result store. Verify with `.venv/Scripts/python -m pytest tests/integration/test_backtest_review.py` and contract generation check. Preserve unrelated cost changes. Existing `tasks/plan.md` and `tasks/todo.md` belong to other work and remain in place; this feature uses this dedicated task list.

## BT-R02. Readable results and navigation

- [x] Compact fills, mode-aware overview, separate reasons/provenance and exact diagnostic/event links.
- [x] URL-driven evidence state, cancellation, related pages, focus and visited-cursor previous navigation.

Dependencies: BT-R01. Verify focused Vitest suites, type-check and build. Dedicated components/composable follow BR04. No per-fill PnL derivation.

## BT-R03. Acceptance

- [x] Verify published backend and UI together in pinned Chrome, keyboard/history, missing evidence and mobile/desktop layouts.
- [x] Run relevant regressions, inspect final diff and record paired verification report with measured results and remaining limits.

Dependencies: BT-R02. Acceptance: BR-A01–BR-A04. Chart/filter expansion in BR06 is outside this release.

Verification: [BR-V01–BR-V04](../docs/verification/2026-10-20-backtest-review.md).
