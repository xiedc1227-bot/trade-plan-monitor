# Change consolidation — 2026-09-17

Canonical English; review copy: `2026-09-17-change-consolidation.zh-CN.md`.

## Scope and delivery

The user requested organizing existing changes and pushing them to GitHub. The delivery branch is `codex/consolidate-r19-r32`; it is not approved for merging or deployment. GitHub `main` is intentionally not updated because verification exposed two reproducible failures.

- Preserve the 37 existing commits after the fetched `origin/main`, including the continuous R19–R32 history. Local `main` was fast-forwarded from `e947397` to `c92f18d` before creating the delivery branch; no existing commit was rewritten.
- Group the existing turnover correction and its tests/specifications separately: compare the current cumulative amount with the previous trading day's opening buckets through the same cutoff, requiring the complete previous session.
- Preserve the paired runtime-recovery proposal and task list as DRAFT / NOT STARTED. Publishing these documents does not approve their design, migrations, implementation, or rollout.
- Correct only the import ordering in `tests/integration/test_source_treatment_review_api.py`; do not change its assertions or runtime behavior.
- Retain isolated R29–R32 worktrees and historical evidence. Do not replay any consumed acceptance request or start R33.

## Verification performed

Commands were run in `trade-plan-monitor` using its existing virtual environment.

| Check | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | Passed after one import-order-only correction |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI snapshot and frontend types are current |
| Pending bilingual documents | 49 pairs exist with matching heading counts; runtime-recovery decision/acceptance/task ID counts also match |
| `git diff --check` | Passed; Git emitted existing LF/CRLF conversion notices |
| Targeted test command below | 158 passed, 2 failed, 1 existing Starlette deprecation warning, 40.58 seconds |
| Same two failures on untouched R32 `c92f18d` | Both reproduced, 5.05 seconds |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" -q --tb=short` | Started and deliberately interrupted during the long backtest capacity group; no full-suite pass is claimed |

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_turnover.py tests/integration/test_market_index_runtime.py tests/integration/test_persistent_monitor_read_service.py tests/integration/test_live_pipeline_acceptance.py tests/integration/test_r29_v6_extraction_acceptance.py tests/integration/test_r30_ai_timeout_budget_acceptance.py tests/integration/test_r32_ai_transient_acceptance.py tests/unit/test_r30_ai_timeout_budget.py tests/unit/test_r26_ai_timeout_diagnostics.py tests/unit/test_r28_field_binding_diagnostics.py tests/integration/test_source_treatment_review_api.py -q --tb=short
```

## Unresolved merge blockers

Both failures are in `tests/integration/test_live_pipeline_acceptance.py` and reproduce without the turnover edits in the clean R32 worktree:

1. `test_market_index_persistence_reuses_an_older_canonical_content_revision`: the head's `updated_at` remains `10:36` instead of the asserted `10:38`. The persistence path coalesces repeated BLOCKED snapshots with identical issues before advancing the head. The intended relationship between this coalescing rule and canonical-revision reuse needs a bounded follow-up.
2. `test_startup_batches_persisted_pending_closes_by_date_and_shared_index[index_error]`: the recovered reference is LIVE while the test expects BLOCKED. The persistence path preserves an existing LIVE head when a later acquisition is non-LIVE. Resolve the contract/test interaction; do not simply weaken the assertion.

The relevant persistence implementation was unchanged between fetched `origin/main` and R32. This report records evidence, not a decision to change either production rule. No failed test was deleted, skipped, or relaxed. The interrupted full suite, frontend build/browser gates, and unresolved failures remain outstanding before merge/deployment review.

## Data and publication boundary

Real AI, market, and account requests were not authorized or executed by this consolidation. Only GitHub synchronization is in scope. The real `config/app.yaml` remains untracked and unchanged, SHA-256 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`.

The outgoing 37-commit history was checked for common credential/private-key patterns and exact local credential matches: no matches. This is a bounded check, not a comprehensive security audit. Real configuration, credentials, databases, and local raw egress review packages are excluded. The already tracked `data/r20-acceptance/r20-20260915-a/termination.json` is retained: it contains sanitized terminal metadata, counters, and zero-row summaries, not raw provider responses or credentials.
