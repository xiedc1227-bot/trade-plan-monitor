# C1 stock-minute permission proof offline verification

> Canonical English report; the matching review copy is `2026-09-27-c1-stock-minute-permission-proof-verification.zh-CN.md`.

## SMPV-01 Scope and status

Date: 2026-09-27. Contract, independent code re-review, and final documentation review passed; offline implementation is complete and its eight-file local commit is authorized. This report accompanies the paired `2026-09-27-c1-stock-minute-permission-proof-contract` documents. C1 and production recovery acceptance remain open.

Changes are limited to `src/trade_plan_monitor/market_data/tushare.py`, `src/trade_plan_monitor/market_data/tushare_client.py`, two new unit-test files, and the paired contract/report documents. No production, controller, scheduler, or ordinary minute filtering code was changed. `_fetch_frame` now preserves the local request-not-started sentinel; both client routes do likewise and retain raised structured HTTP status before generic connection handling.

## SMPV-02 Implementation evidence

- Both single-symbol methods use strict whole-response parsing with fixed 12-second grace and a maximum 15-second evidence interval. A longer configured transport timeout cannot validate a late result and is not forcibly shortened by these methods.
- Frozen slots `MinutePermissionEvidence` contains sorted unique A/B/C source dates and classification counts. It is not a persisted-calendar or runtime-authority approval.
- Required columns, exact scalar types, canonical source timestamps, duplicates, finite positive OHLC, integer shares, non-negative amount, and 640 resource limits are checked before result construction. B cannot be in the future; C can have an END label after R only when its interval has already started.
- The private no-positive-proof exception is a typed `INVALID_RESPONSE`, raised outside the parsing catch. Provider exceptions are rebuilt with fixed metadata so raw cause/context/attributes/notes do not survive. Original trusted `RequestNotStartedError` objects propagate unchanged through fake SDK, `_fetch_frame`, and installed default/direct client wrappers.
- Test calendar callbacks fail immediately if called. Transports are in-memory fakes; installed-client tests replace both network routes and use a fake token. No real service, user database, history write, evaluation, or notification is exercised.
- Independent code review found two defects after the initial green runs: `DataFrame.to_dict` invoked numeric-subclass hooks before validation, and callback/SDK mutation could change the source label mid-request. Exact reproductions failed before the fix. Bounded tuple iteration now preserves object-cell types, and a verified local label is frozen before the callback and used through result construction. Ordinary numeric DataFrame columns remain accepted. Independent correction re-review passed as recorded below.

## SMPV-03 Executed RED and GREEN

Commands ran from `trade-plan-monitor/` with its `.venv`.

| Stage | Command | Observed result |
| --- | --- | --- |
| Initial parser RED | `.venv/Scripts/python.exe -m pytest -q tests/unit/test_stock_minute_permission_proofs.py --tb=no` | 129 failed; new methods were absent. |
| Independent transport RED | `.venv/Scripts/python.exe -m pytest -q tests/unit/test_minute_permission_transport.py --tb=short` | 116 failed, 2 passed; also reproduced existing request-not-started swallowing in wrapper/fetch paths. |
| First combined GREEN | `.venv/Scripts/python.exe -m pytest -q tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_minute_permission_transport.py --tb=short` | 247 passed in 0.94s. |
| Expanded adjacent regression | Command below | 518 passed in 32.47s, including 11 additional clock/zero-boundary cases. |
| Additional transport boundaries | `.venv/Scripts/python.exe -m pytest -q tests/unit/test_minute_permission_transport.py --tb=short` | 136 passed in 0.79s; includes 18 added typed-error sanitization and 30/120-second transport-configuration cases. |
| Code-review reproduction RED | Focused reproduction command below | 14 failed, 1 passed, 140 deselected in 0.74s: six subclass-hook failures and eight frozen-label failures; ordinary numeric-column baseline passed. |
| Code-review reproduction GREEN | Same focused reproduction command | 15 passed, 140 deselected in 0.57s after fixes. |
| Final combined minute GREEN | `.venv/Scripts/python.exe -m pytest -q tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_minute_permission_transport.py --tb=short` | 291 passed in 0.93s after fixes. |
| Final adjacent regression | Final regression command below | 773 passed in 37.59s after fixes. |

```text
.venv/Scripts/python.exe -m pytest -q tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_minute_permission_transport.py tests/unit/test_tushare_client.py tests/unit/test_daily_permission_proofs.py tests/unit/test_tushare_permission_probe.py tests/unit/test_tushare_market_index.py tests/unit/test_tushare_historical.py tests/unit/test_live_certification_profiles.py tests/unit/test_live_certification_runner.py tests/integration/test_tushare_contract.py tests/integration/test_production_semantic_gate.py tests/integration/test_production_certification_gate.py --tb=short
```

The later 18 transport cases were added after the 518-case run; these counts describe their actual runs rather than pretending all cases belonged to the same run.

Focused reproduction command (executed before and after the two fixes):

```text
.venv/Scripts/python.exe -m pytest -q tests/unit/test_stock_minute_permission_proofs.py -k "numeric_subclass_hooks or source_label_is_frozen or builtin_numeric_dataframe" --tb=short
```

Final regression command, including ordinary market-data and request-admission/reservation checks:

```text
.venv/Scripts/python.exe -m pytest -q tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_minute_permission_transport.py tests/unit/test_tushare_client.py tests/unit/test_daily_permission_proofs.py tests/unit/test_tushare_permission_probe.py tests/unit/test_tushare_market_index.py tests/unit/test_tushare_historical.py tests/unit/test_live_certification_profiles.py tests/unit/test_live_certification_runner.py tests/unit/test_market_data.py tests/unit/test_request_recovery_admission.py tests/unit/test_permission_reservation_ack.py tests/unit/test_realtime_index_permission_parser.py tests/integration/test_tushare_contract.py tests/integration/test_production_semantic_gate.py tests/integration/test_production_certification_gate.py --tb=short
```

Earlier green counts are historical evidence, not acceptance of the two defective behaviors. The final runs above include their regression guards.

The coordinating task reported the independent reviewer's actual post-fix results: **291 minute tests passed, 297 adjacent tests passed, and 32 expanded assertions passed**, with **no remaining P1/P2**. The expansion checks both operations, A/B/C int/float subclasses with zero hook calls, callback/SDK changes to END/UNVERIFIED while retaining frozen START, C-only no-proof rejection, and ordinary numeric dtype compatibility. These are separate reviewer runs, not additions to the author's 773 count; exact reviewer commands were not included in the handoff and are not invented here.

## SMPV-04 Matrix coverage and remaining validation

`test_stock_minute_permission_proofs.py` covers SMP-RED-01–05, 07, 09–12 and worker-side SMP-RED-08: A/B/C mixes, no proof, immutable results, frozen clocks, opening/future/session boundaries, raw row caps, multi-day dates, aliases/schema before record conversion, exact scalar types, arbitrary conversion traps, 640 raw/coefficient/expansion boundaries including zero/amount, and no calendar access. The existing ordinary-minute contract tests provide behavior regression coverage.

`test_minute_permission_transport.py` covers SMP-RED-06 and transport aspects of 07/10: one attempt across fake/default/direct routes; original not-started objects; returned/raised HTTP 401/403/429, including connection-first multiple inheritance; timeout/TLS/connection/decode/schema/provider failures; safe cause/context/attributes; configured 30/120-second timeouts with exact 15-second acceptance and one-microsecond overrun rejection.

Owner-side open-day, epoch, stop, generation, and authorization checks in SMP-RED-08 remain future integration work. No test here claims to clear a production latch or exercise scheduling.

The full non-live command `.venv/Scripts/python.exe -m pytest -q -m "not live" --tb=short` was interrupted before completion when independent review reported the two defects (process exited with code 1 after interruption). It is not a full-suite result and was not rerun after the fixes; final validation is the 291-case minute suite and 773-case adjacent regression above. No full-repository pass is claimed.

## SMPV-05 Static checks and practical limits

Final Ruff and diff whitespace checks passed. Paired documentation structure, signatures, commands, numeric thresholds/results, and working-tree ownership were also checked. Other tasks' production/wiring/kill-restart files are outside this change. Only this slice's eight files are authorized for local commit; no push, deployment, or real-service certification is included. Static commands:

```text
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/market_data/tushare.py src/trade_plan_monitor/market_data/tushare_client.py tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_minute_permission_transport.py
git diff --check
```

Independent code re-review passed, but production must still verify all returned source dates against current persisted open-day evidence before clearing the corresponding operation. Real `rt_min` may return no A rows; offline fixtures do not establish live recovery feasibility. Strict proof-only column/scalar rules intentionally do not alter ordinary business minute reads. Final documentation reconciliation passed before the eight-file local commit authorization.
