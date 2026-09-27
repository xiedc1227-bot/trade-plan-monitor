# C1 stock-minute permission owner contract

> Canonical agent-facing English version. The matching Chinese review copy is `2026-09-27-c1-stock-minute-permission-owner-contract.zh-CN.md`.

## SMWO-01 Status and scope

- Date: 2026-09-27.
- Status: **Preparation design approved; execution design conditionally approved after independent preparation acceptance; owner execution not implemented**.
- Independent Sol review approved pure preparation (candidates, identity/calendar preparation, ordering/cursor structures, zero reservations and zero SDK calls). Preparation implementation is in progress and not yet independently accepted. The SDK-boundary prerequisite is resolved by independently verified commit `4804207`. Subsequent independent Sol execution-design review found no new P1/P2 and permits bounded execution implementation after preparation acceptance. This does not certify owner execution or close C1.
- Baseline: the pure provider proof contract and implementation committed as `95feccb`, documented in [the provider contract](2026-09-27-c1-stock-minute-permission-proof-contract.md). That completed slice is distinct from this not-yet-accepted owner integration.
- Proposed scope: candidate selection, preparation, and internal owner entry points for `CURRENT_DAY_MINUTES` and `REALTIME_MINUTES`. Preparation and physical execution are separate thin slices.
- Automatic scheduler integration, the RUNNING/DEGRADED dual-clock dispatcher, status API changes, startup backoff changes, market-deadline cursor changes, and complete C1 acceptance are outside this slice.
- The DAILY_BARS wiring consulted during design remains a reference for principles, not a substitute for owner validation. This documentation change modifies no production/provider/controller code, other documentation, or database schema. Only these two contract files are authorized for a local documentation commit.
- Future implementation evidence is limited to temporary SQLite, fake SDK/transport, and controlled clocks. No real-service requests, user-database access, sends, push, or deployment are included.

## SMWO-02 Actual consumers and original identity

`RuntimeDeadlineCoordinator.run_deadline()` acquires stock minutes for both legacy plans and `ExplicitTradePlan`; explicit rules consume the resulting complete five-minute data. Startup recovery also uses today's eligible active symbols. Both plan families can therefore justify `CURRENT_DAY_MINUTES` and `REALTIME_MINUTES`; the DAILY_BARS legacy-only set cannot be reused.

A consumer must be a complete executable plan, currently persisted as active, eligible under `activation_is_eligible_on(..., today)`, and supported by its composed runtime service. Future, expired, deactivated, or draft plans and plans with only historical pending work do not establish today's minute demand. Missing inventory, risk inputs, or other business dependencies do not automatically remove minute-consumer eligibility; business READY is not a prerequisite for permission repair. Existing persisted minute gaps or today's minute rows are not prerequisites either, because that would strand a blocked startup.

One owned preparation snapshot checks `ActivePlan`, `PlanActivationState`, and `PlanVersion`. Retain the existing maximum of ten ACTIVE plans and bounded payload reads. Require all of the following:

- `ActivePlan.plan_version_id == PlanActivationState.plan_version_id == PlanVersion.id`: both current pointers identify the same version row.
- `ActivePlan.symbol == PlanActivationState.symbol == PlanVersion.symbol == decoded_plan.symbol`: all three stored symbols exactly match the decoded plan.
- `ActivePlan.revision == PlanActivationState.revision > 0`.
- `ActivePlan.activated_at == PlanActivationState.changed_at`: the equal timestamps are canonical Shanghai times and no later than the capture time.
- `PlanVersion.status == ACTIVE`; its `plan_id`, `version`, `plan_hash`, and `payload_json` agree with the complete decoded canonical plan, including its recomputed canonical hash.

Freeze at least:

```text
symbol
plan_version_id
plan_hash
family
activation_revision
activated_at
request_date
```

`plan_hash` already binds execution version, formula version, and activation policy. Response validation repeats the checks and can match only this original identity. A replacement version, deactivation/reactivation, or activation ABA cannot borrow another valid plan for the same symbol to clear the block. These checks suffice for permission-only current identity; they do not prove the validity of the complete historical activation audit. Do not add a historical activation-audit or legacy historical-close scan.

## SMWO-03 Internal signatures and two slices

Proposed internal entry points share one implementation:

```python
async def _maybe_recheck_current_day_minutes_permission(
    self,
) -> PermissionMaintenanceResult: ...

async def _maybe_recheck_realtime_minutes_permission(
    self,
) -> PermissionMaintenanceResult: ...

def _prepare_stock_minute_permission_locked(
    self, operation: TushareOperation,
) -> _StockMinutePermissionPreparation: ...
```

Preparation returns an immutable `PREPARED / UNKNOWN / SKIPPED` result carrying the original candidate, consumer identity, capture time, STOCK semantic mode/revision, label, provider, session factory, and calendar epoch/event.

1. **Candidate/preparation slice:** candidates, identity/calendar preparation, eight-scope ordering and cursor structures including two independent symbol cursors; no reservation or SDK call and no provider changes. The design is approved and implementation is in progress after the SDK-boundary writer released `production.py`; independent implementation acceptance remains required.
2. **Execution slice:** after independent preparation acceptance, connect the provider proof and controller under the conditionally approved execution design. The separate wrapper/provider adaptation has passed verification at `4804207`. Run `SMW-04` and `SMW-06` through `SMW-14` RED-to-GREEN and clear only the corresponding permission block after final validation. Owner execution implementation and acceptance remain outstanding.

The preparation slice changes no provider files. The minimal wrapper/provider adaptation is separately completed work under SMWO-11, not permission to broaden either owner slice. Neither slice changes the controller, automatic scheduling, startup backoff, status API, or market-deadline cursor.

## SMWO-04 Request windows and calendar

Retain the previously proposed conservative maintenance windows. A request may start only during these Shanghai-time intervals:

```text
[09:31:12, 11:30:00)
[13:00:00, 15:00:00)
```

`09:31:12` is the first one-minute end plus the existing 12-second grace. At `13:00:00`, completed morning minutes already exist in the day's session structure; do not add an unapproved `13:01:12` threshold. The actual response must still contain an A proof row.

The request date requires one exact persisted SSE weekday-open fact, using the existing realtime master calendar and SSE epoch scope. Weekday arithmetic alone cannot establish openness. Do not describe this as independent certification of another exchange.

- Missing calendar, a closed day, no demand, or unavailable authority means no reservation and no SDK call. An actual maintenance check records a fixed 30-second local recheck.
- When the first-minute threshold or afternoon opening is known, record that earliest check time. Getters never slide the recorded deadline.
- At midnight, rebuild today's identity and anchor.
- Do not start a minute probe at lunch or at/after `15:00:00`. A response to a legally started request is not rejected solely because it crosses one of those session boundaries.
- Response validation does not require another future 31.25-second capacity window.

A revoked calendar token left by a failed write can be replaced only after a fresh owner persisted read, comparing both the epoch and Event identity captured for that read with their current values. Install a new Event only; never call `clear()` on the old Event. An old invocation retains its original token and cannot obtain the new token to continue.

## SMWO-05 Eight-scope and symbol fairness

Append `CURRENT_DAY_MINUTES` and `REALTIME_MINUTES` after the existing six scopes, retaining their relative order:

```text
TRADING_CALENDAR
INDEX_HISTORICAL_MINUTES
INDEX_REALTIME_MINUTES
DAILY_LIMITS
DAILY_BARS
INDEX_DAILY
CURRENT_DAY_MINUTES
REALTIME_MINUTES
```

Update both the candidate selector's scope collection and the cheap next-due getter's scope collection to these same eight scopes. Preserve the original six-scope order and DAILY_BARS O/F state; extending only one collection is insufficient.

```text
effective_due = max(raw_due, local_defer, shared_429)
selection = raw_due + round-robin tie among currently runnable candidates
```

Each minute scope owns an independent symbol cursor. Select the strict successor in ascending eligible-symbol order and wrap after the end. A disappearing candidate or temporarily empty set retains the cursor; newly added or newly eligible symbols can enter again.

Only `on_reserved`, after successful durable 300-second reservation, advances the global scope position and that scope's symbol cursor, once each. Save failure, peeking, no candidate, and a coalesced waiter do not advance either. Cancellation, queue veto, no positive proof, or timeout after reservation retains that advancement. Extending the reservation floor at physical start and successful clearing do not invoke the callback again.

Hold the shared maintenance lock, precompute one immutable state replacement, and preserve DAILY_BARS O/F state. For a stable eligible set, every symbol gets an opportunity within the corresponding number of reservations for that scope. This is conditional fairness, not a five-minute recovery SLA. Cursors remain process-local.

This slice may test the eight-scope selection contract. It does not prove that existing automatic entry points already share a fair dispatcher. Unified dispatch, RUNNING/DEGRADED dual clocks, and no-candidate wake behavior remain later work.

## SMWO-06 Admission, source authority, and cancellation

Before the entry point's first await, capture `owner_task = asyncio.current_task()` and create a per-invocation `threading.Event`. Reprepare exactly once while holding the shared maintenance lock; do not use an externally retained preparation.

```text
latest_start = captured_at + 15s
market_guard = 31.25s
```

Check at four points: before reservation, queue admission, worker entry, and immediately before the SDK call. Each gate checks the same date, no clock rollback, frozen latest start, legal request window, frozen market window, configuration, semantics, provider/source identity, generation, stop, calendar epoch/event, and cancellation Event. Workers access neither Task objects nor the database.

The wrapper seam is implemented under SMWO-11; the owner callback must still prove every owner-specific condition. Finish the last configuration/certification/semantic I/O before sampling one S. After S, check the original mode's time rules and the in-memory generation/admission/stop, provider/factory identity, epoch/Event, cancellation and frozen-window fences, then directly invoke the resolved SDK callable. No further authority I/O or resampling of S is permitted. The resolver alone does not prove a new owner callback correct.

Use the existing controller with at most one SDK call for the exact endpoint, one symbol, and `freq="1MIN"`. The endpoints retain independent permission blocks/reservations and share 429 cooldown, one physical worker, and 1.25-second pacing. Use `RequestPriority.RECOVERY`; market work remains higher priority. Preserve the original `RequestNotStartedError` sentinel. Pre-reservation revocation creates no reservation; post-reservation revocation retains the durable reservation.

STOCK semantic mode uses existing compatibility checks without imposing the old certification expiry threshold. Legacy certification mode retains its existing validity rules. A missing STOCK binding does not fall back to historical-minute certification.

On `CancelledError`, set the invocation Event before re-raising; set it permanently in `finally` as well. Before the response read and before returning true, the owner validator checks the captured `owner_task.cancelling() == 0`, not the controller's shared task. Requested cancellation must prevent clearing even before the outer catch runs.

There is no guarantee of zero SDK starts before the Event is set. The controller retains the slot and drains already-started physical work; the maintenance lock is not retained just to wait for that drain.

## SMWO-07 Frozen proof and one fresh response snapshot

The existing controller's `validate_after` receives no result argument. Use a per-invocation result slot for immutable `MinutePermissionEvidence` and a per-invocation record of the actual callback's S, never shared pipeline state. The owner must compare `evidence.started_at` with that exact recorded S, not merely test whether it is within a permitted range. An empty slot, wrong result type, or mismatched identity cannot succeed. A late worker may write only its own abandoned invocation's slot; it cannot populate a later invocation's slot or revive clearing authority.

Check the original operation, symbol, request date, certified label, and the exact S returned by this invocation's `physical_start`:

```text
captured_at <= S <= latest_start
0 <= R - S <= 15s
response_validation_time >= R
```

Preserve the provider's A/B/C classification at frozen S/R; advancing the validation clock cannot reclassify rows. Require at least one A and retain the provider contract's date-set and count types/bounds.

Using the captured factory, open exactly one fresh owned explicit-BEGIN read snapshot after the response:

1. Revalidate the original consumer identity and today's eligibility without selecting another symbol.
2. Check the exact persisted SSE open row for the request date.
3. Check the exact persisted SSE open row for every A/B/C `source_dates` entry, including dates represented only by B.
4. Recheck authority, epoch/event, cancellation, and time fences around the snapshot.

`rt_min` has at most 1,000 source dates. Its request date need not occur in that set, so **1,001 distinct date facts** is the upper bound of the union of source dates and request date, not an additional source-date allowance. Use bounded exact-set queries, optionally chunked inside the same explicit transaction. Do not reuse a helper that opens another session or a 366-day range helper. Do not expand a min/max range, impose a five-day or 366-day limit, or append a `trade_cal` network request.

Do not call a calendar helper that opens another UnitOfWork. A missing factory may defer. A supplied borrowed, pre-used, or incorrectly bound Session is a configuration error under `require_owned_recovery_session`; expose it without closing or rolling back caller-owned state. SQL, save, and local programming errors propagate.

The factory must use the application-configured engine with explicit-BEGIN transaction hooks. `require_owned_recovery_session` checks ownership and binding; it does not itself prove that an arbitrary custom engine provides explicit-BEGIN semantics.

Configuration/semantic revocation uses the existing monotone revoked state: restoring an observed changed value does not revive an old request. Supported calendar writes use epoch revocation for same-value rewrites and ABA. This does not claim detection of unobserved external transient changes that bypass those paths.

Snapshot validation and the controller's subsequent permission reset are not one atomic database transaction. The proof establishes endpoint readability only and grants no business execution authority.

## SMWO-08 Outcomes and side effects

- A valid proof clears only its own scope; success removes only its own local defer.
- `NO_POSITIVE_PROOF` retains the existing `INVALID_RESPONSE` failure path, block, and reservation. Do not return an empty normal success or fabricate a new HTTP 403.
- Known permission, 429, transient, timeout, and invalid-response errors return `FAILED`.
- `RequestNotStartedError` maps to `DEFERRED`: use the existing market-blocker yield deadline where applicable, otherwise a fixed local recheck.
- `ERROR/CLOSED/QUEUE_FULL`, SQL, checkpoint, callback errors, and cancellation propagate. Do not swallow them as ordinary failure or close the controller here.
- The 15 seconds are the evidence interval and existing controller boundary, not proof of forced SDK interruption. Late success cannot clear the block again.
- Apart from controller recovery checkpoints, write no minutes, daily bars, caches, health/READY, evaluations, risk, notifications, or pending state.

## SMWO-09 Required RED matrix

| ID | Required boundary |
| --- | --- |
| SMW-01 | Today's legacy, explicit, and mixed plans can be actual consumers; future, expired, deactivated, draft, and historical-pending-only cases create no demand. |
| SMW-02 | Exact three-table pointer/symbol/revision/timestamp and complete canonical-plan agreement from SMWO-02; replacement, same-hash reactivation, and ABA reject the original response; no historical audit scan. |
| SMW-03 | Exact `09:31:12`, one microsecond earlier, `11:30`, `13:00`, `15:00`; closed, unknown, spurious weekend-open facts; fresh cross-date preparation. |
| SMW-04 | One exact call per endpoint and only its own block cleared; ordinary minute reads and other permission states remain unaffected. |
| SMW-05 | Matching eight-scope selector/getter sets, original six-scope order, raw-due/tie order, two independent symbol successors, deletion/addition/empty sets; repeated peeks never advance. |
| SMW-06 | Save failure advances nothing; post-reservation veto/failure advances once; physical-start floor extension does not repeat callback; O/F state is preserved. |
| SMW-07 | Four admission gates, fixed latest start and non-sliding window; 31.25-second equality and revocation after queue waiting. |
| SMW-08 | Certified source/mode/revision, provider, factory, configuration/generation/stop changes; calendar re-arm compares epoch and Event identity, installs a new Event without clearing the old one, and cannot revive an old invocation; no historical-certification fallback. |
| SMW-09 | Real provider with fake SDK: A+B/C success; B/C-only, typed empty, malformed rows, and original sentinel propagation. |
| SMW-10 | Exact validation of every A/B/C date, rejecting an unknown B-only date; at most 1,001 dates in the union of 1,000 sparse source dates and request date; chunks stay in one explicit transaction without a separate-session or 366-day helper. |
| SMW-11 | Exactly one fresh explicit-BEGIN response snapshot using the application-configured engine; ownership preflight alone does not certify arbitrary custom engines; concurrent identity/calendar changes; worker accesses neither SQL nor Task. |
| SMW-12 | Exact equality with per-invocation callback S, not only range checks; a legally started request can validate across lunch/close; no response-time future-capacity recheck; rollback after R rejects. |
| SMW-13 | Queued cancellation, in-SDK cancellation, requested cancellation before outer catch; late workers write only their own abandoned slots; no clearing on late success and no second physical start before slot drain. |
| SMW-14 | Shared 429, durable 300 seconds, 1.25-second pacing, restored state after reopening temporary SQLite; save/callback/SQL faults propagate. |
| SMW-15 | Getters do not slide fixed local rechecks; no demand/calendar means no reservation; no business SQL writes, READY, sends, or automatic scheduling calls. |

## SMWO-10 Remaining gates and documentation state

The internal proposal requires no new business parameter. Expanding lunch/after-close request windows, demonstrating that real `rt_min` supplies an A proof row, and complete automatic-recovery acceptance remain outside this slice. Fake mixed-row evidence cannot close C1.

Preparation implementation is in progress and not yet independently accepted. Independent execution-design review conditionally permits owner execution implementation after preparation acceptance; it remains unimplemented. Its own `SMW-04` and `SMW-06` through `SMW-14` RED-to-GREEN matrix is still required. The SDK slice's 146 independent passing tests cannot substitute for owner acceptance. Documentation parity/format checks are not implementation tests. Unified scheduling and C1 remain OPEN.

## SMWO-11 Resolved SDK prerequisite: production wrapper physical-start boundary

Independent review reproduced the following old boundary offline. The pure provider invoked `physical_start` before `endpoint(...)`, but the production endpoint was `_CertifiedTushareClient.request`. The wrapper then ran `_current()` certificate/configuration-file checks before invoking the inner SDK:

```text
provider physical_start -> S
endpoint(...) -> _CertifiedTushareClient.request
_current() certificate/configuration checks
inner SDK invocation
SDK return -> R
```

In that old sequence, wrapper checks could cross `captured_at + 15s` or observe revocation while S retained the earlier time. Both `S <= latest_start` and `R - S <= 15s` could hold despite a late SDK start.

The original reviewer inline reproduction captured at `10:00:00`, set latest start to `10:00:15`, and recorded S at `10:00:14`; two seconds of certification work delayed the inner fake SDK to `10:00:16`, while the old proof passed. That inline reproduction was not owner-test evidence. The separate SDK slice subsequently added a regression and repaired this boundary.

Commit `4804207` implements a nominal per-call resolver: wrapper checks and endpoint resolution precede the final callback. See `SCB-05`/`SCB-06` in [the boundary contract](2026-09-27-c1-sdk-call-boundary-contract.md) and `SCBV-07` in [the verification report](2026-09-27-c1-sdk-call-boundary-verification.md). A further final-certification-I/O revocation finding was reproduced and fixed. Independent post-fix verification passed 122 boundary cases plus 24 realtime-index cases. These 146 cases are SDK-slice evidence, not minute-owner execution evidence. Shared callback replacement and private hook forwarding remain forbidden.

The SDK slice covers its specified daily/index permission seams; `INDEX_HISTORICAL_MINUTES` and ordinary business-path guarantees were not expanded. S marks the point after local checks and immediately before invoking the resolved inner SDK callable, not network send time or zero thread-scheduling delay. This prerequisite is resolved within that scope. The owner must still implement and verify SMWO-06–09; preparation acceptance, execution acceptance, automatic dispatch and complete C1 remain separate gates.
