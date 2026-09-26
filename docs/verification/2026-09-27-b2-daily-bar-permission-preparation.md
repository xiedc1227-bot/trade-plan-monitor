# B2 DAILY_BARS permission preparation

## Scope

Internal production preparation only: no reservation, SDK call, business write, automatic scheduling, or physical permission probe. Changes are limited to `production.py`, the new integration tests, and this paired report. This does not complete C1 or prove cross-scope starvation freedom.

## Contract

- DBPP-01: Optional `permission_session_factory` owns safe permission reads and a stable independent `LegacyHistoricalCloseReader`. It defaults to the supplied `recovery_session_factory`; it never fills that business-recovery option or enables `_historical_reader`. Without a safe source, return `UNKNOWN` and defer locally by exactly 30 seconds. Never infer a factory from private UnitOfWork fields.
- DBPP-02: `_prepare_daily_bar_permission` holds the shared permission maintenance lock. First check the DAILY_BARS latch and effective due=max(raw, local, 429). Other candidates compete only when effective-due<=now, preserving raw-due and existing scope-cursor order. DAILY_BARS need not exist in the broad selector: missing demand/anchor/authority still receives a fixed now+30 defer. Not-yet-due calls do not slide that deadline or inspect pages; another scope winning does not inspect a demand page.
- DBPP-03: One owner-thread explicit-BEGIN SQLite snapshot contains ACTIVE enumeration, demand inspection, receipt validation, calendar and official-bar reads, and candidate construction. Share the existing evidence logic without changing pure peek behavior; do not combine a UnitOfWork read with a separate demand snapshot. Database read failures propagate.
- DBPP-04: Keep at most 10 current ACTIVE legacy symbols in cursor/receipt caches. Prune disappeared symbols. Today-eligible plans use the helper's TODAY short circuit. Each invocation inspects at most one expired historical symbol and one <=32-calendar-day page, using a separate strict-successor symbol rotation over the entire current historical list. UNKNOWN, NONE, and newly added symbols remain eligible for future inspection. Success may be inspected again; the 32-day budget is per invocation, not a lifetime budget.
- DBPP-05: Cross-day receipts expire without discarding valid pagination cursors. Unrelated events and same-value calendar refreshes do not reset progress. Drop cursors on `invalid_cursor` or checkpoint rollback; preserve them when ordinary evidence is temporarily missing. Identity changes rebuild through the helper. Pending never vetoes independently verified demand.
- DBPP-06: In the same snapshot, validate at most 10 cached receipts, each with the helper's point-check/checkpoint budget, separately from the single 32-day page budget. Only currently valid receipt symbols enter O/F; preserve existing pool sorting, strict-successor selection, and alternation. Return an immutable result with candidate, original receipt, captured_at, semantic binding facts, and calendar epoch. It is neither execution authority nor permission to reuse a long-lived cache.
- DBPP-07: Preparation does not move controller reservations or scope/O/F cursors. No valid demand/anchor/authority returns `UNKNOWN` with a fixed 30-second local defer. Configuration, semantic, generation, and admission revocation remain enforced. Historical-symbol investigation fairness is the only fairness claim here; cross-scope scheduling is a later integration gate.

## Verification

Use real temporary SQLite and fake SDKs. Cover production composition, permission-only construction, due/429/other-scope gates and pure peek, an earlier raw deadline with a future effective deadline, fixed no-anchor defer, 10-symbol rotation, new/NONE/UNKNOWN revisits, day 33/371 and cross-day progress, receipt invalidation/identity ABA/clock rollback/reader replacement, normal pending, one snapshot, and zero reservations/SDK/business writes. Run helper, candidate, rotation, INDEX_DAILY and DAILY_LIMITS adjacent regressions plus Ruff/diff checks. No commit before independent review.

Results (2026-09-27):

- RED: real production composition started successfully, then the new test failed with `AttributeError` for the missing independent `_permission_demand_reader`. The paired contract and tests preceded implementation.
- GREEN: 28 preparation tests passed. Coverage includes ten-symbol UNKNOWN/NONE revisits, day 33/371 across midnight, a normal pending write, original receipt retention, strict receipt filtering, shared-lock serialization, and coherent evidence across a concurrent activation write. A single preparation performed exactly one `BEGIN`, validated 10 receipts on that same session, and issued only `BEGIN`/`SELECT`; reservation deadlines, scope/O/F state, and fake SDK call counts stayed unchanged.
- Adjacent combined run: 137 passed in 46.82s (28 preparation tests plus 109 helper/candidate/rotation/INDEX_DAILY/DAILY_LIMITS tests). One existing FastAPI/Starlette `httpx` deprecation warning. Ruff and `git diff --check` passed.
- The 366-day O/F anchor window remains separate from historical demand pagination without an age cutoff. Ordinary missing activation evidence retains its cursor; a replacement reader invalidates cached receipts and the examined stale cursor. Each successful repeat remains bounded to one historical inspection and at most 10 receipt validations.
- Independent Sol/xhigh review passed with no new P1/P2 findings. The reviewer independently confirmed 28 preparation tests, the 137-test combined run, Ruff/diff checks, and bilingual parity. The change is limited to four files. No real service, user database, push, deployment, scheduler integration, or physical DAILY_BARS probe.

Commands (from `trade-plan-monitor/`):

```powershell
.venv/Scripts/python -m pytest tests/integration/test_production_daily_bar_permission_preparation.py -x -q --tb=short
.venv/Scripts/python -m pytest tests/integration/test_production_daily_bar_permission_preparation.py -q --tb=short
.venv/Scripts/python -m pytest tests/integration/test_production_daily_bar_permission_preparation.py tests/integration/test_daily_bar_permission_demand.py tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_production_daily_limits_permission_maintenance.py -q --tb=short
.venv/Scripts/python -m ruff check src/trade_plan_monitor/runtime/production.py tests/integration/test_production_daily_bar_permission_preparation.py
git diff --check
```
