# Disconnect-aware heartbeat admission

Status: proposal only, 2026-10-22. Baseline: `b323840`. [Chinese review copy](PROPOSAL-disconnect-aware-heartbeat.zh-CN.md). [Previous real measurements](../../verification/result-tail-latency-2026-10-22.md). [Controlled observations](../../verification/evidence/2026-10-22-disconnect-heartbeat-analysis/observations.json).

Implementation authorized and P0 delivered: [specification](SPEC-disconnect-aware-heartbeat.md), [tasks](TASKS-disconnect-aware-heartbeat.md), [verification](../../verification/disconnect-heartbeat-2026-10-22.md). This proposal preserves the analysis snapshot.

## DHA01. Evidence and diagnosis

The previous real-browser/server correlation identifies 7 heartbeat attempts from already closed pages, starting 18.03–21.17 seconds after browser closure. Of these, 6 enter snapshot verification for 3.27–10.93 seconds; 1 never enters a snapshot. These are separate attempts, not 7 successful reads or 6 necessarily distinct physical index validations. Do not sum overlapping snapshot wall time as saved CPU or assign every historical result outlier to this cause.

Current source establishes the mechanism:

- `CommittedMonitorEventStream.serve` accepts the connection, replays events and waits for publication/heartbeat deadlines. It has no continuing receive loop. Both heartbeat branches await `_current_heartbeat_frame` before `send_json`.
- `RuntimeStatusEventStream._current_heartbeat_frame` awaits `get_health`; the ordinary v2 path enters the full owned monitor read. A transport failure at send therefore arrives after that work.
- Installed Starlette updates `client_state` to disconnected when its `receive()` consumes `websocket.disconnect`. Checking an unconsumed state property cannot discover that queued event. Its send path can also surface `WebSocketDisconnect` after an underlying `OSError`.
- `MonitorReadOwner.run` sets the observer lease's cancellation event when its observer is cancelled. It deliberately retains the independently owned task. Without receiving disconnect or cancelling the socket observer, the existing cancellation machinery receives no signal.
- `useMonitorStream.stop` already aborts its snapshot, clears timers and closes the active socket on component disposal. This is not evidence that the server has consumed disconnect; adding another browser unload message is not the primary remedy.

Two new controlled probes use the unchanged stream, real Starlette socket and real `MonitorReadOwner`, with synthetic empty replay/health and an accelerated 0.01-second heartbeat. Closing before the first heartbeat still calls health once; only `websocket.connect` is consumed and disconnect remains queued. Closing during an admitted read leaves 1 owned read, its cancellation flag false and the sender waiting, until the probe releases the read and send discovers failure. These establish control-flow behavior, not actual-owner, integrity, browser or performance acceptance.

The existing ownership, evidence-flight, heartbeat and storage-composition baseline passes 35 tests with 1 existing Starlette deprecation warning in 9.22 seconds. No production code, data, configuration or running service is changed during this analysis.

## DHA02. Time boundaries and achievable guarantee

Distinguish browser closure, server receipt/consumption of disconnect, observer departure and physical completion. Browser closure can precede detection because of transport or event-loop scheduling. A silent network failure without close delivery is not immediately observable; existing protocol-server keepalive remains responsible for detecting it. Do not change transport timeouts in this proposal.

The hard rule is: once this connection has observed disconnect, admit 0 new heartbeat health reads. A read admitted before that boundary may already be running. Treat it as admitted work, propagate observer cancellation and retain physical ownership until actual cleanup. Do not retrospectively call it an admission violation or a successfully verified heartbeat.

## DHA03. Recommended P0: supervise receive and send

Use a small connection-lifecycle helper in `web/` and keep `websocket.py` focused on replay and cadence. After successful acceptance, supervise exactly 1 receiver and 1 sender child per connection. The existing `serve` call owns these children; retain at most 1 pending health observer per connection. No per-tick orphan tasks, application message queue, global connection registry or detached cleanup task is introduced. Resource use is bounded per connection; this does not impose a new global connection limit.

The receiver is the only consumer of `websocket.receive()` after acceptance. It waits for `websocket.disconnect` and records a monotonic closed signal immediately. Non-disconnect application messages have no command/acknowledgement semantics in the existing protocol: discard them without parsing, logging, buffering or triggering reads, and preserve event-loop fairness if receives are immediately ready. Preserve transport frame limits. Do not run multiple competing receivers or bypass Starlette through raw receive callables.

The sender retains the existing replay loop and waits on the shared publication condition. Before starting heartbeat health work, replay work or sending another frame, check this connection's terminal signal. In the heartbeat path there must be no scheduling gap that bypasses a newly observed terminal signal before calling the existing health service. If disconnect and a deadline/publication/read completion are ready together, a known terminal signal wins; do not emit a frame or start another health read.

The supervisor waits for receiver or sender completion. Observed disconnect cancels the sender observer, including its publication wait or current health await. Sender completion, expected send disconnect, snapshot-required closure or failures cancel the receiver. Cancel remaining children once, await their termination and observe all exceptions on every exit, including outer request/server cancellation. Receiver failure also stops new admission; unexpected failures retain existing error semantics rather than becoming successful normal closes. Do not broadly swallow `RuntimeError`, business errors or storage-cleanup failures.

Disconnect is connection-local: do not notify all publication waiters, stop the monitor service, pause storage or cancel another connection's work. Keep expected peer closure quiet and avoid sending a second close frame after terminal transport state. A send-side disconnect remains a necessary fallback because it can precede receive-side observation.

Apply the transport lifecycle consistently to v1/v2, with compatibility tests for both. V1 must not start v2 health reads. Keep `/ws/v1/monitor`, contract negotiation, close-code meanings, frame fields, cursor/replay ordering and snapshot recovery unchanged. Preserve v2's fixed 20-second cadence under publication storms and existing next-deadline calculation; never overlap or catch up missed heartbeats with a burst.

## DHA04. Admission, cancellation and physical ownership

| State when closure is observed | Action | Required outcome |
|---|---|---|
| Waiting for the first/next heartbeat | Stop sender and publication wait | No new health read or read-owner admission |
| Health observer admitted; owned operation not yet started | Cancel this observer through the existing path | Lease cancellation prevents the owned operation at its existing checkpoint |
| Snapshot collection or evidence queue/comparison is running | Detach observer and set its lease cancellation | Existing cooperative checkpoints reject cancelled work; sessions/leases remain owned until unwind |
| Physical proof validation is running | Detach only this observer | No forced thread cancellation, early permit release or evidence-byte release; other live followers remain valid |
| Result and disconnect arrive together | Honor known terminal state | No stale heartbeat delivery or next read; completed outcome/exception is observed |
| Stop/storage checkpoint races with disconnect | Keep normal pause, shutdown and drain | Failed drain retains its pause; no database disposal while physical work remains |

Preserve `MonitorReadOwner`, `IndexEvidenceFlights` and `RuntimeStatusReadService` business semantics. The supervisor cancels the health caller, never reaches into owned task sets or cancels the proof future. A leader's observer leaving must not abort proof needed by a live follower. All observers leaving still does not mean physical work has ended. Existing cancellation checkpoints may terminate abandoned work without a response; they must never turn partial validation into a success.

Successful connected health reads still perform independent authority-before/after comparisons, their own clock and database snapshot, activation reread, and every current plan/inventory/risk/calendar/evidence check. Preserve both attempts on authority instability, the 8-read / 15-second ownership and evidence limits, 1 physical index validator, 1 distinct queued owner, 64 MiB evidence retention and in-flight-only exact-input sharing. The 15-second budget retains its existing cooperative waiting/checkpoint semantics; it is not a new forced execution timeout. No completed response/proof cache or fast heartbeat from an earlier health result is introduced.

Cover the existing `_stopped_health` branch explicitly: it constructs a temporary diagnostic reader and stops that reader in `finally`. A disconnect must not bypass that stop/drain or create another temporary reader. Socket cleanup may need to await this existing cleanup; do not promise instantaneous teardown or add a short timeout that drops its ownership. Only finished transport/observer tasks may be declared cleaned up; physical drain is measured separately.

## DHA05. Diagnostics and comparison plan

Extend existing opt-in allowlisted tracing only as needed: observed disconnect, heartbeat admission, observer cancellation and transport-child cleanup. Associate opaque socket IDs with existing heartbeat/read/physical trace IDs. Separate observation of close from browser-close time, and separate observer cancellation from physical finish. Preserve the 1800-second window, 1024 admitted / 64 active traces, 64 spans, 128 completed records and 1 MiB / 2-backup rotation. Do not log inbound messages, close reasons, authority tokens, plan bodies or URLs. Diagnostic overflow/failure must not alter admission.

Record these separately: new health admissions after observed disconnect; health reads admitted before closure; physical validations and their live followers; observer detach-to-physical-finish interval; pending sender/receiver children; evidence retained bytes; result request stages/response success. Do not count cancellation, 503 or incomplete proof as a fast successful read. Check default-disabled behavior too; do not rely solely on diagnostic records that can reach their observation budget.

Proposed implementation experiment:

1. Capture a fresh successful actual-owner baseline before source changes, preserving the historical observation separately. Use the same data, configuration, server protocol, clients and heartbeat cadence for before/after. Freeze candidate revision before the final runs. Do not mix baseline/after source in a live process.
2. Run at least 20 normal browser closures before the first heartbeat and 20 closures during known admitted reads; correlate actual browser close and server detection independently. Repeat bounded 2/8-client workloads, including one remaining live observer and an open result page. Use at least 20 successful connected heartbeat observations as the correctness control. Force-cancel or held-worker fixtures are deterministic race tests, not real latency samples.
3. Acceptance: 0 health admissions after observed terminal state; no leaked connection children; physical owners/retained bytes return to baseline after real release/drain; connected frame, authority, proof and recovery assertions stay green. A currently undetected silent disconnect must remain labeled separately.
4. Compare result request medians, ranges/maxima, first-byte and physical worker stages with all failures retained. Deduplicate physical proofs rather than sum logical children. Use at least 10 alternating isolated connected rounds; proposed overhead limits retain <=2% CPU / <=5% wall. Report allocation/child-count changes, residual uncertainty and mixed-load regressions; do not promise a fixed result speedup from removing work that may have shared a proof anyway.

## DHA06. Verification matrix

| Boundary | Required regression |
|---|---|
| Admission race | Disconnect before first heartbeat, at deadline, during publication wake and immediately before health admission; already consumed state; send-side failure preceding receive |
| Busy connection | Continuous replay/publication, non-disconnect incoming messages, blocked send and receiver error; fixed cadence remains fair and one receiver/health observer only |
| Cancellation | Queue/collection/comparison/physical validator, leader/follower departure, all observers leaving, outer cancellation and repeated cancellation during cleanup |
| Authority/time | Token/generation/configuration/activation change, runtime startup/stop, temporary stopped-health reader and evidence target/expiry boundaries |
| Integrity | Altered row/content/event/report/set hashes, missing/reordered/extra retained evidence, byte-budget fallback and failure propagation to surviving observers |
| Storage | Stop/checkpoint/close races, drain timeout, cleanup failure retaining its pause, no premature database disposal, release of only the appropriate pause owner |
| Protocol/browser | V1/v2 negotiation, replay cursor and gaps, snapshot-required close, reconnect, close tab versus route navigation, 2/8 pages and actual result/monitor interaction |

Add regression tests that fail on current source before implementing the lifecycle. Remove the disconnect guard, cancellation propagation and child join in separate process-local mutations; each must be caught. Upgrade existing fake sockets to the real receive contract rather than using a production fallback that silently disables detection. Retain existing ownership/evidence/storage suites and browser/accessibility checks.

Baseline command used for this analysis, from the project directory:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_read_ownership.py tests/unit/test_index_evidence_flights.py tests/integration/test_runtime_status_websocket.py tests/integration/test_runtime_status_composition.py -q --basetemp=.pytest_cache/disconnect-analysis-baseline
```

## DHA07. Implementation sequence and alternatives

Proceed in order after implementation authorization: paired specifications/tasks and baseline; failing disconnect/race tests; connection supervisor and admission guard; cancellation/storage/protocol regression; real-browser and before/after report. Prefer keeping changes in the transport/lifecycle helper, tracing allowlist and focused tests. Touch the read owner, proof validator or authority service only if a separate measured defect requires its own review.

Checking `client_state` alone misses unread disconnect messages. Relying on send failure leaves the health-before-send cost intact. A browser unload beacon is unreliable and not authoritative. Shorter heartbeat/keepalive timeouts increase work or change transport behavior without fixing this missing receive path. Health/proof TTL caches, omitting historic evidence, lightweight unverified heartbeat health and larger pools violate or evade the requested boundaries.

Do not bundle a second optimization. If tail latency remains after P0, use the new timeline to distinguish undetected transport loss, event-loop/replay blocking, already admitted physical work and competition among genuinely live readers. Decide later work from those measurements. The rejected canonical-byte P1 is not reopened by this proposal.

## DHA08. References and delivery boundary

The [ASGI WebSocket disconnect contract](https://asgi.readthedocs.io/en/stable/specs/www.html#disconnect-receive-event-ws) defines disconnect delivery through receive and warns that send errors may precede it. [Starlette WebSocket documentation](https://www.starlette.io/websockets/) directs applications to its send/receive methods so connection state stays consistent. Installed source was checked as well; these contracts support the receive/supervision design, not a guarantee of instantaneous detection of an undelivered network failure.

Only this paired proposal and sanitized controlled-observation artifact are added. No production implementation, real-service restart, historical-data change, configuration change, commit or push is performed. Parallel AI extraction code, tests, fixtures and reports remain outside scope and untouched. Implementation acceptance remains future work; this proposal is not a completed optimization claim.
