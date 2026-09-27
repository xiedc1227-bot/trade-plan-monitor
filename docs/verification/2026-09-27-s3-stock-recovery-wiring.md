# S3 stock recovery wiring — F3-C

## SRW-01 — Scope and current status

Base `5e56c41` contains independently accepted F3-B. The paired [startup-minute repair contract](2026-09-27-s3-startup-minute-repair-contract.md) governs F3-C. The startup no-ticket/outcome/failure-evidence interface was independently approved before implementation. **Final independent source/test review passed with no remaining P1/P2; report parity approval passed.** No commit, push, deployment, real service or real user database was used.

The source slice is `runtime/production.py`, `runtime/scheduler.py`, `runtime/service.py` and `web/monitor_composition.py`. Tests include the independent wiring file, strengthened original A07, and explicitly approved fixture-only timing alignment in the existing execution and missed-close kill tests. Root owns commit authority. Connected identity/authority reports belong to their respective authors; the real final-admission controls are documented in the paired delivery report. This batch has final independent approval; overall integration acceptance remains separate.

## SRW-02 — Initial gates

- Startup performs at most one current-day stock fetch. Empty/partial completion retains the completion+30 retry floor across bounded synchronization, target change and repeated startup; provider retry must retain its category and floor without inventing attempts.
- Preblocked missing coverage remains the existing startup failure; complete committed coverage remains zero-fetch success. A missing ticket or `None` is not proof of READY.
- Real index-only composition continues index work without stock semantics; its cached stock getter is `None`, and an accidentally dispatched STOCK_RECOVERY performs no stock action. This does not authorize weakening the direct stock unit's authority guard or swallowing revocation of installed authority.
- STOCK_RECOVERY is maintenance: market work wins ties, both lifecycle cursor/review sites preserve the original market observation, exactly one fresh elapsed duty may run, multiple elapsed duties are not replayed, and pending notifications are not dispatched by stock maintenance.
- Successful market completion does not call the legacy multi-symbol `repair_detected_gaps` bypass; the old generic compatibility API remains available to other callers.
- Original A07 keeps all 13 cases and three oracle controls. Progress now asserts unchanged generation/no runner fault after each wake and at completion, zero business state plus AWAITING_FIRST_EVALUATION after prefix repair but before legitimate evaluation, and exact 10:05 target evaluated at 10:05:12. C2 retains the actual admitted 10:00:59→10:01:13 startup call and zero immediate startup elapsed replay.

The first index negative control mistakenly directly invoked the stock unit without installed stock authority. That refusal was correct, not a product defect. The control was corrected to actual composition routing before the recorded checkpoint below.

## SRW-03 — RED evidence

Commands run from `trade-plan-monitor` with offline SDKs and temporary databases:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_wiring.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_minute_coverage.py -q --tb=short
```

New wiring: **10 failed, 2 passed, 1 warning, 4.73s**. Failures identify startup 10-versus-1 acquisition, absent startup schedule accounting for empty/partial/provider retry, missing composition getter/scheduler callback/deadline kind, and the actual legacy gap-repair call. The two passing controls distinguish preblocked missing coverage from complete committed coverage. Cursor/dispatch assertions await the missing wiring and are not yet independently proven behavior failures.

Strengthened original A07: **2 failed, 11 passed, 11.51s**. Only empty/partial autonomous prefix recovery remains RED; C2 and all three oracles pass. Tests were not skipped, xfailed or weakened. These are author runs, not independent review results.

## SRW-04 — Implementation and correction history

Startup and maintenance now share one private ticket/accounting kernel. Startup has no maintenance reserve; maintenance retains 31.25 seconds. The bounded failure map stores only category, effective floor and original requirement, not exceptions/causes/tracebacks. Own valid empty/partial success clears retryable evidence but keeps completion+30 and any later schedule floor; no-ticket, sibling success, target/activation changes do not clear prior failures. Complete committed facts permit startup success without clearing controller/cached BLOCKED. Only same-binding observed authoritative blocked→clear releases BLOCKED evidence. Current guard invalidation remains startup failure, not provider-error evidence.

Normal production returns synchronize bounded demands. STOCK_RECOVERY uses the pure cached getter, both lifecycle maintenance cursor/review sites, and composition's pending-dispatch exclusion. A real scheduled SDK overrun from 10:01:12.000001 to 10:02:13 proves exactly one original 10:02 target review; the fake-work controls separately retain multiple-elapsed no-replay. Index-only composition is inert for stock work without weakening the direct unit's authority check. The old production multi-symbol gap-fetch path now only synchronizes demands; generic RecoveryService compatibility remains.

Root identified a shared-kernel date regression: official-close await can cross D→D+1. The focused `-k startup_date_rollover` run was **1 failed, 20 deselected, 1.59s**, then **1 passed, 20 deselected, 1.45s** after restoring requested-date filtering before physical fetch. Unknown/no capture/wrong requested date retain old skip behavior.

Independent review identified a fatal masking P2: a real separate thread/UOW completes all facts before the controller returns ERROR/QUEUE_FULL/CLOSED/INVALID_RESPONSE. `-k fatal_provider` produced **4 failed, 4 passed, 18 deselected, 1 warning, 2.96s**, then **8 passed, 18 deselected, 1 warning, 2.61s** after checking this invocation's fatal outcome after accounting and before startup aggregation. Maintenance's original exception identity behavior remains unchanged.

Two execution shutdown tests initially assumed an immediate request after empty startup (earlier adjacent: 317 passed/2 failed). The approved fixture now advances to the actual completion floor, runs the genuine reserve deferral, then advances to its returned wake; all token/drain/database assertions remain. This was fixture alignment, not a product fix.

The official-close kill/read/outcome batch initially produced **2 failed, 47 passed, 1 warning, 93.89s**. Both missed-close fixtures released one fixed sleep, now consumed by legitimate stock observation at 15:00 before the original realtime request at 15:00:12. A real-composition diagnostic confirmed RUNNING/READY and that exact wake. The independently approved fixture-only change releases actual deadlines through 15:00:12 with an eight-wake guard and asserts both times; SDK-entry, force-kill, no-pending, same/next-day recovery and all uniqueness/idempotency assertions remain. Completed/restart phase policy is unchanged.

## SRW-05 — Latest author evidence and review boundary

Commands from `trade-plan-monitor`:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_identity.py tests/integration/test_s3_stock_recovery_authority.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_execution.py tests/integration/test_s3_stock_recovery_owner.py tests/integration/test_s3_frozen_startup_recovery.py tests/unit/test_monitor_runtime.py tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_runtime_liveness.py tests/integration/test_runtime_plan_expiry.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_missed_close_kill_restart.py -q --tb=short
```

After date/fatal fixes, before one subsequent line-wrap-only change: **43 passed, 1 warning, 26.18s** (26 wiring + 13 A07 + 2 delivery + 1 identity + 1 authority); direct adjacent **319 passed, 1 warning, 55.37s**; targeted 120h/liveness/plan-expiry admission **29 passed, 1 warning, 13.30s**. Final corrected four-kill command: **4 passed, 26.07s**, on the final source. Earlier 27/35 target, 319 adjacent and independent 15 connected-case windows predate the date/fatal corrections and are historical only. Overlapping counts are not added together.

Final source/tests remain frozen after independent review. Production SHA256 is `38608F351317BBA04E35D169FC471B0F9707884E83C61E816544073143E968F7`; the only difference from the 43/319 test window is expression line wrapping. Author full `.venv/Scripts/python.exe -m ruff check src tests scripts` passes. No test is skipped/xfail and no business assertion was weakened. This source/test acceptance does not close overall C1 or C3. Historical decision replay, new freshness thresholds and a new recovery loop remain out of scope.

## Final independent validation

Independent Sol ran the following exact command from `trade-plan-monitor` on the final frozen source/tests:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_authority.py tests/integration/test_s3_stock_recovery_identity.py tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py tests/integration/test_s3_missed_close_kill_restart.py -q --tb=short
.venv/Scripts/python.exe -m ruff check .
git diff --check
```

**159 passed, 1 warning, 52.75s**. All 11 SHA256 values (four source files and seven test files) matched the final freeze before and after the run. Ruff and diff checks passed. The final F3-C/A07 source/tests have no remaining P1/P2; the startup fatal-masking P2 is closed. The earlier independent 155/28.47s window crossed the AD22→38608 line-wrap-only change and is not final fixed-revision acceptance; it is superseded by this 159-case run, not added to it. Author and independent windows remain separate. All five report pairs passed independent parity review; overall C1/C3 are not declared closed. No source/test changes or commit accompany this documentation update.
