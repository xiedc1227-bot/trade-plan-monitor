# Business step 4: offline status and page gate

## Status and fixed scope

**COMPLETE within the approved business step 4 offline scope. C4 CLOSED.** Backend/frontend source, real Chrome evidence and paired closure review are independently approved; the final frozen full regression passed. Final frozen backend source/test HEAD: `0f1df66d20cdc52bc542cd69052b2995c1bfe614`. Production recovery source remains the approved `2775f2b` candidate. First full backend HEAD: `d5e045c234ca8b91aefe3c41f472e0147e1b49e1`. Constructor-bypassing fixture alignment is committed as `6b35a1a`; the reviewed frontend is committed as `3589186`. Backend source, collected tests and scripts stayed unchanged throughout the final full run. The exact tested browser fixture/specs and retained evidence are committed as `1747a9e`; their commit changes no tested backend source or collected tests.

The scope is RR002, RR015–RR019 and business step 4/C4 in the approved offline environment. Default production construction and installed assets retain version `1`. Version `2` requires explicit composition/app opt-in and its separate preview build. RR020, step 5/C5, complete A01–A14 release acceptance and live operation remain separate.

All evidence uses temporary SQLite, fake SDK/HTTP/channel boundaries and controlled clocks. No live provider, real LLM, external notification, user-database migration, push or deployment was performed. Configuration replacement still requires safe stop → manual edit → a new process; this work adds no hot reload.

## Implemented boundaries

| Gate | Concrete evidence and preserved behavior |
| --- | --- |
| RR015 / A11 | Actual owner startup, local reconciliation, acquisition, validation/persistence and per-plan commit report bounded completed units. Reads, durable owner heartbeat, socket frames and raw provider success do not report progress. Monotonic overdue work remains `STALLED` until actual completion; physical cleanup precedes `STOPPED`. Local 30-second wakes retain the already selected market deadline. |
| RR016 / A06, A12 | Both plan families read their own committed storage. Missing first results are local `UNAVAILABLE` entries; identity-valid historical results are `CACHED`. Six status GETs and heartbeat reads perform zero SQL writes. Completion proof binds generation, configuration, active identity, exact target and actual consumed inputs. |
| RR016 / D5 | Current reminder eligibility remains backend-owned and rule-specific. Intraday expiry uses the original receipt deadline, including exact expiry equality. State-risk validity keeps its existing classifier and recovery barrier. An `ONCE_ALREADY_EMITTED` R2 retains the original R1 event/hash/evaluation date; cached results never acquire eligibility. |
| RR017 | Exact header `X-Monitor-Contract-Version: 2` protects six GETs and ten POSTs before request-body parsing/service execution. Duplicate, comma-separated, missing and noncanonical versions fail safely. Separate OpenAPI/types and build manifest preserve default version `1`. Committed event payloads remain schema version `1`; v2 heartbeat carries the delivered replay cursor and honest owner status. |
| RR018 | Transport state is distinct from business readiness. Connection/snapshot/silence deadlines are 20/20/40 seconds. Eligibility timers use backend observation/deadline minus complete monotonic request elapsed time; they only withdraw presentation. Epoch, generation, cursor and activation fences reject late results. Every protected command performs a validated same-origin health preflight. |
| RR019 | Dashboard, system and symbol pages show cause, retry/reconsideration time and per-scope progress. Global lifecycle/fault loss withdraws current presentation. A blocked optional index or waiting plan cannot authorize or suppress an unrelated plan. Existing bars/events, charts, positions and command pages retain their endpoints. |

One index snapshot can consume three bounded controller executions. Its deadline is frozen at launch with the actual maximum budget: `3 × 3 × (15 seconds admission + 15 seconds physical wait) + 30 seconds validation = 300 seconds`. This is a single validated immutable snapshot, not an entire index batch or extra timeout grace. At monotonic 290 seconds, a completed sibling cannot extend another snapshot's original 300-second deadline; 301 seconds is `STALLED`. Raw stages do not touch progress. A valid late snapshot may restore progress through actual completion.

A controlled retry disposition may complete local progress only for `TIMEOUT`, `TRANSIENT`, `RATE_LIMITED` or `BLOCKED_PERMISSION` with an actually installed `next_retry_at`. This does not release a timed-out physical worker. Unknown failures and cancellation retain unfinished work; stop still awaits the real controller drain.

## Review findings and corrections

Independent `gpt-6-astra` / `xhigh` source review approved the backend candidate at the fixed HEAD above and the current frontend candidate, with no remaining P1/P2 in the reviewed scope. Bounded implementation and independent reader work followed the existing task model allocation. The review identified and verified these material corrections:

- Official-close input proof includes the actual prior daily history plus `daily_indicator_snapshot.source_bar`. The maximum valid set is 500 prior bars plus the current bar, 501 total. Successful removal of a pending-close obligation preserves a matching current-generation `OFFICIAL_CLOSE` proof; a new applicable target, configuration or identity revokes it.
- Retained reminder history has no artificial 256-row business limit. A real `DATE_RANGE`/`EACH_QUALIFYING_BAR` risk plan committed 257 reminders across six trading days. Reading the current rule uses its activation/rule/action source, validates the original intent, and remains read-only. Legacy intraday sources use exact intent identity; persistent risk separately considers the three risk stages and keeps the original classifier.
- A local progress wake no longer skips the market unit selected before sleep when the clock crosses its deadline.
- Lifecycle `STOPPING` and root runtime faults withdraw frontend eligibility even when the coordinator still has work. Strict frontend validation matches the backend's lifecycle, unique-plan-symbol and explicit-current-target constraints.
- An already disconnected socket does not raise a second transport exception during failure cleanup; failure still closes with code `1011` and never emits a healthy heartbeat.
- History responses compare validated equivalent Shanghai timestamps instead of requiring identical fractional-second formatting, and accept the same UUID versions `[1-5]` as `SymbolEventView`. Real one-minute/five-minute history and the original R1 event are retained.

The real Chrome journey exposed a recovery gap: source minutes could become complete while a missing five-minute bar was never materialized. The next real result then lacked `ROLLING_VOLUME_WINDOW` and correctly remained `CACHED`. The approved correction materializes only validated complete frozen buckets through the actual stock owner task, also when source minutes already exist with zero provider requests. Partial/session-crossing buckets and generation/configuration/activation/cancellation changes cannot write. The missed target acquires no evaluation, alert, eligibility or delivery row; only a later real market duty restores a complete proof and `CURRENT`. Two actual owner-entry cases were RED against the old methods and GREEN after correction. Final Chrome acceptance, the frozen full regression and paired closure review passed.

## Verification results

These are separate overlapping runs, not counts to add together.

| Verification | Actual result |
| --- | --- |
| Independent backend final combination | 151 passed, 1 existing Starlette warning, 26.39 seconds; progress, owner, real pipeline, commit observer, composition, official close, projection, WebSocket and negotiation |
| Default API/OpenAPI/WebSocket/composition regression | 206 passed, 1 existing Starlette warning, 27.82 seconds |
| WebSocket failure-cleanup increment and adjacent regression | 27 passed, 1 existing Starlette warning, 5.79 seconds; independent new failure-cleanup test also passed |
| Independent frontend status/command/deadline/UI validation | 124 tests passed; separate isolated-build verification 2 tests passed; 126 distinct tests total |
| Independent history/parser/UI increment | 62 passed across symbols, validators, UI and route-read tests |
| Independent recovered rolling-window increment | 7 new tests plus 4 adjacent tests passed, 11 distinct; actual owner entry, complete history, no replay, partial/session and identity/cancellation fences |
| Full frontend unit suite and type check | 56 files / 807 tests passed; type check and isolated preview build passed; final Chrome acceptance passed |
| First full backend offline regression | Fixed `d5e045c`: 5910 passed, 3 failed, 1 skipped, 4 deselected, 1 existing warning, 1437.61 seconds; not accepted as a pass |
| Test-fixture alignment and adjacent regression | 67 passed, 47.89 seconds; two constructor-bypassing fixtures initialize the new optional progress fields to `None`, with all existing assertions retained |
| Second full backend offline regression | Fixed `2775f2b`: 5915 passed, 5 failed, 1 skipped, 4 deselected, 1 existing warning, 1169.90 seconds; not accepted as a pass |
| Exact derived-history fixture alignment | Implementation combination: 46 passed, 1 existing warning, 45.89 seconds; independent complete two-file run: 39 passed, 1 existing warning, 14.69 seconds |
| Final full backend offline regression | Fixed `0f1df66d20cdc52bc542cd69052b2995c1bfe614`: 5920 passed, 1 skipped, 4 deselected, 1 existing warning, 1140.87 seconds |
| Ruff, whitespace and generated contracts | Passed after final full run; default version `1` and separate version `2` snapshots/types are current; tested backend paths stayed unchanged |
| Actual Chrome journeys | 2 passed (2.6m), project `chrome`; raw JSON, exact source/test hashes and eight screenshots independently approved |
| Bilingual parity and final C4 review | Approved: matching structure, stable IDs, inline contracts, commands, thresholds, evidence mapping and scope boundaries; C4 closed only for this offline scope |

Backend commands from the project root:

```text
.venv/Scripts/python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short
.venv/Scripts/python.exe -m ruff check src tests scripts
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check --monitor-contract-version 2
git diff --check
```

Frontend commands from `web/`:

```text
npm run test -- --run
npm run type-check
npm run build:runtime-status-preview
npm run test:e2e -- runtime-status-sqlite.spec.ts runtime-status-old-server.spec.ts --project=chrome
```

The full offline command retains the approved S3 heavy-backtest exclusion and deselects tests marked `live`. The retained Windows skip is `test_cursor_key_rejects_foreign_posix_owner_before_use`, requiring POSIX ownership semantics. The existing Starlette/httpx deprecation remains visible; neither is a new relaxation.

The first full run's failures were the two parameters of `test_completed_close_pending_clear_without_health_event_still_requires_commit_admission` and `test_missing_current_calendar_has_a_distinct_local_category`. Their fixtures bypass the production constructors. Only initialization of `_progress_unit` and `_status_progress_owner` was added; no production fallback, skipped case or weaker assertion was introduced.

The second full run found four A06 preparation assertions that treated derived five-minute history as prohibited writes, and one complete-prefix fixture that seeded only source minutes. The approved test-only alignment independently recomputes every new complete frozen bucket and compares its exact stored fields, retains all previous history rows and keeps every other business table unchanged. The complete-prefix fixture seeds six canonical complete bars in its original transaction; its `READY`, 30-second wake and zero-provider assertions remain unchanged. The corrected test-only commit is the final frozen HEAD above; no production change was made for these failures.

## Browser acceptance and retained limits

The Chrome fixture starts with no active plan or inventory. The journey uses ordinary UI extraction through a fake HTTP transport, human review, activation and inventory commands, then actual scheduler/provider/SQLite evaluation. Inventory submission is accepted as evidence only after its real POST response is `200`; an epoch-cancelled zero-POST attempt is not a save. The explicit risk tape keeps the risk condition true after R1 so R2 suppression can prove source preservation rather than conceal a resolved risk.

The mixed-family control installs a real legacy plan through domain repositories, supplies valid reference facts and withholds its minutes. The cutoff control freezes actual SDK minute output; it does not replace status JSON. The stall control holds an actual owned operation beyond its frozen deadline while compatible transport heartbeats continue, then releases the operation for genuine completion. The production heartbeat cadence remains 20 seconds; only the isolated fixture observes at 0.2 seconds.

The final run's [selected original observations and receipts](assets/s4-final/browser-summary.json) retain the actual scope, progress, eligibility, source, request and error fields. This file also records exact frontend/test SHA256 values and the isolated paths containing complete raw JSON and server logs.

| Controlled Shanghai time on 2026-09-14 | Actual backend and page outcome |
| --- | --- |
| 10:20:15 → 10:25:15 | R2 `ONCE_ALREADY_EMITTED` retains valid R1 risk and the complete original source; R2 result hash differs |
| 10:30:15 | Explicit `003043.SZ` is `CURRENT`/`READY`; legacy `600000.SH` is `RECOVERING`/`UNAVAILABLE` |
| 10:35:15 | `RECOVERING`/`CACHED` result 10:30; unknown progress counts, risk false, original source time 10:20 |
| 10:36:15 | `WAITING`/`CACHED` result 10:30, risk false; history repair does not replay the missed result |
| 10:40:15 | Real five-minute duty: `CURRENT` result 10:40, `READY` progress 3/3, R1 risk true |
| 10:41:01, held duty | Transport `LIVE`, lifecycle `RUNNING`, coordinator `STALLED`, mode `BLOCKED`; `CACHED` result 10:40, risk false; `lastProgressAt` remains 10:40:45 across later socket observations |
| 10:41:01, release | Coordinator `SCHEDULED`; plan `RECOVERING`/`CACHED` result 10:40, risk false |
| 10:41:15 | Real minute duty restores the matching proof: `CURRENT` result 10:40, `READY` progress 3/3, R1 risk true, no replayed 10:40 evaluation |
| 10:45:15 | New real five-minute duty: `CURRENT` result 10:45, `READY` progress 3/3, R1 risk true |

R1 remains event `d0277a64-c054-57d7-9dc3-7d79c89a4190`, result hash `4186b620f5fe44808cb3d7e32001f602bc97e14dc0a5c6d2ad4fcb7965e08a32`, evaluated at 10:20:15 with cutoff 10:20:00. The stall selected a real maintenance duty at 10:40:45. After release at 10:41:01, the fixture first advances to 10:41:15 so fake SDK minutes match the selected real duties. Direct one-minute jumps from 10:41:01 had skipped required source minutes; the observed later repair correctly did not replay the missed five-minute result. Production scheduling and `CURRENT` requirements were not relaxed.

Dashboard layout passes at 320/768/1024/1440 pixels without horizontal overflow. At 1440 pixels, dashboard axe violations are zero for the selected WCAG 2.1 A/AA tags; this does not certify every page or width. Actual system, symbol one-minute/five-minute history, original event and deep-command pages were exercised. Eight actual screenshots are retained in `assets/s4-final/`, including [320 pixels](assets/s4-final/s4-v2-320.png), [stalled](assets/s4-final/s4-v2-stalled.png), [restored](assets/s4-final/s4-v2-last-page.png) and [old-server command](assets/s4-final/s4-v2-old-server-command.png).

The final v2 run recorded 55 version-2 sockets and zero raw console errors, failed HTTP responses/503, diagnostic errors, uncaught page errors or external requests. The old-server deep inventory attempt recorded six GETs, zero POSTs and zero console/page/external errors; its health response had no version-2 header. Logs were retained. The final run did not execute the guarded 503 classification branch; earlier failed exploratory runs are not described as zero-error acceptance. Both isolated servers shut down normally. The final frozen backend regression and paired report review passed; C4 is closed within this scope.

After this gate, default enablement and full process/release acceptance still belong to RR020 and step 5. No statement here certifies real provider permissions, OS-level multi-instance exclusion or external exactly-once delivery.
