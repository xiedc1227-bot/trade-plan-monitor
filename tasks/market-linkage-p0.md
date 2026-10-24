# Implementation plan and tasks: market-linkage-p0

Status: APPROVED — on 2026-10-24 the user approved all six decisions and specifications and explicitly authorized ordered implementation. Progress is governed by acceptance evidence; unfinished tasks are not shipped capability.
Progress below is tied to the paired verification report; original acceptance requirements are unchanged.
[Chinese review copy](market-linkage-p0.zh-CN.md) · [Specification package](../docs/specifications/monitoring/SPEC-market-linkage-p0.md).

Current progress: MLP-T01–MLP-T19 and MLP-C01–MLP-C07 are complete and accepted locally. All full-regression failures were resolved and rechecked; see [verification](../docs/verification/2026-10-24-market-linkage-p0.md).

## MLP-P01 — Authority and implementation approach

This topic-specific plan preserves existing task records. The user approved all six decisions and explicitly authorized implementation and staged acceptance on 2026-10-24.

Implementation follows MLP-D01–MLP-D06 and the six approved specifications. Baseline c7378a4 and applicable AGENTS.md were checked before changes. Other work is preserved.

Use existing index infrastructure and one shared decision path. Deliver strict contracts first, then pure policies, then extraction/review, durable authority, production runtime, replay and user-facing verification. Test each behavior before implementation, using independently calculated expected results. Each task targets 3–5 files; split it into sequential subtasks before editing if the exact file inventory exceeds this scope. Shared domain/lifecycle/API files are sequential ownership boundaries; no parallel agent work is authorized by this plan.

## MLP-P02 — Command catalog

All backend commands run from `trade-plan-monitor/`. Test files below are implemented; actual commands and results are in the verification report.

| ID | Command / verification |
| --- | --- |
| V01 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_linkage_contract.py -q` |
| V02 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_regime.py tests/unit/test_market_index_data.py -q` |
| V03 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_relative_strength.py -q` |
| V04 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_confirmation_selection.py -q` |
| V05 | `.\.venv\Scripts\python.exe -m pytest tests/unit/test_quantity_policy.py -q` |
| V06 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_linkage_review.py tests/unit/test_current_review_contract.py -q` |
| V07 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_linkage_storage.py -q` |
| V08 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_linkage_runtime.py tests/integration/test_unified_simulation_transactions.py -q` |
| V09 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_linkage_replay.py tests/integration/test_unified_replay_parity.py -q` |
| V10 | `.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_linkage_api.py -q` |
| V11 | `npm --prefix web run test -- --run tests/unit/marketLinkage.spec.ts` and `npm --prefix web run type-check` |
| V12 | `npm --prefix web run test:e2e -- tests/e2e/market-linkage.spec.ts` |
| V13 | `.\.venv\Scripts\python.exe -m pytest -m "not live" -q` and `.\.venv\Scripts\python.exe -m ruff check src tests` |
| V14 | `npm --prefix web run test -- --run`, `npm --prefix web run type-check`, `npm --prefix web run build` |
| V15 | Check paired section/acceptance/task IDs, numeric thresholds, enums, API paths, commands, relative links and semantic equivalence; inspect the scoped Git diff. |

Use the installed local environment; do not install dependencies to make a documentation check pass. Browser scenarios use local fixtures. Production provider calls, user-database upgrades, push and deployment require their own authorization; this task list grants none.

## MLP-P03 — Ordered implementation tasks

### MLP-T01 — Freeze boundary contracts

- [x] Inventory every reader/writer for the new linked format, exact field shapes, serializers, hashes, bounded expanded conditions, review evidence and generated API variants. Record the version/rollback matrix in paired specifications before code.
- Depends on: user approval and implementation instruction. Acceptance: MLP-D01–MLP-D06, WF-A02; no unresolved serialization or authority ambiguity remains.
- Files/scope: this package and a paired contract appendix if necessary; documentation only, S.
- Verify: V15; compare the documented inventory with actual code, not remembered architecture.

### MLP-T02 — Add explicit linked-plan models

- [x] Add strict new linked/fixed variants, derived reference identity and expanded policy validation, plus the shared pure quantity-feasibility preflight used by both routing and sizing. Reject mixed quantity forms, missing source parameters and five-minute linked confirmation; preserve existing codecs.
- Depends on: MLP-T01. Acceptance: QP-A01, CS-A05, WF-A02.
- Files/scope: new `domain/market_linkage_models.py`, draft/dispatch seam, new `tests/unit/test_market_linkage_contract.py`; M.
- Verify: V01 plus golden round trips for old Schema 1–5 and explicit rejection by unsupported readers.

### MLP-T03 — Add dated index low evidence

- [x] Extend versioned index facts with the prior-20-session minimum low and exact date requirements, preserving old fact bytes. Reuse existing MA/lookback and board mapping.
- Depends on: MLP-T02. Acceptance: MR-A01, MR-A02, MR-A04.
- Files/scope: `market_index/models.py`, `formulas.py`, `canonical.py`, focused index tests; M.
- Verify: V02; independent sequences catch including D, off-by-one windows and future revisions.

### MLP-T04 — Implement four-state policy

- [x] Add a pure priority classifier with exact operands and per-predicate unknowns; source-bound state has no effect on unlinked plans.
- Depends on: MLP-T03. Acceptance: MR-A02, MR-A03, MR-A04.
- Files/scope: new `decision/market_regime.py`, evidence model, `tests/unit/test_market_regime.py`; M.
- Verify: V02; each strict-equality and higher-state ambiguity case has an explicit expected result.

### MLP-T05 — Implement aligned relative strength

- [x] Add 5/20-session stock/index return comparison and own-day MA20 check with fixed endpoints, adjustment basis and three-valued evidence.
- Depends on: MLP-T04. Acceptance: RS-A01–RS-A04.
- Files/scope: new `decision/relative_strength.py`, evidence adapter, `tests/unit/test_relative_strength.py`; M.
- Verify: V03; include suspension gaps, mixed bases, exact equality and future-data mutations.

### MLP-T06 — Select S0/S1/S2 routes

- [x] Compose exact conditions and the six-row route table. Preserve S0 meaning, own-day MA20, necessary-only strength dependency and both persistent P1 blocks.
- Depends on: MLP-T05. Acceptance: CS-A01, CS-A02, CS-A03, CS-A05.
- Files/scope: new `decision/confirmation_selection.py`, condition composition seam, `tests/unit/test_confirmation_selection.py`; M.
- Verify: V04; each S1/S2 component independently fails and all six routes are covered.

### MLP-T07 — Calculate bounded quantities

- [x] Implement source-bound Q0, exact factors, legal floor and full-capacity blocking. Return calculation evidence without manufacturing a zero-share action.
- Depends on: MLP-T06. Acceptance: QP-A01, QP-A02, QP-A03.
- Files/scope: new `decision/quantity_policy.py`, linkage model seam, `tests/unit/test_quantity_policy.py`; M.
- Verify: V05; assert every QP03 fixture and reject incompatible market/simulation rules.

### MLP-T08 — Extract complete policies

- [x] Extend the current AI candidate/prompt boundary to preserve linked policy definitions and source evidence; derive index identity server-side and reject unsupported forms without inventing approval.
- Depends on: MLP-T07. Acceptance: WF-A01, QP-A01, CS-A05.
- Files/scope: `ai/plan_extraction.py`, `ai/extraction.py`, candidate model seam, new extraction/review fixtures/tests; M.
- Verify: V06; deterministic AI outputs cover missing Q0/S0, omitted index conditions, wrong benchmark and fake human evidence.

### MLP-T09 — Bind review and follow-up updates

- [x] Extend review/source bindings and existing preparation/update handling; expose changed policies and invalidate stale reviews. Fully represented P1 rows remain disabled, while unresolved strategy meaning blocks approval.
- Depends on: MLP-T08. Acceptance: WF-A01, WF-A02, CS-A04.
- Files/scope: `ai/daily_review.py`, current update/review seams, `tests/integration/test_market_linkage_review.py`; M.
- Verify: V06; source/content/formula edits, inherited policy changes and dropped restrictions cannot keep old approval.

### MLP-T10 — Persist immutable linked evidence

- [x] Add versioned evidence/signal storage and only necessary additive migrations; preserve old bytes/hashes, restart identity and rollback readability.
- Depends on: MLP-T09. Acceptance: WF-A02, QP-A04.
- Files/scope: state repository/model seam, additive migration if required, new `tests/integration/test_market_linkage_storage.py`; M.
- Verify: V07; temporary SQLite reopen, old/new coexistence and repeated migration tests; never use the user database.

### MLP-T11 — Acquire paired evidence in production

- [x] Wire required stock/index facts into the real owned runtime, including shared requests, exact cutoff admission, recovery and activation fencing.
- Depends on: MLP-T10. Acceptance: MR-A05, RS-A04, WF-A03.
- Files/scope: existing runtime/requirements/provider-composition seams, new `tests/integration/test_market_linkage_runtime.py`; M.
- Verify: V08; prove actual composition, shared requests, missing D behavior and rejection after activation changes.

### MLP-T12 — Enforce frozen signal and atomic quantity

- [x] Bind route/calculation to a signal; preserve independent events/windows; transactionally revalidate and consume exactly the full frozen quantity.
- Depends on: MLP-T11. Acceptance: CS-A04, CS-A05, QP-A04, QP-A05.
- Files/scope: unified lifecycle, simulation transaction and signal repository seams, runtime/transaction tests; M.
- Verify: V08; concurrency, restart, source correction, improvement, repeated commands and capacity recovery do not duplicate or resize trades.

### MLP-T13 — Fence reads and reminders

- [x] Include both evidence sets in completion-proof and send-time eligibility; expose stale/blocked reasons while keeping independent reminders unaffected.
- Depends on: MLP-T12. Acceptance: MR-A05, WF-A03.
- Files/scope: runtime proof, projection and outbox eligibility seams, runtime tests; M.
- Verify: V08; correction before send suppresses stale advice; read-only access performs no acquisition or business mutation.

### MLP-T14 — Admit frozen replay dependencies

- [x] Extend current replay input/preflight to include exact linked-policy stock/index evidence, calendars, adjustment bases and availability cutoffs.
- Depends on: MLP-T13. Acceptance: RS-A04, WF-A02, WF-A05.
- Files/scope: backtest input, index-data and replay adapter seams, new `tests/integration/test_market_linkage_replay.py`; M.
- Verify: V09; missing historical scope rejects honestly and old frozen payloads/hashes stay exact.

### MLP-T15 — Publish causal replay results

- [x] Record selected routes, sizing operands, authorization and zero-trade causes through existing result publication; prove policy parity with live adapters.
- Depends on: MLP-T14. Acceptance: WF-A05, QP-A04.
- Files/scope: backtest report/projection, publication and scenario fixtures/tests; M.
- Verify: V09; all six rows, future mutations, cancellation and restart preserve causality and atomic publication.

### MLP-T16 — Expose formal typed contracts

- [x] Extend existing request/response variants and runtime projections, regenerate the actual OpenAPI/TypeScript artifacts and test server authority.
- Depends on: MLP-T15. Acceptance: WF-A01, WF-A02, WF-A03.
- Files/scope: API schemas/service seam, generated contract artifacts, new `tests/integration/test_market_linkage_api.py`; M.
- Verify: V10; incompatible versions, stale revisions and client-supplied quantity overrides are rejected; routes stay in the existing families.

### MLP-T17 — Render review and decision explanations

- [x] Add linked policy review and runtime displays in the existing workspace, including quantities, actual comparisons and precise blocked states; render only server-authoritative effects.
- Depends on: MLP-T16. Acceptance: WF-A04.
- Files/scope: `web/src/composables/usePlanWorkspace.ts`, existing plan view/components, new `web/tests/unit/marketLinkage.spec.ts`; M.
- Verify: V11; inaccessible/unknown states have readable explanations and no unauthorized trade action; technical versions stay out of ordinary flows.

### MLP-T18 — Verify the complete user path

- [x] Add one deterministic browser journey and cross-entry scenarios for extraction through explicit activation and full simulation, plus P1-blocked and independent-reminder examples.
- Depends on: MLP-T17. Acceptance: WF-A04, WF-A05, QP-A05.
- Files/scope: new `web/tests/e2e/market-linkage.spec.ts`, local fixtures and focused integration scenarios; M.
- Verify: V12 and V08–V10; capture actual outputs, console/network errors and isolation assertions.

### MLP-T19 — Reconcile documentation and release evidence

- [x] Run the regression/build gates; review the diff and evidence; update paired prompt/capability/operations documentation and write a bilingual verification report with actual limitations.
- Depends on: MLP-T18. Acceptance: WF-A06 and all module acceptance IDs.
- Files/scope: paired README prompt, capability map, operations/report and task completion records; split into documentation-only subtasks if needed, M.
- Verify: V13–V15 and browser evidence; no passing claim for tests not run or provider scopes not certified. Update unsupported-capability wording only for the accepted implemented routes.

## MLP-P04 — Checkpoints and traceability

| Checkpoint | After tasks | Required result before continuation |
| --- | --- | --- |
| MLP-C01 | MLP-T01–MLP-T03 | Exact contract inventory and compatibility/evidence tests; no implicit upgrades |
| MLP-C02 | MLP-T04–MLP-T06 | State, strength and route truth tables pass independently |
| MLP-C03 | MLP-T07–MLP-T09 | Correct sizing and complete source/review binding; no strategy guessing |
| MLP-C04 | MLP-T10–MLP-T12 | Durable real runtime and atomic full-quantity simulation pass |
| MLP-C05 | MLP-T13–MLP-T15 | Read/send authority and frozen replay parity pass |
| MLP-C06 | MLP-T16–MLP-T18 | Formal API and real browser journey pass |
| MLP-C07 | MLP-T19 | Complete acceptance evidence, bilingual parity and honest release boundaries |

A failed checkpoint requires scoped repair, never skipped assertions or lower thresholds. After implementation has been authorized, routine passing checkpoints do not require renewed permission; scope/strategy changes require a specification amendment. The task acceptance references are the traceability map: MR → MLP-T03/T04/T11/T13; RS → MLP-T05/T11/T14; CS → MLP-T02/T06/T09/T12; QP → MLP-T02/T07/T08/T10/T12/T15/T18; WF → MLP-T01/T02/T08–MLP-T19.

## MLP-P05 — Review handoff

Implementation follows MLP-D01–MLP-D06 and the six approved specifications. Baseline c7378a4 and applicable AGENTS.md were checked before changes. Other work is preserved.

Implementation and local verification are recorded in the paired report. A checkbox denotes accepted task evidence, not live-provider certification or deployment.
