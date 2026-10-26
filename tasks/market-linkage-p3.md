# Implementation plan and tasks: market-linkage-p3

Status: IMPLEMENTING — 2026-10-26. The user approved all six decisions and implementation; marks record actual progress. [Chinese review copy](market-linkage-p3.zh-CN.md) · [Specification and six approved decisions](../docs/specifications/monitoring/SPEC-market-linkage-p3.md).

## MLP3-P01 — Authority, scope and working method

MLP3-D01–MLP3-D06 and implementation are authorized. Baseline `c9ad16aa352d9bdb5ec49f16cd9fcd90151f9c46`. Preserve `tasks/plan.md` and `tasks/todo.md`; use this phase-specific task pair. No parallel/delegated agents. Migration development/verification uses disposable databases only. User-database migration, live provider calls, deployment and push remain outside authorization.

After explicit implementation authorization, progress in dependency order and accept each checkpoint before its dependents. Use failing tests with independent quantity/fen oracles before behavior changes. Each slice targets 3–5 files. Listed paths are ownership seams; if a parent task spans more, record and execute sequential child slices of at most 5 files, each with its own focused check. Do not adapt every schema set in one unchecked sweep. New schema admission remains closed until the complete authority chain is ready; frozen-input admission remains closed until its replay guards are ready.

Maintain old golden files and byte/hash expectations, exact arithmetic, source boundaries and all existing timeout/memory/payload budgets. Empty selections, scaffold-only code, skipped new assertions and partial checkpoint results are not acceptance. Repair environment/test failures before asking for a decision. Stop for review only on a new strategy/accounting meaning, unsupported historical authority or an out-of-scope change that cannot be resolved within the approved contract. Existing authorized work does not need repeated confirmation.

## MLP3-P02 — Verification commands

Run from `trade-plan-monitor/`. All proposed p3 test files are created by their owning tasks. Before a downstream file exists, record its checks as unexecuted; do not run a selection of zero tests and call it success. Use disposable SQLite, synthetic explicit prices/fees and deterministic providers, never user databases.

| ID | Executable command / check |
| --- | --- |
| V01 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_quantity_policy.py tests/unit/test_market_exception_quantity.py tests/unit/test_p2_policy_contract.py tests/unit/test_p2_sizing.py tests/unit/test_p2_economics.py tests/unit/test_p2_composition.py -q` |
| V02 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_p3_policy_contract.py tests/unit/test_p3_capital_gate.py tests/unit/test_p3_capital_basis.py -q` |
| V03 | `.\.venv\Scripts\python.exe -m pytest tests/integration -m "not live" -k p3 -q` |
| V04 | `npm --prefix web run test -- --run tests/unit/p3Review.spec.ts tests/unit/p3Capital.spec.ts`; `npm --prefix web run type-check` |
| V05 | `npm --prefix web run test:e2e -- tests/e2e/p3-capital.spec.ts tests/e2e/p2-pretrade.spec.ts tests/e2e/market-exceptions.spec.ts tests/e2e/market-linkage.spec.ts` |
| V06 | `.\.venv\Scripts\python.exe -m pytest tests/unit -m "not live" -q`; `.\.venv\Scripts\python.exe -m pytest tests/integration -m "not live" -q`; `.\.venv\Scripts\python.exe -m pytest tests/contract tests/replay -m "not live" -q`; `npm --prefix web run test -- --run`; `npm --prefix web run build` |
| V07 | `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` (both API profiles); `.\.venv\Scripts\python.exe -m ruff check src tests`; `git diff --check`; final staged/baseline diff check |
| V08 | Verify original-source hash/excerpts, paired document sections/IDs/thresholds/API paths/enums/formulas/units/links, task dependencies and source→criterion→actual-test/result trace; preserve protected task files. |

Keep backend directories in separate processes because existing unit/integration basenames collide. Local tests that need socket communication must use an environment that permits it; preserve synthetic-provider isolation. Record original failures, interrupted runs and exact successful reruns. Capacity tests run without competing heavy test/build jobs and retain their existing bounds. Optional BT050_REPORT_METRICS=1 may expose existing metrics; it must not change test conditions or thresholds.

## MLP3-P03 — Ordered tasks and checkpoints

### MLP3-T01 — Freeze contracts, source inventory and baseline

- [x] Deliver slice and independent evidence.
- Depends on: explicit approval and implementation instruction.
- Files/scope: paired CONTRACT-market-linkage-p3 appendix (new), source-excerpt fixture and baseline check (at most 5 files). Freeze owned versions, capacity states, new endpoints, book/event fields and availability rules; verify no name collision.
- Acceptance: MLP3-A01,MLP3-A02. Verify: V01,V08. Baseline tests are evidence only; no P3 pass is claimed.

### MLP3-T02 — Add strict Schema 9 position/capital contracts

- [x] Deliver slice and independent evidence.
- Depends on: T01.
- Files/scope: `domain/p3_policy_models.py` (new), bounded draft models, `tests/unit/test_p3_policy_contract.py` (new).
- Acceptance: MLP3-A02,MLP3-A03. Verify: created V02 files. Reject cap ambiguity, fake/extra max_qty, unsafe amounts and unbounded/unknown confusion.

### MLP3-T03 — Add gated codecs, source paths and review hashes

- [x] Deliver slice and independent evidence.
- Depends on: T02.
- Files/scope: domain codecs, draft dispatch, hash/source-path seams and historical golden tests. Split codec and source/hash adapters into separate 3–5-file children before editing if necessary.
- Acceptance: MLP3-A02. Verify: V01 and created V02 files; public9 stays closed, old readers reject 9, old 1–8 bytes unchanged.

### MLP3-C01 — Contract acceptance

- [x] V01,V02,V08 available-stage checks pass; MLP3-A01,MLP3-A02 and strict A03 boundaries covered. Record downstream checks as not yet executed.

### MLP3-T04 — Expose exact buy-debit arithmetic without changing P2

- [x] Deliver slice and independent evidence.
- Depends on: T03.
- Files/scope: P2 fee helper, pure P3 adapter, P2 goldens and capital-gate unit tests (at most 5 files).
- Acceptance: MLP3-A03,MLP3-A06. Verify: V01 and focused fee tests. OPEN_COST_CAP with economics NONE still requires explicit fees; no target/risk fabrication or duplicated algorithm.

### MLP3-T05 — Implement cost/value predicates and capacity composition

- [x] Deliver slice and independent evidence.
- Depends on: T04.
- Files/scope: `decision/p3_capital.py` (new), versioned capacity/evidence model and `tests/unit/test_p3_capital_gate.py` (new).
- Acceptance: MLP3-A03,MLP3-A04,MLP3-A08. Verify: V02. Use exact independent oracles for equality, full rejection, both caps, unknown versus unbounded, over-cap holdings and no new SELL.

### MLP3-T06 — Implement per-lot retained-basis transitions

- [x] Deliver slice and independent evidence.
- Depends on: T05.
- Files/scope: pure basis reducer, book value models, `tests/unit/test_p3_capital_basis.py` (new).
- Acceptance: MLP3-A05,MLP3-A06. Verify: V02. Consume actual selected lot allocations, conserve fen through residual/full sales, preserve explicit unknown and never credit sale profit.

### MLP3-C02 — Pure-policy acceptance

- [x] V01,V02 pass; MLP3-A03,MLP3-A04,MLP3-A06 arithmetic covered. Mutating a boundary/rounding oracle must be detected; preserve exact original files after the check.

### MLP3-T07 — Add isolated book/event storage and migration

- [x] Deliver slice and independent evidence.
- Depends on: T06.
- Files/scope: state models/repository, additive migration and `tests/integration/test_p3_storage.py` (new), at most 5 files per child.
- Acceptance: MLP3-A05. Verify: focused V03 storage cases, migration/metadata parity, backup/restore, downgrade and revision-mismatch tests on temporary SQLite. No user database.

### MLP3-T08 — Implement explicit reviewed opening/reconciliation service

- [x] Deliver slice and independent evidence.
- Depends on: T07.
- Files/scope: `state/p3_capital_service.py` (new), command/receipt/source-validation seams, `tests/integration/test_p3_opening.py` (new).
- Acceptance: MLP3-A05,MLP3-A09. Verify: focused V03. Exact current lot/revision checks, source/provenance, zero/unknown, duplicate command and tamper/restart behavior; no inventory or approval mutation. Public endpoint waits for T14.

### MLP3-T09 — Bind book mutations to actual simulation allocations

- [x] Deliver slice and independent evidence.
- Depends on: T08.
- Files/scope: `state/daily_accounting.py`, budget transaction adapter, `tests/integration/test_p3_accounting.py` (new) and existing accounting regression.
- Acceptance: MLP3-A05,MLP3-A06,MLP3-A07. Verify: focused V03 plus existing whole-simulation/accounting checks. BUY, ordinary/risk SELL, older-plan unknown-cost buys and plan-switch continuity must share one atomic inventory/book update.

### MLP3-C03 — Storage/continuity acceptance

- [x] V01,V02 and available V03 pass; MLP3-A05,MLP3-A06,MLP3-A07 storage boundaries covered. Include genuine reopen, rollback, older-binary mismatch and account isolation.

### MLP3-T10 — Extract and review monetary policies without inference

- [x] Deliver slice and independent evidence.
- Depends on: T09.
- Files/scope: sequential children: T10a nullable draft/semantic review; T10b extraction/update/prompt preservation; T10c production extraction/review tests. Each child at most 5 files; use `tests/integration/test_p3_review.py` (new).
- Acceptance: MLP3-A01,MLP3-A02. Verify: V01,V02 and focused V03. A-only source, ambiguous total-budget rejection, inherited policy preservation, source edits and no automatic opening cost; retain current extraction-size budget.

### MLP3-T11 — Compose daily runtime quantity and capital evidence

- [x] Deliver slice and independent evidence.
- Depends on: T10.
- Files/scope: versioned Schema 9 quantity/decision adapter, runtime projection, frozen evidence and `tests/integration/test_p3_runtime.py` (new); split model/runtime adapters if over5 files.
- Acceptance: MLP3-A03,MLP3-A04,MLP3-A08. Verify: focused V03 plus P0/P1/P2 policy regression. Amount-only has no fabricated share capacity, confirmation freezes q, and current budget changes cannot rearm or resize it.

### MLP3-T12 — Guard ordinary whole execution and risk bypass

- [x] Deliver slice and independent evidence.
- Depends on: T11.
- Files/scope: lifecycle/transaction guard, current-book binding and `tests/integration/test_p3_simulation.py` (new).
- Acceptance: MLP3-A07,MLP3-A08. Verify: focused V03. Current quote/book revalidation, exact post-state limit, stale preview rejection, no automatic forced SELL, actual technical-risk simulation without cost evidence.

### MLP3-C04 — Ordinary workflow acceptance

- [x] Available V01–V03,V08 pass; MLP3-A01–MLP3-A08 ordinary path covered. Risk bypass must be an executed simulation, not only a pure predicate.

### MLP3-T13 — Preserve both P1 exception authorization paths

- [x] Deliver slice and independent evidence.
- Depends on: T12.
- Files/scope: current exception authority, preview/approval service, exact-quantity adapter and `tests/integration/test_p3_exceptions.py` (new).
- Acceptance: MLP3-A04,MLP3-A07,MLP3-A08. Verify: focused V03 and existing P1 authorization tests. WEAK_MINIMUM exact minimum; BROKEN_STRONG empty/manual; no money-based clipping, new route or reserved allowance; approval and execution recheck independently.

### MLP3-T14 — Add capital read/opening/preview APIs

- [x] Deliver slice and independent evidence.
- Depends on: T13.
- Files/scope: capital router/service, DTOs and `tests/integration/test_p3_api.py` (new), at most 5 files per child.
- Acceptance: MLP3-A05,MLP3-A09. Verify: focused V03. Real HTTP same-origin/admission/idempotency, literal false authority, read-only zero writes, explicit opening receipt,409/422 and rejected caller prices/cost totals.

### MLP3-T15 — Enable complete current admission and generate contracts

- [x] Deliver slice and independent evidence.
- Depends on: T14.
- Files/scope: sequential children: T15a remaining current typed readers/source-storage adapters; T15b capability/editor/runtime DTO unions and new-route whitelist; T15c both generated OpenAPI/TypeScript profiles plus paired API-owner appendix. Each child at most 5 files with focused compatibility checks.
- Acceptance: MLP3-A02,MLP3-A09. Verify: V03,V07. Enable public current Schema 9 only after T12/T13/T14 pass; unsupported 9 frozen inputs remain rejected until T19/T20. Explicitly preserve prior routes/schemas after enumerating only new additions.

### MLP3-C05 — Exception/API acceptance

- [x] V01–V03,V07 pass; MLP3-A02,MLP3-A04,MLP3-A07,MLP3-A09 covered. Generated contracts reflect actual endpoints, not an unimplemented promise.

### MLP3-T16 — Add source-policy and opening-basis review UI

- [ ] Deliver slice and independent evidence.
- Depends on: T15.
- Files/scope: P3 API client, review/opening components and `web/tests/unit/p3Review.spec.ts` (new); split at5 files.
- Acceptance: MLP3-A02,MLP3-A05,MLP3-A09,MLP3-A11. Verify: V04 created files. Two cap meanings, amount-only/combined policy, missing source, exact lot/provenance review and independent opening confirmation; no account-cash input.

### MLP3-T17 — Show current capital limits and separate execution

- [ ] Deliver slice and independent evidence.
- Depends on: T16.
- Files/scope: runtime/exception capital component, stale-response protection, rule-specific notifications and `web/tests/unit/p3Capital.spec.ts` (new); UI and notification children separately at most 5 files.
- Acceptance: MLP3-A07,MLP3-A08,MLP3-A09,MLP3-A11. Verify: V03,V04. Frozen q versus current budget, readable reasons, no BROKEN_STRONG default, no cost prerequisite for value cap, send-time stale suppression.

### MLP3-T18 — Verify complete browser journeys

- [ ] Deliver slice and independent evidence.
- Depends on: T17.
- Files/scope: deterministic browser fixture/server, `web/tests/e2e/p3-capital.spec.ts` (new), fixture and unit repairs only if justified.
- Acceptance: MLP3-A09,MLP3-A11. Verify: V04,V05. Both modes and limit forms, unknown/reconciled basis, both exceptions, quote fail/recovery, separate approval/execution, reload and 320/768/1024/1440 overflow checks; no external network.

### MLP3-C06 — Browser/workflow acceptance

- [ ] V03–V05,V07 pass; MLP3-A05,MLP3-A07–MLP3-A09,MLP3-A11 covered with screenshots and actual request identity checks. Replay acceptance remains pending.

### MLP3-T19 — Freeze budget inputs and causal opening events

- [ ] Deliver slice and independent evidence.
- Depends on: T15; follows C06 in the selected sequential work order.
- Files/scope: sequential 3–5-file children for backtest-run-v10, scheduled/loop input readers, copied opening/reconciliation events and tests. New `tests/integration/test_p3_replay.py` owns missing/future/duplicate-event cases.
- Acceptance: MLP3-A02,MLP3-A05,MLP3-A10. Verify: focused V03 and historical input/hash tests. No live-book lookup, no fake max_qty/cash, source/scenario provenance and no change to old funding/settlement behavior.

### MLP3-T20 — Carry current policies through real frozen adapters

- [ ] Deliver slice and independent evidence.
- Depends on: T19.
- Files/scope: T20a private runtime/quantity/book seeding; T20b loop/research execution and exact sidecar continuity; T20c compact report references, integrity and publication. At most5 files per child.
- Acceptance: MLP3-A06,MLP3-A08,MLP3-A10. Verify: focused V03 plus old P1/P2 worker/accounting tests. Preserve byte budgets, exact selected-lot release and distinct research P&L; only admit Schema 9 frozen execution after the full chain is guarded.

### MLP3-T21 — Prove causal replay, races and restart

- [ ] Deliver slice and independent evidence.
- Depends on: T18,T20.
- Files/scope: `tests/integration/test_p3_replay_mutations.py`, `test_p3_concurrency.py`, `test_p3_frozen_workers.py` (new), support fixture as needed (at most 5 files).
- Acceptance: MLP3-A05,MLP3-A07,MLP3-A08,MLP3-A10. Verify: V03. Future book/quote/policy changes leave earlier prefix unchanged; real workers publish/reopen; two independent signals cannot overspend; retries, revoke/execute races and post-write fault injection have one atomic outcome.

### MLP3-C07 — Runtime/replay acceptance

- [ ] V01–V05,V07 pass; MLP3-A01–MLP3-A11 covered. Reconcile every failed case and prove current/frozen parity with explicit approval/operation events.

### MLP3-T22 — Run complete regressions without weakening gates

- [ ] Deliver slice and independent evidence.
- Depends on: T21.
- Files/scope: tests only when a failure justifies repair, paired verification-report draft. Split repairs by root cause; do not widen assertions or overwrite golden history to hide failures.
- Acceptance: MLP3-A12. Verify: V01–V08, including capacity in isolation. Record commands, revision, unique/overlapping counts, original failures, exact reruns, skipped/live exclusions and resource limits honestly.

### MLP3-T23 — Update bilingual operating/prompt/capability documents

- [ ] Deliver slice and independent evidence.
- Depends on: T22.
- Files/scope: T23a new operations pair plus verification pair (4); T23b root README pair plus docs index pair (4); T23c capability-map pair (2).
- Acceptance: MLP3-A01,MLP3-A11,MLP3-A12. Verify: V08. Clearly explain both cap meanings, explicit simulation opening basis, ordinary/exception quantities, cash independence and still-manual/unsupported original requirements. Do not mark excluded capabilities delivered.

### MLP3-T24 — Audit acceptance and prepare reviewed delivery

- [ ] Deliver slice and independent evidence.
- Depends on: T23.
- Files/scope: T24a report/task pairs (4); T24b specification/contract pairs (4); T24c scoped final Git review and Chinese Conventional Commits. Keep protected task files unchanged.
- Acceptance: MLP3-A01–MLP3-A12. Verify: V07,V08. Every criterion maps to actual tests/results; all required failures are closed before marking completion. No push/deployment under implementation authorization alone.

### MLP3-C08 — Final acceptance

- [ ] V01–V08 pass; MLP3-A01–MLP3-A12 complete. Review the complete diff, paired documents, source trace, report references, byte/budget limits, scope and commit messages. Only then mark 24 tasks/eight checkpoints complete.

## MLP3-P04 — Risks, mitigations and review boundary

| Risk | Mitigation / review condition |
| --- | --- |
| “总投入预算” could mean retained cost, cumulative purchases or net invested cash | Review D02 first; source ambiguity blocks only affected capital buying, never infer a meaning. |
| Amount-only input collides with old mandatory max_qty and capacity=None | New discriminated policy and versioned explicit capacity state; new schema only, old goldens unchanged. |
| Existing live batches have no costs; research account appears reusable | Explicit isolated opening/reconciliation; no inferred cross-account data, no automatic old-cost reconstruction. |
| Selling releases the wrong lot cost or resets under a new plan | Use exact authoritative allocations and one inventory stream; conserve residual fen; no plan-local budget reset. |
| Forecast budget versus research settlement costs diverge | Independent, labeled ledgers; shared fee math, not silently shared account values. |
| Two previews/approvals collectively exceed a cap | Preview/approval reserves nothing; execution serializes and rechecks the exact post-state atomically. |
| New cost failures accidentally block risk SELL or rearm a consumed buy | Actual risk simulation and independent-occurrence tests; budget-only predicate is BUY-scoped. |
| Frozen events/large books leak future facts or exceed result budgets | Availability/order mutation tests, real worker publication, validated references and existing bounds. |

All six decisions and this dependency map are approved; continue through all authorized stages without repeated confirmation. Record each completed check honestly. P0/P1/P2 remain the compatibility baseline; public P3 support is claimed only after the corresponding full guard chain is tested and admitted.
