# Backtest production-fake acceptance

Status: PASS

- Evidence date: 2026-08-31 (Asia/Shanghai)
- Evidence baseline: `main` at `f877d8c77b41cec03e58d838e5cb0f01531300d7`; this report records the accepted candidate derived from that baseline without asserting its eventual commit ID.
- Boundary: offline production composition and deterministic fake contracts only. No real Tushare, broker, notification, credential, AI-provider, or external-network call was made.
- Scope note: the five BT050 deliverables are the acceptance test, this bilingual report pair, and the bilingual todo updates. Separately authorized production prerequisites were repaired before BT050 could pass; they are reviewed and verified as prerequisites, not misreported as additions to the exact five-file BT050 harness scope. No threshold was relaxed.

## Reference environment

| Item | Fixed observation |
|---|---|
| OS / host | Windows 11 `10.0.26200`, Intel Core Ultra 9 275HX, 24 logical processors, 31.43 GiB available memory |
| Python / SQLite | CPython 3.14.7 x64 / SQLite 3.50.4 |
| Node / npm | Node 24.13.1 / npm 11.8.0 |
| Browser | Playwright 1.62.1, isolated Chromium 151.0.7922.34, Chromium-only acceptance |
| Storage / power | NTFS fixed `D:` volume, 931.5 GiB total, balanced power scheme |
| Runtime | One process, one active replay slot, local SSD, fake provider, no concurrent benchmark workload |

## Integrated functional evidence

`BT050-JOURNEY` passes in `tests/integration/test_backtest_acceptance.py::test_fake_production_journey_is_complete_offline_and_live_state_is_unchanged`: the fake production path executes `sync → verify → submit → poll → result → pin → export`, uses production route/composition boundaries, and reads/writes no live provider state.

`LIVE-STATE-ZERO-DIFF` and `NOTIFICATION-ZERO-CALLS` are exact assertions in that node: the captured live-state fingerprint is unchanged, and provider, notification, and WebSocket delivery call counts remain zero. All visible fills and exports are labelled historical simulation/research output.

`BT050-TWO-SYMBOL` passes in `tests/integration/test_backtest_acceptance.py::test_each_fixture_symbol_has_stable_buy_and_t1_exit_bytes`: independent multi-day runs for `003043.SZ` and `600000.SH` each contain a buy and a T+1 reduction/exit, and repeated run/report/export bytes are identical.

The two new functional nodes passed together as `2 passed`; the fixed acceptance file contains eight collected nodes.

## 2026-09-02 board-index extension evidence

The approved `market-index-context` design is implemented offline across monitoring and backtesting. The closed `board-index-map-v1` maps only the five approved boards and rejects unclassifiable symbols without fallback. Shared snapshot tests prove that one index/cutoff/request set is acquired once and published immutably; decision tests prove that two plans can produce different final outcomes from the same snapshot and that a plan with no index leaf is unchanged when index data is absent or blocked.

Schema v2 adds the automatic reference-market binding and six allowlisted condition leaves with exact bounds, three-valued `MISSING_INPUT` behavior, deterministic path evidence, and new hash domains. Existing Schema v1 plan/result goldens remain unchanged. The generated AI schema change is separately versioned as `plan-extract-v2`; the byte-identical v1 prompt remains available at SHA-256 `420e06c0a8ab136a1b95c8218474fccd7f134d1bc5c9e1365e0c6a4a099e3d8d`, and v2 is locked at `6d9ba53055700e508251fc62ce3a10c2c719b68874ac78aee9f27cbd40127daf`.

Backtest dataset v2 freezes normalized index artifacts and exact membership without rewriting v1 datasets. Run v3 reuses the shared snapshot/formula evaluator, persists per-decision reference-market evidence, and publishes summary-v3 export evidence while summary-v2 and fills-v2 bytes remain compatible. The pre-run coverage endpoint and completed-run index-series endpoint are server-authoritative, bounded, and represented in the frozen 41-path OpenAPI contract with SHA-256 `18ce84db8156ad5c4db94a193157e6509b46ab4a03bfdc1ea2b2dceb88fe9d0c`.

Verification completed without provider credentials or external traffic:

- affected snapshot/runtime focused regression after the final cache-identity and official-close batching fixes: `54 passed`;
- complete non-live backend collection: `2,104 passed, 1 skipped`; the final working tree passed all eight long-running acceptance nodes in `2,598.17 s`, and the remaining partition passed as `2,096 passed, 1 skipped, 4 deselected`;
- AI prompt compatibility/version regression: `72 passed`;
- frozen OpenAPI snapshot regression: `13 passed` across `41` paths, and generated TypeScript has no drift;
- frontend unit suite: `30` files and `497 passed`;
- isolated Chromium: `7 passed`, including server-resolved pre-run coverage, the frozen reference-index tab, exact plan paths, and persisted decision evidence;
- Ruff, `compileall`, OpenAPI/generated-TypeScript drift check, Vue/TypeScript type-check, production Vite build, and whitespace check passed.

Real board-index provider capability is intentionally `UNVERIFIED`. No Tushare or other provider endpoint was called; exact intraday/daily interfaces, account entitlement for all five index codes, timestamp/field semantics, quotas, and maximum history remain outside this authorization. The offline implementation exposes strict provider protocols and deterministic fakes and must not be interpreted as live readiness.

## Backend resource and performance evidence

`BT050-RESOURCE` uses the approved fixed fixtures and never calls the network.

### BT-FUNCTIONAL-20D

Five measured fresh database repetitions, after warm-up, all pass the 30 s / 512 MiB / 64 MiB / 32 MiB gates:

```text
elapsedSeconds = [5.597796800, 5.520017000, 5.475313000, 5.480158400, 5.444831700]
workingSetDeltaBytes = [13496320, 12861440, 12902400, 12992512, 13561856]
marketDatabaseAndWalBytes = [4235264, 4235264, 4235264, 4235264, 4235264]
resultDatabaseAndWalBytes = [1392640, 1392640, 1392640, 1392640, 1392640]
```

The final traced-heap node reports `12,678,486` bytes against the 256 MiB limit. It passes as `tests/integration/test_backtest_acceptance.py::test_twenty_day_replay_meets_traced_heap_budget`.

### BT-CAPACITY-1Y

The exact fixture contains ten fixed symbols, 252 trading days, 604,800 usable minute bars, 400 calendar days of warm-up, one frozen dataset per repetition, and ten sequential one-symbol runs. One successful full warm-up preceded the following three fresh measured repetitions:

```text
repetition-1 seconds = [106.295148400, 106.055265700, 104.515315200, 108.556621300, 106.568615600, 106.352307200, 104.775915400, 104.630981600, 103.592741000, 104.496511300]
repetition-2 seconds = [103.749614400, 105.201066500, 104.754093900, 104.687957000, 104.773838400, 104.863972400, 104.684553400, 104.984016300, 104.928564100, 104.851780100]
repetition-3 seconds = [106.300322100, 105.931607800, 106.199623500, 106.405021900, 105.729062700, 105.998598400, 105.680132400, 106.039019600, 106.199076700, 106.013356700]
marketDatabaseAndWalBytes = [519028736, 519028736, 519028736]
resultDatabaseAndWalBytes = [184909824, 184909824, 184909824]
workingSetDeltaBytes = [67825664, 67137536, 64708608]
```

All 30 replay values are below 120 s; every market/result database is below 512/192 MiB and every working-set delta is below 768 MiB. The exact capacity traced-heap node reports `123,830,868` bytes against 384 MiB and passes as `tests/integration/test_backtest_acceptance.py::test_252_day_replay_from_ten_symbol_dataset_meets_traced_heap_budget`.

The prerequisite RED was `959,445,307` traced bytes. The accepted repair streams the canonical report hash at top-level and encodes one already-validated decision at a time. Runner goldens remain identical (`19 passed`), the final peak is bounded, and no hash domain or public report field changed.

### BT-QUERY-LARGE and BT-EXPORT-100K

The fixture has 10,000 jobs, 1,000 completed runs, 100,000 target fills, 30,000 rows of each public detail kind, and 2,000 equity points. Five warm-ups plus 30 measured calls pass:

| Operation | p50 ms | p95 ms | max ms |
|---|---:|---:|---:|
| jobs | 2.529 | 2.895 | 3.059 |
| runs | 49.707 | 50.927 | 52.629 |
| fills | 5.458 | 5.759 | 5.781 |
| decisions | 9.238 | 9.625 | 9.882 |
| signals | 9.264 | 9.604 | 9.633 |
| outcomes | 9.625 | 9.921 | 10.067 |
| equity | 87.444 | 91.851 | 138.556 |

Query memory delta is `1,589,248` bytes and DB+WAL is `298,213,376` bytes. Pages remain at most 100 items, each item at most 32 KiB, JSON below 4 MiB, and equity exactly 2,000 points.

```text
exportFirstByteMs = [2.7377, 2.7569, 2.7174, 2.6593, 2.7122, 2.8713, 2.8024, 3.0776, 3.0798, 2.7860, 2.8057, 2.7528, 2.8589, 2.7283, 2.8529, 2.7950, 3.0727, 3.1176, 2.9188, 2.7701, 2.7511, 3.0803, 2.6918, 2.8374, 3.0930, 2.6989, 3.2186, 3.1143, 2.8103, 2.6789]
exportThroughputMiBPerSecond = [6.2086, 6.1234, 6.2454, 6.1157, 6.2000, 6.1693, 6.1502, 6.0388, 6.1672, 6.0885, 6.1561, 6.1213, 6.1920, 6.0896, 6.1698, 6.1085, 6.1147, 6.0674, 6.1391, 6.1535, 6.0889, 6.1712, 6.0916, 6.1745, 6.0963, 6.0955, 6.0668, 6.1321, 6.0974, 6.1282]
```

First-byte p95 is about 3.115 ms, minimum throughput is 6.039 MiB/s, export memory delta is `2,945,024` bytes, and maximum chunk size remains below 64 KiB. The CSV header is emitted after active-v2 metadata validation; the complete 100,000-row publication set is content-hash, JSON-identity, and set-hash verified before the first fill row. Payload/SQL-identity tamper regressions pass (`5 passed` in the export file), and disconnect behavior is cited below.

## Browser, bundles, and accessibility

`BROWSER-CHROMIUM-ONLY` uses an isolated Chromium production build at 1440×900, 4× CPU slowdown, 20 ms loopback latency, five warm-ups, and 20 measurements per route. It makes no Gecko/Firefox compatibility claim.

| Route | LCP p75 / max ms | INP p75 / max ms | CLS p75 / max |
|---|---:|---:|---:|
| `/backtests` | 172 / 192 | 0 / 0 | 0.04019 / 0.04019 |
| `/backtests/new` | 172 / 188 | 16 / 24 | 0.04019 / 0.04019 |
| `/backtests/data` | 172 / 216 | 16 / 24 | 0.04019 / 0.04019 |
| `/backtests/{runId}` | 204 / 208 | 0 / 0 | 0.02107 / 0.02107 |

Zero INP means the observed event stayed below Chromium PerformanceEventTiming's reporting floor. Representative interaction p95 values are filter 21 ms, page 30 ms, result tab 21 ms, validation-summary focus 30 ms, cancellation dialog open 29 ms, and close 28 ms. The sort control is intentionally disabled with the fixed value `completedAt_desc`; no synthetic sort interaction was fabricated. All browser samples had zero console, API, failed-request, unexpected-request, or external-network findings.

Production build gzip sizes are 26.54 KiB for the entry, 23.17 KiB for the shared Vue helper, 5.98/6.61/8.25/11.28 KiB for the four non-chart backtest routes, 10.68 KiB for the shared backtest API chunk, and 168.36 KiB for the lazy ECharts chunk. The three non-chart routes load zero ECharts bytes; the detail route loads it only after the equity tab.

The allowed Chromium E2E files passed `6 passed`: `web/tests/e2e/backtests.spec.ts` and `web/tests/e2e/accessibility.spec.ts`. They cover 320/768/1024/1440 layouts, 200% text, keyboard/reduced motion, request/timer/DOM limits, lazy loading, and zero serious/critical axe findings. The protected `web/tests/e2e/security.spec.ts` was neither read nor run. The Windows `NVDA` four-route checklist remains PASS from BT049/BC18 (`cb81cf4`); no screenshot, trace, profile, or download is tracked.

## Migration, rollback, race, retention, and isolation evidence

The following exact nodes were rerun together and passed as `12 passed`:

- `MIGRATION-ROLLBACK` — `tests/integration/test_backtest_migrations.py::test_migration_decision_is_bound_to_source_and_verified_backup_facts`
- `MIGRATION-IDENTITY` — `tests/integration/test_backtest_migrations.py::test_market_metadata_migration_preserves_all_identity_bearing_rows`
- `BACKUP-RESTORE` — `tests/integration/test_sqlite_backup.py::test_verified_backup_restores_to_a_readable_database`
- `CANCEL-FIRST-RACE` — `tests/integration/test_backtest_job_coordinator.py::test_atomic_completion_gives_cancellation_first_one_terminal_and_no_partial_result`
- `PUBLICATION-FIRST-RACE` — `tests/integration/test_backtest_job_coordinator.py::test_atomic_completion_gives_publication_first_one_terminal_and_visible_result`
- `RECOVERY-FENCING` — `tests/integration/test_backtest_job_leases.py::test_recovery_has_exactly_three_claim_generations_and_fences_stale_tokens`
- `REPLAY-RESTART` — `tests/integration/test_backtest_runner.py::test_midrun_cancellation_and_restart_replay_from_the_frozen_beginning`
- `RETENTION-BOUND` — `tests/integration/test_backtest_retention.py::test_result_cleanup_consumes_only_caller_budget_and_never_vacuums`
- `WAL-SNAPSHOT` — `tests/integration/test_backtest_result_queries.py::test_detail_page_uses_one_wal_snapshot_during_partial_cleanup`
- `EXPORT-BOUNDS` — `tests/integration/test_backtest_export_api.py::test_disconnect_stops_before_pulling_the_next_chunk_and_closes_iterator`
- `EVENT-LOOP-ISOLATION` — `tests/integration/test_backtest_job_coordinator.py::test_blocking_job_keeps_event_loop_responsive_and_heartbeats_on_one_owned_thread`
- `PRODUCTION-PLAN-ISOLATION` — `tests/integration/test_backtest_production_composition.py::test_production_factory_is_lazy_and_run_replay_reuses_one_plan_snapshot`

Migration authorization binds a recomputed source fingerprint to verified backup facts; the deterministic test backup SHA-256 fact is `dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd`, and a mismatched source fingerprint is rejected. Restore checks `PRAGMA integrity_check = ok` and the WAL sentinel. Rollback is therefore a verified file restore, not reverse or guessed SQL. Existing v1 bytes and identity-bearing rows remain unchanged.

Board-index startup compatibility adds two focused nodes:

- `MARKET-INDEX-SCHEMA-EXPANSION` — `tests/integration/test_backtest_migrations.py::test_exact_pre_index_market_schema_expands_without_rewriting_v1_data`
- `MARKET-INDEX-PARTIAL-FAIL-CLOSED` — `tests/integration/test_backtest_migrations.py::test_partial_market_index_extension_still_fails_without_mutation`

After the board-index schema extension, all `37` migration tests and the complete non-live backend suite excluding the separate heavy acceptance file passed as `37 passed` and `2098 passed, 1 skipped, 4 deselected`, respectively. A copy of the existing six-table `data/backtest-market.sqlite3` also completed the startup expansion with `PRAGMA integrity_check = ok`; all three new index tables were empty and the original database was not modified by this check.

## P19–P27 evidence map and checkpoint decisions

| Capability | Evidence |
|---|---|
| P19 compatibility/migration | MIGRATION-ROLLBACK, MIGRATION-IDENTITY, BACKUP-RESTORE, MARKET-INDEX-SCHEMA-EXPANSION, MARKET-INDEX-PARTIAL-FAIL-CLOSED |
| P20 Shanghai identity/input | existing run-input/time goldens plus the complete backend gate |
| P21 replay/publication | BT050-TWO-SYMBOL, REPLAY-RESTART, capacity/functional measurements |
| P22 query/export/retention | BT-QUERY-LARGE, BT-EXPORT-100K, RETENTION-BOUND, WAL-SNAPSHOT, EXPORT-BOUNDS |
| P23 jobs/recovery | CANCEL-FIRST-RACE, PUBLICATION-FIRST-RACE, RECOVERY-FENCING, EVENT-LOOP-ISOLATION |
| P24 backend API/composition | BT050-JOURNEY and PRODUCTION-PLAN-ISOLATION |
| P25 generated frontend contracts | production build, type-check, and frontend unit gate |
| P26 browser/accessibility | BROWSER-CHROMIUM-ONLY, axe, keyboard/responsive E2E, NVDA |
| P27 final integration | this report and `tests/integration/test_backtest_acceptance.py` |

`BC01` is explicitly re-evaluated as PASS: all four recorded checks are now satisfied. Two-symbol/multi-day actionable fills, durable lease/recovery, replay-from-start, LIVE-STATE-ZERO-DIFF, NOTIFICATION-ZERO-CALLS, resource ceilings, pin/unpin, and initial-lot/public result paths are covered. Historical acquisition remains separate from live Tushare acceptance, and no simulated record is presented as a broker fill or live alert. Strategy event-cursor resume remains the already documented deferral and is not silently claimed.

`T058` remains Open and externally gated: no live Tushare contract was authorized or run. `T059` remains Open and partially externally gated: no optional live AI gate was run. `C24` remains Open because live-contract/final-user release acceptance is outside BT050. These unchanged states are not treated as BT050 failures.

`BC19 / I4` is Complete. The final offline gate passed with `1,941 passed, 1 skipped` on the protected-file-excluded backend suite, `484 passed` on the frontend unit suite, `6 passed` on the allowed Chromium E2E suite, and passing Ruff check/format, `compileall`, `pip check`, OpenAPI/TypeScript generator `--check`, type-check, production build, and whitespace checks. The final fresh-context adversarial review covered correctness, security, architecture, performance, compatibility, test adequacy, and bilingual evidence; it found no unresolved P0–P2 issue. Two maintainability-only P3 observations were corrected and the affected backend gate then passed `302 tests`.

## Known warning and artifact policy

The only recurring test warning is the pre-existing Starlette `TestClient`/httpx2 deprecation warning. Raw temporary SQLite databases, browser profiles, screenshots, traces, downloaded exports, and profiler data remain outside Git. The five protected validation-only files remained untracked and untouched and were excluded from formal file lists.
