# Completed-result read 503 verification — 2026-10-18

Chinese copy: [2026-10-18-result-read-isolation.zh-CN.md](2026-10-18-result-read-isolation.zh-CN.md). Scope: [RR-01–RR-03](../../tasks/result-read-isolation.md).

## RR-V01 — Confirmed root cause

The remaining 503 in AD-V03 came from head-of-line blocking of the shared metadata owner by completed-result projection. A local reproduction of the exact four-plan run `5f64cdab2e88e76acdf78de0a3525e3ba09104158688ee66b41a93d61116497d` returned 200 after 19.448 seconds, while concurrent job, dataset and second result requests returned the existing sanitized 503 envelope after 5.066–5.071 seconds. The requests reproduced the owner's configured 5-second admission timeout, not a provider failure or corrupt historical evidence. Previous access logs show those result/job failures while service-status reads remained 200.

Separate profiling found four loads of the frozen input and 156 day reads across input/report/diagnostics. Copied-input verification consumed 11.561 cumulative profiler seconds; diagnostics also decoded and checked 2961 retained rows. Profiler totals include instrumentation overhead and a concurrent read experiment; they are diagnosis, not a capacity benchmark. The first HTTP helper incorrectly inherited the environment proxy and failed to decode its non-JSON response. The valid localhost reproduction explicitly disabled proxy inheritance.

## RR-V02 — Repair and safety

Input, native report and per-plan diagnostics now share one SQLite read snapshot and one verified copied input. The same report-input and summary bindings, copied-day hashes/canonical bytes, typed audit rows, full published event-set digest, diagnostic limits and retention states remain enforced. No historical artifact, SQL report payload, rule or trade condition is changed.

A lazy result reader isolates summary, full-rule comparison and equity projection from task/dataset/admission metadata. It permits one physical result call, at most 8 observers and 8 distinct in-flight keys, and a 60-second queue-admission wait for distinct work. Metadata retains its existing 8 waiting reads/5-second admission bound. Identical overlapping requests share the active task, keyed by operation/run/source and pin state where applicable. Completion removes it; there is no persistent response cache. Later requests re-read evidence, including retention or damage changes. One observer leaving does not cancel another or drop physical ownership. Shutdown observes the reader and drains physical work. SQL BUSY/LOCKED, stopping, real overload and persistent faults retain sanitized 503/Retry-After behavior. No public schema, dependency, database migration, execution worker or AI authority is added.

## RR-V03 — Tests and actual service

| Check | Result |
| --- | --- |
| Related backend: publication/input, owner lifecycle, result queries/pinning/API, composition, automatic data, submission and diagnostics | 155 passed |
| Complete loop result API | 25 passed |
| Changed Python lint / whitespace review | Passed |
| Sharing mutation: remove in-flight lookup | Regression failed; exact bytes restored |
| Actual identical concurrent scenario, two rounds | All 8 responses 200 |
| Eight mixed concurrent reads, including new and old reports | All 8 responses 200 |

The isolation regression first failed with SERVICE_UNAVAILABLE during a held result projection. An early load-count observer patched a temporary file-handle instance instead of the class and was corrected. A pre-existing backpressure test used equal 5-second hold/admission deadlines, racing its own release; its admission deadline is now deterministically 0.03 seconds while preserving all backpressure assertions. These initial failed checks are retained. No test was skipped or correctness threshold relaxed.

The actual service was restarted after pending/running-task and physical-drain checks. In the same four-request scenario, the first result took 4.736 and 7.513 seconds; concurrent job/dataset reads took 0.025–0.249 seconds. The overlapping result joined active work and also returned 200. In the mixed eight-request scenario, new/old reports completed in 8.809/16.307 seconds, with both observers of each report agreeing; job/dataset/list/status reads took 0.073–0.087 seconds. Disk/load variance remains; the repair's essential observation is that expensive verification no longer makes those metadata reads expire behind it. The actual browser displayed all four dates, profit summary, per-plan price diagnostics and rule-comparison entries without the read-failure/retry prompt.

Both complete API responses match the saved baselines: the four-plan run above and `9050185da63d7961aa29228542fa024d127ac4d754af10e3066cbc26e09abeb2`. All 50 owned input/day/report/marker JSON files snapshotted before the restart keep their hashes. There was no new replay, network data synchronization, AI extraction or result rewrite. The zero fills, zero PnL and qualitative/valuation limits of the original four plans remain unchanged.

## RR-V04 — Evidence and limits

Ignored local evidence: `data/verification/2026-10-18-result-read-503/`, including `concurrent-before.json`, `profile-before.txt`, `concurrent-after.json`, `concurrent-after-repeat.json`, `mixed-reads.json`, `protected-files.json`, `red-isolation.log`, `owner-green.log`, `backend-regressions.log`, `result-api-green2.log` and `mutation.log`. Initial helper/test failures remain alongside them; no raw sources, configuration, credentials, screenshots or generated reports are added to Git.

This verification addresses the measured completed-result contention. Finite admission overload, prolonged I/O, persistent SQLite locks, unavailable/stopped services and corrupt evidence can still fail explicitly. The bound on readers is intentional. No general throughput/load certification or new live-provider/paid-AI validation is claimed; the original acceptance and automatic-data preparation limits remain.
