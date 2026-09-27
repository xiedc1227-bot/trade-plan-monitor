# C1 unified permission dispatch contract

Status: **Design approved after independent Sol review / not implemented**.

The two review P2 findings are closed: UPD-03/R05 distinguish scope arbitration from the actual candidate frozen after one DAILY_BARS preparation; UPD-04/R02 distinguish pure timing getters from bounded fresh B1 evidence peeks. S1–S5 may proceed with the source handoffs and implementation acceptance gates below. This is not C1 or A07 completion.

## UPD-01 — Scope, authority and evidence

This proposal connects the approved B1/B2 selection/reservation contracts and SMWO stock-minute owners to one eight-scope permission-maintenance path in RUNNING and DEGRADED. It specifies integration, clocks, error ownership and acceptance, not new permission-proof or trading policy. C1 remains OPEN. This task creates only this contract and its Chinese counterpart; it changes no source, tests or existing documents and makes no commit.

Read-only observations used HEAD `47a803b` and the shared working tree on 2026-09-27. Stock-minute execution and A07 F1 source writers are active; their uncommitted work is not accepted evidence. Symbol references below identify integration points, not fixed line numbers. SMWO execution acceptance is a prerequisite to enabling its scopes automatically. The A07 F3 design is approved but not implemented by this proposal.

Authority: [runtime recovery plan](../../tasks/runtime-recovery-plan.md), [B1 selection](2026-09-26-b1-permission-candidate-selection.md), [B2 reservation acknowledgement](2026-09-26-b2-controller-reservation-ack.md), [B2 rotation](2026-09-26-b2-permission-candidate-rotation.md), [SMWO](2026-09-27-c1-stock-minute-permission-owner-contract.md), [SDK boundary](2026-09-27-c1-sdk-call-boundary-contract.md), and [A07 repair](2026-09-27-s3-startup-minute-repair-contract.md). Their accepted proof identities, bounds and source-mode differences remain authoritative. Reuse the accepted DAILY_LIMITS, DAILY_BARS and INDEX_DAILY owners, including DAILY_BARS demand receipts and O/F alternation; do not repeat or generalize those proofs here.

No hot reload, provider/notification service, real user database, migration, push or deployment is authorized. Future tests use temporary SQLite, fake SDK/transport, real wrappers/controllers and controlled clocks. No passing implementation result is claimed in this design document.

## UPD-02 — Complete scope inventory and confirmed gaps

The registry order is exactly the existing `_PERMISSION_SCOPES` order; selector, cheap getter and dispatcher must use the same registry.

| Scope | Exact endpoint | Integration obligation |
|---|---|---|
| `TRADING_CALENDAR` | `trade_cal` | Replace the inline `_request` recheck with a selected, locked owner; add final SDK-entry hook; preserve exact completed SSE anchor, including a closed day |
| `INDEX_HISTORICAL_MINUTES` | `idx_mins` | Add shared lock, global selection and durable acknowledgement to the old owner; add final SDK-entry hook; preserve its completed-session proof |
| `INDEX_REALTIME_MINUTES` | `rt_idx_min_daily` | Add shared lock, global selection and durable acknowledgement; reuse the reviewed final SDK boundary and existing index proof |
| `DAILY_LIMITS` | `stk_limit` | Integrate the accepted date-wide owner and today-eligible legacy demand |
| `DAILY_BARS` | `daily` | Integrate the accepted current/historical legacy demand receipt and O/F owner |
| `INDEX_DAILY` | `index_daily` | Integrate the accepted independent index owner |
| `CURRENT_DAY_MINUTES` | `rt_min_daily` | Integrate SMWO after its execution acceptance; preserve its independent symbol cursor |
| `REALTIME_MINUTES` | `rt_min` | Integrate SMWO after its execution acceptance; preserve its independent symbol cursor |

Today composition `next_index_permission_at` and pipeline `run_deadline(INDEX_PERMISSION)` consider only the two index-minute scopes. `_request(TRADING_CALENDAR, ...)` can trigger `_maybe_recheck_calendar_permission` outside global arbitration. The older index owners have no shared maintenance lock or `on_reserved` callback. The existing cheap `next_permission_probe_due_at` already scans eight controller/local time entries without SQLite; use it instead of the old authority-reading index getters for automatic scheduling.

Commit `4804207` does not cover final SDK entry for calendar or historical index permission calls. Calendar lacks a per-call physical hook; historical index checks at adapter/worker entry before resolver work. Adding these two seams and their owner guards is required work, not evidence inherited from the other six scopes.

## UPD-03 — Minimal interfaces and serialized selection

Add one pipeline entry, `async run_permission_maintenance_unit() -> PermissionMaintenanceResult`. It owns the existing `_permission_maintenance_lock` and dispatches at most one selected scope. Retain `PermissionMaintenanceResult` values `SKIPPED`, `DEFERRED`, `PROBED`, `FAILED`; no public status/API version changes are needed.

Refactor scope implementations into private lock-held bodies. A single private dispatcher accepts an optional `requested_operation` for compatibility wrappers: a direct `_maybe_recheck_*_permission` call acquires the same lock and may execute only if that scope wins global selection. Do not acquire the non-reentrant asyncio lock twice, call eight public locking methods in a loop, or let a named wrapper bypass fairness. Automatic production calls use only the common entry.

Inside the lock, read current due/controller state and the existing bounded candidate evidence. Set due-but-unavailable local checks under UPD-04, then select the due scope/rank by raw reservation plus round-robin tie order. Preserve DAILY_BARS preparation's existing synthetic own-scope rank, including when no broad DAILY_BARS anchor exists; global arbitration must not bind its eventual execution to a broad symbol/day hint before demand preparation. Perform the selected scope's existing fresh preparation exactly once. For DAILY_BARS, that one preparation checks its scope rank before bounded demand work, reads at most one historical page and validates at most 10 demand receipts, then forms the actual O/F candidate from `valid_symbols`. Only then freeze the actual candidate, its matching receipt and invocation capture. A broad hint for A with no demand may therefore legitimately yield B with a valid receipt. Other scopes retain their existing identity-validation rules.

A selection hint is not retained execution authority. Do not prepare once to pick the winner and again in the execution body, consume an external old preparation, re-page an already prepared DAILY_BARS receipt, or change the frozen actual candidate during execution/response validation. Preparation that becomes UNKNOWN/deferred ends this unit; it does not try another SDK scope in the same unit.

Immediately before reservation, recheck due/authority and precompute one immutable cursor replacement from the current state. Pass it only as `on_reserved` to the existing controller. The controller's successful durable reservation is the sole cursor acknowledgement, once only; do not acknowledge on selection, physical start, response or success. Keep the maintenance lock across owner preparation/reservation/result validation; never hold a SQLite transaction across provider await. Cancellation releases this lock while the controller retains and drains its physical slot. Each unit may create at most one new reservation and at most one physical call, including units that fail after reservation.

## UPD-04 — Pure getter, fixed local checks and progress

For each blocked operation use `effective_due = max(raw_due, local_defer, shared_429)` and select by raw due plus round-robin only among currently runnable candidates. Pacing and work-key backoff remain controller authority; a concrete controller retry floor returned by a unit is retained as its local not-before time. Shared cooldown must not overwrite raw ordering. Preserve the global scope cursor, DAILY_BARS O/F state and the two minute-symbol cursors.

`next_permission_probe_due_at` and composition's scheduling adapter read only bounded in-memory controller/local timing. Repeated calls perform no SQL, certification/configuration I/O, paging, reservation, probe, cursor update or `now + 30s` assignment. No candidate existence test belongs in this getter. It includes blocked scopes lacking current demand or anchor, so their local requirements can be reconsidered.

This zero-I/O contract applies to the timing getter and its scheduling adapter, not to B1's `permission_probe_candidates` or `select_due_permission_probe`. Those bounded candidate/selection peeks may read SQLite evidence and certification/configuration authority under their existing contracts; they make no reservation, SDK call or cursor write. Do not force them onto stale cached evidence or use them as scheduler timing getters. Their evidence reads also do not authorize a second DAILY_BARS demand preparation.

Only an actual due maintenance check records a fixed `checked_at + 30s` local recheck for a blocked scope with no consumer, anchor or temporarily usable scope authority. Cover all such due scopes, not merely B1's narrower missing-anchor list: otherwise an absent consumer can leave the getter permanently overdue. Repeated peeks and entries before that fixed time do not slide it. A known legal session opening uses the scope's existing earliest-start time; a concrete market blocker uses the existing blocker deadline plus one microsecond. Each examined unavailable scope or selected no-start result must get a justified future local deadline or be established as no longer blocked. Unselected runnable siblings may stay due for the next serialized unit. No zero-delay SKIPPED loop.

One bounded check may update local deadlines for several unavailable scopes but can reserve/probe only one. A candidate invalidated during selected preparation gets its own defer; another ready scope may win the next owner iteration. No scope cursor moves for these local checks. With a stable eligible equal-raw-due set, reservations visit every scope before repeating; general progress remains conditional on authority, market capacity and controller eligibility, not a fixed recovery SLA.

If no safe pipeline exists, the composition getter returns `None` and permission execution is skipped without creating one. DEGRADED still waits for its existing full-startup deadline; absence cannot become an immediate retry. Global revocation or NEEDS_RESTART follows the existing blocked/explicit-stop path, not indefinite local polling under a revoked baseline. Unknown persisted calendar anchors never authorize a blind calendar probe or weekday inference.

## UPD-05 — Calendar and historical-index final entry

Add optional invocation-local `_physical_start=None` only to `probe_trading_calendar_permission` and its private calendar route, and to `probe_historical_minutes_permission` through the existing index SDK-call helper. Construct all ordinary arguments first; use `resolve_permission_endpoint` to finish wrapper checks and inner callable resolution; then invoke the final owner hook immediately before the resolved SDK callable. Ordinary no-hook calendar/index acquisition keeps existing kwargs, parsing, cache behavior and error behavior. Never forward a private hook to Tushare, replace a shared callback or reuse a prepared endpoint across invocations.

Apply the existing SCB ordering: finish authority I/O before sampling one S, then check the original scope's same-date/no-rollback, `captured_at <= S <= captured_at + 15s`, original mode-specific validity, generation/stop, source/provider/factory identity, calendar epoch/Event, cancellation and frozen 31.25-second market window, then call directly. The worker does no SQL and reads no Task. Missing scheduler-window authority is a local defer, not unlimited permission to start. Preserve the identical `RequestNotStartedError` outside provider sanitizers; unknown worker faults remain controller `ERROR`, not fabricated permission denial.

Calendar and historical-index owners must revalidate the exact original persisted anchor, frozen source and calendar token before reservation and in one fresh owned explicit-BEGIN response snapshot using the captured session factory; a different valid date cannot replace it. Calendar may retain its completed closed-day anchor, whereas historical index still needs a completed SSE weekday-open anchor. Calendar rearming follows SMWO's epoch-plus-Event comparison and new Event installation; never clear an old token. Freeze the original owner Task and cancellation Event, and reject clearing on requested cancellation. Preserve each existing proof parser and scope-specific response-time rules; do not impose stock-minute row classification on index history or add a common certificate-expiry policy. No proof response writes calendar, market history or caches.

## UPD-06 — RUNNING integration and market priority

Reuse `DeadlineKind.INDEX_PERMISSION` as the existing internal permission-maintenance scheduling slot for all eight scopes. Its historical name does not restrict the registry; do not add a second permission kind/loop or change external status names. Composition `next_index_permission_at` becomes a thin adapter to the cheap eight-scope getter. Pipeline's corresponding deadline branch calls `run_permission_maintenance_unit`; it no longer compares two index deadlines. Remove the calendar recheck from `_request`: an ordinary blocked calendar request must remain blocked and let the common maintenance path repair permission on its own schedule.

The scheduler retains real market priority on equal due times and the existing 31.25-second reserve at preparation and final physical entry after queueing. Use `permission_market_window`'s actual known/possible market duties, not a constant fake next deadline. Do not treat this maintenance task itself as running market work. Queue priority, one worker, 1.25-second start pacing and the existing 15-second timeout remain controller-owned; none proves forced SDK interruption.

Use the shared lifecycle maintenance classification at both `_advance_progress_deadline` and the `market_review_after` branch. Permission work must neither advance `_last_deadline_at` nor replace the original elapsed-market review start. A07 F3's later `STOCK_RECOVERY` joins that same classification when implemented; this task does not implement it. Preserve unrelated `INDEX_RECOVERY` behavior. After scheduled maintenance, reuse the existing bounded review of at most one fresh elapsed REALTIME_MINUTE duty with its original target and age 0..90 seconds; do not replay multiple/stale duties or add startup catch-up. Permission work returns before normal reference/evaluation/delivery dispatch, including in index-only composition. Clearing a permission block is not READY or business execution authority.

## UPD-07 — DEGRADED dual clocks in the existing owner

Add an optional internal lifecycle `next_permission_maintenance_at` callback, defaulting to no deadline for existing standalone callers. Production wires the same cheap composition getter used by RUNNING. Execute a due permission maintenance deadline through the existing `_execute_deadline` owned-work path and common pipeline dispatcher; do not call ordinary market work while DEGRADED, set `_accepting_work=True`, or start a second background coordinator.

Maintain distinct internal `startup_due`/`startup_attempt` and permission timing. On entering a degraded retry episode, compute the next full-startup deadline once using the existing 30/60/120/300-second progression and the already published controller floor. Wait interruptibly until the earlier of that fixed deadline and permission due. Permission checks/results may update only permission timing and shared controller state; they do not reset attempts, recompute startup as `now + delay`, shorten its floor, or invoke `_recheck_degraded_startup`. A later shared 429 or relevant controller floor may extend startup's not-before time, never shorten it. Keep the existing public retry field's meaning as the full-startup retry, without adding status fields.

If both clocks are due, run exactly one allowed full-startup retry first. If it fails normally, increment the startup attempt once and fix the next startup deadline from that attempt's completion and controller floor; then reconsider permission due and allow at most one safe permission unit before waiting again. If startup succeeds, transition through the existing RUNNING path and its market priority. Thus fixed tie order cannot starve permission by repeatedly selecting an already-consumed startup deadline. If permission work overruns a startup deadline, run at most one overdue startup attempt after it completes; do not replay missed retries or overlap the calls.

Current `probe_capabilities` already reuses a still-authorized pipeline. Preserve that path: repeated failed startup attempts in the same generation must retain its lock, raw/controller state, local defers, global cursor, O/F state and minute-symbol cursors. A first valid local bootstrap may install a pipeline; maintenance must not repeatedly reconstruct one or reinstall source semantics. Loss of existing frozen authority requires the current NEEDS_RESTART behavior, not rebuilding to reset state. Process restart may reset in-memory cursors but retains durable admission floors under UPD-10.

Current `generation_current` combines database READY, `business_commit_admission_open` and generation equality; the latter admission property checks stop/cleanup/liveness, not `_accepting_work`. Preserve these bindings, including baseline revocation. They already permit read-only permission proofs during legal DEGRADED ownership; add no separate permissive capability and do not relax liveness, database, configuration or semantic gates. Permission success alone does not exit DEGRADED or trigger business evaluation; only the existing full-startup recheck can establish RUNNING.

## UPD-08 — Clock/action matrix

| Observation | Required next action | Forbidden effect |
|---|---|---|
| RUNNING market and permission due together | Market first; re-evaluate permission window afterwards | Consuming a market cursor with a permission result |
| DEGRADED permission due before fixed startup due | One safe permission unit; retain startup deadline and attempt | Immediate full-startup retry or opening business work |
| DEGRADED both due | One startup attempt first; on normal failure fix its next due, then reconsider one permission unit | Repeated startup selection without giving eligible permission work an opportunity |
| No candidate/consumer/anchor after a due check | Fixed 30-second local check or existing known session boundary | Sliding getter deadline, reservation or speculative network proof |
| Shared cooldown or later controller floor | Respect the later not-before time; retain raw fairness order | New target/scope wake bypassing 300 seconds or shared 429 |
| Queue/resolver crosses latest start or market reserve | Zero SDK starts; retain any reservation/ack and set concrete local defer | Re-capture inside the same queued attempt |
| Date rollover or clock before capture | Invalidate the capture; fresh bounded owner check later | Reusing old date/anchor or replaying timers |
| Pipeline absent; valid local owner still DEGRADED | Permission getter `None`; existing startup wait remains | Installing a new owner or a zero-delay maintenance loop |
| NEEDS_RESTART, stop, liveness/cleanup failure | Revoke/terminate through the existing lifecycle | Maintenance reviving source or business authority |

## UPD-09 — Closed results, errors and side effects

| Result/error | Maintenance boundary behavior | Accounting |
|---|---|---|
| No block/not due | `SKIPPED`; refresh cheap timing | No reservation/cursor/SDK change |
| Missing local requirement or `RequestNotStartedError` | `DEFERRED` with a fixed/concrete next check | Before reservation: none; after reservation: retain floor and once-only ack; no new provider failure from the sentinel |
| Valid proof and final owner validation | `PROBED`; controller clears only that operation; remove only its local defer | No business rows, health READY, evaluation, alert or delivery |
| Known permission/429/transient/timeout/invalid response | `FAILED`; retain block and applicable retry/cooldown timing | Preserve durable reservation and any controller timeout/late-failure accounting |
| `ERROR`, `CLOSED`, `QUEUE_FULL`, SQL/storage/checkpoint/callback or programming/protocol failure | Propagate to existing lifecycle/supervision; do not map to normal `FAILED` | No fabricated provider category or automatic permission retry loop |
| `CancelledError` | Mark invocation cancelled and re-raise; existing owner stop/drain applies | No late permission clear; retained reservation and physical slot |

Narrow older broad `RequestControlError` catches where necessary to meet this same matrix across all eight owners. Do not catch arbitrary exceptions at the unified dispatcher. Expected provider failures are consumed as scoped maintenance outcomes in either mode; they do not independently set RUNNING globally DEGRADED, reset its startup clock, or invoke supervisor replacement. A real unrelated market/startup error keeps its existing policy. Unknown worker errors can remain wrapped as controller `ERROR`; do not promise their original exception type.

## UPD-10 — Stop, durable reservation and cross-process limits

Use the existing work-task owner, owner Task cancellation check, invocation-local Event and controller shield/drain. Stop closes admission before cancellation; already-started physical work retains its slot until joined, and storage/owner disposal follows drain. No late response can clear a block after cancellation or revive a new invocation. Do not hold the maintenance lock solely to join a cancelled worker. A late sentinel does not erase a timeout already recorded. The existing live controller uses `LIVE_TUSHARE_IN_CYCLE_RETRIES=0`; this proposal adds no retry policy.

The durable 300-second reservation commits before acknowledgement and queue work. Queue veto, cancellation, timeout, invalid response and post-reservation guard refusal retain it. Worker-start floor extension does not repeat acknowledgement. Reopen the temporary database in a new process only after successful old-owner shutdown and prove the same operation cannot reserve before the stored floor, including shared 429 cooldown. Rotation and local checks remain process-local; a crash between reservation commit and acknowledgement can lose a cursor advance but cannot erase the committed reservation.

`ProviderRecoveryRepository` has a process-local owner registry and saves a bounded checkpoint snapshot; it is not an inter-process lease or compare-and-swap scheduler. The runtime-recovery plan assumes one legal owner per database and requires old-process exit before new start. Claim cross-restart floor preservation under that premise, not globally exactly-once probing by concurrently launched processes. Do not add an OS lock, reservation schema, migration or cross-process mutual-exclusion promise in this slice. The controller's worker-start floor is not an atomic database transaction with final inner SDK entry.

## UPD-11 — Ordered implementation slices and ownership

These are proposed follow-up assignments, not authorization to edit now. Source handoffs are serial: the current stock-minute writer owns `runtime/production.py`; A07 F1 owns `runtime/service.py` and `runtime/explicit_service.py`. Wait for their release and recheck interface drift. Only a designated provider writer changes the two provider files; no concurrent SDK-boundary edits.

| Slice | Files and dependency | Acceptance checkpoint |
|---|---|---|
| UPD-S1 | `market_data/tushare.py`, `market_index/tushare.py`, focused provider boundary tests; after provider handoff | Calendar/history final-hook RED→GREEN, ordinary no-hook compatibility; no owner/scheduler enablement |
| UPD-S2 | `runtime/production.py`, calendar and two index-owner tests; after S1 and production handoff | Shared locked bodies, original anchor/cancel guards, global selection/ack and closed error matrix; direct internal calls only |
| UPD-S3 | `runtime/production.py`, candidate selection/rotation and new unified-dispatch integration tests; after S2 and SMWO execution acceptance | One common eight-scope unit, pure getter, all no-candidate fixed checks, preserved O/F/symbol fairness; no calendar inline bypass remains |
| UPD-S4 | `runtime/scheduler.py`, `runtime/service.py`, `web/monitor_composition.py`, focused runtime/scheduler tests; after S3 and F1 handoff | RUNNING real composition, market priority, common maintenance classification at both cursor sites; A07 F3 not implemented |
| UPD-S5 | `runtime/service.py`, `web/monitor_composition.py`, focused dual-clock and lifecycle tests; after S4 | DEGRADED dual clocks, pipeline/state retention, same-generation restoration and stop/drain; no business permission shortcut |

Run targeted RED→GREEN and adjacent regressions after each slice; independently review the changed authority/clock boundaries at S2/S3 and connected RUNNING/DEGRADED acceptance after S5. Do not rerun unchanged proof matrices as a substitute for new scheduler tests. If a slice expands beyond a bounded reviewable change, split its tests/implementation serially without enabling a partially connected default path. C1 is not closed by any standalone helper or by this contract's approval.

## UPD-12 — Precise RED acceptance gates

| ID | Required offline failing case and eventual acceptance |
|---|---|
| UPD-R01 | All eight scopes blocked at equal raw due; real common dispatcher reserves/probes one per unit, reaches every eligible scope, and clears only the selected block. Different raw dates and shared 429 must preserve raw ordering. |
| UPD-R02 | Repeated `next_permission_probe_due_at` and scheduling-adapter calls before and after due perform zero SQL/file I/O/reservation/SDK/cursor writes. Separately prove `permission_probe_candidates` and `select_due_permission_probe` retain bounded fresh evidence/authority reads with zero reservation/SDK/cursor writes; do not impose the timing getter's zero-I/O rule on them. Missing consumer, missing anchor and temporarily absent scope authority each establish fixed 30-second checks through actual maintenance, without sliding or hot looping. |
| UPD-R03 | First-minute/session earliest starts, closed/unknown day and midnight re-preparation retain existing scope rules. No consumer/anchor means zero reservation even while another scope progresses. |
| UPD-R04 | Real controller save failure advances no cursor; commit-before-queue veto advances once; coalesced waiter and worker-start extension do not acknowledge twice. O/F and both symbol cursors survive other scope reservations. |
| UPD-R05 | Concurrent named/common entries serialize without deadlock or stale precomputed callback overwrite; a named nonwinning scope cannot bypass arbitration. Each unit has at most one reservation and one physical call. DAILY_BARS broad hint A has no demand while B has a valid receipt: global arbitration selects the scope/rank, exactly one fresh preparation selects and freezes B, and execution uses that same candidate/receipt. Assert one preparation, at most one historical page and at most 10 receipt point-checks, with no prepare-to-select then prepare-to-execute duplication or post-capture replacement. |
| UPD-R06 | Real calendar and historical-index providers plus certification wrapper: wrapper/resolver I/O consumes time or revokes authority after adapter entry; final hook rejects with zero inner SDK calls. Test legal entry, equality/late start, identical sentinel, no private kwargs, no worker SQL, ordinary no-hook behavior. |
| UPD-R07 | Calendar closed-day proof remains legal; original calendar/historical anchor changes while another valid date remains: no substitution/clear. Interleaved epoch correction, failed calendar write and new Event installation cannot revive old invocation authority. |
| UPD-R08 | A normal calendar request with a due permission block never calls a recheck inline; only a later globally selected maintenance unit probes. Startup failure does not secretly probe outside its clock. |
| UPD-R09 | Real RUNNING composition selects market first on ties; preparation-safe permission queued into the 31.25-second reserve is rejected at actual SDK entry, preserving reservation. Permission work cannot treat its own running flag as market work. |
| UPD-R10 | Maintenance completion crosses a market deadline: both original cursor and elapsed-review start survive; exactly one original fresh target may run at actual age 0..90 seconds, no stale/multiple replay. No delivery or evaluation follows the permission branch itself. |
| UPD-R11 | DEGRADED startup attempts follow 30/60/120/300 seconds from successive attempt completions, extended by later controller floors. Multiple permission wakes/successes/failures before each deadline neither reset attempt nor move it earlier or slide it later. |
| UPD-R12 | Both degraded clocks due: one startup first, then on normal failure one eligible permission unit before another wait; no starvation. Overrunning permission creates at most one overdue startup attempt, with no parallel physical call or replay. |
| UPD-R13 | Same-generation failed startup rechecks reuse the valid pipeline and preserve fixed defers/global/O-F/symbol cursors. Absent pipeline waits on startup only; first legal creation does not revive an abandoned capture. Revoked baseline stays NEEDS_RESTART. |
| UPD-R14 | Real DEGRADED bindings permit a legitimate read-only proof without changing `_accepting_work`, business rows or runtime generation. Proof success alone stays DEGRADED; later due full-startup success resumes existing scheduling, without supervisor replacement. |
| UPD-R15 | Every UPD-09 error category through each owner family: expected failure remains scoped; fatal controller/storage/callback/programming errors reach the owner. No broad catch disguises `ERROR`, `CLOSED` or `QUEUE_FULL`. |
| UPD-R16 | Cancel before queue/entry, request cancellation before outer catch, cancel during SDK then return late success: no clear; no second physical call/DB disposal before drain. Stop/cleanup/liveness/configuration revocation terminates maintenance in both modes. |
| UPD-R17 | Separate sequential processes reopening temporary SQLite preserve permission and 429 floors; before-floor zero reservations, equality permits only an otherwise valid attempt; cursor reset does not change stored timing. Do not simulate simultaneous processes as supported. |
| UPD-R18 | Positive progress for calendar, both index endpoints, all three daily scopes and both stock-minute scopes through actual RUNNING/DEGRADED wakes, not direct private calls; assert physical counts, own-scope clearing, same generation and zero permission-path business writes. |

Retain adjacent tests in `test_permission_candidate_selection.py`, `test_permission_candidate_rotation.py`, `test_permission_reservation_ack.py`, the existing scope-owner/proof suites, `test_runtime_lifecycle.py`, `test_production_a06_process_scheduler.py` and targeted A07 cursor/freshness/stop regressions. Use fixture-approved real local ownership, not bypassed liveness or fabricated health. Commands/results belong to later paired verification evidence, separating author and independent runs; none were run for this proposal.

## UPD-13 — Review questions and completion boundary

No new user business choice is identified: all thresholds, trading rules, proof semantics and restart policy are inherited. Independent Sol review must check the lock-held dispatch/refactor boundary, non-sliding absent-candidate timing, startup-first tie fairness, unchanged DEGRADED admission bindings, both real SDK seams and the two maintenance cursor sites. Working-tree changes may require a fresh interface check before implementation, not weaker acceptance criteria.

Approval of this proposal is design approval only. Implementation acceptance requires all eight integrated paths, dual-clock progress and failure/stop/restart gates above. Full runtime recovery, A07, real-provider acceptance, live migration and deployment remain separately tracked; no new background owner or universal recovery-time guarantee is introduced.
