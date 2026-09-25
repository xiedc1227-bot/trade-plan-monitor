# Certified runtime lifecycle test repair (offline)

## RED and cause

`test_certified_pipeline_recovers_evaluates_once_and_restarts` failed at its first `trade_cal` request with `RequestControlErrorCode.ERROR`. A temporary in-memory trace exposed the guarded client's `RuntimeError("provider certification is not current")`. The old test directly constructed `_ProductionRuntimeState`, called `probe_capabilities`, skipped database opening and liveness admission, and passed `uuid4` as a generation callback that changed on every call. Its test setup no longer met production admission requirements.

## Repair and verification

The test now creates the installed `create_monitor_composition`, starts and stops one owned generation, then starts a second composition on the same temporary SQLite database. It asserts ready database state, liveness ownership, bound provider recovery, and current generation before a direct exact-minute deadline. The fake SDK's no-checked-out-connection assertion points to each generation's actual composition engine. The first deadline commits one evaluation; a repeat in the first generation and the same deadline after restart add no evaluation or `rt_min` request. The persisted decision head is unchanged after restart.

The focused test passed. The full `test_certified_production_runtime.py`, `test_production_certification_gate.py`, and `test_live_pipeline_acceptance.py` regression set passed **72 tests**. No production safety guard changed. This is a test-harness repair, not C1 closure or a real provider/permission claim. No real Tushare request, external notification, user database migration, push, or deployment occurred.
