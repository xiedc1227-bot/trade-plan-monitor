# Spec: runtime-status

> RR002 contract draft for review, derived from approved proposal D7 and constrained by D1–D6. Implementation authorization on 2026-09-21 does not mean this detailed protocol has passed C0/C4, is implemented, or is the production default. Canonical English; review copy: `SPEC-runtime-status.zh-CN.md`.
> Depends on [provider-contract](SPEC-provider-contract.md) and [runtime-recovery](SPEC-runtime-recovery.md). Task and acceptance IDs refer to `tasks/runtime-recovery-todo.md` and `tasks/runtime-recovery-plan.md`.

## RS01 Objective and invariants

Expose authoritative recovery status even when no plan has a current decision. Isolate unavailable plans and dependencies, support both `TradePlan` and `ExplicitTradePlan`, and distinguish a working transport from coordinator progress and actionable data. This contract changes presentation and protocol compatibility, never evaluator rules, immutable result bytes/hashes, activation identities, alert delivery eligibility, or provider admission.

Version 2 replaces the old global `status`/`readOnly` relationship and exact heartbeat shape. It is not an optional-field extension. `monitorContractVersion=2` versions the monitor presentation protocol; `/api/v1`, `/ws/v1/monitor`, persisted event `schemaVersion=1`, plan schema versions, and execution versions keep their separate meanings. Only one monitor version is served by a v2 application. Existing production behavior stays unchanged until RR020 and its prerequisites pass.

## RS02 Version negotiation and route inventory

The following existing REST routes require exactly one `X-Monitor-Contract-Version` header whose parsed field value is the canonical ASCII string `2`. Missing, duplicate, comma-joined, unsupported or non-canonical values, including `02`, fail before reading a monitoring projection or invoking a command service. Ordinary HTTP framing whitespace is handled by the HTTP parser; the application accepts no additional version-list grammar.

| Scope | Existing paths under `/api/v1` |
|---|---|
| Changed monitoring reads | `GET /health`, `GET /health/symbols/{symbol}`, `GET /dashboard`, `GET /symbols`, `GET /symbols/{symbol}`, `GET /explicit-plan-runtime/{symbol}` |
| Active-plan changes | `POST /plan-activations`, `POST /plan-deactivations` |
| Monitoring inventory changes | `POST /position-lots`, `POST /position-lot-closures`, `POST /position-inventory-closures`, `POST /position-inventory-confirmations` |
| Monitoring confirmations and diagnostics | `POST /manual-event-risk-confirmations`, `POST /alert-acknowledgements`, `POST /diagnostic-evaluations` |

Plan replacement uses activation of a successor immutable version; there is no existing delete/replace endpoint to invent. Draft save/import, extraction/review, AI configuration, independent backtests, historical bars/events and other unchanged read routes retain their existing contracts. A future route that changes active monitoring state must be reviewed for this guard. Version agreement does not replace Origin checks, idempotency, optimistic revisions or business validation, and it does not authorize a trade.

Every response on these guarded routes includes `X-Monitor-Contract-Version: 2` and `Cache-Control: no-store`, including errors. Responses that contain the new monitoring projection also include integer `monitorContractVersion: 2`. The header supplements, rather than changes, unchanged command response bodies. An incompatible request returns HTTP `409`, the existing `CONFLICT` error envelope, and exactly one detail with code `MONITOR_CONTRACT_MISMATCH`, location `["header", "X-Monitor-Contract-Version"]`, and fixed message `Reload the application to use monitor contract 2`. It returns no projection or command result and causes no command side effect. Never echo the rejected value. The ordinary server-owned `requestId` and `X-Request-ID` remain required.

The new client checks the response header before accepting a guarded response, then validates the body version where defined. Missing/wrong headers from an old server, body/header disagreement, or the mismatch detail enters a terminal local `RELOAD_REQUIRED` state: invalidate current actionable presentation, cancel monitoring reads/stream/reconnects, disable guarded command submissions, and show an accessible reload instruction. A reload obtains the installed hashed assets and renegotiates; do not retry the same incompatible assets indefinitely. Unaffected research/draft contracts gain no new business restriction.

Before each guarded POST, the shared command adapter must complete a read-only preflight against `GET /api/v1/health` or an authoritative dashboard refresh and validate its v2 header and body. This applies to direct command-page entry, initial submission and an uncertain retry; no route may assume that mounting the monitor shell already negotiated. Failure, missing/wrong version or an unvalidated response prevents the POST from being sent. Inspecting a command response's version is too late because an old backend could already have applied it. Bind the preflight to the same origin and current client request lifecycle; navigation, reconnect, generation replacement or a mismatch invalidates a pending preflight. Preserve the original idempotency key for an uncertain identical command. This protocol preflight does not derive command authorization from recovery mode or `readOnly`; the command service still owns that decision. Coordinated rollout must prevent a backend downgrade between preflight and command; an old server that ignores this version header cannot enforce a new atomic negotiation protocol.

An unmodified cached v1 client cannot be made to render new copy. Its guarded requests receive an old-envelope-compatible `409`, and its socket is rejected before data; its existing fail-closed parsing/liveness timeout must remove live presentation. Even if its old screen temporarily retains a stale button, the server guard rejects its submission. This is the guaranteed old-client safety property; a new reload message in every historical binary is not claimed.

`GET /health` with the accepted header remains readable during missing projections, provider errors, blocked scopes and standby. Protocol mismatch does not enter the normal provider retry policy. Real storage/composition faults may still return the existing sanitized `SERVICE_UNAVAILABLE`; do not fabricate a healthy status when the authoritative source cannot be read.

## RS03 Common status and lifecycle

`RuntimeStatusView` is a closed object with these required keys, including explicit nulls. The surrounding response owns `monitorContractVersion`, `runtimeGeneration`, `observedAt` and, for dashboard snapshots, the committed `sequence`.

| Field | Type and meaning |
|---|---|
| `lifecycle` | `STARTING`, `RUNNING`, `STOPPING` or `STOPPED`; resource ownership only. A provider failure does not stop the owner. |
| `mode` | `RECOVERING`, `MONITORING`, `STANDBY`, `DEGRADED` or `BLOCKED`; aggregate description, never permission to evaluate/send. |
| `reasonCode` | A fixed code from RS05, or null only for `MONITORING`. |
| `nextWakeAt` | Nullable canonical Shanghai timestamp for the next coordinator reconsideration, including maintenance. |
| `nextRetryAt` | Nullable earliest currently scheduled scoped retry; this is an eligibility time, not a promise of a provider start/completion. |
| `lastProgressAt` | Nullable time of the last completed bounded reconciliation step; never set by a REST read or socket frame. |
| `coordinator` | Exact `{state, progressDueAt}`; state is `STARTING`, `SCHEDULED`, `WORKING`, `STALLED` or `STOPPED`, deadline is nullable Shanghai time. |
| `scopes` | At most 32 unique `scopeKey` entries sorted by that key, using RS04. Never truncate away an active plan. |

`runtimeGeneration` is a UUIDv4 allocated when the runtime owner is created, including `STARTING`, recovery and standby. It remains the same through scoped failures, retries and normal mode transitions. It changes only on owner/configuration replacement under D5. It is null only when no runtime owner exists. A stopped owner can retain its generation for diagnosis; it confers no liveness. Missing decisions do not erase an existing generation.

All datetimes use the existing canonical `Asia/Shanghai` contract: `+08:00`, 0–6 fractional digits accepted, six digits emitted. Data cutoffs, completed target timestamps and `lastProgressAt` cannot be later than `observedAt`. Durations/deadlines are enforced against injected monotonic time; wall-clock timestamps explain the current schedule and are recomputed after sleep/wake or clock change. Comparing wall times alone cannot restore liveness after clock reversal.

`SCHEDULED` requires a known `nextWakeAt` and `progressDueAt`; `WORKING` requires `progressDueAt` for its currently owned bounded operation. Deadline calculation comes from the approved runtime owner: at most 30 seconds between local reconsiderations, physical timeout 15 seconds, existing admission/cooldown and owned-worker completion rules. This specification adds no timeout grace, universal recovery SLA or permission to release a still-running worker. Expected backoff, cooldown or permission wait remains live through actual local reconsideration. A legitimately idle standby pass is progress when the coordinator actually checks facts and installs its next wake.

`STALLED` means the installed monotonic progress deadline was exceeded; it requires `mode=BLOCKED`, `reasonCode=COORDINATOR_STALLED`, all plan `readOnly=true`, and no current intraday actionable presentation. Old wake/deadline timestamps may remain overdue for diagnosis. Only a real completed coordinator step or supervised replacement can restore progress. `STOPPED` requires `progressDueAt=null`, `nextWakeAt=null`, `nextRetryAt=null`, and `mode=BLOCKED`/`reasonCode=RUNTIME_STOPPED`. Resource start/stop failures use `RUNTIME_STARTING`/`RUNTIME_STOPPING` or `RUNTIME_FAULT` as applicable; they never masquerade as a dependency retry.

## RS04 Scoped readiness and both plan families

Every scope contains exactly the common keys `scopeKey`, `kind`, `status`, `reasonCode`, `requiredTarget`, `dataCutoff`, `nextRetryAt`, `progress`. `scopeKey` is a server-owned non-secret identifier of 1–128 characters from `[A-Za-z0-9._:-]`; it is stable for that dependency/activation, not a raw endpoint, credential, exception or ever-changing minute target. `kind` is `PLAN | INDEX | PROVIDER | CALENDAR`. Plan entries additionally require `symbol`, `planFamily`, `planVersionId`, `planHash`, `activationRevision`, `readOnly`; index entries additionally require `indexCode`; provider and calendar entries have no other fields. Identity fields keep existing canonical formats and JavaScript-safe revision bounds.

`planFamily` discriminates `LEGACY_LOW_BUY` (`TradePlan`) and `EXPLICIT_RULES` (`ExplicitTradePlan`). `requiredTarget` is null when no eligible completed target can yet be identified; otherwise it is exactly `{"kind":"INTRADAY","targetEnd":<Shanghai timestamp>}` or `{"kind":"OFFICIAL_CLOSE","tradeDate":<YYYY-MM-DD>}`. The backend chooses the actual required target from D3; a completed minute acquisition target is not automatically an eligible five-minute evaluation boundary. `dataCutoff` is the latest validated persisted data represented by this scope or null; it alone never proves contiguous coverage, references or state completeness.

`progress` is exactly `{requiredCount, completedCount}` with nullable nonnegative safe integers. Both are null if the exact required obligation set is unknown; otherwise both are present and `completedCount <= requiredCount`. Counts refer to the current scope/target's verified required units, not provider attempts or a percentage. Target/activation/requirements change may reset these counts and must update the identity/target coherently. A `0/0` preopen requirement can be complete without inventing a minute. Do not claim completion because one call returned successfully or returned an empty list.

| `status` | Required meaning |
|---|---|
| `WAITING` | No eligible work is currently due, or first-result/bootstrap preparation has not yet been admitted. Concrete waiting reason; no claim of recovery activity. |
| `RECOVERING` | Actual pending/owned recovery work or a scheduled retry exists for known missing inputs/state; concrete reason and target where known. |
| `READY` | Exact required persisted inputs and state are available for the stated scope/target. `reasonCode=null`, `nextRetryAt=null`; known counts are complete. This is not synonymous with fresh intraday data. |
| `BLOCKED` | A required dependency/state cannot currently be admitted or justified. Concrete reason plus eligible recheck time where policy allows, otherwise required operator action. |

The old global `readOnly` is removed from version 2, not silently redefined or emitted beside `mode`. Only `PLAN.readOnly` remains: `false` means the backend currently finds this plan eligible for its exact evaluation target after activation, dependency, generation and applicable freshness/state guards; `true` means it is not eligible. `false` requires `status=READY`, a non-null eligible target and a live coordinator. `READY` may still have `readOnly=true` during session standby or when no evaluation is due. An official-close/state-reconstruction target does not become an intraday trading opportunity when `readOnly=false`.

This per-plan field is a diagnostic projection of the evaluation guard, not authorization for manual position/plan/acknowledgement commands and not notification eligibility. Commands retain their own backend policies; current reminder presentation and delivery retain D5, including the cross-day risk exception and per-plan recovery barrier. A temporarily blocked plan cannot block another plan or independent supported display index. Stock provider failure must not suppress otherwise eligible index display, including supported hidden turnover constituent `399107.SZ`; deferred `899050.BJ` never becomes requestable through this view.

## RS05 Mode selection and public reasons

Determine mode from current desired scopes and actual work, in this order. Historical cache age is not an aggregate failure criterion.

1. No usable owner, stopped/stalled/faulted owner or a global local-resource fault: `BLOCKED`.
2. Some desired work is blocked/failed while an independent desired scope can proceed: `DEGRADED`; healthy plans remain eligible. If every desired scope is prevented, use `BLOCKED`.
3. Otherwise, real pending/owned recovery or retry work exists: `RECOVERING`.
4. Otherwise, at least one current session monitoring scope is ready and has work due: `MONITORING`.
5. Otherwise: `STANDBY` with its next scheduled reconsideration, for example before the first minute, lunch, closed session or no active plan. Pending close/reference repair takes precedence over standby.

`RECOVERING` cannot be justified by an old quote alone; it requires work recorded by the coordinator. A closed market with complete display facts and no obligations is `STANDBY` even though intraday freshness is false. Unused/deferred indexes are not desired evaluation dependencies. Delivery/database/provider detail remains visible in `/system` without making unrelated plan readiness global.

Fixed `reasonCode` vocabulary for this revision:

| Category | Codes |
|---|---|
| Lifecycle/progress | `RUNTIME_STARTING`, `RUNTIME_STOPPING`, `RUNTIME_STOPPED`, `RUNTIME_FAULT`, `COORDINATOR_STALLED`, `STORAGE_UNAVAILABLE` |
| Normal waiting | `BEFORE_FIRST_MINUTE`, `SESSION_BREAK`, `SESSION_CLOSED`, `NO_ACTIVE_PLANS`, `AWAITING_FIRST_EVALUATION` |
| Recoverable work | `CALENDAR_UNKNOWN`, `REFERENCE_PENDING`, `COVERAGE_INCOMPLETE`, `CLOSE_PENDING`, `PUBLICATION_PENDING`, `PROVIDER_UNAVAILABLE`, `RATE_LIMITED` |
| Scoped blocks | `CREDENTIAL_MISSING`, `PERMISSION_DENIED`, `SEMANTICS_INCOMPATIBLE`, `CONFIGURATION_INVALID`, `HISTORY_UNAVAILABLE`, `STATE_UNAVAILABLE`, `GENERATION_CHANGED` |
| Aggregate mixture | `SCOPED_DEPENDENCY_FAILURE` |

The backend maps these codes to bounded UI copy; raw provider/storage exceptions and secrets have no field. `SCOPED_DEPENDENCY_FAILURE` is aggregate-only and scopes contain actual causes. Provider failures preserve D4 retry ownership: 30/60/120/300 seconds transient backoff, shared cooldown at least 300 seconds, permission recheck no more than once per operation per 300 seconds. Missing credentials have no provider request; local maintenance rechecks configuration. A nullable retry is not an excuse for an unexplained failure: the UI shows either scheduled retry/local reconsideration or the fixed required-action explanation.

## RS06 REST projections and partial availability

All changed monitoring responses contain integer `monitorContractVersion=2`, nullable `runtimeGeneration`, and `observedAt`. Dashboard and symbol collection snapshots also retain their authoritative committed `sequence`; pagination remains unchanged. The health response contains `runtimeStatus` plus the existing resource/detail fields `startedAt`, `stoppedAt`, `lastCompletedMinute`, `lastCompletedMinuteAgeSeconds`, `latestEvaluationAt`, `latestEvaluationAgeSeconds`, `gaps`, `cooldownUntil`, `providers`, `executor`, `database`, `delivery`. Old root `status`, `readOnly`, `nextPollAt` and `nextRetryAt` are replaced by `runtimeStatus`; resource-detail validations and their secret-free bounds remain applicable. A missing owner uses null lifecycle timestamps; a known owner's stop timestamps remain ordered. Root aggregate minute/evaluation ages remain diagnostic and never confer per-plan freshness.

The dashboard's exact root keys are `monitorContractVersion`, `sequence`, `runtimeGeneration`, `observedAt`, `runtimeStatus`, `counts`, `symbols`, `marketIndexes`, `marketTurnover`. Remove the old aggregate `connectionStatus` business-liveness shortcut; transport connection state is browser-owned. Existing index/turnover schemas and six count names remain. `symbols` contains at most 10 unique active-plan entries, including plans awaiting their first result. Empty database/no active plans gives HTTP `200` with empty `symbols`, zero counts and an honest `runtimeStatus`; absence of one result never replaces the whole dashboard with `UNAVAILABLE`. Real read/validation failures still fail closed.

Each active-plan entry is a closed union with common keys `symbol`, `name`, `planFamily`, `planVersionId`, `planHash`, `activationRevision`, `observedAt`, `availability`, `scope`, `currentActionable`. `scope` is the exact matching PLAN scope from `runtimeStatus.scopes`.

- `availability=UNAVAILABLE`: additionally `projectionState=WAITING|RECOVERING|BLOCKED`, matching the scope status, and `reasonCode`; no `decision`, `explicitRuntime`, result hash, invented signal, price or zero-filled evidence. If inputs are ready but the first evaluation has not committed, use `projectionState=WAITING`/`reasonCode=AWAITING_FIRST_EVALUATION` while scope may be `READY`. `currentActionable=false`.
- `availability=CURRENT|CACHED`, `planFamily=LEGACY_LOW_BUY`: additionally `decision`, the existing validated `AuthoritativeDecisionView`, plus existing `riskDistanceFen`, `satisfiedConditionCount`, `totalConditionCount`, `referenceMarket`. Read the legacy result repository with exact plan/activation identity. Do not overwrite its immutable `dataHealth` to pretend recovery succeeded.
- `availability=CURRENT|CACHED`, `planFamily=EXPLICIT_RULES`: additionally `explicitRuntime`, the existing `ExplicitPlanRuntimeView` with `status=CURRENT`, exact plan/activation identity and persisted `ruleOutcomes`, plus outer `resultHash`, `ruleEligibility` and `actionableRuleIds`; no legacy `decision`, zone/episode or legacy counts. Read `ExplicitDecisionRepository.latest(...)` with the exact active plan hash and activation revision. Validate each `ExplicitEvaluationResult` before using its rule outcomes. No legacy loader or synthetic single signal may stand in for multiple explicit rules.

`ruleEligibility` contains exactly one entry per displayed explicit rule, in the same order, at most 3. Each entry has exactly `ruleId`, `action`, `currentActionable`, `reasonCode`; rule ID/action must match that rule's persisted outcome. Outer `resultHash` is the unchanged `ExplicitEvaluationResult.result_hash`; the result, `explicitRuntime`, active identity and current-generation validation must agree. `actionableRuleIds` is the ordered, duplicate-free subset whose eligibility is true; row-level `currentActionable` equals whether this subset is nonempty. A true rule requires `reasonCode=null`; a false rule requires a fixed presentation reason: `NO_CURRENT_SIGNAL`, `INTRADAY_EXPIRED`, `RECOVERY_HOLD`, `RISK_NO_LONGER_VALID`, `CURRENT_STATE_UNVERIFIED` or `CACHED_RESULT`. These reasons summarize the existing D5 checks and do not create new signal or delivery policy. Unknown/contradictory reasons, unknown IDs, action mismatch or a subset mismatch fail closed. An unavailable explicit entry has no result/eligibility fields; a cached explicit entry has an empty subset and all rules false with `CACHED_RESULT`.

Per-rule eligibility is a current backend projection outside immutable `ruleOutcomes` and result hashes, derived from the signal-specific validity and applicable committed state/intent. For example, an expired BUY and a still-valid `RISK_ALERT` may coexist: only the risk rule appears in `actionableRuleIds`, even though the row boolean is true. Components use that explicit subset and never apply the row boolean to every rule. The recovery barrier may temporarily hold the risk rule without expiring it; a later resolved risk remains false. No renderer may infer eligibility from condition satisfaction alone or change stored outcomes to match present eligibility.

`CURRENT` requires the currently installed generation, active identity and applicable target to match the committed result; it alone does not mean a BUY/SELL signal exists. `CACHED` is an identity-valid historical projection shown with its original cutoff and evaluation date; it always has `currentActionable=false`. A prior activation or plan hash cannot populate the current active-plan entry; that result remains available only through historical reads. `currentActionable` is backend-owned, requires `CURRENT`, and applies the existing signal-specific D5 validity/barrier checks. It must never be computed from `mode`, socket state, `readOnly` or a new blanket 90-second rule; risk-state exceptions remain intact. No status read mutates a result or dispatches an alert.

For a still-valid historical risk notice, a `CURRENT` projection requires current-generation authoritative proof of the latest risk state and completed per-plan recovery barrier. The original risk result/hash/date remain unchanged; that proof does not recertify historical market data as fresh or create a new evaluation/intent. Merely loading a historical result is `CACHED`. `PLAN.readOnly=true` because no new evaluation is due during standby does not by itself invalidate a separately proven risk notice.

`GET /symbols` uses the same union with existing pagination. `GET /symbols/{symbol}` returns the same plan discriminant and projection availability with its applicable existing detail data, or typed `NO_ACTIVE_PLAN` absence for a known inactive symbol. `GET /health/symbols/{symbol}` exposes the exact PLAN scope even before its first decision. `GET /explicit-plan-runtime/{symbol}` uses the same explicit projection authority and status envelope; it does not create an independent readiness source. Unknown valid symbols retain `NOT_FOUND`.

The six dashboard counts remain backend-owned display counts, not a partition or permission gate. Existing legacy categories retain their business meaning; explicit outcomes do not acquire a legacy low-zone classification. `actionable` counts unique entries with `currentActionable=true`; unavailable entries contribute only to `blocked` when their scope is blocked and never to actionable/normal/risk from fabricated evidence. Exact result identity, safe sequence and snapshot data are captured coherently; an owner change during assembly retries/fails the read rather than combining generations. Consumers reject invalid sibling entries instead of guessing a healthy fallback; normal missing projections use the declared union rather than malformed data.

## RS07 WebSocket and transport versus progress

Connect only after a validated v2 dashboard snapshot: `/ws/v1/monitor?after=<sequence>&monitorContractVersion=2`. Both query parameters must occur exactly once; version has the same canonical `2` grammar. Validate Origin, version and cursor before reading/replaying events. Missing/wrong version is accepted only to close with code `1008`, reason `MONITOR_CONTRACT_MISMATCH`, and zero data frames; malformed cursor remains `1008`. An absent injected service remains `1013`; untrustworthy/unsafe durable sequence remains `1011`. No old-version fallback stream is offered.

Committed event envelopes and payloads remain byte-for-byte `schemaVersion=1`; do not add `monitorContractVersion` to persisted events. `monitor_sequence` remains the sole monotonic high-water domain, with existing replay window, page limit, range validation and snapshot invalidation. No new committed event type is needed.

The exact v2 heartbeat keys are `type`, `monitorContractVersion`, `sequence`, `runtimeGeneration`, `observedAt`, `runtimeStatus`. `type=heartbeat`, integer version `2`, and `runtimeStatus` has RS03's closed shape. Remove old `runtimeLive` and `runtimeStartedAt`; generation is present even during recovery/standby. The frame is a current status observation, not a decision snapshot and not a durable event. Its `sequence` is the server replay cursor already delivered on that socket; reading status cannot advance it.

The exact v2 recovery frame is `{type:"snapshot.required", monitorContractVersion:2, sequence:<safe integer>, reason:"REPLAY_UNAVAILABLE"}`. It precedes normal close and authoritative snapshot recovery. No compatible status frame repairs an event gap or substitutes for a dashboard snapshot.

Keep 20-second heartbeats, 20-second snapshot/connect deadlines, 40-second silence detection and existing capped jittered reconnect. An accepted, ordered, well-formed heartbeat with the applied generation/cursor can refresh transport silence even when mode is `BLOCKED`, `DEGRADED`, `RECOVERING` or `STANDBY`; it cannot refresh `lastProgressAt`, clear `STALLED`, restore a stale action or promote a cached decision. Duplicate/stale observations do not reset transport silence. `observedAt` is nondecreasing within one accepted observation stream; identical observations are duplicates. Clock reversal triggers an authoritative snapshot recovery before accepting a new time baseline, never a browser freshness calculation.

A generation change, event gap, malformed compatible frame or `snapshot.required` invalidates current actionable presentation, then coalesces one dashboard refresh before reopening with its exact cursor. A mode/progress-only change with the same generation/cursor updates authoritative status in place, without reconnecting or changing decision payloads. Loss of generation identity, coordinator progress or required state readiness invalidates affected current presentation and coalesces an authoritative projection refresh; restoring it requires that projection and applicable D5 checks. A mere `readOnly` change because no evaluation is due cannot implement a new risk-notice expiry rule. Status observations coalesce a projection refresh when current signal validity may have changed; Vue does not recalculate signal validity from timestamps or scope counters. An ordinary `system.health.updated` remains an invalidation hint. Protocol mismatch enters terminal `RELOAD_REQUIRED`, not this reconnect loop.

## RS08 Wire examples and rejection cases

Valid new request and negotiation headers:

```http
GET /api/v1/health HTTP/1.1
X-Monitor-Contract-Version: 2
Accept: application/json

HTTP/1.1 200 OK
X-Monitor-Contract-Version: 2
Cache-Control: no-store
```

Valid complete heartbeat: the coordinator is alive during lunch, and no recovery work is falsely reported. This example has no desired plan/index scope.

```json
{
  "type": "heartbeat",
  "monitorContractVersion": 2,
  "sequence": 42,
  "runtimeGeneration": "b2f55d82-8d98-4c5e-a3bc-18529f84e982",
  "observedAt": "2026-09-21T12:00:00.000000+08:00",
  "runtimeStatus": {
    "lifecycle": "RUNNING",
    "mode": "STANDBY",
    "reasonCode": "NO_ACTIVE_PLANS",
    "nextWakeAt": "2026-09-21T12:00:20.000000+08:00",
    "nextRetryAt": null,
    "lastProgressAt": "2026-09-21T11:59:50.000000+08:00",
    "coordinator": {
      "state": "SCHEDULED",
      "progressDueAt": "2026-09-21T12:00:20.000000+08:00"
    },
    "scopes": []
  }
}
```

Valid complete PLAN scope for an explicit plan missing coverage; it may coexist with a `READY` legacy sibling in one dashboard. It is a scope object, not a complete dashboard or a fabricated result.

```json
{
  "scopeKey": "plan:003043.SZ:7",
  "kind": "PLAN",
  "status": "RECOVERING",
  "reasonCode": "COVERAGE_INCOMPLETE",
  "requiredTarget": {
    "kind": "INTRADAY",
    "targetEnd": "2026-09-21T10:05:00.000000+08:00"
  },
  "dataCutoff": "2026-09-21T10:03:00.000000+08:00",
  "nextRetryAt": "2026-09-21T10:05:30.000000+08:00",
  "progress": {"requiredCount": 5, "completedCount": 3},
  "symbol": "003043.SZ",
  "planFamily": "EXPLICIT_RULES",
  "planVersionId": "41699c9c-8c65-4ab8-9740-20efdd45e3d9",
  "planHash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "activationRevision": 7,
  "readOnly": true
}
```

Old client request `GET /api/v1/dashboard` without a version is rejected; a guarded POST has the identical negotiation result before command execution:

```json
{
  "error": {
    "code": "CONFLICT",
    "message": "Request conflicts with current state",
    "details": [{
      "location": ["header", "X-Monitor-Contract-Version"],
      "code": "MONITOR_CONTRACT_MISMATCH",
      "message": "Reload the application to use monitor contract 2"
    }],
    "requestId": "aabbccddeeff00112233445566778899"
  }
}
```

Valid eligibility subobject for two displayed rules in the same identity-valid explicit result: the BUY has expired at its source cutoff + 90 seconds, while current committed risk state and the completed recovery barrier still justify the risk notice. This illustrates the outer eligibility fields, not a complete plan entry; the referenced rule IDs/actions must also occur in its `explicitRuntime.ruleOutcomes`.

```json
{
  "currentActionable": true,
  "ruleEligibility": [
    {"ruleId": "buy-entry", "action": "BUY", "currentActionable": false, "reasonCode": "INTRADAY_EXPIRED"},
    {"ruleId": "risk-watch", "action": "RISK_ALERT", "currentActionable": true, "reasonCode": null}
  ],
  "actionableRuleIds": ["risk-watch"]
}
```

Valid compatible socket: `/ws/v1/monitor?after=42&monitorContractVersion=2`. Old socket `/ws/v1/monitor?after=42`, and invalid versions `monitorContractVersion=02` or duplicate `monitorContractVersion=2&monitorContractVersion=2`, close `1008` with `MONITOR_CONTRACT_MISMATCH` before any replay/heartbeat. A new client receiving an old five-key heartbeat without version rejects it and requires reload; it never treats `runtimeLive=true` as v2 negotiation.

| Invalid example or mutation of the valid examples | Required result |
|---|---|
| Heartbeat `monitorContractVersion: "2"` or missing version | Reject; no live/actionable upgrade. Missing/unsupported protocol requires reload. |
| The heartbeat adds root `readOnly:false` or `runtimeLive:true` | Reject the closed v2 shape; no optional compatibility interpretation. |
| `coordinator.state=STALLED` while `mode=MONITORING` | Reject contradictory status; keep actions invalidated even if socket traffic continues. |
| The recovering PLAN scope changes only `readOnly` to false | Reject; incomplete coverage cannot authorize evaluation. |
| `completedCount=6` with `requiredCount=5` | Reject impossible progress. |
| Explicit entry contains `decision` or legacy entry contains `explicitRuntime` | Reject family mismatch; do not run a fallback loader. |
| Unavailable entry has `currentActionable=true`, or a cached entry becomes actionable after a heartbeat | Reject; require authoritative identity-valid current projection and D5 validity. |
| The eligibility example adds `buy-entry` to `actionableRuleIds` or applies the true row flag to its BUY | Reject; per-rule eligibility and subset must agree. |
| A new command page submits POST before validating any v2 health/dashboard preflight | Client contract violation; the POST must never be sent to an unnegotiated old backend. |
| Standby has old display cutoff and `readOnly=true` | Valid when obligations are complete; no stale-recovery banner solely for age. |

## RS09 UI, acceptance and rollout

Use existing `/` and `/system` surfaces. Show transport disconnected/reconnecting separately from backend mode. Display standby without a stale-data recovery warning, recovering with target/progress, and failed scopes with fixed cause plus retry/reconsideration time or required action. Keep cached cutoff and historical risk date visible. No retry-now button, token screen, login, silent refresh of provider certification or client-side trading calculation is added.

| Acceptance | Required offline evidence before its gate closes |
|---|---|
| A06 / RR016 | Both plan families coexist; waiting/blocked plan never hides a healthy sibling; unsupported optional index does not block unrelated work; explicit outcomes come from their repository. |
| A11 / RR015, RR018–RR019 | Healthy heartbeats during an overdue coordinator cannot certify progress; standby remains honest; generation survives degraded/standby states. |
| A12 / RR017–RR018 | Old/new client-server matrix, direct-command entry against an old server with zero POST calls, duplicate/missing version and cursor, safe mismatch errors, missing projections, sequence gaps, generation replacement, clock reversal and cached asset reload. |
| D5 / RR016, RR018 | Cached/first-result/old-activation projections cannot become current through status alone; mixed explicit expired BUY/current risk, risk-state exceptions and recovery barriers survive presentation. |

RR015–RR019 must update backend models/guards, OpenAPI, generated types, strict runtime parsers, shared guarded command adapters, monitor store/stream and UI in bounded slices. Generate artifacts; never hand-edit generated types. Guarded routes add no new REST path. Ship matching backend and hashed frontend assets as one local version, with a non-stale HTML entry point and no mixed-version default path. RR020 enables the replacement only after C0–C4 prerequisites; live migration, real-provider acceptance and deployment remain separately authorized.

Review must settle the exact negotiation/header guard inventory, status union, scoped `readOnly`, family projections and all wire examples before RR017 implementation. This draft records those concrete choices for review and does not itself close RR002 or a checkpoint.
