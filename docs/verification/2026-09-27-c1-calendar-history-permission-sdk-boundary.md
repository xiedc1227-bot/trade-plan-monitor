# C1 UPD-S1 calendar/history permission SDK boundary verification

> Canonical agent-facing English version. The matching Chinese review copy is `2026-09-27-c1-calendar-history-permission-sdk-boundary.zh-CN.md`.

## CHB-01 Scope and status

- Date: 2026-09-27.
- Authority: approved [UPD-05, UPD-S1 and provider portion of UPD-R06](2026-09-27-c1-unified-permission-dispatch-contract.md), commit `26b15e2`.
- Status: **Implemented; writer verification and independent Sol review passed; no P1/P2; five-file local commit approved**.
- Owned paths: `src/trade_plan_monitor/market_data/tushare.py`, `src/trade_plan_monitor/market_index/tushare.py`, `tests/unit/test_calendar_history_permission_sdk_boundary.py`, and this bilingual report.
- The separately committed business `current_day_minutes` hook at `e7c6d8f` is preserved. This slice changes no generic protocol, SDK resolver/helper implementation, production owner, controller, scheduler, service or database schema. Concurrent minute-owner review work is separate and not included in this slice.

## CHB-02 Minimal implementation

`probe_trading_calendar_permission(exchange, anchor, *, _physical_start=None)` forwards the optional invocation-local callback through `_trading_calendar` to the existing `_fetch_frame` helper. `probe_historical_minutes_permission(index_code, anchor, *, _physical_start=None)` forwards it to the existing `_call_index_sdk` helper.

Ordinary arguments are constructed before entering the helper. When the hook is present, the existing nominal resolver completes real `_CertifiedTushareClient` checks and resolves the inner callable, then runs the guard immediately before invoking that callable. The hook is neither an SDK kwarg nor provider state; an endpoint is resolved anew per invocation. Guard/resolver exceptions, including the identical `RequestNotStartedError`, remain outside provider classification. Actual SDK failures retain the existing classification and sanitization.

Omitting the hook or supplying `None` retains the ordinary path, argument values, response parsing, error behavior and caches. Calendar proof still accepts an exact closed-day row. Historical-index proof still requires the existing complete 48/49-row closed-session parser and does not fill, replace or clear caches. No owner deadline, anchor policy, stock-minute classification, expiry threshold, authority I/O or automatic dispatch is added to these providers. Timing/revocation guards in the tests are callback fixtures, not new provider policy; production owner guards belong to UPD-S2.

## CHB-03 RED-to-GREEN and focused checks

From `trade-plan-monitor/`:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_calendar_history_permission_sdk_boundary.py -q --tb=short
```

- Initial RED: **44 failed, 10 passed**. The new opt-in calls failed because both permission methods lacked `_physical_start`; existing no-hook classification/parser paths continued passing.
- After minimal forwarding: **6 failed, 48 passed**. Those six failures were a test expectation typo in the historical-index `fields` ordering. The provider's existing order was preserved and the fixture expectation corrected; this is not a product fix.
- Expanded target: **62 passed**.

The checked-in cases cover both endpoints through the real certification wrapper and dynamic inner resolver: certification/resolution delays of 2 seconds, exactly 15 seconds and 15 seconds plus one microsecond; authority revocation during either stage; real wrapper refusal; unchanged sentinel/RuntimeError/ValueError/CancelledError identity from the guard; resolver exception identity; no private SDK kwargs; a complete request before guard; closed calendar success; complete historical proof; omitted/`None` hook compatibility; preservation of existing cache objects; unchanged generic protocols; malformed response and actual HTTP 403/429/500 classification; and concurrent/sequential invocation isolation. Concurrent worker tests fail on SQL or Task access. One concurrent invocation can refuse while the other reaches exactly one inner SDK call.

## CHB-04 Provider/proof regression and lint

The complete selected legacy provider/proof/boundary matrix passed **904 tests**, including all **62** new cases, with one existing Starlette/httpx deprecation warning. The final rerun after the test-only line wrap also passed **904 tests**. Both provider source hashes and the final test hash were unchanged across that last run:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_calendar_history_permission_sdk_boundary.py tests/unit/test_market_data.py tests/unit/test_tushare_client.py tests/unit/test_tushare_historical.py tests/unit/test_tushare_live_probe.py tests/unit/test_tushare_market_index.py tests/unit/test_tushare_permission_probe.py tests/unit/test_index_http_classification.py tests/unit/test_minute_permission_transport.py tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_sdk_call_boundary.py tests/unit/test_current_day_business_sdk_boundary.py tests/integration/test_tushare_contract.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_production_sdk_call_boundary.py -q --tb=short
```

Focused Ruff and source whitespace checks:

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/market_data/tushare.py src/trade_plan_monitor/market_index/tushare.py tests/unit/test_calendar_history_permission_sdk_boundary.py --output-format concise
git diff --check -- src/trade_plan_monitor/market_data/tushare.py src/trade_plan_monitor/market_index/tushare.py
```

Review snapshot SHA256:

- `market_data/tushare.py`: `5FD5ACF4ECA7177E1B95CAE5C6ADDE022A1DBB2454BBE15DEA371FDD0FA4FDE0`.
- `market_index/tushare.py`: `84AD6415E2C331B06238A8E9692F6C5A26F12A3C6CE6B68542F8BF005B3908CF`.
- `test_calendar_history_permission_sdk_boundary.py`: `12735A260C1BD09FE1FDFE633EDF3532E5B562122BB067ACAB2B9B95816E9CEC`.

Independent Sol verification passed **62 tests in 0.79s** with the CHB-03 target command, and **237 adjacent tests, 1 existing warning in 48.03s** with the command below. Reviewed source/test hashes were unchanged. These separate runs overlap the writer matrix and are not additive. Independent Ruff and scoped whitespace checks passed; no P1/P2 remains.

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_tushare_permission_probe.py tests/unit/test_sdk_call_boundary.py tests/unit/test_tushare_historical.py tests/unit/test_tushare_market_index.py tests/unit/test_index_http_classification.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_sdk_call_boundary.py -q --tb=short
```

## CHB-05 Remaining gates

Independent implementation review passed and the five-file local commit is approved. This is only the provider seam portion of UPD-R06. Actual calendar/historical owner guards, snapshot/anchor rules, cancellation/admission, unified dispatch and RUNNING/DEGRADED progress belong to UPD-S2–S5 and are not established by these callback tests. C1 remains OPEN.

Tests use fake SDK callables, controlled clocks and the real wrapper/parser; adjacent integration fixtures use temporary databases. There were no real-service calls, user-database access, notifications, dependency changes, push or deployment. No complete repository-suite or live-release claim is made.
