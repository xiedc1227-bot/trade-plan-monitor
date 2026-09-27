# S3 degraded retry read-health evidence

## DRH-01 — Scope

Tests-only S3-08 supplement to the existing installed-composition A04 scenario. Root owns `tests/integration/test_production_a04_retry_timeline.py` and this paired report. No production code, public status/field, provider policy or retry interval is changed. All requests use the existing fake SDK and temporary SQLite; no live service, real notification, user database, push or deployment is involved.

The four original calendar transport failures, 30/60/120/300-second floors, same owner/controller/generation and genuine eventual decision remain required. This does not implement or accept C1 UPD-S5's permission/startup dual clocks.

## DRH-02 — Assertions and reviewed fixture alignment

At each of the four actual retry waits, the real read service must expose `DEGRADED`, `read_only=true`, `degraded_reason=REFERENCE_REFRESH_FAILED`, no block reason, READY database/WAL, and `next_retry_at` equal to the lifecycle's full-startup retry time and the actual wait deadline. The deadline must still respect the controller backoff/shared cooldown; it is not artificially reduced to just the controller floor. `REFERENCE_TRANSIENT` is the existing log classification, not the public degraded-reason value.

The dashboard remains exactly `UNAVAILABLE / AWAITING_FIRST_EVALUATION`, current symbol health is absent, and the actual socket heartbeat frame says `runtimeLive=false` and `runtimeGeneration=null`. Local reads work, but neither a socket nor a legal local owner claims business progress. Evaluation/alert rows remain absent. Check the real runtime generation, not the deliberately excluded hidden generation field of a copied v1 public response.

After startup recovery, preserve the original first 10:09 wake and zero evaluation. Release actual scheduler waits, at most eight additional iterations, until exactly `10:10:12`. Each intervening wake must preserve the same runtime/generation, no runner fault and zero evaluation/alert. Never select or invoke a deadline directly, infer a market duty from its sleep ordinal, skip beyond the target, or derive the expected target from an arbitrary final wake. The sole result must have target `10:10`, actual evaluation time `10:10:12`, original plan hash and activation revision 1 in its decision head, and no alert.

Sol independently approved this bounded fixture alignment and additional read assertions before editing. No original business assertion, case or retry threshold was removed, skipped or weakened.

## DRH-03 — Development evidence

On committed F3-C (`a1f217b`, documentation HEAD `39ab6f4`), the unchanged original A04 test produced **1 failed in 2.16s**. All four retry checks passed; the failure was its fixed second-sleep assumption: new legitimate maintenance woke at `10:09:42`, not the assumed `10:10` market duty. This is an old fixture assumption exposed by a new duty, not a product RED or a reason to remove the duty.

After the reviewed change, the target passed **1 test in 2.36s**. Adding the explicit sole-result/evaluation-time assertions passed the two-file run; Ruff then caught a loop-variable binding in the test callback. Binding that value explicitly yielded the latest author result **2 passed, 1 warning in 4.45s**, and target Ruff passed:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_a04_retry_timeline.py tests/integration/test_s3_installed_runtime_read_liveness.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_production_a04_retry_timeline.py
```

The final test SHA256 is `40C345937E654EAED3D81361B08A35C8AC375B9BBC9BF2F800AB9875A847CA83`. These runs overlapped the S2 writer's source work; the latest observed `production.py` hash was `6BF2CE8DAA3B797896B39EF4A6201DAEDD8DC3E7C33F2A044339527F9C76A7E7`. They are development evidence, not an asserted stable-source or full-suite run. Counts overlap and must not be added.

## DRH-04 — Remaining gate

Independent Sol review approved these three files with no P1/P2. The exact two-file pytest command above passed **2 tests, 1 warning in 4.67s**. Six source and two test hashes were unchanged before/after the coordinated run, including `production.py` at `6BF2CE8DAA3B797896B39EF4A6201DAEDD8DC3E7C33F2A044339527F9C76A7E7` and the final A04 hash above. Both test files passed independent Ruff; the targeted diff check passed. Bilingual parity and the original business assertions were independently checked.

This is a short source-frozen S2 working-candidate compatibility window, not approval of the S2 implementation or fixed-commit full-suite acceptance. C1 unified permission scheduling, the full S3-08 matrix, fixed-commit aggregate regression and final integration review remain OPEN. No new public API or Step 4 page/protocol is claimed.
