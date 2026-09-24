# A04 Installed Retry Timeline (Offline)

## Scope and method

This bounded check installs the production composition with a temporary SQLite database, a certified offline stock profile, one active Schema v1 plan, and a fake SDK. The fake `trade_cal` request for the same SSE date range raises `requests.ConnectionError` four times and returns valid rows on its fifth call. The production request controller, recovery repository, lifecycle, scheduler, and read service remain installed. Only the SDK boundary and the lifecycle retry wait are controlled by the test.

The test uses one timeline for the business `Clock`, request-control `monotonic` and `pace_sleep`, and scheduler `sleep_until`. A retry gate records the computed delay and physical-call count. The test checks that no new physical request occurs while the gate is closed, then releases it and advances the timeline by exactly that delay. It does not accelerate heartbeat, physical-worker timeout, or shutdown draining.

## Observed result

- The four lifecycle retry delays satisfy the 30, 60, 120, and 300 second floors. Each due time is at or after the lifecycle `retry_at`, the controller's same-key backoff, and any controller cooldown.
- The first five physical `trade_cal` calls use the identical SSE range; the sixth is the subsequent SZSE calendar request. No physical request occurs before an owned retry gate is released.
- The composition remains locally readable while `DEGRADED`. It recovers to `RUNNING` with the same lifecycle object, request controller, runtime generation, and liveness ownership revision; the crash supervisor records zero restart attempts.
- The scheduler, rather than a direct `run_deadline` call, handles 10:09:12 and then 10:10:12 on 2026-09-08. The 10:09 poll creates no evaluation or alert because the active plan evaluates on five minute targets. The 10:10 poll commits one `INTRADAY` result for `2026-09-08T10:10:00+08:00` with the active plan hash and activation revision 1. No alert is persisted.

The new test and adjacent lifecycle, composition, and certification checks passed: **118 passed, one existing Starlette/httpx deprecation warning**. This is offline A04 recovery evidence for the specified transient calendar sequence, not full A04 or release acceptance. No real Tushare request, external notification, user database migration, deployment, or push was used.
