# Original fourth stage: runtime recovery final offline gate

## Status and scope

**OFFLINE_IMPLEMENTATION_COMPLETE.** This report records the remaining integration, verification and documentation work within the original four-stage refactor. It adds no fifth stage or trading rule. Base HEAD: `e09c3ea30b5ce0c32dea4ec6734ded3aebf45b26`; frozen final backend HEAD: `185263aa5d78065c40ffc3287023d35faa16cbed`. The complete passing browser HEAD is `d4db557b19aeda20c034db09a8e151193f0476e0`; the subsequent change isolates two Python test fixtures and changes no production, frontend or browser input. Earlier complete browser candidates: `0e0621868d13c847e45089d904ab6aa33cdb1e23` and `a00af51555e277a50b719e3e4a4e9a9d93a9786d`. The final backend gate passed; C5 user evidence review remains pending.

Scope: approved D1–D8 / A01–A13, normal production entry and matching monitor contract version `2`, actual temporary-database process restart, existing crash/send/migration matrix, all proposal section 7 offline gates and bilingual operations documentation. D9/A14 alert-linked sale registration remains an API-unapproved follow-up; it is not implemented or included in completion claims. Existing position registration and alert-read behavior remain unchanged.

All state is temporary, provider/LLM/channel boundaries are offline, and no user database, real provider, external notification, push or deployment is used. Configuration replacement requires successful stop → manual edit → a new process. No hot reload, new dependency or new migration is introduced in this closure.

## Final integration changes

- `create_production_app` defaults to monitor contract version `2`; the ordinary CLI uses this factory. Lazy composition remains free of construction-time provider/database work, and the actual lifecycle reader is checked before startup with cleanup on failure.
- The normal frontend build and Python package contain matching v2 assets and `monitor-contract.json`. A locally built wheel was inspected and contains the version `2` manifest and HTML entry.
- Default contract generation/checking covers canonical v2 and the explicit v1 compatibility fixtures. Both snapshots retain their approved wire contracts.
- Existing v1 browser and bounded R14 diagnostic fixtures use isolated `web/dist-legacy-test` assets. Their business assertions and diagnostic budgets remain unchanged. The R14 tool requires `npm --prefix web run build:legacy-test`; this does not select assets for the normal CLI.
- Normal-entry process/session and browser restart tests exercise the installed path. Existing crash, delivery, permission, expiry and migration tests are reused rather than replaced.

## Acceptance traceability

Historical reports retain their tested revisions and limited conclusions. Their evidence is combined with the new normal-entry acceptance and the final complete regression; historical passes alone are not a new full pass.

| IDs | Evidence and retained boundary |
| --- | --- |
| A01, A02, A04, A05 / C1 | [S3 aggregate](2026-09-27-s3-final-offline-gate.md): compatible semantic import, scoped eight-operation permission recovery, durable cooldown, independent retry clocks and bounded serial calls. |
| A03, A07, A10 | [S3 aggregate](2026-09-27-s3-final-offline-gate.md), `test_anytime_runtime_recovery.py`: session targets, unknown/partial data, clock/session transitions and normal-entry sequential processes. Standby/cached display never grants current trading eligibility. |
| A06, A09 | [S3 identity/fault matrix](2026-09-27-s3-final-offline-gate.md), [S4 status gate](2026-09-30-s4-offline-status-gate.md): both plan families, required/optional dependency isolation and generation/configuration/activation fences. |
| A08 | [Missed-close kills](2026-09-27-s3-missed-close-kill-restart.md), [notification kills](2026-09-27-s3-notification-kill-restart.md), [S3 aggregate](2026-09-27-s3-final-offline-gate.md): atomic intent, commit/send interruption, uncertain receipt handling and physical stop/drain. No universal exactly-once external delivery claim. |
| A11, A12 / C4 | [S4 status gate](2026-09-30-s4-offline-status-gate.md), final normal-entry browser acceptance: authoritative status, GET/WS generation coherence, cached results, explicit compatibility rejection and matching packaged assets. |
| A13 | `test_runtime_liveness.py`, `test_runtime_plan_expiry.py`, S3 aggregate: interruption uses durable legal-owner liveness; `>120` hours expires plans, exact equality does not. Unknown history remains blocked; holdings and confirmed trades are retained. |
| Migration/rollback | `test_index_permission_scope_migration.py`, `test_runtime_recovery_storage.py`, `test_sqlite_backup.py`: interrupted additive migration rollback, downgrade refusal with retained state, WAL-inclusive backup/restore on temporary databases. |
| D9/A14 | Separate API-unapproved follow-up. No new alert-linked sale endpoint or changed sale/reminder rule. |

C2 also relies directly on [historical-close evidence tests](../../tests/integration/test_historical_close_evidence.py) (latest committed close, long-lived plan, corrupt anchor and bounded unchanged-close queries), [missed-close execution tests](../../tests/integration/test_missed_close_execution.py) (two causal closes, historical holdings, risk source time, latest applicable occurrence and stale-activation rejection), [inventory boundary tests](../../tests/integration/test_inventory_history_boundaries.py) and [inventory transaction tests](../../tests/integration/test_position_inventory_recovery_transactions.py). Their contracts are retained in [runtime-recovery](../specifications/monitoring/SPEC-runtime-recovery.md); actual continuation evidence is in [restart continuation](runtime-recovery-acceptance.md#restart-continuation-cleanup-and-health-visibility--2026-09-23) and [latest node/opening holdings](runtime-recovery-acceptance.md#latest-node-continuation-and-opening-holdings--2026-09-23). Finite invalid/incomplete historical proof still blocks only the affected plan; no new unlimited-history promise is made.

## Executed checks

Counts are overlapping runs, not additive. The complete final backend and browser suites passed on their recorded frozen inputs; the approved offline implementation is complete.

| Check | Actual result |
| --- | --- |
| Normal-entry composition and reader guards | 10 passed, 1 existing warning, 1.79 seconds; two new behavior cases first failed against the old source. |
| Adjacent default/explicit compatibility composition | 71 passed, 1 existing warning, 10.01 seconds before the final normal packaged assets were built. The later full attempt exposed three legacy test cases still resolving normal package assets; their correction and final regression are recorded separately. |
| Packaging tests | 12 passed, 1 existing warning, 1.65 seconds; real local wheel also contains manifest version `2`. |
| Default contract generator / promotion / snapshots | 25 passed, 1 existing warning, 27.38 seconds; default checks both approved contracts. |
| Preserved R14 offline diagnostics | 24 passed, 1 existing warning, 15.23 seconds. No paid diagnostic run. |
| Normal-entry session/process matrix | 6 passed, 33.69 seconds; 11 independent OS processes, five session times and missing-credential blocking. Stored plan/activation/result/reminder sources remain unchanged; GET/WS share the actual generation and heartbeat does not extend progress. |
| Reused crash/migration/expiry matrix | 51 passed, 82.17 seconds: missed-close kills, notification kills, projection migration and plan expiry. |
| Installed lunch/liveness regression | 8 passed, 4.32 seconds. |
| New normal-entry Chrome journey | 1 passed, 1.5 minutes; actual processes `57572 → 6200` exit normally, original full alert rows retained, `CURRENT → CACHED → CURRENT` and the normal 20-second WebSocket cadence verified. Two same-origin GET cancellations are retained separately from unexpected failures; no console/page/external error. |
| Full frontend unit suite | 56 files / 808 passed; type check passed. |
| Legacy browser-fixture isolation | 31 passed, 38.1 seconds; original assertions retained. |
| Normal frontend build | Passed; normal and packaged assets have 58 files each and identical manifest SHA-256 `71caaaef6a0a540c3a10fc87aa82060a071cf1d301d341a5f41275d3b1c9796d`. Both protocol manifests are `2`. |
| Complete backend `not live`, including heavy backtest acceptance | 5948 passed, 1 skipped, 4 live deselected, 1 existing warning, 3291.64 seconds, exit `0`, at `185263aa`. All 8 heavy backtest acceptance cases passed; no new exclusion or reduced threshold. [Full result and measured values](assets/rr-final/backend-final-summary.json). |
| First complete-backend attempt at `d4db557b` | Interrupted after a confirmed fixture mismatch at 33% / 2018 reported markers, one failure and one existing skip; not a full pass. A direct AI fixture reproduction failed once in 1.66 seconds; two R15 diagnostic parameters failed in 1.72 seconds for the same v1-fixture/v2-package asset mismatch. [Retained attempt and diagnosis](assets/rr-final/backend-first-interrupted-summary.json). Only test resource isolation is corrected; the full backend gate is rerun without exclusion or threshold change. |
| Legacy Python asset isolation | 3 failing cases → 9 passing tests across both entire files, 1 existing warning, 2.69 seconds. Each legacy fixture resolves a temporary package with explicit manifest `1`; original AI configuration, diagnostic and client-close assertions remain unchanged. Normal package `2` and production asset validation are unchanged. |
| First complete Chrome suite at `0e062186` | 39 passed, 4 failed across 43 tests / 18 specs, 9.6 minutes; not accepted as a pass. One legacy fixture lacks cached index history; three legacy fixtures jump past actual maintenance/market wakes. Normal production restart, normal recovery, both C4 journeys passed. Strict original assertions are retained; only the test fixture was corrected. |
| Bounded legacy fixture correction | Four original failures passed: three R13 cases in 2.0 minutes and R12 in 42.3 seconds. Cached index facts remain `BLOCKED` with no indicator facts; precise legacy wake release retains the final clock target. No production/frontend/spec assertion changed. |
| Second complete Chrome suite at `a00af515` | 42 passed, 1 failed, 9.1 minutes; not accepted as a pass. The remaining strict classifier rejected one sanitized dashboard `503` in `market-duty-10:20`; the UI withdrew risk eligibility after 57.6ms and later actual `CURRENT` / original R1 evidence passed. Its internal cause was not recorded, so it is not retroactively certified as an authority race. Test-only cause observation was added; unknown/storage failures remain unacceptable. |
| Read-failure observation guard | 4 passed, 1 existing warning, 2.48 seconds in the root verification. Real healthy, two-attempt authority-race, storage-failure and unavailable-reader paths retain identical response bytes, headers and SQL statements with/without observation. Only the exact original authority-race exception is acceptable in browser boundary phases; every `503` must match its actual request ID and withdraw action eligibility. No production reader or retry policy changed. |
| Final complete Chrome suite | 43 passed across 18 specs, 9.0 minutes, at frozen `d4db557b`; one worker, zero retries, exit `0`. |
| Final lint / contract checks | Ruff `src tests scripts` passed. The default generator verified canonical version `2` and compatibility version `1`. Complete non-live collection found 5949 selected / 5953 total tests, 4 live deselections; no backtest exclusion. |
| Final source review / bilingual parity | Passed: root reviewed normal factory/actual reader/assets, bounded fixture fixes and cause-observation guards, consolidated existing independent S3/S4 and final-scope reviews, and checked paired sections, IDs, commands and thresholds. No unresolved material finding. No new cross-model review is claimed; additional review was waived by the user. |

Completed focused and full commands (from the repository root):

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_runtime_status_composition.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_packaging.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_frontend_contract_promotion.py tests/integration/test_openapi_snapshot.py tests/integration/test_runtime_status_routes.py -q
.venv/Scripts/python.exe -m pytest tests/unit/test_r14_bounded_acceptance.py tests/integration/test_r14_offline_wiring.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_anytime_runtime_recovery.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_browser_read_diagnostics.py -q
.venv/Scripts/python.exe -m pytest tests/integration/test_configured_ai_web.py tests/integration/test_r15_extraction_diagnostics.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_missed_close_kill_restart.py tests/integration/test_s3_notification_kill_restart.py tests/integration/test_live_monitor_projection_migration.py tests/integration/test_runtime_plan_expiry.py -q
npm --prefix web run test -- --run
npm --prefix web run type-check
npm --prefix web run build
.venv/Scripts/python.exe -m ruff check src tests scripts
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
.venv/Scripts/python.exe -u -m pytest -m "not live" -v --tb=short --durations=10 -o junit_logging=system-out --junitxml=<temporary XML>
npm --prefix web run test:e2e -- --project=chrome
git diff --check
```

Final heavy-gate measurements: the ten 252-day replay samples range from 81.32 to 83.22 seconds each (limit 120); capacity working-set delta 116412416 bytes (limit 768 MiB), market/WAL 519073792 bytes (limit 512 MiB), results/WAL 184918016 bytes (limit 192 MiB), traced heap 126174567 bytes (limit 384 MiB). Maximum endpoint query p95 is 95.61ms (limit 250ms); minimum CSV throughput is 9.02 MiB/s (minimum 5). The only skip is `test_cursor_key_rejects_foreign_posix_owner_before_use`, requiring POSIX ownership semantics unavailable on Windows; the single warning is the existing Starlette/httpx deprecation. Raw samples, eight case durations and the full log are retained in [the backend result](assets/rr-final/backend-final-summary.json).

The targeted browser raw evidence is `C:/Users/xiedc/AppData/Local/Temp/tpm-r12-browser-gobvmg3k/normal-runtime-recovery.json`, SHA-256 `e39b7b7b92071ed5f62cc18f64dfea0547d9bf835faf2e2c65031df0ff43aef8`. This temporary record is separate from the final full-suite result. The final full Chrome command was `npm --prefix web run test:e2e -- --project=chrome` at the frozen HEAD: 43 passed across 18 specs, one worker and zero retries, 9.0 minutes. Full log: `C:/Users/xiedc/AppData/Local/Temp/tpm-rr020-all-chrome-d4db557b-final-20260930.log`.

The index failure was reproduced read-only using the baseline `e09c3ea` history reader, the identical v1 route and the same failing temporary database: all four exact queries returned `404`. Baseline/current reader, router and legacy trend UI are unchanged. This is a baseline read-boundary reproduction, not a full baseline-browser run. The four-case correction uses only honest unavailable past cache and the real installed wake order. R12/active/replace report zero console/external errors; the stream spec does not collect console observations, so no such zero is claimed for it.

Final persistent evidence is stored under [`assets/rr-final`](assets/rr-final/browser-gate-summary.json), including the complete passing Chrome log, both earlier failing logs and the unmodified second-run C4 record. The final normal entry uses the same temporary SQLite across processes `55224 → 80172`, both exiting normally: `CURRENT` at 10:10 → non-actionable `CACHED` after restart → actual `CURRENT` at 10:15. Its errors/external requests are empty; two actual navigation GET `net::ERR_ABORTED` cancellations remain separately recorded. The final C4 record has 54 actual v2 sockets and zero console observations, `503` responses, read diagnostics, diagnostic/page errors or external requests. At 10:45 the decision is actual `CURRENT`, while the original R1 event ID/hash/evaluation time/cutoff remain unchanged. The old server receives six GETs and zero POSTs, with no v2 health header and no recorded error/external request.

| Retained artifact | SHA-256 |
| --- | --- |
| [Browser summary](assets/rr-final/browser-gate-summary.json) | `06a469b1507211260490dab5bceeaf48a9eb4dfb02f0259a7ac40529a700ec0c` |
| [Normal restart](assets/rr-final/normal-runtime-recovery.json) | `7777e30bc98c2b7baf48a62db0c16733875032f86160503335d8d133184d9588` |
| [Final C4](assets/rr-final/runtime-status-final.json) | `d3a33e9105e6d75ca4510a2b6cddff5e49b64b8b3be217992c4b888da4943cd9` |
| [Old server](assets/rr-final/old-server-evidence.json) | `884223baa49137b94824c42971c9503b1ff48f7c884418fb8e9db68dcd2ae0b3` |
| [Read-only baseline index boundary](assets/rr-final/baseline-index-404-proof.json) | `260b1b85a7e9af51da600f3d9f3ddef85f038216e67d4600f9121c52210a864c` |
| [Complete backend result](assets/rr-final/backend-final-summary.json) | `6ecfb31289aeeed07406cdab9b22da99b993de4d56fc0f05b34a3fb498fc0992` |
| [Complete backend log](assets/rr-final/backend-final.log) | `7ad0772fc42dc2fd6b54a540d73ce4be4c8f8dbbfd3c7967d2f31c8045fecadf` |
| [Frontend source manifest](assets/rr-final/frontend-source.manifest.txt) | `4a3f15bb77b73207834b04eef4aeea0b91a98b65d0dec74b2c8eb60a2d299481` |

The frontend source manifest uses Windows native Path ordering (case insensitive), forward-slash paths plus a space and lowercase file SHA-256, joined by LF without a terminal LF. Normal/packaged assets remain identical at the recorded 58-file hash; isolated legacy assets have 44 files, protocol `1`, manifest hash `79423aa649fecb6295e288fd658d86b6fe5b119f2c802fd3d78623b975a6bc9e`. This evidence directory disables Git text conversion to retain original artifact bytes; local attributes preserve raw logs' Windows line endings and trailing spaces without changing source checks.

## Completion and handoff boundary

RR001–RR022 and C0–C4 are complete only for approved D1–D8 / A01–A13 offline delivery, based on the executed final gates and consolidated source/evidence review. C5 remains the user's completed-evidence review; it is not a remaining implementation task. Production backup, real-provider acceptance and deployment require separate authorization. Existing limited historical reports are not rewritten as unrestricted historical recovery. No OS-level concurrent-instance lock or unlimited recovery capacity is claimed.

V1d is evaluated against approved D8/A13 and `SPEC-runtime-recovery.md` sections on liveness and legacy resolution. Missing heartbeat blocks admission and uses the existing preview, fingerprint and separate confirmation for audited invalidation; corrupt/future heartbeat remains blocked for investigation. Unclassifiable old alerts retain sanitized audit without invented terminal receipts. Sweep failure logs `ALERT_SWEEP_FAILED`, preserves its cursor and retries without stopping the owner heartbeat. The old V1d suggestions for an additional alert-review workflow and a Web maintenance-status field are not approved D8/A13 or RS04 contracts, are not implemented and are not introduced into this refactor. Evidence: `test_old_alert_sweep_audits_corrupt_alert_without_losing_later_valid_one` and `test_long_outage_sweeps_receiptless_old_alert_after_transient_failure` in `test_runtime_plan_expiry.py`.
