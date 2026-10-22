# Plan runtime read timezone repair — 2026-10-22

## PR-TZ-001 — Failure and root cause

Opening a saved plan draft requested both `GET /api/v1/simulation-position-inventory`
and `GET /api/v1/plan-runtime/{symbol}`. The simulation inventory request failed while
building `DailyInventoryResource`: the production lifecycle clock returns an aware
UTC datetime, but `evaluated_at` requires `ShanghaiDatetime`. The browser consequently
displayed `本地监控服务发生内部错误`. UTC `updated_at` values on persisted evaluation
heads exposed the same mismatch in `DailyStateView`.

The problem was response serialization, rather than invalid trading policy or a
reason to disable timestamp validation. Existing historical simulation data remained
subject to `DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED`.

## PR-TZ-002 — Repair and boundaries

`web/daily_service.py::read_daily` now reuses the existing `_shanghai_datetime`
conversion for current inventory responses, unsupported inventory responses, and
persisted evaluation-head timestamps. Conversion preserves the instant and rejects
naive timestamps. The production clock and persisted timestamps remain unchanged.

No response schema, source review, domain validation, legacy-data detection, trading
rule, activation operation, or inventory mutation was changed. There is no exception
suppression, inferred timezone, fabricated zero inventory, automatic migration of
historical positions, or new external AI/market-data request in this repair.

## PR-TZ-003 — Regression verification

The new file is `tests/integration/test_plan_read_timezone.py`. All test databases
are isolated from `data/monitor.sqlite3`.

| Check | Executed result |
| --- | --- |
| New regression tests before the repair | 7 failed, 4 passed; failures reproduce the strict timezone mismatch |
| New regression tests after the repair | 11 passed |
| Related regression selection, including the 11 new cases | 117 passed |
| Ruff on the changed Python source and new test file | Passed |

Coverage includes current and unsupported inventory responses, the unchanged default
UTC clock, UTC evaluation-head timestamps, conversion across the Shanghai calendar-day
boundary, rejection of naive clocks, continued rejection of raw UTC/naive values by
the response model, HTTP reads, and unchanged persisted inventory/activation records.

Executed test selections:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_plan_read_timezone.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_plan_read_timezone.py tests/integration/test_daily_simulation.py tests/integration/test_daily_plan_boundaries.py tests/integration/test_daily_plan_chain.py tests/integration/test_daily_simulation_review_regressions.py tests/integration/test_plan_production_composition.py tests/unit/test_daily_safety_boundaries.py tests/unit/test_current_review_contract.py -q --tb=short
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/web/daily_service.py tests/integration/test_plan_read_timezone.py
```

Windows TestClient execution used local event-loop support and unique workspace
temporary directories. No external provider was called. The 117-case result describes
the selected regression scope, not the entire repository suite.

## PR-TZ-004 — Actual draft page and protected state

The verified local service was restarted with its existing configuration. The saved
draft page was reloaded and inspected at:

`/plans/f053d41c-2eca-4c3b-980b-ac6c370c2881`

The page no longer displays the internal error. Both read requests return HTTP 200.
The actual retained state is `UNSUPPORTED`, with reason
`DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED`; the page displays
`计划当前状态：历史数据不支持模拟`. This is preserved protection, not a successful
simulation setup. Its inventory snapshot remains null.

| Acceptance item | Observed value |
| --- | --- |
| Plan identity | `SNGC-OBS-20261022`, version `1`, `605296.SH` |
| Persisted status | `DRAFT` |
| Technical alert | 1; `close`, offset `0`, `LT`, fixed `2659` `FEN`, `OFFICIAL_DAILY_CLOSE` |
| Buy / sell / risk-liquidation rules | 0 / 0 / 0 |
| Review binding | `review_id=null`, `review_revision=0`, `confirmed_at=null` |
| Activation button | Disabled |
| Plan hash | `18825a7f0dfd462f10b2392d74eaa826b6e6c11e128a54484937252320e2cea5` |
| Actual/simulated inventory and activation state before/after | Identical |

Protected-state comparison covers actual position tables, activation tables, risk
tables, and daily records other than extraction/review records. The draft's unchanged
hash and review binding were checked separately. No review confirmation, activation,
position initialization, or simulated trade was performed.

## PR-TZ-005 — Evidence

Sanitized evidence is under
`evidence/2026-10-22-plan-runtime-read-timezone/`:

- `acceptance.json`: persisted draft, typed responses, browser observations and final checks.
- `protected-before.json` / `protected-after.json`: protected record counts and hashes.
- `test-results.json`: executed red/green and related regression results.
- `http-status.txt`: successful local read request status lines.
- `draft-restored.jpg`: actual browser page after the repair.

The original research appendix and AI extraction verification archive remain unchanged
at `data/research/SNGC-OBS-20261022/validation-20261022-115118/`. Existing unrelated
working-tree changes were preserved.
