# Missing-close Discovery Verification — 2026-09-21

> English canonical; paired Chinese review copy. Continuation from `63e8209`. RR009 discovery slice only, not rollout acceptance.

## Scope and boundaries

The new pure scanner discovers legacy official-close candidates even when no pending record was created before shutdown. It separates actual activation, historical policy, exchange calendar, absence and attributed committed occurrences. Calls are bounded to 32 calendar days and expose continuation; a completed window is not a complete recovery barrier. Unknown evidence and possible later-after-hole history remain explicit. Source code for production startup, evaluators, dispatch, database schema and UI is unchanged. There are no real provider calls, notifications or production database operations.

Design inspection found why this increment must not directly replay historical dates through the existing evaluator: the legacy ledger has no activation revision; the duplicate shortcut accepts a hash-only claim; the context builder reads current inventory/risk; decision heads cannot move backward; and settlement progression compares a historical date with risk state time written at recovery evaluation. Sorted date calls alone would not establish correct causal state. Those are requirements for the next historical-evidence/reconstruction increment, not waived checks.

## Test-first and review evidence

The implementation child runs `gpt-6-astra` / `high`; independent design and fresh-context implementation reviewers run `gpt-6-astra` / `xhigh`. These settings do not attest the parent model/effort. Extra cross-model review is skipped per the user's earlier choice. Initial focused RED failed collection because the new module did not exist. The first implementation run passed 26 cases with 1 test-fixture failure: the existing result model correctly rejected a forged digest before the scanner could see it. The deliberate-corruption test now constructs invalid evidence explicitly and verifies scanner revalidation. The frozen focused set has 42 passing cases. Final independent review found no actionable issue after examining source, tests, paired specification and dependent validators within this discovery-only scope; it is not full RR009 or rollout approval.

## Executed verification

| Command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/unit/test_missed_close_recovery.py -q` | Initial RED: 1 collection error, missing new module; final focused run: 42 passed in 0.68 seconds |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | Passed |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI snapshot and frontend types are current |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | Frozen-source functional regression: 3283 passed, 4 pre-existing failures, 1 existing skip, 4 live deselected, 1 existing warning; 457.04 seconds |

All 42 new cases are included in that final functional run. The 4 failures exactly match the preceding report: canonical index-head update time, pending-close index-error reference health, provider TIMEOUT versus TRANSIENT, and the R14 mock payload rejected by the temperature guard before its fake transport. No new functional failure was observed; the full acceptance gate is not green. The unchanged heavy backtest file was not rerun; its earlier full-run evidence remains in the runtime-recovery increments report. The existing skip is the Windows/POSIX ownership boundary, and the existing warning is the Starlette/httpx deprecation. No assertion was weakened and no new skip was introduced.

All 3 document pairs have matching heading counts and normalized inline technical literals. A high-confidence secret-pattern scan of the 8 changed files found no match; this is scoped hygiene, not a credential audit. Whitespace checks passed.

## Remaining work

RR009 remains incomplete. Implement durable completion/activation attribution and authoritative historical state, handle cross-window causal continuity and later results after holes, then integrate ordered execution with activation/generation fences. This scanner neither proves database provenance nor grants replay or delivery permission. RR011–RR013 final current-authority and send gates, lifecycle/status/UI integration and process-restart acceptance also remain open. The 4 existing functional failures from the preceding report are not waived. No push, merge, migration, deployment or production default switch is part of this continuation.
