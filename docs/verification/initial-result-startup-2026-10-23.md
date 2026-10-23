# Initial result startup verification

## IMS-V01. Decision
KEEP the frontend candidate. Only fresh result entry defers same-page monitor startup until result settlement or `5000 ms`. Canonical query changes retain the gate; leaving the path releases it; unmount prevents late start. Established monitor, backend authority, full evidence validation and cancellation/drain remain unchanged. Native memory work stays paused. No AI extraction, daily inventory or README changes are included. No commit or push performed.

## IMS-V02. Method and retained failure
Current production composition, existing configuration and real historical run; local standby workload, not active trading acceptance. A pre-existing service on port `8765` was left running; the measurement service used `8766`. The first bind attempt failed and was not a performance sample. Both browser variants serve their respective actual built static assets through identical local browser interception and send real API requests to the same unchanged backend. No responses or proofs are mocked. Each page begins after physical drain, awaits its initial dashboard response and closes before final drain.

The first fixed `20` pairs found a correctness defect: automatic query normalization released a gate keyed by full URL. All first-wave data is retained. After correcting identity to pathname and adding regression tests, the same fixed `20` pairs were rerun once. No samples were dropped or added to achieve a pass. API guards use a separately predeclared `10` alternating pairs of single and genuinely concurrent HTTP reads. Their baseline/candidate labels designate alternating control slots on the identical backend, not different backend implementations.

## IMS-V03. Results
| Median seconds | Baseline | Candidate |
|---|---:|---:|
| Browser result ready | 4.9885 | 2.4280 |
| Complete page lifecycle server process CPU | 4.890625 | 4.539063 |
| Result-only API | 1.962758 | 1.980688 |
| Result-only process CPU | 1.992188 | 2.023438 |
| Concurrent result API | 4.517462 | 4.502802 |
| Concurrent monitor API | 4.064097 | 4.055023 |
| Concurrent process CPU | 4.726563 | 4.679688 |

Readiness improves by `2.5605 s` / `51.33%`, passing both `1.0 s` and `20%` gates. All guard median regressions are below `10%`. Browser readiness ranges: baseline `4.961–5.024 s`, candidate `2.405–2.452 s`. Both variants have `20` ready views and `80` successful HTTP responses. Baseline also has `4` later dashboard requests without a response before closure; these are retained as incomplete, not successful fast reads. Candidate has none. There are `0` page-script errors and `0` business writes. The API guard has `60` successful responses and identical hashes across all `40` result responses. Required authority retries and tail latency remain visible; no p95 claim or backend acceleration claim is made.

CPU is measured with server process CPU counters across each complete lifecycle, including drain and snapshot overhead; it excludes browser CPU and other processes. Measurements are diagnostic for this run and machine. They do not guarantee gains for every dataset or competing monitor tab. Required validation has not been removed.

## IMS-V04. Boundaries and tests
Frontend: `1225` tests passed; type checking and production build passed. Backend boundaries: `55` tests passed in `3.79 s`, with the existing Starlette deprecation warning. Coverage includes settlement success/failure, URL normalization, leaving, timeout, unmount, stale callbacks, established monitoring and existing protocol mismatch behavior. A deliberately inverted settlement condition caused `2` test failures and was restored. The initial test was red before implementation. A sandbox temporary-file rename failure was rerun outside that restriction; it was not a product failure.

Real-browser stalled-result verification observes monitor request arrival `5.143 s` after navigation, including app startup; the owned timer is exactly `5000 ms`, tested at its boundary with fake timers. Pending connection text is truthful; result reading subsequently completes and drains. The event loop may schedule execution later than its timer deadline. Final outstanding reads, pauses, active/queued proof owners, retained bytes and socket children are zero. The measurement service shut down normally; the pre-existing service was not stopped. Protected backend and monitor-stream hashes match the prior baseline.

## IMS-V05. Evidence and stopping
[Raw measurements, harnesses, traces and hashes](evidence/2026-10-23-initial-result-startup/manifest.json). Harnesses are archived source; restore their original `.pytest_cache/initial-result-startup` layout and built assets to rerun. The candidate passes the fixed gates; stop here. Do not add caching, backend schedulers, native allocation work or further performance experiments to this task.

Archive text uses LF line endings; the manifest retains original capture hashes and archived-byte hashes.
