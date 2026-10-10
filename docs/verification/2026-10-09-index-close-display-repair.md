# Verification: index-close-display-repair

Chinese review copy: [2026-10-09-index-close-display-repair.zh-CN.md](2026-10-09-index-close-display-repair.zh-CN.md).

## ICDV01 Authorization and scope

The user authorized implementation and acceptance against [ICDR01–ICDR10](../specifications/monitoring/SPEC-index-close-display-repair.md) on 2026-10-09. Only the index effective-head/acquisition chain, final-bucket recovery, bounded display API, existing index components, generated contracts and their tests/documentation changed. Existing concurrent work is preserved. No new provider permission, endpoint, dependency, normal acquisition frequency, plan eligibility or turnover formula is introduced. No commit or push is part of this work.

## ICDV02 Root cause and resulting behavior

Later failed captures previously replaced a successful same-key durable head, while the process retained success in memory. The chart followed that poisoned head and the UI mapped acquisition failure directly to 阻断. The repair shares capture-order selection, keeps failed attempts separately, and renders trusted exchange session separately from display completeness. Quote, return, high/low/amount and line are assembled from one immutable snapshot in one readonly transaction. SSE is the default selected index. No display fallback replaces a failed plan input.

The final 11:30/15:00 target has at most 3 supplemental starts at +72/+132/+252 seconds before target +5 minutes. A reason change, ordinary transient exhaustion or process restart cannot reset its budget. Late/slow work has no catch-up burst; permission, cooldown, source/generation and commit gates remain effective. Ordinary transient 30/60/120-second recovery and 15:20/16:00/17:00 reconciliation stay intact.

## ICDV03 Acceptance evidence

| IDs | Evidence |
|---|---|
| A01–A02 | Actual SQLite persistence/reopen retains the LIVE hash, 3813.791 and all 48 bars after a later failed capture; latest acquisition remains separately BLOCKED. |
| A03–A04 | Older/failed targets cannot become current plan evidence; a newer valid correction with smaller numeric revision wins by acquisition order. Actual persistence also accepts a newly reobserved stored revision while preserving its original immutable payload/time; an intermediate out-of-order correction cannot regress the head or latest attempt. |
| A05–A06 | Fake clock/provider plus the real scheduler and reopened SQLite prove both session boundaries, only-lagging-index requests, fixed deadlines, expiry, at most 3 starts, cooldown/permission deferral, source mismatch, in-flight generation/configuration revocation, slow completion and reason-change exhaustion. |
| A07–A08 | 47 bars/internal gaps remain INCOMPLETE. Trusted preopen, lunch, close, non-trading date and midnight use explicit dates/targets; unknown calendar never certifies closed/current. Preopen startup repair selects strictly the previous trading day. |
| A09 | Source mismatch remains cached; configuration/generation/admission/semantic revocation cannot certify current data. Read authority checks publish nothing. Corrupt latest-attempt identity returns sanitized 503 without changing stored evidence or sequence. |
| A10 | Frontend coalescing, cancellation and generation/sequence guards retain/replace one complete envelope; failed or obsolete responses retain the original data as cached. |
| A11 | Poisoned exact-key heads repair from validated stored LIVE captures. A second repair changes nothing. Snapshot payloads and historical decision references remain intact. |
| A12 | Missing prior close retains point/bars with null return and UNVERIFIED status; any missing returned-bar amount yields null total; empty cards and transport caching remain honest. |
| A13 | Signed history still returns the 48th final bar; original DTOs/cursors and official-close/turnover contracts stay compatible. Strict additive schemas, exact four cards, no-store and the 512 KiB bound are tested. The API reads one SQLite transaction with no DML or provider call. |

Focused final backend index/session/persistence/recovery/history/web acceptance: 119 passed. The source/composition/official-close/history regression group passed 47. The frontend overview group passed 7 including the added obsolete-generation/sequence cases. Browser acceptance passed the existing 4 dashboard tests plus 5 close/interface tests. At 320/768/1024/1440, the closed SSE card has no blocking badge or live pulse; the actual ECharts series has 49 rendered points (one synthesized 09:30 opening plus 48 completed bars), final time 15:00 and value 3813.791 matching the headline. Keyboard selection, reduced motion, 200% text and accessibility checks pass.

## ICDV04 Full regression and build

- Backend unit directory: 2927 passed; contract/history/replay directories: 13 passed, 4 live cases deselected.
- Backend full integration directory: 3833 passed, 29 failed, 1 skipped (4709.13 seconds). Final-code rechecks resolved all 26 directly related migration/contract/persistence failures: migration files 113 passed; permission/old-contract files 8 passed; persistence/monitor-loop/OpenAPI/plan-composition group 58 passed with only the two unrelated baseline lifecycle assertions still failing. The original 100k-export performance case passed alone in 234.89 seconds with unchanged thresholds. Competing regression load is a plausible explanation for the earlier throughput failure, rather than a demonstrated product regression.
- Frontend complete unit suite: 942 passed with file parallelism disabled. The parallel run reached 940 passed and two 5-second lazy-route-loading timeouts under competing full-regression load. Assertions and timeouts were unchanged for the successful isolated run.
- Frontend type check, both generated monitor contracts, scoped Python lint and diff whitespace checks pass.
- Production Vite build passes using an isolated output and the existing v2 plugins, with the distribution-copy plugin omitted until coordinated rollout. Running assets are untouched during staging.

The one-command backend collection encounters existing same-named backtest test modules; importlib mode also conflicts with existing sibling imports. Full offline coverage is therefore executed by directory. Migration expectations now explicitly include `0025_index_close_display` and the new table; the old-version contract comparison explicitly includes the sole authorized overview path. Historical migration targets, row/sequence preservation, permission/physical-request assertions and every existing path/schema comparison remain intact. Existing Starlette/httpx deprecation and the temporary staging-config loader warning are unrelated and do not fail checks.

```powershell
.venv/Scripts/python.exe -m pytest tests/unit -m "not live" --basetemp data/icdr-full-unit-1815 -q
.venv/Scripts/python.exe -m pytest tests/integration -m "not live" --basetemp data/icdr-full-integration-1810 -q
.venv/Scripts/python.exe -m pytest tests/contract tests/history tests/replay -m "not live" --basetemp data/icdr-full-other-1818 -q
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run --no-file-parallelism
npm --prefix web run build -- --config ../data/icdr-build-stage.config.ts
npm --prefix web run test:e2e -- dashboard.spec.ts index-close-display.spec.ts interface-design.spec.ts
```

Actual-data read latency was 3012.8 ms. After reading the complete target first under a known calendar and falling back only when missing, three measurements were 78.1/51.7/53.9 ms. A new regression rejects whole-history scanning under a known calendar; all session/fallback acceptance tests passed (37).

## ICDV05 User-data rehearsal and local rollout

A consistent readonly backup of the running user database was migrated/repaired in an isolated directory first. Rehearsal result: 0 head repairs, 5 reliable acquisition backfills; second run (0,0). Existing 17:00 reconciliation had already restored current heads. Four cards retain 48 bars through 15:00, respectively 3813.791, 12641.858, 3043.335 and 1457.267. Old records without source provenance remain CACHED rather than being assigned invented authority. The original user database was unchanged by rehearsal.

Local rollout completed on 2026-10-09. The previous owner drained normally in 0.41 seconds and released port 8765. Before migration, a consistent SQLite backup with a successful integrity check was saved to [monitor-before-0025.sqlite3](D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor/data/backups/index-close-display-20261009-193513/monitor-before-0025.sqlite3). Migration reached `0025_index_close_display`, repaired 0 heads and backfilled 5 acquisitions. All 1906 immutable snapshot rows were compared and preserved; the decision count remained 0. The frontend was published after migration by adding staged hashed assets and replacing the entry HTML last; all 57 previous assets were retained. The restarted owner reports RUNNING/STANDBY with NO_ACTIVE_PLANS, database/WAL READY and no active or waiting workers. Its generation is `49fe951d-7f5e-4ac2-9bf5-de85d25acfaf`.

Actual HTTP acceptance returns KNOWN/CLOSED for 2026-10-09 with the expected 15:00 target. All four cards contain 48 bars through 15:00; their points match the final bar and their returns match the same snapshot's prior close. The response is 66809 bytes, `Cache-Control: no-store`, and three reads take 90.9/59.1/54.7 ms. Signed legacy history also returns all 48 bars. Historical source identity is unknown, so the four display states honestly remain CACHED.

Actual browser acceptance passes against the restarted service and published build: default SSE, point 3813.79, cutoff 15:00, 已收市 · 已缓存, no 阻断 badge or live pulse, and successful switching across all four indexes. There are no console errors or failed requests. The full-page result was visually inspected in [icdr-live-closed.png](D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor/data/icdr-live-closed.png). The first 5-second check preceded the existing connection heartbeat; a second check within a 40-second window received the heartbeat and loaded the overview normally. Connection-handshake behavior and heartbeat intervals were not expanded into this repair.

## ICDV06 Limits and completion

All regression providers/clocks are offline fakes. The displayed value is a completed five-minute close; this work does not independently certify an official daily settlement or guarantee an upstream publication delay. Corrupt metadata fails closed; unknown historical provenance remains explicit. Rollback must use the stopped consistent backup or a compatible reader. The migration refuses downgrade with FINAL_BUCKET or attempts>2 records; an old writer must not discard pending/exhausted budgets.

The two remaining baseline lifecycle tests require eager backtest startup, while unchanged `web/lifespan.py` uses `LazyBacktestLifecycle`. Their custom fake lifecycles do not touch index composition, selection or reads. The application, lifecycle module and these tests have no changes against HEAD. They are retained as known failures; no unrelated backtest behavior or assertions are modified.

Final completion: A01–A13 and local rollout are accepted within the authorized index scope. The full regression is not entirely green: the two recorded, unchanged backtest lifecycle failures remain outside this repair. The paired focused task plan is complete without replacing ongoing backtest work.

## ICDV07 Related monitor and presentation acceptance

The preceding overview investigation reproduced three defects: a second wall-clock read rejected an already elapsed immediate wake; the legacy DEGRADED projection omitted a timestamp required for a physically STOPPED owner under monitor contract `2`; and explicit quota wording was misclassified as permission denial. Elapsed wakes now use zero delay while retaining the 30-second future limit and existing token/overdue/owner guards. STOPPED reads retain actual owner health, generation and timestamp. Explicit rate-limit wording installs the existing cooldown; structured authorization errors and genuine permission denials still block. The original October 8 provider reply was not retained, so the classification defect is not established as the cause of that specific reply.

Focused scheduling/lifecycle checks passed 37, broader monitoring checks passed 225, and provider/cooldown/permission checks passed 413. On October 9 the unchanged configured service and credential returned HTTP 200/code 0 for `trade_cal`, `idx_mins`, `rt_idx_min_daily` and `index_daily`; no additional entitlement or permission reset was required. These are dated observations, not continuing live-provider certification.

Retry/refresh reads stored display data; it does not call the provider or restart a stopped runtime. Ordinary acquisition follows completed five-minute boundaries plus the existing 12-second publication grace and automatic recovery. Transport connectivity alone does not prove current data. Subsequent startup/final-bucket display behavior is governed by ICDR01–ICDR10 and ICDV02–ICDV05.

The requested presentation changes remove numbered English page captions and the overview management button, and place the connection banner above backtest navigation. Chinese headings, descriptions and accessible actions remain. The caption removal's original checks passed type checking, 118 unit tests in 7 files, 6 browser cases, production build and visual inspection. Current combined checks are recorded below.

## ICDV08 Final-code verification on 2026-10-10

- Related backend regression: 183 passed, covering scheduling, quota handling, composition, persistence, recovery, session, overview and OpenAPI.
- Complete frontend unit suite: 942 passed in 63 files with file parallelism disabled.
- Browser acceptance: 9 passed across `dashboard.spec.ts`, `index-close-display.spec.ts` and `interface-design.spec.ts`.
- Type checking, generated canonical v2/compatibility v1 contracts, scoped Python lint and isolated production build passed.
- Mutation review inverted LIVE retention only inside an isolated test process; both A01/A02 persistence cases failed as expected. Source and the running service were unchanged.

These final-code checks do not replace the full-regression limits in ICDV04/ICDV06: the two unchanged backtest lifecycle failures remain recorded. No assertions or thresholds were weakened.
