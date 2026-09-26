# S3 coordination baseline regression

## Scope and status

On 2026-09-27, the coordinator reran the existing S3-04–S3-08 test groups after the DAILY_BARS preparation commit `233f969abf14435048fee8b9830361b888b34506`. The separate stock-minute slice was in progress in the shared working tree. These are baseline results, not final integrated-revision evidence or acceptance of missing scenarios.

Only offline tests using temporary state and fake boundaries were run. No real provider, notification service, user database, push, or deployment was used. This report changes no contract or task checkbox.

## Executed results

| Group | Result | Time | Meaning |
| --- | --- | --- | --- |
| S3-04 existing session/recovery cases | 147 passed | 21.12s | Existing tests remain green; does not prove forced-termination obligation reconstruction. |
| S3-05/S3-06 existing isolation and identity cases | 81 passed, 1 warning | 52.01s | Existing isolation and activation-fence baseline only. |
| S3-07/S3-08 existing lifecycle, delivery, and local-read cases | 140 passed, 1 warning | 10.50s | Existing drain/delivery/read baseline only; not full C3 acceptance. |

Total: **368 passing tests** across these three non-overlapping invocations. Both warnings are the existing Starlette/httpx deprecation warning. No tests were skipped or weakened to obtain these results.

Commands executed from `trade-plan-monitor/`:

```powershell
.venv/Scripts/python -m pytest tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py tests/integration/test_runtime_recovery_coverage.py tests/integration/test_missed_close_execution.py -m 'not live' -q --tb=short
.venv/Scripts/python -m pytest tests/integration/test_production_a06_matrix.py tests/integration/test_production_a06_process_scheduler.py tests/integration/test_market_index_runtime.py tests/integration/test_recovery_activation_fences.py tests/integration/test_production_certification_gate.py -m 'not live' -q --tb=short
.venv/Scripts/python -m pytest tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py tests/integration/test_notification_delivery.py tests/integration/test_delivery_admission.py tests/integration/test_persistent_monitor_read_service.py -m 'not live' -q --tb=short
```

## Remaining gates

C1 remains open for DAILY_BARS physical wiring, stock-minute proofs and integration, unified maintenance scheduling, and complete cross-process acceptance. S3-04–S3-09 remain incomplete. In particular, a physical request spanning a market deadline followed by forced process termination needs explicit restart-obligation evidence; a live heartbeat or 31.25-second admission guard alone is insufficient. Independent inspection of that missing scenario is in progress, not a reported pass. Rerun the required gates on the final integrated revision before claiming C1/C3 or step 3 completion.
