# Durable Close Evidence Verification — 2026-09-21

> English canonical; paired Chinese review copy. Continuation from `c1e1b4a`; isolated RR009 evidence reading, not historical replay or rollout acceptance.

## Scope and boundaries

The first separate increment extracts existing activation event/audit-chain and monitor high-water checks into a shared state module. The alert-origin reader retains its original publication/alert interval and source-cutoff checks. This prevents the new close reader from maintaining a second copy of activation proof. Refactor commit: `16a5008`.

The next increment derives active legacy scope and discovers missing official-close candidates from one fresh SQLite snapshot. It requires canonical plan identity, activation-chain agreement and exact ledger/result/publication attribution. It does not need an alert to prove an occurrence. Unknown or corrupted evidence is never converted into absence or a send permit. Stored fields are bounded before parsing; parameterized queries and no-autoflush ownership prevent unintended writes. No production startup/evaluator/dispatcher/default, migration, credential or external integration changes are included.

An otherwise absent claim/result also requires a bounded orphan-publication check. The 1000-row limit can be reached during normal long-running intraday use; unknown is intentional at that boundary, not evidence that recovery is complete. Durable direct provenance remains a prerequisite for broader production progress. Complete occurrence attribution still does not reconstruct historical inventory, risk, settlement or cross-window causal state.

## Test-first and review evidence

Implementation uses `gpt-6-astra` / `high`; independent design/extraction review uses `gpt-6-astra` / `xhigh`. These settings do not attest the parent model/effort. Extra cross-model review remains skipped per the user's earlier choice. The existing origin suite passed 45 cases before and after extraction. Independent extraction review found no substantive regression; its documentation note was applied to make the owned no-autoflush snapshot and prior high-water validation preconditions explicit.

Reader test-first evidence began with 27 failures before the module existed. Two additional failing compatibility cases exposed rejection of Beijing symbols and an unnecessary UUIDv4 restriction; the implementation now uses the repository's canonical symbol and UUID contracts. Four further failing storage-corruption cases exposed SQLite text/real calendar coercion and BLOB payload handling. The fixes require actual integer calendar storage with values 0/1 and string payloads before encoding; they do not broadly swallow programming errors.

The final focused suite contains 47 new reader cases, 45 existing origin-proof cases and 42 discovery cases: 134 passed. Coverage includes coherent concurrent snapshots, dirty-session rejection without flush, inactive/explicit scope, same-hash reactivation, missing/oversized/corrupt evidence, orphan-history limits and occurrence-only WAIT/BLOCKED_DATA results. A fresh-context final reviewer using `gpt-6-astra` / `xhigh` examined the frozen fixes and found no additional actionable findings. No extra cross-model review was performed.

## Executed verification

| Command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_recovery_alert_provenance.py -q` | Before and after extraction: 45 passed |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_close_recovery_evidence.py tests/integration/test_recovery_alert_provenance.py tests/unit/test_missed_close_recovery.py -q` | 134 passed, 1 existing warning; 15.25 seconds |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | Passed |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI snapshot and generated frontend types are current |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | Frozen-source functional regression: 3330 passed, 4 pre-existing failures, 1 existing skip, 4 live deselected, 1 existing warning; 428.10 seconds |

All 47 new cases are included in the final functional run. Its 4 failures exactly match the preceding discovery report: canonical index-head update time (10:36 versus expected 10:38), pending-close index-error reference health (LIVE versus expected BLOCKED), provider TIMEOUT versus TRANSIENT, and the R14 mock payload rejected by the temperature guard before its fake transport. No new functional failure was observed; the full acceptance gate is not green. The unchanged heavy backtest file was not rerun; its earlier full-run evidence remains in the runtime-recovery increments report. The existing skip is the Windows/POSIX ownership boundary, and the existing warning is the Starlette/httpx deprecation. An earlier run started before the final storage fixes was interrupted and is not counted as a completed verification.

Bilingual heading and technical-literal parity checks passed for the specification, task list and this report. Whitespace checks passed. A scoped high-confidence secret-pattern scan across all 10 changed files since the starting commit found no matches; this is not a comprehensive credential audit. No assertion was weakened, no new skip was introduced and no live provider or real delivery was exercised.

## Remaining work

RR009 remains open for historical-state reconstruction and safe chronological execution, including later committed results after earlier holes and source-day versus recovery-write-time semantics. Direct provenance for histories beyond bounded proof, current-risk/inventory/barrier reconstruction, final per-channel send admission, lifecycle/status/UI integration and process-restart acceptance remain open. The 4 preceding baseline functional failures are not waived. No push, merge, production migration, deployment or default switch is included.
