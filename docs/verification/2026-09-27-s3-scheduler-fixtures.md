# S3 scheduler fixture migration: offline verification

## Scope and evidence baseline

This test-only slice updates `test_live_pipeline_acceptance.py`, `test_runtime_crossed_market_deadline.py`, and `test_s3_index_retry_process.py` against base `53b731271b4b3a10a8558da993ecd000f03c1d58`. The prior full non-live regression reported 16 failures, 5695 passes, 1 skip, 4 deselections, and 1 warning in 1087.48 seconds. Seven failures belong to these three files. Independent pre-migration reproduction reported live pipeline: 3 failures in 10.48 seconds; crossed market: 3 failures in 18.68 seconds; index retry: 1 failure in 4.11 seconds. These baseline results were supplied by the coordinating investigation, not rerun by this implementation slice.

The outdated assumptions were fixed sleep counts, first-wake classification as market/index work, and startup repairing all five stock symbols. Previously unreachable downstream assertions required execution before drawing conclusions about product behavior.

## S1: Timer and index invalidation fixtures

The timer case uses a local clock that releases actual scheduler due times through `10:05:12`, with at most 12 releases, then parks without advancing. It waits for the next parked sleep and asserts exactly the five market deadlines `10:01:12` through `10:05:12`, five `rt_min` calls, one owner/generation, a running unfaulted runner, exactly one persisted decision/result head, target `10:05`, and evaluation time `10:05:12`. Restart retains the same projection. The shared `ControlledClock` is unchanged.

The expiry/tamper cases precommit only legitimate historical input: five symbols, each with 64 normalized END minutes from `09:31` through `10:34`, for 320 rows. Prices, volume, and amount match the fake SDK, and `received_at` is legal. In one temporary UoW transaction, the real `history.upsert_minutes` derives replaceable quotes; after verifying no original quotes exist, the fixture deletes only those five derived `LatestQuote` rows before the single commit. A fresh UoW verifies all minute endpoints, no `10:35`, no quotes, and no decision, decision head, or index snapshot. This is test setup only.

Real startup performs at most one stock-history fetch. The original real market deadline then produces all 65 minutes for each symbol and exactly five decisions, each retaining activation revision 1. Existing shared-index hash, independent index, BSE blocking, Schema 1, and one request per three index endpoints per available index assertions remain. Both expiry and tamper execute their downstream checks: all snapshots become `BLOCKED`, and no additional index SDK request occurs. The existing legacy-certification path remains unchanged.

## S2: Crossed market and invalid elapsed review

A file-local sleep override releases actual due times through the fixed first market handler at `10:04:12`, with at most 10 releases, then parks. The positive case still crosses time inside the real fake-SDK call to `10:05:13`. It waits for the original `10:05:12` handler to return and the next sleep to park, so a stock-recovery wake at `10:05:13` cannot repair the gap before observation. All duties are observed; `STOCK_RECOVERY` is allowed, while the market subset must be exactly `10:01:12` through `10:05:12`, once each. The original owner/generation, `10:04` gap, `GAPPED` health, advancing projection revision, and zero evaluations/alerts are asserted.

Both negative cases run the actual `10:04:12` handler before rolling back to `10:04:11` or moving to September 11. They retain read-only `DEGRADED`, `MARKET_DEADLINE_REVIEW_UNAVAILABLE`, no next poll/retry, a live runner, the original last deadline, and zero alerts, with added zero-evaluation and same-owner/generation checks.

## S3: Index retry across an OS restart

The stepped clock releases only actual scheduler sleeps, bounded by 32 steps per phase. The failure phase waits for the real `REALTIME_MINUTE` target `10:00` at `10:00:12` to complete before capturing market evidence. The five-index, blocked dependent plan, healthy explicit plan, actual fake-channel send, receipt, and clean-stop assertions remain.

Restart remains at `10:00:20`, preserving the durable retry floor and original cutoff. A transparent `_run_deadline` observer captures every SDK call, business-table snapshot, and send at the complete `INDEX_RECOVERY` entry and exit without changing parameters, return values, exceptions, or scheduling. Its nonempty SDK delta must consist only of the required index's `idx_mins`, `rt_idx_min_daily`, and `index_daily` endpoints; it never filters stock calls out of that delta. Adjacent stock-maintenance intervals are recorded separately. Business data and sends also remain unchanged from startup through index completion.

Copied-observation negative controls still reject injected stock calls, evaluation writes, alert writes, and sends. Subsequent real scheduler wakes reach `10:05:12` within 32 steps, complete target `10:05` exactly once, and park without further advancement. Existing original-receipt, event, target-uniqueness, no-duplicate-delivery, distinct-PID, and clean-exit checks remain, with owner/generation assertions.

## Verification and limitations

Final author verification on the frozen three test files:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_live_pipeline_acceptance.py tests/integration/test_runtime_crossed_market_deadline.py tests/integration/test_s3_index_retry_process.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_live_pipeline_acceptance.py tests/integration/test_runtime_crossed_market_deadline.py tests/integration/test_s3_index_retry_process.py
```

Result: **24 passed, 1 warning in 30.91 seconds**; Ruff passed. The warning is the existing Starlette/httpx deprecation. The first complete live-pipeline run passed 19 tests in 21.35 seconds; crossed-market passed 3 in 4.20 seconds; index-process passed 2 in 7.56 seconds. Timer development also exposed the obsolete first-sleep assertion and author mistakes in the newly added identity field assertion; those were corrected before final verification. No downstream product failure was observed in this tested slice.

Independent verification of the same three frozen files reported **24 passed, 1 warning in 31.21 seconds**, with Ruff and diff checks passing and no P1/P2 finding in static review. This is a separate run, not an additional 24 distinct tests. The reviewer verified unchanged before/after hashes for these three tests and six relevant source files (production, service, scheduler, composition, recovery, and targets); this sampling is not a hash of the entire source tree.

Frozen SHA256 values:

| File | SHA256 |
| --- | --- |
| `tests/integration/test_live_pipeline_acceptance.py` | `972C20C70BAD157F6AF3AA065BE2BB00627029A2B334CD2D58034A0693A87C4C` |
| `tests/integration/test_runtime_crossed_market_deadline.py` | `1F878CF8B66802CCF36B9C362AEED1E5C270358740B6015BDE08602852048F5F` |
| `tests/integration/test_s3_index_retry_process.py` | `4CE3658C64E7F46F7586068CA5FD622FE4FA085AECFD05A3A44E5F781D7924FD` |

No production source changed in this slice. The coordinator's final regression against the committed combined change remains required; this report does not claim the full suite is green. All work uses temporary SQLite, injected clocks, fake SDK data, and fake delivery. No live provider, external notification, real user database, push, deployment, or hot reload was used. The implementation agent did not commit; the coordinator owns local commits.
