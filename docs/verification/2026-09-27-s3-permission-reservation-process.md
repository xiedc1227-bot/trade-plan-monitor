# S3 permission reservation across sequential processes

## Status and scope

Author acceptance: **2 passed in 7.90s**, no warnings. Independent review and rerun: **limited pass**, **2 passed in 7.74s**, no warnings or P1/P2 findings within this scope. This is new UPD-R17 evidence, not a baseline RED or a production bug fix.

The only test added is `tests/integration/test_s3_permission_reservation_process.py`. It covers one representative scope, `INDEX_HISTORICAL_MINUTES` (`idx_mins`), through the real common `run_permission_maintenance_unit`, production composition, controller and SQLite repository. Two scenarios exercise the generic durable admission boundary. This does not claim all eight scopes or UPD-R18 automatic RUNNING/DEGRADED wakes.

The tested checkout was HEAD `3f111f73508049f263787b4ec2c1a4a87d4903fc` plus the uncommitted UPD-S3 production candidate. Although all imported fixture helpers are committed, the common method is not yet committed. These three test/report files must land with the accepted S3 source or immediately after it; they are not independently ready to commit onto that HEAD.

## R17-P01 — Raw 300-second floor

Both children use a real index-only composition with no active plans, valid index evidence, the original completed SSE anchor `2026-09-07`, and the current open calendar day. The initial permission latch at `2026-09-08 10:00:14+08:00` is explicit fixture input, **not** a measured reservation.

1. Child 1 starts at `10:00:15`, reaches RUNNING, and parks its actual scheduler with zero released sleeps. Its complete SDK call list is empty and its persisted checkpoints are unchanged by startup.
2. One common maintenance unit makes exactly one fake `idx_mins` SDK call, receives `BLOCKED_PERMISSION`, and retains the real reservation at `10:05:15` (`now + 300 seconds`). Exactly one original acknowledgement follows durable commit.
3. Child 1 successfully stops, drains and exits with code 0 before Child 2 is spawned.
4. Child 2 starts at `10:05:14.999999`, again RUNNING with zero startup SDK calls and unchanged checkpoints. A common unit at that instant performs zero reservations and zero SDK calls. The unit at exactly `10:05:15` reserves once, calls once, validates the original anchor proof, and clears its own block. Its callback observes the new durable floor `10:10:15` before the original acknowledgement.

## R17-P02 — Later shared 429 and changed token

The first reservation and clean-exit boundary are the same. Before stopping, Child 1 advances to `10:02:15` and uses the same real controller for one separately counted fake `index_daily` call that returns `RATE_LIMITED`. This is explicit setup work, not a second common-unit call. It establishes shared cooldown `10:07:15` while retaining the raw historical permission floor `10:05:15`.

The test manually changes only the dummy credential between stopped processes, keeping the endpoint identity. This is not hot reload. Child 2 restores both floors unchanged and starts RUNNING with an empty SDK call list. Common units at `10:05:14.999999`, exactly `10:05:15`, and `10:07:14.999999` all perform zero reservations and zero SDK calls. Exactly `10:07:15` permits one reservation and one original-anchor proof; the callback sees `10:12:15` durably stored before acknowledgement. The raw floor is not overwritten by the later shared floor at any refusal.

## Shared hard assertions

- Real OS `spawn` creates both children; the parent joins a successful old-process exit before creating the new owner. All time advances are monotonic.
- The actual runner is parked, not replaced. Both children must be RUNNING, repository-bound, index-authorized and stock-semantic-free. Startup performs **zero calls across all SDK endpoints** and leaves the complete checkpoint snapshot unchanged.
- The observer wraps `_permission_probe_reservation_callback` transparently. At each actual callback, a fresh separate read-only SQLite connection must see the exact `now + 300` row for the stable endpoint identity. It then forwards the original callback once and verifies the real rotation acknowledgement. Seed rows and callback construction do not count as reservations.
- Every common invocation hard-asserts matching reservation/SDK deltas of either 0 or 1. The separately counted 429 setup has one physical attempt and no extra permission acknowledgement.
- Real market-window checks and the original anchor are not mocked. Each physical common call must use `idx_mins`, SSE composite and the original anchor's request dates. A valid complete historical frame is checked by the real provider proof path.
- Full rows from all application tables are compared before/after startup, every unit, setup 429, stop and process replacement. Only schema metadata, runtime liveness and provider recovery bookkeeping are excluded; facts, quotes, indexes, evaluation/risk/HOLD/delivery/audit state remain unchanged.
- Within each child, runtime instance/generation remains the same, with no runner failure or restart. Successful stop empties owned tasks and controller slots, closes admission, drains the runner and reports the database STOPPED. Cross-process generations are distinct as expected.

## Commands and candidate window

Run from the repository directory:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_permission_reservation_process.py -q --tb=short
.venv/Scripts/ruff.exe check tests/integration/test_s3_permission_reservation_process.py
git diff --check
```

The author target passed **2 tests in 7.90s**, without warnings. Target Ruff passed; `git diff --check` found no whitespace errors (Git printed its ordinary LF/CRLF notice for the separately owned production WIP).

The source writer supplied a short freeze at the production hash below and was released immediately after the run. The initial/final PowerShell table display abbreviated the hash columns; the full values below were recorded in JSON before releasing that freeze. Other source files were unchanged tracked files at this HEAD. This is a frozen candidate window, not a clean-HEAD or full-suite claim.

| File | SHA-256 |
|---|---|
| `runtime/production.py` | `1AD6922F9253369BAF7691FF751D33AF8B931FBC4EC612CE1D088E84248B173E` |
| `runtime/service.py` | `1FBF2D7C6731F46A4104F0C55C1EC1CB89F3C961482E55D9D87FB7C83FAB84C5` |
| `runtime/scheduler.py` | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| `web/monitor_composition.py` | `3030F227DE0DA8EF02C69BF04996FCE92AF10546C577B10D955CED51AA339C68` |
| `runtime/request_control.py` | `11AC5CBEDEB85BD651A1D28C0CA84F305EB815415D3FC950A2E9657A5A11B640` |
| `state/runtime_recovery.py` | `F4F762197F9A7FEAFB6BED6D5BCE911CE6DF3A0092B7911A5A4D8E6BE5F55AF3` |
| `test_s3_permission_reservation_process.py` | `C634BB3D21E01FCAE2E559FE42A6055C9D9DD9F431ABC5E4210289E256F18B4A` |

Source paths in the table are relative to `src/trade_plan_monitor/`; the test is under `tests/integration/`.

### Independent verification

The independent reviewer reran the same pytest command above on HEAD `3f111f73508049f263787b4ec2c1a4a87d4903fc` plus the frozen production candidate: **2 passed in 7.74s**, no warnings. Target Ruff, the three-path `git diff --check`, static review and English/Chinese parity passed, with no P1/P2 findings for these files. This count overlaps the author run and is not added to it.

The reviewer recorded complete, untruncated paths and 64-character hashes immediately before and after the completed pytest run. All six sampled source files and the test were identical. The sampled files were `runtime/production.py`, `runtime/scheduler.py`, `runtime/service.py`, `runtime/recovery.py`, `runtime/recovery_targets.py`, `web/monitor_composition.py` and `test_s3_permission_reservation_process.py`. Production, scheduler, service, composition and test match the corresponding author-table hashes. The two additional source hashes are:

| File | SHA-256 |
|---|---|
| `runtime/recovery.py` | `E9F6D412042A4CB6A8A65ED8ED3E9FC4A9D1C9971186F8646AAD5581A2B9C051` |
| `runtime/recovery_targets.py` | `C19139108C4C7B2192AF10B7391F0A4899E821685B40705FE0A6FBB9A32618BD` |

The independent sampling set did not include the author table's `runtime/request_control.py` or `state/runtime_recovery.py`; their author values remain as recorded, not relabeled as independently sampled before/after hashes. This limited acceptance does not approve the broader S3 common dispatcher. A separate future-defer-path P2 is being addressed by its source writer; this R17 window is not evidence that that path passed. The uncommitted-source landing dependency above still applies.

## Boundaries

Temporary SQLite, local dummy credentials, virtual controller pacing and fake SDK frames only; no live provider, notification, service, real-user database, migration-policy change or production edit. This proves sequential restart floor preservation, not concurrent-process exclusion, an inter-process lease, exactly-once probing, or atomicity between reservation and final SDK entry. The runner is deliberately parked and the common method is explicitly invoked; UPD-R18 automatic eight-scope progression, UPD-S4/S5, C1 and the final S3 integration gate remain open. Independent acceptance must use a coherent source window again if the candidate changes; historical pass counts are not additive.
