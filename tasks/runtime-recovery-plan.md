# Implementation Proposal: Anytime Runtime Recovery

> Status: IMPLEMENTATION IN PROGRESS — proposal approved for implementation on 2026-09-21; not approved for deployment. Original proposal date: 2026-09-17.
> Canonical English proposal; review copy: `runtime-recovery-plan.zh-CN.md`.
> Initiative: `runtime-recovery`. Task index: `runtime-recovery-todo.md`.
> The user's 2026-09-21 instruction authorizes implementation and task-specific subagent allocation. Existing completed plans and unrelated working-tree changes remain untouched. Detailed contracts and checkpoint evidence are recorded below and in the paired task index; no complete-runtime acceptance is claimed.

## 1. Objective and boundaries

An already configured, supported installation must start at any wall-clock time, reconstruct authoritative local state, and autonomously resume eligible monitoring when its dependencies become usable. Closed sessions are normal standby, not failed startup. Unavailable dependencies must produce truthful, scoped status and a scheduled retry where recovery is possible.

Assumptions: one production owner per database, valid local configuration and usable SQLite storage, existing supported provider semantics, and eventual availability of required provider data and permissions. Cold installation against an unknown provider, unavailable historical data, broken storage, and irrevocably revoked permission cannot be guaranteed to recover without intervention. No application can guarantee progress during an operating-system failure.

- Always preserve plan/result canonical bytes, hashes, activation identity, evaluator rules, committed-event ordering, and business-alert intent deduplication.
- Always keep actual provider responses untrusted and validate them before persistence/evaluation.
- Code implementation and temporary-database additive migration tests are authorized. Ask separately before live database migration, a new dependency, real-provider acceptance or deployment.
- Never edit credentials/evidence to fake success, relax trading-data checks, remove failing tests, overwrite unrelated changes, or deploy/restart the user's process during design.
- Out of scope: a new login system, an automatic weekly full-certification service, a general workflow engine, additional broker/order functionality, and an overhaul of trading formulas or notification channels.

## 2. Model and reasoning allocation

| Stage | Model | Effort | Gate |
|---|---|---|---|
| Design, dependencies, interface and migration decisions | `gpt-6-astra` | `xhigh` | Reviewable proposal and explicit invariants |
| Fresh-context adversarial design review | `gpt-6-astra` | `xhigh` | Findings reconciled, remaining risks disclosed |
| Approved, bounded code/test implementation | `gpt-6-sol` | `high` | Focused failing test, implementation, focused passing test; escalate novel safety decisions to Astra review |
| Difficult recovery/identity failures and final integration review | `gpt-6-astra` | `xhigh` | Fault matrix and regression gates |
| Documentation synchronized from settled decisions | `gpt-6-sol` | `medium` | English/Chinese semantic parity and unchanged technical identifiers |

As of 2026-09-23, the model IDs and `high`/`xhigh` efforts remain supported. This prospective allocation uses Sol for bounded implementation and settled documentation while retaining Astra for architectural decisions, adversarial review and difficult failures. Luna is available for focused repetitive work but is not assigned a safety or acceptance gate. This is a workload choice, not evidence that a lower-cost model passes the same checks; compare representative outcomes and latency before further lowering effort. Sources: [official model guidance](https://developers.openai.com/api/docs/guides/latest-model), [model selection](https://developers.openai.com/api/docs/guides/model-selection), and [reasoning effort](https://developers.openai.com/api/docs/guides/reasoning).

Choose the model and effort at task boundaries, not arbitrarily in the middle of an invariant. Do not use `max` by default. If implementation reveals a new architectural or safety decision, return to Astra / `xhigh` review before coding further. Historical reports retain the models actually used; this table applies to future assignments and does not attest the current parent task's runtime model or effort.

## 3. Code findings and reuse

| Current location | Finding | Proposed action |
|---|---|---|
| `src/trade_plan_monitor/live_profiles.py` | Fixed 7-day evidence lifetime gates loading | Separate historical observation from semantic compatibility |
| `src/trade_plan_monitor/runtime/production.py` | Whole-file evidence equality; stock gate also precedes index-only refresh | Use semantic revision and independent dependency gates |
| `src/trade_plan_monitor/web/monitor_composition.py` | Only RUNNING startup receives a supervised task | Supervise the coordinator after valid local bootstrap, including degraded startup |
| `src/trade_plan_monitor/runtime/service.py` | One-shot startup result; read-only run only waits for shutdown | Separate resource lifecycle from repeatable reconciliation |
| `src/trade_plan_monitor/runtime/recovery.py` | Batch results and yield semantics do not themselves establish per-plan readiness | Persist facts, then check the exact required coverage |
| `src/trade_plan_monitor/runtime/health.py` | Identity depends on global readiness and next market deadline | Distinguish generation, coordinator progress, and actionable data |
| `src/trade_plan_monitor/web/persistent_monitor_read_service.py` | Current-generation completeness can make a whole projection unavailable | Preserve per-scope unavailable/cached display without admitting stale decisions |
| `web/src/composables/useMonitorStream.ts` | Non-live heartbeat collapses to STALE | Display authoritative recovery status independently of transport |

Reuse the existing SQLite unit-of-work, durable events, immutable snapshots, source normalization, physical request admission, evaluator transactions, index recovery storage, and supervisor cleanup. Do not broadly split the large runtime service or rewrite unrelated index/turnover work.

## 4. Proposed responsibility map

These are logical boundaries for review, not separate services or approved module specifications.

| Module ID | Responsibility | Dependencies | Main location |
|---|---|---|---|
| `provider-contract` | Parse/migrate semantic configuration and determine compatibility | Existing provider normalizers | New `runtime/provider_contract.py`, existing `live_profiles.py` |
| `runtime-recovery` | Own reconciliation, scoped readiness, session targets and pending work | `provider-contract`, existing request control and storage | Lifecycle in `runtime/service.py`, small new `runtime/reconciliation.py`, `runtime/production.py` |
| `runtime-status` | Project lifecycle/progress and scoped readiness to API and UI | `runtime-recovery` | Existing health, read-service, WebSocket and monitor UI files |

Dependency order: `provider-contract` → `runtime-recovery` → `runtime-status`. Cross-cutting evaluator/alert invariants constrain every slice. Core changes remain sequential; independent read-only review may run alongside design. Multiple agents must not edit the same mutable runtime files concurrently.

## 5. Decisions

### D1. Durable semantics, current operational health

The new semantic record contains `schemaVersion`, normalized `endpointUrl`, `profileId`, capability/interface scope, interval, `sourceTimeLabel`, an adapter compatibility identifier, `verifiedAt`, and migration provenance. `semanticRevision` is computed from interpretation-relevant fields only; verification timestamps and old READY observations do not change it. No credential is stored in this record.

There is no age-based hard expiry. Semantic compatibility is checked against the installed adapter and supported SDK compatibility mapping, not merely a literal SDK field in a file. Changed credentials invalidate current permission observations, not timestamp interpretation. Changed endpoint or incompatible semantics requires verified replacement; unknown semantics remain blocked.

Keep the old evidence readers and integrity checks for historical audit. A dedicated importer accepts only complete, untampered evidence with known schema/profile, matching normalized endpoint, a verified time label and an explicitly reviewed compatibility mapping. It ignores age for this migration only; future-dated or otherwise invalid evidence is not accepted. Stock and index scopes migrate separately; unverified/deferred indexes remain unavailable. Import is idempotent and does not overwrite the source file or change its original dates/hash. A checksum detects corruption; it is not a security signature.

Current operational capabilities start UNVERIFIED and become ready only from validated current operations. Valid locally stored reference coverage may satisfy a plan's input requirement without claiming the provider was just contacted. Reuse normal requests as health evidence. Detectable semantic contradictions block the affected scope; arbitrary silent upstream interpretation changes cannot be ruled out solely by successful parsing. First-time/incompatible-source verification retains explicit operator control and may require an eligible market window.

### D2. One coordinator, separate lifecycle

Local bootstrap loads configuration, opens/migrates storage, restores durable identity/work, and binds read services. Provider requests run in the owned coordinator, not in web construction or a permanently decisive startup check.

The coordinator reconciles local facts with the current session and active plans, selects bounded work, executes through existing admission, persists a result, and recomputes readiness. A missing market deadline schedules calendar/maintenance reconciliation instead of stopping. A degraded result is data, not an exception that destroys the coordinator.

Reconcile on startup, due market/recovery work, validated configuration change, local plan-state change, and a bounded maintenance wake. Proposed maintenance bound: 30 seconds; this is a local check, not a provider poll. Use an interruptible wait and monotonic time for durations. After sleep/wake or clock changes, recompute targets; never consume future-dated data or run every missed timer blindly.

Resource lifecycle remains STARTING/RUNNING/STOPPING/STOPPED with fault reporting. Operational mode is RECOVERING/MONITORING/STANDBY/DEGRADED/BLOCKED and is derived from actual scoped facts. No public mode authorizes an evaluation; the exact plan inputs do.

Stop closes admission, drains/joins physical work, then releases resources. Ordinary network failure does not consume the supervisor's crash-restart budget. Unexpected programming faults and failed cleanup retain bounded supervision and explicit failure; do not spawn replacement workers while old physical requests still run.

### D3. Session targets and scoped completeness

| Situation | Target and behavior |
|---|---|
| Before the first completed minute | Restore references/pending work; no requirement for nonexistent current-day minutes |
| Intraday | Latest completed eligible target; recover its required lookback before evaluation |
| Lunch | Display completed morning facts; wait for afternoon deadlines without issuing a new stale intraday recommendation |
| After close | Reconcile official-close obligations and available completed data; publication lag remains retryable |
| Weekend/holiday | Last known completed session for display and pending close; future open session for scheduling |
| Calendar unknown/outside coverage | Schedule calendar refresh; do not assume a weekday is open or silently exit |
| Restart after a long outage | Restore only justified state and recoverable requirements; disclose unavailable history per affected plan |

Preserve the existing 90-second intraday actionable freshness rule unless separately approved. Session-aware display health must not redefine old data as fresh. Official-close evaluation remains its own target type and is not a fresh intraday buy/sell signal.

Build a requirements set from the captured `TradePlan` or `ExplicitTradePlan`, activation revision, target and dependencies. Check stock/index prerequisites separately. Legacy references, explicit rule-state requirements and optional index conditions retain their distinct semantics. An unavailable required index blocks only plans that require it; unused or deferred indexes cannot block unrelated plans. Missing stock capability cannot block independent display indexes, including the hidden turnover constituent when it is supported.

Readiness follows verified persisted coverage and state prerequisites, not a batch return code or absence of errors. Empty/incomplete current-day results are not complete recovery. Unresolved pending close blocks only dependent state transitions; unrelated plans continue.

Freeze a completed observation cutoff per acquisition; exclude later rows before persistence/evaluation. Recompute current-day acquisition after date rollover rather than asking a current-day endpoint for yesterday. Discover missed legacy official-close obligations from eligible exchange dates and absent committed close identities, not only existing CLOSE_PENDING markers: stopping before 15:20 and restarting after 17:00 must not lose the close. Respect actual activation time/revision and restore dependent close transitions chronologically before the next actionable evaluation. If the historical inputs or activation history cannot justify a transition, keep that plan blocked with an explicit missing-state reason.

Reference-work identity includes the actual dependency set and relevant plan/activation identity, not only `(date, symbols)`. Switching a symbol from ExplicitTradePlan to TradePlan must request newly required history/limits even when the date and symbol set are unchanged. Recovery-work identity does not replace either family's existing evaluation identity.

### D4. Bounded recovery and retry ownership

The coordinator owns what to retry and when to wake; request control owns physical admission, pacing, cooldown and retry permission. Keep one physical provider worker, at least 1.25 seconds between starts, 15-second timeout, and zero immediate in-cycle retries.

| Outcome | Behavior |
|---|---|
| Transient connection failure / timeout | Existing 30/60/120/300-second backoff; repeated cycles continue at the ceiling |
| Rate limit | Shared 300-second cooldown, or longer validated provider instruction; survives process restart |
| Permission rejection | Block normal work; explicit config change or a single controlled recheck may reset the existing operation block |
| Missing credential | No provider request; recheck local configuration on maintenance wake |
| Expected publication lag / incomplete data | Bounded scoped recovery keyed to target and required coverage |
| Incompatible semantics / invalid configuration | Block affected scope; do not retry blindly or import fallback evidence |
| Storage failure / programming error | Visible fault and bounded supervision, not normal provider retry |

Proposed permission recheck policy: one eligible probe per operation every 300 seconds, coalesced, admitted through the same cooldown/queue, never a full certification. It alone may call the existing `reset_permission_block`; failure immediately restores the block. Preserve rate-limit state when credentials change. Do not just put permanently blocked normal calls on another timer.

Use stable failure-scope keys across successive minute targets so new target timestamps cannot bypass backoff. Deduplicate in-flight work; cap the queue at its existing 32 waiting slots and backoff keys at 64. Supersede obsolete display targets; do not discard unresolved business-state obligations. Existing index per-target retry limits are not silently reset by a new loop; distinguish capped old-cutoff publication work from future-target/provider recovery.

A recovery pass handles a bounded unit before reconsidering deadlines and other scopes. Avoid an all-symbol startup batch monopolizing the provider. Give the minimum data needed to unblock an active plan a fair turn; background historical repair yields to live work. If capacity is insufficient, show lag and pending scopes rather than promising a universal recovery time. Persisted coverage is the recovery cursor wherever possible; add explicit work records only where facts cannot reconstruct an obligation.

### D5. Identity, reconfiguration and alerts

Every unit captures the active plan/activation revision, target, semantic revision and runtime generation. Recheck the relevant generation before committing. Configuration reload pauses admission, joins old calls, validates the replacement, then installs it atomically. An invalid edit leaves the affected scope blocked with a visible reason; no silent fallback to a different source. Metadata-only evidence refresh does not replace the runtime.

Do not treat a new generation as permission to rewrite historical evaluations, reuse stale current projections, or re-alert. Reconstruct current health from persisted facts and valid current observations. Keep evaluation identities/unique claims and exact plan activation checks. Historical minute import restores facts; it does not replay expired trading opportunities. State reconstruction requiring historical transitions must be distinguished from a new actionable evaluation, preserve required causal order, and never pretend the plan was active before its actual activation.

Before sending an unsent actionable alert after downtime, revalidate its validity window, plan/activation identity and applicable current status. Obsolete pending intent is retained as auditable history with a terminal suppression reason; do not delete it or create a replacement intent automatically. Preserve non-actionable/official-close notification policy separately. A send that timed out may have succeeded externally; retain current uncertain-delivery handling and channel idempotency. The acceptance guarantee is no duplicate business intent, not impossible universal exactly-once external delivery.

Delivery eligibility is separate from evaluator outputs and hashes. Both evaluation transaction paths must persist state/claims and delivery eligibility atomically; historical reconstruction must never commit an unrestricted dispatchable intent and rely on later WebSocket suppression. Proposed policy: intraday buy/sell/ready reminders expire at their source cutoff plus the existing 90-second freshness allowance, and earlier on activation invalidation. Risk-state notices (including the existing cross-day RISK_BREACH exception and explicit RISK_ALERT) follow their state-validity rules, not this blanket intraday timeout; retain true risk notices and label their historical date. Classify every existing signal in the approved specification. Apply the same gate to pre-upgrade pending rows before any startup dispatch. Legacy and explicit plan loaders must both work in delivery validation. Unknown legacy validity fails closed for sending but retains the record; in-flight external sends cannot be recalled.

Risk notices are held behind a per-plan recovery barrier until all state-changing obligations required to reach the current target are reconciled. If downtime spans a breach on D1 and resolution on D2, the intermediate D1 commit must not release a notice. Immediately before admission to channel I/O, recheck the latest committed risk state, activation revision and completed recovery barrier; unresolved backlog keeps that plan's recovered/pending risk notices on hold. Persist/reconstruct this barrier before startup dispatch and do not mark a temporary hold as terminal suppression. This does not block unrelated plans' notifications. A concurrent state change after external send admission cannot retract an already started send.

### D6. Minimal persistence changes and safe rollback

Use a separate versioned semantic record beside existing live evidence, written atomically. Reuse current history, health, evaluation, index-recovery and outbox storage. Proposed additive migration: a bounded provider recovery checkpoint keyed by configured provider identity and operation, with retry/cooldown timing and sanitized reason; plus minimal delivery-eligibility metadata keyed by existing alert event ID for expiry/suppression, without rewriting event payloads or hashes. Existing coverage/claims remain authoritative; persist extra pending work only when reconstruction is impossible. Resolve the exact migration revision from the then-current Alembic head, not a hardcoded number from this draft.

Migration approval and a usable consistent SQLite backup are prerequisites to production rollout. Import into the new file without modifying legacy evidence. Migration must be idempotent; restart at every boundary must be safe. Never restore a pre-upgrade database over newly written business records as a casual rollback. Prefer a verified old application on a forward-compatible additive schema, or a stopped, reviewed recovery procedure; refuse destructive downgrade while pending state exists. Old binaries may reinstate the old certification problem and are not an anytime-recovery solution.

### D7. Honest status and coordinated protocol evolution

Define one backend-owned status contract with `monitorContractVersion`, `runtimeGeneration`, `mode`, `reasonCode`, `nextWakeAt`, `nextRetryAt`, `lastProgressAt`, and bounded scoped progress. Per-scope views include the required target, data cutoff, reason and readiness. No secrets/raw provider exceptions appear. Empty/missing per-symbol projections must not prevent delivery of runtime status.

Return typed WAITING/RECOVERING entries for a plan without its first current decision, retaining healthy siblings. Dispatch projection parsing explicitly by plan family and read explicit rule results from their own repository instead of the legacy decision head. Never coerce an ExplicitTradePlan through the legacy-only loader to satisfy a dashboard schema.

Generation exists during recovery and standby; it identifies a runtime incarnation, not readiness. Retain generation fencing for current decision projections. Liveness derives from the owned coordinator's scheduled wake or active bounded operation plus real progress; merely sending WebSocket heartbeats cannot refresh it. Differentiate transport loss from an alive but blocked backend.

This is an explicit monitor-contract revision, not an allegedly harmless optional-field change: current health validators tie DEGRADED to global `readOnly`, and heartbeat parsing uses exact keys. Define version negotiation and old-client rejection before implementation. Ship backend, generated types and hashed frontend assets as one local application version; an incompatible cached client must require reload and remain non-actionable. Preserve event sequence monotonicity and snapshot refresh on generation change; no event-type proliferation or reconnect per health tick.

Use existing dashboard and `/system` surfaces for status/progress. Display STANDBY without a stale-data recovery banner; RECOVERING only with active/pending work; failures with a concrete retry time or required action. Existing configuration files remain the configuration entry point, with validated maintenance reload; no new login, token-renewal screen or mandatory recovery button. A retry-now control is not required for automatic recovery and is outside this initial scope.

## 6. Acceptance matrix

| ID | Scenario | Required evidence |
|---|---|---|
| A01 | Compatible evidence older than 7 days | Migrates without source-file edits; operational health still requires actual current evidence |
| A02 | Corrupt/future/mismatched/unknown evidence | Affected scope blocked; no physical request using invented semantics |
| A03 | Restart before open, intraday, lunch, after close, weekend, holiday | Correct target/mode; no nonexistent-data requirement, false LIVE or stale intraday alert |
| A04 | Startup disconnected; provider recovers after several retries | Coordinator remains owned; auto-resume without another process restart |
| A05 | 429 or permission denial, then restore/restart | Cooldown survives; single permission recheck can actually clear the controller block |
| A06 | One stock/index fails; both plan types active | Unrelated eligible plans/index display continue; required dependency remains blocked |
| A07 | Empty/partial recovery, close backlog, constrained request capacity | No premature readiness, no lost obligation, fair progress with bounded memory |
| A08 | Restart before/after evaluation commit or alert send | Stable claims, no duplicate intent, stale pending actionable alerts suppressed, uncertain sends handled |
| A09 | Plan disable/replace/reactivate or source change during a request | Old-generation result cannot produce a current decision/alert; metadata refresh is harmless |
| A10 | Sleep/wake, cross-day, clock reversal, calendar cache exhaustion | Reconciliation recomputes targets, schedules refresh and rejects future data |
| A11 | Healthy socket but stuck coordinator; standby with old display facts | UI reports actual fault/standby; socket heartbeats do not certify business progress |
| A12 | Protocol mismatch, missing projections, migration interrupted | Safe reload/unavailable display, intact historical rows, idempotent migration and usable rollback evidence |

Use injected clocks, fake providers, temporary databases and deterministic process restart tests first. Measure physical starts, queue/backoff bounds, retry timing, completed obligations and alert intents; do not equate green startup with recovered monitoring. No fixed wall-clock full-recovery SLA is claimed before workload measurements. Proposed numerical policies above require approval with the proposal.

## 7. Implementation and verification gates

The task list separates bounded implementation changes (normally 3–5 source/test files) from business acceptance checkpoints. A small commit is a rollback unit, not a completed recovery stage. Do not begin coding while the proposal is DRAFT. After approval, synchronize affected English/Chinese specifications and integrate through the existing production-composition boundary. Do not enable a half-migrated default production path.

### 7.1. Execution workflow revision — 2026-09-22

The user requested higher implementation efficiency before continuing implementation. This revision changes work sequencing and verification cadence, not D1–D7, A01–A12, trading rules, evidence requirements or deployment authority. Existing RR001–RR022 and C0–C5 remain traceable; completed evidence is retained. The task index's five business outcomes are the progress-reporting authority, not commit counts or the model-allocation stages.

- **One active business outcome.** Finish a connected recovery scenario before extending unrelated foundations. Keep internal changes reviewable and independently recoverable, but group adjacent record decoders, their consumers and tests under one outcome. A passing decoder alone does not advance the business stage.
- **Integrate early, enable late.** Build the temporary-database/fake-provider recovery composition and restart harness while implementing the recovery path, not for the first time at RR020. Reuse the real repositories, evaluator transactions and owned coordinator; do not build a second runtime or mock away the boundary under test. RR020 still gates default enablement and full process-restart acceptance.
- **Resolve decisions once.** Before a history consumer, resolve historical cutoff/late registration, risk source-effective meaning and proof budgets together. Review new safety decisions before coding; reuse settled decisions unless new evidence contradicts them. Ambiguous business meaning needs user direction, not an invented default. Missing history stays explicitly unknown for the dependent plan.
- **Test at the right boundary.** Every behavior change starts with a meaningful failing test and runs the affected tests after edits. Each connected outcome runs its integration/crash cases and relevant regression groups. Run the complete section 7 offline gates before final acceptance/default enablement; run broader checks earlier when shared code/contracts change. Never delete, skip, weaken or mark expected-failure tests to obtain a green result. Do not repeat a successful check on unchanged relevant inputs.
- **Review changed risk, not the same context.** Review new trust/transaction/identity/send-admission decisions before implementation and review the connected diff before accepting the outcome. Follow-ups review the finding and affected boundaries; a new material issue broadens review. Do not launch another design review for each helper implementing an unchanged reviewed contract. The user's decision to skip an extra cross-model review remains in force.
- **Bound parallel work.** One owner edits shared runtime/state code. Delegate only an independently useful, non-overlapping test or review task with explicit inputs and output; do not open tasks merely to keep agents busy. Existing model/effort allocation remains unchanged. Status/client work may use a frozen RR002 contract before runtime completion, but cannot claim integrated acceptance until real runtime projection is verified.
- **Keep one work record.** Update this plan only for decisions, the paired task index for progress, and one paired verification report per connected outcome for commands/results/review. Preserve old reports; do not create a new report for every helper. Record tested revision/diff, exact command, scope, result and remaining failures. Update bilingual counterparts in the same change.
- **Report useful progress.** Every handoff states business step, newly working scenario, evidence, remaining blocker and next action. Distinguish implemented, integrated, accepted and deployed. Existing failures remain visible and block final acceptance; historical passing results are not a fresh full-suite pass. No automatic branch creation/switch/merge, push, live migration, real channel/provider operation or deployment is introduced.

Success is measured by accepted scenarios and shorter delay from code to integration evidence, not fewer safety checks. The next target is a proven missed-close recovery in temporary storage: reconstruct the historical state, commit chronologically through the existing evaluator, reopen storage, and prove the same obligation cannot create a second result or alert intent. A broader multi-day/fault matrix is required before business step 1 is complete.

Existing stack: Python `>=3.14,<3.15`, FastAPI, Pydantic, SQLAlchemy/SQLite, pytest/Ruff; Vue Composition API with TypeScript, Pinia, Vitest and Playwright. No dependency change is planned. Python uses typed small functions and frozen boundary values; Vue displays backend facts without duplicating business rules. Generated API types are never hand-edited.

Run from the `trade-plan-monitor` repository with its environment. Commands below are future verification instructions, not claims of execution in this design turn:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest -m "not live"
.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e
git diff --check
```

The offline browser suite must use temporary state/fake providers, never the running user's database, port or notification destinations. Existing tests that encode the old seven-day/global-block policy are deliberately replaced by stronger approved behavior tests; do not merely delete/skip them. Run regression gates for both plan types, activation, index sharing, replay, projections and notifications. Live-provider verification and deployment require separate authorization.

## 8. Review decisions and remaining approval

The 2026-09-21 implementation instruction approved these proposal boundaries: the responsibility map; removal of age-based runtime gating; compatible historical-evidence import; 30-second local maintenance wake; controlled 300-second permission recheck; scoped recovery; suppression of obsolete pending actionable alerts; additive checkpoint migration tests; coordinated monitor-contract upgrade; model allocation. Live migration and deployment remain separately gated.

Detailed module specifications and implementation evidence now follow in the paired task index and `docs/verification/2026-09-21-runtime-recovery-foundations.md`. The index/turnover changes identified during design were already committed before implementation began; preserve those behaviors. Existing failed regressions remain explicitly recorded. Source changes do not authorize changing live configuration, evidence or databases.

### Independent design review reconciliation

Review configuration: `gpt-6-astra` / `xhigh`, isolated context, read-only. Findings were checked against source, not accepted as an implementation verdict. Additional cross-model review was offered and has not been executed.

Three bounded design review cycles were completed: initial fresh-context review, a targeted revised-contract review, and a final review of the risk-recovery barrier. The final cycle found no further substantive issue within that rule's stated constraints. This is design review evidence, not proof of implemented behavior. Paired IDs, heading counts, technical literals/commands and whitespace were checked; all 22 tasks were unstarted at the 2026-09-17 design checkpoint. Current progress is recorded in the task index.

| Finding | Classification | Disposition |
|---|---|---|
| R01: permanent permission latch defeats ordinary retries | Valid + actionable | D4 defines one controlled reset/reprobe, preserving shared cooldown |
| R02: close missed entirely offline has no pending marker | Valid + actionable | D3 derives absent close identities from eligible dates and actual activation |
| R03: empty recovery and future rows lack a completeness boundary | Valid + actionable | D3 freezes cutoff, verifies required coverage, and retargets on rollover |
| R04: historical/queued alerts can still dispatch | Valid + actionable | D5 defines atomic delivery eligibility, preserved risk notices and pending-row checks; D6 adds minimal metadata |
| R05: all-or-nothing/legacy-only projections hide healthy/explicit scopes | Valid + actionable | D7 requires typed partial entries and explicit-family projection |
| R06: date/symbol reference key misses changed plan dependencies | Valid + actionable | D3 keys work by requirements and applicable activation identity |
| R07: an intermediate historical breach may dispatch before a later recovery clears it | Valid + actionable | D5 holds risk delivery until the plan's current-state recovery barrier is complete, then rechecks latest state before send admission |
