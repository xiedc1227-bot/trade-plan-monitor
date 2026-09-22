# Recovery Reader Transaction Ownership — 2026-09-22

> Canonical English; paired Chinese review copy. Continuation from `2536856`; isolated safety correction, not anytime-restart acceptance.

## Scope and root cause

`LegacyCloseRecoveryReader` and `LegacyAlertOriginReader` checked fresh Session state but not its underlying binding. A fresh Session can borrow another writer's Connection and read that writer's uncommitted evidence. The single-lot reader already rejected this configuration. The shared `require_owned_recovery_session` preflight now applies that policy to all three readers without changing evidence interpretation, hashes, identities, schema or production defaults.

Require a fresh session, a SQLite Engine default bind, and identical mapper/table-clause Engine bindings for every proof model. Reject invalid factories before context entry or SQL, outside evidence-validation exception handling. Rejection does not flush, commit, roll back or close caller-owned state. Ordinary storage errors still propagate, and invalid stored content still follows each reader's existing unknown rules. The application's file-backed engine and explicit-BEGIN hooks remain prerequisites; this is not certification of arbitrary engines, malicious Session overrides, or database authenticity.

SQLAlchemy documents [external transaction participation](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites) and [mapper/clause bind resolution](https://docs.sqlalchemy.org/en/20/orm/session_api.html#sqlalchemy.orm.Session.get_bind). These support the binding boundary, not a claim that a fresh Session alone certifies committed data. Dependencies and engine hooks are unchanged.

## Test-first evidence

The independent test author used `gpt-6-astra` / `high`. Independent proposal and final source/test reviews used `gpt-6-astra` / `xhigh`; those settings do not attest the parent task's model/effort. Additional cross-model review remains skipped per the user's earlier choice.

The reproduction deletes and commits the close/alert evidence, then restores it inside an uncommitted writer transaction. An ordinary independent reader correctly sees `ABSENT` or `UNKNOWN`, while both original readers given a new Connection-bound Session incorrectly returned `PROVEN`. The targeted RED run failed both cases. The complete new suite was 46 failed and 10 passed before the fix, then 56 passed after it (7.80 seconds).

Coverage includes direct active/idle Connections, every proof model's mapper and table routes, two Engine objects pointing to the same database file, unbound sessions, active/pending/dirty caller state, and valid same-engine routing. Rejection is checked for zero SQL and zero session lifecycle side effects. The realistic uncommitted-evidence cases additionally prove the caller can commit successfully afterward. Existing single-lot regressions retain external-transaction rollback and different-database coverage. Existing concurrent-commit tests retain coherent snapshot behavior.

## Executed verification

| Command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_close_recovery_session_ownership.py -q` | 56 passed; 7.80 seconds |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_close_recovery_evidence.py tests/integration/test_recovery_alert_provenance.py tests/integration/test_position_lot_history.py tests/integration/test_close_recovery_session_ownership.py -q` | 256 passed, 1 existing warning; 36.09 seconds |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | Passed after correcting import ordering and one line length |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI snapshot and frontend types remain current |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | 3616 passed, 4 pre-existing failures, 1 existing skip, 4 live deselected, 1 existing warning; 501.94 seconds |

Independent proposal and final code review found no actionable issue under the stated factory contract. No real provider, notification channel, live database or schema migration was used. The final functional run includes all 56 new tests, with no new failure observed. The four baseline failures remain: canonical index-head update time (10:36 versus 10:38), pending-close index-error reference health (LIVE versus BLOCKED), provider TIMEOUT versus TRANSIENT, and the R14 mock request missing the required temperature and being rejected before its fake transport. They are not waived or fixed in this increment. The unchanged heavy backtest file was not rerun; this is not a full-suite or final acceptance pass. The existing skip is the Windows/POSIX ownership boundary, and the warning is Starlette/httpx deprecation.

Paired heading/technical-literal checks passed after normalizing intentional counterpart-language links; staged whitespace checks passed. A scoped high-confidence secret-pattern scan across all 11 changed files found no matches, not a comprehensive credential audit. No tests were skipped, deleted or weakened by this change. The correction is saved as one local increment; remote synchronization is separate.

## Remaining work

The identified transaction-binding gap is closed for these three readers. RR009/C2 remain incomplete: opening-balance and inventory-confirmation history, complete historical inventory, source-effective risk semantics, proof budgets and safe chronological execution still need implementation. Final per-channel admission, lifecycle/status/UI integration and actual process-restart acceptance remain separate gates. No push, merge, production default switch or deployment is included.

A separate read-only `gpt-6-astra` / `xhigh` investigation scoped the next writer increment: preserve the complete confirmation before/after row, any newly created opening balance, the accepted opening-balance reduction date and board lot, and inventory-revision/confirmation synchronization for lot buys, lot reductions and opening-balance reductions. The current confirmation row is overwritten; automatic synchronization changes quantities without preserving each intermediate state. Adding only reduction dates would therefore remain insufficient. Existing strict lot-evidence version 1 must not gain unexpected fields; use a distinct inventory audit scope for additional inventory facts. Keep all evidence in the existing transaction and preserve admission, old hashes/events and old audit bytes. This is a next-step proposal, not implemented history or an approved replay policy. Historical completeness cutoffs, late/non-monotonic registration and legacy missing evidence still require explicit contracts before consumption.
