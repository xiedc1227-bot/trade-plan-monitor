# S3 installed runtime read liveness

## S3-READ-01 — Scope

2026-09-27. Test-only S3-08 evidence on committed production baseline `6bcf080`. Adds `tests/integration/test_s3_installed_runtime_read_liveness.py`; changes no source, schema, public protocol, lifecycle policy or UI. Only a temporary SQLite database, controlled clock and fake SDK are used; HTTP clients are forbidden. No real service, real notification, user-database migration, push or deployment.

This covers the real lunch-standby/overdue-progress contrast. C1 dual-clock recovery reads and F3 fact-repair-versus-decision reads still await their connected implementations. It does not close S3-08, C1/C3, step 4 or the final aggregate gate.

## S3-READ-02 — Actual path and assertions

- Start the installed composition at `11:29:15` with a legally activated legacy plan. Release the real scheduler's `11:30:12` wait; the actual fake SDK request produces exactly one committed evaluation with `market_data_at=11:30:00` and `evaluated_at=11:30:12`.
- At `12:00:00`, the scheduler's promised next poll remains in the future. The actual read service reports `RUNNING`, not read-only, with that exact `next_poll_at`. The dashboard remains connected under the original generation, and current symbol health remains actionable. The installed stream's heartbeat carries the dashboard's exact sequence, generation and runtime start time. Historical decision content and all captured business rows are unchanged; no pending official close exists.
- Then deliberately leave the actual scheduler permit blocked and move observation time to its promised `next_poll_at + 1 microsecond`. Invoke the real admitted owner's heartbeat and verify its new durable `last_alive_at`. The owner remains `RUNNING` in the same generation, but actual dashboard reads are disconnected, symbol health is unavailable, and the installed heartbeat reports `runtimeLive=false` with null generation/start time. A durable owner heartbeat therefore cannot conceal overdue scheduler progress.
- Historical LIVE decision content is retained, not rewritten as a current signal. SDK calls, evaluation ledger/result/head, alert events, delivery attempts and pending closes remain unchanged across the stalled observation. The test inspects the installed stream's frame directly; it is not a browser/socket transport test.

The fixture uses only committed helpers. It permits genuine bounded maintenance sleeps through lunch, so later F3 wiring can be verified without replacing the scheduler or hard-coding its afternoon next wake.

## S3-READ-03 — Oracle corrections and verification

This is a new evidence test for existing behavior, not a production fix or a claimed product RED→GREEN change. First, a fixture used the wrong table name `notification_attempt`; it was corrected to the existing `delivery_attempt` after a failed run. Next, an assertion compared `get_health().runtime_generation` with the internal owner identity and failed. Independent Astra inspection confirmed that both existing v1 health models deliberately mark this field `exclude=True`; revalidation therefore recreates its legacy internal default. This is not a public generation field or a proven S3 product defect. The existing public contract binds generation through dashboard snapshots and heartbeat frames. The test now strengthens those actual public-path checks while retaining the internal same-owner assertion. No source/schema was changed and no promised assertion was removed. The corrected initial test passed **1 test, 1 warning, 2.28s** before the final exact evaluation-time assertions were added.

Final writer command:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_installed_runtime_read_liveness.py tests/integration/test_persistent_monitor_read_service.py tests/integration/test_websocket.py -q --tb=short
```

Result: **47 passed, 1 warning, 7.92s**, including the new real-composition case. The warning is the existing Starlette/httpx deprecation. Production source fingerprints were identical before and after this run and matched `6bcf080`:

| File under `src/trade_plan_monitor/` | SHA256 |
|---|---|
| `runtime/production.py` | `582BAF6F419F6CC2B139020BCD668663BCB4658F252D2BCCD2CB165936A10531` |
| `runtime/service.py` | `72E2EFCE3BFCC3F99FC0BA54B920E6BE20C44FD8AD0161F15C7E982750920989` |
| `runtime/scheduler.py` | `956887081F421DA68CAE222195CD35C3D946785513639C686976C278A542CC30` |
| `web/monitor_composition.py` | `2B32683AAAC03898BAD8AB82FC69930062690ED81A9B36CCCE1FCB8F6FFCEB6C` |
| `web/persistent_monitor_read_service.py` | `AEE9D668B7AECAEA8843B2897AD667E213C925B5B00232C4694188F0BEEFB23C` |
| `web/websocket.py` | `ACFD28A58DF92969C70DFB64FC42634222590072ACE8A2791EC80E077EC2E573` |

Independent Sol review passed with no P1/P2. The same three-file command independently passed **47 tests, 1 warning, 7.96s**; limited Ruff on the new test and its no-index whitespace check passed. In this separate stable window, `runtime/production.py` was the uncommitted F3-A candidate with SHA256 `75218CA0FA35DBB1995476D9DB83094C6585691F58D26E3B2C40FE4B74099E6F`; the other five production fingerprints matched the table. The test SHA256 remained `D7B6E9B7D6A6E3E7D11C3B679400B1E0134CDD01A9658365D306ACA99AB0F21E`. This independent run does not approve F3-A. Re-run the case after final F3-C/C1 connection. Writer and independent counts overlap and are not additive; no passing aggregate result is claimed.
