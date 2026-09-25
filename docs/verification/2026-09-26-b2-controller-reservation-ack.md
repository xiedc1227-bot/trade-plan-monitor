# B2 controller reservation acknowledgement: offline first slice

## Scope

`TushareRequestController.recheck_permission` accepts an optional internal synchronous `on_reserved` callback only with a bound recovery repository. It runs exactly once for a new logical permission recheck after its 300-second reservation commits and before a probe task or SDK call starts. A caller joining the same operation's shared probe does not invoke its callback. A later worker-start reservation extension does not invoke the callback again. Calls without `on_reserved` retain their existing behavior.

The callback must return `None`. A callback exception, other return value, or awaitable result raises the fixed sanitized local `PermissionReservationCallbackError` after retaining the durable block and retry time. It starts no SDK work and does not mark a provider or checkpoint fault or close the controller. Invalid or asynchronous callback arguments and use without a bound repository are rejected before a new reservation write. A failed checkpoint write invokes neither callback nor SDK.

## Verification

RED collection failed because the callback fault type was absent. GREEN fake SDK and temporary SQLite tests verify an independent database session sees the committed reservation inside the callback before SDK start, a coalesced second waiter invokes no callback, cancellation of the reserving caller leaves the shared probe running, queue abort and stop preserve one acknowledgement without SDK start, callback failures keep only a sanitized local fault, unbound/invalid input and save failure have no callback side effects, and a later worker retry extension does not acknowledge twice. The new file passed **9 tests**. The adjacent command passed **84 tests**; full Ruff and `git diff --check` passed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_permission_reservation_ack.py tests/unit/test_request_recovery_admission.py tests/unit/test_tushare_permission_probe.py tests/integration/test_production_certification_gate.py -q
.\.venv\Scripts\ruff.exe check .
git diff --check
```

This first B2 slice is not connected to `ProductionMonitorPipeline`, RUNNING/DEGRADED scheduling, any new physical probe, 30-second local checks, or cursor advancement. C1 remains OPEN. No real Tushare request, notification, user database change, push, or deployment occurred.
