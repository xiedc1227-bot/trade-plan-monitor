# Opening-Balance Reduction Decoding — 2026-09-22

> Canonical English; paired Chinese review copy. Continuation from `8d14bb6` on the existing `codex/consolidate-r19-r32` branch. No branch creation or switch.

## Scope and contract

The pure `decode_opening_balance_mutation` validates one opening-reduction audit, not a history. Results are frozen `ValidatedOpeningMutation` or `UnknownOpeningMutation` with distinct missing, unsupported-version and invalid-content reasons. Original write/closure strings survive validation; dates are typed immutable dates. The decoder recomputes existing hashes through `OpeningBalanceRecord` JSON, preserving the difference between stored UTC `+00:00` and DTO `Z`. It checks fixed fields, metadata binding, positive operation quantity/board lot, exact remaining/revision arithmetic and coherent closure state.

The details budget is explicitly 16384 UTF-8 bytes for this fixed two-snapshot record, with character/byte guards before parsing. Opening/entity IDs are bounded to 36 characters by existing reduction lookup semantics; confirmation IDs have a conservative 128-character reader bound. Timestamps are bounded to 64 characters, and hashes are exactly 64 lowercase hexadecimal characters. Duplicate keys, nonstandard numeric constants, coercion, malformed Unicode, excess nesting and extra/missing fields do not become valid evidence. The parser reuses existing strict primitives without altering the lot decoder or adding a generic framework/dependency.

These are local reader bounds, not new writer restrictions or future confirmation member-list budgets. Same-day sellability, non-UUID IDs, odd original/remaining quantities, changing board lots and late/out-of-order source dates remain supported. No global quantity/revision formula or write/closure/effective chronology is invented. SHA-256 checks are internal consistency checks, not authentication against a database writer. No database access, mutation, migration, provider call, notification, production consumer or replay permission is introduced.

## Test-first and independent review

The main task wrote adversarial unit tests before the module existed; a separate `gpt-6-astra` / `high` agent wrote actual-writer/database-reopen tests independently. Both initial runs failed with the expected missing-module collection error. Implementation then passed 71 unit cases and 10 integration cases. Combining the suites exposed duplicate test-module basenames under the existing pytest importer; the integration file was renamed to `test_opening_balance_evidence_roundtrip.py`, without changing test configuration or skipping coverage.

Fresh-context design and final reviews used `gpt-6-astra` / `xhigh`; these settings do not attest the parent task's model/effort. Design review clarified the opening ID lookup bound and the exact zero-balance/closure equivalence; both were incorporated before implementation. Final review found no required issue. The reviewer independently checked 1000 generated writer-shaped mutations with varying board lots, revisions and timezone offsets, and 357 hostile substitutions without escaped exceptions. Extra cross-model review remains skipped per the user's earlier choice.

Unit tests cover immutable outputs, input preservation, strict metadata, malformed JSON, exact UTF-8 budget, legacy/version distinctions, invariants even after hashes are recomputed, and raw UTC versus DTO hashing. Integration tests exercise real persisted partial/full reductions, custom IDs, variable board lots, same-day sellability, non-monotonic dates, engine recreation, untouched legacy rows and wrong scopes. Persisted-state comparisons confirm decoding does not alter storage; engine recreation is not actual process-restart acceptance.

## Executed verification

| Command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/unit/test_opening_balance_evidence.py -q --tb=short` | 71 passed; 0.41 seconds |
| Independent real-writer/reopen integration selection | 10 passed, 1 existing warning; 2.29 seconds |
| `.\.venv\Scripts\python.exe -m pytest tests/unit/test_opening_balance_evidence.py tests/integration/test_opening_balance_evidence_roundtrip.py tests/unit/test_position_lot_evidence.py tests/integration/test_position_lot_history.py tests/integration/test_position_inventory_recovery_audit.py tests/integration/test_position_inventory_recovery_transactions.py -q --tb=short` | 328 passed, 1 existing warning; 17.73 seconds |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | Passed after formatting the new source/unit test file |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI snapshot and frontend types remain current |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | 3734 passed, 4 pre-existing failures, 1 existing skip, 4 live deselected, 1 existing warning; 478.00 seconds |

The final regression includes all 81 new cases and no new failure. The four baseline failures remain unchanged: index-head update time (10:36 versus 10:38), pending-close index-error reference health (LIVE versus BLOCKED), provider TIMEOUT versus TRANSIENT, and the R14 mock request missing required temperature and being rejected before its fake transport. They are neither fixed nor waived here. The unchanged heavy backtest file and live-provider tests are outside this run; no full-suite or final acceptance pass is claimed. The existing skip is the Windows/POSIX ownership boundary; the warning is Starlette/httpx deprecation.

Paired heading/technical-literal parity and staged whitespace checks passed. A scoped high-confidence secret-pattern scan across all 9 changed files found no matches, not a comprehensive credential audit. Existing source/tests are untouched; no test is weakened, removed or newly skipped. The increment is saved locally on the same branch, without push or deployment.

## Remaining work

This closes only opening-reduction single-record decoding. Confirmation and automatic inventory-change receipt decoders still need explicit outer/nested budgets and field-level contracts. Durable source/chain/current-row/publication checks and a historical completeness policy remain separate. Opening creation is embedded in confirmation evidence and has no standalone root publication; do not blindly copy single-lot proof rules. Risk source-effective dates, safe chronological execution, delivery admission, lifecycle/status/UI integration and actual process-restart acceptance still block RR009/C2 and stage-3 completion. No push, merge, deployment or production switch is included.
