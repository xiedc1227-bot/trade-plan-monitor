# Recovery Delivery Metadata Verification — 2026-09-21

> Canonical English; paired Chinese review copy. Continues from `5f91b51`. Isolated implementation evidence, not complete anytime-restart acceptance or deployment approval.

## Scope and boundaries

- RR011 storage slice: migration `0019_alert_delivery_eligibility`, matching ORM model and session-bound repository. Missing metadata initializes to HOLD, at most 100 per batch. Canonical alert/result payloads and hashes are unchanged. Original source cutoff, not recovery creation time, determines actionable expiry at +90 seconds; state-risk alerts have no age-only expiry.
- The repository persists explicit-risk classification with captured barrier/result identity, revision fencing and atomic audit. Source/class/deadline and classifier evidence are validated against fresh canonical alert reads. Corrupt metadata and database failures are visible faults; they never grant permission. Suppression is terminal; HOLD can be reevaluated. The caller owns commit/rollback.
- `AlertOutbox.enqueue_recoverable` is opt-in: canonical enqueue and initial HOLD share the caller transaction. Dedup does not reset metadata or invent current-activation provenance. Existing evaluator callers and dispatcher defaults remain unchanged.
- RR012–RR013 policy slice: a separate pure legacy classifier covers approved latest-risk/current-inventory applicability and latest-only repeated exits. Proven original plan/result reconstruction precedes terminal suppression. Coherent current observations, official history/stage, T+1 and current target lot are required. Closed-day targets may retain the previous session only with newly certified current observations. This policy does not read durable current history, persist legacy suppression or send messages.
- Nonempty downgrade refuses to discard delivery metadata, including terminal audit records. Only temporary databases were upgraded/downgraded; no production database, credentials/configuration, provider, real notification channel or deployment was touched. No dependencies, generated contracts or frontend source changed.

Full RR011–RR013, C0/C2/C3 and the anytime-restart acceptance remain open. Required follow-up includes evaluator-transaction wiring, durable provenance/current-state/barrier reconstruction, missing official-close discovery, candidate filtering before query limits, per-channel post-claim authority rechecks, generation fencing, lifecycle/status integration and real-process restart tests with fake external services. A stored ELIGIBLE receipt is never standing send permission; no exactly-once external-delivery guarantee is introduced. ADR 0007 records the design and rollback boundary.

## Test-first and independent review

| Slice | Observed RED | Final review outcome |
|---|---|---|
| Delivery storage | Missing module; missing classifier/helper methods; accepted canonical-source/deadline/evidence mismatches; accepted invalid terminal classifier reasons and incomplete false-risk evidence | Three bounded code-review rounds closed with no remaining material finding. Added concurrency, audit-failure rollback, interrupted migration, persisted receipts and cache-refresh cases |
| Legacy policy | Missing module; contradictory latest stage and future inventory admitted; same-day T+1 contradiction, invalid provenance suppressed before validation, stale current observations and newer occurrence outside snapshot; closed-day acquisition later than certified session | Three bounded review rounds closed with no remaining material finding. 56 policy cases including the closed-day positive case, not a blanket risk expiry |

The legacy implementation child used `gpt-6-astra` / `high`; independent storage and legacy reviewers used `gpt-6-astra` / `xhigh`. These child settings do not attest the parent model/effort. The extra cross-model opinion was skipped per the user's prior choice. Review changes tightened source, snapshot and settlement evidence rather than weakening failed assertions. Existing SQLite migration tests changed only the expected latest head/table set for the additive schema; all business preservation/downgrade assertions remain.

## Executed verification

Run from `trade-plan-monitor`; external live tests are excluded.

| Command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_delivery_eligibility_storage.py tests/integration/test_sqlite_repositories.py -q --tb=short` | 146 passed, 1 existing warning, 14.73 seconds; 40 new storage cases plus 106 existing SQLite cases |
| `.\.venv\Scripts\python.exe -m pytest tests/unit/test_legacy_recovery_delivery_eligibility.py -q --tb=short` | Coding agent: 56 passed in 1.61 seconds after final review fix; final reviewer also passed all 56 |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_delivery_eligibility_storage.py tests/unit/test_legacy_recovery_delivery_eligibility.py tests/integration/test_recovery_alert_provenance.py tests/unit/test_recovery_delivery_eligibility.py tests/integration/test_notification_delivery.py tests/unit/test_notification_outbox.py tests/integration/test_sqlite_repositories.py tests/integration/test_runtime_recovery_storage.py -q --tb=short` | Final focused regression: 385 passed, 1 existing warning, 29.36 seconds; includes all 96 new cases |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | Passed |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI snapshot and frontend types are current |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | 3190 passed, 4 known failures, 1 existing skip, 4 live deselected, 1 existing warning; 492.18 seconds |

The functional run reproduced exactly the 4 pre-existing failures below. They are not waived or repaired in this delivery increment; no failing test was removed or skipped to claim green.

- `tests/integration/test_live_pipeline_acceptance.py::test_market_index_persistence_reuses_an_older_canonical_content_revision`: expected index-head update 10:38, actual 10:36.
- `tests/integration/test_live_pipeline_acceptance.py::test_startup_batches_persisted_pending_closes_by_date_and_shared_index[index_error]`: expected BLOCKED reference health, actual LIVE.
- `tests/unit/test_market_data.py::test_tushare_provider_errors_use_stable_codes_and_drop_raw_context[provider_error2-TRANSIENT]`: expected TRANSIENT, actual TIMEOUT.
- `tests/unit/test_r14_bounded_acceptance.py::test_ai_guard_allows_only_one_approved_prompt_and_counts_failed_attempt`: the mock payload lacks the required temperature guard input, raising `BudgetDenied` before fake transport.

The functional process collected/imported before the final closed-day acquisition bound and its one regression case were added; its actual count includes 95 new cases. The final 385-case focused run executed after that fix and includes all 96 new cases. The unchanged heavy backtest acceptance file was not rerun here; its earlier passing full-run evidence remains in `2026-09-21-runtime-recovery-increments.md`. The existing skip is the Windows/POSIX ownership boundary. Full acceptance is not green, and no complete production/restart acceptance is claimed.

Whitespace and global Ruff checks passed. All four document pairs have matching heading counts and technical literals after paired-path normalization, except the ADR header's explanatory `.zh-CN.md` suffix in English only. A high-confidence secret-pattern scan of all 16 changed files found no match; this is scoped hygiene, not a credential audit.

## Changed surfaces and sources

New `notifications/delivery_eligibility.py`, `notifications/legacy_recovery_eligibility.py`, migration `0019_alert_delivery_eligibility.py`, focused storage/policy tests; narrow additions in `notifications/outbox.py` and `state/models.py`; SQLite expected-head assertions; paired recovery specification, ADR 0007, task checkpoint and this report.

Caller-owned transaction design follows [SQLAlchemy transaction boundaries](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html); the additive table uses the existing [Alembic operations API](https://alembic.sqlalchemy.org/en/latest/ops.html#alembic.operations.Operations.create_table). Business rules come from the approved project specification, not those framework documents.
