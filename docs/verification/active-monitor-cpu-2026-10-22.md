# Active monitor CPU attribution and process feasibility verification

[Chinese review copy](active-monitor-cpu-2026-10-22.zh-CN.md). [Specification](../specifications/backtesting/SPEC-active-monitor-cpu-isolation.md). [Tasks](../specifications/backtesting/TASKS-active-monitor-cpu-isolation.md).

## AMC-V01. Decision and scope

P0 adds default-disabled, bounded diagnostic observations. The exploratory buffered process variant is **P1 no-go**: its aggregate input-copy accounting is 119,382,234 bytes (113.85 MiB), exceeding the unchanged 67,108,864-byte (64 MiB) boundary. No production process, completed-proof cache, authority offloading, new dependency or weakened validation is introduced. No commit/push is part of this phase.

Baseline is `7a7ac88`. Preserve the earlier proposal/evidence and unrelated README edits. AI extraction and daily-inventory implementation files remain outside this change. The isolated experiment uses frozen read-only copies; it never writes historical inputs or publishes a result.

## AMC-V02. Implemented attribution

Authority observations distinguish health, delivery SQL, configuration/semantic checks, progress, plans and dependencies. They execute in their original synchronous order on the owner loop. Index observations cover SQL iterator advancement, collection, exact comparison, waits, validation, count/byte admission and fallback. One `index.physical` trace identifies a physical proof; followers link to it with `index.join`, rather than duplicating physical CPU. One `monitor.loop_lag` aggregate records maximum timer lateness and cancels its timer at read completion, including cancellation.

`index.scan` is inclusive in wall time but its `activeNs` and thread CPU measure iterator advancement only. `index.collect` includes scanning; `authority.health` includes `authority.delivery`. Do not add nested intervals or interpret wall minus thread CPU as exclusive GIL wait. The 1800-second / 1024-trace / 64-active / 64-span / 128-completed / 1 MiB / 2-backup limits remain unchanged. Only allowlisted timings, opaque identities, counts and bytes are recorded.

The protected `_read_owned`, `_assemble`, `_identities`, `_latest_index_records`, `_market_index_from_row`, admission, release and drain functions retain their baseline AST. Every request retains independent before/after authority, transaction and clock checks. Literal canonical equality, metadata binding, all historical evidence, shared-proof exact comparison, time boundaries, storage fences and actual-work drain are preserved.

## AMC-V03. Fixed feasibility results

Each workload uses 10 A/A pairs followed by 20 alternating ABBA/BAAB blocks: 20 thread controls plus 40 thread and 40 process observations. There are 200 completed measurements across isolated monitor and mixed result/monitor workloads. Mixed results start after physical validator submission. Authority is a synthetic absent owner; full monitor assembly and full immutable result projection run against frozen inputs. These are not live-owner or browser latency measurements.

| Median measure | Existing thread | Exploratory process | Change |
|---|---:|---:|---:|
| Isolated monitor completion | 2.0121 s | 2.1943 s | +9.05% |
| Isolated monitor total CPU | 2.0000 s | 2.1563 s | +7.81% |
| Mixed result duration after launch | 5.2224 s | 2.7358 s | -47.61% |
| Mixed monitor completion | 3.0953 s | 2.8750 s | -7.12% |
| Mixed batch completion | 5.3565 s | 2.9132 s | -45.61% |
| Mixed parent + child CPU | 5.2969 s | 5.5391 s | +4.57% |

All complete monitor outputs match, and all 100 mixed complete result outputs match. Each monitor read performs 2 independent authority calls and 1 physical proof, then reaches zero outstanding reads and retained bytes. Child CPU is measured with before/after process clocks, including IPC handling; it is not limited to validation-function CPU. Cold Windows spawn/import is separate from warm samples.

Input accounting for 2008 candidates: parent raw retention 30,826,621 bytes; parent serialized input 28,864,496 bytes; child serialized input 28,864,496 bytes; child reconstructed raw retention 30,826,621 bytes. Their combined accounting already exceeds the gate before further IPC transients and the 83,015-byte output. The raw-retention counter is conservative and can count repeated scalar references; this is the existing admission accounting, not a measurement of unique live heap bytes. 3 fresh-process observations per variant separately record Windows working set and private commit. Summed process peaks are not a simultaneous aggregate RSS peak.

The median parent peak working set is 290.53 MiB for the thread variant; the process variant has 345.52 MiB parent and 184.30 MiB child peaks, whose medians sum to 529.82 MiB. The two main experimental worker cold starts are 0.9488 s and 1.0715 s. These measurements strengthen the reason to specify a separate absolute process-memory allowance before any future production design.

The latency gate passes, but the input-copy gate fails. An absolute production process-memory allowance, isolated-result production regression and 100-attempt live-owner P1 acceptance were therefore not advanced. A streaming/shared-memory alternative would require a separate design and measured lifecycle contract; it is not silently substituted here.

## AMC-V04. Diagnostic overhead

20 alternating ABBA/BAAB blocks on complete frozen monitor reads give 40 disabled and 40 enabled observations. Median wall time is 2.2688 s disabled and 2.2355 s enabled; parent CPU is 2.2344 s and 2.2031 s. This passes the <=5% wall / <=2% CPU overhead gates for this sample. Negative observed deltas are measurement variation, not a claimed speedup. These synthetic-authority measurements do not replace real authority-path observations.

## AMC-V05. Real requests and browser

Both real waves complete 20 result-only and 20 mixed result/monitor attempts: 120 HTTP responses, all 200. All 80 complete result response hashes are identical. Real live input has 2238 candidates / 35,441,065 retained bytes; the frozen feasibility input has 2008 candidates. Browser result tabs, source inspection, refresh, live heartbeat and concurrent 2/8-page journeys all pass without page/network errors or business writes. These direct HTTP timings are separate from browser rendering checks.

| Real result observation | Old service, diagnostics disabled | P0, diagnostics enabled |
|---|---:|---:|
| Result-only median / maximum | 2.128 / 2.403 s | 2.136 / 2.685 s |
| Mixed median / maximum | 4.675 / 4.890 s | 6.010 / 6.335 s |

This cross-restart mixed increase is retained and is not presented as a speedup or a causal diagnostic overhead estimate. It triggered the separately declared, fixed same-process investigation: 20 alternating ABBA/BAAB blocks, 40 disabled and 40 enabled mixed attempts, all 160 HTTP responses successful with identical complete result hashes. Result duration is 5.7139 s disabled versus 5.8223 s enabled (+1.90%); batch completion is 6.1416 versus 5.8395 s; process CPU is 6.2734 versus 6.0781 s. All samples remain in these medians. The owner performed a second complete validation in 9 disabled and 4 enabled samples; the lower aggregate CPU/batch time is not an intrinsic diagnostic benefit. Exploratory one-proof strata have 31 disabled and 36 enabled samples and likewise show no CPU increase. This same-owner check does not establish the entire cause of the earlier cross-restart drift.

All 20 P0 mixed result requests overlap an actual `http.monitor` index validator; none of the 20 result-only requests does. The largest result is round 3, trace `e6d225252abb4062ba0c76654f7fccac`, with physical result `e674021fefae4cfe8faa0920d381436e`:

| Recorded interval | Wall seconds | Thread CPU seconds |
|---|---:|---:|
| Server HTTP | 6.3334212 | unavailable |
| Result worker | 6.2792696 | 2.9062500 |
| Result publication, inside worker | 0.5365048 | 0.5156250 |
| Result audit, inside worker | 5.6639362 | 2.3125000 |
| Competing index collection, including scan | 1.5342162 | 0.1718750 |
| Competing SQL iterator advancement | 1.5259158 active | 0.1562500 |
| Competing full index validation | 3.3493336 | 3.1718750 |
| Monitor authority before / after | 0.0377143 / 0.3141721 | 0.0468750 / 0.0468750 |

Only 0.0541516 s is outside the result worker. Index gate wait is 0.0000009 s; maximum observed loop lateness is 0.6829393 s. In the after-authority check, configuration takes 0.0847016 s, plan capture 0.1179282 s, dependency capture 0.1095891 s and delivery SQL 0.0015708 s. Thus result audit and full index validation are the main competing CPU work in this sample; input scanning and loop scheduling also wait. No exclusive GIL-wait or GC counter was collected.

The 20 slow result samples leave at most 1.01% of their server interval outside the measured result worker. The 12 slow monitor samples leave at most 0.53% outside non-overlapping authority/snapshot/activation spans. The largest monitor request, trace `e413dd1993ed4052a5dd3cb724eae27c`, takes 9.328 s client / 9.3274302 s server and has two complete snapshot attempts (4.8786724 s and 3.7409956 s). This is the existing authority/identity retry path, not permission to reuse the first proof after a changed authority. New spans do not identify which individual comparison changed. All these direct slow requests meet the 5% reconciliation target without dropping nested intervals or double-counting shared CPU.

After browser close and after the supplemental investigation, outstanding reads, active calls, queued owners, retained bytes, storage pauses and connection child tasks are zero; no storage fence is cleared. Normal shutdown completes and the same local service is restored with P0 loaded and diagnostics disabled (health 200, no trace header). Result/preparation table counts and configuration hash match before/after, including 5 runs, 14,800 detail rows and 19 preparations.

## AMC-V06. Verification and retained failures

- Relevant backend regression: 469 passed, 1 existing platform skip, 1 existing Starlette deprecation warning. All 9 new attribution tests also pass independently after strengthening assertions.
- Browser regression: 25 passed; frontend type checking passes.
- Integrity, independent authority, disconnect admission and drain mutations: 13 rejected as expected. 3 new observation mutations are rejected: missing physical trace, missing iterator closure and missing timer cancellation.
- Exploratory IPC checks: complete output equality; corrupted unselected historical JSON, missing payload and crossed head revision rejected; cancellation detaches one observer while its follower receives the actual result; normal shutdown joins the child.
- Scoped Ruff passes. Source fingerprints and protected-core AST checks are retained in the evidence.

The first mixed fixture attempt correctly failed because the frozen result database lacked its matching immutable-input owner directory. The original 100 isolated-monitor observations were retained; the missing directory was copied with ownership marker and content hashes, and only the not-yet-measured mixed schedule ran. No ownership check was bypassed. The first physical-trace mutation run exposed a test collection dependency; the new test was made independently collectible. The first timer-cancellation mutation survived because the test checked only scheduled callbacks, missing an already-ready callback; the assertion now also checks the actual timer handle. The supplemental client's first setup request encountered an environment proxy response before any sample or diagnostic toggle; explicit localhost transport fixed the harness. All failures are retained, not reclassified as passes.

## AMC-V07. Evidence and limitations

[Portable measurements](evidence/2026-10-22-active-monitor-cpu-verification/measurements.json) include fixed samples, 572 real traces (325 in the primary drained browser cohort), full hashes, memory observations, source checks, failures and verification outcomes. No spans were dropped in the primary cohort. [Result screenshot](evidence/2026-10-22-active-monitor-cpu-verification/result-enabled.png) and [monitor screenshot](evidence/2026-10-22-active-monitor-cpu-verification/monitor-enabled.png) were visually inspected. No database, credentials or serialized private evidence payload is published.

Parallel work appeared during verification in `src/trade_plan_monitor/ai/plan_extraction.py`, `src/trade_plan_monitor/domain/unified_plan_validation.py`, `tests/unit/test_current_review_contract.py`, AI fixtures/reports/tests and README files. These are preserved and excluded from this P0 scope; their observed hashes are recorded separately. The related regression is repeated on the shared tree after those dependency edits. No parallel patch is copied into the P0 implementation.

Controlled measurements are local-host observations, not cross-machine guarantees; normal host scheduling and unrelated host load remain possible. No claim is made that P0 reduces production latency or that the historical 6.502-second request can be retroactively subdivided by new spans. The next candidate is a separately specified bounded chunked transport for pure validation, with aggregate byte leases and physical drain; it needs new feasibility evidence before P1 can proceed.

## AMC-V08. Pre-submission review

After implementation, the user separately authorized review, commit and push. The earlier no-push scope describes the implementation phase. The reviewed release base is `6fd3e4c`, already synchronized with `origin/main`; the parallel AI changes are already separate remote commits and are not included in this P0 diff.

No blocking finding remains. Current production source, new tests and parallel dependency fingerprints match the recorded completed regression. A fresh focused run passes 34 tests with the existing Starlette warning; the physical-trace, iterator-close and timer-cancel process-local mutations are all detected again. Scoped Ruff, whitespace, bilingual IDs/numbers/code-token parity, local links, protected-core AST checks and evidence/source/screenshot fingerprints pass. A credential-pattern scan finds no matches in the pending text files. No production restart, historical-data write or new performance claim is part of this review.

The release includes only the paired P0 proposal/specification/tasks, attribution code and tests, and paired verification report with sanitized evidence. AI extraction, daily inventory, README and configuration changes are excluded. P1 remains no-go under the unchanged input-copy budget.
