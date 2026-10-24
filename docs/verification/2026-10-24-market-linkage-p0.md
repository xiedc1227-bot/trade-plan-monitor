# Market linkage P0: implementation verification

## MLV01 — Scope and status

The user approved MLP-D01–MLP-D06 and ordered P0 implementation on 2026-10-24; the later instruction to use official quantity rules is implemented in QP06. Baseline: `c7378a4`, branch `main`. All tasks MLP-T01–MLP-T19 and checkpoints MLP-C01–MLP-C07 are complete and accepted locally. Full-regression failures are resolved with exact-case and related-suite rechecks recorded below. This acceptance covers local implementation, not deployment or live-provider certification.

The existing `/plans` workflow now accepts strict Schema 6 daily linked BUY/TACTICAL plans, complete source-bound policies and Q0. Shared pure policies classify the index, compare aligned stock/index strength, select S0/S1/S2 and compute a legal whole quantity. The real runtime persists immutable decisions; source corrections invalidate reads, completion proofs, sends and execution. Both research and monitor-loop replay consume frozen inputs. Existing Schema 1–5 serialization, independent reminders, CORE/T+1 accounting and explicit simulation remain covered by regression checks.

[Tasks](../../tasks/market-linkage-p0.md) · [contract inventory](../specifications/monitoring/CONTRACT-market-linkage-p0.md) · [operations](../operations/market-linkage-p0.md).

## MLV02 — Stage acceptance evidence

| Checkpoint | Tasks | Evidence and result |
| --- | --- | --- |
| MLP-C01 | MLP-T01–MLP-T03 | Strict linked/fixed unions, required nullable draft fields, source-defined parameters, bounded expanded trees, exact old codecs/hashes, dated index low excluding D. `test_market_linkage_contract.py`, existing domain/index tests pass. |
| MLP-C02 | MLP-T04–MLP-T06 | Priority and three-valued market predicates, strict equality, 21 aligned sessions, 5/20 returns, own-day MA20, every S1/S2 component and all six routes pass in policy suites. An isolated in-memory `<` → `<=` mutation produces 4 expected failures, proving equality tests detect the change; repository code was never mutated. |
| MLP-C03 | MLP-T07–MLP-T09 | Legal-grid enumeration, no roundup/capacity clipping, official rule dates, quantity/evidence digests, complete eight-definition source review, extraction and follow-up inheritance pass. Full source/prompt budgets remain unchanged. |
| MLP-C04 | MLP-T10–MLP-T12 | Temporary SQLite reopen, frozen quantity, atomic consumption, correction invalidation and actual production adapter/shared index acquisition pass. Combined storage/API/replay/parity and unified runtime check: 43 passed in 21.79s. |
| MLP-C05 | MLP-T13–MLP-T15 | Current-source read/send/completion fences and read-only database assertions pass. Six actual evidence routes produce identical live/frozen policy decisions. Linked historical extraction, explicit review, copied input, actual worker, job completion, report publication and reopen pass; final replay suite: 3 passed in 57.97s. Research report contains quantity 300 and next-session nonexecution/zero-trade causes. |
| MLP-C06 | MLP-T16–MLP-T18 | Both API profiles retain exact projected old schemas/routes; 28 contract checks pass in 31.25s. Frontend: 1,232 tests in 86 files pass, type-check and 949-module production build pass. Pinned Chrome: existing and linked workflows both pass (2 tests, 20.0s). |
| MLP-C07 | MLP-T19 | Full backend unit suite: 3,598 passed in 53.97s. The full non-live integration/contract/history/native/replay/browser run finished: 4,459 passed, 16 failed, 1 platform skip, 4 live cases deselected, 4,532.73s. All 16 failures pass together after repair (18.82s); related recovery/workbench/contracts: 79 passed (18.84s). Ruff, diff whitespace, 14 bilingual document pairs and generated artifact digests pass. See MLV05 for precise disposition. |

Stage runs overlap; their counts must not be added as a unique-test total. The initial contract red phase and intermediate failures were repaired before the subsequent stages. No assertion, timeout, resource budget or production limit was lowered.

## MLV03 — Reproducible commands and diagnostics

Commands run from `trade-plan-monitor/` using installed dependencies and isolated `.test-tmp/mlp-*` directories. Frontend commands use the existing pinned Chrome installation.

```powershell
.venv/Scripts/python.exe -m pytest tests/unit -m "not live" -q -p no:cacheprovider --basetemp .test-tmp/mlp-all-unit-final
.venv/Scripts/python.exe -m pytest tests/integration tests/contract tests/history tests/native tests/replay tests/browser -m "not live" -q -p no:cacheprovider --basetemp .test-tmp/mlp-all-integration
.venv/Scripts/python.exe -m pytest tests/integration/test_market_linkage_api.py tests/integration/test_backtest_service_contract.py tests/integration/test_openapi_snapshot.py -q -p no:cacheprovider --basetemp .test-tmp/mlp-api-parity
.venv/Scripts/python.exe -m pytest tests/integration/test_market_linkage_replay.py -q -p no:cacheprovider --basetemp .test-tmp/mlp-loop-final6
.venv/Scripts/python.exe -m ruff check src tests
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e -- tests/e2e/market-linkage.spec.ts tests/e2e/condition-plan.spec.ts
```

The single root pytest collection hits an existing duplicate module basename (`test_backtest_service_contract.py` in unit/integration). Running unit and all other test directories separately preserves coverage without skipping cases. Windows sandbox asyncio blocked at `socket._fallback_socketpair` / `accept`; identical isolated tests run outside that sandbox. Neither diagnostic is represented as a passing blocked run.

Intermediate corrections: schema factoring/named-type prompt outlines keep full source evidence within the existing 50,000-character budget; unsupported-version testing now uses version 7 while malformed version 6 has dedicated rejection tests; the existing review-context route is registered in the old contract allowlist under its earlier BR02 approval. The result-only BT019 database reopen check now recognizes the exact supported result/review schema without requiring optional job tables; no user database was migrated. An API test was corrected to the existing 422 validation response. Replay fixtures were corrected to bind the exact source ID, chronology and fixed job clock, preserving all authority checks.

Known harmless diagnostics: local Python launcher location warning, Starlette/httpx deprecation and an existing browser-server Windows pipe-close callback warning. Browser assertions and request/console isolation checks pass. No dependency was installed or upgraded.

## MLV04 — UI, review and release boundaries

The linked browser journey uses the built frontend and real isolated HTTP/SQLite services: extract → edit/review → save → explicitly activate → register synthetic opening inventory → confirm/freeze 300 shares → consume exactly once → display persistent P1 exception blocking → independent five-minute reminder. Final inventory is CORE 100 / TACTICAL 300, total 400. Viewports 320/768/1024/1440 have no horizontal overflow. The blocked-state screenshot was visually inspected; quantities, evidence and no extra trade action are readable.

Five-axis review covers correctness, source/authority validation, shared policy ownership, bounded acquisition/serialization and maintainability. Tests detect strict-equality mutation, stale source authority and tampered quantity hashes. Generated OpenAPI/TypeScript hashes are recorded in U-MLP; no route or dependency was added.

Both P1 exceptions stay blocked. Official quantity rules are dated `cn-equity-buy-grid-2026-07-06`; earlier dates and unsupported securities are unknown, and simulation still uses 100-share multiples. Q0 and complete S0/policy source meaning require explicit review. Provider credentials, BSE calendar/index readiness, live data certification, user database operations, deployment and manual screen-reader certification were not performed. There are no new strategy decisions awaiting the user.

Final focused hardening: the known BROKEN state reports `MARKET_BROKEN`, not a spurious missing-market reason (126 policy/runtime/parity tests pass). The real provider combines intraday/daily content into a non-monotonic revision hash; unchanged daily refetches now preserve authority while actual daily revisions invalidate it. A read-only correction check and actual next-session 300-share simulation cover this distinction; API/storage/route checks pass (25 tests, 11.29s). The final lower-revision, production adapter and actual replay worker suite passes: 39 tests in 79.70s. The full regression began before these final focused fixes; the final unit/focused/browser reruns cover those fixes.

[Inspected blocked-state screenshot](assets/2026-10-24-market-linkage-blocked.png).

Full-run repairs: the exact result/review schema check is now shared by reopening and verified additive job migration, including the post-migration table inventory. The existing exact table-set assertion now includes the already implemented `backtest_review_event`. All job, result and migration regressions pass: 83 tests in 17.30s. Backup authorization and integrity checks are retained.

The existing daily-scheduler test adapter now implements explicit linked-plan registration and asserts that unlinked plans register an empty tuple. The real SDK-normalization/scheduler chain and unified runtime pass together: 31 tests in 17.45s.

The existing capability transport assertion now includes the approved `supportedSchemaVersions: [5, 6]` and `linkedExecutionVersion: "condition-plan-v2"` fields while preserving all previous exact fields. Its complete test file passes: 6 tests in 3.59s. Shared monitor evidence regressions also pass independently: 20 tests in 45.06s.

## MLV05 — Final regression disposition

The 75-minute full run loaded modules before the final repairs. Its initial result is retained honestly; it is not described as a clean full run. The complete failure inventory was extracted from that run and executed together against the final files: **16 passed, zero failures**. The remaining full-run cases, including annual capacity/memory and large-result query/export budgets, passed. The one skip is the existing POSIX file-owner check on Windows; the four deselected cases require live services.

| Initial failures | Resolution and final evidence |
| --- | --- |
| 2 result/job schema cases | Exact result/review schema and additive migration repaired; 83 related cases pass. |
| 10 OpenAPI/TypeScript and mounted-contract cases | Approved linked schema projection and existing BR02 route inventory synchronized; 28 focused checks and all exact failed cases pass. |
| 1 daily scheduler case | Explicit linked-plan registration added to the unlinked test adapter; 31 scheduler/runtime cases pass. |
| 1 capability transport case | Exact response expectation includes the two approved fields; all 6 file cases pass. |
| 1 degraded permission cleanup case | The old assertion incorrectly waited for the supervisor to terminate. Existing SPEC-monitor-runtime requires recovery after an admitted DEGRADED owner's unexpected exit. A controlled restart boundary now proves the original error, complete cleanup, unchanged business rows and scheduled fresh-owner recovery within the original 5-second limit. Production recovery behavior is unchanged. |
| 1 workbench replay case | Stored evidence showed the historical fixture job had been pruned using wall-clock time. The fixture now uses its existing admission/job time for real retention maintenance and waits for maintenance before asserting public job/result reads. No retention rule, timeout or authority check is bypassed. Both response modes and restart reads pass. |

The last two repairs, monitor-loop contracts and supervisor regression pass together: 79 tests in 18.84s. Full failing-case recheck: 16 tests in 18.82s. Final code changes are also covered by the 3,598-unit run, 39-case runtime/production/replay run and both real browser journeys; subsequent edits affect tests and documentation only. No unresolved failing case remains.

[Initial full-run log](assets/2026-10-24-market-linkage-full-regression.log) · [all 16 repaired cases](assets/2026-10-24-market-linkage-failure-recheck.log) · [final unit log](assets/2026-10-24-market-linkage-unit.log) · [recovery and workbench log](assets/2026-10-24-market-linkage-recovery.log).

## MLV06 — Final pre-commit review and repairs

The user requested a fresh review of all P0 changes and authorized direct repairs, tests and commits. MLV01–MLV05 retain the preceding implementation's results; this section records the subsequent review. The review checked all six specifications, MLP-T01–MLP-T19, contract boundaries, modified/new implementation and acceptance tests. No strategy decision changed.

| Finding | Repair and regression evidence |
| --- | --- |
| RV01 — Unchanged stock refetch invalidated frozen signals | Separate semantic stock/confirmation content from receipt IDs/times and adjustment-as-of dates; normalize equivalent Decimal representations. Actual price/basis corrections still invalidate. A real SQLite next-session test proves unchanged evidence permits exactly 300 shares and a changed low blocks execution. |
| RV02 — Normal STAR quantity below minimum reported a P1 exception | NORMAL_TRANSITION Q0 100 / minimum 200 now returns `MARKET_QUANTITY_BELOW_MINIMUM`; only specified WEAK/BROKEN exceptions use `P1_EXCEPTION_REQUIRED`. Arithmetic and UI tests pass; QP02/operations clarify the distinction. |
| RV03 — Negated expanded definitions could match source authority | Chinese/English explicit non-adoption prefixes reject the expanded-definition binding. Both previously failing cases and positive source/review flows pass. |
| RV04 — Evidence card omitted cutoff and nested comparisons | Display the Shanghai evidence cutoff, numbered nested ALL/ANY evidence, actual operands/dates and reviewed requirements. Tests cover nested content and quantity explanations; the UI adds no execution action. |
| RV05 — Fact-only daily replay dropped a missing-basis reason | Single-plan replay now uses the existing shared dataset requirements, including OFFICIAL_DAILY_CLOSE. An S0 consisting only of REVIEWED_FACT still reports `PRICE_BASIS_UNVERIFIED`. |
| RV06 — Extraction guidance and generated description drift | All three prompt builders consistently select condition-plan-v1/v2. Regenerated both OpenAPI snapshots after correcting the linked model description; TypeScript content is unchanged from MLV05. U-MLP records current hashes. |
| RV07 — Reminder confirmation boundaries and browser fixture | A valid omitted `acknowledgedAt` now behaves like null in the button handler; both forms have regression tests. Separately, browser diagnostics proved the fixture lacked its V2 event stream: reconnect invalidation cancelled command preflight. The fixture now uses the real `RuntimeStatusEventStream`, and the journey requires a healthy connection before confirmation. Production protocol cancellation remains unchanged. |

The substantive boundary tests first failed on the faulty code and passed after repair. An isolated in-memory inversion of the new WEAK minimum-quantity branch produced one expected failing test; repository source was not mutated. No assertion was removed, no timeout was increased, and no provider or user database was accessed. The browser acknowledgement wait is now bounded at 10 seconds within the original 120-second journey.

Final verification:

- Backend unit suite: **3,599 passed**, 53.11s.
- Related integration regression: **1,057 passed / 4 failed**, 710.05s. All four were exact generated-snapshot mismatches loaded before regeneration; the complete affected contract/API suites subsequently passed **41/41**, 35.80s. No unresolved failure remains. The selection covers market_linkage, unified, monitor_loop, plan_preparation, daily_plan, extraction diagnostics, backtest jobs/results/migrations/service, OpenAPI, transport, workbench and shared index runtime.
- Frontend: **1,236 passed in 86 files**, 9.70s; type-check and 949-module production build pass.
- Real browser: original and linked journeys repeated twice, **4 passed**, 35.9s. Earlier timeout diagnostics are retained; the repaired run validates the real stream, source review, explicit activation, whole-quantity simulation, independent reminder acknowledgement and responsive layouts.
- Ruff, generated-artifact checks, whitespace checks and **14 bilingual document pairs** (section IDs and local links) pass. No dependency, route or production resource budget changed.

Counts overlap and must not be added as unique cases. The earlier 75-minute run remains the evidence for unrelated annual capacity/memory and export coverage; it was not rerun or relabeled as a new clean full run. P1 exceptions, live-provider certification and deployment remain outside this acceptance.

[Review unit log](assets/2026-10-24-market-linkage-review-unit.log) · [integration log](assets/2026-10-24-market-linkage-review-integration.log) · [contract recheck](assets/2026-10-24-market-linkage-review-contract.log) · [frontend log](assets/2026-10-24-market-linkage-review-web-final.log) · [accepted browser repeats](assets/2026-10-24-market-linkage-review-browser-accepted.log) · [browser diagnostic](assets/2026-10-24-market-linkage-review-ack-state.log) · [mutation experiment](assets/2026-10-24-market-linkage-review-mutation.log).

[Final inspected evidence card](assets/2026-10-24-market-linkage-review-blocked.png): cutoff, full-quantity receipt and persistent exception block are readable.

Saved text logs normalize trailing whitespace only; failure details and outcomes remain intact.
