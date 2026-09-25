# B2 permission candidate rotation: offline second slice

## Scope

`ProductionMonitorPipeline` keeps one immutable in-memory cursor state for the six permission scopes and separate `DAILY_BARS` official (`O`) and fallback (`F`) `(symbol,date)` pools. Repeated candidate peeks are read-only. The controller's successful durable `on_reserved` acknowledgement is the only trigger that replaces this state; the callback performs one bounded in-memory assignment, with the next state computed before reservation. A persisted reservation counts even when queue admission later aborts before physical SDK start. Save failure and candidate scanning do not advance cursors.

The first daily-bar choice uses `O` when present. When both pools exist, reservations alternate `O` and `F`, and each pool advances independently through its bounded date-descending, symbol-ascending order. If a prior pair disappears or moves to the other pool, selection takes the strict successor of its retained sort key and wraps only after the end. An empty pool retains its cursor for later recovery. Scope ties use the last reserved scope; a probe attempt or failure does not itself rotate it. Cursor state is process-local and resets on restart.

## Verification

RED tests first failed on missing callback factory, pool identity, immutable state, and strict-successor helper. GREEN fake SDK and temporary SQLite tests cover all six equal-due scopes, repeated peeks, durable reservation followed by a queue abort with exactly one acknowledgement, O/F alternation, same-day symbol and cross-day successors, deleted and cross-pool pairs, empty-pool recovery, and failed checkpoint save leaving the cursor unchanged. The new rotation file passed **4 tests**. The adjacent command passed **89 tests**; full Ruff and `git diff --check` passed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_candidate_selection.py tests/integration/test_production_certification_gate.py tests/unit/test_permission_reservation_ack.py tests/unit/test_request_recovery_admission.py -q
.\.venv\Scripts\ruff.exe check .
git diff --check
```

No production scheduler connection or new physical permission probe was added. This slice does not implement 30-second local checks or cross-restart cursor persistence. A later production caller must create and pass each precomputed acknowledgement immediately within its serialized reservation flow; concurrent callbacks precomputed from the same old state are outside this slice. C1 remains OPEN. No real Tushare request, notification, user database change, push, or deployment occurred.
