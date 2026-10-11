# Verification: Monitoring-loop Backtest

Canonical English; Chinese review copy: [monitor-loop-backtest.zh-CN.md](monitor-loop-backtest.zh-CN.md). Updated 2026-10-09, Asia/Shanghai. The user-requested sequence of 20 tasks uses individual verification, commits and pushes; all 37 active tasks and 13 checkpoints are complete. Cancelled ML-T06/ML-T09 and ML-A07 retain historical IDs. Single-plan, one unfinished task and mutually exclusive operation constraints remain.

Current acceptance is MV18–MV46: source preparation and complete reviewed freeze, one cutoff, private monitoring loop, atomic settlement, native causal results, latest-30 retention, lazy lifecycle/service controls and frontend workflows are implemented. MV43 preserves four failed load attempts, narrow corrections and actual Windows 600/600-second measurements passing the original gates. MV44 records 58 final relevant backend checks, 935 frontend checks and 34 real Chrome journeys passing; MV45 records operation boundaries. MV46 isolates committed source for both-profile review, retains approval history and completes 69 contract checks plus exact allowlist mutation/restoration; the two former approval failures are resolved. Shared-process and measured paced-load boundaries remain, without live AI/market-provider certification, production migration or deployment. Historical checkpoint IDs and unique executed evidence are retained; superseded process narratives are summarized and are not current blockers.

## RP-V01. Offline continuity checkpoint

RP-T03 is complete and RP-C01 passes: one private session traverses reviewed versions through the shared activation transaction, retains account/risk state, closes old ordinary intents and records context mismatches without inventing trades. Independent review corrected duplicate source snapshot identities and expired-event authority. 64 focused runtime/account/cycle/report/fixture/legacy checks pass, including 10 switch cases; deliberate removal of ordinary-intent closure fails and exact bytes are restored. Ruff and diff checks pass. **3 of 20 repair tasks complete.** Next: RP-T04. End-to-end preparation, publication and UI acceptance remain pending.

The earlier MV sections describe the narrower historical delivery and are not whole-repair acceptance. RP-T01 baseline: 11 fixture / 14 fixture-plus-legacy checks; RP-T02: 65 schedule/input/fixture/legacy checks. The literal four-version run buys 100 shares for 100000 fen plus 500 commission, carries 899500 cash and 100500 cost with T+1, then sells for 120000 less 500 commission: final cash 1019000, realized P&L 19000, total fees 1000. Later source assertions of 0 or 200 shares do not overwrite the ledger; explicitly account-dependent instructions are blocked. No scripted transactions or live providers were used. v2 lifecycle events are verified; complete v2 report publication remains RP-T11.

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_plan_switch.py tests/integration/test_monitor_loop_account.py tests/integration/test_monitor_loop_cycle.py tests/unit/test_monitor_loop_report.py tests/unit/test_monitor_loop_continuity_fixture.py tests/integration/test_backtest_compatibility.py -q --basetemp=.pytest_cache/rpt03-identity-fixed
```

## RP-V05. Follow-up extraction

RP-T05 is complete: first-source extraction remains unchanged; follow-up extraction uses a distinct bounded contract containing only its source and validated past context, explicit scope/operations and non-authoritative account assertions. Independent review found and corrected cross-bucket quantity attribution and overlapping evidence. 144 extraction/provider checks pass, including 23 new follow-up cases; both account-attribution regressions failed before repair. Windows sandbox socket initialization blocked asyncio; the approved unsandboxed local fake-provider checks passed. Ruff and diff checks pass. **5 of 20 repair tasks complete.** Next: RP-T06; candidates remain unresolved until materialization and explicit review.

```text
.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_extraction.py tests/integration/test_ai_provider_contract.py -q --basetemp=.pytest_cache/rpt05-final
```

## RP-V06. Materialized source evidence

RP-T06 is complete and RP-C02 passes: deterministic full replacement and explicit add/modify/revoke/retain operations produce complete candidates and reviewable differences. Inherited fields retain original source spans, binding paths and human supplement hashes through index changes; later holdings remain comparison context. Independent review reproduced and corrected negated/hypothetical replacement and unsupported account-dependency attribution. 67 focused merge/binding/fixture/schedule checks pass, including 31 merge/binding cases and bounded evidence persistence through store restart. Narrow literal scope/dependency guards leave other wording unresolved for explicit review. Ruff and diff review pass. **6 of 20 repair tasks complete.** Next: RP-T07; worker integration and whole-chain freezing remain pending.

```text
.venv/Scripts/python.exe -m pytest tests/unit/test_plan_update_merge.py tests/unit/test_plan_update_bindings.py tests/unit/test_monitor_loop_continuity_fixture.py tests/unit/test_monitor_loop_schedule.py -q --basetemp=.pytest_cache/rpt06-durable
```

## RP-V07. Sequential preparation and cancellation

RP-T07 is complete. The user approved RP05-A01 on 2026-10-11; the two cancellation invariant regressions now pass. One owned operation processes items serially with source/base/generation fences, per-item retry budgets, explicit unknown recovery and exact edit receipts. Cancellation preserves validated predecessors and original attempt bindings, retains global exclusion until physical work ends, and rejects late completion. 169 preparation service/worker/store checks pass, including restart and real blocked fake-provider cancellation. Ruff, bilingual checks and independent diff review pass. **7 of 20 repair tasks complete.** Next: RP-T08.

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_api.py tests/integration/test_plan_preparation_worker.py tests/integration/test_plan_preparation_store.py -q --basetemp=.pytest_cache/rpt07-reviewed-cancel
```

## MV01. Implemented boundary

Historical ML-T30–ML-T32 established inert startup, shared guarded initialization, separate metadata/execution capabilities, bounded owned threads and drain-before-replacement. Cancelled waiters do not cancel physical work; slow initialization returns 503 with `Retry-After`. The then-pending recovery, controls and UI work is completed in MV18–MV46. Current behavior and reproduction steps are maintained in [ML-O01–ML-O09](../operations/monitor-loop-backtest.md).

## MV02. Executed checks

Initial partial checks used fake providers and isolated temporary stores, without live monitoring or paid requests. Their intermediate counts are superseded by the final executed acceptance in MV43/MV44/MV46; reproducible commands are in ML-O07. Original step-by-step logs remain in Git history.

## MV03. Existing approval mismatch

The historical OpenAPI approval test failed against actual SHA-256 `8da41a7d8d06f6a4e114570b52e88c894d0f817de365dc062bee08b28989e833` while paired approval records contained `4d1ff1d58e37b764aa057415cee1418298bc05bedbd360fbec60202f1f7cd255`. This was not fixed by silently changing approvals: MV12 and final MV46 record concrete reviewed interfaces and retained approval history. These historical hashes are not current interface authority.

## MV04. Remaining evidence and decisions

The historical expired-claim, pacing, control, business/UI and load gaps are resolved by MV18–MV46. Same-process native crash, memory exhaustion, disk contention and non-cooperative-thread limits remain accepted boundaries. Paid AI/provider certification and production deployment are outside this acceptance.

## MV05. AI decision and local sync-pacing scope

The 2026-10-07 scope decision retains one active AI extraction, idempotency receipts and sequential preparation batches. Historical sync retains one active task and local 1.25-second request-start pacing with cooperative cancellation. No global quota pool, reserved capacity, cross-business scheduler, shared cooldown, adaptive allocator or provider-isolation guarantee was introduced. Actual entitlement and shared quota scope are not inferred. Implemented limits are maintained in ML-O06.

## MV06. Export compatibility and concurrency scope

The 2026-10-07 decision preserves legacy `SUMMARY_JSON`/`FILLS_CSV` contracts, bytes, chunking and disconnect behavior without new loop exports, bulk packaging, export jobs or scheduling. The former blanket preparation/replay mutex proposal was withdrawn; the later single-unfinished-task admission and operation boundaries in MV45 govern the implemented workflow. Immutable freeze prerequisites and revision guards remain; no hard resource-isolation guarantee is claimed.

## MV07. Cancelled disk/log budgets and latest-30 retention

The 2026-10-07 decision cancelled new disk/log quotas and free-space admission thresholds while retaining ordinary storage-error handling and existing guards. Latest-30 retention is one total cap including pinned runs; bounded publication cleanup protects active jobs, shared inputs and owned files. Its final implementation and acceptance replace the initial pending status; see ML-O06 and MV18–MV46. No new cleanup scheduler was added.

## MV08. Existing-only storage protection and pressure assessment

Retain independent default databases, path normalization and existing storage-domain rejection of live-monitor or mixed tables. No new deep Windows file-identity, junction/hard-link or cross-file alias framework was authorized. Existing finite event, queue, thread and read-batch bounds remain; actual Windows load measurements are in MV43, without exhaustive alias or hard CPU/memory isolation claims.

## MV09. Adopted finite-work scope and remaining safeguards

The 2026-10-07 decision retained existing finite-work safeguards, cooperative cancellation and offline load checks, and cancelled dynamic CPU/memory pressure controllers, sampled admission thresholds and generic resource-control modules. Subsequent recovery, sync pacing, latest-30 retention and service/UI acceptance are complete in MV18–MV46. ML-O06 and the formal ML17 scope retain the authorized boundaries.

## MV10. Complete acceptance gap register

The 2026-10-07 register originally counted 39 task slices: 3 complete, 1 partial and 35 pending. That historical gap list is superseded by the final 37 active tasks and 13 completed checkpoints; cancelled ML-T06/ML-T09 and ML-A07 keep their IDs. MV18–MV46 preserve the executed business, UI, fault/load and contract evidence. No paid-provider, live-notification, broker-execution, production-migration or deployment gate was added.

## MV11. Startup-decoupling acceptance only

The user clarified that the requested acceptance is startup decoupling, excluding monitoring-loop business redesign. MV10 is the whole-delivery register and must not be used as the prerequisite list for this narrower acceptance. ML-T30–ML-T32/ML-C11 are implemented with passing automated evidence in MV02. No runtime source change followed those checks; subsequent scope edits are documentation only.

**Result: PASS for startup-decoupling acceptance.** All three fixed scenarios were executed on 2026-10-07, Asia/Shanghai, using real Windows Uvicorn processes, `create_production_app`, the actual packaged Vue SPA, real loopback HTTP and the Codex In-app Browser. Runtime source was unchanged. The evidence assertions passed; [summary.json](evidence/2026-10-07-startup-decoupling/summary.json) records results and [commands.json](evidence/2026-10-07-startup-decoupling/commands.json) records launch/environment details.

| Fixed acceptance scenario | Existing automated evidence | Actual-environment result |
|---|---|---|
| Normal startup/restart without backtest use | Startup registers an unused manager; routes/schema remain mounted; no backtest factory invocation; unused shutdown remains inert. The production factory remains an inert closure. | **PASS.** Server PIDs 20760 and 37240 on `127.0.0.1:58537`; restart reused the isolated monitor store. `/`, `/system`, health and dashboard returned 200. Real browser rendered monitoring/system pages. Backtest remained `NOT_INITIALIZED`, with no factory/start/store/key/coordinator call or backtest thread, no backtest files and no warm-up. Evidence: `s1-start/` and `s1-restart/` below the evidence root. |
| Unusable backtest-only resource at startup | A deliberately failing backtest factory is never called during startup; the monitor lifecycle remains started. | **PASS.** Server PID 25668 on `127.0.0.1:58538`, with a deliberately truncated 16-byte backtest cursor key (required length: 32 bytes; owner-only ACL preserved). Startup and monitor page/API access succeeded. Backtest stayed `NOT_INITIALIZED`; its factory/key reader was unused and neither backtest database existed. Evidence: `s2-corrupt/unused-observation.json`, `corrupt-resource.json`, `http.jsonl` and browser files. |
| First backtest use fails locally | Repeated actual HTTP dataset requests return scoped 503 without leaking internal paths; the failure is cached and monitoring is not stopped; normal lifecycle cleanup still occurs. | **PASS.** On the already running damaged-resource server, the first `GET /api/v1/backtest-datasets` reached the real production factory/key reader and failed on key length. Four explicit HTTP probes plus browser reads returned local 503, `SERVICE_UNAVAILABLE`, with no internal path/cause or `Retry-After`. Factory invocation remained exactly one through a 78.279-second cache observation. Backtest was `DEGRADED`, outstanding work 0; monitor health/dashboard continued returning 200, and browser monitoring/system pages remained readable with a connected transport. Normal shutdown removed runtime bindings and the owned backtest thread. Evidence: `s3-first-use/` and `s2-corrupt/lifecycle.jsonl`. |

### MV11.1 Environment and executed commands

Repository/run directory: `D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor`. Python 3.14.7, Uvicorn 0.52.3, FastAPI 0.141.1, Vite 8.2.1. `npm run build` from `web/` passed (854 modules); production-mounted asset SHA-256 identities are in each `lifecycle.jsonl`. The default monitor, plan and AI compositions were used with temporary `{}` configuration and an empty temporary monitor store. Backtest defaults were redirected into the disposable process working directory. No production factory or lifecycle result was replaced. A profiler/audit hook observed production calls and rejected non-loopback socket connections; rejected external attempts were also zero.

The deliberate absence of Tushare credentials yields monitor health `DEGRADED`, read-only, `TUSHARE_NOT_CONFIGURED`, database/WAL `READY`, and empty/no-data UI. This proves local startup/read availability and isolation; it does not certify healthy live market monitoring or load capacity. Browser warning/error captures were empty. Index-series 404 responses reflect missing offline data. `BacktestThreadOwner.__init__` is an inert ownership object, not an executor/thread. Profiler `MonitorWebComposition.start/stop` call counts include coroutine resumptions and do not count lifecycle instances.

The three server commands below were launched with PowerShell `Start-Process -WindowStyle Hidden`, repository working directory and per-scenario stdout/stderr redirection. Each `--root` was disposable and marker-checked. Scenario 3 reused the already running scenario-2 process; it did not create a fake read service.

```powershell
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --serve --root data/mv11-normal --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s1-start --port 58537
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --serve --root data/mv11-normal --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s1-restart --port 58537
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --serve --corrupt-key --root data/mv11-corrupt --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s2-corrupt --port 58538
```

HTTP probes used real sockets and `X-Monitor-Contract-Version: 2`, matching the frontend. Exact probe invocations (repeated cache checks used the same arguments with the recorded `--label`):

```powershell
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --probe /api/v1/health /api/v1/dashboard /api/v1/runtime-status --label normal-start-contract-v2 --root data/mv11-normal --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s1-start --port 58537
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --probe / /system /api/v1/health /api/v1/dashboard --label normal-restart --root data/mv11-normal --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s1-restart --port 58537
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --probe / /system /api/v1/health /api/v1/dashboard --label corrupt-unused-start --root data/mv11-corrupt --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s2-corrupt --port 58538
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --probe /api/v1/backtest-datasets /api/v1/backtest-datasets /api/v1/health /api/v1/dashboard --label first-use-controlled-key-failure --root data/mv11-corrupt --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s3-first-use --port 58538
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --probe /api/v1/backtest-datasets /api/v1/health /api/v1/dashboard --label cached-failure-later-monitor-still-readable --root data/mv11-corrupt --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s3-first-use --port 58538
.venv/Scripts/python.exe scripts/verify_backtest_startup_decoupling.py --probe /api/v1/backtest-datasets /api/v1/health /api/v1/dashboard --label final-cache-and-monitor-check --root data/mv11-corrupt --evidence docs/verification/evidence/2026-10-07-startup-decoupling/s3-first-use --port 58538
```

Initial health/dashboard probes without the required version header returned 409 and were corrected; exploratory `/api/v1/system` and `/api/v1/runtime-status` returned 404 because those paths are not mounted. These setup observations were not product failures; the compacted `s1-start/http.jsonl` retains the successful acceptance responses. Fault setup initially tried an invalid key through the length-validating creator and exited before server launch; the redundant fixture log was removed during commit preparation. The corrected fixture creates test material with the secure writer, then truncates it. [Injected cause evidence](evidence/2026-10-07-startup-decoupling/s3-first-use/injected-failure-cause.json) confirms `ValueError: cursor key must contain exactly 32 bytes`.

### MV11.2 Evidence, cleanup and fixed blocker register

Evidence root: [evidence/2026-10-07-startup-decoupling/](evidence/2026-10-07-startup-decoupling/summary.json). Retained attachments include launch/results summaries, actual call/asset/lifecycle records, acceptance HTTP responses, unused-resource and final-cache snapshots, controlled fault evidence and representative browser screenshots. Duplicate PID/status/hash inventories, stdout/stderr, AX text, empty console captures and transitional snapshots were removed during commit preparation. Scenario-3 browser evidence includes the [local error page](evidence/2026-10-07-startup-decoupling/s3-first-use/backtest-full-page.png), [monitor after failure](evidence/2026-10-07-startup-decoupling/s3-first-use/monitor-after-failure.png) and [system after failure](evidence/2026-10-07-startup-decoupling/s3-first-use/system-after-failure.png).

The observer samples every 0.5 seconds. A request-adjacent sample contained the previous, pre-initialization state (`NOT_INITIALIZED`, factory 0); this redundant transitional snapshot was removed. The scenario-3 state conclusion uses the retained `final-cache-observation.json` (`DEGRADED`, factory 1), timestamped HTTP 503 and browser evidence.

Each server was stopped with the script's `--stop` mode using its matching `--root`, `--evidence` and `--port`; this only signals the task-owned server's normal Uvicorn shutdown. All three completed application shutdown and exited without forced process termination. Durations: 18.043 seconds at initial shutdown with a browser WebSocket present, 0.152 seconds after restart, 1.123 seconds after failed backtest use. The initial wait was Uvicorn connection/background-task drain, not backtest initialization/cleanup; no shutdown latency threshold is claimed. Task-created browser tabs 1/2/3 were closed. Both ports have no listener; all recorded server/launcher PIDs have exited. Only marker-checked `data/mv11-normal` and `data/mv11-corrupt` were removed after verifying their absolute paths; the retained summary records port closure and source preservation. Essential evidence and the reusable script remain. Source/research hash checks matched all 240 preserved files; no formal databases, account configuration or Shengxin research files were changed. No paid AI/market call, real notification, commit, push or deployment occurred.

| Register item | Status and disposition |
|---|---|
| MV11-B01 Actual startup-decoupling blockers | **None found.** All three required scenarios passed. The deliberately corrupt resource is the controlled fault, not a new production defect. No runtime repair is required by this acceptance. |
| MV11-O01 Offline environment and probe/fixture observations | `DEGRADED`/no market data, contract-header 409, unmounted-path 404, rejected invalid-key fixture setup and WebSocket shutdown drain are recorded above; they do not fail startup isolation. |
| MV11-O02 Separate existing work | ML-T33 historical-slot decisions, ML-T34 sync pacing, latest-30 result cleanup, service controls/UI, loop preparation/replay/results, full Windows baseline/load tests and whole-delivery API approval alignment remain outside MV11. The known `test_openapi_change_requires_bilingual_spec_approval` baseline mismatch and approval digest were not changed. |

Validation of this change: current frontend build passed; `ruff check scripts/verify_backtest_startup_decoupling.py` passed; evidence assertions for all real-server scenarios, cache behavior, normal shutdown, port closure and unchanged source/research hashes passed. Existing MV02 tests were not rerun or presented as a substitute for these observations. A stronger model is unnecessary: the required real-server/browser evidence is complete and no unresolved runtime blocker needs escalation.

## MV12. Isolation wrap-up and contract review

Date: 2026-10-07, Asia/Shanghai. This round completes ML-T33/ML-T34/ML-C12 and repairs the existing unified research approval record. It does not implement monitoring-loop business/UI or certify future interfaces. MV01–MV10 retain historical scope summaries, with original step logs in Git history; the former OpenAPI approval failure remains recorded in MV03. MV11 remains **PASS**; its real startup/browser evidence was not rerun or redefined as load acceptance.

### MV12.1 Baseline and implemented behavior

Before this round, an internal baseline recorded the starting dirty worktree and 1,188 file hashes. The full temporary inventory and duplicate diff backup were removed during commit preparation; durable conclusions remain here and in Git history. Existing lifecycle/composition/web changes, untracked service/recovery/startup files, design edits and independent Shengxin research artifacts were already present. This round changes `backtest/jobs/repository.py`, `backtest/sync.py`, the focused recovery/pacing tests and paired plan/task/verification/current-approval documents; the other baseline files remain preserved.

The user resolved ML-T33 with dormant history and safe slot release. Expired historical RUNNING/CANCEL_REQUESTED records remain unchanged and do not occupy the slot; merely opening history or execution readiness does not authorize them. A valid or unknown/null lease blocks both queued admission and selected recovery. SQL write transactions serialize competing new claims and recovery; selected IDs are filtered before ordering, so earlier unselected records cannot starve them. Explicitly selecting an expired CANCEL_REQUESTED task acknowledges cancellation rather than executing it. Existing 30-second leases, at most 3 claim generations, idempotency and cancellation/publication fences remain. Stale tokens cannot renew, progress or publish. No new status, database migration or public API was required.

The current coordinator still awaits the actual operation future before requesting another claim. A new regression advances the clock beyond its lease while a non-cooperative worker remains held: the next job stays QUEUED and executes only after physical return. Existing shutdown/replacement ownership tests remain applicable. Several dormant records can coexist with one valid execution lease; the old total-status count assertion no longer misclassifies this as corruption.

ML-T34 paces inside each synchronous provider callback using monotonic request-start time and the existing `LIVE_TUSHARE_MIN_INTERVAL` (1.25 seconds). It covers `trade_cal`, `daily`, `stk_mins` and `stk_limit`, including controller-delayed/repeated callbacks, failed attempts and successive sync invocations. Real provider adapters were inspected: each of those methods issues one endpoint request. Production constructs a fresh blocking core per job, so its owned worker retains just the last request-start timestamp in thread-local storage across fresh cores. No extra executor, cross-operation mutex or account-wide scheduler is introduced. A wait checks cancellation at intervals no longer than 0.05 seconds and again before the call; the first request starts immediately, long calls need no additional full interval, and cached sync makes no calls/waits. Existing transport timeout/error mapping remains, and the sync service adds no retries. Only the two planned pacing files implement this change; monitor/AI request modules are unchanged.

### MV12.2 Executed checks

Commands ran from `trade-plan-monitor/`, with fake providers and temporary databases. Counts are separate, overlapping command results and must not be summed into a new suite total.

| Check | Command | Observed result |
|---|---|---|
| ML-T33 final lease/recovery/admission/cancellation/publication | `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_thread_recovery.py tests/integration/test_backtest_job_leases.py tests/integration/test_backtest_job_coordinator.py tests/integration/test_backtest_jobs.py -q -m 'not live'` | 47 passed, 8.47 seconds after the fresh-core timestamp change (previously 7.56 seconds). Includes new-claim/selected-recovery race, multiple dormant records plus one valid lease, unknown lease, stale tokens and same-coordinator physical drain. |
| Existing event/time/cancellation guards and expanded recovery | `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_thread_recovery.py tests/integration/test_unified_replay_boundaries.py -q -m 'not live'` | 28 passed, 42.55 seconds. Includes the existing 70,000-event refusal before another runtime evaluation and bounded calendar context. |
| Initial pacing reproduction | `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_sync_pacing.py -q -m 'not live'` | Before implementation: 10 failed, 2 passed. After implementation: 12 passed, 1.78 seconds; a later fresh-core regression expands this file to 13 cases. |
| Pacing, existing sync/storage/ownership/composition/startup guards | `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_sync_pacing.py tests/integration/test_backtest_sync.py tests/integration/test_backtest_results.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_backtest_production_composition.py tests/integration/test_backtest_startup_isolation.py -q -m 'not live'` | 80 passed, 1 skipped, 66.37 seconds after the fresh-core timestamp fix. The earlier candidate passed 79 cases, skipped 1 in 66.29 seconds. |
| Existing unified research API/job/result and legacy compatibility | `.venv/Scripts/python.exe -m pytest tests/integration/test_unified_replay_entries.py tests/integration/test_backtest_compatibility.py -q -m 'not live'` | 5 passed, 6.25 seconds. Reviewed inactive input, missing/wrong review rejection, idempotency, frozen worker inputs, results/equity/export and cancellation/no publication pass. |
| OpenAPI before approval repair | `.venv/Scripts/python.exe -m pytest tests/integration/test_openapi_snapshot.py -q -m 'not live'` | 1 failed, 13 passed, 9.76 seconds. Only the known approval-record check failed. |
| OpenAPI after concrete bilingual review | Same complete `test_openapi_snapshot.py` command | 14 passed, 9.27 seconds. Snapshot, actual routes, approved paths, public errors, generated TypeScript and deterministic/LF checks pass without test changes. |
| Generation and static checks | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`; `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe -m compileall -q src`; `git diff --check` | Passed. Both canonical monitor v2 and compatibility monitor v1 artifacts remain current. |

ML-T33 reproduction initially failed 4 of 10 recovery cases and passed 6, detecting expired history blocking new/selected work and preventing the next job even after physical return. The repository fix passed those cases; the final file contains 11 cases after adding the concurrent claim/recovery race. No assertion, time gate or test was removed/weakened. The existing Windows skip is `requires POSIX ownership semantics`; the existing Starlette/httpx deprecation warning is preserved.

### MV12.3 Concrete review of the old OpenAPI mismatch

[openapi-review.json](evidence/2026-10-07-isolation-wrapup/openapi-review.json) contains a compact index of all 37 JSON-path differences and comparison conclusions; exact schema bodies remain reproducible from the recorded Git commits. The former approved SHA-256 `4d1ff1d58e37b764aa057415cee1418298bc05bedbd360fbec60202f1f7cd255` is found exactly in commit `a0915f71b52a415e55086587e029c38e126c0d49`. The current snapshot `8da41a7d8d06f6a4e114570b52e88c894d0f817de365dc062bee08b28989e833` was committed in `7a92f75` and equals HEAD. There are 25 added schemas, 12 differences within 5 existing schemas, and no removed schema. The complete `paths` tree, non-schema components and other existing schemas compare equal, including monitoring, job, public error, authentication, parameter and response declarations. This is stale approval for previously authorized unified research, rather than a startup or pacing defect.

| Reviewed group | Concrete changes | Authority and conclusion |
|---|---|---|
| Frozen research input (11 added schemas, 1 existing-schema difference) | `BacktestRunCommand.researchInput`; `UnifiedResearchInput`, `ResearchReview`, `ResearchFactor`, `ResearchAdjustmentProof`, `TradingDay`, `ResearchFact`, `DailyOfficialProof`, `ResearchDeactivate`, `ResearchReplace`, `ResearchSimulation`, `ResearchReassessment`. | UR03/UR04/UR05/UR06: explicit review/start/inventory, frozen certified evidence, bounded operations and exact simulation cause/quantity. Strict values, explicit +08:00, unique order/IDs and server review validation remain. No file-path or real execution authority is added. |
| Research decision/operation details (12 added schemas, 3 existing-schema differences) | `ResearchDecisionView`, `ResearchDecisionEvent`, `ResearchConditionEvidence`, `ResearchRuleEvidence`, `ResearchReminder`, `DailySignalState`, `DailyRiskState`, `DailyRiskAction`, `DailyInventoryView`, `ResearchOperationView`, `ResearchOperationOutcome`, `ResearchOperationValuation`; `BacktestDetailView` replaces its three-branch `oneOf`/`kind` discriminator with five typed `anyOf` branches. | UR06 retains DECISION/EXECUTION_OUTCOME envelope kinds for both legacy and research; `kind` alone therefore cannot discriminate all five branches. Required `researchDecision`/`researchOperation` versus legacy payloads and inner schema-version constants distinguish them. Extra fields are forbidden; bounded detail validation remains. This is the approved typed additive mapping, not arbitrary payload acceptance. |
| Research metrics/equity (2 added schemas, 8 existing-schema differences) | `ResearchMetricsView`, `ResearchEquityView`; metrics in `BacktestRunSummaryView`/`BacktestRunView` become typed unions (3 differences each); `BacktestEquitySeries.items` becomes a typed union (2 differences). | UR05/UR06: separate research monetary projections, nullable invalid valuation, safe-number money, bounded/ordered equity output; legacy branch meanings and export bytes stay unchanged. |

UR01 authorizes design/internal review/sequential implementation/independent final review; UR08 includes backtest transport/generated contracts and bilingual records. The prior [unified replay verification](2026-10-03-unified-replay.md) records independent review and UR-A01–UR-A10 evidence. This round additionally reviewed concrete schemas/source bindings and ran the actual entry/compatibility and generation/snapshot checks above. With that evidence, the paired `SPEC-unified-plan` current approval was corrected with date, implementation commit, change summary, design authority and the preserved historical digest. `openapi.json`, generated types and tests remain unchanged. ML-T29/ML-C10 remain unchecked because future monitoring-loop interfaces/dependencies are incomplete.

### MV12.4 Review and remaining scope

Self-review using the `code-review` skill examined security, correctness/concurrency, performance and maintainability against the recorded starting-file copies, separating this round from existing dirty changes. SQL values remain parameterized; valid/null leases fail closed; stale tokens and atomic publication remain fenced; one physical worker still serializes operations. Local pacing retains constant-size timestamp state, existing callback/error policy and cancellable bounded waits. Concrete final baseline contract review found no unresolved in-scope defect. Paired document IDs/commands/dependencies and the completed historical todo tail are checked for parity/preservation.

ML-T30–ML-T34 and ML-C11/ML-C12 are complete; 34 of the existing 39 task slices remain pending. They cover preparation/review, frozen loop inputs and account/reminder/daily replay, submission/publication/results/latest-30 retention, public service controls/generated UI, broader integration/browser/Windows load, and final operations/evidence/future contract review. Those are existing separate tasks, not new MV11 blockers. Cancelled protection work remains excluded. No production database/configuration, independent Shengxin research, live provider/paid AI, notification, commit, push or deployment was changed or invoked. The accepted same-process/non-cooperative-thread limits remain; this round does not claim full fault/load or healthy live-market certification.

## MV13. Commit preparation and artifact cleanup

The user authorized packaging and GitHub delivery on 2026-10-07. Redundant process artifacts were removed while essential evidence, reusable offline harnesses and substantive regression tests were retained; independent Shengxin research remained outside delivery. No safety assertion or threshold was weakened. Intermediate packaging test counts are superseded by MV44/MV46. This historical authorization does not grant deployment or paid-provider activity.

## MV14. Frozen input and shared simulation foundation

On 2026-10-07, implementation started from `0db69c9` under the existing business authorization. ML-T01 and ML-T02 are complete, each within its four primary files, with paired todo/verification updates. Independent Shengxin research files are preserved. This round performed no commit, push, production change, live monitor, paid request, notification or deployment.

### MV14.1 Implemented behavior

ML-T01 adds strict immutable `monitor-loop-input-v1` / `backtest-run-v5` values, with no v1–v4 codec changes. Opening facts distinguish unknown/zero cash, unknown inventory/cost/sellability, exact `401050`-fen cost and independent market mark. Account facts may precede monitoring start; future facts/unavailable marks are rejected. Cash, costs, quantities and market value retain safe-integer checks, including unknown cash. Content review binds original source hashes and evidence hash and must exist by submission. Authoring date/time, availability, information cutoff, effective day and review time are distinct; date-only sources gain no invented timestamp, and later-authored plans remain retrospective. Calendar preflight rejects duplicate/unknown/closed dates and uncovered starts. Successors switch at daily boundaries; identical continuation retains activation and future versions cannot rename earlier authority IDs. Existing activation/rule validity remains authoritative.

An injected aware submission clock resolves omitted/null or explicit end dates once in Asia/Shanghai. Past/holiday dates remain inclusive; today freezes the submission instant. Before-start/future dates and forged cutoff/origin values fail. Source limits remain 256 items, 8 MiB UTF-8 total and 150,000 characters per source; opening lots remain capped at 200. Evaluations including refreshes, reminders, intents and attempts each have a 70,000 cap. Define one batch extraction slot and 3 total retryable attempts. Worker enforcement, submission reservation and cutoff dataset wiring remain future tasks; these values do not implement them.

ML-T02 extracts the existing checks/writes into `state/simulation.py`, with typed commands/receipts and transport-independent rejection codes. It writes inventory, signal consumption, risk fulfilment and receipt within the caller's transaction, without committing. Web retains idempotency, commit and error mapping; old research simulation no longer uses the private HTTP helper. Tests independently check exact ledger rollback, receipt values, revisions, full quantity and no Web imports during execution.

### MV14.2 Executed checks

All commands ran from `trade-plan-monitor/` with offline fixtures and temporary databases. New tests first failed for missing modules. A later red test exposed future-review admission and passed after its fix. New fixture mismatches (SSE/SZSE calendar and quote freshness before session checks) were corrected to existing behavior; no existing test/assertion was edited, skipped or weakened.

| Check | Command | Result |
|---|---|---|
| ML-T01 | `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_input.py tests/unit/test_monitor_loop_schedule.py -q -m 'not live'` | 35 passed, 0.59 seconds. |
| ML-T02 | `.venv/Scripts/python.exe -m pytest tests/integration/test_simulation_participant.py tests/integration/test_unified_simulation_transactions.py tests/integration/test_unified_replay.py -q -m 'not live'` | 25 passed, 50.86 seconds; includes 7 new participant cases. |
| Online/shared/frozen compatibility | `.venv/Scripts/python.exe -m pytest tests/integration/test_unified_runtime.py tests/integration/test_unified_replay_parity.py tests/integration/test_backtest_compatibility.py tests/integration/test_daily_plan_chain.py tests/integration/test_daily_history_regression.py tests/integration/test_openapi_snapshot.py -q -m 'not live'` | 56 passed, 47.61 seconds after extraction. |
| Final unit/contract regression | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live'` | 2793 passed, 4 live tests deselected, 20.83 seconds after the final input fix. |
| Static/generated artifacts | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`; `git diff --check` | PASS; both canonical monitor v2 and compatibility monitor v1 remain current. |
| Structural review | Paired heading IDs/commands/task checkboxes; original completed todo tail; normalized AST comparison of the original and extracted execution bodies | PASS. The AST comparison excludes only the changed docstring/signature and transport-type/error mapping names. |

### MV14.3 Review and remaining scope

Self-review with the `code-review` skill compared the extracted body to the prior helper and checked authorization, arithmetic, determinism and bounds. Source/evidence approval binding, unknown-cash market-value bounds, separate account/start times and future-review admission were corrected. Public schemas/transports and current allocation/simulation/transaction rules remain unchanged. Existing Starlette/httpx deprecation warnings remain. No future API digest was approved.

ML-C01 still requires ML-T03 reminder capture. There is no automatic loop, atomic cash participant, preparation workflow, new result/API/UI or completed Windows load acceptance yet. 32 of the existing 39 slices remain pending. Next dependencies are ML-T03, ML-T04 atomic accounts and ML-T05 offline single-plan cycles. This evidence neither claims them complete nor reinstates cancelled scope.

## MV15. Private reminders and ML-C01

### MV15.1 Implemented behavior

ML-T03 is complete in two slices: unknown opening-lot persistence/accounting, then private monitoring/reminder capture. `LoopSession` creates only a fresh private SQLite file, seeds frozen review/active bindings and calendar, and injects virtual time and causal reminder IDs into the shared runtime. Its source row is explicitly a reviewed manifest, not invented original source text. Historical opening holdings remain unchanged by evaluation or capture; no live provider, sink, network or Web execution path is used.

`ReminderCapture` uses `daily_delivery_allowed`, records CAPTURED/SUPPRESSED receipts atomically, deduplicates retries, enforces the 70,000 cap and returns bounded pages. Quote age and corrected minute/fact/inventory/review/activation evidence suppress delivery. The new red minute-correction test exposed a missing ordinary send fence; the shared ordinary predicate now applies the existing minute-source check. Valid online behavior remains covered. Pure technical alerts have no quantity or execution candidate. The explicitly tagged private opening variant preserves unknown acquisition dates and sellability; unknown/zero availability blocks sells, while an explicit whole-lot availability permits the existing full-quantity check. No production migration or API/generated contract changes are required.

### MV15.2 Executed checks

All commands ran offline from `trade-plan-monitor/` with temporary stores. New tests first failed for missing private-session/state support; the corrected-minute fence failed before its fix. Fixture corrections retained actual later receipt times. No existing tests, assertions or thresholds were weakened.

| Check | Command | Result |
|---|---|---|
| ML-T03 | `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_reminders.py tests/integration/test_unified_runtime.py -q -m 'not live'` | 40 passed, 12.14 seconds; includes 18 new private-loop cases. |
| Shared state/online regression | `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_reminders.py tests/integration/test_unified_runtime.py tests/integration/test_daily_simulation.py tests/integration/test_daily_simulation_review_regressions.py tests/integration/test_simulation_participant.py tests/integration/test_unified_simulation_transactions.py -q -m 'not live'` | 79 passed, 36.91 seconds. |
| Unit/contract regression | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live'` | 2793 passed, 4 live tests deselected, 21.68 seconds. |
| Static/generated artifacts | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`; `git diff --check` | PASS; canonical monitor v2 and compatibility monitor v1 remain current. |

### MV15.3 Review and remaining scope

Self-review checked frozen authority, source labels, missing facts, rollback/idempotency, bounded reads, temporal fences and shared behavior. ML-C01 is complete. Atomic cash, automatic response cycles, daily plan switching, preparation, result/API/UI and full load acceptance remain pending; 31 of 39 tasks remain. ML-T04/ML-T05 are next. Existing Starlette/httpx deprecation warnings remain. No commit, push, paid/live action or deployment was performed in this continuation.

## MV16. Atomic private account settlement

### MV16.1 Implemented behavior

ML-T04 adds `LoopAccountParticipant` and exact-fen cost/state/receipt values, composed only by the fresh private session. The shared simulation participant retains quantity, T+1, CORE/risk and occurrence authority. One caller-owned transaction covers cash, lot costs, inventory, signal consumption/risk fulfilment, shared receipt and money receipt. No participant commits itself. Private tables require no production migration. Observation mode rejects execution.

Use absolute per-share fen slippage and the existing upward rounding of each proportional fee. The source example buy 100 at 28.70 uses fill price 2871 fen, notional 287100, fees 503; sell 100 at 29.30 uses 2929, 292900 and 650. These are frozen source assumptions, not current statutory rates. Cash admission uses the whole quantity including fees; unknown cash or a one-fen shortage rejects without mutation. Fees/cash/cost totals retain safe-integer checks. The shared receipt records the authorization quote; the money receipt separately records the slipped fill price and costs.

The opening 401050-fen basis is retained without a new buy or purchase fee. Sold basis follows the actual shared batch debits. Proportional released basis rounds down to whole fen; the residual stays with the remaining lot, preserving total cost. Unknown basis remains unknown and makes realized cost-based P/L unknown. Repeated keys require identical command/cost settings and return the original immutable receipt. Receipt validation checks settlement/quantity and resulting bucket quantities. Failures after inventory writes and after all money/receipt writes, stale revisions and invalid retries leave no partial effects. Commit-time minute-source revalidation prevents a correction after evaluation from authorizing a fill; a new red test exposed this gap before the fix. Non-execution record kinds cannot act as money causes.

### MV16.2 Executed checks

All runs used offline fixtures and temporary databases from `trade-plan-monitor/`. New fee/account tests first failed for missing modules or participant methods. No existing assertions or gates were lowered.

| Check | Command | Result |
|---|---|---|
| ML-T04 final target | `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_costs.py tests/integration/test_monitor_loop_account.py -q -m 'not live'` | 21 passed, 2.11 seconds after final receipt/commit fences; 8 cost and 13 account cases. |
| Loop/shared/legacy replay | `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_costs.py tests/integration/test_monitor_loop_account.py tests/integration/test_monitor_loop_reminders.py tests/integration/test_simulation_participant.py tests/integration/test_unified_replay.py tests/integration/test_unified_replay_parity.py tests/integration/test_openapi_snapshot.py -q -m 'not live'` | 76 passed, 84.47 seconds; before final private receipt/commit fences. |
| Unit/contract regression | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live'` | 2801 passed, 4 live tests deselected, 21.11 seconds after receipt and minute-source validation. |
| Static/generated artifacts | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | PASS; monitor v2 and compatibility v1 unchanged. |
| Document/worktree checks | `git diff --check`; paired heading IDs, commands, task states and original completed todo tail | PASS. |

### MV16.3 Review and remaining scope

Self-review checked cash bounds, exact rounding, opening cost preservation, shared debit reconciliation, unknown P/L, receipt bindings and rollback. ML-T04 is complete. ML-T05 automatic response timing and a full single-plan cycle are still pending; this participant alone does not implement next-minute selection, price-limit admission or result publication. ML-C02 remains open. 30 of 39 tasks remain. No commit/push, paid provider, production state or live notification was used.

## MV17. Single-plan scope correction and input regression

### MV17.1 Accepted scope and implementation

On 2026-10-07 the user required single-plan backtesting only. Each run freezes exactly one complete reviewed plan/source and one initial effective binding. It may continue across trading days while valid; execution updates the ledger without changing plan content. Daily replacement, predecessor inheritance/merge, multi-plan preparation and simultaneous multi-plan replay are outside this release. ML-T06/ML-T09 and ML-A07 are cancelled, not passed/completed; their IDs and earlier evidence remain. Active dependencies/checkpoints exclude them. Proposal, plan and todo were updated in both languages. Nine tasks are completed; 28 of 37 active tasks remain, with 39 registered IDs and 13 checkpoints.

The private source/input contracts now reject second sources/entries including duplicate versions, model copies and decoded payloads. Selection keeps one activation across days, availability and expiry fences; successor selection is removed. Reviewed evidence hashes keep their independent bounded collection. Preserve optional end/cutoff, opening-account precision, fees/atomic state, legacy encodings and existing isolation/provider/event limits. Unavailable authority reports `LOOP_PLAN_AUTHORITY_UNAVAILABLE`, not a request to switch plans. Preparation/API/UI remain planned single-source work, not implemented by this scope correction.

### MV17.2 Executed checks

Offline checks used temporary stores only. New cardinality cases first produced 3 failures and 1 pass under the prior multi-entry implementation. Old positive batch/switch fixtures were replaced by explicit rejection, fixed-plan continuation/expiry and dataset/causal-identity cases because the user cancelled that behavior. Other causal, account and public compatibility assertions remain. Static checking found two long test lines; formatting was corrected without changing assertions.

| Check | Command | Result |
|---|---|---|
| Single-plan input/time | `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_input.py tests/unit/test_monitor_loop_schedule.py -q -m 'not live'` | 39 passed, 0.57 seconds. |
| Reminder/account/fees | `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_reminders.py tests/integration/test_monitor_loop_account.py tests/unit/test_monitor_loop_costs.py -q -m 'not live'` | 39 passed, 3.53 seconds after final authority-error wording. |
| Unit/contract regression | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live'` | 2805 passed, 4 live tests deselected, 21.32 seconds. |
| Static/generated artifacts | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | PASS after formatting; canonical monitor v2 and compatibility monitor v1 remain current. |
| Document/worktree checks | `git diff --check`; paired headings/IDs/dependencies/commands/files/numeric thresholds and original completed todo tails | PASS. |

### MV17.3 Review and remaining scope

Self-review checked one-plan cardinality, immutable-copy/decoded-input fences, cross-day activation/expiry, independent evidence bindings and causal IDs across dataset revisions. Existing public schemas/generated files remain unchanged. The full automatic response cycle is still pending ML-T05; these checks do not complete it, preparation, results/UI or load acceptance. Existing Starlette/httpx deprecation remains. No commit/push, paid request, production state, live notification or deployment was used.

## MV18. Single unfinished task admission

The latest user correction requires one unfinished task, not merely one executing thread. Removed the 100-job queue capacity, authorization accumulation and multi-ID recovery. Existing SQLite write transactions now reject different new sync/verify/replay operations while any job is QUEUED/RUNNING/CANCEL_REQUESTED, including expired/unknown leases. Pending snapshot reservations also block new operations until release/finalization or jobs-owned orphan cleanup. Same-key and same-operation idempotency remain. Terminal state releases admission; cancellation requested does not. Selected recovery authorizes one job and preserves physical drain, 30-second leases/3 generations and stale-token/publication fences. Internal `BACKTEST_BUSY` uses existing public `409 CONFLICT`; no API fields/schema/dependencies/migration were added. ADR 0009 supersedes the earlier queue and expiry/preparation concurrency choices. Preparation is still pending and must inherit this entry rule.

The new admission test initially failed all 15 cases against multi-task admission. After correction and adding expired-reservation coverage, all 16 cases pass within the following combined gate. Existing bulk queue fixtures now create terminal history records, preserving pagination, membership fences, stale-token and worker-drain assertions.

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_single_task.py tests/integration/test_backtest_jobs.py tests/integration/test_backtest_thread_recovery.py tests/integration/test_backtest_job_coordinator.py tests/integration/test_backtest_run_api.py tests/integration/test_backtest_production_composition.py tests/integration/test_backtest_job_api.py tests/unit/test_backtest_service_contract.py tests/integration/test_monitor_loop_cycle.py tests/integration/test_monitor_loop_reminders.py tests/integration/test_monitor_loop_account.py tests/integration/test_simulation_participant.py tests/unit/test_monitor_loop_input.py tests/unit/test_monitor_loop_schedule.py tests/unit/test_monitor_loop_costs.py -q -m 'not live' --tb=short
```

Result: **278 passed, 1 skipped, 27.98 seconds**. The skip is the existing POSIX ownership check on Windows. Later cycle calendar/volume cases and the final scope guard are verified in MV19. No test was skipped/deleted to make the correction pass. Unrelated live-monitor request queues and result/history paging remain outside this cleanup.

## MV19. Private single-plan response cycle

ML-T05/ML-C02 are implemented and verified. Frozen causal frames drive shared monitoring and eligible local reminder capture; bounded intents use frozen response delay and the next complete minute interval. The 09:35:12 reminder cannot fill on the 09:35–09:36 interval: the fixture buys at 09:37 and sells at 09:42, each for 100 shares. Independent expected values assert cash `503590` fen, remaining accounting cost `798654` fen, total 200 shares, zero sellable TACTICAL and 15 evaluations including post-fill refreshes. There is no future trade script.

The first buy/sell integration failed because the fixture supplied ten source minutes where current delivery expects the latest five-minute bucket; corrected the fixture to the established source contract, preserving send-time fences. Risk tests use explicitly certified historical daily revisions available at each virtual instant. Shared risk priority blocks a pending ordinary buy, executes the authorized risk quantity and retains a latched exit after plan expiry. Expired ordinary authority closes without switching/reactivating a plan. Unknown/closed sessions, insufficient volume, price limits and cash block whole fills; an interval cannot repeat. Cancellation and intent/attempt/evaluation boundaries stop additional account commits. Frozen input limits remain 70000. Observe/recorded modes create no automatic trades.

| Check | Command | Result |
|---|---|---|
| Cycle, reminders, atomic accounts and shared simulation | `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_cycle.py tests/integration/test_monitor_loop_reminders.py tests/integration/test_monitor_loop_account.py tests/integration/test_simulation_participant.py -q -m 'not live' --tb=short` | 57 passed, 9.65 seconds; includes 19 cycle cases. |
| Lease and historical compatibility | `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_job_leases.py tests/integration/test_backtest_acceptance.py::test_fake_production_journey_is_complete_offline_and_live_state_is_unchanged tests/integration/test_backtest_acceptance.py::test_each_fixture_symbol_has_stable_buy_and_t1_exit_bytes tests/integration/test_backtest_acceptance.py::test_prior_evidence_manifest_and_bilingual_reports_fail_closed -q -m 'not live' --tb=short` | 10 passed, 4.24 seconds; offline application, BUY/SELL/T+1 byte repeatability and evidence manifest preserved. |
| Unit/contract regression | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live' --tb=short` | 2809 passed, 4 live deselected, 21.18 seconds. |
| Static/generated files | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | PASS; monitor v2 and compatibility v1 remain current. |
| Documentation/workspace | `git diff --check`; paired headings/IDs/literal commands, fields, paths, thresholds, dependency/checkpoint counts and original completed todo tail | PASS; 9 bilingual pairs, 39 retained task IDs/13 checkpoints; 10 completed, 27 pending active, 2 cancelled; original history unchanged. |

Two broader legacy acceptance invocations were interrupted during unrelated year-scale fixtures; neither full invocation is counted as PASS. The second name-based filter still included a year-scale case, so final related checks use the explicit node selection above. Capacity thresholds and test definitions are unchanged; full loop load acceptance remains pending.

Self-review checked transactional admission/reservation races, idempotent retries, terminal release, single recovery authorization, minute/quote/limit/calendar binding, exact quantities/costs, shared risk authority, expiry observation and bounded feedback. Existing Starlette/httpx deprecation remains. This private slice does not implement preparation, recorded-action import, frozen-dataset reader, worker/API/UI/report integration or full loop load acceptance. There are 10 completed and 27 pending active tasks, 37 active / 39 retained IDs; ML-T06/ML-T09 remain cancelled and ML-T07 is next. No commit/push, paid request, production state, live notification or deployment was used in this slice.

## MV20. Single-plan preparation persistence

On 2026-10-08, ML-T07 continued from `main` `91eca25`. Its three primary files are `backtest/preparation_models.py`, `backtest/preparation_store.py` and `tests/integration/test_plan_preparation_store.py`; paired plan/todo/verification records are updated. Independent Shengxin research remains outside this change.

The separate SQLite file contains `backtest_preparation_metadata`, `backtest_preparation` and `backtest_preparation_idempotency`. The metadata binds `backtest-preparation-v1` and schema version 1. Existing normalized-path/storage guards and the tag/table check reject live, market, result/job, unknown, mixed and unsupported-version stores. Reverse market/result opening also rejects the preparation file; rejection tests verify unchanged file bytes. No production migration/configuration or deep file-alias framework is added.

Strict immutable input contains exactly one source. Preserve original text, SHA-256, supplied authoring/availability/effective dates and a separate metadata binding hash; absent historical dates remain unknown. Revalidate typed create/edit values at the persistence boundary so constructed objects cannot bypass source cardinality or blank-text rejection. Each source revision retains at most 3 attempts; unchanged edits do not reset this budget. Reads/restarts retain unresolved attempts without a provider call, automatic retry or lease-expiry release.

Source corrections increment revisions and invalidate candidate/review bindings. An in-flight edit or cancel persists `CANCEL_REQUESTED` and the unresolved attempt identity; late candidate completion is rejected. Another preparation mutation/start remains blocked, including after restart. Only explicit `acknowledge_cancellation` records the confirmed end. A changed source can then return to a draft; explicit cancel after an edit ends cancelled. This storage acknowledgement does not prove physical worker drain: ML-T10 must establish that fact before calling it and ML-T10/ML-T12 must connect preparation to the existing global job admission rule. This task exposes no worker or public preparation entry.

Candidate persistence reuses the existing 1 MiB output, 10000-node and 64-depth extraction bounds; duplicate keys, malformed/non-finite JSON and a non-object root reject. Its bounded opaque payload does not implement ML-T08's complete-plan/opening-account output. `VALID` is distinct from approval. Explicit stored review requires literal boolean true and exact source/candidate revisions, candidate hash and evidence hash. Re-extraction invalidates review even when output repeats. Full source-clause validation, semantic review and immutable submission freeze remain ML-T08/ML-T11/ML-T17 work.

Each mutation and its idempotency response commit in one `BEGIN IMMEDIATE` transaction. Same-key retries return the original receipt after later edits without restoring old state; changed requests/operations conflict. Concurrent creation/edit/start tests prove one receipt, revision fencing and one unresolved preparation attempt. An injected receipt-insert failure rolls back the earlier document write and permits the original retry. Cancellation/acknowledgement revisions and attempt IDs fence stale completion.

The initial target failed because the modules did not exist. The next slice had 16 expected missing-operation failures. No-op edits and admission tests then exposed two real boundary gaps; cancellation tests exposed premature terminal release and edit-then-cancel reopening. Constructed-value tests exposed source-validation bypass. Each was corrected before the final gate, with no assertion removed or test skipped. The first default temporary-directory run had permission errors; executed gates use dedicated ignored workspace directories. Large-input test identifiers were shortened to avoid Windows filename limits.

| Gate | Executed command | Result |
|---|---|---|
| Preparation and related integration | `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_store.py tests/integration/test_backtest_single_task.py tests/integration/test_monitor_loop_cycle.py tests/integration/test_backtest_results.py::test_backtest_storage_domains_reject_aliases_and_live_tables tests/integration/test_backtest_results.py::test_backtest_stores_reject_each_plan_web_state_table tests/integration/test_backtest_market_store.py::test_market_store_reopens_with_stable_dataset_content -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t07-release` | 92 passed, 7.75 seconds; includes all 53 ML-T07 cases. |
| Unit/contract regression | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t07-units-final` | 2809 passed, 4 live deselected, 23.95 seconds; before the final two private create/edit revalidation lines, covered by the integration gate above. |
| Code quality | `.venv/Scripts/python.exe -m ruff check src tests scripts` | PASS after the final source changes. |
| Existing generated contracts | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | PASS for canonical monitor v2 and compatibility monitor v1; no public schemas/types changed. |

Self-review checked source/metadata authority, exact revision binding, restart/unknown outcomes, cancellation occupancy, explicit acknowledgement, bounded JSON, idempotent snapshots, rollback, path separation and concurrent writes. Existing Starlette/httpx deprecation remains. ML-T07 is complete; 11 tasks are complete and 26 active tasks pending, with 37 active / 39 retained IDs and 13 checkpoints. ML-C03 remains pending ML-T08; ML-T06/ML-T09 remain cancelled. No provider/paid request, live notification, production-state mutation, deployment or additional load fixture was invoked. This private storage slice adds no extraction worker, global cross-store admission integration, API, UI or replay submission path.

## MV21. Complete single-source plan and opening-account extraction

On 2026-10-08, ML-T08 continued from `main` `b3a466c`. Changes stay in its four primary files: `ai/loop_plan_extraction.py`, the shared seam in `ai/extraction.py`, `tests/unit/test_monitor_loop_extraction.py` and `tests/fixtures/ai/monitor-loop-extraction-cases.json`. Paired plan/todo/verification records are updated; independent Shengxin research is excluded.

The private `monitor-loop-extraction-v1` output contains one complete Schema 5 candidate and typed opening-account facts. The adapter selects `monitor-loop-extract-v1`; ordinary extraction still selects `plan-extract-v9`. Both share provider request limits, envelope identity, finish-reason checks, sanitized diagnostics, duplicate/non-finite JSON rejection and the existing 1 MiB / 10000-node / 64-depth bounds. Candidate persistence applies the same bounds after deriving evidence and issues. No public schema, route, worker or provider transport changes are introduced.

Each economic fact retains an exact Unicode span/excerpt. Finite labelled-value and surrounding-context guards reject targets, ceilings, hypothetical trades, reference quotes, negation, recommendations and overlapping duplicate lots; bucket evidence must identify the same actual quantity assertion. These guards do not independently verify natural-language truth or grant human authority. Unsupported wording remains for explicit review. The source fixture retains actual CORE 100, TACTICAL 0 and ceiling 300; `40.105` yuan/share produces exact total cost `401050` fen without unit rounding, an opening BUY or acquisition fees. Subfen totals stay unresolved, including under a deliberately low Decimal precision. No opening valuation is inferred from quotes.

Unknown cash, allocation, acquisition date, sellability and snapshot time remain null and blocking; explicit zero cash and zero inventory remain known. Date evidence uses exact labelled ISO dates/timestamps; incoherent acquisition/sellability rejects. Trusted source authoring/availability/effectiveness metadata is retained and included in the evidence hash, never inferred from import time or used to populate account dates. Source clauses and mixed daily/five-minute ALL/ANY trees remain intact; missing rule quantities remain null. Partial fills, pending-order capacity and fundamental exits receive visible unsupported blockers. No predecessor/update/inheritance/merge or approval fields are accepted.

The semantic candidate round-trips through ML-T07 persistence/restart with its exact source and evidence hashes, unknown sellability and complete clause coverage; it does not create a review. Identical evidence yields the same evidence hash across distinct requests, while source-time corrections and account-fact changes alter it. Future worker admission/cancellation drain belongs to ML-T10; full semantic review and freeze belong to ML-T11.

| Check | Executed command/evidence | Result |
|---|---|---|
| Task gate | `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_extraction.py tests/unit/test_current_plan_extraction_security.py tests/unit/test_ai_plan_extraction_v4.py -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t08-release-final` | 93 passed, 2.26 seconds; includes 70 new cases. Final input-type fence is also covered by the full gate below. |
| Final unit/contract and related integration | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract tests/integration/test_plan_preparation_store.py tests/integration/test_backtest_single_task.py tests/integration/test_monitor_loop_cycle.py -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t08-final-gate` | 2967 passed, 4 live tests deselected, 30.04 seconds; all 70 new cases and 88 related integration cases included. |
| Ordinary output/contracts | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | PASS for canonical monitor v2 and compatibility monitor v1. |
| Code quality | `.venv/Scripts/python.exe -m ruff check src tests scripts --output-format concise`; `.venv/Scripts/python.exe -m ruff format --check src/trade_plan_monitor/ai/loop_plan_extraction.py tests/unit/test_monitor_loop_extraction.py` | PASS. |
| Mutation review | Temporarily invert the nonactual-context condition; run the 13 nonactual-context cases; restore exact original file bytes before the final gate. | All 13 fail under the mutation; restored final gate passes. |
| Documentation/worktree | `git diff --check`; paired headings/IDs/literal contracts and original completed todo tail | PASS; 12 complete, 25 pending active, 37 active / 39 retained IDs, 13 checkpoints. |

ML-T08 and ML-C03 are complete; ML-T06/ML-T09 remain cancelled and ML-T10 is next. Self-review covered source fidelity, exact arithmetic, chronology, absence of inferred facts, transport/parser compatibility, bounded persistence and explicit-review separation. The existing Starlette/httpx deprecation remains. Checks used fake providers and temporary isolated stores, with no paid requests, market downloads, live notifications, production-state mutations or deployment. This private adapter has no public preparation entry and does not bypass the existing single unfinished task requirement; future worker/API integration must share that admission rule. Additional load acceptance is not claimed.

## MV22. Single-source owned extraction and explicit recovery

ML-T10 is complete in the planned two increments. Optional ownership/progress fields extend existing preparation documents without a new table or schema version; older documents remain readable. A read-only repository seam retrieves the exact existing global admission token, including expired tokens. No new job kind, queue, database, public route, global AI budget or generic lock is added.

A fresh request atomically binds one source/revision/hash, generation and service owner before dispatch. The owned worker persists CALLING before the external call, with no SQLite transaction held during HTTP. Reads and original idempotent receipts never dispatch. RUN/SYNC/VERIFY and unrelated preparation mutations remain excluded while admission is unresolved. Cancellation/source corrections retain admission and discard late results; physical worker drain precedes durable completion and token release. Shutdown timeout and cancelled observers retain ownership until cleanup finishes. Old edit receipts cannot signal a later generation's cancellation token.

The configured adapter captures immutable settings and creates/calls/closes a fresh HTTP client on its owned thread/event loop. Ordinary extraction and backtest extraction share the existing capacity of one. Transport retries are disabled per durable attempt; configured known retries use at most three durable attempts per source. TIMEOUT, uncertain transport failures and unexpected exceptions retain UNKNOWN occupancy, including after lease expiry/restart. Explicit recovery requires confirmed_ended true and no locally owned outstanding work; it never resends. After restart the caller must explicitly confirm prior work ended, since a lost paid outcome cannot prove remote completion. A subsequent fresh extraction request consumes the remaining attempt budget. Exact generation/source/result bindings reject foreign or stale outputs; candidates grant no review or production activation authority.

| Check | Executed command/evidence | Result |
|---|---|---|
| Task gate | `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_worker.py -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t10-release-final` | 29 passed; storage compatibility, before/after-commit crashes, two-service races, late source/result fencing, cancellation/drain, historical receipt replay, expired UNKNOWN recovery and three-attempt budget. |
| Final unit/contract and related integration | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract tests/integration/test_plan_preparation_store.py tests/integration/test_plan_preparation_worker.py tests/integration/test_backtest_single_task.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_backtest_thread_recovery.py tests/integration/test_configured_ai_web.py -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t10-final-regression` | 3000 passed, 4 live tests deselected, 34.40 seconds. |
| Code quality | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe -m ruff format --check src/trade_plan_monitor/backtest/preparation_service.py src/trade_plan_monitor/backtest/preparation_worker.py tests/integration/test_plan_preparation_worker.py` | PASS. |
| Ordinary contracts | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | PASS for canonical monitor v2 and compatibility monitor v1; no snapshot/type/approval digest changes. |
| Mutation review | Invert the historical-receipt generation equality and run the old-edit cases; restore exact original source bytes. | The first mutation exposed a missing externally cancelled-generation case. After adding it, the mutation causes 1 failure / 1 pass; restored checks pass. |
| Documentation/worktree | Paired IDs/headings/literal contracts, original completed todo tail and `git diff --check` | PASS; 13 completed, 24 pending active, 37 active / 39 retained IDs, 13 checkpoints. |

ML-T11 is next; ML-C04 remains pending until ML-T11/ML-T12 pass. Self-review covered admission/physical ownership, idempotency, stale-generation/source/result fencing, known versus unknown retry classification, client loop ownership, bounded parsing and absence of approval. Executed checks use fake providers and temporary stores, with no paid requests, market downloads, live notifications, production-state mutations or deployment. The existing Starlette/httpx deprecation remains. Separate overview-retry/runtime edits and Shengxin research artifacts are preserved outside these commits. This private application seam has no public preparation entry; semantic review/freeze, API/UI integration and whole-load acceptance remain pending.

## MV23. Explicit review and one frozen preparation manifest

Executed 2026-10-08 for ML-T11 within its four primary files. ML-T10 was pushed to GitHub main at `75b6c19` before this work. No public preparation route, new table/schema/job kind/queue, production activation or run-boundary resolution is added.

One explicit confirmed review binds the preparation/source/candidate revisions and exact extraction/evidence hashes. AI output is revalidated through the existing source/field/account boundary; a VALID flag, erased issues or legacy review declaration cannot grant frozen-input authority. Only this human operation can register corrected draft/mapping, scoped supplements and evidenced account corrections. Missing technical details remain blockers; unsupported execution clauses cannot be acknowledged away. Original opening facts and extraction hashes remain in the frozen manifest alongside any declared human account correction. Source-derived cash, acquisition date, sellability and opening mark remain unknown unless explicitly evidenced. Historical account/mark availability and position bounds apply before freezing.

The existing transaction atomically writes one bounded immutable manifest, exact review declaration and original idempotency receipt. Receipt-write failure rolls all three back without consuming the key. Source edits invalidate the current candidate/review; the original receipt remains readable after restart and during unrelated active work. An already constructed MonitorLoopInput retains identical canonical bytes/hash after editing its source. No paid request or implicit retry occurs on review, read or receipt replay.

Review uses the existing global admission token and owned bounded metadata thread. RUN/SYNC/VERIFY in QUEUED/RUNNING/CANCEL_REQUESTED/expired states, unresolved reservations including the same review key, and unfinished extraction cleanup block fresh review. Observer cancellation/shutdown timeout retains admission until physical metadata work ends. A durable original review receipt proves completion and permits exact reservation cleanup after a crash between commit and release; a missing receipt never authorizes reclaim, even after expiry.

| Check | Executed command/evidence | Result |
|---|---|---|
| Task gate | `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_review.py -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t11-gate-final` | 51 passed; exact bindings, missing confirmations/details/times, unknown facts, immutable inputs, forged provenance/legacy flags, source invalidation, rollback, global occupancy, physical drain and commit/release recovery. |
| Final unit/contract and related integration | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract tests/integration/test_plan_preparation_store.py tests/integration/test_plan_preparation_worker.py tests/integration/test_plan_preparation_review.py tests/integration/test_backtest_single_task.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_backtest_thread_recovery.py tests/integration/test_configured_ai_web.py -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t11-final-regression` | 3051 passed, 4 live tests deselected, 34.54 seconds. |
| Code quality | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe -m ruff format --check src/trade_plan_monitor/backtest/preparation_review.py tests/integration/test_plan_preparation_review.py` | PASS. |
| Ordinary contracts | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | PASS for canonical monitor v2 and compatibility monitor v1; no snapshot/type/approval digest changes. |
| Mutation review | Invert opening-mark availability comparison and run opening_account_information cases; restore exact source bytes. | Mutation: 1 failed / 1 passed; restored: 2 passed. A prior failing case exposed the missing freeze-stage future-mark guard, which was fixed before final regression. |
| Documentation/worktree | Paired IDs/headings/literal contracts, original completed todo tail and MV01–MV22 history, `git diff --check` | PASS; 14 completed, 23 pending active, 37 active / 39 retained IDs, 13 checkpoints. |

ML-T12 is next; ML-C04 remains pending until the public preparation path is verified with fake AI over real HTTP. Self-review covered explicit authority, canonical hash/revision bindings, original evidence and unknown facts, atomic storage, historical causality, single admission and physical ownership. Executed checks use synthetic inputs and temporary databases, with no paid requests, market downloads, live notifications, production-state mutations or deployment. The existing Starlette/httpx deprecation remains. Separate overview-retry/runtime edits and Shengxin research artifacts are preserved outside these commits. API/UI/report integration and whole-load acceptance remain pending.

## MV24. One-source preparation HTTP and on-demand ownership

ML-T11 was pushed to GitHub main at `d2edc5b` before continuing ML-T12 on 2026-10-08. The two planned increments stay within seven primary files: `backtest/preparation_store.py`, `backtest/preparation_service.py`, `backtest/composition.py`, `web/preparation_schemas.py`, `web/routers/backtest_preparations.py`, `web/app.py` and `tests/integration/test_plan_preparation_api.py`. Paired plan/todo/verification documents are synchronized; separate overview-retry/runtime edits and Shengxin artifacts remain excluded.

The application mounts exactly-one-source create/read/edit/extract/cancel/review/recovery commands. Envelope fields use camel case; embedded research values preserve their existing field names. Source text remains limited to 150000 characters, candidate persistence to 1 MiB, public progress to 2 MiB and incoming transport to the existing 4 MiB. Revisions respect safe integers. Projections contain typed candidate/account/mapping or frozen values, with generation/phase progress and bounded attempts; raw candidate JSON, private owner/admission tokens, provider diagnostics and filesystem paths are excluded. Malformed opaque candidates and legacy review flags project UNAVAILABLE and cannot grant frozen authority.

Origin, command, identifier, query and mutation-key validation precede capability acquisition. The preparation store opens only for an explicit valid preparation request; unused startup/history/shutdown never opens it. Metadata operations leave the job coordinator dormant and never capture/call AI. Fresh extraction checks its original receipt and global admission before capturing the existing configured adapter. Missing AI creates no attempt. Preparation-store acquisition failure is cached and scoped; monitor and ordinary job reads remain usable. Repairing a file does not retry acquisition; the existing explicit lifecycle retry does.

Fresh create/edit/extract/cancel/review commands reject RUN/SYNC/VERIFY in QUEUED/RUNNING/CANCEL_REQUESTED/expired states. Original create/edit/cancel/extraction/review receipts remain readable during later work, without restoring old state or dispatching a new call; GET returns the current state. Cancellation/source edits preserve global admission until actual worker completion, discard late results and retain exact source/generation fences. Unknown results survive restart with admission held; explicit generation/revision-bound confirmed recovery never resubmits. Subsequent extraction requires a fresh explicit request. Acquired preparation shutdown retains physical ownership after inner observation timeouts and drains before closing AI; unused capability shutdown acquires nothing.

Two HTTP regressions first exposed old edit/cancel receipts being blocked by unrelated work; another exposed AI configuration capture before admission. The fixes moved original receipt replay before fresh-work admission and adapter capture after admission. No assertion, bound or skip was weakened. A real loopback Uvicorn/httpx journey, using fake AI and temporary databases, verifies cancel → edit → extract → review → restart and immutable receipt replay without implicit calls.

| Check | Executed command/evidence | Result |
|---|---|---|
| Task gate | `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_api.py -q --tb=short -m 'not live' --basetemp=.pytest_cache/ml-t12-release-final` | 53 passed, 17.14 seconds. |
| Final unit/contract and related integration | `.venv/Scripts/python.exe -m pytest tests/unit tests/contract tests/integration/test_plan_preparation_api.py tests/integration/test_plan_preparation_store.py tests/integration/test_plan_preparation_worker.py tests/integration/test_plan_preparation_review.py tests/integration/test_backtest_single_task.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_backtest_thread_recovery.py tests/integration/test_backtest_production_composition.py tests/integration/test_backtest_startup_isolation.py tests/integration/test_configured_ai_web.py tests/integration/test_backtest_data_api.py tests/integration/test_backtest_job_api.py tests/integration/test_backtest_run_api.py tests/integration/test_backtest_result_api.py tests/integration/test_backtest_export_api.py tests/integration/test_backtest_index_api.py tests/integration/test_web_api.py tests/integration/test_openapi_snapshot.py -q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t12-final-regression` | 3484 passed, 1 existing skipped, 4 live deselected, 113.21 seconds; includes all 53 task cases. |
| Code quality | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe -m ruff format --check src/trade_plan_monitor/web/preparation_schemas.py src/trade_plan_monitor/web/routers/backtest_preparations.py tests/integration/test_plan_preparation_api.py` | PASS. |
| Ordinary contracts | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | PASS for canonical monitor v2 and compatibility monitor v1; no snapshot/type/approval digest changes. |
| Mutation review | Temporarily invert the added original mutation-receipt condition and run the edit/cancel replay cases; restore exact original source bytes before final regression. | 2 failures under mutation; restored final regression passes. |
| Documentation/worktree | Paired headings/IDs/literal contracts, original completed todo tail, MV01–MV23 history and `git diff --check` | PASS; 15 completed, 22 pending active, 37 active / 39 retained IDs, 13 checkpoints. |

ML-T12 and ML-C04 are complete; ML-T13 is next. Routes are mounted but schema publication remains staged with `include_in_schema=False`; ML-T13 publishes the flag and generates contracts for concrete review without silently approving a digest. Self-review covered bounds, typed projection, global admission, original receipts, exact revisions, late-result fencing, physical ownership, restart and explicit human authority. The existing Starlette/httpx deprecation remains. There are no paid/provider/market calls, live notifications, production-plan mutations or deployment. UI/run/result integration and whole-load acceptance remain pending.

## MV25. Published preparation contracts and preserved compatibility

ML-T12 was pushed to GitHub main at `0d5b603` before ML-T13 on 2026-10-08. The transport slice is committed at `abf20db`. The scoped plan was expanded before implementation to eight primary files across three increments: `src/trade_plan_monitor/web/preparation_schemas.py`, `src/trade_plan_monitor/web/routers/backtest_preparations.py`, `scripts/generate_frontend_types.py`, `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts` and `tests/integration/test_plan_preparation_contract.py`. Publication and generated artifacts are committed together at `fdf250d`. Separate runtime/overview-retry edits and Shengxin artifacts remain excluded.

The mounted router publishes seven one-source operations with their existing errors, mutation-key and revision requirements. Cancellation documents its actual 200/202 results; success responses document no-store and bounded Location, and accepted work documents Retry-After 2. The public candidate is a discriminated EXTRACTION/FROZEN/UNAVAILABLE union with mutually exclusive required payloads. Public nested review, attempt and frozen revisions share the safe integer bound; successful field names/nulls stay unchanged. Single-source and three-attempt limits, literal confirmed recovery, explicit unknown/zero cash and private-state exclusion are checked in both profiles. TypeScript fixtures compile exhaustive candidate narrowing and valid commands, and reject false recovery confirmation and a null frozen manifest without suppression directives.

Publishing the review request initially split existing Pydantic validation/serialization definitions into names containing -Input/-Output, which the generator rejected. Three regression cases first failed. The existing generator now normalizes component names and all references: output keeps its old name and distinct input appends Input; collisions fail explicitly. Validation and serialization shapes remain separate. This naming issue follows the documented [Pydantic schema-mode behavior](https://pydantic.dev/docs/validation/latest/api/pydantic/config/?query=alias_generator). Offline comparison against `0d5b603` confirms all 52 old path items and all 287 compatibility-v1 / 300 canonical-v2 schemas are semantically identical; every old TypeScript alias and operation block is byte-identical. Each profile adds seven paths and 71 schemas. Every reference resolves and the progress/frozen closure contains no durable private record, ownership/admission tokens, opaque payload JSON or provider diagnostics.

| Check | Executed command/evidence | Result |
|---|---|---|
| Task gate | `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_contract.py -q --tb=short --basetemp=.pytest_cache/ml-t13-type-green` | 20 passed, 8.05 seconds; both profiles and actual TypeScript compilation. |
| Final unit/contract and related integration | Unit/contract suites and the MV24 integration selection, plus preparation-contract and frontend-contract-promotion tests; `-q -m 'not live' --tb=short --basetemp=.pytest_cache/ml-t13-final-regression` | 3509 passed, 2 approval failures, 1 existing skipped, 4 live deselected, 172.42 seconds; includes all 53 preparation HTTP cases. |
| Existing frontend | `npm --prefix web run test -- --run`; `npm --prefix web run type-check`; `npm --prefix web run build` | 807 tests / 57 files passed, 12.18 seconds; type checking and build PASS. |
| Code quality | `.venv/Scripts/python.exe -m ruff check src tests scripts`; `.venv/Scripts/python.exe -m ruff format --check scripts/generate_frontend_types.py src/trade_plan_monitor/web/preparation_schemas.py src/trade_plan_monitor/web/routers/backtest_preparations.py tests/integration/test_plan_preparation_contract.py` | PASS after restoring consistent source formatting. |
| Generated artifacts | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | Both canonical monitor v2 and compatibility monitor v1 PASS. |
| Mutation review | Temporarily permit a null FROZEN manifest; run frozen-missing candidate rejection and restore exact source bytes. | 1 expected failure, 19 deselected; restored final regression passes this case. |
| Documentation/worktree | Paired headings/IDs/literal contracts, retained completed todo tail and MV01–MV24 history, unchanged unrelated-file hashes, `git diff --check` | PASS; 16 completed, 21 pending active, 37 active / 39 retained IDs, 13 checkpoints. |

Approval remains pending ML-T29. The unchanged `test_openapi_change_requires_bilingual_spec_approval` fails because the candidate v1 snapshot digest is absent from the approved paired specification; `test_openapi_contains_only_approved_paths_and_public_error_schemas` fails because the seven preparation paths are outside APPROVED_PATHS. Neither test/assertion nor approved digest is changed, skipped or suppressed. The approved baseline remains `8da41a7d8d06f6a4e114570b52e88c894d0f817de365dc062bee08b28989e833`. Candidate SHA-256 values, pending approval: compatibility v1 `1fd4eea69dbe1827c35ca2f19a0261296be5e447f293d7a2e52c4fc8a5c9e3a4`; canonical v2 `7e5f0a6ebec6ce3cefd440af7d9619e9332e22dd081f3f667b40a7c08473a367`.

ML-T13 implementation and generation are complete; ML-T14 is next, while ML-C05 awaits upload/progress/review UI. Self-review covers compatibility, mode/name references, discrimination, bounds, private-state exclusion and exact success/error behavior. The existing Starlette/httpx deprecation remains. Tests use temporary stores and fake AI; no paid/provider/market calls, production-state mutations, notifications or deployment occurred. Final API approval and whole-delivery acceptance remain pending.

## MV26. Single-source input, progress and stable request control

ML-T13 was pushed to GitHub main at `c31904d` before ML-T14 on 2026-10-08. Three increments use five unique primary files: `web/src/api/preparations.ts`, `web/src/composables/usePlanPreparation.ts`, `web/src/components/backtests/PlanPreparationSourceForm.vue`, `web/src/components/backtests/PlanPreparationProgress.vue` and `web/tests/unit/PlanPreparation.spec.ts`. The first two increments are committed at `9f61cdd` and `c5018f1`. The final component increment also corrects unsaved-evidence and stale-read refresh handling in the same controller (2 / 2 / 4 files; 5 unique). Paired plan/todo/verification records and browser evidence accompany the scoped code; unrelated runtime/overview-retry edits and Shengxin artifacts remain excluded.

The transport reuses the existing bounded, frozen, redacted same-origin JSON layer. It accepts one embedded source, validates identifiers/safe revisions/Shanghai chronology, progress-envelope and candidate-discriminator bounds, and checks actual success status, no-store, Location and Retry-After 2. Semantic candidate review remains server-owned and belongs to ML-T15 UI integration. No generated snapshot/type/approved specification or backend is changed.

One controller owns one draft/preparation and one immutable outstanding mutation intent. Duplicate clicks coalesce; uncertain results retain the original key, revision and payload for explicit receipt replay. Reads never implicitly replay mutations. Original older receipts and stale reads cannot downgrade current state. Source edits survive failed reads; edited evidence must be saved before extraction. Definitive rejected creation restores editing. Cancellation waiting, UNKNOWN, source-edit cleanup and other unended physical work continue blocking fresh operations, including apparent FAILED/CANCELLED states. Generation/revision-bound UNKNOWN recovery requires explicit ended confirmation and never extracts automatically. Reads do not overlap, stop on idle/drained states, pause when hidden and stop on unmount; aborted/late read or mutation results cannot update disposed state.

The controlled form accepts pasted text or exactly one UTF-8 .txt/.md file, limited to 600000 bytes and 150000 Unicode characters. Optional Shanghai timestamps/date are never invented. Invalid/multiple/oversized files retain prior evidence and show escaped errors; manual edits, changed source/disabled state and unmount invalidate late file reads. Native labels, focus, status/error announcements and the existing design tokens are reused. The progress component shows cancellation waiting, attempts, explicit extraction/cancel/refresh, safe same-intent retry and confirmed recovery. Recovery confirmation resets when the observed revision/generation changes. Production page composition and reviewed-plan preview remain ML-T15; ML-C05 is still pending.

Three added regressions exposed rejected-creation editing staying locked, extraction remaining enabled with unsaved evidence, and stale reads leaving refresh permanently busy. Each failed before its fix and passes in the final suite. The browser fixture uses real local HTTP and synthetic candidate-envelope values to exercise progress only; it is not semantic review or production-route acceptance. Chrome DevTools MCP is unavailable, so the installed Playwright/Chrome runtime supplies the real-browser verification. The temporary harness/server are closed and removed after evidence capture.

| Check | Executed command/evidence | Result |
|---|---|---|
| Task gate | `npm --prefix web run test -- --run tests/unit/PlanPreparation.spec.ts` | 50 passed: transport, one controller, source/progress components and failure/lifecycle boundaries. |
| Full frontend | `npm --prefix web run test -- --run`; `npm --prefix web run type-check`; `npm --prefix web run build` | 857 tests / 58 files passed, 8.60 seconds; type checking and build PASS. |
| Related backend/API contracts | `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_api.py tests/integration/test_plan_preparation_contract.py tests/integration/test_frontend_contract_promotion.py tests/integration/test_openapi_snapshot.py -q --tb=short -m 'not live' --basetemp=.pytest_cache/ml-t14-contract-regression` | 92 passed, exactly 2 existing approval failures, 73.19 seconds; all 53 preparation HTTP and 20 preparation-contract cases pass. |
| Generated artifacts | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | Both canonical monitor v2 and compatibility monitor v1 PASS; snapshots/types unchanged. |
| Real browser | [Machine-readable journey evidence](evidence/2026-10-08-plan-preparation-ui/browser-summary.json) | One creation, 4 explicit extractions, one cancel, one confirmed recovery and one receipt replay. Save-before-extract, drain waiting, same-key/body replay, invalid UTF-8 preservation, keyboard Tab and stopped polling PASS. Widths 320 / 768 / 1024 / 1440 have no horizontal overflow or axe violations; console/page errors and external requests are zero. |
| Visual evidence | [320-width candidate](evidence/2026-10-08-plan-preparation-ui/candidate-320.png), [1440-width candidate](evidence/2026-10-08-plan-preparation-ui/candidate-1440.png), [cancel waiting](evidence/2026-10-08-plan-preparation-ui/cancel-wait-1440.png), [confirmed UNKNOWN recovery](evidence/2026-10-08-plan-preparation-ui/unknown-confirmation-1440.png) | Inspected responsive layout, expanded optional dates, controls and recovery confirmation. |
| Mutation review | Invert the unended-work condition, run physical drain cases, then restore exact source bytes. | Mutated: 2 failed / 2 passed (FAILED/CANCELLED fences detected), other tests filtered; restored final suite passes all 50. |
| Documentation/worktree | Paired headings/IDs/literal contracts, retained completed todo tail and MV01–MV25, unrelated-file hashes, `git diff --check` | PASS; 17 completed, 20 pending active, 37 active / 39 retained IDs, 13 checkpoints. |

The first backend attempt used the inaccessible Windows system pytest temporary directory (70 setup errors); rerunning with the explicit workspace-local basetemp above eliminates those errors without changing tests. A temporary browser fixture initially registered its simulated HTTP handler after Vite's fallback, causing 404 responses; moving fixture registration earlier makes the final journeys pass. These were verification-environment corrections. The two unchanged approval failures are `test_openapi_change_requires_bilingual_spec_approval` and `test_openapi_contains_only_approved_paths_and_public_error_schemas`, already recorded in MV25 and pending ML-T29. No assertion/skip/approved digest is altered. The existing Starlette/httpx deprecation remains.

ML-T14 is complete; ML-T15 is next. Self-review covers immutable intent and authoritative revision handling, unsaved evidence, source/file races, single unfinished work, physical drain, lifecycle ownership, bounded polling, safe rendering and accessibility. No batch/queue/generic lock, paid/provider/market call, production-state mutation, notification or deployment is introduced. Final API approval and whole-delivery acceptance remain pending.

## MV27. Exact prepared-plan review and creation page

ML-T14 was pushed to GitHub main at `9d08083` before ML-T15 on 2026-10-09. ML-T15 uses four scoped increments (5 / 3 / 2 / 5 primary files, eight unique including shared tests and a backend-generated fixture). Initial transport/preview and controller/component increments are `f887b7c` and `efc6df0`; route composition and the real-HTTP receipt correction land together after final verification. Paired plan/todo/evidence and browser artifacts accompany the scoped change. Existing unrelated runtime/overview-retry and Shengxin files remain excluded.

The readable preview retains all complete rules, original account facts/spans, exact 40.105-yuan unit cost, source authoring/availability/effective date, all clauses and unresolved items. Known unbound values require explicit per-field reasons; missing technical parameters, chronology, lot attribution or unresolved/unsupported clauses block review. Preservable unknown account facts remain unknown and require separate acknowledgement. Zero cash is distinct from unknown; no prices, timestamps, holdings or cost are invented. Review submits current original contents and scoped human supplements, without operations JSON or production activation.

Review uses generated `PreparationReviewInput` and the actual `PreparationFrozenView` receipt, with exact preparation/source/candidate revision and hash bindings. A confirmed receipt is followed by a bounded latest-state read; failed/stale reads cannot unlock source editing, another review or usable authority until the minimum post-review revision is observed. Unknown mutation outcomes retain the same immutable command/key. Unended work, cancellation waiting and UNKNOWN remain mutually exclusive. Confirmation clears on source/candidate/review revisions or local evidence edits; source editing immediately invalidates usable frozen authority. Late completions cannot update disposed state. Shape checks are bounded and source code points are materialized once per validation; semantic approval stays server-owned.

The existing creation page defaults to the old run form. An explicit mode choice composes one source, progress and review; an explicit preparation ID may resume readonly/current state. Merely opening the page acquires no preparation resource. Pending/unknown preparation or legacy submission blocks mode switching. New loop-run submission remains ML-T24; this is not whole-run acceptance.

| Check | Executed command/evidence | Result |
|---|---|---|
| Task gate and related UI | `npm --prefix web run test -- --run tests/unit/PlanPreparationReview.spec.ts tests/unit/PlanPreparation.spec.ts tests/unit/BacktestNewView.spec.ts` | 96 passed, including 27 task cases, 3.29 seconds. Real candidate/frozen fixture, stale receipt, unknown facts, exact retry, revision-floor failed/stale reads, source invalidation, disposal and old form are covered. |
| Full frontend | `npm --prefix web run test -- --run --maxWorkers=4`; `npm --prefix web run type-check`; `npm --prefix web run build` | 884 tests / 59 files passed, 22.59 seconds; type checking and build PASS. |
| Preparation server regression | `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_api.py tests/integration/test_plan_preparation_review.py tests/integration/test_plan_preparation_contract.py -q -m 'not live' --basetemp=.pytest_cache/ml-t15-api-review --tb=short` | 124 passed, 42.69 seconds, one existing Starlette/httpx deprecation. |
| Generated contracts | `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --monitor-contract-version 2 --check` | Canonical v2 and compatibility v1 PASS; snapshots/types unchanged. |
| Real mounted HTTP and browser | [Machine-readable journey](evidence/2026-10-09-plan-preparation-review/browser-summary.json) | Real `BacktestNewView`, mounted production preparation routes, temporary stores and fake AI. Legacy plan lookup alone is stubbed. One new extraction, explicit per-field review/freeze, exact 401050-fen cost and edit/save invalidation PASS. Widths 320 / 768 / 1024 / 1440: overflow 0, axe violations 0; console/page errors and external requests 0. Keyboard Space confirms the labelled review checkbox. |
| Visual evidence | [320-width candidate](evidence/2026-10-09-plan-preparation-review/candidate-320.png), [1440-width candidate](evidence/2026-10-09-plan-preparation-review/candidate-1440.png), [reviewed](evidence/2026-10-09-plan-preparation-review/reviewed-1440.png), [edited source](evidence/2026-10-09-plan-preparation-review/source-edited-1440.png) | Responsive full rules/account evidence, complete review and immediate source invalidation captured. |
| Mutation review | Remove the source-dirty guard from usable prepared authority, run the source-edit case, then restore exact bytes. | Mutation: 1 failed; other cases filtered. Exact restoration verified and final 96-case gate passes. |
| Documentation/worktree | Paired headings/IDs/literals, historical todo tail and MV01–MV26 preservation, unrelated-file hashes, `git diff --check` | PASS; 18 completed, 19 pending, 37 active / 39 retained IDs, 13 checkpoints. ML-C05 complete. |

The first real-browser review exposed a frontend transport mismatch: the endpoint returns a frozen receipt rather than the progress projection used by other commands. Backend review succeeded, but the client correctly retained an uncertain state on its unrecognized response. Tests were corrected to the actual generated receipt and failed before the transport/controller fix; the final mounted journey passes. A first concurrent frontend/backend verification had two unchanged 5-second lazy-route test timeouts (880 passed, 2 timed out); the complete isolated four-worker frontend run passes without increasing timeouts or weakening assertions. The initial browser date-fill syntax was corrected in the temporary harness. Chrome DevTools MCP is unavailable; installed Playwright/Chrome provides real browser checks. Temporary servers/harnesses are closed and removed.

API approval remains pending ML-T29. The two previously recorded approval gates and approved specification remain unchanged; they were not rerun in this task's 124-case preparation gate. Approved digest: `8da41a7d8d06f6a4e114570b52e88c894d0f817de365dc062bee08b28989e833`; unchanged candidate v1: `1fd4eea69dbe1827c35ca2f19a0261296be5e447f293d7a2e52c4fc8a5c9e3a4`; v2: `7e5f0a6ebec6ce3cefd440af7d9619e9332e22dd081f3f667b40a7c08473a367`. No backend/contract/approval change, live or paid call, production-state write, notification or deployment occurs. ML-T15/ML-C05 are complete; ML-T16 is next.


## MV28. Cutoff-safe selection and partial trading days

2026-10-09: ML-T16 completes from pushed `476c874`, within five primary implementation/test files and paired task/plan/verification documents. Separate `monitor-loop-dataset-v1` and `LoopFrozenSymbolDay` preserve old formats and full-day readiness.

| Verification | Execution | Result |
| --- | --- | --- |
| Task gate | `tests/integration/test_monitor_loop_dataset.py`, `tests/unit/test_monitor_loop_cutoff.py`, `tests/integration/test_backtest_compatibility.py` | 30 pass; final 2.82 seconds. |
| Related regression | Task gate plus legacy market store/index dataset/catalog queries/runner/input and loop input/schedule/cycle | 159 pass in 56.11 seconds. |
| Static checks | Ruff checking and formatting of five changed primary files | PASS; no new suppressions/skips. |
| Mutation review | Temporarily replace five-minute constituent `all` with `any`; run the missing-constituent case | 1 expected failure, 15 deselected; exact bytes restored and final task gate passes. |
| Documentation/worktree | Paired structure/stable literals, old todo tail, original MV01–MV27, unrelated-file hashes and `git diff --check` | PASS; 19 complete, 18 pending. |

One SQLite snapshot selects immutable calendar/minute/limit/daily references, retaining cutoff-eligible minute corrections in availability order and excluding later evidence. Missing closed intervals, required limits, official close or daily warm-up reject explicitly without moving the cutoff backward. Initial minute warm-up shortages remain explicit; affected rules stay UNKNOWN until sufficient complete five-minute intervals arrive. Requirements come from this complete plan, including the supported maximum 500 historical five-minute intervals. Lunch/close adds no fictitious intervals; a holiday end retains its requested date. A partial day never claims completeness.

Partial-minute recording reuses the original content hash/storage format without creating a legacy full-day `MINUTE` artifact or catalog readiness. Existing deterministic historical daily/limit availability contracts remain; this task adds no new live daily writer. Reopening reads artifact hashes only; missing/corrupt input fails without current-head fallback. ML-T17 durably copies this manifest and its dependencies with run input, so this task does not yet claim independence from market-store retention. No new database/table/migration, HTTP contract, approval, live call or production-state write occurs. API approval remains pending ML-T29. ML-T16 is complete; ML-T17 is next.


## MV29. Durable reviewed input and bounded job references

2026-10-09: ML-T17 completes from pushed `2d40768`, within five primary implementation/test files and paired records. Complete `FrozenPreparedPlan`, `MonitorLoopInput`, cutoff manifest and verified day evidence are copied to a content-addressed `.loop-inputs` directory owned by the configured result file. Existing input/snapshot tables bind canonical references; no database/table/migration is added.

| Verification | Execution | Result |
| --- | --- | --- |
| Task gate | `tests/integration/test_monitor_loop_input_store.py`, `tests/integration/test_backtest_jobs.py` | Final 28 pass in 10.71 seconds. |
| Related regression | Task checks plus legacy results/publication/migration/retention/query, preparation review, cutoff dataset and loop input | 199 pass in 27.42 seconds. |
| Static/contract checks | Ruff on five primary files; formatting of four new/touched files; both generated profiles with `--check` | PASS; unrelated pre-existing job-repository formatting is restored and contracts do not drift. |
| Mutation review | Temporarily skip dependent day validation; run the corrupt-day case | 1 expected failure, 11 deselected; exact bytes restored and final task regression passes. |
| Fault/retry | Inject atomic manifest-link failure after writing/flushing its temporary file | No input/snapshot rows, partial manifest or temporary files; unreferenced day artifacts remain and exact retry succeeds after recovery. |
| Documentation/worktree | Stable IDs/literals, old todo tail and original MV01–MV28, unrelated-file hashes and `git diff --check` | PASS; 20 complete, 17 pending. |

The directory handle stays inert; explicit persistence creates its ownership marker/artifacts. Files are flushed before atomic non-overwriting publication. Reads verify canonical content, complete review bindings, artifact hashes/timestamps and the result-reference/plan snapshot. Missing or damaged input fails without reconstruction from mutable preparation/market heads or overwriting. Removing original preparation/market rows does not change restart or repeat persistence. Synthetic five-day market data exceeds 256 KiB; the job queues only path/source/snapshot-free `inputReference` under the unchanged request limit. Existing transactions continue rejecting different unfinished tasks and mutually exclusive operations; a public-intent reservation binds the original small reference.

This completes private storage/admission, not page-executable new runs. ML-T18 connects submission, ML-T19 adds worker decoding/consumption and ML-T21 handles input/shared-artifact retention, including unreferenced copies after interruption. No API/approval change occurs; the two old approval gates were not executed in the 199-case focused regression and remain pending ML-T29. Inputs/faults use temporary offline substitutes, without live/paid calls, production-state writes or deployment. ML-T17 is complete; ML-T18 is next.


## MV30. Prepared submission and original cutoff binding

2026-10-09: ML-T18/ML-C06 complete from pushed `de339d2`. Five primary files include a narrow correction to the existing reservation transaction; its paired boundary was updated before that correction. Existing `POST /api/v1/backtest-runs` accepts closed `PreparedBacktestRunCommand`; original `BacktestRunCommand` fields and receipt/response headers stay compatible.

| Verification | Execution | Result |
| --- | --- | --- |
| Final task gate | `tests/integration/test_monitor_loop_submission.py`, `tests/integration/test_backtest_run_api.py` | 75 pass. |
| Related regression | Task gate, job repository/leases, production composition, preparation API/review, durable input, cutoff data and owned thread | 261 pass, one pre-existing environment-conditional skip, 56.51 seconds. |
| Mutation review | Temporarily disable committed reservation intent comparison; run exclusion/replay case | 1 expected failure, 24 deselected; exact bytes restored before final task gate. |
| Static/documentation | Ruff on five primary files, new file/added-region formatting, paired stable IDs/literals, original history, unrelated-file hashes and `git diff --check` | PASS; 21 complete, 16 pending. |

Public `preparationId`, `manifestHash`, `response`, `costs` and optional `endDate` form fixed intent before reservation; submission time comes from that original reservation. Start comes from reviewed source availability/effective day; an independently owned preparation service performs reads. Market freeze/copy and result-input binding stay on bounded metadata execution; renewal uses a second inert role of the same existing owned-thread primitive so long copies cannot starve it. Cancellation waits for physical copy drain before releasing reservation. Missing preparation maps to 404, stale review/missing minutes to 409, invalid end/rates/integers to 422 and unavailable owned preparation to retryable 503.

Focused testing found that a committed public key did not check changed intent. Changed response now conflicts; exact midnight replay returns its original receipt/reference without preparation lookup. Different unfinished tasks and dataset verification remain blocked by the existing single-task transaction. Actual production reader composition leaves the worker dormant; mounted HTTP keeps `Location` and `Retry-After`. No database, queue, provider call, live notification, production write or deployment is added. Tests use temporary offline inputs.

Generated publication of the new request variant remains ML-T23; final API approval remains ML-T29, without editing an approval digest or skipping gates here. ML-T19 must consume frozen references and ML-T20/ML-T21 must complete reporting/atomic retention; full execution of new runs is not yet claimed. ML-T18/ML-C06 complete; ML-T19 is next.


## MV31. Streamed causal report and honest valuation

2026-10-09: ML-T20 completes from pushed `2348d29`, within four primary implementation/test files and paired records. Existing completion verifies staged reports, so ML-T20/ML-T21 precede ML-T19 consumption; paired dependencies were corrected before implementation without adding deliverables or lowering completion standards.

| Verification | Execution | Result |
| --- | --- | --- |
| Focused report gate | `tests/unit/test_monitor_loop_report.py`, `tests/integration/test_monitor_loop_valuation.py` | 24 pass, 6.46 seconds. |
| Final related regression | Report gate, single-plan cycle, account/reminders, input/cost/time and legacy replay | 137 pass, 80.52 seconds. |
| Mutation review | Temporarily allow zero through the positive-denominator guard; run zero-opening-equity case | 1 expected failure, 15 deselected; exact bytes restored before final regression. |
| Static/scope | Ruff/format checks on four primary files, paired stable IDs/literals, original task tail/MV01–MV30 and `git diff --check` | PASS; 22 complete, 15 pending. |

Separate `backtest-report-v4` report and `monitor-loop-event-v1` envelopes distinguish evaluation, reminder, request, execution, resulting state and valuation. Committed account states point to execution, execution to its matching intent/reminder/evaluation, and refreshed evaluation to the resulting state. Ordered canonical event hashing streams without collecting the whole trail in the report; causal indexes/counts stay within existing finite bounds. Verification rejects tampering, order/count mismatch, repeated attempts, unauthorized requests and mismatched execution causes. Existing attempt callbacks/private cycle behavior stay compatible.

Opening cost `401050` fen remains distinct from market value. Historical cost P/L, interval return, fees, absolute slippage, and valid-valuation drawdown/turnover stay separate. Missing opening price is never replaced by cost or a later quote; unknown cash/holdings/cost and zero denominators null only corresponding values, preserving known zero. Original cutoff and last evidence/valuation times are explicit. End does not liquidate; pending intents remain unfilled. Existing risk exit/expiry behavior is rechecked through original scenarios. Identical input produces identical report/event bytes. Cancellation or audit write failure does not complete a cycle and cannot finish a report.

This completes projection only. ML-T21 must stream storage, publish atomically and retain the latest 30; ML-T19 then binds actual worker dispatch and ML-T22/ML-T23 add typed queries/generated contracts. Old report/export bytes, approval digests, live calls, production state and deployment are unchanged. ML-T20 completes; ML-T21 follows.


## MV32. Atomic typed publication and latest-30 total retention

2026-10-09: ML-T21 completes from pushed `9b4d95e`. Two slices and obsolete count-assertion updates were recorded before implementation; each slice has at most 5 primary files. Separate large report artifacts keep the existing 32 KiB row bound; v2 envelopes, DECISION audit family, fill ledger and existing token-atomic completion are reused without a new database/queue/scheduler.

| Verification | Execution | Result |
| --- | --- | --- |
| Final task gate | `tests/integration/test_monitor_loop_publication.py`, `tests/integration/test_monitor_loop_retention.py`, `tests/integration/test_backtest_publication.py` | 22 pass, 25.28 seconds. |
| Final related regression | Task gate, legacy results/retention/query/pinning/exports, jobs/leases, frozen inputs, account and report | 118 pass, 48.93 seconds. |
| Mutation review | Temporarily change total cap from 30 to 31 | 1 expected failure, 7 deselected; exact bytes restored before final passing task gate. |
| Static/scope | Ruff; new/changed region formatting, paired stable IDs/literals, original task tail/MV01–MV31, unrelated-file hashes and `git diff --check` | PASS; 23 complete, 14 pending. |

Publication verifies complete owned frozen inputs, report hashes/opening facts, ordered typed audit, frozen minute evidence, account settlement continuity, every fill and stage revision. Existing completion commits token-authorized materialization and job completion atomically. Missing records, cancellation, write failure, foreign input, rehashed fill tampering, stage changes and report corruption cannot produce a completed partial report. Headers and individual events keep separate semantic versions; existing storage and supported-mode export compatibility pass regression.

Total retention orders by publication/retention time, comparing absolute UTC/+08:00 times without losing microseconds, then run_id. Latest 30 materialized runs include pins; oldest excess details/fills/summaries are removed under the existing batch budget. Optional details retain original age expiry; orphan inputs/snapshots retain the existing cleanup grace before unreferenced report/frozen files are removed. Ownership markers, unknown names and retained input/report files survive; no recursive directory deletion occurs. Unfinished jobs or unreleased submission reservations defer maintenance, including expired reservations that may still own physical copying. All checks use temporary offline stores.

ML-T21 completes storage participants and maintenance itself; ML-T19 next connects worker consumption and existing post-completion maintenance. Full page queries/contracts remain ML-T22/ML-T23, final approval ML-T29. No live AI/market calls, production-state writes or deployment occur. ML-T19 follows.


## MV33. Native frozen worker and completion maintenance

2026-10-09: ML-T19/ML-C07 complete from pushed `b3a7ed2`. Request discrimination, native `loop_replay.py`, existing coordinator completion callback and tests were recorded as 5 primary files before implementation. Existing compatibility `runner.py` stays unchanged; no CLI, command coordinator, queue or cleanup scheduler is added.

| Verification | Execution | Result |
| --- | --- | --- |
| Final task/production gate | `tests/integration/test_monitor_loop_worker.py`, `tests/integration/test_backtest_job_coordinator.py`, `tests/integration/test_backtest_production_composition.py` | 46 pass, 1 existing environment skip, 22.45 seconds. |
| Final related regression | Task, publication/retention/frozen input, prepared submission, jobs/leases/API, old run API and loop | 192 pass, 79.02 seconds. |
| Mutation review | Temporarily remove reference-to-claim dataset_hash comparison | 1 expected failure, 6 deselected; exact bytes restored before final passing gates. |
| Static/scope | Ruff on 5 primary files, format checks on 4 new/touched files and added coordinator region; paired stable IDs/literals, original task tail/MV01–MV32, unrelated-file hashes and `git diff --check` | PASS; 24 complete, 13 pending. |

Worker requests discriminate immutable references and verify claim identities. Owned frozen copies spool in temporary private files ordered by availability and frozen artifact identity; mutable source/preparation/market heads, configuration/providers and scripted trades do not drive execution. Bounded rolling minute/five-minute context plus calendar/start/end boundaries feed existing private shared monitoring, reminder, response and settlement. Audit streams to disk and stages through verified publication. Warm-up grants no authority; same-time facts become visible before evaluation, without rewinding delayed old intervals into current quotes. Daily technical conditions remain explicitly unknown without frozen adjustment proof; no certified series is fabricated. End does not liquidate.

Only currently authorized jobs execute on the existing owned worker. Mutually exclusive operations reject while a task is unfinished. After token-fenced completion, the same owned thread reuses the existing repository for bounded maintenance, honoring stop between passes. Verification found and fixed progress-phase reset violating attempt-wide monotonicity and repository reconstruction causing completion-maintenance preflight races. Copied inputs run after original market records are removed and without configuration. Repeated replay reports match and verified completed results can be reused. Pre-start/mid-frame cancellation leaves no completed report, closes private files and retains the single slot until termination.

All verification uses temporary offline data and existing real composition; the environment skip and Starlette notice retain their existing conditions. Approval digests, live AI/market/notification calls, production user state and deployment are untouched. Typed result/API/pages remain ML-T22–ML-T27; final approval remains ML-T29. ML-T19/ML-C07 complete; ML-T22 follows.


## MV34. Typed loop result routes and export compatibility

2026-10-09: ML-T22 completes from pushed `f54df4e`. The paired task boundary was corrected before implementation to five primary files: existing result decoding, existing application projection, result schemas, existing run router and focused HTTP tests. No route, export format, queue, scheduler, lock or UI is added.

| Verification | Execution | Result |
| --- | --- | --- |
| Final task/export/production gate | `tests/integration/test_monitor_loop_result_api.py`, `tests/integration/test_backtest_exports.py`, `tests/integration/test_backtest_production_composition.py` | 44 pass, 1 existing environment skip. |
| Related regression | Existing result/run/query/pinning/submission/export APIs and new loop result checks | 189 pass, 56.14 seconds; final gate also includes the added backpressure check. |
| Mutation review | Remove public detail-to-native event identity comparison temporarily | 1 expected failure, 11 deselected; exact bytes restored and final gate passes. |
| Scope/static | Ruff on five primary files, changed-region formatting, paired stable IDs/literals, original task tail/MV01–MV33, unrelated-file hashes and `git diff --check` | PASS; 25 complete, 12 pending. |

Existing run list/detail/pin, fill and DECISION detail routes accept explicit `monitor-loop-result-v1`, `monitor-loop-fill-v1` and `monitor-loop-event-v1` variants. Native typed evidence retains its original field names, causal hashes, sequence and times. The full result binds `backtest-report-v4`, one frozen plan, source/review/input provenance, the original opening account, response and exact costs. It omits raw source text. Legacy UUID plan filtering stays separate from the prepared stable version ID. Unknown cash/equity and known zero remain distinct; legacy daily equity is NOT_RECORDED rather than fabricated. Expired details retain the verified header/provenance; pin replay retains identical native report bytes.

List/event/fill records retain 32 KiB and pages retain 100 items/below 4 MiB. The separate full loop header is bounded below 4 MiB, without raising legacy item limits. Query and typed projection use the existing owned metadata thread. A held projection preserves event-loop progress and rejects excess backtest work with scoped 503/Retry-After; no second executor or admission framework is introduced. Supported legacy CSV/JSON checks pass unchanged. Loop export requests return 409 before stream/download headers, without inventing a new exporter. Stable cursor paging preserves every native event exactly once. All verification is offline; approval remains pending ML-T29. ML-T23 follows.


## MV35. Generated run and result contracts

2026-10-09: ML-T23 completes from pushed `bd7a221`. Actual schema/type checks exposed optional native discriminator defaults and three existing table assumptions. Before extending changes, the paired task records three slices: generator/tests, four generated profiles, and three existing tables/API fixture. Ten primary files retain the existing routes and generator; complete result experience remains ML-T25.

| Verification | Execution | Result |
| --- | --- | --- |
| Final task gate | `tests/integration/test_monitor_loop_contract.py` | 11 pass, 7.73 seconds. |
| Related contracts | Task, preparation contract, both-profile drift and OpenAPI checks apart from the two pending approval gates | 50 pass, 2 deselected, 57.48 seconds. |
| Frontend | `BacktestResultTables.spec.ts`, `BacktestRunsView.spec.ts`, `backtestsApi.spec.ts`; frontend type-check | 114 pass; type-check PASS. |
| Generation | `scripts/generate_frontend_types.py --check` | Both existing profiles current. |
| Mutation review | Temporarily bypass discriminator-aware TypeScript rendering | 1 expected compile/type failure; exact generator bytes restored, final task gate passes. |
| Pending approval | `test_openapi_change_requires_bilingual_spec_approval`, `test_openapi_contains_only_approved_paths_and_public_error_schemas` | 2 expected failures; unapproved digest/preparation path scope still awaits ML-T29. |

Snapshots add 32 supporting schemas and remove no schemas or paths. Prepared submission and old submission remain distinct alternatives, as do old/full loop summaries and typed causal details/fills. Loop payload discriminators require their mapped literal in TypeScript union context even when a standalone native model supplies a default; standalone defaults and the underlying HTTP schema remain unchanged. Exhaustive switches and invalid-mode/version/unknown-cash probes compile as expected. Existing single source, 200 opening lots, 100-item pages, safe-integer bounds, exact decimal strings and nullable metrics remain. Public prepared submission excludes manual opening overrides, multiple plans and recorded-action policy. Result references resolve without copied-source/path/claim data.

Existing tables handle new typed rows and actual account/fee facts, displaying unavailable fields honestly. No browser trading rules, new timeline, export, route or service is introduced. Paired task/evidence literals and IDs, original task tail/MV01–MV34, unrelated-file hashes, Ruff and whitespace checks pass. The approval digest and approved path set stay unchanged; their independently observed failures are recorded rather than suppressed. ML-T23 completes; ML-T24 follows.


## MV36. Prepared single-plan run creation

2026-10-09: ML-T24 completes from pushed `eb6d083`. Seven primary files, recorded before expansion, extend the existing API/composable/form/page and three focused or existing test files. The existing accessibility fixture gains fields without removing assertions. No new routes, task coordinator, client trading rules or account override is introduced.

| Verification | Execution | Result |
| --- | --- | --- |
| Final task and related gate | `MonitorLoopRunForm.spec.ts`, `BacktestNewView.spec.ts`, `BacktestAccessibility.spec.ts`, `backtestsApi.spec.ts`, `PlanPreparation.spec.ts`, `PlanPreparationReview.spec.ts` | 195 pass, including 11 prepared-run checks; 2.49 seconds. |
| Frontend types | `npm --prefix web run type-check` | PASS. |
| Mutation review | Remove the unknown-outcome edit guard from the existing composable | 1 expected failure detects a second semantic submission; exact bytes restored before final gate. |

The prepared variant submits only the current reviewed preparation/manifest, response policy, exact costs and optional end. Extracted cash, lots and snapshot time are readonly; unknown and zero retain their meaning. The existing review continues to show unsupported clauses and missing facts. End omission delegates resolution to the service; the form explains that the frozen exact cutoff is supplied by the completed result boundary, whose full presentation is ML-T25. No browser clock manufactures a cutoff. Malformed shape, extra initial account, multiple plans, recorded actions, invalid dates and unsafe absolute slippage are rejected before sending.

Submission uncertainty locks fields and mutually exclusive source/extraction/review/mode operations. Retry sends the original frozen body and idempotency key. Accepted receipts retain the existing run/job navigation. Old run creation, preparation acquisition/review and accessibility regressions pass. ML-C08 completes using unchanged legacy export evidence from ML-T22; native exports still return the explicit existing conflict. Original task tail/MV01–MV35, bilingual literals/IDs and unrelated hashes remain intact. Shared page-caption edits stay outside the task commit. Final API approval remains ML-T29; ML-T25 follows.


## MV37. Native single-plan result review

2026-10-09: ML-T25 completes from pushed `ce64a66`. Ten primary files were recorded before expanding the original four-file slice: native HTTP validation/actual fixture, readonly result presentation, and existing composable/pin integration. One existing legacy-only API assertion gains a type guard without dropping its check.

| Verification | Execution | Result |
| --- | --- | --- |
| Final task and related gate | `MonitorLoopResults.spec.ts`, `backtestsApi.spec.ts`, `BacktestRunDetailView.spec.ts`, `BacktestResultTables.spec.ts`, `BacktestResultActions.spec.ts`, `BacktestRunsView.spec.ts` | 157 pass, including 17 native result checks; 2.57 seconds. |
| Frontend types | `npm --prefix web run type-check` | PASS. |
| Real Chrome | Isolated local Vite harness with actual publication HTTP fixture | 1440/390 pixels, 32 causal events, 2 selected-resource requests; no runtime error or horizontal overflow. Summary/timeline screenshots visually inspected. |
| Mutation review | Remove native input/provenance identity binding | 1 expected failure; exact validator bytes restored before final gate. |

The fixture comes from the existing private publication/result HTTP setup with fake providers and temporary stores. Native run, summary, event and fill variants use independent bounded transport checks and identity links; native versus old detail/fill mixing is rejected. Timestamp identity compares exact Shanghai instants across the public microsecond and embedded native representations. Frozen source revisions, one full reviewed plan, opening/final cash and inventory, exact service boundary and nullable metrics are readonly. Current-page causal events distinguish observation, reminders, intents, blocked/closed attempts, actual fills, account state and valuations. Reason IDs may refer to preceding pages. Unknown/zero and expired/unrecorded resources remain distinct; no reconstruction or client trading calculation occurs.

Existing URL/cursor fences and one-page fetch behavior are reused. Native pin receipts preserve report identity; unsupported native export links are hidden while legacy exports/actions remain compatible. Reference-index data is not advertised or fetched for this native result. Shared page-caption edits remain outside this commit. Original task tail/MV01–MV36, paired IDs/literals and unrelated hashes remain intact. No new route, export format, job/lock framework or plan-switch history. Final API approval remains ML-T29; ML-T26 follows.


## MV38. Independent parity and failure atomicity

2026-10-09: ML-T26 / `d026006`. 89 backend checks pass, including independent 15-evaluation online parity, two literal expected fills and account/publication/worker/preparation faults. Causal identity mutation fails as expected; exact bytes restored. Actual HTTP fixture refreshed. ML-T35 follows; final approval remains ML-T29.

The independent online workflow uses actual public simulation participants; expected money values never become replay inputs. Future dataset changes preserve earlier semantic event IDs. Run membership remains explicit and the full stream digest still includes it. Injected commit/handoff/release failures preserve unfinished admission, roll back complete transactions and allow exact-request retry without duplicate settlement or external AI/market/notification/HTTP calls. Six primary files were recorded in two slices before expansion; no new schema fields or execution policy.


## MV39. Inert service status and explicit controls

2026-10-09: ML-T35 / `eedbae1`. 77 checks pass with one existing environment skip. Epoch/revision/idempotency, one selected resume, cached first-use failure, physical-drain repair, inert status/stop and bounded 1000-receipt history pass. Removing the epoch fence produces one expected failure; exact bytes restored. ML-T39 follows.

Five primary files, including lifecycle ownership, were recorded before expansion. Three routes expose lightweight state and capabilities or accept explicit controls within the existing local-origin/mutation guards. Control acknowledgement does not await heavy initialization, resume or stop completion; only accepted controls advance the revision. Whole-app cleanup observes owned control work. Retry does not submit a run or paid extraction; status/data polling cannot repair cached failure. Old boot epochs and changed intents conflict. Generated publication is ML-T39 and final API approval remains ML-T29.


## MV40. Generated independent lifecycle contracts

2026-10-09: ML-T39 / `d14d638`. 37 contract checks and frontend type checking pass; both generated profiles are current. The two existing approval gates remain pending ML-T29 with snapshot dde2866b81a9710a51bf7817eeeb30513cfb4e844437adba7a2ef202fd52caa0. Expanding resume bounds produces two expected failures; exact bytes restored. ML-T36 follows.

Five primary files publish the three mounted lifecycle operations, state/capability fields, closed commands, safe revisions and <=1 selected job in both profiles. All prior routes/schemas retain exact mounted meaning. Controls return 202 with original Location/Retry-After and existing public error envelopes. No duplicate handwritten transport models, approval stamp or suppressed gate.


## MV41. Scoped first-use and recovery UI

2026-10-09: ML-T36 / `71e5c56`. All 935 frontend checks, type checking and production build pass. Real Chrome verifies readonly history and one explicitly confirmed resume at 1440/390/320 pixels, with no runtime error or overflow. Removing 503 intent retention produces one expected failure; exact bytes restored. ML-T27 follows.

Six primary files were recorded in two slices. The shared shell lazily mounts service UI only on an active backtest route; code prefetch and monitor navigation make no service request. Status polling is inert, slows on failure and stops on disposal. Recovery selection loads only on explicit request and requires confirmation for exactly one job; unknown controls retain original body/key. Scoped 503 retains existing run form and exact submission key. No history opening resumes jobs or AI. Shared unrelated shell edits are preserved through a separate task-only index.


## MV42. Complete mounted browser journey and frozen identity

2026-10-09: ML-T27 / `6c1c630`. Two real Chrome journeys, 75 backend checks, 96 frontend checks and type checking pass. The browser found and verified narrow navigation and authoritative frozen identity corrections. Removing the frozen identity projection produces one expected failure; exact bytes restored. C09 passes; ML-T37 follows.

The disposable loopback server mounts production composition, stores, coordinator and native worker. Only external AI/market facts are fake; no preparation/trade/result scripts are seeded. The original 503 body/key survive explicit scoped repair. Source revision 2 requires a fresh extraction/review; actual replay produces one causal fill, 102396 cash fen and 200 shares at the frozen cutoff. Unknown cancellation retains admission across monitor navigation/reload and requires explicit ended confirmation. Real graceful server shutdown drains owned work before stopping monitoring. The test-only clock also binds actual retention, preventing fake historical jobs from expiring under wall time. API paths/fields and snapshot bytes are unchanged. Shared user caption/theme edits remain unstaged.


## MV43. Windows lazy ownership and admitted thread load

2026-10-09: ML-T37 / `e1b19f5`. Windows 600/600-second ten-stock load passes with 5 completed sequential native runs, 12000 exact evaluations and no duplicated/missing semantic reminders. The final 209-case affected regression and 131 shared runtime/accounting checks pass with one existing environment skip; Ruff passes. Public fill identities remain stable with run-bound internal storage; legacy exact retry passes. Initial unpaced failure is retained; all original gates remain. ML-T37 completes; ML-T28 follows.

Eleven recorded primary files cover actual lazy activation/concurrent first-use/backlog/late-work/drain faults, ten-stock BACKGROUND sync pacing and real admitted replay. A fourth sequential response-delay variant exposed collision of causal receipt IDs in a global SQLite fill primary key. Only internal stored fill IDs now bind run identity; authority/public receipt and audit identities remain exact. Publication validates the exact new or legacy record once per receipt; retrying an old staged row adds no duplicate. No schema, route, monitor-rule or resource-controller change.

The initial unpaced 600/600-second stress failed the fixed monitoring cadence: the baseline completed 6000 evaluations; the load completed only 5790 / 579 ticks of the required 6000 / 600. Its terminal timestamp was 2026-09-22T10:19:38+08:00. Phase assertion prevented load percentile return, so no failed-load percentile is claimed. Replaying five more monitor ticks against the accumulated temporary history without replay measured 0.798 / 0.761 / 0.770 / 0.770 / 0.769 seconds per ten-stock cycle. Per ML17's explicit reduce-admitted-load rule, only the offline controller was paced to >=120 seconds between native admission starts; thresholds, 600-second phases, 1-second monitoring cadence and all completeness assertions remain exact. The second paced long run was interrupted by a measurement-only FileNotFoundError after SQLite legitimately removed a listed WAL file. The probe now treats only a disappeared file as zero and still propagates permission/other stat errors; its controllable race/failure case and the then-current six-case matrix passed in 13.56 seconds. The interrupted baseline/failure is retained in ignored `.pytest_cache/ml-t37-failed-wal-probe.json`. The third five-second run completed both 6000-evaluation phases but failed with real submission SQLITE_BUSY during strict retained-input maintenance; load schedule p99 was 7340.370 ms, exceeding the original gate. That report remains in ignored `.pytest_cache/ml-t37-failed-maintenance-load.json`. Only actual SQLITE_BUSY/SQLITE_LOCKED metadata errors now become the existing 503/Retry-After, with unchanged intent retry and other SQL faults preserved. The final profile admits at most five native experiments per ten minutes, retaining the original monitoring workload and all gates. It does not certify high-frequency retained-history stress. The fourth 120-second profile completed only 596 ticks / 5960 evaluations and 1074 status samples in 603.366 seconds; load status p95/p99 was 81.603/108.270 ms and schedule p99 7003.955 ms. Its report is preserved in ignored `.pytest_cache/ml-t37-failed-monitor-cost.json`. Profiling that actual accumulated history measured 0.9644695 seconds per ten-stock cycle, with 0.631 seconds in 20 duplicate legacy scans and 24390 JSON decodes. SQL candidate filtering reduced the same cycle to 0.6655926 seconds and 310 decodes; one transaction-local legacy result now replaces the second identical scan. Invalid/non-object/duplicate-key/escaped-key/non-finite payloads retain the original Python behavior. No persistent cache or historical mutation is introduced. The 131-case shared accounting/runtime/parity regression passes in 74.43 seconds after those changes. The new bounded-run controller refuses admission at the nominal phase deadline, including when a final monitor tick is still draining. All four failed long measurements are retained; none is reclassified as a pass. The final paced run below is the accepted workload.

Host: Windows 11 10.0.26200, Python 3.14.7, 24 logical CPUs, 33751425024 bytes RAM (31.43 GiB), local SSD temporary stores. Read-only hardware inventory records Samsung SSD 990 PRO 1TB (1000204886016 bytes) and YMTC YMSS2ED08D25MC (1024209543168 bytes). Disposable root: `C:\Users\xiedc\AppData\Local\Temp\backtest-thread-load-h9yriuba`. No live provider, paid AI, notification or user database access.

| Measurement | Baseline | Admitted replay load |
|---|---|---|
| Phase / elapsed seconds | 600 / 600.001 | 600 / 600.000 |
| Status samples | 1200 | 1200 |
| Status p95 / p99 (ms) | 18.683 / 21.382 | 27.385 / 41.381 |
| Monitor schedule p99 (ms) | 1.973 | 2.158 |
| Evaluations / new steady-state reminders | 6000 / 10 | 6000 / 0 |
| RSS start / peak / end (bytes) | 254697472 / 255651840 / 212119552 | 222093312 / 499605504 / 233811968 |
| WAL peak (bytes) | 4194192 | 5665096 |
| Backtest thread peak | 0 | 7 |

Added status p95: 8.702 ms <=100 ms; added monitor scheduling p99: 0.185 ms <=250 ms. Both status p95 <=250 ms / p99 <=1000 ms and >=1000 samples pass. Exactly 6000 evaluations occur in each phase, with ten initial reminders and zero extra reminders while signals stay READY. Native completed runs: 5; admission p95: 784.769 ms (observed, not a new gate). One monitor start/stop and complete owned-thread drain pass. RSS/WAL are observations without production memory/disk thresholds or a leak-free guarantee. This certifies the measured paced fixture, not unrestricted stress or live production traffic.

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_isolation_fault_matrix.py tests/integration/test_backtest_sync_pacing.py tests/integration/test_monitor_loop_parity.py tests/integration/test_monitor_loop_publication.py tests/integration/test_monitor_loop_worker.py tests/integration/test_monitor_loop_result_api.py tests/integration/test_monitor_loop_retention.py tests/integration/test_backtest_run_api.py tests/integration/test_backtest_job_api.py tests/integration/test_backtest_data_api.py tests/integration/test_backtest_production_composition.py -q -m "not live" --basetemp=.pytest_cache/ml-t37-final-after-history --tb=short
.venv/Scripts/python.exe scripts/verify_backtest_thread_load.py --profile windows-threads --offline
```

The final affected Python command passes 209 cases / one existing environment skip in 108.57 seconds, with one existing Starlette/httpx deprecation notice. The controlled real SQLite lock first fails with one raw-error case / six deselected, then passes with an exact original-intent retry, zero partial admissions, monitoring still serving and other SQL faults preserved. Removing the run-bound stored fill key yields one expected fourth-run failure / four deselected; exact bytes restored and the final 209-case gate passes. Ruff checks the Python primary files and the JSON fixture parses exactly and whitespace checks pass. The three-second paced smoke passes only as a development probe. Raw final output remains in ignored `.pytest_cache/backtest-thread-load.json`; the original failed run is retained in ignored `.pytest_cache/ml-t37-failed-long-load.json`. Final interface approval remains ML-T29.


## MV44. Operation guide and final executable checks

2026-10-09: ML-T28 / `62324ed`. Paired operations cover the implemented single-plan source/review/run/result workflow, exact account/cutoff semantics, single unfinished task, cancellation/unknown recovery, export compatibility and measured-load limits. Final relevant checks pass: 58 backend, 935 frontend, type checking, build, 34 real Chrome journeys, Ruff and both generated profiles. Two unchanged exact API approval gates remain pending ML-T29; their actual failures are retained. ML-T28 completes; ML-T38 follows.

Five primary files add the paired operation guide, actual execution record and verified legacy browser fixture correction. The task changes no runtime/API/UI implementation. The initial full Chrome run had 6 failures / 28 passes in 100.76 seconds: five strict audits rejected the formerly unhandled service-status GET; one original 200-percent layout check observed 16px rather than 32px. Only the explicit status fixture was added; all original error/request/zoom/overflow assertions and UI bytes remain unchanged. The focused original keyboard/a11y and 200-percent layout cases then passed in 6.6 seconds. The failed full log remains in ignored `.pytest_cache/ml-t28-initial-failed-e2e-0.log`; the final full run below is the accepted result. All checks use local fake providers and disposable stores; the full browser suite includes existing monitor and backtest compatibility flows. The two failures below are the previously known bilingual approval identity and 52-path allowlist, resolved only after the final scoped review in ML-T29. No assertion is weakened or marked skipped. Timings include command startup.

| Command | Observed result | Wall seconds |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest tests/unit/test_unified_replay_input.py tests/integration/test_unified_replay.py tests/integration/test_unified_replay_parity.py tests/integration/test_unified_runtime.py tests/integration/test_unified_simulation_transactions.py -q -m 'not live' --basetemp=.pytest_cache/ml-t28-final-backend --tb=short` | 58 passed; one existing deprecation notice | 98.75 |
| `.venv/Scripts/python.exe -m ruff check src tests scripts` | Passed | 0.22 |
| `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | Passed | 11.60 |
| `npm --prefix web run test -- --run` | 935 checks passed | 13.68 |
| `npm --prefix web run type-check` | Passed | 5.59 |
| `npm --prefix web run build` | Passed | 1.72 |
| `npm --prefix web run test:e2e` | 34 real Chrome journeys passed | 86.96 |
| `.venv/Scripts/python.exe -m pytest tests/integration/test_openapi_snapshot.py -q -m 'not live' --basetemp=.pytest_cache/ml-t28-pending-api-approval --tb=short` | 2 failed, 12 passed; pending ML-T29 | 24.72 |

No live AI/market-provider certification is claimed. The original 600/600-second load gates and all four failed attempts remain in MV43; this documentation task does not rerun or relabel them. Existing unrelated workspace edits are preserved and excluded from this commit. The focused backend reports one existing Starlette/httpx deprecation notice; it is not a failure.


## MV45. Service lifecycle operations and accepted thread boundaries

2026-10-09: ML-T38 / `32921ee`. Paired guidance records dormant startup, explicit metadata/execution authority, one selected resume, scoped repair, accepted controls versus physical drain, boot/revision/idempotency fences and accepted shared-process limits. Actual MV43 load and MV44 final/browser evidence are referenced without rerunning or broadening them. C13 completes; only ML-T29/C10 final reviewed approval remains.

Four primary operation/verification documents record ML-O08/ML-O09. Status remains inert; READ_READY/READY grant no automatic backlog authority. Stop/recovery acknowledgement is 202 with the original epoch/revision/body/key; STOPPED requires physical drain and unknown durable work still needs explicit confirmed recovery. Resume selects exactly one job. Seven bounded owners share process CPU/memory/disk; no forced thread termination, hard resource ceiling or mandatory process phase is promised. Historical U04/MV12 approval mismatch and its scoped correction are retained. This documentation-only task verifies bilingual section/field/path/limit parity and whitespace; executed fault/load/UI results remain MV39–MV44. No runtime, generated interface or unrelated workspace edits are included.


## MV46. Final reviewed contracts and exact API approval

2026-10-09: ML-T29 / `e7d36e7`. Final review retains all 52 original paths, approves exactly 10 additions and the documented additive native branches, preserving historical identities. Both reviewed snapshots/types match committed source. The exact allowlist, bilingual approval, public-error and generated TypeScript gates pass: 51 integration plus 18 service-value checks. Removing one approved path fails; exact bytes restored and the gate passes. C10 completes; all 37 active tasks and the user-requested 20-task sequence are complete.

Five primary files record the concrete final contract review in the paired proposal/U09 and add only the 10 reviewed literals to APPROVED_PATHS. Existing exact path equality, digest, public-error and all other assertions remain byte-equivalent. Compared with 7a92f75, both profiles retain 52 paths, add 10, modify only two existing path items and three existing schemas through the reviewed branches, add 108 reachable schemas and remove none. U04 retains the earlier a0915f7 mismatch and its 7a92f75 scoped correction. Final LF snapshot identities are dde2866b81a9710a51bf7817eeeb30513cfb4e844437adba7a2ef202fd52caa0 / d34ffd622021a50127a6f92cbf81be8323884f1f5b2dc36e529a7ca2c0b9c807.

Checks run in an isolated e7d36e7 checkout plus the five reviewed files, with Python package origin asserted under that checkout. Other in-progress index-display changes, including a newly added path in the shared allowlist, remain outside this review/commit. Only the reviewed test version is staged; working edits are preserved. The first setup attempt rejected same-basename integration/unit collection and CRLF checkout artifacts. Subsequent setup checks rejected an LF entry mismatch, absent TypeScript compiler and absent Node declarations. Standard bytes were read directly from committed Git blobs, and installed TypeScript/Node/undici declarations were privately copied; no source, generator or assertion was weakened. Earlier setup logs remain in ignored .pytest_cache/ml-t29-initial-isolation-gates.json, .pytest_cache/ml-t29-dependency-isolation-gates.json and .pytest_cache/ml-t29-node-types-isolation-gates.json.

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_openapi_snapshot.py tests/integration/test_backtest_service_contract.py tests/integration/test_monitor_loop_contract.py tests/integration/test_plan_preparation_contract.py -q -m "not live"
.venv/Scripts/python.exe -m pytest tests/unit/test_backtest_service_contract.py -q -m "not live"
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
.venv/Scripts/python.exe -m ruff check tests/integration/test_openapi_snapshot.py
```

Final results: 51 integration cases pass in 38.05 seconds; 18 service-value cases pass in 0.44 seconds. Both-profile generation verification passes in 4.63 seconds and Ruff passes. Removing /api/v1/backtest-service from the isolated exact allowlist produces one expected failure / 13 deselected in 2.76 seconds; exact original bytes are restored, then one pass / 13 deselected in 2.51 seconds. Main reviewed literals and all original assertions are independently compared with the prior committed file. Bilingual sections/fields/paths/limits and whitespace pass. The broader backend/frontend/build/browser and original load results remain MV43/MV44; they are not rerun or extended by this specification task.
