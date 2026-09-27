# S3 scheduled stock recovery identity evidence

## Status and scope

TEST-ONLY connected acceptance for S3-06/A09. The strengthened final test passed in a coordinated source-stable window and in the final independent combined run below. This report does not approve all F3-C or close S3-06, C1 or the overall integration gate.

Owned files: `tests/integration/test_s3_stock_recovery_identity.py` and this paired report. No production source or existing test was changed by this slice. No commit, push, deployment, live service, real provider, real notification or user database was used.

The test intentionally imports the still-uncommitted A07 `_Run`, `_CoverageSDK` and scheduler-controlled clock from `test_s3_startup_minute_coverage.py`. A07 and C must be accepted in the same batch; this file is not independently committable. It also reuses committed live-pipeline fixture helpers. SQL repositories, request control, recovery, lifecycle scheduling, evaluation and delivery admission remain real. Only the remote SDK and notification transport are offline fakes; HTTP is prohibited by the fixture.

## SRI-01 — Stale physical response, healthy sibling, fresh recovery

Test: `test_scheduled_stock_recovery_reactivation_rejects_old_facts_and_resumes`.

1. At 10:00:15, two active legacy plans share one real composition. The first lacks 09:31; startup performs exactly one stock acquisition. The sibling can acquire complete facts on its own scheduled turn.
2. Release actual scheduler sleeps until the first plan enters a scheduled `rt_min_daily` physical call. Freeze its full response in the fake SDK worker. At this held boundary, assert the lifecycle's actual deadline kind is `STOCK_RECOVERY`, its current task is unfinished and belongs to `runtime._work_tasks`, and `stock-prefix:003043.SZ` has `snapshot.in_progress=True`. A transparent observer forwards the original deadline and result unchanged; it does not replace the scheduler, choose a deadline or invoke work directly. This prevents a fenced legacy gap-repair bypass from satisfying the test. A separate real SQLite connection deactivates/reactivates the same plan at the **current clock**, preserving its plan version/hash and changing activation revision from 1 to 3. The clock is never backdated to an earlier activation time.
3. Release the stale SDK response. Assert exact equality of the first plan's complete minute and latest_quote rows, including received_at, and all snapshotted business tables. The missing 09:31 is not admitted. No old evaluation, risk update/audit, decision head, alert/HOLD or delivery attempt is fabricated or relabelled.
4. Continue real wakes with that first minute still unavailable. The healthy sibling produces a genuine 10:05 result at 10:05:12 under activation revision 1; the first plan still has no decision or notification intent.
5. Make history available at the offline SDK boundary. A later actual maintenance acquisition repairs the prefix without rewriting previously committed minute rows, and does not evaluate. Only the next legal market duty produces the first plan's sole result, at 10:10:12 for target 10:10, linked to activation revision 3 through the decision head. Validate result/ledger/head hashes, formula, source time, actual evaluation time, complete prefix, and age 0..90 seconds. The sibling's earlier result remains unchanged; 10:05 is not replayed for the first plan.

Every released wake and each physical-wait boundary asserts the original runtime_generation, RUNNING status and absence of RUNTIME_RUNNER_FAILED. No evaluator/recovery replacement or direct deadline execution is used. The 45-second watchdog, 8-second worker barrier and 64-wake guard bound only the test, not production timing policy.

## Execution evidence

Commands, from `trade-plan-monitor/`:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_identity.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_s3_stock_recovery_identity.py
```

The initial version passed: **1 passed in 4.54s**, on HEAD `8d83f7913fb9bb295313322580205f5a0d9739d6` plus the C writer's uncommitted source. The four source SHA256 values were identical immediately before and after that run:

| Source | SHA256 |
|---|---|
| runtime/production.py | `2EEDEBFFD778BBF6B7CA9FBC0CE346489316A9B26D42A39AC352FAC4A7516076` |
| runtime/service.py | `1FBF2D7C6731F46A4104F0C55C1EC1CB89F3C961482E55D9D87FB7C83FAB84C5` |
| runtime/scheduler.py | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| web/monitor_composition.py | `3030F227DE0DA8EF02C69BF04996FCE92AF10546C577B10D955CED51AA339C68` |

The pre-review strengthened test passed in the source writer's coordinated window: **1 passed in 4.57s**; Ruff passed. HEAD remained `8d83f7913fb9bb295313322580205f5a0d9739d6`. `runtime/production.py` was now `7A5DE1FE6ADF80587505A3E3156B6CDD6A3C25A93192B2A83046EA2C1806A275`; the other three source hashes remained as above. All four source hashes and both test hashes below were identical before and after that run:

- Identity test: `961410F55D498DB70CB8BD4CAE4DF2BA2B9D0235DC477355F65BF6802FBA2767`.
- A07 fixture dependency: `93E459A2B2D85A975895F4A374CE59F52BA44EF44C0AC4A5CCA16D153B0387EF`.

Following independent review, the explicit deadline/task/scope ownership assertions above were added. The final test passed in another coordinated window after the C writer's date-skip correction: **1 passed in 4.88s**; Ruff passed. HEAD was unchanged. `runtime/production.py` was `9A8095BF2C0D1C59BCC1FF1903B3554A35EC15552764AA3383B3E303429894A8`; the other three source hashes and A07 hash remained as above. The final identity test hash is `9E47CBB6E5F69D5273647F71E1EA90D9096C2230B8B2098DD48CF59C9FA99ED1`. All six hashes were identical before and after this author run.

These are separate, overlapping development runs, not independent cases. This new connected test has no independently executed baseline RED: C wiring had landed before its first run. No dynamically substituted HEAD modules were used to manufacture one. C's separately recorded real wiring/A07 RED evidence is not this test's RED.

### SRI-02 — Final independent combined verification

The independent Sol reviewer ran the following exact command from `trade-plan-monitor/` against the final frozen candidate:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_authority.py tests/integration/test_s3_stock_recovery_identity.py tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py tests/integration/test_s3_missed_close_kill_restart.py -q --tb=short
.venv/Scripts/python.exe -m ruff check .
git diff --check
```

Result: **159 passed, 1 warning in 52.75s**. Both quality checks passed. This combined run includes the unchanged final identity test and its three held-SDK ownership assertions: actual `STOCK_RECOVERY` deadline, unfinished lifecycle-owned task, and the symbol's in-progress stable scope.

HEAD remained `8d83f7913fb9bb295313322580205f5a0d9739d6` plus the frozen candidate. The reviewer confirmed matching before/after hashes for the four source files and monitored test files. `runtime/production.py` was `38608F351317BBA04E35D169FC471B0F9707884E83C61E816544073143E968F7`; scheduler, service and composition matched the table above. Identity remained `9E47CBB6E5F69D5273647F71E1EA90D9096C2230B8B2098DD48CF59C9FA99ED1`, and A07 remained `93E459A2B2D85A975895F4A374CE59F52BA44EF44C0AC4A5CCA16D153B0387EF`.

The 159 cases overlap earlier author/reviewer runs; do not add their counts. This is final-candidate, not clean-HEAD or full-suite evidence, and it does not close C1 or the overall integration gate.

## Limits

This single scenario covers legacy prefix semantics, same-plan activation replacement, one healthy sibling, and in-process scheduled recovery. It does not retest the complete F1/F2 fault matrix, explicit-rule semantics, worker source revocation, process kill/restart or positive notification delivery. Alert/HOLD/attempt rows are absent controls here, not pre-existing historical notification fixtures. Candidate results are not clean-HEAD integration evidence; later source changes require a final coordinated rerun.
