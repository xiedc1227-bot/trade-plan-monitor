# S3 actual startup minute coverage

## Current F3-C status

The historical evidence below is retained, not relabelled as a current failure. F1 `f4a5050` repaired associated incomplete outcomes; F2 `6bcf080` repaired frozen startup captures; F3-A/B `05487b4`/`5e56c41` supplied the bounded owner/executor. The current uncommitted F3-C wiring makes all **13 original cases GREEN**, including all three oracle controls. Final independent source/test review passed without remaining P1/P2; report parity approval passed. Overall C1/C3 are not declared closed.

The post-F2 strengthened baseline was **11 passed, 2 failed, 11.51s**, with only empty/partial autonomous progress failing. Both progress cases now require the original runtime generation and no runner fault after every real scheduler wake and at completion. Before the legitimate next evaluation, repaired prefix facts coexist with zero decision/claim/risk/outbox/send and public `AWAITING_FIRST_EVALUATION`; only actual target 10:05 evaluated at 10:05:12 produces current business results. Automatic runner replacement can no longer satisfy progress. C2 still tests a physically admitted startup request from 10:00:59 to 10:01:13, frozen response exclusion, and no immediate elapsed replay.

Latest author verification after date/fatal fixes: the command below produced **43 passed, 1 warning, 26.18s**, including all 13 cases in this file (not a separate 13-case run). The three connected representatives and fuller chronology are recorded in the paired wiring/identity/authority/delivery reports. Source then received one formatting-only line wrap; final source/tests remain frozen after independent review. No original case/oracle was removed, skipped or weakened.

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_identity.py tests/integration/test_s3_stock_recovery_authority.py -q --tb=short
```


## Final independent validation

Independent Sol ran the following exact command from `trade-plan-monitor` on the final frozen source/tests:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_authority.py tests/integration/test_s3_stock_recovery_identity.py tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py tests/integration/test_s3_missed_close_kill_restart.py -q --tb=short
.venv/Scripts/python.exe -m ruff check .
git diff --check
```

**159 passed, 1 warning, 52.75s**. All 11 SHA256 values (four source files and seven test files) matched the final freeze before and after the run. Ruff and diff checks passed. The final F3-C/A07 source/tests have no remaining P1/P2; the startup fatal-masking P2 is closed. The earlier independent 155/28.47s window crossed the AD22→38608 line-wrap-only change and is not final fixed-revision acceptance; it is superseded by this 159-case run, not added to it. Author and independent windows remain separate. All five report pairs passed independent parity review; overall C1/C3 are not declared closed. No source/test changes or commit accompany this documentation update.

## Historical scope and reviewed contract

Baseline: `453cc0c`. This tests-only slice adds `tests/integration/test_s3_startup_minute_coverage.py` and this English/Chinese report pair. Production, migrations and existing tests remain outside its scope. The coordinator's full offline run had already collected its tests before these files were added; these new cases are not part of that run's result. C1 remains open, and S3-04 remains OPEN; this slice does not declare completion.

The independently reviewed contract uses one current-day legacy plan with fixed activation identity, actual composition/controller/scheduler/provider, temporary SQLite, fake SDK/clock/channels and forbidden HTTP. Valid certification supplies capabilities; SDK calls are recorded by actual sequence, phase and entry time, never inferred from a supposed second `rt_min_daily` call. Empty frames retain their valid schema. No test directly invokes recovery/evaluation, inserts pending work, or forces `DEGRADED`.

## Cases and expected evidence

| ID | Case | Expected evidence before execution |
|---|---|---|
| SSMC-A-S | Empty startup, later historical data unavailable | Exact empty startup minute set; realtime 10:01–10:05 cannot create a result/claim/risk/outbox/send; public detail remains `AWAITING_FIRST_EVALUATION`. Expected safety GREEN. |
| SSMC-B-S | Startup contains 09:32–10:00, missing only 09:31; later history still missing it | Exact persisted identities, including the complete current bucket; the same safety assertions as A. Expected safety GREEN. |
| SSMC-A-P | Empty startup, later full history available | Real scheduled work must autonomously reacquire the original missing prefix and produce one valid current decision by the test's finite market bound 10:10:12. Expected progress RED on baseline. |
| SSMC-B-P | Partial startup, later full history available | The original 09:31 gap must be autonomously committed before one valid current decision. Expected progress RED on baseline. |
| SSMC-C1 | Complete prefix plus a raw future row | A row still incomplete at response time is filtered by the real provider. Expected GREEN. |
| SSMC-C2 | Acquisition at 10:00:59, response at 10:01:13 | START-labelled raw time 10:00 normalizes to bar_end 10:01. It is usable at response time but exceeds frozen cutoff 10:00 and must not enter SQLite. Expected cutoff RED. Startup-only observation permits zero second business fetches and zero realtime calls. |
| SSMC-C3 | New acquisition begins at 10:01:13 | A separate real startup acquisition can accept bar_end 10:01 under its new cutoff. Expected GREEN. |
| SSMC-D | Complete persisted 09:31–10:00, empty startup response | Existing facts survive; complete realtime 10:01–10:05 yields one correct 10:05 decision; repeated startup preserves the same business records. Expected GREEN. |

Safety and progress are separate cases, so a successful early repair cannot hide an unsafe result. Progress permits a current eligible decision, not replay of old 10:00/10:05 decisions. `RUNNING` and single-minute `LIVE` are observations, not business-readiness assertions. No new pending state is required: evidence is exact persisted minute identity, physical SDK entry, decision head, claim/result/outbox and existing public responses.

## Isolation and bounds

The controlled clock releases the real scheduler's requested deadlines, not a fixed number of sleeps. The progress horizon is 10:10:12, with a 45-second real watchdog, 64-wake guard and 10-second cleanup limit. These are fixture bounds, not a production recovery SLA or fairness guarantee. Safety observations can stop at a public `RUNTIME_RUNNER_FAILED` boundary; a separate enabled regression then rejects that fault. Progress cases allow the actual supervisor to run, including autonomous replacement. The C2 fourteen seconds are a simulated market-clock advance, with no real fourteen-second sleep; the real controller retains its timeout and pacing configuration, so this is not a physical timeout-boundary test. A fresh acquisition control uses the real provider, never `recover_scope` directly.

## Execution and classification

The eight-case contract above was recorded before execution. Actual execution uncovered another production failure, so two explicit A/B fault regressions were added in the same new test file. Independent static review then requested three oracle controls, giving ten composition cases plus three oracle cases. No assertion was marked xfail/skipped, and no production behavior was replaced to obtain a pass.

| ID | Actual result | Evidence |
|---|---|---|
| SSMC-A-S / SSMC-B-S | GREEN, 2 cases | Exact startup identity sets; five real realtime SDK calls; no decision/claim/risk/outbox/attempt/send; public `AWAITING_FIRST_EVALUATION`, including at the fault boundary. |
| SSMC-A-F / SSMC-B-F | RED, 2 newly exposed fault regressions | With a complete 10:05 bucket and missing earlier prefix, public health becomes `RUNTIME_RUNNER_FAILED`. Expected publication incompleteness must not become a runner fault. |
| SSMC-A-P / SSMC-B-P | GREEN, 2 cases; original progress-RED hypothesis disproved for this fixture | A second business acquisition enters at 10:05:12 after automatic runtime replacement, commits the original gap, and yields one valid 10:05 decision. Both cases record `generation_changed=True`; SDK sequence 5 is the initial 10:00:15 acquisition and sequence 15 is the 10:05:12 acquisition. These are observations, not sequence-based request selection. |
| SSMC-C1 | GREEN | All 30 canonical 09:31–10:00 minutes survive; the additional still-future raw row does not. |
| SSMC-C2 | RED | Exactly one startup business fetch enters at 10:00:59; zero realtime calls and zero released scheduler sleeps. SQLite nevertheless contains the additional `2026-09-08T10:01:00+08:00` identity, 31 rows instead of the frozen 30. |
| SSMC-C3 | GREEN | A new real fetch beginning at 10:01:13 legitimately persists all 31 identities through 10:01. |
| SSMC-D | GREEN | Existing prefix survives the empty response; one matching 10:05 result/claim/head, price 6405 and complete source prefix; repeated actual startup preserves minute identities and all observed business rows/deliveries. No zero-fetch requirement is imposed. |
| SSMC-O | GREEN, 3 oracle controls | Accepts a 10:05 target evaluated at 10:05:12; rejects its late replay at 10:10:12 and a falsely backdated evaluation timestamp. |

The initial harness waited only for another scheduler sleep and therefore timed out when the runner stopped after 10:05. Diagnostic exception observation, without changing production, located `RuntimeDeadlineCoordinator.run_deadline` in `runtime/service.py:2639–2648`: legacy `INCOMPLETE` correctly has `facts=None`, but the coordinator omits it from `by_symbol` and raises `RuntimeError("deadline evaluation omitted a due plan")`. The real supervisor subsequently restarts the runtime. The final harness recognizes the public fault boundary and tests it explicitly; temporary diagnostic tracing and the short diagnostic wait were removed. This was not evidence that incomplete data had created a bad decision.

The observed restart also corrects the earlier static progress hypothesis: for these fixtures, once history becomes available, the real supervisor does recover it without manual recovery calls. This does not prove healthy scoped recovery, because the path first crashes the runner and changes runtime generation. Activation identity remains unchanged. The progress tests do not require a crash or generation change to pass after a future fix.

The first complete diagnostic matrix was **3 failed, 7 passed in 15.05s**. After adding source-prefix/price checks, fault-boundary capture and progress diagnostics, the next run was **3 failed, 7 passed in 15.00s**. A control-only cleanup then allowed D's already-complete data to avoid a provider fetch while preserving its data and deduplication assertions.

One rerun was blocked during collection (**1 error in 1.04s**): concurrent edits at shared HEAD `e9c6ac5` temporarily made `production.py:299` inherit from an undefined `PermissionEndpointResolver`. No test executed in that invocation. The coordinator confirmed this was the sole source writer's intermediate edit and paused pytest until imports stabilized. After the coordinator released that hold, the complete ten-case rerun was **3 failed, 7 passed in 15.27s**. The temporary collection blocker is resolved and is not a product regression or one of the three coverage failures. This task did not modify the writer's files.

Independent Sol review identified a P2 in the original current-decision oracle: checking only that the target was after 10:00 and no later than the clock could accept a 10:05 target replayed at 10:10:12. The revised oracle parses target/evaluated_at, requires evaluated_at to equal the observed evaluation clock, and requires an age from 0 through the existing 90-second limit. The canonical snapshot must carry the same evaluated_at. D's repeated-startup check keeps the actual original evaluation observation rather than relabelling the old result with restart time. SSMC-O adds a fresh 10:05/10:05:12 positive control and two synthetic negative controls: a late 10:10:12 replay of 10:05, and a falsely backdated 10:05:12 evaluation observed at 10:10:12. These controls exercise only the oracle; they do not replace production evaluation or persisted results. Fresh 10:05 decisions remain allowed, and generation changes remain observations only.

Final author verification of the complete revised file: **3 failed, 10 passed in 15.08s**, including all three passing oracle controls. Independent Sol verification separately reproduced **3 failed, 10 passed in 14.90s** at HEAD `3c22bff`, with Ruff passing; these two runs are not added together. The oracle P2 is closed and the test evidence is accepted for repair design, not as product GREEN. The two incomplete-data runner-fault failures and the frozen-cutoff failure remain unrepaired. Both progress cases still observed automatic generation replacement and a genuine 10:05:12 evaluation of 10:05. The author run began at shared HEAD `3c22bff` with the other task's uncommitted SDK-boundary source changes; this is current shared-worktree evidence, not certification of an isolated committed revision. Ruff and the three files' whitespace/bilingual parity checks passed. These three files remain uncommitted; production fixes require a separate reviewed design. Other tasks' source edits and reports are outside this change.

Commands from `trade-plan-monitor/`:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_minute_coverage.py -q -rP --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_s3_startup_minute_coverage.py
git diff --check
```

## Limits

This slice covers one current-day legacy symbol with stable identity. It does not establish multi-scope fairness, arbitrary activation/semantic changes, cross-day recovery, ExplicitTradePlan coverage, or all A07 acceptance criteria. It changes no UI/API protocol, freshness threshold or official-close recovery behavior.
