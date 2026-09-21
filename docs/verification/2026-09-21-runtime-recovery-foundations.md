# Runtime recovery foundations — 2026-09-21

Canonical English; review copy: `2026-09-21-runtime-recovery-foundations.zh-CN.md`.

## Scope and authority

Implementation was authorized on 2026-09-21. This report covers isolated provider/recovery foundations, not the complete anytime-restart requirement. Production composition has not enabled the new recovery path. No live configuration, provider request, notification delivery, process restart, or production-database migration was performed. Temporary databases and mocked transports were used. The implementation phase did not commit, push or deploy; the subsequent user instruction separately authorizes organizing commits and publishing them to GitHub, not deployment.

Publication scope: the existing development branch `codex/consolidate-r19-r32`, without merging into `main` or rewriting history. Changes are grouped by contract, semantic records, checkpoint storage, request admission, recovery targets/schedule, injected gates and verification documentation. Before publication, the combined regression command below was rerun: 368 passed, 1 existing warning, 41.39 seconds. Ruff, generated-contract checks and whitespace checks passed. A bounded scan of the 27 pending files found no common credential/private-key pattern; live configuration and runtime data are excluded. This does not supersede the full-suite failures or rollout limits below.

## Implemented slices

- RR001: paired `SPEC-provider-contract` and `SPEC-runtime-recovery` derive existing approved D1–D6 boundaries. Detailed transport/status specifications and full C0 review remain outstanding.
- RR003: historical evidence readers and independent durable semantic sidecars. Legacy seven-day loaders retain their old contract; injected new gates use semantic revisions. Actual installed SDK compatibility is checked; original evidence and operational health are not rewritten. Atomic no-clobber publication handles competing imports.
- RR004 (partial): `ProductionSemanticBindings` installs independent stock/index gates through dependency injection, including the index-only dashboard path. The public composition and selected-stock-failure orchestration are not switched.
- RR005: additive `0018_provider_recovery` and bounded checkpoint storage, max 74 rows per provider identity (64 work backoffs + 9 operation permissions + 1 shared cooldown). Downgrade refuses populated checkpoints. Existing latest-head assertions and metadata parity were updated.
- RR006 (foundation): optional durable controller binding, controlled/coalesced permission rechecks, bounded fair scope schedule, stale-target fencing and stable retry admission. Late physical failures are retained even by an unbound controller; this does not enable automatic production retries. Not a background runtime owner.
- RR007/RR008 (foundation): pure session targets and exact persisted-minute coverage, max 240 identities per work unit, frozen cutoff and cross-day/clock-reversal rejection. No new default recovery coordinator or business-state replay yet.

## Execution allocation and method

The provider/gate, retry/storage and coverage subagents were explicitly launched with `gpt-6-astra` / `high`. Independent foundation, semantic-gate and admission reviewers used `gpt-6-astra` / `xhigh`. This records tool-confirmed subagent settings, not a claim about the parent model's mutable settings. The user declined additional cross-model review.
Test-driven and incremental implementation skills required failing cases before source changes. API/interface and migration skills kept new paths injected and storage additive; independent review was applied to race/ownership assumptions. Official implementation references: [Python 3.14 task cancellation](https://docs.python.org/3.14/library/asyncio-task.html), [SQLAlchemy transaction boundaries](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html).

Applied skills: `using-agent-skills`, `spec-driven-development`, `api-and-interface-design`, `documentation-and-adrs`, `incremental-implementation`, `test-driven-development`, `deprecation-and-migration`, `source-driven-development`, `debugging-and-error-recovery`, `doubt-driven-development`, `code-review-and-quality`. They informed contract-first additive slices, red/green tests, primary-source checks and bounded adversarial correction cycles; they did not authorize live actions.

## Verification evidence

All commands run from `trade-plan-monitor`.

| Check | Observed result |
|---|---|
| Combined foundation/regression command below, final post-review run | 368 passed, 1 existing Starlette warning, 43.60 seconds |
| `.\.venv\Scripts\python.exe -m pytest tests/unit -m "not live" -q --tb=short` | 1574 passed, 2 failures listed below, 15.14 seconds; no all-unit-pass claim |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | Passed |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI snapshot and frontend types are current |
| `git diff --check` | Passed; existing LF/CRLF conversion notices |
| Full integration, frontend build/browser and real restart acceptance | Not performed for this foundation checkpoint |

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_live_certification_profiles.py tests/unit/test_provider_contract.py tests/unit/test_recovery_targets.py tests/unit/test_runtime_reconciliation.py tests/unit/test_request_recovery_admission.py tests/unit/test_monitor_runtime.py tests/integration/test_runtime_recovery_storage.py tests/integration/test_sqlite_repositories.py tests/integration/test_production_semantic_gate.py tests/integration/test_production_certification_gate.py tests/integration/test_certified_production_runtime.py tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py -q --tb=short
```

## Findings and disposition

Independent foundation review found three actionable issues; all reproduced with failing tests and were corrected. Cycle 2 found no unresolved issue within its bounded scope:

1. Concurrent sidecar publication could overwrite another import. Publication now uses atomic no-clobber linking; an existing destination is validated, never overwritten.
2. A failure arriving after target change could lose its retry deadline. Stale business readiness is discarded, while the stable scope retains its retry gate.
3. A held ticket could yield an immediate wake despite blocking admission. Owned work now returns a future maintenance wake, avoiding a tight loop.

Admission review found three further actionable issues, also reproduced before correction:

4. Cancelled ordinary callers discarded late physical rate-limit/permission/transient outcomes. Controller-owned completion now records them before releasing capacity or ownership; observed timeouts are not counted twice.
5. Queue delay shortened the 300-second permission interval. The initial durable reservation is retained and extended immediately before physical submission.
6. An observed checkpoint-write failure could release ownership while old readable state omitted the known cooldown. All unresolved checkpoint faults now quarantine replacement, after worker cleanup; no separate late-fault flag remains.

Admission review completed three bounded cycles; the final correction had no remaining high-confidence finding, with four focused ownership/failure checks passing. The independent injected semantic-gate review found no concrete regression/fail-open issue. The final combined command above was then rerun. These bounded reviews do not approve C1's still-missing autonomous integration or the full feature.

## Existing failures and limits

The unit failures reproduce individually in unchanged files:

- `test_market_data.py::test_tushare_provider_errors_use_stable_codes_and_drop_raw_context[provider_error2-TRANSIENT]`: test expects TRANSIENT, provider returns TIMEOUT.
- `test_r14_bounded_acceptance.py::test_ai_guard_allows_only_one_approved_prompt_and_counts_failed_attempt`: mock request omits temperature, while the existing transport requires `temperature == 0`; it raises BudgetDenied before the mock handler. This was not a real external AI request.

The two failures documented in `2026-09-17-change-consolidation.md` were also reproduced (2 failed, 3 passed, 14 deselected): older canonical index revision head time and pending-close index-error reference health. No failed test was removed, skipped or weakened.

## Remaining work

C0–C5 remain open. Complete RR002 and RR004 integration, install the persistent lifecycle coordinator, discover missed closes, fence business commits, add atomic alert eligibility and recovery barriers, implement honest partial status/versioned transport/UI, then run actual offline process-restart and full acceptance gates. The current user-visible “recovering” problem is not claimed resolved by these foundations.
