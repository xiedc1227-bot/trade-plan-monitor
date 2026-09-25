# C1 daily permission probes: offline provider proof

## Scope and result

The read-only provider proofs for `DAILY_LIMITS`, `DAILY_BARS`, and `INDEX_DAILY` passed independent Sol/`xhigh` review with no remaining P1/P2 finding in this slice. They use fake SDK responses. They are **not yet connected to production permission maintenance**, do not select persisted anchors or schedule 300-second rechecks, and do not clear controller blocks or write business caches. C1 remains **OPEN**.

## Proof contracts

- `DAILY_LIMITS` requests `stk_limit(trade_date=D, fields=trade_date,ts_code,up_limit,down_limit)` for a caller-selected persisted completed open day. It validates every row of the whole-market batch, requiring 1–5,800 rows, unique canonical six-digit exchange identities on exactly `D`, finite positive raw prices, and `down_limit < up_limit`. No plan-symbol hit is required. Raw prices are not converted to A-share fen, so valid sub-fen B-share or fund values can pass. Exact primitive text/numeric values are checked before string conversion; raw text, Decimal coefficient, and fixed-point expansion are each bounded to 640 characters/digits under the stock-local rule. Required columns occur once, all column names are unique, and unique extra columns are accepted.
- `DAILY_BARS` requests `daily(ts_code=S, start_date=D, end_date=D)` for a caller-selected relevant stock and persisted completed open day. Its existing strict response profile validates the whole response and requires one valid official row for exactly `S/D`; empty suspended responses do not prove permission. Persisted stock-anchor selection and bounded candidate rotation remain future work.
- `INDEX_DAILY` requests `index_daily(ts_code=I, start_date=D, end_date=D)` for a certified READY index and a caller-selected persisted completed open day. It requires one valid official row for exactly `I/D`, unique required columns and unique column names, while accepting unique extra columns. It does not mutate index caches. Physical SDK HTTP 401/403/429 failures are safely classified for the controller, without retaining raw token context; `RequestNotStartedError` passes through unchanged.

## Verification and boundary

`tests/unit/test_daily_permission_proofs.py` passed **53 targeted tests** after RED-to-GREEN checks for missing probes, invalid whole batches, 640/641 decimal edges, extra/duplicate/missing columns, fake HTTP 401/403/429 controller effects, and deferred physical start. The adjacent command below passed **266 tests**, with **14 deselected** from the pre-existing `test_tushare_provider_errors_use_stable_codes_and_drop_raw_context` parameter group because its `requests.Timeout` expectation conflicts with the unchanged HEAD `TIMEOUT` mapping. Ruff on the two provider files and new test file, and `git diff --check`, passed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_daily_permission_proofs.py tests/unit/test_tushare_market_index.py tests/unit/test_market_index_data.py tests/unit/test_tushare_permission_probe.py tests/unit/test_market_data.py tests/unit/test_request_recovery_admission.py -q --tb=short -k "not test_tushare_provider_errors_use_stable_codes_and_drop_raw_context"
```

No real Tushare request, external notification, user database migration, push, or deployment occurred. The remaining five-scope production maintenance wiring and independent anchor selection are open. Separate review also identified raw SDK HTTP classification gaps in ordinary index request paths and existing index permission rechecks; those are outside this pure-probe slice. This evidence does not close A05, C1, or release acceptance.
