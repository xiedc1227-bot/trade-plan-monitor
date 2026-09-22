# Single-lot History Verification — 2026-09-22

> English canonical; paired Chinese review copy. Continuation from `84c8719`. Verified single-lot increment; not restart acceptance.

## Scope and contract

The read-only single-lot reader joins strict versioned audit evidence, a unique fully consumed hash chain, the raw current row and exact deterministic position publications within one fresh application SQLite read snapshot. It returns a frozen proven history or typed unknown. It never certifies complete inventory, authenticates accepted dates, invokes the evaluator or grants replay/delivery permission. No production consumer, default switch, real provider or notification is enabled.

Both history queries use row limits with an overflow sentinel and pre-fetch text/type bounds. Default history budget is 256, hard maximum 1000, audit details 16384 UTF-8 bytes, event payload 4096. Invalid arguments/non-fresh sessions raise, invalid stored evidence stays unknown, and storage errors propagate. No guessed source dates, timestamp-based ordering or partial-history success is allowed.

## Design and independent review

Bounded implementation uses `gpt-6-astra` / `high`; independent design and final review use `gpt-6-astra` / `xhigh`. These settings do not attest the parent task's model/effort. Additional cross-model review remains skipped per the user's earlier choice.

The design review identified strict raw publication/current-row validation and query indexing as necessary. Existing event/DTO decoders alone can normalize corrupt input. Clock reversal, delayed registration and separate close/audit clock reads are valid existing behaviors, so dates and times are not used to order the chain. Increasing publication sequences allow unrelated global gaps. An aggregate-ID collision with other event types remains conservatively unknown.

The seven-day monitor replay policy filters client replay rather than deleting publications. The reader therefore examines persisted evidence without a time cutoff. Physically missing publications cannot be replaced by current state or audits alone. This remains consistency proof under the local database trust boundary, not tamper-proof authentication against a writer able to rewrite all corresponding records.

## Index migration and rollback

Source migration `0020_lot_history_indexes` adds non-unique audit `(entity_type, entity_id)` and monitor `(aggregate_id, sequence)` indexes. It does not modify historical records or identities. Downgrade removes only these indexes. Each adds storage and write-maintenance cost; the intended gain is indexed target lookup without unrelated-history scans, not a claimed production latency target. Only isolated temporary databases are migrated in verification. Deployment still needs its own backup, migration window and approval; SQLite index creation is not a zero-lock live operation.

## Executed verification

Official-source checks: the project pins SQLAlchemy 2.0.52; the 2.0 documentation confirms the existing explicit-BEGIN engine-hook pattern used by the configured factory ([transaction control](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#enabling-non-legacy-sqlite-transactional-modes-with-the-sqlite3-or-aiosqlite-driver)). SQLite documents byte versus text/NUL length semantics ([scalar functions](https://www.sqlite.org/lang_corefunc.html#length)) and scoped index lookup/temporary-sort diagnostics ([query plans](https://www.sqlite.org/eqp.html)). No dependency upgrade or engine-hook change was made.

The index tests first failed in 4 cases because the indexes were absent and both queries scanned existing data. After the additive migration, the new tests plus the full existing SQLite repository suite passed (110 passed, 11.38 seconds). A subsequent explicit before/after query-plan assertion passed in the 4-test focused run (1.03 seconds). On the same populated fixture, both queries change from `SCAN` to scoped `SEARCH` using their new indexes, with identical results and no temporary sort. This is query-plan evidence, not a runtime latency benchmark.

The existing 12 latest-head migration assertions now expect the new revision. The existing monitor-index preservation check still compares every prior index, while separately asserting the exact added non-unique index. No prior migration was edited. A fresh-context index reviewer found no actionable issue and independently reran both suites (110 passed, 10.33 seconds).

The reader's first RED run failed collection because the module did not exist. The initial implementation passed 84 cases. Further cases and source review replaced a global aggregate scan with an indexed descending one-row maximum lookup, and replaced text-driver decoding with bounded binary projections followed by strict UTF-8 decoding. A proposed long-ID reduction fixture hit the existing 36-character mutation lookup limit; coverage now tests the committed 64-character buy separately from ordinary-ID custom-board-lot reduction, without changing admission. Before the ownership fix below, the 236-line reader passed 104 integration cases, including individually valid but conflicting branches/orphans, deleted middle publication, exact payload limits, mistyped numeric cells, malformed UTF-8 in TEXT/BLOB, non-monotonic dates/clocks and concurrent committed WAL writes.

| Command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_lot_history_indexes.py tests/integration/test_sqlite_repositories.py -q` | 110 passed; final independent index review 10.33 seconds |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_position_lot_history.py -q` | Post-ownership-fix: 108 passed; 11.43 seconds |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | Passed on frozen source/tests |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI snapshot and frontend types remain current |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | Final frozen-source functional regression: 3560 passed, 4 pre-existing failures, 1 existing skip, 4 live deselected, 1 existing warning; 495.89 seconds |

Final review found an actionable P1 transaction-ownership defect: a new Session bound to another transaction's Connection could return proven evidence for an uncommitted buy. This was reproduced for direct, model-routed and table-routed connection bindings; all 3 new regression cases failed before the fix. The contract now explicitly requires one engine-bound, application-configured SQLite snapshot and rejection without touching the caller's transaction. This matches SQLAlchemy's documented ability to [join an external transaction](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites) and its [bind resolution rules](https://docs.sqlalchemy.org/en/20/orm/session_api.html#sqlalchemy.orm.Session.get_bind). The initial broad regression was interrupted for the fix and is not counted as completed verification.

The fix requires a SQLite Engine as the Session bind and verifies both mapper and table-clause bindings against that same engine for all four proof tables before any SQL. The 3 connection regressions and an additional different-database routing regression now pass; rejection preserves the caller's uncommitted transaction and subsequent rollback. Review cycle 2 found no remaining actionable issue and independently reran 108 cases in 11.87 seconds. All 112 new tests are included in the final functional regression, with no new failure observed. Full acceptance remains blocked by the broader unfinished work and the 4 baseline failures, which are not waived.

Those failures match the preceding decoder report: canonical index-head update time (10:36 versus expected 10:38), pending-close index-error reference health (LIVE versus expected BLOCKED), provider TIMEOUT versus TRANSIENT, and the R14 mock request rejected by the temperature guard before its fake transport. The unchanged heavy backtest file was not rerun; earlier full-run evidence remains in the runtime-recovery increments report. The existing skip is the Windows/POSIX ownership boundary; the existing warning is Starlette/httpx deprecation. No assertion was weakened; only superseded schema-head/index expectations changed, and no new skip was introduced.

Bilingual heading/technical-literal parity and whitespace checks passed. A scoped high-confidence secret-pattern scan across all 12 changed files found no matches; this is not a comprehensive credential audit. Verification used temporary local databases and no real provider or notification channel. The indexes and reader are saved as separate local increments for independent review/rollback.

## Remaining work

Adjacent-code inspection found that `LegacyCloseRecoveryReader` still has the earlier fresh-Session-only guard. Its owned-engine binding contract needs a separate implementation/reproduction check before composition; it was not changed or certified by this increment. The single-lot reader's fix must not be generalized into a claim that all recovery readers have the same protection.

Per-lot proof does not establish complete portfolio coverage or make non-monotonic accepted effective dates safe to replay. Opening-balance and confirmation history, inventory completeness, source-effective risk state, ordered historical execution, final send admission and process-restart acceptance remain prerequisites. RR009/C2 and the wider anytime-restart goal are incomplete. No push, merge, live migration or deployment is included.
