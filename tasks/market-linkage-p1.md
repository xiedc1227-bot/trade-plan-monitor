# Implementation plan and tasks: market-linkage-p1

Status: APPROVED — on 2026-10-24 the user approved the [specification](../docs/specifications/monitoring/SPEC-market-linkage-p1.md), all six decisions and ordered implementation with staged testing and acceptance. Progress is tied to executed verification. [Chinese review copy](market-linkage-p1.zh-CN.md).

## MLP1-P01 — Authority, sequencing and scope

The user has approved MLP1-D01–MLP1-D06 and explicitly instructed P1 implementation. This topic-specific plan follows the existing `tasks/market-linkage-p0.md` convention and leaves unrelated `tasks/plan.md` and `tasks/todo.md` intact. Baseline for review is `dbeff32`; recheck the actual working tree and baseline when implementation begins.

Retain the existing module boundaries. Deliver the two exception routes through one production authority chain, with shared eligibility/quantity policies. Do not build a second plan workspace or delegate parallel agents under this plan. The ordered tasks below can proceed without repeated user confirmation once their decisions and implementation are authorized. A failed checkpoint blocks its dependent work until repaired; a changed strategy decision needs a bilingual amendment and user review.

Before each behavior change, write a failing test with independent expected outcomes, then implement and run the focused tests. Use temporary SQLite and deterministic providers. Each implementation slice targets 3–5 files; if its exact inventory exceeds 5, record sequential subtasks before editing. File lists identify ownership seams, not permission to rewrite entire subsystems. New paths below are proposed deliverables and are not present/passing tests today. Keep the application usable after each slice; new routes remain unavailable until their authority chain is complete.

## MLP1-P02 — Verification command catalog

Run from `trade-plan-monitor/` with the installed environment. New exception test files will be created by their owning tasks. Commands are future verification requirements, not results from this documentation turn.

| ID | Command / check |
| --- | --- |
| V01 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_linkage_contract.py tests/unit/test_market_regime.py tests/unit/test_relative_strength.py tests/unit/test_confirmation_selection.py tests/unit/test_quantity_policy.py -q` |
| V02 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_exception_contract.py -q` |
| V03 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_exception_policy.py tests/unit/test_market_exception_quantity.py -q` |
| V04 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_exception_review.py tests/integration/test_market_exception_updates.py tests/integration/test_market_linkage_review.py -q` |
| V05 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_exception_storage.py -q` |
| V06 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_exception_authorization.py tests/integration/test_market_exception_concurrency.py -q` |
| V07 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_exception_runtime.py tests/integration/test_market_exception_simulation.py tests/integration/test_unified_simulation_transactions.py -q` |
| V08 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_exception_api.py tests/integration/test_market_linkage_api.py -q` |
| V09 | `npm --prefix web run test -- --run tests/unit/marketExceptionReview.spec.ts tests/unit/marketExceptionRuntime.spec.ts` and `npm --prefix web run type-check` |
| V10 | `npm --prefix web run test:e2e -- tests/e2e/market-linkage.spec.ts tests/e2e/market-exceptions.spec.ts` |
| V11 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_exception_replay.py tests/integration/test_market_exception_replay_mutations.py tests/integration/test_market_linkage_replay.py tests/integration/test_unified_replay_parity.py -q` |
| V12 | `.\.venv\Scripts\python.exe -m pytest -m "not live" -q` |
| V13 | `npm --prefix web run test -- --run`, `npm --prefix web run type-check`, `npm --prefix web run build` |
| V14 | `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` (both API profiles) |
| V15 | `.\.venv\Scripts\python.exe -m ruff check src tests` and `git diff --check` |
| V16 | Inspect paired section/decision/acceptance/task IDs, numerical constraints, enums, API paths, commands, links and semantic equivalence; record exact scope and results. |

Use the relevant file subset while a task is creating the remaining tests in a command group; run the full group at its checkpoint. Generate contracts during implementation with `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py`, then verify V14. No dependency installation, user-database mutation, real provider/AI/Webhook calls, push or deployment is authorized by this plan.

## MLP1-P03 — Ordered implementation tasks

### MLP1-T01 — Freeze the P1 boundary inventory

- [x] Inventory plan/draft/extraction/update/review/state/runtime/notification/API/replay readers and writers; verify proposed versions and exact authority fields; document the old/new hash and rollback matrix in both specification copies.
- Depends on: user approval and implementation instruction. Acceptance: no open quantity/authority/version ambiguity; trace MLP1-A01, MLP1-A05 and MLP1-A14.
- Files/scope: paired P1 specification, optional paired contract appendix; S–M, documentation only.
- Verify: V01 baseline and V16; record baseline failures without hiding them.

### MLP1-T02 — Add strict opt-in plan contracts

- [x] Add Schema 7 policy/route variants, draft dispatch and exact review hashing; preserve Schema 1–6 round trips and Schema 6 `BLOCK_P1`; missing flags never grant permission.
- Depends on: MLP1-T01. Acceptance: MLP1-A01; invalid mixed/fixed/policy forms, bounds and unsupported reader behavior covered.
- Files/scope: `domain/market_exception_models.py` (new), codec/draft/hash seams, `tests/unit/test_market_exception_contract.py`; M, split dispatch seams if needed.
- Verify: V02 and existing golden fixtures; V01 remains green.

### MLP1-T03 — Implement eligibility and quantity policies

- [ ] Extend shared selection with both exception routes and pure quantity validation; make candidate eligibility distinct from approval; preserve every ordinary route and calculate without hidden clocks/providers.
- Depends on: MLP1-T02. Acceptance: MLP1-A02–MLP1-A03, every MLP1-Q01–MLP1-Q12 row, exact/unknown/incompatible-grid edges.
- Files/scope: `decision/confirmation_selection.py`, `decision/market_exception_policy.py` (new), shared quantity seam, two new V03 unit test files; M.
- Verify: V03 and V01; independent arithmetic fixtures include legal broken-route values above and below half Q0.

### MLP1-C01 — Contract and arithmetic checkpoint

- [ ] V01–V03 and V16 pass; trace MLP1-A01–MLP1-A03. Both routes are representable but no test or production adapter may infer approval. Old plans retain exact bytes and behavior.

### MLP1-T04 — Bind extraction and review to source permission

- [ ] Extend extraction/review with complete per-route semantics, source bindings and deliberate disabled states; reject fabricated approval, negated permission and missing definitions; no broken-route quantity inference.
- Depends on: MLP1-C01. Acceptance: MLP1-A04–MLP1-A05; Chinese and English sources produce equivalent authority boundaries.
- Files/scope: `ai/plan_extraction.py`, `ai/daily_review.py`, `ai/semantic_validation.py`, policy definition seam, `tests/integration/test_market_exception_review.py`; M.
- Verify: relevant V04 tests, malformed/negative source cases and existing review regression.

### MLP1-T05 — Preserve permission through updates and preparation

- [ ] Carry exact route permission through full updates, patches, preparation and inheritance; permission changes require fresh review; importing/copying a plan never copies occurrence approvals.
- Depends on: MLP1-T04. Acceptance: MLP1-A01, MLP1-A04; no fallback to fixed rules or older linked format and no inherited live grant.
- Files/scope: `ai/plan_update_extraction.py`, `ai/preparation_wire.py`, `ai/predecessor_patch.py`, update review seam, `tests/integration/test_market_exception_updates.py`; M.
- Verify: full V04; cover enabled→disabled, disabled→enabled, missing fields, stale review and plan clones.

### MLP1-T06 — Persist immutable candidates and authorization events

- [ ] Add versioned candidate/event models, unique occurrence/command constraints, verified hashes and durable projections; test additive storage and rollback with temporary databases; no changes to user databases.
- Depends on: MLP1-T02, MLP1-T03. Acceptance: MLP1-A01, MLP1-A06–MLP1-A07; restart preserves PENDING and terminal history without new opportunities.
- Files/scope: new state model/repository modules, existing repository transaction/migration seams, `tests/integration/test_market_exception_storage.py`; M, split migration if needed.
- Verify: V05, corruption/unsupported-version tests and byte-identical old state fixtures.

### MLP1-C02 — Source and durable-state checkpoint

- [ ] V04–V05 and V16 pass; trace MLP1-A04–MLP1-A06 and storage part of MLP1-A07. Every grant still requires an explicit local command; no approved event comes from source, plan copies or startup.

### MLP1-T07 — Implement preview and exact approval commands

- [ ] Build server previews and approval/rejection services with exact digest/revision binding, server receipt time, explicit reasons, full quantity checks and command receipts; atomically freeze quantity on first approval.
- Depends on: MLP1-C02. Acceptance: MLP1-A05–MLP1-A07; empty broken quantity cannot approve; invalid/stale previews and unknown capacity fail closed.
- Files/scope: new exception application service, typed command models, repository seam, `tests/integration/test_market_exception_authorization.py`; M.
- Verify: relevant V06 tests; prove approval leaves inventory unchanged and only the exact displayed quantity is accepted.

### MLP1-T08 — Enforce terminal lifecycle and concurrent commands

- [ ] Implement revocation, expiry and invalidation without reopening occurrences; guard duplicate commands and concurrent approval/revoke attempts with durable constraints and atomic revisions.
- Depends on: MLP1-T07. Acceptance: MLP1-A06–MLP1-A08; holidays, delayed evidence, backdating, quantity change and cross-plan/route reuse are covered.
- Files/scope: exception service/repository, existing independent-signal authority seam, `tests/integration/test_market_exception_concurrency.py`, V06 authorization tests; M.
- Verify: full V06 using real temporary SQLite, injected transaction failures and fresh-process reopen; execution races are completed in MLP1-T10.

### MLP1-T09 — Connect owned runtime and reminder authority

- [ ] Production composition persists eligible candidates and exposes only current authority; reuse existing data collection and cutoff; bind read/completion/send checks and stable reminders to candidate/approval state.
- Depends on: MLP1-T08. Acceptance: MLP1-A06, MLP1-A08; corrected consumed facts invalidate, harmless refetches do not; ordinary/five-minute paths remain independent.
- Files/scope: `runtime/daily_service.py`, `state/market_linkage_authority.py`, completion/read seam, outbox/send seam, `tests/integration/test_market_exception_runtime.py`; M, split adapter seams if needed.
- Verify: relevant V07 tests with actual production composition, provider fakes, stale notification races and restart.

### MLP1-C03 — Per-occurrence authorization checkpoint

- [ ] V05–V07 applicable files and V16 pass; trace MLP1-A05–MLP1-A08. Both routes have durable approval and all terminal states; no inventory mutation or automatic approval results from runtime/reminders.

### MLP1-T10 — Consume approval with whole simulated execution

- [ ] Integrate approved frozen quantity with existing simulation; revalidate all current gates and atomically consume approval, signal and inventory; enforce rejection/revocation versus execution ordering.
- Depends on: MLP1-C03. Acceptance: MLP1-A07–MLP1-A09; capacity recovery never resizes, repeated commands do not fill twice, no window extension.
- Files/scope: `state/simulation.py`, lifecycle/authority seam, exception repository, `tests/integration/test_market_exception_simulation.py`, V06 concurrency tests; M.
- Verify: full V06–V07; test races from separate connections, crash before/after commit, same/different command keys and inventory isolation.

### MLP1-T11 — Expose typed API commands and runtime views

- [ ] Add the three proposed command families and Schema 7 runtime projections; retain existing guard/error/idempotency conventions; reject client-supplied grants and expose service failures honestly.
- Depends on: MLP1-T10. Acceptance: MLP1-A05, MLP1-A10; exact paths, required fields, status codes and ordinary projections match the reviewed inventory.
- Files/scope: new `web/routers/plan_exceptions.py`, `web/routers/daily_plans.py`, service/composition registration seams, `tests/integration/test_market_exception_api.py`; M.
- Verify: V08 including cross-origin, forged identity, malformed quantities, unavailable storage and approval/execute separation.

### MLP1-T12 — Generate and verify both client contracts

- [ ] Generate the two OpenAPI and two TypeScript artifacts from server models; compare old projections and strict new command variants; never hand-edit generated types to hide a server mismatch.
- Depends on: MLP1-T11. Acceptance: MLP1-A01, MLP1-A10; exact snapshot hashes and compatibility differences are recorded.
- Files/scope: `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, contract tests; M.
- Verify: V08, V14 and frontend type-check; fix generators/models in a separately recorded small slice if necessary.

### MLP1-C04 — Complete backend authority checkpoint

- [ ] V06–V08, V14–V16 pass; trace MLP1-A05–MLP1-A10. A complete local service journey approves an exact quantity and separately consumes it once; every bypass/race has a negative assertion.

### MLP1-T13 — Show plan-level route permissions in review

- [ ] Extend the existing plan review to show independently enabled/disabled routes, complete conditions and different quantity rules; editing permission invalidates review; no occurrence approval in this screen.
- Depends on: MLP1-C04. Acceptance: MLP1-A04, MLP1-A10–MLP1-A11; readable user labels and server source bindings, no technical version picker.
- Files/scope: `web/src/components/plans/ExplicitPlanReviewPanel.vue`, `web/src/composables/usePlanWorkspace.ts`, focused exception review component/helper, `web/tests/unit/marketExceptionReview.spec.ts`; M.
- Verify: relevant V09 tests and type-check; source omissions and disabled paths remain visible.

### MLP1-T14 — Build per-occurrence approval and revocation interaction

- [ ] Render eligibility/evidence, read-only weak quantity, initially empty broken quantity, reason and exact preview; support approval/rejection/revocation and a separate simulation action with terminal/stale/error states.
- Depends on: MLP1-T13. Acceptance: MLP1-A05–MLP1-A06, MLP1-A10–MLP1-A11; no auto submit/resize, retry reuses command identity and no server decision is recomputed in Vue.
- Files/scope: new exception runtime component/composable, existing workspace integration, `web/tests/unit/marketExceptionRuntime.spec.ts`; M.
- Verify: full V09; keyboard/focus behavior, in-flight duplicate clicks, capacity changes, expiry and service unavailability.

### MLP1-T15 — Verify both browser journeys

- [ ] Test source→review→activation→eligible candidate→preview→approval→separate whole simulation for both routes; also reject/revoke, stale preview, retry/restart, missing evidence and old ordinary paths.
- Depends on: MLP1-T14. Acceptance: MLP1-A11; actual local server/API with synthetic data and healthy event-stream behavior, no browser-only authorization mock.
- Files/scope: `web/tests/e2e/market-exceptions.spec.ts`, local backend fixture and existing `market-linkage.spec.ts` where needed; M.
- Verify: V10; retain useful screenshots/logs, inspect quantity/evidence displays and prove approval itself leaves inventory unchanged.

### MLP1-C05 — User workflow checkpoint

- [ ] V09–V10 and V13 pass; trace MLP1-A10–MLP1-A11. Both exception journeys and terminal/error paths work in a real browser; old plans and independent reminders still work.

### MLP1-T16 — Freeze authorization events in research inputs

- [ ] Add versioned research input and integrity-checked event streams with recorded versus hypothetical provenance; preserve old runs, enforce cutoff/identity admission and keep current local approvals inaccessible to workers.
- Depends on: MLP1-T10, MLP1-T12. Acceptance: MLP1-A01, MLP1-A12; no events means no exception grants; future events are not usable early.
- Files/scope: `backtest/run_input.py`, `backtest/loop_dataset.py`, serialization/admission seams, `tests/integration/test_market_exception_replay.py`; M.
- Verify: relevant V11 tests and old research golden fixtures; corruption, unsupported event types, wrong plan and missing historical calendar/grid scope reject explicitly.

### MLP1-T17 — Replay the shared authority and execution lifecycle

- [ ] Feed frozen events into the shared policies in deterministic time order; approval alone does not fill; operation scripts, original windows and full execution gates remain necessary; label research assumptions in results.
- Depends on: MLP1-T16. Acceptance: MLP1-A09, MLP1-A12; runtime/replay parity under identical inputs and empty-event zero-trade results.
- Files/scope: `backtest/runner.py`, `backtest/loop_runner.py`, plan schedule/result projection seams, V11 replay tests; M.
- Verify: relevant V11 tests covering both routes, rejected/revoked/late events and local/backtest inventory isolation.

### MLP1-T18 — Prove replay causality and update compatibility

- [ ] Add mutation tests for future approval/revocation, corrected prices/basis, updated plans, changed quantities and repeated events; verify both replay entry paths, preparation/updates and result provenance.
- Depends on: MLP1-T17. Acceptance: MLP1-A04, MLP1-A08, MLP1-A12; no hindsight authority, silent policy downgrade or live-grant export.
- Files/scope: `tests/integration/test_market_exception_replay_mutations.py`, V11 replay/parity tests and focused update/result fixtures; M.
- Verify: full V11; explicit pre-cutoff outputs remain equal after future mutations while affected later decisions change correctly.

### MLP1-C06 — Frozen replay checkpoint

- [ ] V11 and V14–V16 pass; trace MLP1-A01, MLP1-A04, MLP1-A08–MLP1-A09 and MLP1-A12. Missing or hypothetical approval is reported honestly; all runtime/replay comparisons use frozen inputs.

### MLP1-T19 — Complete backend regression and failure repair

- [ ] Run all non-live backend tests and quality checks; repair failures without reducing coverage/assertions and rerun affected scopes; retain commands, counts, durations, skips and limitations in paired verification reports.
- Depends on: MLP1-C05, MLP1-C06. Acceptance: MLP1-A13 and all backend acceptance IDs; no unresolved failure may be described as complete.
- Files/scope: paired dated `docs/verification/*-market-linkage-p1.md` reports and scoped evidence; fixes become separately recorded 3–5-file slices.
- Verify: V12 and V15; distinguish pre-existing/environmental failures and any truly unexecuted checks.

### MLP1-T20 — Complete frontend and generated-contract acceptance

- [ ] Run the full frontend suite, type-check, production build, browser journeys and generated checks; inspect final screens, original routes and error handling; append exact results to both verification reports.
- Depends on: MLP1-T19. Acceptance: MLP1-A10–MLP1-A11, MLP1-A13; no stale generated output or browser-only success claim.
- Files/scope: paired verification reports and scoped browser evidence; necessary repairs use small sequential slices.
- Verify: V10, V13–V15; repeat affected tests after any repair, not merely after documentation edits.

### MLP1-T21 — Reconcile documentation and final acceptance

- [ ] Complete the following documentation substeps in order: T21a, paired P1 operations guide and README capability/prompt text; T21b, paired capability map and documentation index; T21c, paired P1 specification and task status; T21d, paired final verification report and scoped diff review. Each substep changes at most 4 documentation files.
- Depends on: MLP1-T20. Acceptance: MLP1-A14; every MLP1-A01–MLP1-A14 links to actual evidence; no proposed capability is presented as shipped before acceptance.
- Files/scope: the named bilingual pairs; four sequential S–M documentation slices. Preserve P0 history and unrelated work.
- Verify: V16 and `git diff --check`; confirm no dependency/threshold weakening, accidental user data or secrets. Do not infer authorization to push, deploy or migrate a user database.

### MLP1-C07 — P1 completion checkpoint

- [ ] MLP1-T01–MLP1-T21 and all fourteen acceptance criteria have passing, bilingual, traceable evidence; both routes, quantity examples, approval lifecycle, full simulation and frozen replay are accepted. Record remaining live-certification limits separately. Only now may the implementation be reported as complete.

## MLP1-P04 — Acceptance traceability

| Acceptance IDs | Owning tasks | Checkpoints |
| --- | --- | --- |
| MLP1-A01–MLP1-A03 | MLP1-T01–MLP1-T03; compatibility again in MLP1-T12 and MLP1-T16 | MLP1-C01, MLP1-C04, MLP1-C06 |
| MLP1-A04 | MLP1-T04–MLP1-T05, MLP1-T13, MLP1-T18 | MLP1-C02, MLP1-C05, MLP1-C06 |
| MLP1-A05–MLP1-A08 | MLP1-T06–MLP1-T10, MLP1-T14, MLP1-T18 | MLP1-C02–MLP1-C04, MLP1-C06 |
| MLP1-A09 | MLP1-T10, MLP1-T17 | MLP1-C04, MLP1-C06 |
| MLP1-A10–MLP1-A11 | MLP1-T11–MLP1-T15, MLP1-T20 | MLP1-C04–MLP1-C05, MLP1-C07 |
| MLP1-A12 | MLP1-T16–MLP1-T18 | MLP1-C06 |
| MLP1-A13–MLP1-A14 | MLP1-T19–MLP1-T21 | MLP1-C07 |

## MLP1-P05 — Risks and review conditions

| Risk | Mitigation / evidence |
| --- | --- |
| “Minimum exception” becomes general upward rounding | Exact official minimum only, ordinary/exception separation, incompatible-minimum and over-Q0 negative fixtures |
| Broken-market quantity gets an implicit half/full default | Empty input, explicit legal quantity and exact preview; MLP1-D03 requires review |
| Plan review or technical fact is mistaken for approval | Distinct plan permission and per-occurrence event, strict import/API boundaries, browser and service bypass tests |
| Reapproval or plan copy bypasses independent-signal limits | Stable occurrence continuity, terminal states, cross-version and concurrency tests |
| Corrected evidence or stale reminder exposes invalid authority | Consumed-evidence binding, read/send/execute fencing and receipt-only continuity tests |
| Historical evaluation assumes human consent | Frozen events, missing-event zero fills, explicit research provenance and future-mutation tests |
| Broad contract change damages old plans | New explicit versions, exact legacy fixtures, unsupported reader rejection and rollback preservation |

MLP1-D01–MLP1-D06 are approved. Completed checks are recorded in the paired [verification report](../docs/verification/2026-10-24-market-linkage-p1.md); unchecked tasks remain incomplete.
