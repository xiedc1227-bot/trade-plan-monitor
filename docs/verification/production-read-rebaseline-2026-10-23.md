# Production read rebaseline and minimal optimization proposal

Historical baseline archive — `2026-10-23`, measured against `c7ba0d4` before the frontend optimization. The candidate was subsequently implemented and accepted in `c97dac6`; see the [final acceptance report](initial-result-startup-2026-10-23.md) and [completed implementation tasks](../specifications/backtesting/TASKS-initial-result-monitor.md). Descriptions of startup behavior, source hashes, “no source changes” and unchecked implementation checkpoints below describe the investigation at that time, not the current code or outstanding work. Preserve the original measurements and failed/exploratory observations; do not reinterpret them as final acceptance results. Native memory accounting remains PAUSED.

Evidence text is archived with LF line endings. The manifest retains original capture hashes separately from archived-file hashes; measurement values and historical source hashes are unchanged.

## PRR01. Decision and scope

Native memory accounting is PAUSED at the user's request. Keep all prior work and evidence; do not resume allocator instrumentation, process isolation or lower-budget admission automatically. This investigation changes no production code. Its recommendation is one frontend scheduling change for fresh entry into the historical result page.

[Chinese copy](production-read-rebaseline-2026-10-23.zh-CN.md). [Measurements and traces](evidence/2026-10-23-production-read-rebaseline/measurements.json). [Source/evidence manifest](evidence/2026-10-23-production-read-rebaseline/manifest.json).

## PRR02. Measurement method and limits

Baseline commit: `c7ba0d4`. No project server was running initially. Started the current production composition with the existing configuration/data on loopback, using its existing bounded trace switch. The small runner only controls normal shutdown and takes out-of-sample ownership snapshots. No reference authority, frozen clock, experimental allocator or alternative validator is injected.

Actual state: `RUNNING / STANDBY / NO_ACTIVE_PLANS`. The history contains `5` runs and `14800` detail rows. Requests select the first completed run from the actual list. Monitor reads verify `2473` historical index candidates, with `39820239 B` retained input in the ordinary single-proof path. These observations do not represent an active trading-session workload or all result sizes.

Run a fixed `20` rounds with rotated result-only, monitor-only and simultaneous result/monitor order: `80` HTTP responses, all `200`. All `40` result response hashes match. Preserve every attempt, including retries. Use medians and ranges, not p95.

The first browser wave has `6` rounds for each of entry, deferred startup and simultaneous two-page entry. It did not wait for physical work after closing pages; retain it as an exploratory succession-of-pages workload. The separate controlled wave uses the same fixed `6` rounds per case and awaits zero outstanding reads, active/queued proof owners, retained bytes, storage pauses and socket children before the next case. Both entry and deferred cases enable the same browser routing interception; only the initial dashboard request's send time differs.

In the deferred control, the result page's dashboard request is held until the result view is ready, then forwarded to the unchanged server and awaited through response completion. Nothing is mocked or treated as validated without a real read. This control estimates scheduling opportunity; it is not a shipped candidate or formal acceptance. Fresh browser contexts and the existing pinned browser are used. The two-page case opens an actual monitor page concurrently; its heading timing is not a monitor-data readiness metric.

## PRR03. Current performance

| Real HTTP scenario | Samples | Median seconds | Range seconds |
|---|---:|---:|---:|
| Result alone | 20 | 1.885 | 1.854–2.024 |
| Monitor alone | 20 | 2.441 | 2.420–5.021 |
| Result with monitor | 20 | 4.515 | 4.402–4.759 |
| Monitor with result | 20 | 4.166 | 4.044–6.990 |

| Controlled browser result readiness | Samples | Median seconds | Range seconds |
|---|---:|---:|---:|
| Current fresh result entry | 6 | 4.986 | 4.960–5.489 |
| Defer same-page startup dashboard | 6 | 2.462 | 2.431–3.890 |
| Actual simultaneous result and monitor pages | 6 | 5.071 | 5.034–5.121 |

The scheduling control saves `2.5245 s` or `50.63%` in median readiness. This is an observed diagnostic opportunity, not promised deployed improvement. It does not reduce total required validation or prove reduced total CPU. A different active monitor tab continues competing with result verification.

The controlled wave has `18` successful result views, `0` page-script errors and `0` business write requests. Of all recorded HTTP requests, `75` complete with `200`; `3` startup dashboard requests lack a response before page closure and are not classified as successful/fast reads. Physical work is subsequently drained. All deferred-control dashboard requests complete normally. Both browser waves, including their outliers, are retained.

## PRR04. Main bottlenecks and causal limits

Result audit verification is the main result cost: median wall `1.550 s` alone and `4.076 s` under concurrency. Result worker thread CPU is `1.875 s` alone and `2.086 s` concurrently. Result admission wait is about `0.00001 s`; a larger queue or more workers is not justified by this cohort.

Monitor full index validation takes median `2.302 s`, about `94%` of monitor-alone elapsed time, with `2.297 s` thread CPU. Independent before/after authority checks each take about `0.025 s` in the single-read case. Under concurrency, index collection rises from `0.079 s` to `1.402 s`, but concurrent collection thread CPU is only `0.156 s`. This is not evidence that adding a SQL index will remove the dominant cost. The spans support CPU/execution competition; wall minus thread CPU cannot uniquely identify GIL, scheduling, I/O or GC waits. Nested stage durations are not additive.

Four monitor requests perform two complete snapshot attempts: single rounds `6` and `13`, mixed rounds `16` and `19`. The longest is `6.989648 s`, trace `ae18ad8d561c43a3940eb77af4f8215d`, with `6.464507 s` in two snapshot attempts. The existing authority/identity retry condition caused the repeated attempt; current spans do not identify the individual comparison that changed. Do not weaken the second check or reuse the first proof across a changed authority. This is a new observation, not a reconstruction of the historical `8.69 s` request.

The actionable avoidable contention is in [App.vue](../../web/src/runtime-status/App.vue): `onMounted(monitor.start)` runs on result routes too. [stream.ts](../../web/src/runtime-status/stream.ts) immediately obtains a full dashboard snapshot before connecting the stream. Consequently, entering a historical result page starts both result verification and unrelated startup monitor verification. The controlled browser scheduling result isolates a useful first intervention without touching either verifier.

## PRR05. One minimal candidate

Limit the change to fresh entry into route `backtest-run-detail` while the app's monitor stream has not started. Start the primary result read immediately; start the same page's monitor flow after that initial read settles. Preserve normal startup on every other route and preserve an already-running monitor when navigating into the result page. No global request scheduler, cross-tab leader, new cache, backend queue or dependency is needed.

The gate releases on initial result success or failure. A proposed `5-second` maximum deferral prevents a stalled result read from indefinitely delaying monitor startup. Leaving the route releases the gate for the new route; unmount closes it and prevents late callbacks from starting abandoned work. Use route/request generations and one owned timer. The top banner must honestly show connection pending during the delay; never claim live/actionable status from old state. Once started, existing snapshot, heartbeat, protocol mismatch, expiry, reconnect and freshness behavior resumes unchanged.

The browser control defers until view readiness without this production timer; the implementation must separately verify the narrower request-settlement boundary and timeout. The expected benefit is earlier historical-result visibility on fresh entry. It will not eliminate CPU competition when another real monitor page is active, accelerate all monitor reads, or remove legitimate authority retries. Do not expand the task when those limits remain visible.

Implementation checkpoints:

- [ ] Specify paired frontend lifecycle/acceptance requirements for this single gate, using the existing app/view boundary.
- [ ] Implement the initial-result gate and honest banner state; keep backend and evidence code unchanged.
- [ ] Test success, failure, timeout, route changes, unmount, late callbacks, already-running monitor, protocol mismatch and deferred-start cancellation.
- [ ] Run the fixed comparison and decide keep/revert under PRR06; record all outcomes.

## PRR06. Benefit gates and stopping rules

Predeclare one `20`-pair alternating current/candidate browser comparison with the same run, configuration and drained starting state. Require both at least `20%` and at least `1.0 s` median improvement in fresh result readiness. Use medians/ranges only; any p95 claim still requires at least `100` successful observations per variant. The diagnostic `50.63%` is not the acceptance threshold or a guarantee.

Also verify result-only APIs and genuine monitor/result concurrency remain within `10%` median regression for response time and measured total CPU, with no increased errors/refusals/timeouts. A failed local stopwatch is not a success because the page looks faster. Monitor startup's explicit bounded deferral is reported separately; established monitor pages must not be delayed by the new gate.

Stop and reject the candidate if it weakens authority/integrity/freshness, refunds in-flight work, breaks drain, leaves an orphan timer/request, or needs a completed-proof cache or allocator/IPC redesign. Stop if the fixed comparison misses the benefit gate or worsens the guard metrics. Do not add samples until it passes. Allow focused correctness repair, then rerun the same declared check; repeated inability to satisfy the gate ends this candidate rather than creating a new infrastructure project.

If the candidate passes, ship only that bounded frontend change and stop expansion. Revisit backend CPU only when later production measurements show a remaining user-visible problem that justifies a separately bounded task. Prior backend/native acceptance limits are not weakened by this new frontend experiment.

## PRR07. Preservation and verification

No source changes under `src`, `web`, `tests` or `scripts`; protected-source hashes are recorded. Every actual request retains independent authority before/after, activation reread, full historical evidence, exact comparison and existing retry/retention rules. Cancellation and physical-drain implementations are unchanged. No histories, hashes, fields or validation stages are omitted.

After measurement, outstanding reads, active calls, queued owners, retained bytes, storage pauses and socket child tasks are all zero. The temporary service completes normal shutdown; no server was running beforehand. Result/preparation table counts and configuration hash match before/after. Existing `5` runs and `14800` detail rows remain. No concurrent AI extraction, daily inventory or README changes are included.

Focused regressions: `55` pass in `3.62 s`, with one existing Starlette deprecation warning. Selection: `tests/integration/test_monitor_disconnect.py`, `tests/integration/test_monitor_disconnect_ownership.py`, `tests/integration/test_read_trace_ownership.py`, `tests/unit/test_audit_read_integrity.py`. This validates unchanged boundaries, not an unimplemented candidate. There are `680` recorded traces and `0` dropped spans. The initial controlled-harness file-generation encoding error occurred before measurements; it was corrected to explicit UTF-8 and retained in the evidence notes. Bilingual IDs, literals, limits and local links are checked.
