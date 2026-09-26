# B2 DAILY_BARS permission demand

## Scope

Independent read-only methods on `LegacyHistoricalCloseReader`; no production wiring, shared B1 candidate changes, scheduler, migration, SDK, market/evaluation/notification writes, or historical execution permission. Existing `missing_targets_in_session` remains unchanged. Caller supplies a fresh explicit-BEGIN SQLite snapshot; the helper uses `no_autoflush` and owns no transaction.

## Contract

- DBPD-01: `inspect_permission_demand_in_session(session, symbol, now, cursor=None)` returns immutable `DemandCheck`: `NEEDED`, `NONE`, or `UNKNOWN`, full current identity, optional receipt, reason, and next cursor. Identity includes symbol, plan_version_id, plan_hash, formula_version, activation_revision, and actual activated_at. Broken activation evidence is `UNKNOWN` without paging past it; activation and orphan-publication reads retain the existing 1000+1 cap.
- DBPD-02: An ACTIVE legacy plan eligible today immediately yields `TODAY_REFERENCE`, without history/date/checkpoint/pending reads and without D_need. Full current identity is still verified. Future policies have no historical demand. Expired policies use `HISTORICAL_CLOSE`.
- DBPD-03: Each historical call examines at most 32 consecutive calendar days, at most 32 date completion checks, and one latest verified close checkpoint. Start is max(actual activation/policy start, checkpoint+1); end is bounded by policy, observation, and close due. There is no 366-day or five-day cutoff. Reuse `_scope`, `_latest_completed_close`, `_CompletionReader`, and `discover_missed_closes`; never call the unbounded missing-target scan.
- DBPD-04: An applicable open date with completion `ABSENT` yields witness `(S,D_need)` in the current snapshot, even following unknown dates. This is permission demand only; it never authorizes business replay across `UNKNOWN`. A pending date alone is never evidence. Pending presence cannot veto independently verified activation, calendar, and completion-absence evidence or invalidate its receipt. This helper does not read pending or use it as a shortcut. Pending alone with insufficient historical evidence remains `UNKNOWN`.
- DBPD-05: Cursor stores full identity, next_date, checkpoint identity/hash, observed_at, and reader-instance token; no ORM values or transaction authority. Unknown pages advance; the tail wraps to the authoritative start. Global unrelated events, time advancement, and calendar refresh alone do not reset progress. Identity change rebuilds from start. Checkpoint advancement skips its covered prefix. Checkpoint rollback/replacement/corruption, clock rollback, or another reader invalidates the cursor and produces `UNKNOWN`; retry without that cursor starts fresh.
- DBPD-06: `NONE` requires checkpoint coverage of the end, an empty authoritative applicable interval, or the complete remaining applicable range inspected and complete in this snapshot. A short tail is insufficient. Pages from different snapshots are never combined into a completeness proof.
- DBPD-07: `validate_permission_demand_in_session(session, receipt, now)` returns bool. Receipt binds identity, kind, optional D_need, checkpoint, captured_at, and reader token. TODAY revalidates full identity and eligibility. HISTORICAL point-checks the same date, policy/calendar/absence/latest checkpoint. Completion, checkpoint coverage/rollback/corruption, identity ABA, time rollback, cross-day reuse, or another reader invalidates it. A valid receipt still carries no execution permission.

## Verification

Real temporary SQLite fixtures are the primary evidence; mocks only observe budgets or forbid unwanted calls. RED precedes implementation. Targeted coverage includes today short circuit, day 33, history beyond 366 days, unknown-page advancement/wrap, no tail-only NONE, read budgets, unrelated events/calendar refresh, identity ABA, checkpoint advancement/rollback, bare ledger/orphan/corrupt evidence, receipt invalidation, pending ambiguity, and zero writes/SDK calls. Historical recovery and permission candidate regressions plus Ruff and diff checks are required. No commit until independent review.

Results (2026-09-27):

- RED: the new test reached a fully initialized temporary database and failed with `AttributeError` for the missing `inspect_permission_demand_in_session` API before implementation.
- Review correction: the earlier 38 demand tests and 279 distinct passing tests missed a P1. The symbol-wide pending veto contradicted independent historical evidence; those prior green results are not correctness evidence for that behavior.
- P1 RED: normal `RuntimeEvaluationService._mark_close_pending` writes in temporary SQLite reproduced two failures: independent demand changed from `NEEDED` to `UNKNOWN`, and the existing valid receipt became false. Three pending-only cases with missing calendar, activation, or completion evidence stayed `UNKNOWN` (2 failed, 3 passed, 37 deselected).
- P1 GREEN: 5 passed, 37 deselected. Final combined run: 283 passed (42 demand tests and 241 adjacent tests) in 52.56s, with one existing FastAPI/Starlette `httpx` deprecation warning. Ruff and `git diff --check` passed. The fix removes only the new global veto, its private helper, and its import; no pending shortcut is added.
- Independent Sol/xhigh review: 42 demand tests, Ruff, and diff checks passed; the normal-pending regression is resolved, with no remaining P1/P2 findings in this helper scope.
- Budget instrumentation covers exactly 32 date reads plus 1 checkpoint read. Day 33 and day 371 are reached through pagination; a 400-day-old gap remains visible. Actual activation and policy start are both enforced.
- The original recovery methods are unchanged. The change is limited to four files, with no real database/service/provider access and no production integration.

Commands (run from `trade-plan-monitor/`):

```powershell
.venv/Scripts/python -m pytest tests/integration/test_daily_bar_permission_demand.py -x -q
.venv/Scripts/python -m pytest tests/integration/test_daily_bar_permission_demand.py -k 'normal_pending or pending_alone' -q --tb=short
.venv/Scripts/python -m pytest tests/integration/test_daily_bar_permission_demand.py tests/integration/test_historical_close_evidence.py tests/integration/test_close_recovery_evidence.py tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/unit/test_missed_close_recovery.py tests/unit/test_production_historical_recovery.py tests/integration/test_missed_close_execution.py tests/integration/test_close_recovery_session_ownership.py -q --tb=short
.venv/Scripts/python -m ruff check src/trade_plan_monitor/runtime/historical_close_evidence.py tests/integration/test_daily_bar_permission_demand.py
git diff --check
```
