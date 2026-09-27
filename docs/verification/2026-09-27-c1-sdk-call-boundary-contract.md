# C1 SDK call boundary contract

## SCB-01 Status and evidence

- Status: **REVIEWED / approved for local commit**. At the initial design-only handoff the status was **DESIGN REVIEWED / implementation pending**.
- Source baseline inspected: `453cc0c7c9f15d977776c98671f0d419f37e9545`.
- This document records the Astra read-only design and two rounds of independent Sol design review. The design review itself authorized no implementation or test changes. The coordinator subsequently released the source freeze and separately authorized this bounded implementation. After independent code re-review and paired-document reconciliation, the coordinator authorized a local commit of exactly the 10 owned files. Push, deployment, scheduler integration, and A07 production fixes remain outside that authorization.
- The coordinator's pre-change full offline suite finished with 18 failed, 4778 passed, 1 skipped, and 4 deselected. Position/R13/R14/R17 failures are being handled separately and are not claimed fixed by this slice.
- The coordinator relayed a confirmed offline inline reproduction using the real `_CertifiedTushareClient` and an inner fake SDK, without file writes, external services, or database access. At design review, no new RED regression existed. The later PB01 RED and local verification are recorded in [the implementation report](2026-09-27-c1-sdk-call-boundary-verification.md).
- Earlier 248/281/291 passing results do not establish this newly identified SDK boundary. Independent code re-review accepted the repaired implementation with no remaining P1/P2; its separate 146-case evidence is recorded in the implementation report.

## SCB-02 Confirmed gap and inline reproduction

The current permission path can execute in this order:

```text
provider physical_start -> old S
endpoint(...) -> _CertifiedTushareClient.request
_current() certification/configuration checks
getattr(inner_client, operation)
inner SDK callable invocation
SDK return -> R
```

The wrapper performs potentially time-consuming checks and callable resolution after the provider guard. That guard therefore does not establish the final inner SDK admission time.

The confirmed inline reproduction freezes `captured_at=10:00:00`, `latest_start=10:00:15`, and allows the old physical guard at `10:00:14`. The real wrapper's certification callback advances a fake clock by two seconds. The inner fake SDK enters at `10:00:16`; the resulting proof has `S=10:00:14`, `R=10:00:16`, and `A=1`, and the old proof checks still accept it. PB01 must turn this reproduction into a failing regression before implementation.

## SCB-03 Scope and explicit gaps

| Scope/path | Current finding | Planned boundary scope |
| --- | --- | --- |
| `CURRENT_DAY_MINUTES` / `rt_min_daily` permission proof | S precedes wrapper certification and inner endpoint resolution | Included |
| `REALTIME_MINUTES` / `rt_min` permission proof | Same early-S gap | Included |
| `DAILY_BARS` / `daily`, including `453cc0c` | Final provider guard precedes wrapper work | Included |
| `DAILY_LIMITS` / `stk_limit` | Final provider guard precedes wrapper work | Included |
| `INDEX_DAILY` / `index_daily` | Final guard precedes wrapper work and date-argument construction | Included |
| `INDEX_REALTIME_MINUTES` / `rt_idx_min_daily` | Early S affects final admission and response row-time interpretation | Included |
| `INDEX_HISTORICAL_MINUTES` / `idx_mins` | Worker-entry guard exists, but no provider physical-start seam; the intervening work remains unguarded at the final boundary | Excluded from this implementation scope; remains an explicit unresolved gap. Adding a seam requires separate authorization and preservation of its existing window contract |
| Trading-calendar permission, historical stock paths, and ordinary business calls | This review does not establish a final inner SDK boundary for these paths | Excluded; do not claim acceptance or silently extend their guarantees |

Ordinary business paths retain their existing call routing, parameters, parsing, and exception behavior. The shared `_daily_bars` path may use the new resolver only when `_physical_start is not None`; ordinary daily/history calls keep the existing path. A parser-only permission call without an optional hook does not establish the new final-start guarantee.

## SCB-04 Minimal nominal resolver protocol

Introduce a standard-library-only common module, `market_data/sdk_call_boundary.py`, containing an internal nominal base `PermissionEndpointResolver` and `resolve_permission_endpoint(client, operation) -> Callable`.

1. Recognize owned wrappers only through the nominal base. Do not use `runtime_checkable Protocol`, virtual registration, custom instance checks, or `getattr`/`hasattr` to discover an optional private protocol. Installed Tushare `DataApi.__getattr__` turns arbitrary names into endpoint callables.
2. `_CertifiedTushareClient` explicitly implements `prepare_permission_endpoint(operation)`. On the current worker, complete `_current()`; a false result raises the existing `RequestNotStartedError`. Then resolve the inner endpoint and return the already unwrapped SDK callable. Do not return the existing `request` closure, which still performs certification work when invoked.
3. Resolve through nested wrappers only when each explicitly implements the nominal protocol. For raw fake clients and installed DataApi, resolve only the actual operation and require a callable. Every owned wrapper added to this chain must honor the same preparation contract.
4. Keep endpoint, arguments, and hook local to each invocation. Do not cache a prepared callable across calls, replace a shared callback temporarily, monkeypatch an instance, or store per-call admission state on a shared client.
5. Never forward a private hook or protocol argument to the real SDK. The final invocation receives only the existing endpoint's business kwargs.
6. The common module imports no runtime modules. Retain the existing `RequestNotStartedError` class and identity; the production wrapper can use its existing import. Do not move or redefine the exception, or introduce a runtime import cycle to support this protocol.

## SCB-05 Final guard and unique S

The required per-invocation order is:

```text
validate and construct all SDK arguments
-> wrapper certification/configuration checks and inner callable resolution
-> complete any remaining time-consuming authority checks
-> sample one S
-> evaluate existing time predicates using S and frozen epoch/event/cancel facts
-> directly invoke the already resolved inner SDK callable
-> sample R after return where the proof requires it
```

The final callback may perform authority preparation before sampling S. After S, allow only pure value validation and in-memory admission checks followed by the direct Python call. Do not read configuration/certification files, resolve endpoints dynamically, query the database, or resample the start time after S.

Existing generation/admission fences must be evaluated after the last time-consuming certification read, including reads performed by the final authority callback after wrapper preparation. Earlier checks at wrapper preparation do not satisfy this ordering. This preserves the existing predicates and adds no new policy.

Preserve `captured_at <= S <= latest_start`, where `latest_start = captured_at + 15s`, the original 31.25-second frozen market guard, same-day and rollback checks, and the existing generation/stop/calendar epoch/event/cancellation semantics. Worker checks use neither database reads nor Task objects. The hook and any recorded S belong only to the current invocation.

S means the call-site time marker after local preparation and before invoking the resolved inner SDK callable. It does not mean socket transmission time. SDK-internal argument serialization and transport work occur within that callable. This contract does not promise zero operating-system scheduling gap, atomic observation of all external state, forced SDK interruption, or zero SDK starts before the cancellation Event is set.

## SCB-06 Preserve mode-specific time rules

Freeze the evidence identity and the time predicates already required by the request's scope/mode. After all time-consuming reads, evaluate those predicates again using the same S without another file read:

- `INDEX_REALTIME_MINUTES` retains `S < semantics.provenance.valid_until`.
- Legacy certification retains its existing `observed_at <= S <= valid_until` rule and comparison boundaries.
- STOCK semantic mode retains its existing compatibility requirements. Do not introduce legacy freshness/expiry conditions into that mode.
- Other included paths retain their existing scope/mode conditions; this protocol does not invent a uniform expiry policy.

This closes the case where a certificate is valid when a read begins but expires before that read finishes, while S still satisfies the request's latest-start and market windows. Preserve the existing inequalities at equality boundaries.

## SCB-07 Exceptions, accounting, and side effects

Wrapper preparation and the final guard execute outside broad provider exception sanitizers. Only invocation of the prepared SDK callable is covered by existing SDK failure classification. Preserve explicit `except RequestNotStartedError: raise` handling so a trusted sentinel crosses the provider/controller boundary as the same object, without being converted to permission denial or another provider failure.

A false certification check is a local not-started outcome. Unexpected preparation/configuration-read errors and non-callable resolution are not fabricated HTTP 403 responses; the existing controller may still wrap unknown worker errors as `ERROR`.

The existing controller's ordinary `RequestNotStartedError` path propagates it directly. Its late-failure classifier currently maps this type to `ERROR`, for which it writes no permission block, cooldown, or backoff. The sentinel itself must not add supplier-failure accounting. If a controller wall-clock timeout has already occurred before the sentinel arrives, preserve that existing timeout accounting; do not claim it can be undone.

Keep the original durable 300-second reservation and once-only cursor callback semantics, including post-reservation rejection. Preserve existing controller floor-extension and physical-slot drain behavior; this design does not relocate the controller's persistence boundary or claim it is atomic with inner SDK entry. Cancellation releases the maintenance lock while already-started physical work drains through the existing controller slot. Late success cannot clear permission again. No business writes or scheduler integration are authorized.

## SCB-08 Required RED matrix

These are the design's required evidence entries. Their later local test results are recorded separately in the implementation report. Use temporary databases, fake SDK/transport, controlled clocks/events, and real wrappers/controllers where specified. No live provider or user database is needed.

| ID | Required failing case and acceptance evidence |
| --- | --- |
| PB01 | Reproduce `captured=10:00:00`, `latest_start=10:00:15`, old S at `10:00:14`, and real wrapper certification advancing entry to `10:00:16`. After the change, the final guard rejects and the inner SDK call count is zero |
| PB02 | Certification consumes time but remains legal. S is sampled after certification completes, exactly once, and the minute evidence/owner checks use that same S |
| PB03 | Inner dynamic `getattr` advances time or revokes authority. Final guard runs after resolution and rejects with zero inner SDK calls |
| PB04 | Certification begins valid and finishes beyond an existing effective-time bound while latest-start remains legal. Reject with zero SDK calls; cover `observed_at` lower bounds and `valid_until` equality using each mode's original comparison |
| PB05 | STOCK semantic compatibility does not accidentally inherit legacy freshness/expiry rejection |
| PB06 | During certification/resolution, trigger the frozen 31.25-second market window, epoch/event revocation, cancellation, stop, or configuration change. Also revoke generation/admission inside the final authority read after wrapper preparation. Reject with zero SDK calls; preserve any durable reservation and exactly one original cursor advancement |
| PB07 | Propagate the identical trusted sentinel through provider/controller without new supplier-failure, 429, or backoff accounting. Cover late sentinel handling separately from a controller timeout already recorded |
| PB08 | Raw fake client and dynamic DataApi resolve only the true operation. No optional-private-protocol lookup, private endpoint call, or private SDK kwargs leakage |
| PB09 | Installed default and direct-address query routes both work through offline transport substitutes and reach the existing strict parser |
| PB10 | Two concurrent or nested calls retain separate hook, endpoint, and S state; no callback replacement, cross-call overwrite, or cached preparation reuse |
| PB11 | Stock minute evidence covers `S=latest_start`, `S>latest_start`, `R-S=15s`, and `R-S>15s`. Requested cancellation and late success cannot clear permission; draining does not repeat the reservation callback |
| PB12 | DAILY_BARS, DAILY_LIMITS, INDEX_DAILY, and INDEX_REALTIME_MINUTES each pass through the real certification wrapper for legal start, boundary crossing, and revocation cases. Check durable reservations with the real controller and temporary SQLite; assert zero worker SQL |
| PB13 | Ordinary business paths preserve call counts, kwargs, parsing, and error behavior; parser-only calls without optional hooks are not counted as final-boundary acceptance |

## SCB-09 Independent design review and implementation gate

The Astra proposal was reviewed by an independent Sol sub-agent in two read-only rounds:

1. First review found one P2: sampling S after authority reads was insufficient unless the final guard also rechecked the scope/mode's existing certification time bounds. In particular, `_realtime_index_probe_current` checked `valid_until` before later configuration/certification reads. The reviewer found no other code-supported P1/P2.
2. The revision added same-S checks for the original time predicates, preserved their comparison boundaries, excluded an added legacy expiry rule for STOCK semantic mode, and expanded PB04/PB05. Second review confirmed the P2 was resolved and found no remaining P1/P2.

Both rounds were source/design inspection only: the reviewer changed no files and ran no tests or real requests. Those approvals concern the design, not implemented behavior. The coordinator subsequently released the freeze and authorized implementation, beginning with PB01 RED and bounded regressions for included paths. Later independent code re-review accepted the P2 repair and paired documents, and the coordinator authorized only the 10-file local commit. This does not close INDEX_HISTORICAL_MINUTES, stock minute owner wiring, A07, C1, or C3. Keep excluded gaps explicit.
