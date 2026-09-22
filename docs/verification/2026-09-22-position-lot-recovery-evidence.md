# Position-lot Recovery Evidence Verification — 2026-09-22

> English canonical; paired Chinese review copy. Continuation from `e7e5ab9`. RR009 prerequisite only, not historical reconstruction or restart acceptance.

## Scope and decision

The existing reduction command accepts a trade date but its lot audit retained only bucket, quantity and symbol. Later reconstruction cannot reliably substitute the audit write date for a delayed registration's accepted trade date. The bounded increment retains a versioned date and full before/after lot snapshots inside the existing audit details, without changing lot hashes, event identities, API fields or trading rules. Historical rows are not rewritten. Opening balances, inventory-confirmation history, complete-history proof and risk source-effective dates remain separate work.

Independent design inspection rejected directly replaying old dates through the current context builder: it reads current positions/risk/head. Risk progression also uses the persisted write date, and decision heads reject backward advancement. This increment supplies one missing future input, not a workaround for those restrictions.

## Verification and review

Implementation uses `gpt-6-astra` / `high`; independent design and adversarial review use `gpt-6-astra` / `xhigh`. These settings do not attest the parent task's model/effort. Additional cross-model review remains skipped per the user's earlier choice. The independent contract review examined both language versions and the repository/web/idempotency paths and found no actionable issue in this writer-only scope.

Before production edits, the new focused tests produced 4 expected failures for delayed buys, partial reductions, full reductions and repeated partial reductions because the envelope was absent; 4 rollback/legacy-preservation cases already passed. Expected snapshots pin the nine fields explicitly, and hashes are independently recomputed using the unchanged camelCase lot-hash representation rather than the implementation helper. The minimal implementation adds 9 production lines; the original 8 cases then passed.

A subsequent UTC-success test proposal was incorrect: the existing monitor-event timestamp contract rejects a UTC write clock. That trial produced 4 failures and 126 passes, and was not accepted as a production regression. The tests now explicitly verify unchanged timezone rejection and complete rollback for buys, partial reductions and full reductions; no clock or admission logic was changed. An early broad run was interrupted when this test correction was identified and is not counted as completed verification. The final new file has 11 tests; existing HTTP buy/closure replay tests additionally check preserved evidence without duplicate audits.

| Command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_sqlite_repositories.py tests/integration/test_position_inventory.py tests/integration/test_position_production_composition.py tests/integration/test_position_lot_recovery_audit.py -q` | 129 passed, 1 existing warning; 14.77 seconds |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | Passed on final source/tests |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI snapshot and frontend types remain current |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | Frozen-source functional regression: 3341 passed, 4 pre-existing failures, 1 existing skip, 4 live deselected, 1 existing warning; 455.56 seconds |

The fresh-context final implementation reviewer found no actionable issue in the scoped diff and confirmed that the corrected UTC rejection regression matches the existing timestamp contract. The reviewer did not rerun tests. All 11 new cases are included in the final functional regression; no new functional failure was observed. The full acceptance gate is not green.

The 4 failures match the preceding close-evidence report: canonical index-head update time (10:36 versus expected 10:38), pending-close index-error reference health (LIVE versus expected BLOCKED), provider TIMEOUT versus TRANSIENT, and the R14 mock request rejected by the temperature guard before its fake transport. The unchanged heavy backtest file was not rerun; earlier full-run evidence remains in the runtime-recovery increments report. The existing skip is the Windows/POSIX ownership boundary, and the existing warning is the Starlette/httpx deprecation. No existing assertion was weakened and no new skip was introduced.

Bilingual heading/technical-literal parity and whitespace checks passed. A scoped high-confidence secret-pattern scan across the 9 changed files found no matches; this is not a comprehensive credential audit. Tests used isolated local state and no real providers or notification channels.

## Security and compatibility boundaries

Only already-stored local lot fields are copied into local audit history for the approved recovery purpose. No credentials, free-form request bodies, external logging or new data category is introduced. This grows historical retention of existing position data; the increment adds no pruning, export, backup or remote-transmission behavior. Existing hashes cover lot state, not the newly retained command date. Readers must not treat them as a signature of that date, complete inventory coverage, independent exchange-calendar proof or permission to replay/send.

The existing transaction, repository validation and HTTP idempotency remain authoritative. There is no schema migration, dependency change, new reader, recovery integration, production default switch or real service call. Rolling back this writer addition stops new enriched audits; already committed enriched rows remain readable as ordinary existing audits and must not be stripped or rehashed.

## Remaining work

RR009 and C2 remain open. A strict bounded evidence decoder, per-lot and inventory continuity, legacy missing-evidence policy, opening-balance/confirmation history, risk source-effective semantics and safe ordered execution are still needed. Broader lifecycle/status/UI integration, final send admission and process-restart acceptance remain prerequisites to rollout. The preceding 4 baseline functional failures are not waived. No push, merge or deployment is included.
