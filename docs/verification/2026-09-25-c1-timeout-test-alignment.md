# C1 market-data timeout test alignment

## Finding and correction

The complete `test_tushare_provider_errors_use_stable_codes_and_drop_raw_context` parameter group was run before editing: **1 failed, 13 passed**. Only the injected `requests.Timeout` case expected `TRANSIENT` while the provider returned `TIMEOUT`. `git show HEAD:src/trade_plan_monitor/market_data/tushare.py` confirmed that the existing `_safe_provider_error` branch explicitly maps `requests.Timeout` to `TushareErrorCode.TIMEOUT`; this was not introduced by the recent daily or index probe changes. The single outdated test expectation was changed to `TIMEOUT`. Product error classification was not changed.

## Verification and boundary

After the assertion correction, the parameter group passed **14/14**, the full `tests/unit/test_market_data.py` passed **171/171**, and Ruff on that file passed. Earlier dated evidence correctly recorded the failure when observed; this record supersedes it for current test status. No real Tushare request, external notification, user database migration, push, or deployment occurred. The five business permission scopes still lack production maintenance scheduling, so C1 remains **OPEN**.
