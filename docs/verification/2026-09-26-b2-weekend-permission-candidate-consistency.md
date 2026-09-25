# B2 weekend permission candidate consistency: offline verification

## Scope

This bounded repair makes three existing reads agree with the completed weekday-open rule. B1 `historical_anchor` chooses only a completed persisted SSE row with `weekday() < 5` and `is_open=True`. B1 realtime `current_open` requires today to be a weekday and its unique persisted SSE row to be open. The existing `_historical_index_permission_anchor` seven-day helper applies the same weekday-open rule. `calendar_anchor` still accepts a completed weekend row, open or closed, so `trade_cal` can prove calendar access. No scheduler, reservation, or physical probe path was added.

## Verification

Two new RED cases showed that a newer false Sunday-open row replaced Friday's historical index anchor and that a false Saturday-open row generated a realtime index candidate. After the repair, the historical candidate and existing helper both choose Friday; the Saturday realtime scope has no candidate or physical SDK call. A guard case confirms that a persisted Sunday-closed row remains a valid `TRADING_CALENDAR` anchor. Existing weekday behavior is covered by adjacent historical, realtime, B1, and INDEX_DAILY regression tests. The focused and adjacent command passed **104 tests**; full Ruff passed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_permission_candidate_selection.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_production_index_daily_permission_maintenance.py -q
.\.venv\Scripts\python.exe -m ruff check .
git diff --check
```

This remains candidate selection and existing historical anchor read only. Unified six-scope scheduler wiring and its market-deadline cursor proof remain OPEN. No real Tushare request, notification, user database change, push, or deployment occurred.
