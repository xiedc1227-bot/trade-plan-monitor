# Monitor evidence sharing: CPU contention and next-step proposal

Status: analysis only, 2026-10-21; baseline `4c71bccfdeb5525e166d98b14dc9bc0c777d609d`. [Chinese review copy](PROPOSAL-monitor-evidence-sharing.zh-CN.md). [Previous verification](../../verification/result-read-concurrency-2026-10-21.md). [New isolated observations](../../verification/evidence/2026-10-21-monitor-sharing-analysis/measurements.json). Production code, configuration, service ownership and real evidence were not modified. This is a proposal, not implementation approval or acceptance.

## MSH01. Findings

`RuntimeStatusReadService._read` captures authority on the owning event loop, assembles one committed SQLite snapshot in a worker, rereads activation identities, captures authority again, and permits at most two attempts. Its comparison includes token, generation, configuration, lifecycle, block/standby reasons, owner absence, plans, dependencies and progress state. These checks must remain per request.

`get_dashboard`, `get_health`, symbol collection/detail/health all reach this expensive read. `RuntimeStatusEventStream._current_heartbeat_frame` calls `get_health` for every socket heartbeat. One SELECT fixed N+1 overhead, but each physical assembly still validates every historical index payload. Default `to_thread.run_sync` use does not coalesce these assemblies. In a GIL-enabled process they compete with result audit verification; adding workers does not remove this repeated CPU work.

The new read-only experiment freezes a consistent copy of the live monitor database: 2,008 candidate heads, no active plans. This differs from the earlier 1,928-head sample. Runtime authority is a synthetic stable absent owner, time is fixed, and the real immutable result projection retains its existing validators. It measures duplication and an upper bound, not live authority correctness or deployed sharing.

| Isolated scenario | Wall seconds | Process CPU seconds | Physical monitor assemblies |
|---|---|---|---|
| Two monitor reads | 7.8355 | 7.8125 | 2 |
| Two monitors + result, round 1 | 10.3930 | 10.6250 | 2 |
| One shared assembly + result, round 1 | 6.0348 | 6.0781 | 1 |
| Two monitors + result, round 2 | 10.1057 | 10.3438 | 2 |
| One shared assembly + result, round 2 | 6.4013 | 6.4375 | 1 |

Complete dashboards and complete result responses match in the accepted experiment. Individual monitor assembly CPU is approximately 3.8–4.1 seconds. The shared experiment retains `_read` and observer authority/identity probes, but does not implement production admission, time fencing, cancellation or shutdown. The approximately 40% CPU opportunity is an upper-bound observation, not a forecast. An initial equality experiment against the changing live database was discarded; background index publication changed its input. A restricted helper run did not reach measurement and was stopped; accepted runs used the permitted local execution environment.

A separate ordered scan binds every raw head/payload column and literal `snapshot_json` without parsing or validating it: 2,008 rows / 32,402,117 encoded bytes, wall 0.1555 / 0.1298 / 0.1305 seconds; median 0.1305 seconds. This establishes feasibility of fresh content comparison. It does not measure the proposed registry, exact comparison, retained memory or end-to-end candidate.

## MSH02. Options and recommendation

| Option | Safety/cost | Decision |
|---|---|---|
| Share a completed dashboard or use a TTL cache | Can hide evidence damage, lifecycle changes and time expiry. | Reject. |
| Share the entire in-flight `_read` by token/sequence | A late request can inherit an earlier snapshot, health observation or actionable state. Current token equality is not full data/time equality. | Do not implement directly. |
| Seal a cohort before taking authority/time/database snapshot | Avoids late-join ambiguity, but misses staggered requests unless they wait for the next cohort; requires retry/lifecycle ownership. | Safe alternative to benchmark if necessary; not the first implementation. |
| Share only in-flight index evidence validation after each request proves identical raw content | Targets the measured CPU hot path while preserving each request's snapshot, observation, authority and response formatting. Adds bounded raw input ownership and a fresh comparison scan. | Recommended first slice. |
| Separate CPU process or reuse completed typed objects | More lifecycle, consistency and memory complexity. | Defer pending this slice's measurements. |

The shared function is pure: ordered immutable head/payload values → validate all candidates → verified ranking → immutable selected records. It must use the same typed/canonical/hash/provider/head binding checks as `_market_index_from_row` and `list_latest_market_index_snapshots`. It must not receive an ORM session, runtime owner, clock-dependent eligibility or authority provider. No dependency from monitor code to backtest thread lifecycle is introduced.

## MSH03. Admission and content proof

1. Each caller follows its own `_read`: owning-loop authority capture and its own observation; fresh owned session with explicit `BEGIN`; plan, proof, inventory, risk, rule and calendar checks in that snapshot. Whole responses, `get_health` output and actionable flags are not shared.
2. Scan all requested historical head/payload candidates in that same transaction, preserving the left join and missing-row visibility. Use stable head-key ordering only for content comparison; compute selection with verified `snapshot_rank`, never SQL metadata maxima.
3. The private namespace includes composition/database identity, validator contract, `MAPPING_VERSION`, formula definition and requested index scope. A conservative first slice may also separate generation/configuration namespaces. Do not assume the arbitrary `RuntimeReadAuthority.token` is hashable. A digest is a lookup prefilter, not validation or sufficient equality proof.
4. A joining caller must compare the complete ordered raw rows byte-for-byte, including literal JSON, all head/payload columns, missing-payload markers and candidate count, with the active flight's immutable input. Digest collision, partial/prefix equality, matching filenames or matching stored hashes alone never permit joining. Comparison streams in 128-row batches without retaining another full input copy.
5. Join only while physical validation remains in progress. A completed future, including the completion/cleanup race, cannot satisfy a new caller. If the flight completes during comparison, perform a new full validation. A mismatch takes an independent validation path in the caller's same snapshot; a fresh scan in that transaction may be needed to recover an already-consumed prefix. It must not omit previously scanned rows or jump to a different transaction.
6. The leader verifies every candidate, including corrupt unselected history, and returns only immutable selected records plus internal completeness metadata. Followers continue assembling their own dashboard/health/detail response in their own transaction. No SQLAlchemy identity map or mutable response object crosses threads/consumers.

This permits a later caller to share the expensive pure validation because it has reread the same entire input in its own snapshot. It does not let it adopt the leader's older snapshot or clock. Missing/different evidence must fail or be fully revalidated, never fall back to a previously valid response.

## MSH04. Authority, time and heartbeat boundaries

Keep every existing before/after authority comparison, activation identity reread and maximum two-attempt budget for every caller, including followers. Retry accounting is per caller, not two shared attempts followed by two private attempts. Provider failure means unavailable authority; it must not be converted to owner absence. Authority providers remain on their owning loop.

Each request retains its own `observedAt`, progress state, desired target, health observation/ages and eligibility/deadline calculations. Do not retimestamp a prior dashboard or reset an action's validity window. Index artifact validation is time-independent with respect to the current caller clock; live plan/input-proof and time-sensitive projection work remain independent. The existing 90-second condition-plan window, day/session transitions and command preflight remain unchanged.

Each WebSocket still builds a heartbeat with its own delivered replay cursor. A shared index proof or dashboard high-water sequence cannot replace that cursor, certify progress or skip replay. Heartbeat cadence and continuous-publication starvation protection remain unchanged.

The isolated fence fixture shows why shortcuts fail: event sequence stays 7 when evidence is changed; a persistent observer's `PRAGMA data_version` changes 2 → 3 while a newly opened connection reports 2. The writer's own value does not change for its own commit. A held WAL read still sees old bytes and a new transaction sees changed bytes. SQLite documents that data versions are comparable only on the same connection and WAL reads retain their snapshot. Use these only as optional invalidation hints, not positive content proof. See [SQLite PRAGMA](https://sqlite.org/pragma.html#pragma_data_version) and [SQLite isolation](https://sqlite.org/isolation.html).

The real `RuntimeProgress` fixture keeps the same authority token while advancing from `WORKING` to `STALLED` after its deadline. Token equality cannot replace the existing progress-state check. A digest/content-only shared index validator avoids caching these time-dependent authority facts.

## MSH05. Bounded ownership and shutdown

Proposed initial limits, to finalize in paired implementation specifications: 1 active physical index validation, 1 pending distinct-content group, 8 admitted monitor observers, and 64 MiB retained raw-input budget across all flights. Stream comparison in 128-row batches. The 32,402,117-byte experiment counts encoded content, not Python retained size or RSS; account DTO/string/byte overhead explicitly. Budget pressure must switch to full streaming verification within the same bounded physical admission, or return existing `SERVICE_UNAVAILABLE`, without partial validation or stale fallback. No unbounded materialization or hidden 8 × full-input copies.

Resolve joins before acquiring a leader-only validation permit. Followers must not hold a permit needed by their leader. Use a synchronous future/condition or equivalent owned bridge inside existing workers; do not create another large CPU pool or block the owner event loop. Preserve caller deadlines, avoid resetting queue age and observe all exceptions. A caller's cancellation releases its observer only; it cannot cancel another caller, evict the physical flight early or free its byte budget before the worker finishes. See [AnyIO thread cancellation](https://anyio.readthedocs.io/en/stable/api.html#anyio.to_thread.run_sync) and [Python shield](https://docs.python.org/3.14/library/asyncio-task.html#shielding-from-cancellation).

Ownership belongs to the monitor read service/composition. Track whole physical assembly/identity reads as well as shared validation. Shutdown must reject new reads, revoke current runtime authority, drain already-owned work and sessions, then allow database checkpoint/disposal. A timeout cannot be reported as successful drain or release ownership of a still-running worker. Audit `MonitorWebComposition.stop` and runtime database-close ordering; the current service has no shared-flight shutdown boundary to reuse automatically.

## MSH06. Implementation order and acceptance gates

- MSH-T01: record paired specifications/tasks; add scoped measurement of source endpoint/heartbeat, raw scan/comparison CPU, physical validations, join/miss reasons, authority retry, queue/drain and peak retained bytes/RSS. No evidence bodies or credentials in logs. Establish same frozen sample and live request-overlap baselines.
- MSH-T02: isolate immutable index inputs and the pure validator, prove literal output/hash/error/ranking equality without sharing, then implement the bounded in-flight registry and exact comparison. Preserve standalone repository behavior by default; explicitly inject the monitor-owned verifier.
- MSH-T03: connect HTTP and heartbeat consumers while retaining independent `_read` checks; implement cancellation, retry budgets, shutdown and storage-failure behavior. No API/schema, heartbeat interval, timeout, retention or result audit change.
- MSH-T04: run the safety matrix and real browser journeys, compare CPU and latency, then keep only a measured win. Do not extend scope to whole-response sharing in this slice.

Mandatory safety matrix: active owner/configuration/generation change during a shared flight; STOPPING/STALLED and unreadable authority; activation ABA; inventory/risk/rule/calendar/proof changes; 90-second/target/day boundaries and clock rollback; same-size/same-mtime SQL corruption; bad canonical bytes/domain/hash/formula/provider/head binding; missing unselected history; deletion/retention; forced digest collision; completion/cleanup races; same/different scopes; leader/follower/all-observer cancellation; full admission/byte budget; shutdown with a held worker; heartbeat cursor/cadence/replay. Every rejected share must still fully validate or fail closed. Existing result event-set, pin, retention and physical-drain regressions remain required.

Proposed performance gates: with 2 and 8 overlapping identical-content monitor callers plus one result read, one shared traversal validates all 2,008 candidates; every later request after completion traverses them again. At least 10 alternating controlled rounds should reduce median process CPU by at least 25%, while the single-monitor case regresses at most 10%. Also report real HTTP result latency, monitor wait, event-loop/service probes, admission rejection and RSS. Retain existing heartbeat/client deadlines. These are proposed gates, not achieved production results. If live overlap is rare or byte/lifecycle overhead misses the gates, keep the original path and reassess representation/process work separately.

## MSH07. Delivery state

Only this proposal pair and portable analysis observations were added. One-off scripts, frozen copies and isolated fence fixtures remain ignored under `.pytest_cache/monitor-sharing-analysis-20261021/`. No production implementation, service restart, real-data cleanup, schema migration, commit or push was performed for this analysis.
