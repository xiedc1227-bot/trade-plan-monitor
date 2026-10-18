# Backtest read and preparation progress verification — 2026-10-18

Chinese review copy: [2026-10-18-backtest-read-reliability.zh-CN.md](2026-10-18-backtest-read-reliability.zh-CN.md). Task: [BR-01–BR-03](../../tasks/backtest-read-reliability.md).

## BR-V01 — Reproduced causes

Independent history/job reads shared one metadata owner that immediately rejected overlap, even for ordinary page reads. Deterministic overlap tests reproduced the missing read admission. Actual measurements were approximately 555 ms for run history, 64 ms for jobs, 69 ms for datasets and 2483 ms for the reviewed library. An initial 1-second read wait still failed a five-way actual burst; the final admission window is 5 seconds with at most 8 waiting readers, using the existing single physical thread. Overload is still finite and explicit.

The real backend/Chrome preparation journey reproduced the previous 10000 ms candidate-ready failure. Captured GETs returned 200 and `CANDIDATE`, revision 9, while the UI retained extracting/error state. The frontend's closed candidate keys omitted the already-published `confirmationSummary`. Its attempt keys also omitted the existing optional `repair_feedback` / `repair_context_json`; these were reproduced separately with transport tests. Separately, a terminal summary followed by a temporary detail-page failure stopped automatic recovery. Recovery counters were reset too early at summary acceptance, preventing a reliable complete-read limit.

After accepting the valid candidate, the journey exposed another legacy blocker: summary presence hid required supplement controls while the submit guard still required those values. The controls now remain visible; review requirements were not removed. Explicit values already bound to the source are not turned into missing-source questions. No trading or extraction semantics changed.

Visual review of the actual four-plan page exposed a further valid-HTTP/invalid-transport case. Its complete detail page was 2007934 UTF-8 bytes but contained 58137 JSON nodes, exceeding the browser's existing 50000-node budget. Every individual candidate was valid. Server projections now enforce that same node budget and depth 32 alongside 2 MiB, so existing adaptive paging returns the first 3 items and then the remaining item at offset 3. No threshold was raised and no original/evidence was truncated. A red/green regression covers a node-heavy page below the byte cap.

## BR-V02 — Repair and regression evidence

Read-only metadata admission serializes short overlap on the existing owner. Mutations remain nonqueued. Cancelling or timing out a waiting read prevents its later execution; active work stays owned after HTTP cancellation. Stop rejects new work and drains the physical owner. Preparation completion/cleanup waits for admitted reads. Existing SQLite errors, job admission and explicit recovery remain enforced.

History/library GET retries only `SERVICE_UNAVAILABLE` / 503, up to 3 total attempts with a 1-second abortable delay. POST/PUT, malformed successful responses and other error classes are not retried. Preparation keeps its separate 2-second work poll and up to 3 additional transient initial/terminal-detail refreshes. The counter resets only after complete summary/detail success. No retry starts AI, repeats a mutation, resumes a job or changes original intent keys.

| Check | Result |
| --- | --- |
| Full frontend | 72 files / 1105 passed |
| Type checking / production build | Passed |
| Thread, production composition, result query/API and snapshot regression | 108 passed, 1 expected POSIX-only skip on Windows |
| Preparation API/review and monitoring-loop production regression | 176 passed after the final node-budget repair |
| Service API and service contract regression | 31 passed |
| Both generated-contract checks / changed Python lint | Passed; public snapshots and generated types unchanged |
| Actual-backend Chrome preparation/review/run and unknown-cancellation journeys | 2 passed in the final run |

The complete journey retains upload/edit/retry, the original first-use 503 intent, explicit review, causal fills, source revision, cutoff, audit rows, service stop and monitor continuity. It now asserts the product's existing `POSITION_LIMIT_ONLY` mode rather than an obsolete capital balance. The same fixture still produces 1 fill, 200 shares, 504 fen fees and exact 5346 fen PnL: final value 804000 minus opening cost 401050 minus buy cost 397100 minus fees 504. Realized PnL is 0, floating PnL 5346, capital return remains unavailable. This updates the stale browser expectation, not financial behavior or the explicit-known-cash backend test.

Evidence is local under `data/verification/2026-10-18-read-reliability/`: `thread-red.log`, `thread-green.log`, `preparation-red.log`, `preparation-green.log`, `review-red.log`, `review-green.log`, `read-retry-red.log`, `read-retry-green.log`, `node-budget-red.log`, `node-budget-green.log`, `unit-accepted.log`, `backend-final.log`, `backend-preparation-final.log`, `backend-service.log`, `type-check.log`, `build-final.log` and `budget-accepted-browser.log`. Baseline/diagnostic browser captures preserve the initial valid-response rejection. Intermediate runs also preserve the hidden-control and stale-capital failures. Existing Starlette/httpx deprecation warnings remain.

## BR-V03 — Actual service and four-plan reads

The actual service at `http://127.0.0.1:8765` was drained and restarted only after verifying no authorized or unfinished jobs. Its retained run `9050185da63d7961aa29228542fa024d127ac4d754af10e3066cbc26e09abeb2` and original reports were not rewritten or replayed. Stock 002240.SZ with coverage end 2026-10-09 still returned 4 records.

Twenty rounds each read runs, unfinished jobs, datasets, the reviewed library and an actual preparation concurrently. All 100 HTTP responses were 200; each run page retained 4 matching rows. This uses direct HTTP reads without test-script retry. A subsequent browser check loaded `cohort-plan-20261018-4-v6`, including both revision-9 item pages at offsets 0 and 3, and displayed reviewed/frozen progress without a residual read error. All 3 preparation reads returned 200; no runtime error or browser write occurred. Desktop screenshots were inspected.

Evidence: `actual-read-checks.json` combines the completed burst evidence from `actual-read-failure.json` with the subsequent successful preparation check; `actual-preparation-accepted.log`, `actual-records.png` and `actual-preparation.png` record the UI. The first combined helper finished all 100 reads but checked progress before network completion using a 5000 ms visibility wait. A later screenshot still showed a detail-read error despite HTTP 200, leading to the node-budget repair. The final check explicitly waited for network completion and rejected residual errors. This is reported as separate checks, not one completely successful helper invocation. Actual raw projections and diagnosis remain local and ignored.

## BR-V04 — Retained boundaries

An earlier restart entered the existing degraded-initialization path; direct metadata diagnosis passed in 0.185 seconds, and the existing explicit preparation-repair control restored readability without authorizing history. Another cold first-use read returned 503 before readiness and left the old page on an error, motivating the final bounded GET retry. A browser navigation attempted before the restarted listener existed also failed to connect. These observations are retained, not counted as successful reads. Initialization watchdogs and explicit repair are preserved; genuine degradation is not automatically repaired or hidden.

The repair does not promise that a stopped service, sustained load exceeding 8 waiting reads/5 seconds, SQLite locks, provider failures or invalid responses will never fail. Persistent failures remain visible. The whole historical browser suite, broad navigation-abort request audits, full capacity certification and new actual-source AI/replay were not rerun or declared passing. The previous preparation-progress blocker is now covered by the successful full journey; unrelated limitations in [SC-V04](2026-10-18-compact-backtest-service.md#sc-v04--remaining-verification-limits) and the [functional acceptance record](2026-10-18-backtest-functional-acceptance.md) retain their stated scope. No credentials or local generated evidence are committed.
