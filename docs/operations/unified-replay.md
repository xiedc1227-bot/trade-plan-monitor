# Current Plan Replay Guide

## R01. Local synthetic example

Run from `trade-plan-monitor/` with the existing development environment. This command creates a new temporary directory, synthetic raw daily/minute data, a frozen dataset, complete Schema 5 minute/daily plans, explicit research declarations, as input files. It contacts no provider and reads no local application configuration.

```powershell
$replayDemo = Join-Path $env:TEMP ("unified-replay-" + [guid]::NewGuid().ToString("N"))
.venv/Scripts/python.exe scripts/create_unified_replay_fixture.py --output $replayDemo
```

The generator creates inputs only; it does not execute a backtest. Output directories must be empty. The generated `dataset.json` contains `datasetHash`; `minute-plan.json` / `minute-research.json` and `daily-plan.json` / `daily-research.json` are independent usable pairs. All prices and conditions are synthetic. The daily example explicitly declares synthetic constant adjustment factors; these must never be copied as proof for real raw data. Both scripts initially contain no operations, so signals appear while inventory and cash remain unchanged. The minute signal confirms at 09:35 with `CURRENT_SESSION`; the daily signal confirms on 2026-08-24 with `NEXT_EXCHANGE_SESSION_ONLY` for 2026-08-25. Neither means a trade was executed.

## R02. Existing Web/API entrances

The API accepts parsed JSON as `researchInput`, never a filesystem path. Legacy plans forbid this field; current plans require it. API/Web accepts initial lots through `initialLots`. The backtest CLI and compatibility adapters have been removed.

For Web use, select the exact saved, reviewed current version on `/backtests/new` and paste the matching research JSON in “统一计划研究输入 JSON”. The plan does not need live activation. The server independently checks the saved immutable review; `review.confirmed: true` in the JSON cannot approve an unreviewed plan. Nested research fields keep their snake_case names, including `started_at`, `inventory_known`, `review.content_hash`, `adjustment_proofs` and `operations`. Outer HTTP fields retain camelCase. Missing or mismatched research authority returns a conflict; malformed or unsupported assumptions return validation errors.

The result page distinguishes evaluated signals from resulting state after scripted operations. It shows per-signal quantities, execution window and blockers, data blockers, reminder evidence and risk state. Optional JSON is detailed evidence, not the only explanation of a blocked signal.

The isolated real API/job/read/export path and browser fixture can be reproduced without a running production server:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_replay_entries.py -q -m 'not live'
Push-Location web
npm run test:e2e -- tests/e2e/backtests.spec.ts -g "current research input"
Pop-Location
```

The API test creates its own reviewed inactive synthetic plan and temporary databases. The browser uses the existing local fake API and actual typed decision bytes, exercises the current form/detail page, and checks accessibility and external-request/console failures. Neither is a real AI or provider certification.

The removed command tree is `backtest sync/verify/run/list/prune`, together with `BacktestApplicationService` and the synthetic fixture generator's `--run` dispatch. Old CLI invocations and the removed Python facade have no compatibility alias or replacement CLI. The shared production Web/API worker factory and frozen result formats remain supported. Bounded retention remains an internal capability; removing `prune` adds no automatic cleanup scheduler or public replacement endpoint. Command-surface regression is in `tests/unit/test_command_surface.py`.

## R03. Explicit operations and money

An empty `operations` array authorizes no inventory change. `SIMULATE` names a rule and exact occurrence or a risk kind, full positive whole-lot quantity, explicit timestamp and order. Current authority, T+1, CORE, capacity, quote and risk checks still apply. Partial requests are blocked; a consumed occurrence cannot grant the same trade again. Scoped positive/negative facts, independent-event evidence, deactivation, reviewed replacement termination and explicit risk reassessment are frozen inputs. A replacement does not execute a second plan. Saving another draft does not terminate the original authority.

The monitor receipt price is separate from research slippage and fees. Insufficient research cash blocks monetary valuation and leaves the complete monitor receipt intact; later returns remain null. Unknown inventory stays unknown. `DECISION` and `EXECUTION_OUTCOME` details use current typed evidence. Summary JSON uses `backtest-report-summary-v4`; the existing fills export route emits `explicit-simulation-valuation-v1` CSV for current runs, with separate `monitor_status` and `valuation_status` columns. Legacy exports retain their original bytes.

## R04. Limits

Daily-dependent rules require frozen adjustment proofs and verified session coverage. A future adjustment anchor is rejected. `FULL_SESSION_SUSPENSION` is explicitly blocked as `RESEARCH_FULL_SESSION_SUSPENSION_UNSUPPORTED`; it cannot override traded frozen minutes. `MANUAL_EVENT_RISK` is unsupported for current replay. The historical minute profile keeps its deterministic 12-second receipt grace and ready-dataset coverage requirements. This feature does not certify actual historical collection times, real holdings, broker orders, notifications or live providers.

Starting intraday may use an already completed same-day bucket under current monitor semantics, but produces no events, operations or valuation before `started_at`. Calendar context is at most 512 rows with forward context only through the next open session; missing historical coverage stays visible. The report fails with a stable error before exceeding 70,000 decision events or safe integer money limits. Existing API item/response/page limits also remain enforced.
