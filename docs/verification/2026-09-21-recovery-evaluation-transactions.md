# Recovery Evaluation Transaction Verification — 2026-09-21

> English canonical; paired Chinese review copy. Continuation from `6dff7ae`; not complete RR012/RR013 or deployment acceptance.

## Scope and boundaries

The prior two commits `964fde2` and `6dff7ae` were pushed to `origin/codex/consolidate-r19-r32`; a remote read confirmed head `6dff7ae591c2dae33683cb3c447fd6bc2125f4f9` before this increment. This increment connects the existing initial-HOLD outbox helper to the two evaluator services only through a strict opt-in `recovery_delivery` constructor flag. Production factories/composition and notification dispatch remain unchanged. The flag is not a send guard: the existing dispatcher does not inspect the new metadata.

The transaction boundary includes decision claims/results, rule or risk/episode transitions, projections, canonical alerts, delivery metadata and audit. Failure must not publish rolled-back decision/alert events. Legacy market acquisition and official close-pending preparation already committed before that transaction remain durable. Duplicate decisions or dedup skips do not rewrite classification or manufacture provenance; no-intent evaluations create no delivery metadata. Missing historical rows still require bounded reconstruction separately.

Design review exposed a clock mismatch in the existing helper: the unit of work defaults to UTC, ordinary outbox enqueue normalizes any aware clock, but the helper forwarded the raw clock to a Shanghai-only repository. The helper now passes its existing normalized `_now` method; canonical source timestamps and evaluator time validation are unchanged. No real database/configuration, provider or notification channel was used; no new dependency, migration, generated schema or UI change is introduced.

## Test-first and review evidence

- Clock compatibility: two UTC/UTC-4 examples failed with `ValueError` before the one-line helper fix, then passed with the storage/outbox regression suite. This closes an integration precondition; it does not relax timestamp validation.
- Evaluator RED: 24 failed / 3 passed before the constructor option existed. The core implementation then passed 36 cases; final coverage is 48 cases after fixture corrections and added no-intent, canonical-equivalence, duplicate-no-backfill and two-intent atomicity cases. Injected metadata/audit SQL failures prove rollback and successful retry; both explicit intents roll back if the second write fails. The final independent code review found no remaining material issue within this storage-only increment.
- The implementation child used `gpt-6-astra` / `high`; independent review used `gpt-6-astra` / `xhigh`. These settings do not attest the parent model/effort. Extra cross-model review remained skipped per the user's earlier choice.

## Executed verification

| Command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_delivery_eligibility_storage.py -k normalizes_the_outbox -q --tb=short` | Before fix: 2 failed, 40 deselected, 1 existing warning; failure at Shanghai clock validation |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_delivery_eligibility_storage.py tests/unit/test_notification_outbox.py -q --tb=short` | After fix: 88 passed, 1 existing warning, 6.09 seconds |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_recovery_alert_eligibility.py -q --tb=short` | Implementation agent after source freeze: 48 passed, 8.22 seconds |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | Passed |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI snapshot and frontend types are current |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | Final functional regression after source freeze: 3241 passed, 4 pre-existing failures, 1 existing skip, 4 live deselected, 1 existing warning; 489.73 seconds |

All 50 new cases (48 transaction cases and 2 clock cases) are included in this final functional run. Its 4 failures exactly match the prior report: canonical index-head update time, pending-close index-error reference health, provider TIMEOUT versus TRANSIENT, and the R14 mock payload rejected by the temperature guard. No new functional failure was observed; the full acceptance gate is still not green. The unchanged heavy backtest acceptance file was not rerun here; its previous full-run evidence remains in `2026-09-21-runtime-recovery-increments.md`. The existing skip is the Windows/POSIX ownership boundary. No failing assertion was removed, skipped or weakened.

The explicit evaluator tests use a UTC unit-of-work clock. An exploratory legacy UTC fixture reproduced a separate existing default-path error before alert enqueue: `_persist_projection_dependencies` → `HealthRepository.upsert_symbol` → `MonitorEventDraft.occurred_at` rejects the UTC value. It also fails with `recovery_delivery` omitted, so this was not repaired by expanding the slice. Legacy integration fixtures retain their existing Shanghai clock contract. The outbox normalization fix does not claim all legacy repositories accept UTC clocks; this integration limitation must remain visible before production composition changes.

Whitespace checks passed. All three changed document pairs have matching heading counts and technical literals after paired-path normalization. A high-confidence secret-pattern scan covered all 11 changed files and found no match; this is scoped hygiene, not a credential audit. The UTC helper correction and evaluator implementation are saved as local commits `60b0690` and `5970eba`, after the previously requested push; they have not been pushed in this continuation.

## Remaining work

This is an opt-in transaction slice of RR012, not a completed recovery-delivery system. Durable current-risk/inventory/calendar/barrier reconstruction, missing official-close discovery, legacy suppression persistence and per-channel final send admission remain open. Production lifecycle/status wiring, protocol/UI implementation and process-restart acceptance also remain open. The 4 pre-existing functional failures recorded in `2026-09-21-recovery-delivery-metadata.md` are not waived. No default switch, merge or deployment is implied.
