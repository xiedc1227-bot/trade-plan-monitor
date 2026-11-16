# Specification: plan-monitor-assurance

Status: APPROVED FOR IMPLEMENTATION — 2026-10-27. The user approved PMA-D01–D06 and ordered all implementation tasks and staged acceptance. Real extraction is authorized within the shared48-attempt ceiling. User database migration remains prohibited; actual progress is recorded in the task pair and verification report.

Canonical English · [Chinese review copy](SPEC-plan-monitor-assurance.zh-CN.md) · [implementation plan/tasks](../../../tasks/plan-monitor-assurance.md).

Later scope delta: **PBS-FP-D01 approved on 2026-11-16, Asia/Shanghai; implementation and acceptance remain pending**. PMA-S09 records the narrowly authorized new Schema10 preparation/composition path; it does not change historical decisions, old frozen admission or task/checkpoint completion.

## PMA-S01 — Objective and evidence

Make a plan's suitability for monitoring explicit through three separate questions: did every material source obligation survive extraction; does the exact extraction version pass a representative, independently annotated corpus; and is this exact saved plan receiving valid current evaluation and notification service? `SUCCEEDED`, zero existing review issues, `ACTIVE`, and passing offline tests answer none of these questions alone.

The 2026-10-27 read-only investigation reproduced the following on the P3 baseline `a5546ad`: a valid Schema9 fixture has145 source clauses,128 bindings and zero issues. Appending either “Only buy when turnover exceeds 3 percent.” or “仅当换手率超过3%时才允许买入。” and marking the new clause `CONTEXT/COMMENTARY`, with no paths and a nonempty reason, leaves146 clauses,128 bindings and zero issues. The candidate remains structurally executable; no activation was performed. See `ai/daily_review.py` and `ai/source_resolution.py`. This is a demonstrated validation blind spot, not evidence that a particular user's current plan has that omission.

The same read-only inspection found three local Schema5/v9 reminder plans, each with one alert and zero ordinary/risk rules; one was active. Its source intentionally defines an observation plan. Local migration head was0026, while P3 code introduced0027. These observations motivate separation of code capability, stored plan scope and installed readiness; they are dated observations, not fixtures to hard-code or permission to upgrade user data.

Preserve the accepted [P3 boundaries](SPEC-market-linkage-p3.md), [current workflow](SPEC-unified-plan.md), and finite [source treatments](SPEC-source-treatment-review.md). The original prompt remains outside this repository at `../../../../docs/TradingAgents/reports/新提示词.txt`, normalized UTF-8 SHA-256 `f17e12b88f4c12d7af7b67caabede2e9d7c2712142a64e67a212c7621865f731`; do not replace it with amended documentation when assessing scope.

## PMA-S02 — Proposed module map and build order

| Module ID | Owns | Depends on |
| --- | --- | --- |
| `source-condition-coverage` | Conservative source obligations, relationship coverage, versioned review binding and omission blockers | Existing source review, plan-domain and strategy-state |
| `extraction-v12-acceptance` | Frozen corpus/truth, bounded real-provider runs, independent scoring and version-specific evidence | `source-condition-coverage`; existing extraction transport |
| `monitor-readiness` | Read-only per-rule readiness explanations from existing current runtime authority | `source-condition-coverage`; existing runtime/data/outbox projections |

Implement coverage before using it in corpus signoff or readiness. Corpus preparation and readiness contract drafting may proceed independently after common interfaces are frozen; shared authority/persistence edits remain sequential. This proposed map does not mark these modules delivered in the production capability map. Each module has its own linked specification below.

## PMA-S03 — Six decisions for review

| ID | Recommended decision | Reason/tradeoff |
| --- | --- | --- |
| PMA-D01 | Use positive, server-verifiable non-policy treatments and atomic obligation/relationship coverage. Unknown or suspicious trading content blocks new authority; AI background labels and absence of keywords cannot discharge it | Accept more explicit review/clarification rather than silently removing conditions. This is a finite conservative contract, not a claim to understand arbitrary prose |
| PMA-D02 | No generic “acknowledge/ignore/background” override for mandatory omissions. Repair the source-bound rule, use an already registered exact supplement/override, or save a clarified source version | Preserve existing scoped human supplements, including authorized deadline overrides, without turning them into arbitrary omission waivers |
| PMA-D03 | Version current coverage separately from historical source-review verification. Old bytes/hashes/receipts remain readable; no old zero-issue record automatically gains new coverage. New current authorization requires the exact new proof | Avoid both a legacy-reading failure and a legacy-label bypass. Preserve independent technical-risk continuity and already consumed signals |
| PMA-D04 | Preserve `plan-extract-v12` instruction/template/output-schema bytes where possible; pin the contract, each assembled prompt hash and server coverage version independently. Changed instruction/output contract gets an honestly named new version and separate results, not merely a different source payload | Prevent “v12 accepted” from referring to an unrecorded new prompt or a corrected response |
| PMA-D05 | After this package is approved and implementation is explicitly requested, permit up to48 real extraction provider attempts:12 cases×2 runs for v12, plus a separate12×2 deployed-version set only if the prompt changes. No automatic retries; failures/timeouts count. Use the approved, redacted corpus and existing configured service only | This is a bounded future external-data/cost authorization proposed for review. This documentation turn makes zero calls. A larger budget, another provider/judge, or changed resource limits requires another decision |
| PMA-D06 | Readiness is a read-only, per-dependency explanation, never an authority token. The real-installation audit may honestly return `NOT_READY`; user migration, actual plan review/activation and test-message delivery are separately authorized operations | A diagnostic feature can pass its tests without claiming that today's real installation or every plan is ready |

Approval of this package is distinct from an instruction to start implementation. If D05 is not approved, keep real-provider acceptance pending; do not substitute synthetic responses or call the whole phase accepted.

## PMA-S04 — Scope and explicit exclusions

In scope: current Schema5–9 source-derived drafts, extraction/save/reload/review/activation/reuse, related current ordinary/exception/actionable-notification checks, a versioned coverage ledger, source-to-rule UI, corpus grading, and read-only readiness. Preserve isolated inventory, capital, research and actual-account boundaries. Valid but incomplete drafts remain inspectable and savable.

Out of scope: new trading indicators or strategies, automatic discovery of technical levels/fundamentals, broker execution, actual-account/partial-fill/order reservation, capital allocation, automatic rule repair or source rewriting, a second AI judge as an approval source, and user-database migration in this request. Readiness reads must not acquire market data, update a heartbeat, send a notification, confirm inventory/costs or activate a plan.

Old frozen inputs/replay remain governed by their exact historical contracts. This phase does not rewrite their inputs/hashes or introduce a frozen-run formula version. A historical/scenario replay cannot certify current source coverage or real-installation readiness. Current-plan reuse must use the new current source guard. The later PMA-S09 exception authorizes only a separately versioned immutable Schema10 preparation/composition contract with exact current proof; existing formats retain Schema10 rejection and cannot acquire that authority through new fields or fallback.

## PMA-S05 — Module specifications and owned interfaces

- [source-condition-coverage](SPEC-source-condition-coverage.md): obligations, proof, compatibility and admission.
- [extraction-v12-acceptance](SPEC-extraction-v12-acceptance.md):12-case matrix, truth, provider budget and scoring.
- [monitor-readiness](SPEC-monitor-readiness.md): axes, states, freshness, delivery and read-only boundaries.

Proposed owned versions: `source-obligation-v1`, `source-coverage-v1`, `source-coverage-review-v1`, `extraction-acceptance-v1`, `plan-monitor-readiness-v1`. These are assurance/evidence versions, not new strategy schemas or replacements for existing signal identities. T01 freezes exact DTOs, hash preimages and trusted historical dispatch before production changes.

Proposed API additions, after approval and complete guards:

| Interface | Contract |
| --- | --- |
| `GET /api/v1/plan-versions/{version_id}/source-coverage` | Summary plus paginated obligation rows, default `limit=50`, maximum100, cursor bound to exact source/candidate/mapping/ruleset. Read-only, `authorityGranted=false` |
| `GET /api/v1/plan-versions/{version_id}/monitor-readiness` | Exact plan/activation/runtime/target snapshot and per-rule explanations; no data acquisition or writes, `authorityGranted=false` |
| Existing extraction/draft/detail views | Add a typed coverage summary distinguishing transport success, semantic coverage and review eligibility; never hide a blocked draft |
| Existing `POST /api/v1/plan-review-confirmations` | Bind `coverageEvidenceHash` and current `coverageRulesVersion` in addition to existing exact review binding; missing/stale new proof yields a structured conflict, never a legacy fallback |

Retain public error envelopes, same-origin/idempotency controls and both generated API profiles. Invalid structure/spans/hashes return existing422 admission errors; valid semantic omissions are visible blocking issues, not erased candidates. Confirm/activate with missing, blocked or stale coverage returns409. Stored proof corruption retains the existing secret-free integrity error. Missing assurance storage is an explicit upgrade/unknown state, not zero issues. No generated artifact or approved API-owner appendix is changed in this documentation turn.

## PMA-S06 — Cross-cutting acceptance criteria

| ID | Required evidence |
| --- | --- |
| PMA-A01 | Reproduce both appended-condition counterexamples, then prove every context role and keyword-free variant blocks new authority while preserving the candidate |
| PMA-A02 | Detect same-clause partial coverage, ALL/ANY, negation, exception, comparator/unit, cycle/offset, validity, quantity, permission and independent-occurrence changes |
| PMA-A03 | Derive positive non-policy treatments from exact complete spans; preserve true metadata/history/account context and registered exclusions/supplements without creating inventory or permissions |
| PMA-A04 | Audit normalization before/after against original source; unknown, unsupported or over-limit obligations remain visible and blocking, with no truncation or invented repairs |
| PMA-A05 | Exact versioned proof revalidates on save/reload/confirm/activation/reuse and current action; tamper/stale/retry/race tests preserve atomicity |
| PMA-A06 | Historical bytes/hashes/reviews and frozen replay remain readable; legacy cannot self-upgrade, already consumed signals never rearm, and BUY-only failures do not veto independent technical-risk SELL |
| PMA-A07 | Frozen independent12-case truth, provenance and full prompt/config hashes; real attempts, synthetic tests, assisted corrections and original failures reported separately |
| PMA-A08 | Fixed-matrix mandatory omissions/inventions/relation changes are zero, expected blockers are correct, complete supported cases pass; no general natural-language accuracy claim or silent case substitution |
| PMA-A09 | Per-rule readiness distinguishes FALSE, expected close waiting, missing/stale data, first evaluation, cached state, irrelevant prerequisites, execution window and consumed signals |
| PMA-A10 | Delivery configuration/queue/retry/delivered receipts remain distinct; GETs make zero business writes/provider calls/heartbeats/messages and grant no authority |
| PMA-A11 | Real Chrome source→coverage→repair→exact review and readiness flows, stale responses, accessibility and320/768/1024/1440 layouts pass |
| PMA-A12 | Full non-live backend/frontend, contracts, type/build, both generated profiles, lint, whitespace, bilingual parity and isolated unchanged capacity gates pass; real acceptance and installation status are separately stated |

## PMA-S07 — Implementation conventions and verification boundary

Use current Python3.14, immutable Pydantic contracts, exact quantities/fen and the existing canonical hashes. Domain coverage logic belongs in `ai/` or a focused source-policy module; persistence/authority in `state/`; HTTP projections in `web/`; current evidence collection in existing runtime read seams. Vue uses Composition API `<script setup lang="ts">`. No new dependency is proposed. A representative gate is `can_confirm = integrity_valid and coverage_complete and exact_binding`; a readiness badge is never substituted for this gate.

The [task pair](../../../tasks/plan-monitor-assurance.md) owns executable commands, prospective test filenames, dependencies,24 tasks and eight checkpoints. Each implementation slice targets3–5 files; split broader tasks sequentially before editing. Use independent failing tests before behavior changes. Keep `tasks/plan.md` and `tasks/todo.md` unchanged. No source-code mutation experiment or test run is claimed by writing this draft.

Always preserve source, original failures, old goldens and existing resource/admission limits. After explicit implementation authorization, additive migration development and temporary-database tests may proceed; applying any migration to user data remains separate. Ask for a decision only for genuinely new semantics, ambiguous truth, unapproved external data/cost scope, version/budget expansion or an unavoidable compatibility change. Never waive omissions, fabricate READY, relabel prompts, silently rewrite history, or weaken tests to close a checkpoint.

Do not advertise a completed current coverage capability or accept its new review receipt before the full save/reload/review/activation/reuse/action/send-time guard chain is tested. Stage partial adapters privately; missing required assurance capability/storage is an explicit blocker or unknown, never a fallback that grants new authority. Final public admission follows C03/C04, and user rollout remains separately controlled.

## PMA-S08 — Review and completion rule

Review D01–D06 together with the three module contracts and task dependencies. All task/checkpoint marks remain unchecked until actual implementation and evidence exist. Engineering completion, finite-corpus acceptance and per-installation readiness must be reported separately. Missing real-provider evidence cannot become an offline PASS, and a truthful `NOT_READY` installation diagnosis cannot become a claim of live readiness.

## PMA-S09 — Later minimum Schema10 frozen preparation delta

**PBS-FP-D01: scope approved on 2026-11-16, Asia/Shanghai; no implementation acceptance.** The user approved the concrete [T24-05/06 minimum](../../verification/pma-t24-reconciliation-2026-11-16.md), limited to a **new versioned immutable Schema10 preparation carrier/projection: prepare → serialize → reread → true03→04 composition**. The canonical detailed contract delta is [PBS section 6.2](SPEC-plan-buy-suspension.md#62-pbs-fp-d01--later-minimum-frozen-preparation-delta), with prospective PBS-FP01–PBS-FP08 acceptance. This is a later, bounded exception to the original PBS-D05 preparation exclusion, not a revision of PBS-D01–PBS-D06 or an implication of PMA-D04. Existing frozen bytes, hashes, goldens, historical contracts and Schema10 rejection remain unchanged.

Before format code, freeze bounded bilingual contract refinement from the actual preparation/review/hash/schedule/composition owner audit: exact discriminator/version, payload, canonical codec/hash preimages, dispatch and rejection. This scope delta chooses no wire identifier or DTO name and mandates no particular old owner edits or reused representations. Then private typed-carrier/codec unit engineering can use synthetic candidates without a real 03 parent, explicitly as **synthetic contract evidence only**. Actual-source admission remains held for faithful complete sources, current proofs and actual predecessor bindings where applicable; private units cannot release PMA-T13–T15. Evidence for the source/supplement/current-review/lineage authority route may come from isolated existing current-plan/source mechanisms or independent pure-model mapping tests. New-format 03 freeze/reread is required before actual 04 composition, not before initial format code; no circular prerequisite is allowed. The approval includes new versioned preparation/projection/composition entry points and version adapters after their prerequisites pass; private staging does not permanently exclude them. Guard definition/start/source inheritance remains mandatory. Runtime state/proof/revision, consumed signals, holdings, cost and other account continuity need preservation only when actually present in the source/account snapshot/carrier; no new live-state collection, user DB reads, simulated consumption or runtime consumer is required, and missing runtime state is never clear.

The following rows mirror the PBS acceptance boundary; neither document claims they have passed:

| Acceptance reference | Assurance requirement |
| --- | --- |
| PBS-FP01 | Audit/freeze the new exact contract and owners before code; use explicit new dispatch with no lossy fallback. Preserve old bytes/hashes/goldens and explicit old-format Schema10 rejection. |
| PBS-FP02 | Preserve both complete original sources and source hashes, every independently classified obligation/relationship and remaining blocker. Bind approved clarifications and current coverage/exact review to source/obligation identities, separately from historical review; separate raw, assisted and human results without invented satisfaction or stripped conditions. |
| PBS-FP03 | Actual-source producer/freeze/review/reread admission requires faithful complete sources, current proofs and actual predecessor bindings where applicable. Actual 04 composition requires independently complete, reviewed/frozen and reread actual 03; this new-format 03 is not an initial format-code prerequisite. Bind exact predecessor plan/version/content/source/current-coverage/review/guard ownership; reject missing/stale/substituted/copied identities, old snapshots and replacement seeds. Synthetic units do not satisfy actual-source acceptance or release PMA-T13–T15. |
| PBS-FP04 | Prove immutable lossless source/candidate/coverage/review/predecessor/guard definition/start/schedule serialization and reread; preserve runtime state/proof/revision actually present in the source/account snapshot/carrier without requiring new live-state collection, user DB reads, simulated consumption or a runtime consumer. Reject tamper/stale binding at reread/composition, including self-authorized payload-hash recomputation, and retain rejected input/diagnostics. |
| PBS-FP05 | Ordinary 03 → 04 fully inherits the source guard obligation, `2026-09-30T09:30:00+08:00` start, first close `2026-09-30T09:35:00+08:00` and definition. Preserve represented authority/state/proof/revision, including unverified/latched state, as actually present in the source/account snapshot/carrier; missing runtime state is not clear. No omission/date/standalone/replacement relabel bypass; a frozen representation cannot clear history or authorize runtime activation. |
| PBS-FP06 | Compose the actual two-plan schedule with full chronology, earlier risk context, source quantities and distinct first/second 100 permissions; preserve consumed signals/permissions, holdings, cost and other account continuity actually present in the source/account snapshot/carrier without reset/fabrication. This preparation delta requires neither simulated consumption nor a new runtime consumer; a third executable grant is not allowed. No public execution replay. |
| PBS-FP07 | Public Schema10 dataset/run and execution replay still reject, including promotion through old adapters; the approved new versioned preparation/projection/composition entry points are not excluded. No new strategies, user DB/state writes, services, providers, live acquisition or real notifications. |
| PBS-FP08 | Independently review exact-candidate bilingual and deterministic isolated evidence while preserving failures/goldens. Scope approval or synthetic codec evidence does not automatically close F083; its specific failure may close after independent exact-candidate PASS of every original F083 requirement/assertion for the complete original-source chain. Source/parent/codec/feasibility/T14/corpus/provider and overall PMA-T13/T22/T24 or C05/C07/C08 gates still require separate evidence. Keep independent 12-case truth, the shared 48-physical-attempt cap and zero automatic retries. |

This authorization removes only the new preparation scope blocker. It does not freeze the corpus/truth, prove actual 03/04 source success, release T14/T15, or grant runtime authority. Raw extraction, approved-clarification assistance, human changes and final review remain separate; no offline result substitutes for C05. User database/state operations, live monitoring, new strategies and public dataset/run/execution replay remain excluded. [T24-06](../../verification/pma-t24-reconciliation-2026-11-16.md#t24-06--ordered-candidate-slices-after-prerequisites) paths remain candidates to reconfirm from prerequisite evidence, within the one-writer and bounded-path rules in [HND-04](../../../tasks/pma-t13-handoff-2026-11-16.md#hnd-04--authorization-and-limits).

This four-document scope slice runs no business tests and changes no implementation, old report or task mark. N03 remains without business RED/GREEN evidence after its Windows proactor/socketpair environment blocker; this approval is not its resolution. PMA-T13/T14/T15/T20/T21/T22/T24, H01–H05 and C05/C07/C08 remain open overall.
