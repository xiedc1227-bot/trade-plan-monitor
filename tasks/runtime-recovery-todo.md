# Task List: Anytime Runtime Recovery

> Status: IN PROGRESS since implementation authorization on 2026-09-21. Canonical English; paired copy: `runtime-recovery-todo.zh-CN.md`.
> Governing proposal: `runtime-recovery-plan.md`. Original D1–D7/A01–A12 and D8/A13 are approved; D9/A14 business intent is confirmed, but its API awaits review.
> Future assignments follow proposal section 2: `gpt-6-astra` / `xhigh` for architecture, adversarial review and difficult failures; `gpt-6-sol` / `high` for bounded implementation and `gpt-6-sol` / `medium` for settled documentation. Historical execution records retain their actual model/effort. Each checkpoint review is evidence only when performed.

## Execution rules

### Current delivery order — 2026-09-22

Use proposal section 7.1 for execution. The following five outcomes govern user-facing progress; RR tasks below remain the implementation/acceptance index, not five additional stages. Baseline: `1f50439`, on `codex/consolidate-r19-r32`. **Business step 1 is in progress, not complete.** The workflow revision itself changes no runtime behavior; actual implementation evidence follows below.

| Business step | Current state | Completion evidence / RR mapping |
|---|---|---|
| 1. Historical-state recovery | Bounded historical inventory and attributable risk now feed two ordered missed closes through the existing evaluator; separate-process restart and pre-evaluation abrupt-exit recovery pass offline. Approved but unwired five-day admission/expiry rule, recent-state provenance for long-lived plans, opening-aware evaluation and production coordinator integration remain | Real temporary SQLite state reconstructed at the required historical target for eligible interruptions; missed closes applied chronologically; interrupted/repeated recovery creates no duplicate canonical result or intent; interruptions longer than 120 hours expire plans safely; unknown history blocks only the affected plan. RR007–RR010, C2, A13 |
| 2. Notification safety | Classification/storage and opt-in transaction foundations exist; final delivery admission is missing | Both plan families use freshly reconstructed risk/inventory/barrier evidence before fake-channel admission; obsolete notices suppressed, identical applicable exits latest-only, insufficient evidence held; uncertain sends preserved. RR011–RR013 |
| 3. Actual lifecycle integration | Coordinator/retry foundations exist; production lifecycle integration is missing | Same application composition recovers from unavailable dependencies, validates reload, fences old work and drains on shutdown; acceptance includes controlled process restart. RR004–RR006, RR010, RR014, C1/C3 |
| 4. Status APIs and page | Contract draft only | Real backend state reaches the page as standby/recovering/blocked/transport failure with reasons and retry information; old clients fail safely. RR002, RR015–RR019, C4 |
| 5. Restart/fault acceptance | Local component evidence only | All A01–A14 scenarios, all section 7 offline gates, migration/rollback evidence and final independent review completed; deployment remains separate. RR020–RR022, C5 |

The main sequence is 1 → 2 → 3 → 4 → 5. Bring forward offline composition/restart test scaffolding into step 1 and dependency-retry tests into step 3; do not postpone their first execution until step 5. After RR002 is reviewed, independent status/client preparation can overlap without claiming step 4 completion. Original task dependencies remain acceptance/default-enablement gates, not a ban on testing injected integrations early.

Current implementation handoff: the user resolved V1a's temporal choice: alerts are not executions; only manual registration changes holdings, inclusively at its timestamp, without backdating earlier inventory. The bounded historical reader proves inventory, attributable risk and the earliest absent close within a 32-day activation window. An opt-in service path now evaluates two consecutive missing closes with exact historical lots, source-effective risk time, transaction fences and initial `HOLD` alerts; separate-process restarts and pre-evaluation abrupt exit do not duplicate results or intents. Missing data, a prior blocked result and opening balances without legacy attributes cannot silently become completed closes. Index-only migration `0021_inventory_history_index` has temporary-database upgrade/downgrade coverage; no user database was migrated. V1a/V1b foundations are implemented; V1c/RR009/C2 remain open for the approved but unwired five-day gate, recent-state provenance of long-lived plans, opening-aware evaluation, production coordinator integration and broader restart/fault acceptance. Commands and review findings accumulate in paired `docs/verification/runtime-recovery-acceptance.md`. No further late-registration choice is pending.

### Five-day scope amendment — 2026-09-23

- [ ] **V1d — Implement approved D8/A13.** The 120-hour boundary, durable last-alive evidence and unknown/legacy database behavior are approved. The additive `0022_runtime_liveness` schema, persistence/classifier and temporary-database boundary/corruption/legacy/downgrade tests are implemented; **no production heartbeat or expiry gate is wired yet**. Next: transactional plan expiry and queued-work suppression, then wire admission before active-plan loading or dispatch. Never run bulk expiry on the user database in this stage.
- [ ] **V2a — Review D9/A14 alert-page action contract.** Keep risk and sell signals separate; distinguish read acknowledgment, not-sold and actual-quantity sold. Reuse the inventory-closure boundary with idempotency and audit, then test stale alert, partial sale and repeated confirmation. Implement after the five-day admission decision, without changing evaluator rules.

### Next connected outcome: one provable missed close

Internal work units below belong to RR009/C2. Keep their commits bounded; do not give each decoder a separate business milestone or verification report. Extend to multi-day and fault coverage before checking off step 1.

- [x] **V1a — Settle the historical reconstruction contract.** Dependencies: existing writer/decoder evidence and RR001. Decide historical observation cutoff versus accepted effective date, late/non-monotonic registration treatment, risk source-effective semantics, and explicit byte/member/history budgets in one focused review. Preserve custom board lots, raw snapshots and old canonical hashes. Acceptance: paired specification contains example timelines and explicit known/unknown outcomes; unresolved business choices go to the user before consumer implementation. Files: paired `docs/specifications/monitoring/SPEC-runtime-recovery.md` and this paired task index. Verify: trace examples to writer fields and D3/D5, check bilingual parity and reconcile new safety findings; no repeated review of unchanged decisions.
- [x] **V1b — Read one complete historical inventory.** Dependencies: V1a. Complete confirmation/inventory-change decoding together with the durable inventory reader, reusing existing lot/opening validators and owned-snapshot guard. Acceptance: real writer records yield one coherent inventory at the requested target; broken links, missing members, over-budget or contradictory histories remain typed unknown; no uncommitted/foreign-transaction evidence is accepted. Source area: `src/trade_plan_monitor/state/`; tests: existing inventory audit/transaction/lot-history tests plus NEW focused inventory-history tests. Verify: fail-first writer-to-reader cases and corruption/transaction/budget cases, then the affected inventory regression group. Use bounded internal source/test commits, not a new generic history framework.
- [ ] **V1c — Execute and reopen the missed-close path.** Dependencies: V1b plus reviewed risk-source reconstruction and existing RR008/RR010 guards. Connect discovery, exact historical inputs and existing evaluator transactions with initial HOLD in temporary storage; use fake providers and no real sender. Acceptance: a missed close commits once; reopening storage and repeating discovery creates no extra result/intent; crash before commit rolls back, stale activation cannot commit, and a missing prerequisite holds only its dependent plan. Source area: existing `runtime/service.py`, recovery orchestration and evaluator transaction boundary; NEW `tests/integration/test_missed_close_execution.py`. Verify: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_missed_close_execution.py tests/integration/test_recovery_alert_eligibility.py tests/integration/test_recovery_activation_fences.py -q`; expand to production coordinator, verified recent provenance for long-lived plans, the approved but unwired five-day gate and process-restart coverage before C2 closure. Reopening SQLite alone is not full process-restart acceptance.

### Verification cadence and handoff

- During edits: meaningful fail-first tests, affected test groups and lint; add generation/transaction/identity regressions when those boundaries change. Test the consumers in the same connected outcome, not just each parser.
- At a connected-outcome checkpoint: run its integrated recovery/fault scenarios and cross-module regression groups; review the complete connected diff. Record commands, tested revision/diff and results in one paired outcome report. Rerun affected checks after a fix; unchanged successful evidence need not be regenerated.
- Before final acceptance/default enablement: all proposal section 7 commands, including the complete `not live` suite without a new exclusion and browser acceptance on isolated test state. Known failures are neither waived nor converted to skips. A targeted pass does not close C0–C5.
- Baseline failures remain open: the prior report `docs/verification/2026-09-22-opening-balance-decoding.md` records 3734 passed / 4 failed / 1 skipped / 4 deselected in a run excluding the heavy backtest file. This is historical scoped evidence, not a full-suite pass. Reproduce relevant failures when their boundaries are touched; resolve all four before final acceptance. Do not repeatedly spend a full run rediscovering unchanged failures after documentation-only edits.
- Handoff format: business step; working integrated scenario (or explicitly only a foundation); actual evidence; remaining decision/failure; next connected action. No percentage inferred from commit/test counts. Keep the current branch; no push, branch switch/merge, real provider/channel operation or deployment is authorized by this workflow revision.

### Implementation checkpoint — 2026-09-21

See paired evidence in `docs/verification/2026-09-21-runtime-recovery-foundations.md`. Completed foundation slices do not close C0–C5 or enable production recovery.

| Task | Current state |
|---|---|
| RR001 | Paired provider/recovery specifications written; full contract review remains open |
| RR003 | Implemented and independently reviewed; integrity, compatibility and concurrent no-clobber import tests pass |
| RR004 | Injected pipeline gates implemented and reviewed; composition and independent scheduling after a selected-stock failure remain open |
| RR005 | Checkpoint model/repository/migration and SQLite latest-head assertions implemented and reviewed |
| RR006 | Durable admission, `RecoverySchedule` and injected single-owner `RecoveryCoordinator` implemented/reviewed; production lifecycle integration remains open |
| RR007–RR008 | Pure targets plus injected single-symbol acquisition verify exact committed coverage; composed coordinator/controller/SQLite recovery tested; historical acquisition/replay and production integration remain open |
| RR010 | Reference keys now bind plan family/content, actual activation and stock semantics; post-await cache/admission fences reviewed; broader generation/reconfiguration obligations remain open |
| RR002 | Paired detailed status/protocol draft added for review; no protocol source/default change or C0/C4 closure |
| RR011–RR013 policy/storage slices | Explicit-risk classifier and legacy origin proof independently reviewed; isolated legacy applicability classifier, delivery migration/repository and opt-in atomic HOLD enqueue added; RR012 initial-HOLD evaluator transaction wiring implemented and independently reviewed, not enabled in production composition; durable current-evidence reconstruction and dispatcher integration remain open |
| RR009 | Bounded discovery plus a read-only SQLite occurrence/activation evidence reader added; direct provenance beyond proof budgets, historical-state reconstruction and ordered execution remain open |
| RR011–RR022 | Not completed; use dependencies below, not this incremental checkpoint as rollout approval |

- The user's 2026-09-21 instruction authorizes the approved proposal/map's implementation. Derived provider/recovery contracts accompany isolated, injected foundation slices; unreviewed protocol/business changes and the production default switch remain gated. This authorization does not approve live migration or deployment.
- Every code task starts with a meaningful failing test; preserve unrelated changes and old canonical identity goldens. Do not skip tests merely because they encode the old behavior: replace only the specifically superseded assertions with approved new-contract tests.
- Paths below are repository-relative and prospective where marked NEW. Keep internal code changes at approximately 3–5 source/test files; split oversized changes within a connected outcome, without adding another business milestone. Synchronize paired specifications/contracts with the related change; RR017/RR021 retain their generated-contract/operations acceptance obligations.
- Reuse the current default production behavior until the replacement path is complete enough to pass its checkpoint. Integrate early through dependency injection and the existing composition, not a second permanent production framework. Enable the new default only at RR020 after all prerequisite contracts and guards exist; do not defer the first integrated test to RR020.
- Every task records changed paths, exact commands, observed results and outstanding failures. Do not claim the requested model/effort ran unless the task execution can confirm it.

### Continuation checkpoint — 2026-09-21

The continuation adds isolated RR006/RR008/RR010 slices; it does not mark these full tasks complete. Details and observed verification are in `docs/verification/2026-09-21-runtime-recovery-increments.md` and its Chinese copy. The new coordinator stays alive for typed dependency retries with a 30-second local maintenance ceiling, while storage/programming faults remain visible. Scoped acquisition never upgrades partial, future or wrong-date data to ready. Queue-time local abort preserves existing provider backoff. Reference cache reuse cannot cross a plan-family or actual activation change.

Latest-state explicit-risk and read-only legacy-origin slices are independently reviewed; the user-approved latest-only repeated exit rule is recorded but not dispatch-wired. Final functional verification reports 3095 passed and 4 pre-existing failures; the unchanged heavy backtest file passed in the earlier full run. The R32 real-date-dependent test was corrected without changing its execution guard. No default switch, live action, merge or deployment is authorized by this checkpoint.

### Delivery safety checkpoint — 2026-09-21

The next isolated increment adds migration `0019_alert_delivery_eligibility`, revision-fenced classification/audit, bounded missing-row initialization and opt-in `enqueue_recoverable`. Canonical alert/result identities and existing production defaults are unchanged. Actionable source expiry and state-risk applicability are separate; stored ELIGIBLE is not a lasting send permit. The legacy pure policy checks original evidence, latest official risk stage, current inventory/T+1 and approved latest-only repeated exits. Its calendar and current-state inputs remain injected, not a completed durable reader.

See `docs/verification/2026-09-21-recovery-delivery-metadata.md` and ADR 0007 with paired Chinese copies. RR011–RR013 and C0/C2/C3 remain incomplete until evaluator transactions, current authority, final per-channel admission and end-to-end crash/restart evidence are integrated. This increment does not authorize live migration, notification, production switch or deployment.

### Evaluator transaction checkpoint — 2026-09-21

The requested push synchronized `964fde2` and `6dff7ae` to the existing GitHub branch before this continuation. RR012 now proceeds as an isolated transaction slice: strict constructor opt-in routes both legacy evaluation paths and explicit alert writes through the existing HOLD helper. The helper normalizes the outbox's aware clock before metadata initialization. Decision rollback must include claims/results/transitions/alerts/metadata/audit and exclude previously committed market facts. Details and final verification are tracked in paired `docs/verification/2026-09-21-recovery-evaluation-transactions.md`.

The rollout position remains core recovery/notification safety, before complete production integration: C0–C5 are not closed by these slices. No existing factory enables the flag; it does not cause the dispatcher to enforce HOLD. Current-authority reconstruction, final send admission, lifecycle/status/UI wiring and process-restart acceptance remain prerequisites to RR020. Local commits made after the requested push are not implicitly pushed or deployed.

### Missing-close discovery checkpoint — 2026-09-21

The isolated RR009 scanner discovers due legacy close candidates without relying on a pending marker. Actual activation, historical policy, authoritative calendar and exact completion evidence remain distinct inputs. Each call covers at most 32 calendar days; a window boundary never certifies overall recovery. Unknown attribution and possible out-of-order history are explicit. It does not invoke the current evaluator with today's state for historical dates, change the production startup path or send notifications. Evidence is recorded in paired `docs/verification/2026-09-21-missed-close-discovery.md`.

RR009 stays unchecked: bounded durable attribution is covered by the following checkpoint; authoritative historical-state reconstruction and chronological execution with activation/generation fences remain open. Existing hash-only claims, later results after holes, current-inventory context and risk write-time semantics must be resolved without rewriting canonical identities or changing trading rules. The scanner is not a recovery barrier or a release gate.

### Durable close evidence checkpoint — 2026-09-21

The next RR009 slice shares the already-tested activation-chain proof and reads active scope, calendar, claims, complete results and publications in one owned SQLite snapshot. Occurrence proof does not depend on alert creation or risk signal type. Missing/corrupt/oversized/wrong-activation evidence remains unknown, and absence additionally requires a bounded orphan-publication check. The publication-history budget can conservatively exhaust in normal long-running use; this is a documented pending direct-provenance requirement before rollout, not a claim that arbitrary history is recoverable.

See paired `docs/verification/2026-09-21-close-recovery-evidence.md`. RR009 is still open for authoritative historical-state reconstruction and safe chronological execution; no replay, real notification, schema migration or production default was enabled. Current-snapshot facts are not a lasting mutation/send permit.

### Position-lot evidence checkpoint — 2026-09-22

RR009's next prerequisite records versioned command-date and complete before/after snapshots for future manual lot buys and reductions in the existing audit transaction. It preserves lot hashes, event identities, inventory rules and idempotent behavior; it does not reconstruct a historical portfolio or enable replay. Old rows remain unchanged and cannot acquire a missing reduction date from their write timestamp. The contract is in the paired runtime-recovery specification; verification is recorded in paired `docs/verification/2026-09-22-position-lot-recovery-evidence.md`.

The next historical-state work must validate those records and establish complete per-lot/inventory history, opening-balance and confirmation semantics, plus a distinct risk source-effective date. Existing evidence budgets and causal gaps still block unknown scopes. RR009 and C2 remain unchecked; no production recovery, live service, migration or real delivery is enabled.

### Position-lot decoding checkpoint — 2026-09-22

The isolated pure decoder validates one versioned lot-mutation audit: bounded strict JSON, metadata bindings, exact legacy hashes and buy/reduction invariants. Missing old evidence, unsupported versions and invalid data return typed unknown; no write-time inference is used. It supports the existing non-UUID/custom-board-lot conventions without changing mutation admission. See paired `docs/verification/2026-09-22-position-lot-evidence-decoder.md` for test-first and independent-review evidence.

This closes single-record decoding only. A durable per-lot reader still must establish a bounded unique chain, committed publications and agreement with the current lot in one snapshot. An audit query row limit alone does not bound database scan work; the existing audit table has no entity-type/entity-ID index. Inventory completeness, opening balances/confirmations, risk source-effective dates and safe chronological execution remain open. RR009/C2 and production integration are not complete.

### Single-lot history checkpoint — 2026-09-22

The next RR009 slice reads one lot's complete stored audit/publication chain in one owned SQLite snapshot. A unique buy root, every exact reduction, current-row agreement and ordered deterministic publications are required. Missing, conflicting, malformed or over-budget evidence remains unknown. The evidence is not a complete inventory or a replay/send permit. The seven-day client replay filter is not used to discard older persisted publications.

Additive migration `0020_lot_history_indexes` supports exact audit scope and ordered aggregate-event queries; it changes indexes only and is tested on temporary databases. Reader, migration and review evidence is recorded in paired `docs/verification/2026-09-22-position-lot-history.md`. Complete inventory, opening balances/confirmations, risk source-effective semantics and chronological execution still block RR009/C2 closure and production integration.

- The transaction-ownership follow-up identified here is addressed by the checkpoint below; the single-lot increment itself did not certify the adjacent readers.

### Recovery reader transaction-ownership checkpoint — 2026-09-22

`LegacyCloseRecoveryReader`, `LegacyAlertOriginReader` and `PositionLotHistoryReader` share a small preflight requiring a fresh session and one application SQLite Engine for every mapper/table binding. External Connections and split engines are rejected before context entry or SQL, without changing the caller's transaction. Real tests reproduce both legacy readers falsely proving uncommitted evidence before the fix. This closes the identified binding gap, not historical-state reconstruction or the entire recovery-reader trust boundary.

See paired `docs/verification/2026-09-22-recovery-reader-transactions.md`. The next RR009 slice must preserve opening-balance and inventory-confirmation history before complete historical inventory can be reconstructed. Risk source-effective semantics, history budgets, causal execution and the broader integration gates remain open. No production default, provider/channel operation, schema migration or deployment is enabled.

### Inventory writer evidence checkpoint — 2026-09-22

Future confirmations preserve complete raw previous/next rows and any newly created opening balance. Opening reductions preserve accepted trade date, board lot and raw before/after rows. Every lot buy/reduction and opening reduction also records a separate source-linked inventory transition, including missing/stale confirmations. Existing admission, responses, hashes, publication identities, ID/clock consumption and transaction ownership remain unchanged; no migration or backfill is included.

See paired `docs/verification/2026-09-22-inventory-recovery-evidence.md`. This increment completes writer storage, not historical inventory reconstruction. RR009/C2 stay unchecked: bounded decoding, source/chain verification, completeness cutoffs, late/non-monotonic registration, risk source-effective semantics and chronological execution remain open. Final delivery admission, lifecycle/status integration and actual process-restart acceptance are later gates; no live provider, real notification, production default or deployment is enabled.

### Opening-balance reduction decoder checkpoint — 2026-09-22

`decode_opening_balance_mutation` now validates one bounded opening-reduction audit and returns immutable consistent evidence or typed unknown. It preserves raw timestamps while checking the existing DTO-based hashes, exact scope and mutation arithmetic. Same-day sellability, variable board lots, odd balances and independent write/closure/effective dates remain supported. It reuses strict parsing primitives without changing existing writers or the lot decoder.

See paired `docs/verification/2026-09-22-opening-balance-decoding.md`. This is the first of three inventory-related decoder slices, not a durable history reader. Confirmation and inventory-change receipt decoding, source/chain proof, explicit completeness policy and chronological execution remain open; RR009/C2 stay unchecked. No branch creation/switch, migration, production recovery, real notification, push or deployment is included.

## Specification gate

- [ ] RR001 — Freeze semantic and recovery specifications. Effort: `xhigh`. Dependencies: proposal/map approval.
  - Acceptance: D1–D6 and A01–A10 are precise; module interfaces, actual activation boundaries, all signal delivery classes and additive migration are approved, not inferred.
  - Files: NEW paired provider-contract specification and paired runtime-recovery specification under `docs/specifications/monitoring/` (4 files).
  - Verify: trace every decision/acceptance ID, check bilingual parity, obtain specification approval.
- [ ] RR002 — Freeze status/protocol and rollout contract. Effort: `xhigh`. Dependencies: RR001.
  - Acceptance: D7 defines discriminated status, exact protocol/version negotiation, old-client safe reload, both plan families and per-scope unavailable behavior; no ambiguity remains about the old global `readOnly` field.
  - Files: NEW paired runtime-status specification and `docs/specifications/monitoring/SPEC-local-web.md` / `SPEC-local-web.zh-CN.md` (4 files).
  - Verify: review valid/invalid status and old/new client message examples, A11–A12 traceability and bilingual parity.

### Checkpoint C0 — Approved contract

- [ ] Complete review of RR001–RR002 against the user-approved proposal; changes to source semantics, alert eligibility, schema and compatibility are explicit. Isolated foundations may proceed under the 2026-09-21 implementation instruction; no production default switch or unapproved semantic expansion before this gate.

## Provider and recovery foundations

- [x] RR003 — Introduce compatible semantic-record import. Effort: `high`. Dependencies: C0 (isolated foundation authorized by the 2026-09-21 instruction).
  - Acceptance: A01–A02; migration idempotent, verified scope only, original evidence untouched; semantic revision ignores metadata but checks adapter compatibility.
  - Files: NEW `src/trade_plan_monitor/runtime/provider_contract.py`, `src/trade_plan_monitor/live_profiles.py`, `tests/unit/test_live_certification_profiles.py`, NEW `tests/unit/test_provider_contract.py`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_live_certification_profiles.py tests/unit/test_provider_contract.py -q`.
- [ ] RR004 — Replace whole-evidence runtime gates. Effort: `high`. Dependencies: RR003.
  - Acceptance: stock/index gates independent; old READY does not confer current health; metadata refresh harmless and incompatible change rejected before physical request.
  - Files: `src/trade_plan_monitor/runtime/production.py`, `src/trade_plan_monitor/web/monitor_composition.py`, `tests/integration/test_production_certification_gate.py`, `tests/integration/test_certified_production_runtime.py`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_production_certification_gate.py tests/integration/test_certified_production_runtime.py -q` using injected composition until RR020.
- [x] RR005 — Persist bounded provider recovery checkpoint. Effort: `high`. Dependencies: RR003, temporary-database migration approval.
  - Acceptance: cooldown/retry state survives restart, contains no credentials, migration is additive/idempotent and refuses destructive loss of pending state.
  - Files: NEW migration under `src/trade_plan_monitor/state/migrations/versions/`, `src/trade_plan_monitor/state/models.py`, NEW `src/trade_plan_monitor/state/runtime_recovery.py`, NEW `tests/integration/test_runtime_recovery_storage.py`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_recovery_storage.py -q` with temporary database upgrade/restart cases.
- [ ] RR006 — Add controlled reconciliation/retry admission. Effort: `high`. Dependencies: RR004–RR005.
  - Acceptance: A04–A05; stable failure keys, one permission reprobe, preserved shared cooldown, bounded/coalesced work; no permanent permission latch loop.
  - Files: NEW `src/trade_plan_monitor/runtime/reconciliation.py`, `src/trade_plan_monitor/runtime/request_control.py`, `tests/unit/test_monitor_runtime.py`, NEW `tests/unit/test_runtime_reconciliation.py`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py -q` with fake clock and physical-call counters.

### Checkpoint C1 — Provider recovery

- [ ] A01, A02, A04, A05 pass offline; serial request/cooldown bounds preserved; inspect migration and new-record integrity at `xhigh`.

## Session and business-state recovery

- [ ] RR007 — Calculate session-aware recovery targets. Effort: `high`. Dependencies: C1.
  - Acceptance: A03/A10; unknown calendar has a retry wake, standby is not live actionable data, rollover and clock reversal do not consume future data.
  - Files: `src/trade_plan_monitor/runtime/scheduler.py`, `src/trade_plan_monitor/runtime/reconciliation.py`, `tests/unit/test_monitor_runtime.py`, `tests/unit/test_runtime_reconciliation.py`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py -q` across the full session matrix.
- [ ] RR008 — Restore exact scoped coverage in bounded steps. Effort: `high`. Dependencies: RR007.
  - Acceptance: empty/partial rows do not prove readiness; cutoff is frozen; fair per-scope progress, no all-symbol startup monopoly, existing index retry caps respected.
  - Files: `src/trade_plan_monitor/runtime/recovery.py`, `src/trade_plan_monitor/runtime/production.py`, `src/trade_plan_monitor/runtime/reconciliation.py`, NEW `tests/integration/test_runtime_recovery_coverage.py`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_recovery_coverage.py -q`; include partial and cross-day acquisition plus constrained-capacity cases.
- [ ] RR009 — Discover completely missed close obligations. Effort: `high`. Dependencies: RR008.
  - Acceptance: stop before 15:20/restart after 17:00 and multi-day outages restore eligible missing closes in causal order; unknown historical state blocks only the dependent plan.
  - Files: `src/trade_plan_monitor/runtime/production.py`, `src/trade_plan_monitor/runtime/reconciliation.py`, NEW `tests/integration/test_missed_close_recovery.py`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_missed_close_recovery.py -q`; do not dispatch historical alerts before RR012–RR013.
- [ ] RR010 — Fence dependency changes and plan-family recovery. Effort: `high`. Dependencies: RR008–RR009.
  - Acceptance: A06/A09; reference keys cover requirements and activation; same-symbol explicit-to-legacy replacement fetches missing references; old generations cannot commit current decisions.
  - Files: `src/trade_plan_monitor/runtime/production.py`, `src/trade_plan_monitor/runtime/production_context.py`, `tests/integration/test_explicit_runtime_production.py`, NEW `tests/integration/test_recovery_activation_fences.py`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_explicit_runtime_production.py tests/integration/test_recovery_activation_fences.py -q`.

### Checkpoint C2 — Correct recovery targets

- [ ] A03, A06, A07, A09, A10 pass offline; independently review close discovery, state reconstruction and activation semantics at `xhigh`.

## Notification safety and lifecycle

- [ ] RR011 — Add durable delivery eligibility without hash changes. Effort: `high`. Dependencies: C0, C2, migration approval.
  - Acceptance: historical eligibility/expiry/suppression is durable, event payloads/hashes unchanged; old pending rows get fail-closed classification without deletion.
  - Files: NEW additive migration, `src/trade_plan_monitor/state/models.py`, `src/trade_plan_monitor/notifications/outbox.py`, `tests/unit/test_notification_outbox.py`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_notification_outbox.py -q` with migration interruption/golden payload cases.
- [ ] RR012 — Apply intent eligibility in both evaluator transactions. Effort: `high`. Dependencies: RR010–RR011.
  - Acceptance: A08; state/claims and delivery eligibility commit atomically; preserve historical result hashes, true risk notices and explicit activation identity; no unrestricted stale intent is committed.
  - Files: `src/trade_plan_monitor/runtime/service.py`, `src/trade_plan_monitor/runtime/explicit_service.py`, `tests/integration/test_explicit_runtime_production.py`, NEW `tests/integration/test_recovery_alert_eligibility.py`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_recovery_alert_eligibility.py tests/integration/test_explicit_runtime_production.py -q`.
- [ ] RR013 — Gate pending dispatch after downtime. Effort: `high`. Dependencies: RR012.
  - Acceptance: obsolete unsent actionable messages suppressed with audit reason; risk messages wait for the per-plan current-state recovery barrier and latest-state recheck (D1 breach/D2 resolution); both plan loaders and existing uncertain-send behavior work.
  - Files: `src/trade_plan_monitor/notifications/dispatcher.py`, `src/trade_plan_monitor/notifications/outbox.py`, `tests/integration/test_notification_delivery.py`, `tests/integration/test_recovery_alert_eligibility.py`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_notification_delivery.py tests/integration/test_recovery_alert_eligibility.py -q` using fake channels only.
- [ ] RR014 — Keep a coordinator alive through degraded startup. Effort: `high`. Dependencies: RR006–RR013.
  - Acceptance: A04/A11; local bootstrap is independent of provider IO; one owner, interruptible waits, progress deadline and safe shutdown; expected errors do not exhaust crash supervision.
  - Files: `src/trade_plan_monitor/runtime/service.py`, `src/trade_plan_monitor/runtime/reconciliation.py`, `src/trade_plan_monitor/web/monitor_composition.py`, `tests/integration/test_runtime_lifecycle.py`, `tests/integration/test_monitor_production_composition.py`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py -q` against injected new lifecycle; keep public default switch for RR020.

### Checkpoint C3 — Safe autonomous runtime

- [ ] A04 and A08–A11 pass offline; `xhigh` audit of commit/crash/send windows, generation changes and physical-worker cleanup.

## Status and user-visible recovery

- [ ] RR015 — Project lifecycle and scoped status honestly. Effort: `high`. Dependencies: C3, RR002.
  - Acceptance: alive/recovering/standby/blocked distinctions valid; no global boolean authorizes work; live socket cannot hide overdue coordinator progress.
  - Files: `src/trade_plan_monitor/runtime/health.py`, `src/trade_plan_monitor/web/routers/health.py`, `tests/integration/test_runtime_lifecycle.py`, NEW `tests/integration/test_runtime_status_contract.py`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_status_contract.py tests/integration/test_runtime_lifecycle.py -q`.
- [ ] RR016 — Return partial dashboard projections for both plan families. Effort: `high`. Dependencies: RR015.
  - Acceptance: A06/A12; waiting/new symbols cannot hide healthy siblings, explicit rule results use correct storage, cached decisions are not upgraded to actionable.
  - Files: `src/trade_plan_monitor/web/persistent_monitor_read_service.py`, `src/trade_plan_monitor/web/routers/dashboard.py`, `src/trade_plan_monitor/web/routers/symbols.py`, `tests/integration/test_persistent_monitor_read_service.py`, `tests/integration/test_runtime_status_contract.py`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_persistent_monitor_read_service.py tests/integration/test_runtime_status_contract.py -q`; preserve existing dirty index-read tests.
- [ ] RR017 — Version transport and regenerate contracts. Effort: `high`. Dependencies: RR016.
  - Acceptance: exact RR002 version handshake, safe incompatible-client rejection, sequence/generation refresh semantics; OpenAPI and generated types agree.
  - Files: `src/trade_plan_monitor/web/websocket.py`, `tests/integration/test_websocket.py`, `tests/integration/test_openapi_snapshot.py`, `openapi.json`, `web/src/api/generated.ts`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_websocket.py tests/integration/test_openapi_snapshot.py -q`; `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` after approved generation.
- [ ] RR018 — Separate frontend transport and business recovery state. Effort: `high`. Dependencies: RR017.
  - Acceptance: generation refresh, reconnect and snapshot sequence guards retained; active backend degradation does not cause an endless ambiguous STALE/reconnect loop.
  - Files: `web/src/composables/useMonitorStream.ts`, `web/src/stores/monitor.ts`, `web/tests/unit/useMonitorStream.spec.ts`, `web/src/api/health.ts`.
  - Verify: `npm --prefix web run test -- --run tests/unit/useMonitorStream.spec.ts`; `npm --prefix web run type-check`.
- [ ] RR019 — Show standby, retry and per-scope progress. Effort: `high`. Dependencies: RR018.
  - Acceptance: clear cause/next retry or required action; no recovery banner without work; cached cutoff visible and healthy siblings stay usable.
  - Files: `web/src/views/SystemRouteView.vue`, `web/src/components/health/MarketStatusStrip.vue`, `web/tests/unit/SystemHealthRoute.spec.ts`, NEW `web/tests/unit/RuntimeRecoveryStatus.spec.ts` (split additional index-card work if needed).
  - Verify: `npm --prefix web run test -- --run tests/unit/SystemHealthRoute.spec.ts tests/unit/RuntimeRecoveryStatus.spec.ts`; `npm --prefix web run type-check`.

### Checkpoint C4 — End-to-end status contract

- [ ] A06, A11, A12 and type/contract gates pass; `xhigh` review checks old cached clients, explicit-family reads and real progress versus socket activity.

## Integration and handoff

- [ ] RR020 — Enable the complete path and prove real process restart offline. Effort: `high`; fault interpretation/review: `xhigh`. Dependencies: C4.
  - Acceptance: A01–A14 across all target times; stop/kill/restart at commit and dispatch windows; migrations interrupted safely; no provider calls or real notifications.
  - Files: `src/trade_plan_monitor/web/monitor_composition.py`, NEW `tests/integration/test_anytime_runtime_recovery.py`, `web/tests/e2e/production-restart.spec.ts`, `web/tests/e2e/r13-active-process-restart.spec.ts`, NEW `web/tests/e2e/runtime-recovery.spec.ts`.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_anytime_runtime_recovery.py -q`; `npm --prefix web run test:e2e -- production-restart.spec.ts r13-active-process-restart.spec.ts runtime-recovery.spec.ts` with isolated test state.
- [ ] RR021 — Synchronize operations and verification evidence. Effort: `high`. Dependencies: RR020.
  - Acceptance: restart/first-time source validation/reconfiguration/rollback instructions are accurate; record only actually executed tests; English/Chinese match.
  - Files: `docs/operations/live-certification.md`, `docs/operations/live-certification.zh-CN.md`, NEW paired `docs/verification/runtime-recovery-acceptance.md` / `runtime-recovery-acceptance.zh-CN.md`.
  - Verify: compare IDs/commands/thresholds/fields in both languages; trace every A01–A14 result to evidence.
- [ ] RR022 — Run full offline gates and final adversarial review. Effort: `xhigh`. Dependencies: RR021.
  - Acceptance: all proposal section 7 gates pass, current unrelated changes preserved, no unresolved material finding, no secret or relaxed test in diff; list any live-only limits honestly.
  - Files: paired acceptance report and this paired task list (4 files); do not hide fixes in this review task, return them to a bounded implementation task.
  - Verify: run every full command in proposal section 7; review the diff and crash matrix; record actual model/effort where available and user review outcome.

### Checkpoint C5 — Ready for deployment review, not deployed

- [ ] User reviews completed offline evidence. Production backup, real-provider acceptance and rollout are separately authorized. Mark this initiative complete only when its explicitly approved scope is actually achieved.
