# S3 notification transaction/send kill and restart evidence

## SNKR-01 Scope and status

This 2026-09-27 report covers four offline process-crash windows in [S3-07](../../tasks/runtime-recovery-todo.md), using only the new `tests/integration/test_s3_notification_kill_restart.py`. Production code, existing tests, notification policy, and migrations are unchanged by this slice. The root reviewer independently reviewed the test and reran all four cases with no P1/P2 findings; paired-report parity review passed and the three-file local commit is approved.

This is bounded evidence, not closure of S3-07, C3, or Step 3. Connected A07 F2/F3 stop/drain acceptance remains separate. No real service, external notification, user database, deployment, push, or hot reload is involved.

## SNKR-02 Production path and process proof

Each case uses one temporary SQLite database and four sequential `spawn` processes. It reuses the committed official-close fixture: a valid legacy `TRADING_DAY` plan for `003043.SZ`, activation revision 1, 200 prior-day shares, calendar, and heartbeat. Initially the observed decision/notification tables are empty. This tests one same-day `RISK_BREACH` path; it does not establish arbitrary downtime coverage. The 120-hour rule concerns software inactivity, not the last market-data timestamp.

P1 starts the real monitor composition at `2026-09-08 17:05`; startup autonomously discovers the missed `15:00` official close and produces the decision. It does not seed results, alerts, or attempts or directly invoke business/recovery/dispatch methods. The mandatory real `IN_APP` channel and `CurrentDeliveryAdmission` remain intact. Only the SDK, clock, pacing, and additional `CONSOLE` channel are fakes; actual fake-SDK `trade_cal` and `daily` calls are asserted, and HTTP transports reject network access.

The fake channel appends a local JSONL external-effect marker and calls `flush`/`fsync` before returning success. It has no idempotency suppressor. Pause-only observers wrap the real business UoW commit and dispatcher finalization; the receipt-uncommitted window is reached after the real SQL update, observed on that connection. The child reports its PID and boundary facts, then blocks on a process-local event. The parent reads committed state through a separate read-only connection, kills and joins only its owned child, requires a nonzero exit code, and checks that durable state and markers are unchanged by the kill. P1 never executes normal stop.

P2, P3, and P4 perform real composition restarts at `17:05:30`, `17:06:00`, and `17:06:01`. Each must reach `RUNNING`, park on a future scheduled sleep without advancing the clock, and exit through normal stop. The existing 60-second claim lease and admission/health rules are not changed.

## SNKR-03 Four hard assertion windows

| Window | Before kill | Restart assertions |
| --- | --- | --- |
| `business-uncommitted` | The transaction contains one ledger, result, risk state, alert, delivery eligibility, and decision head, and has removed its pending close. None of those staged changes are committed. | The exact independently committed pre-transaction snapshot survives, including its legitimate pending-close identity. Startup creates one canonical close decision and delivers it. |
| `business-committed` | One canonical business intent is committed; delivery eligibility is `HOLD`; there are zero attempts and external markers. | Startup recovers the same event and business rows, then delivers without creating a second business intent. |
| `receipt-uncommitted` | `IN_APP` is delivered; one external marker exists; the console receipt is staged as `DELIVERED`, but a separate reader still sees the committed `CLAIMED` attempt with no response/delivery time. | At +30 seconds the claim and marker are unchanged. At lease equality (+60 seconds), the same event, attempt ID, and attempt number 1 are reused; the second external marker is expected and the receipt commits. |
| `receipt-committed` | The console receipt is durably `DELIVERED`, response code 200, with no next retry; exactly one external marker exists. | All restarts retain the same attempts and marker, with no new attempt or send. |

All recovered decisions retain the original plan hash/version/formula, `15:00` source close, activation revision 1, 200-share risk inventory, one risk audit, one alert, and no pending close. Already committed business rows remain unchanged. P4 verifies the complete observed snapshot, including eligibility and attempts, plus markers is unchanged. An already delivered `IN_APP` receipt is not resent. Lost console receipts can repeat the external effect: this proves durable business intent and claim reuse, **not external exactly-once delivery**.

## SNKR-04 Results and candidate identity

The first `business-uncommitted` run was **1 failed, 3 deselected in 3.62s** because the initial oracle incorrectly expected an empty database: official-market-context persistence had already independently committed a valid `PendingOfficialClose`. The oracle was corrected to compare the independently read pre-decision snapshot and assert its exact pending identity. Assertions that all staged decision participants remain uncommitted were retained. This was an oracle error, not a product RED; no production fix was made. The corrected case passed (**1 passed, 3 deselected in 10.57s**). A development run of the other cases passed (**3 passed, 1 deselected in 28.94s**), but source changed during that run, so it is not stable-candidate evidence.

After strengthening assertions, the author's coordinated frozen-source run passed **4 tests in 38.53s**. Adjacent notification, admission, lifecycle, and composition tests separately passed **118 tests in 7.16s**, with one existing Starlette/httpx deprecation warning. Ruff passed. The four tracked source fingerprints were identical before and after that window:

| Source under `src/trade_plan_monitor/` | Author-window SHA-256 |
| --- | --- |
| `web/monitor_composition.py` | `3D9D8A7B36CEDB248A06E2D633078F06CF3F7A8BAEE2A7D61511B4985F7B52C8` |
| `runtime/recovery.py` | `7F8FFB6AAE4739C864FB3C40F7EEDF5E270422D826E2903F1344453DB4658B7D` |
| `runtime/production.py` | `021993781B39E3F1E88EB63402D30CCE1EBB65B2D6B0DD4746F646A0FE252581` |
| `runtime/service.py` | `DF3EE4DF221D7FB40088B3CDAD66F263C8AB1D529C2A5774F213AFE41E9FAD43` |

The root reviewer then independently reran this unchanged test: **4 passed in 36.82s**, Ruff passed, and no P1/P2 review findings. This second frozen window used the same HEAD `7c178184b84b835aa93b40e7120185c95fccaccf` plus the F2 core working-tree candidate. Its monitored fingerprints were identical before and after:

| Source under `src/trade_plan_monitor/` | Root-review-window SHA-256 |
| --- | --- |
| `runtime/recovery.py` | `C090C838BF61F5DA7EB89184C2153AC9D83C00490A9AB49D97BA6F0CC7E5378F` |
| `runtime/recovery_targets.py` | `C19139108C4C7B2192AF10B7391F0A4899E821685B40705FE0A6FBB9A32618BD` |
| `runtime/production.py` | `7D5FA3724CE7CC0243535B2A7FDCD54E78EB7A4A703FAEFC41F56AF553CEBBB7` |
| `web/monitor_composition.py` | `DBB3381DC4D29F80AAAF755F9340317D3A655D85C8C85649883A059C3404901E` |

The unchanged test SHA-256 is `46E62F96653D36D7C1DEF4A0520DE7F98BE1E90103123CABA26C31825B8C7632`. Both windows are working-tree candidate observations, not clean-HEAD aggregate acceptance or approval of F2. Development and final runs overlap; author 4, adjacent 118, and reviewer 4 are separate observations, not a cumulative unique-test count.

## SNKR-05 Reproduction and limits

Run from `trade-plan-monitor` with its existing environment:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_notification_kill_restart.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_notification_delivery.py tests/integration/test_delivery_admission.py tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py -m 'not live' -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_s3_notification_kill_restart.py
git diff --no-index --check -- NUL tests/integration/test_s3_notification_kill_restart.py
```

The initial development commands used the same test path with `-k business-uncommitted -x -q --tb=short` and `-k 'not business-uncommitted' -x -q --tb=short`. The no-index check reports the new-file difference and may warn about LF-to-CRLF normalization; those are not a whitespace defect.

Not covered: real channel behavior/idempotency, every signal or both plan families, every instruction-level crash point, cross-day release, arbitrary downtime, concurrent owners, or connected F2/F3 worker stop/drain. The earlier four official-close kill/restart cases remain distinct local evidence, not a substitute for the whole crash/send matrix. No new sending policy or external exactly-once promise is introduced.
