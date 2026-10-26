# Implementation plan and tasks: market-linkage-p2

Status: IMPLEMENTING — 2026-10-26. User approved all six decisions and implementation. Task/checkpoint marks and the verification report record actual completion. [Chinese review copy](market-linkage-p2.zh-CN.md) · [Specification](../docs/specifications/monitoring/SPEC-market-linkage-p2.md).

## MLP2-P01 — Authority and working method

MLP2-D01–MLP2-D06 and implementation are authorized. Baseline is 8db00c425706945d69a39ae0d3ffe1d85348d626; recheck the workspace before implementation. Preserve tasks/plan.md and tasks/todo.md; no parallel workflow or delegated agents.

Write failing tests with independent expected outcomes before changing behavior. Target 3–5 files per slice; listed seams are ownership, not permission for wholesale rewrites. If more than 5 files are needed, record sequential subtasks before editing. Repair failed checkpoints before dependent work; changed strategy semantics require a bilingual amendment and review. Parallelizable dependencies do not authorize spawning agents.

## MLP2-P02 — Verification commands

Run from trade-plan-monitor/. All p2 test files are proposed and created by their owning tasks; an empty selection is not a pass. During development use explicit created files; checkpoints run the entire relevant group. Use temporary SQLite, deterministic providers and frozen fixtures, never user databases for acceptance.

| ID | Command / check |
| --- | --- |
| V01 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_quantity_policy.py tests/unit/test_market_exception_contract.py tests/unit/test_market_exception_policy.py tests/unit/test_market_exception_quantity.py -q` |
| V02 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_p2_policy_contract.py tests/unit/test_p2_sizing.py tests/unit/test_p2_economics.py tests/unit/test_p2_composition.py -q` |
| V03 | `.\.venv\Scripts\python.exe -m pytest tests/integration -k p2 -q` |
| V04 | `npm --prefix web run test -- --run tests/unit/p2Review.spec.ts tests/unit/p2Runtime.spec.ts`; `npm --prefix web run type-check` |
| V05 | `npm --prefix web run test:e2e -- tests/e2e/p2-pretrade.spec.ts tests/e2e/market-exceptions.spec.ts tests/e2e/market-linkage.spec.ts` |
| V06 | `.\.venv\Scripts\python.exe -m pytest -m "not live" -q`; `npm --prefix web run test -- --run`; `npm --prefix web run build` |
| V07 | `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` (both API profiles); `.\.venv\Scripts\python.exe -m ruff check src tests`; `git diff --check` |
| V08 | Bilingual sections/IDs/enums/formulas/units/boundaries/links agree; trace each original clause to tasks, tests and actual results. |

## MLP2-P03 — Ordered implementation tasks

### MLP2-T01 — Freeze contracts and source inventory

- [x] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: approval / 批准.
- Files / scope: paired spec + proposed CONTRACT-market-linkage-p2 pair; original-source fixtures.
- Acceptance: MLP2-A01, MLP2-A02. Verify: V01,V08.

### MLP2-T02 — Add strict versioned policy models and arithmetic validation

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T01.
- Files / scope: domain/p2_policy_models.py (new), domain codecs, tests/unit/test_p2_policy_contract.py (new).
- Acceptance: MLP2-A02, MLP2-A03. Verify: V02.

### MLP2-T03 — Integrate Schema 8 dispatch, old-reader rejection and review hashes

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T02.
- Files / scope: draft/version dispatch, source binding models, existing codec golden tests.
- Acceptance: MLP2-A02. Verify: V01,V02.

### MLP2-C01 — Stage acceptance

- [ ] V01,V02 pass; cover MLP2-A02.
- Check all tests available at this stage, historical compatibility and authority boundaries; explicitly record not-yet-created downstream tests as unexecuted. Record commands, code revision, results, failure repairs and limits; partial success is not full acceptance.

### MLP2-T04 — Implement source-defined ATR tiers and legal Q0 floor

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T03.
- Files / scope: decision/p2_sizing.py (new), quantity adapter, tests/unit/test_p2_sizing.py (new).
- Acceptance: MLP2-A03, MLP2-A04. Verify: V02.

### MLP2-T05 — Implement exact fee preview and explicit numeric gates

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T03.
- Files / scope: decision/p2_economics.py (new), cost value models, tests/unit/test_p2_economics.py (new).
- Acceptance: MLP2-A05, MLP2-A06. Verify: V02.

### MLP2-T06 — Compose sizing, market routes and exception quantity preview

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T04,T05.
- Files / scope: decision/market_linkage.py, decision/market_exception_policy.py, tests/unit/test_p2_composition.py (new).
- Acceptance: MLP2-A04, MLP2-A07. Verify: V01,V02.

### MLP2-C02 — Stage acceptance

- [ ] V01,V02 pass; cover MLP2-A03–A07.
- Check all tests available at this stage, historical compatibility and authority boundaries; explicitly record not-yet-created downstream tests as unexecuted. Record commands, code revision, results, failure repairs and limits; partial success is not full acceptance.

### MLP2-T07 — Extend A-only extraction and reviewable source evidence

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T06.
- Files / scope: ai/plan_extraction.py, review seams, tests/integration/test_p2_review.py (new).
- Acceptance: MLP2-A01, MLP2-A02. Verify: V03.

### MLP2-T08 — Persist frozen policy evidence with additive migration

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T07.
- Files / scope: state authority models/repository, migration (new), tests/integration/test_p2_storage.py (new).
- Acceptance: MLP2-A02, MLP2-A09. Verify: V03.

### MLP2-T09 — Apply runtime confirmation, corrections and window invariants

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T08.
- Files / scope: runtime/daily_service.py, signal lifecycle adapter, tests/integration/test_p2_runtime.py (new).
- Acceptance: MLP2-A03, MLP2-A07, MLP2-A08. Verify: V03.

### MLP2-C03 — Stage acceptance

- [ ] V03,V08 pass; cover MLP2-A01,A02,A07,A08,A09.
- Check all tests available at this stage, historical compatibility and authority boundaries; explicitly record not-yet-created downstream tests as unexecuted. Record commands, code revision, results, failure repairs and limits; partial success is not full acceptance.

### MLP2-T10 — Guard exception approval and atomic simulation using current economics

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T09.
- Files / scope: runtime/market_exceptions.py, simulation transaction seam, tests/integration/test_p2_simulation.py (new).
- Acceptance: MLP2-A07, MLP2-A08, MLP2-A09. Verify: V03.

### MLP2-T11 — Add read-only preview API and runtime projection

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T10.
- Files / scope: web preview router (new), response models, tests/integration/test_p2_api.py (new); generated contracts in a separate subtask.
- Acceptance: MLP2-A09. Verify: V03,V07.

### MLP2-T12 — Add evidence and policy review UI

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T11.
- Files / scope: web/src plan editor, policy component (new), API client, web/tests/unit/p2Review.spec.ts (new).
- Acceptance: MLP2-A02, MLP2-A11. Verify: V04.

### MLP2-C04 — Stage acceptance

- [ ] V03,V04,V07 pass; cover MLP2-A02,A07,A08,A09,A11.
- Check all tests available at this stage, historical compatibility and authority boundaries; explicitly record not-yet-created downstream tests as unexecuted. Record commands, code revision, results, failure repairs and limits; partial success is not full acceptance.

### MLP2-T13 — Explain runtime tiers, fees, gates and separate exception action

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T12.
- Files / scope: web/src runtime/exception components, notification projection, web/tests/unit/p2Runtime.spec.ts (new).
- Acceptance: MLP2-A07, MLP2-A08, MLP2-A11. Verify: V04.

### MLP2-T14 — Carry frozen P2 evidence through replay inputs and runtime adapters

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T10.
- Files / scope: backtest input/version adapter, shared policy adapter, tests/integration/test_p2_replay.py (new).
- Acceptance: MLP2-A02, MLP2-A10. Verify: V03.

### MLP2-T15 — Prove no-lookahead, restart/concurrency and browser journeys

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T13,T14.
- Files / scope: tests/integration/test_p2_replay_mutations.py (new), tests/integration/test_p2_concurrency.py (new), web/tests/e2e/p2-pretrade.spec.ts (new).
- Acceptance: MLP2-A09, MLP2-A10, MLP2-A11. Verify: V03,V05.

### MLP2-C05 — Stage acceptance

- [ ] V03,V04,V05 pass; cover MLP2-A07–A11.
- Check all tests available at this stage, historical compatibility and authority boundaries; explicitly record not-yet-created downstream tests as unexecuted. Record commands, code revision, results, failure repairs and limits; partial success is not full acceptance.

### MLP2-T16 — Run complete regressions and reconcile every failure

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T15.
- Files / scope: test repairs only when justified; paired verification report (new).
- Acceptance: MLP2-A12. Verify: V01–V08.

### MLP2-T17 — Update bilingual prompt, operations and capability boundaries

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T16.
- Files / scope: README pair, operations pair, capability map pair (split into paired subtasks).
- Acceptance: MLP2-A01, MLP2-A12. Verify: V08.

### MLP2-T18 — Audit acceptance matrix and prepare reviewed delivery

- [ ] Deliver this slice and its independent tests, retaining every specification boundary.
- Depends on: T17.
- Files / scope: paired specification/tasks/report; scoped Git diff.
- Acceptance: MLP2-A01–A12. Verify: V07,V08.

### MLP2-C06 — Stage acceptance

- [ ] V01–V08 pass; cover MLP2-A01–A12.
- Check all tests available at this stage, historical compatibility and authority boundaries; explicitly record not-yet-created downstream tests as unexecuted. Record commands, code revision, results, failure repairs and limits; partial success is not full acceptance.

## MLP2-P04 — Delivery evidence and stop conditions

The final bilingual report maps MLP2-A01–MLP2-A12 to test names, executed commands, outcomes and limits; never prefill passes. Retain P0/P1 authority, quantity, cost and replay golden fixtures. Repair failures or explicitly record acceptance as unmet; do not lower existing gates.

Ask the user only when new strategy thresholds, ambiguous fee meaning, incompatible historical authority or an out-of-scope requirement cannot be resolved within approved boundaries. Diagnose and repair environment/test failures first; do not repeatedly request existing authorization. Unverified official fee references must not be presented as current market facts; explicit synthetic fixtures may complete non-live acceptance with market-data certification excluded.

Delivery includes paired specification/contract/tasks/operations/verification, code/tests, generated contracts and commits following the project's Chinese Conventional Commit format. User-database migration, live providers/notifications, deployment and push are outside this plan's authorization. This turn delivers review documents only.

