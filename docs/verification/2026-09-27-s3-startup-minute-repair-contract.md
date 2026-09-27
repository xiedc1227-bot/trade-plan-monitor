# S3 startup minute repair contract

Status: **F1/F2/F3 design approved / implementation acceptance pending; F1 released for implementation; A07 OPEN**.

Independent Sol review has approved all three slice designs, including F1 normal typed-stale accounting and the final F2 scoped business-fetch interface in F2-04/05. No design blocker remains. F1 is released for independent implementation; F2/F3 await serial source-writer handoff, implementation and acceptance, with F3 dependent on F2. All implementation proof obligations remain open; F1 GREEN alone cannot close A07 or S3-04. This document-only revision updates and locally commits only this contract and its Chinese counterpart; it changes no source, tests or evidence reports and authorizes no push. Earlier code observations were checked at HEAD `4804207`; the SDK handoff observations were rechecked in the current working tree. Line numbers locate observations and are not stable interfaces.

Evidence: the author ran 13 cases with **3 failed, 10 passed in 15.08s**; the independent run had **3 failed, 10 passed in 14.90s**. These are separate runs, not additive. Ruff passed, oracle P2 is closed and the evidence reports are aligned. The genuine failures remain two empty/partial startup RUNTIME_RUNNER_FAILED cases and one frozen-cutoff case that writes 10:01 despite a captured 10:00 cutoff. Current progress succeeds through supervisor replacement and a legal 10:05 decision at 10:05:12; this is not evidence of normal scoped recovery. S3-04 remains OPEN.

Evidence: [English report](2026-09-27-s3-startup-minute-coverage.md) · [Chinese report](2026-09-27-s3-startup-minute-coverage.zh-CN.md).

## A07-F1 — F1 — Preserve INCOMPLETE with exact originating-plan identity

### A07-F1-01 — Ownership and interface

The released F1 implementation changes `runtime/service.py` and `runtime/explicit_service.py`; it targets `tests/integration/test_ten_symbol_runtime.py`, `tests/integration/test_market_index_runtime.py`, `tests/integration/test_explicit_runtime_production.py` and the existing A07 test file, outside this document-only slice. Introduce an internal immutable `PlanCycleOutcome` with the original identity and exactly one of a real cycle result or a closed `STALE` disposition identifying the typed pre-commit guard failure. Identity carries consumer kind, symbol, plan_id/version/hash, activation_revision and target_bucket_end. Capture ordered candidate identities before the provider/index awaits; after bucket availability is known, select the due subset without recapturing activation. Bind each original due identity to its own coroutine before filtering outcomes. Never zip already-filtered result sequences or infer identity from optional facts.

### A07-F1-02 — Compatibility and stale outcomes

Add a strict associated-outcome entry point for the production coordinator. Preserve the existing public tuple-of-result contracts and stale filtering of `run_intraday_batch` and `run_intraday_batch_from_minutes`; share the evaluation implementation, not the filtered output. Strict evaluation propagates `StaleActivationGenerationError` or `StaleExplicitDecisionError` only as far as the wrapper for that original plan, which records a `STALE` outcome. These exceptions must originate from the evaluator's pre-commit guards. `StaleExplicitDecisionError` covers activation, inventory and manual-event-risk changes; all three are normal invalidations of the captured work. Keep the conversion boundary around pre-commit evaluation, not the whole `run_intraday_and_publish` call: even the same exception type raised during publication must propagate, not become `STALE`. Storage, publication, programming/protocol errors and cancellation remain errors; no broad `RuntimeError` catch is added.

The coordinator accounts for every original due identity, including `STALE`, then returns only real cycle results in original due order. An all-stale batch may return an empty public tuple only after complete internal accounting. A missing outcome remains missing and fails closed; it cannot be relabelled stale. A stale sibling neither cancels other valid plan coroutines nor rewrites their identities. Results are associated per plan, not committed atomically as a batch: a valid sibling may already have committed, and a later association error does not promise to roll it back.

### A07-F1-03 — Exact validation for both consumers

Validate the complete ordered expected identity set, omissions, duplicates and extra outcomes before extracting the public result tuple; a symbol dictionary must not overwrite duplicates. Where facts or evaluation_result exist, cross-check their actual symbol, plan hash, target and any represented plan/formula identity. Legacy fields that are absent stay supported by capture and transaction guards. `ExplicitEvaluationResult` actually carries `activation_revision`: require it to equal both the originating identity and the strict captured revision, including DUPLICATE results. Validate relevant explicit result identity before persistence as well; an envelope check after business commit cannot fence a wrong activation.

Today `RuntimeDeadlineCoordinator.run_deadline` captures revisions near `service.py:2547`, then awaits acquisition, but explicit `_capture` near `explicit_service.py:223` calls `_require_active(..., None)`. A deactivate/reactivate of the same plan during that wait can therefore be accepted as a new revision before the old due call commits. Add optional internal `expected_activation_revision: int | None = None` through `run_intraday_and_publish`, `run_intraday` and `_capture`. Production always supplies the revision captured before the await; strict `_capture` passes it to `_require_active`, and final commit checks that same revision again. Never replace it with the newly observed active revision. The `None` default retains existing standalone callers' behavior; it is not allowed in the production strict path.

### A07-F1-04 — Normal incompleteness and transitional RED

Legacy INCOMPLETE remains a legitimate result with facts=None and no evaluation, claim or event. Existing minute/health persistence may continue, but no business result, risk, outbox, pending or head may be created. Missing or mismatched outcomes still fail closed; do not catch RuntimeError or fabricate facts. F1 can turn the existing progress cases RED because it removes their accidental supervisor-restart recovery. Record this intermediate state and require F3 before claiming the repair complete.

### A07-F1-05 — Stale lifecycle and mandatory race controls

`RuntimeLifecycleService._execute_deadline` near `service.py:3483` only awaits owned work and releases it in `finally`; it does not absorb typed stale errors. Allowing normal reactivation to escape there would create a new `RUNTIME_RUNNER_FAILED` path. The per-plan conversion in F1-02 is the selected boundary; the lifecycle receives a successfully accounted deadline, not a stale exception. It continues with its original market cursor and the next eligible deadline. Do not reevaluate the replaced activation at the old target, rewind the cursor, or discard a genuine missing outcome. Mutable explicit safety-fact staleness is likewise accounted under its original due identity, without an in-place retry. Unexpected errors still reach supervision.

RED must include a real composition/provider wait between coordinator capture and explicit `_capture`: deactivate and reactivate the same plan while acquisition is parked, then release it. Assert the original identity has the dedicated typed stale outcome, the rejected scope makes zero new business writes under either the old or new revision (including explicit ledger/rule occurrence/outbox), and its pre-existing business rows remain unchanged. Assert no RUNTIME_RUNNER_FAILED, the same runtime generation, and a healthy sibling's independent commit under its own captured identity. Drive the next legitimate scheduler deadline and require continued operation, without inventing a new target for the rejected invocation or replaying it. Also change activation after explicit evaluation but before its final transaction, exercise the legacy typed-stale path, and prove a non-stale `RuntimeError` and a publication-stage stale-typed exception still propagate. Missing/duplicate/extra/wrong-identity outcomes must not enter the stale catch. Public-default compatibility and normal INCOMPLETE remain separate controls. These real-composition assertions are mandatory F1 implementation acceptance gates, not deferred to F3.

## A07-F2 — F2 — Freeze acquisition scope and fence each commit

### A07-F2-01 — Files, dependencies and single-writer ownership

Use `runtime/recovery.py`, `runtime/recovery_targets.py`, `runtime/production.py`, `market_data/tushare.py` and, from F2 onward, `web/monitor_composition.py`; `runtime/service.py` participates in the authority-writer audit and any required ownership/cancellation wiring. A minimal flush/commit seam in `state/unit_of_work.py` is allowed only if needed for the final fence. The completed SDK-boundary implementation protects permission-proof calls, not the ordinary business fetch used by recovery. Reuse that resolver/final-entry mechanism through the new opt-in in F2-04/05; do not claim the business guard already exists. All `market_data/tushare.py` and further SDK-boundary edits belong to one designated writer after handoff. F2 design is approved, including the shared-lock protocol below; implementation still requires serial source-writer handoff and acceptance, not concurrent edits.

### A07-F2-02 — Immutable capture and exact requirements

Reuse `derive_recovery_target`, `select_current_day_rows` and `check_minute_coverage`. Each immutable `RecoveryCapture` carries observed_at, calendar-derived trade_date/completed cutoff, required_ends, exact plan identity/activation revision, configuration/source/minute-semantics revisions and runtime generation. Queueing or a late response cannot advance its cutoff; only a new attempt may capture a later target. Legacy required_ends is the exact trading-minute prefix from session start through the captured completed minute, excluding lunch and bounded by 240.

### A07-F2-03 — Committed coverage and safe writes

Compute the difference from actual committed minute identities, never a count, maximum timestamp, or health gaps alone. The pre-fetch missing set is only an acquisition hint. In the final owned transaction, reread the captured `required_ends`, recompute `missing_now`, and intersect verified response rows with it immediately before staging writes. If another legal writer filled a minute while this request waited, do not upsert that row, its OHLC/volume/received_at, or its latest_quote contribution, even if response-time normalization gave the older fetch a later received_at. Empty responses and an empty final difference are no-op fact writes. Minute completeness does not replace reference, historical official-close, inventory, rule or freshness gates.

### A07-F2-04 — Per-invocation seams

Extend `recover_scope` with an optional per-invocation persistence seam such as `persist_selected(rows)` and an invocation guard, while keeping the existing constructor callback as the compatibility default. Production must pass its captured closure explicitly. Never temporarily replace `self._persist_minutes` or another shared callback. Each attempt closure reads immutable capture and its own cancellation token.

Add an optional invocation-local business-fetch callback for this scoped path, threaded through `_execute_joined` to `_current_day_call`. The callback binds that attempt's physical-entry guard and calls the concrete provider's `current_day_minutes(symbol, _physical_start=...)`; add this optional keyword to that concrete method and forward it unchanged to `_fetch_frame(_physical_start=...)`. The generic provider protocol and ordinary no-hook callers retain `current_day_minutes(symbol)` without an added keyword. If no scoped callback is supplied, recovery retains its existing provider call. Do not mutate a provider/controller-wide hook or use permission-proof results as business minute rows. This is an internal acquisition seam, not a new business policy or user parameter.

### A07-F2-05 — Capture and physical SDK admission

Capture consistent active plan, activation, calendar and source binding in a short owned UoW, and retain the owner-published authority epoch/generation and an attempt-local thread-safe cancellation token. Hold no database transaction or authority lock while awaiting the provider. Currently `_current_day_call` near `recovery.py:575` checks before calling ordinary `provider.current_day_minutes(symbol)`; `tushare.py:296` exposes no per-call hook. That early check cannot guard wrapper preparation I/O. With F2-04, `_fetch_frame` first resolves the actual inner SDK endpoint through the existing resolver (including wrapper preparation), then invokes the attempt-local `_physical_start`, then invokes the endpoint. At this final SDK boundary check only thread-safe clock/source/generation/cancellation authority, outside provider exception classification, preserving `RequestNotStartedError`. Keep the early recovery check as an additional guard, not a substitute. The worker must not query the database or inspect an asyncio Task. An edit after entry may allow one obsolete read-only fetch; the final transaction rejects its result. Admission checks do not eliminate that window.

### A07-F2-06 — Transaction commit fence

After the response, validate clock, source bindings and rows. The synchronous owner-loop persistence closure opens a fresh owned transaction and rereads exact active plan payload/hash/version, activation revision, trading-day requirements and required minute identities. Stage only `missing_now` rows from F2-03; minute and latest_quote changes belong to this same transaction. Resolve external-file validation and callback-driven invalidation before the final fence. Flush staging before entering the fence if commit would otherwise invoke staging callbacks.

Enter the baseline authority `RLock`; read the final in-memory revoked/epoch, generation, acceptance and attempt-cancellation state, plus a fresh thread-safe clock/date check, then perform synchronous commit without await or application callbacks. On a failed guard, leave the critical section and roll back the entire transaction. No network, file reload, notification, physical-worker join or additional identity queries occur under this lock. In particular, do not call `_decision_commit_current` inside it: that helper includes configuration/certification file I/O and may publish revocation. Perform those authority validations outside the lock, then use a dedicated final memory-only predicate over the current owner state; an earlier cached boolean is insufficient. Scope recovery may not reuse the unfenced generic `persist_minutes` callback. This protocol fences scoped acquisition commits; it does not claim to retrofit every other business transaction in the application.

### A07-F2-07 — Authority assumptions that require proof

Add one `threading.RLock` to `_ProcessRuntimeBaseline`, shared by the runtime state and every scoped persistence closure in that process. Both `_revoke_configuration` and `_revoke_semantics` currently publish `Event.set()` directly from workers before notifying the loop (`monitor_composition.py:1178/1196`); change both to publish the revoked flag/authority epoch while holding this same lock, then notify the owner only after releasing it. Merely relying on no await does not order these worker writes. Revocation that has acquired the lock and published first makes the commit fail; a commit that wins the lock may finish before the blocked revocation publishes. Commit is the linearization point; later revocation does not delete it retroactively.

Use `RLock`, not a non-reentrant lock, because validation can synchronously call a revocation callback. Run such validation before the final memory-only predicate, recheck revoked state after it, and never put arbitrary callbacks inside the check-to-commit interval. Current UoW commit has no application publication callback; preserve that property. Revocation publication must never acquire a DB connection or wait for a worker/owner while holding the lock. Staging may hold SQLite write ownership before taking the authority lock; the reverse lock-to-DB acquisition order is forbidden on revocation paths. The section contains only bounded in-memory checks and the existing bounded SQLite commit, not provider work.

Runtime generation assignment, acceptance/stop and attempt-token cancellation are owned by the event loop. Their normal changes cannot interleave with its synchronous closure; cancellation sets the thread-safe token before cancelling the owned task. The implementation writer inventory must also cover final generation replacement, database resource readiness/disposal and every dependency of `business_commit_admission_open`: `_stopping`, `_cleanup_complete`, `_cleanup_failed` and `_liveness_failed`, including heartbeat/liveness failure and cleanup paths. The final memory predicate must preserve these dependencies, not check generation equality alone. Cross-thread requests for any such changes must either marshal to that owner without directly changing authority, or publish the change through the same lock before notification. Moving scoped persistence off-loop without also enrolling those setters in the protocol invalidates this proof.

Separately prove the DB fence with the real application engine and two connections: A executes explicit BEGIN and reads plan/activation identity; B deactivates/reactivates and commits; A then attempts minute/latest_quote writes. A must fail to upgrade its stale snapshot and roll back the whole transaction; B's new activation remains intact. No connection/session retry may reuse A's old capture. Surface the recognized storage conflict to the owner; any later attempt starts from a new capture. Also prove revocation published before final lock acquisition yields zero writes, the commit-first ordering, and a reentrant revocation callback without deadlock.

### A07-F2-08 — Error channels and cancellation

Keep guard invalidation/retargeting separate from normal INCOMPLETE, provider failure and storage failure, using a typed internal disposition or a dedicated exception translated only at its intended boundary. Narrow the broad Exception-to-PERSISTENCE_FAILED catches in recover_scope: guard changes follow F3-09; identified storage failures retain their type/cause for the owner; programming errors and cancellation propagate. In particular, DB snapshot-upgrade conflicts do not enter a generic old-capture retry loop. Do not classify guards as permission/cooldown failures or silently retry them forever.

### A07-F2-09 — Clock and calendar limits

On rollover or now earlier than captured_at, reject this attempt's write and recapture. An unknown calendar cannot invent a trading day or justify using a current-day endpoint to repair history. Check clock reversal at each phase; reversal and restoration entirely between observation points is not detected without a separate clock-epoch facility, which is outside this slice.

### A07-F2-10 — Startup integration before F3

First replace startup stock-minute acquisition with the frozen scoped path, preserving existing official-close recovery order and startup error policy. Each symbol has its own capture; the transitional startup is bounded to at most 10 symbols and 240 required minutes per symbol. F3 subsequently reduces startup to at most one stock acquisition and schedules the remainder. No new database state is needed. Keep business recovery separate from permission-probe semantics.

## A07-F3 — F3 — Bounded autonomous prefix recovery in the existing owner

### A07-F3-01 — Scheduler interfaces and ownership

Use `runtime/production.py`, `runtime/scheduler.py`, `runtime/reconciliation.py`, `runtime/service.py` and `web/monitor_composition.py`. Reuse the pure `RecoverySchedule`; do not start a separate `RecoveryCoordinator` background loop. The approved design adds an internal `STOCK_RECOVERY` maintenance deadline and `next_stock_recovery_at` / `run_stock_recovery_unit` wiring, owned by the existing runtime `_execute_deadline`. The scheduler's next callback reads only in-memory timing. Synchronize bounded requirements at initialization and after recovery/market work.

Use a stock-specific schedule instance; keep independent index scopes and their permission owners unchanged. The stock owner caches the next wake, requirements and permission observations. It refreshes those bounded local observations at startup, after market/permission/recovery work, and at maintenance polls; the scheduler getter performs no DB read, permission probe or state mutation. An existing permission owner may notify the loop to resynchronize, but no second loop or hidden request is introduced.

### A07-F3-02 — Bounded work, stable retry and fairness

Each maintenance wake handles at most one symbol, one current-day request and 240 committed minute identities. Enumerate at most 10 active identities in a short read and choose eligible scopes round-robin; do not scan unbounded history. Use a stable key such as `stock-prefix:{symbol}` and a revision representing dependency identity, target and the local permission-readiness epoch defined in F3-10. Preserve RecoverySchedule's RETRY deadline across target revisions and late completion so each new minute cannot bypass cooldown. A failing symbol must not starve other eligible symbols. All calls still share existing controller pacing and HTTP 429 cooldown; independent index scopes are not permission to bypass that shared limit.

Reuse the actual live controller's existing `LIVE_TUSHARE_IN_CYCLE_RETRIES=0`. The earlier concern based on generic default `execute` retries does not apply to this production composition and is withdrawn; F3 introduces no retry interface or new retry policy.

### A07-F3-03 — Restart, partial data and retry timing

Final startup performs at most one stock scoped acquisition; real maintenance wakes handle the remainder. Restart reconstructs requirements from active plans and committed coverage, without pending tables. Complete existing prefixes create no duplicate business records; partial facts are preserved and only missing identities are repaired. Empty/partial responses are normal incomplete scopes: finish the ticket as RETRY at completion time plus the existing `MAINTENANCE_INTERVAL` of 30 seconds, not immediate PENDING. Local polling has a 30-second ceiling, but physical entry may wait longer for the market reserve, provider next_retry_at or shared cooldown. These ceilings are not a recovery SLA. Storage/programming faults are not normal incompleteness.

### A07-F3-04 — Real market priority and admission

Maintenance uses real market deadlines, with market work winning ties. Reuse the 31.25-second reserve: yield when now plus reserve reaches a market deadline and return a concrete next wake without a busy loop. Recheck the frozen market window at actual SDK entry after queueing. Do not mistake the maintenance task's own running state for realtime work. Timeouts/drain remain owned by the existing runtime/controller; the reserve does not prove an arbitrary provider can never overrun.

Adding the enum and dispatcher branch is insufficient. Define one explicit lifecycle maintenance classification containing existing `INDEX_PERMISSION` and the approved `STOCK_RECOVERY`, and use it at both `service.py:3225` (`_advance_progress_deadline` must not advance `_last_deadline_at`) and `service.py:3089` (elapsed-market review must retain `market_review_after`, not replace it with the maintenance due_at). Preserve existing `INDEX_RECOVERY` behavior unless separately reviewed. If no prior market cursor exists, preserve the current pre-execution observation used by this path; do not infer an earlier startup cursor. After a maintenance request waits or overruns, the existing bounded review may consume exactly one elapsed REALTIME_MINUTE duty only while its original target has age 0..90 seconds. Multiple elapsed duties remain subject to the existing no-replay behavior.

### A07-F3-05 — Startup reserve policy and the substantive C2 control

The existing C2 starts its SDK call at 10:00:59 and returns at 10:01:13, inside the 31.25-second reserve before the 10:01:12 market deadline. Apply the new reserve guard only to normal maintenance. Preserve admission for the one bounded startup call and freeze its cutoff. Current `_start_sequence` near `service.py:3000` asks for `next_deadline()` after recovery; that scheduler excludes earlier due times. There is no existing immediate startup elapsed-deadline execution path to preserve. This design adds none: C2 may proceed to the next future market duty after startup. The elapsed review in F3-04 applies after scheduled maintenance, not as startup replay. Extending the reserve to startup or adding immediate startup catch-up requires separate review. C2 must retain its actual admitted 10:00:59→10:01:13 SDK call; suppressing the call cannot count as fixing cutoff fencing.

### A07-F3-06 — Legacy and explicit requirements

Legacy needs the complete current-day minute prefix. Explicit evaluation keeps its actual FiveMinuteBars dependencies: current-bar conditions and rolling-volume window_bars+1 with legal trading adjacency are different requirements. Do not impose legacy prefix readiness on every ExplicitTradePlan. Existing bounded current-day minute prefetch for explicit plans may remain, but it does not prove cross-day lookback recovery. Preserve existing explicit evaluation/dependency behavior; new condition-derived historical recovery requirements require separate review.

### A07-F3-07 — Decision freshness and preserved lifecycle contracts

Recovery persists facts and rechecks coverage; it does not replay missed five-minute decisions. Evaluation runs only through eligible realtime work or the existing bounded post-scheduled-work elapsed review in F3-04, with actual evaluated_at minus target in 0..90 seconds. Normal incompleteness and expected per-scope stale invalidation do not set global DEGRADED or trigger runner replacement. Preserve manual stop/edit/start, 120h liveness admission, and autonomous official-close discovery/idempotency without rewriting that chain. No new business/user parameter is introduced.

### A07-F3-08 — Cancellation, drain and propagation

Stop first revokes admission and the attempt cancellation token, then cancels the owned task. Continue shield/join for physically started workers; do not release the request slot before drain or dispose the database early. Late responses cannot write. Late provider failures follow existing controller accounting while drain completes; cancellation is ultimately re-raised. Normal-path errors go to the owner rather than being swallowed by a new maintenance loop.

### A07-F3-09 — Closed maintenance outcome matrix

This is the approved handling contract at `run_stock_recovery_unit`, not a broad exception handler and not a change to unrelated market-work error policy.

| Observed outcome | Scope/owner action | Physical-call boundary |
|---|---|---|
| Exact committed requirement complete | READY for that revision; future target changes may require a new scope attempt | No fetch merely to prove already committed coverage |
| Valid empty/partial response, residual missing identities | Preserve verified new facts; RETRY at completion + 30 seconds | Respect reserve and controller eligibility before retry |
| Retryable provider failure, rate limit or cooldown | Retain typed provider category; RETRY no earlier than both completion + 30 seconds and provider next_retry_at | Preserve later deadline across target revisions/late completion; shared 429 pacing still applies |
| BLOCKED_PERMISSION | BLOCKED, retaining the operation and blocked authority observation | Business recovery must not call `recheck_permission`, clear the block or treat a business success as proof; rearm only under F3-10 |
| Local admission yield / `RequestNotStartedError` | Identify reserve deferral versus invalid capture; yield to the next concrete market-safe wake or recapture on a bounded later wake | Zero physical attempt; never manufacture a provider failure/cooldown |
| Activation/target/date/clock guard invalidation | Discard stale closure, resynchronize exact requirements and recapture; remove deactivated scope | No old-capture retry; if no authoritative calendar/target exists, make no current-day request and retain a bounded local recheck |
| Configuration/source/semantic revocation or NEEDS_RESTART | Publish F2 revocation and hand off to existing runtime blocked/restart handling | No rearm, hot reload or business call under the revoked baseline |
| Runtime generation no longer current or stopping | Terminate work for that owner; replacement generation reconstructs its own requirements | No retarget loop in an obsolete generation |
| Storage error, including stale SQLite snapshot upgrade; programming/protocol error | Roll back and propagate the typed error to the existing owner | No conversion to empty/partial/provider failure, no automatic old-capture retry |
| Cancellation | Re-raise after existing physical-worker drain/accounting | No late fact commit or premature slot/DB release |

### A07-F3-10 — Explicit BLOCKED rearming

`RecoverySchedule.claim` skips BLOCKED, and its unchanged requirement never rearms itself. Also, `synchronize` normally resets a changed non-RETRY requirement to PENDING. Therefore the stock owner must freeze the blocked schedule requirement revision while its authoritative controller operation remains blocked; changing clock/target alone must not reset it. Track the latest desired target separately in the bounded owner cache, without making it runnable. A newly discovered blocked scope may complete one local ticket as BLOCKED without any SDK request.

At the owner synchronization points in F3-01, observe `is_permission_blocked(operation)`. Only a previously observed blocked→cleared transition from the authoritative controller, under the same non-revoked source/semantic binding, increments that scope's local permission-readiness epoch. The separate reviewed permission owner is responsible for proving/releasing that block. Replace the frozen requirement with the latest captured dependency/target plus the new epoch using `synchronize`; this deliberate revision change rearms BLOCKED as PENDING. Recheck controller permission/cooldown again before physical entry. An elapsed retry time, fresh target, provider health label or generic business response is not this transition. If the dedicated permission owner cannot supply clearance, the scope stays BLOCKED; F3 does not invent a recovery probe. Polling/notifications update the cached next wake; the scheduler getter itself remains read-only.

## A07-VERIFY — Implementation order and RED verification matrix

### A07-VERIFY-01 — Slice A: result association

F1 design is approved for independent implementation. First demonstrate RED for facts=None association, missing/duplicate/extra outcomes, wrong symbol/hash/version/activation/target, typed stale accounting, mixed consumers and input ordering. Include the actual same-plan deactivate/reactivate await race and final-transaction race from F1-05; assert no new-revision business commit by the original invocation, a valid sibling's independent success, no runner fault/replacement for expected stale, and continued propagation of unexpected errors. Add explicit inventory/risk invalidation, publication-stage stale-type propagation and public-default controls. Record transitional progress RED rather than weakening its expectations. F1 GREEN alone cannot close A07.

### A07-VERIFY-02 — Slice B: per-call scope and frozen startup

F2 design review is complete; implement only after serial source/SDK writer handoff, then satisfy the acceptance gates. Preserve SSMC-C2 as RED before the fix and GREEN after it, plus SSMC-C1 future-row rejection and SSMC-C3 acceptance under a new capture. Cover empty/partial/residual exact identities and concurrent captures without callback leakage. A competing legal write during provider wait must retain the exact minute and latest_quote values/timestamps after the stale response returns. Use two real connections and explicit BEGIN for the A-read/B-reactivate-commit/A-write race; prove whole-transaction rollback and no old-capture retry. Test worker-published configuration and semantic revocations before the final fence, commit-first ordering, reentrant callback safety, all relevant authority writers, stop/edit/restart, rollover and clock reversal. Neither a post hoc assertion nor a no-await-only test proves the cross-thread guarantee.

Exercise the real provider/wrapper/resolver path with offline fakes: allow wrapper preparation I/O, then publish revocation or advance beyond the maintenance entry window before resolver return. Require the scoped business hook to reject at final entry with zero actual SDK calls; an adapter-entry-only fake is insufficient. Also prove hook isolation between concurrent captures and ordinary no-hook compatibility. Retain the legitimate startup C2 SDK call at 10:00:59→10:01:13 and its frozen cutoff; the maintenance reserve must not suppress it.

### A07-VERIFY-03 — Slice C: actual autonomous progress

F3 design is approved, but implementation and acceptance remain pending F2 and serial source-writer handoff; use real composition and scheduler wakes. After empty/partial startup, restore provider history and require original-prefix repair and a legal 10:05 decision at 10:05:12 within the fixture's finite horizon. Replace the current generation-change print-only observation with hard assertions that the generation captured after initial startup is unchanged throughout recovery and at final success, with no RUNTIME_RUNNER_FAILED boundary. Do not directly invoke recovery/evaluation, force DEGRADED or rely on supervisor replacement. Preserve separate safety assertions while history remains unavailable and all actual evaluation-time/source-prefix checks.

### A07-VERIFY-04 — Slice D: boundedness and lifecycle

Verify ten-symbol round-robin fairness, one symbol cooling down while others advance, market tie priority and physical-entry recheck, rolling targets that cannot bypass retry, and BLOCKED scopes that rearm only after an observed authoritative permission clearance. A maintenance call queued across a market deadline must preserve both the market cursor and review start, consume at most the existing one fresh elapsed duty with its original target and actual age 0..90 seconds, and reject stale/multiple elapsed replay. Prove startup still selects a future deadline and C2 still admits its crossing call. Cover every F3-09 row, complete facts without duplicate business effects, partial facts surviving restart, independent index scopes/shared 429 pacing, blocked-worker stop without premature DB closure or slot release, and zero late-response writes.

### A07-VERIFY-05 — Slice E: regression and evidence accounting

Independently rerun the original 13 A07 cases, retaining all three oracle controls. Run the new gates and adjacent coordinator/recovery/scheduler/lifecycle checks, the four existing official-close kill/restart cases, and targeted 120h/manual-admission regressions. Record author and independent runs separately rather than adding overlapping suite counts. Update material documentation in both languages. Claim completion only when the three genuine failures and normal autonomous recovery are all resolved with evidence.

## A07-SCOPE — Unapproved extensions and residual authority limits

### A07-SCOPE-01 — Excluded architecture and behavior changes

No persistent recovery queue or database migration, official-close rewrite, general dispatcher for all business scopes, global DEGRADED policy, automatic plan/liveness changes, historical decision replay or new freshness threshold is approved here. Approval of these slice designs does not authorize those extensions or source implementation in this document-only slice; F2/F3 still require their serial source-writer handoff.

### A07-SCOPE-02 — Existing fact provenance

The canonical minute table has no per-row source/minute-semantics revision. Capture fencing constrains new acquisition writes; it cannot retroactively establish semantic provenance of existing facts. Source-switch purging/rebuilding and provenance proof require separate design, not an implicit assumption or a claim of current protection.

### A07-SCOPE-03 — Additional recovery and authority policy

New explicit historical-lookback recovery, autonomous unknown-calendar recovery, startup reserve/catch-up policy changes and a clock-epoch facility are separately bounded review topics. F2 orders new scoped commits against already published runtime revocations; it cannot make an arbitrary external configuration/semantic-file write atomic with SQLite, detect an unobserved edit, or authorize hot reload. Existing minute provenance remains limited by F2-03 and SCOPE-02. DB commit-race and cross-thread revocation guarantees are still proof obligations, not implementation facts. All three designs are approved and implementation acceptance remains pending. F1 is released independently without closing S3-04 or hiding transitional progress RED; F2/F3 await serial source-writer handoff, with F3 dependent on F2. Keep the three existing A07 evidence files unchanged and uncommitted during this document-only slice.
