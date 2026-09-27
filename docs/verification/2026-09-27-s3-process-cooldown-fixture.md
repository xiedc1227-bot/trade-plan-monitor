# S3 process cooldown fixture alignment

## Status and scope

TEST-ONLY restoration of the existing controlled-process 429 regression. Author and independent runs pass; independent final review approved all three paths with no P1/P2. Owned changes are limited to the local clock fixture in `tests/integration/test_provider_cooldown_process_restart.py` and this paired report. No production source, controller, checkpoint policy, provider behavior or other test was changed by this slice. No commit, push, deployment, real service, external notification or user database was used.

## PCF-01 — Diagnosis and unchanged acceptance

The original file failed both `change_token=False/True` cases: the first spawned process reached its bounded observation limit with `cooldown_until is None`, exited with code 1, and never entered the second process. The fixture released exactly one scheduler sleep. After F3 added genuine stock maintenance wakes before the first market duty, this ordinal no longer proved that `rt_min` had run. This is a fixture prerequisite mismatch, not evidence of a failed durable 429 restore or a newly repaired product defect.

Independent Sol review approved a bounded fixture-only correction before editing:

- Only the first, `induce_limit` child replaces its clock's sleep adapter. It releases real scheduler-selected deadlines through fixed `10:01:12`, at most eight wakes; any later wait parks without advancing time. It does not invoke a deadline or provider directly.
- Hard assertions require that `10:01:12` was actually released, the clock remains exactly there, exactly one `rt_min` call occurred, and its shared cooldown equals that target plus 300 seconds (`10:06:12`).
- The second child retains zero released sleeps. It starts at `10:02:15`, must be DEGRADED, restores exactly the first process's cooldown, and makes zero SDK calls. Real `spawn`, successful old-process stop/exit before new startup, temporary SQLite, same-token and manually changed-token cases, and all original final assertions remain intact. The same endpoint retains its recovery identity; this is not hot reload.

## Execution evidence

Commands, from `trade-plan-monitor/`:

```powershell
# Original fixture, before editing
.venv/Scripts/python.exe -m pytest tests/integration/test_provider_cooldown_process_restart.py -q --tb=short
# Corrected fixture and adjacent in-process 429 restart regression
.venv/Scripts/python.exe -m pytest tests/integration/test_provider_cooldown_process_restart.py tests/integration/test_production_certification_gate.py::test_production_429_cooldown_restores_before_provider_work_after_restart -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_provider_cooldown_process_restart.py
git diff --check -- tests/integration/test_provider_cooldown_process_restart.py
```

Original result: **2 failed in 12.09s**. Corrected plus adjacent result: **3 passed in 9.58s**, no warning. Ruff and the targeted diff check passed. Both runs observed HEAD `8d61a8e35173ca4c8250737d2b6a6eabfdf79810` plus the S2 writer's uncommitted source checkpoint. Each run had its own coordinated stable-source window. The source changed **between** runs, so these are not a same-source controlled RED/GREEN comparison, not clean-HEAD aggregate evidence, and not approval of S2. No production fix was made by this slice.

The following SHA256 values matched immediately before/after their respective runs:

| File | Original window | Corrected + adjacent window |
|---|---|---|
| runtime/production.py | `522560DDFB708A0DA31B6C5321611E96E0D700B5DF7AF9AB6B391ACED27658A7` | `A7D112694000DDF4DB5BF35170B32BDC4F056D18A991B69BDC272AEAE3CC5938` |
| runtime/service.py | `1FBF2D7C6731F46A4104F0C55C1EC1CB89F3C961482E55D9D87FB7C83FAB84C5` | Same |
| runtime/scheduler.py | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` | Same |
| web/monitor_composition.py | `3030F227DE0DA8EF02C69BF04996FCE92AF10546C577B10D955CED51AA339C68` | Same |
| test_provider_cooldown_process_restart.py | `0A7FC3E231C74B914019D0C71F6ECADCB8CC75EE55D9EE11EC9A49F932768EDD` | `7C9CDE144190D8506D86C060E69E7473A4C26117E938F647487F479F196EF5B1` |
| test_production_certification_gate.py | Not fingerprinted in this window | `D79C4E4C90F241374D3338297A900C91CA7AECA0ECE245043085DC40D267C010` |

## Independent verification

Independent Sol reran the exact corrected-plus-adjacent command above: **3 passed in 10.34s**, no warning. Six source and two test hashes were identical before/after the coordinated run. Production and process-test hashes matched the corrected author window; the adjacent certification file was now `D8C3A617242B46A294CC322649A8BB258243B082D1D0DF30825E5A02087160AE`. Its historical author hash above is retained, not overwritten. Target Ruff, diff check, static review and bilingual parity passed; the three paths were approved for local submission. This does not approve S2 or replace the fixed-commit full-suite gate.

## Limits

This restores the original real-process shared-429 before-floor regression and adds precise market-time prerequisites. It does **not** prove UPD-R17 permission reservation admission at exact 300-second equality, eight-scope automatic maintenance, UPD-R18 RUNNING/DEGRADED progress, concurrent-process ownership, live permissions or the full S3/C1 gate. Those remain assigned to the unified dispatcher writer and final fixed-revision integration review. Historical and adjacent case counts are not additive.
