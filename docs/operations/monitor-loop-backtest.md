# Monitoring-loop Backtest Operations

Canonical English; Chinese review copy: [monitor-loop-backtest.zh-CN.md](monitor-loop-backtest.zh-CN.md). This guide describes the implemented single-plan research workflow. Executed evidence and review status are in [verification](../verification/monitor-loop-backtest.md).

## ML-O01. Supported scope

Each run freezes one complete reviewed Schema 5 plan, one symbol and one opening account. Its rules stay fixed across eligible trading days; fills update the account and shared monitoring state. Daily successors, plan chains, simultaneous plans and shared multi-symbol capital are outside this release. One unfinished task occupies the common backtest slot across synchronization, dataset verification, extraction and replay. Queued, running, cancellation-pending and expired unconfirmed work retain the slot until terminal completion or explicit recovery; changing pages does not release it.

This is offline simulation. It does not activate a live plan, place broker orders, send real notifications or rewrite monitoring holdings. Historical compatibility runs remain readable under their original contracts.

## ML-O02. Prepare and review one source

Open `/backtests/new`, choose the source preparation mode, and paste a complete source or read one UTF-8 text/Markdown file. Preserve authored time, historical availability and effective trade date separately; date-times use Asia/Shanghai. Missing facts remain unknown. Save before extracting. The accepted preparation identity is retained in the URL so refresh/return loads that same record.

Extraction uses existing configured AI guards and at most 3 source-revision-bound attempts. A failed retryable attempt needs an explicit retry; an unknown paid outcome is not silently retried. Review every executable field, mapped source clause, supplement, exclusion and opening-account fact. Unsupported/unresolved clauses block freezing. AI supplies a candidate; explicit human confirmation supplies review authority.

Editing the saved source invalidates its candidate/review and requires a fresh extraction and review. Submitted frozen inputs stay immutable. A reviewed `FROZEN` candidate publishes the authoritative preparation manifest as `candidateHash`; its embedded extraction hashes retain the original source/extraction binding. Use that manifest identity for run submission.

## ML-O03. Opening account, costs and time

Opening lots describe actual source holdings; they are not simulated buys and incur no purchase fee. Distinguish per-share acquisition cost, total lot cost, source reference price and a time-valid opening valuation. For example, 100 shares at 40.105 yuan/share preserve total cost 401050 fen. Unknown cash, inventory, cost or sellability cannot become an invented zero. A human correction needs explicit reviewed evidence.

Choose `FOLLOW_REMINDERS` or `OBSERVE_ONLY` and exact fees/slippage. The first mode derives full-quantity requests from valid reminders; the second changes no holdings. `RECORDED_ACTIONS` remains a bounded domain compatibility value and does not add automatic requests; the source preparation UI offers the two implemented automatic-response choices. Whole-lot, T+1, CORE, position ceiling, risk/conflict and fees-inclusive cash checks remain authoritative. No partial substitute is applied when the complete quantity fails.

An omitted/null end date resolves once at accepted submission to the Shanghai date and evidence cutoff. An explicit end is inclusive and cannot precede the historical start or exceed submission's local date. Retries/restarts reuse the original cutoff. A current incomplete session retains only available complete evidence; genuine gaps remain blockers. No event precedes source availability/effectiveness. Ending preserves open holdings and creates no liquidation trade. The report shows the requested/resolved end, actual evidence cutoff and unavailable market-return metrics separately from historical-cost profit/loss.

## ML-O04. Public API and result reading

Mutations use the existing local-origin guard and `Idempotency-Key`. Freeze a request body/key before sending; retry an unknown response with exactly the same pair. Server revisions and identities are authoritative.

| Operation | Route |
|---|---|
| Save one source | `POST /api/v1/backtest-preparations` |
| Read durable progress | `GET /api/v1/backtest-preparations/{preparation_id}` |
| Edit the source | `PUT /api/v1/backtest-preparations/{preparation_id}/source` |
| Extract explicitly | `POST /api/v1/backtest-preparations/{preparation_id}/extractions` |
| Review and freeze | `POST /api/v1/backtest-preparations/{preparation_id}/reviews` |
| Request cancellation | `POST /api/v1/backtest-preparations/{preparation_id}/cancellations` |
| Confirm ended unknown extraction | `POST /api/v1/backtest-preparations/{preparation_id}/recoveries` |
| Submit/read a run | `POST /api/v1/backtest-runs`, `GET /api/v1/backtest-runs/{run_id}` |
| Read causal audit / fills | `GET /api/v1/backtest-runs/{run_id}/details`, `GET /api/v1/backtest-runs/{run_id}/fills` |

Prepared submission binds `preparationId`, `manifestHash`, `response`, `costs` and optional `endDate`. It accepts no handwritten future trades. `monitor-loop-result-v1` results carry frozen provenance, complete plan/opening account, native `backtest-report-v4` metrics and causal `monitor-loop-event-v1` rows. Native audit reading uses `kind=DECISION`; pages are server ordered and capped at 100. Receipts keep the public simulation identity; internal stored fill keys bind the run so sequential experiments cannot collide. Existing legacy staged fills remain strictly validated and replayable without duplicate rows.

The result page shows summaries, evidence cutoff, account/valuation limitations, chronological evaluations/reminders/requests/executions/state/valuation, and actual fill receipts. It never manufactures per-fill profit/loss. Native loop export returns 409 before streaming and its UI action is unavailable. Existing frozen research export bytes retain their compatibility behavior.

## ML-O05. Failed, cancelled and unknown operations

A 503 indicates a scoped capability failure or a bounded SQLite BUSY/LOCKED conflict; source/run forms retain the original intent for an explicit safe retry. A 409 means the state/binding or common unfinished slot conflicts: read authoritative state before another action. A failed job and a degraded service are separate facts; neither a refresh nor a history read silently resubmits work.

Cancellation acknowledgement is not physical completion. An in-flight extraction retains admission until its owned call ends. An unknown generation remains visible across reload/navigation; confirm that the prior call ended through the explicit recovery action before releasing it. Late source results are fenced by generation/revision. Replay cancellation or publication failure creates no completed partial report. Cancellation/lease/commit races retain existing claim-token and atomic-publication checks.

## ML-O06. Storage and finite limits

Default isolated paths are `data/backtest-market.sqlite3`, `data/backtest-results.sqlite3`, `data/backtest-preparation.sqlite3` and `data/backtest-cursor.key`. Existing path/storage-domain validation remains. Browser/API commands do not accept arbitrary server file paths. Replay reads durable copied input/evidence and performs zero configuration, provider, AI or notification calls.

A source is capped at 150000 characters; bounded source bytes, 3 extraction attempts, 70000 loop records and at most 420001 audit rows are explicit limits. Results retain the latest 30 runs as one total cap, including pinned runs, with bounded cleanup and owned input/report-file protection. Pages cap at 100; integers remain safe and monetary arithmetic remains exact. Historical synchronization is single-active, uses BACKGROUND request priority and at least 1.25 seconds between actual starts across calendar/daily/minute/limit requests. Cache hits add no wait; cancellation observes pacing before the next provider call. No global quota allocator or dynamic CPU/memory controller is added.

## ML-O07. Reproduce local verification

Run from `trade-plan-monitor/` with the existing development environment. These checks use synthetic facts and disposable stores, not live user data or paid providers. If the default OS pytest temporary root is unavailable, add a fresh workspace `--basetemp=.pytest_cache/local-verification-unique` directory without changing checks:

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_production_composition.py tests/integration/test_backtest_isolation_fault_matrix.py tests/integration/test_monitor_loop_parity.py -q -m "not live"
.venv/Scripts/python.exe scripts/verify_backtest_thread_load.py --profile windows-threads --offline
npm --prefix web run test:e2e -- tests/e2e/monitor-loop-backtest.spec.ts
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
```

The Windows load command runs 600 seconds of ten-stock monitoring baseline and 600 seconds with sequential admitted native replay/WAL load, with at least 120 seconds between replay admission starts (at most five experiments per ten minutes). This bounds only the offline fixture; it adds no production submission throttle. Each phase collects at least 1000 status requests and verifies all scheduled evaluations and steady-state semantic reminders. Status p95 <= 250 ms, p99 <= 1000 ms, added p95 <= 100 ms and added scheduling p99 <= 250 ms remain the planned gates. `--smoke` is a short development probe and cannot certify them. The ignored `.pytest_cache/backtest-thread-load.json` records host, duration, actual percentiles, memory/WAL observations and completed jobs; the bilingual verification report preserves executed evidence. This fixture certifies the measured workload only, not live AI/provider access, large production datasets or every shared-host contention pattern.

The measured-load correction filters current evaluation history before decoding legacy markers and reuses that compatibility decision within one monitoring transaction. Malformed and legacy data keep their original protection; no persistent cache, historical rewrite or monitoring rule change is introduced.
