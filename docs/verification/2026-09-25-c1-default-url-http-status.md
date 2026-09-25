# C1 default URL HTTP status preservation (offline)

## RED and cause

The installed Tushare 1.4.29 `DataApi.query` checks a `requests.Response` by truth value. On non-2xx HTTP, it returns an empty DataFrame before the provider can inspect the status. An offline test with fake `requests.post` showed that the default URL route classified 401 and 403 as `INVALID_RESPONSE` without a permission latch, and 429 as `INVALID_RESPONSE` without shared cooldown. The same test's fake `connect_ip` route preserved `BLOCKED_PERMISSION` and `RATE_LIMITED`. No real service was called.

## Bounded change

`create_tushare_client` now installs an instance-owned query adapter only for its official default `DataApi` factory without `connect_ip`. It retains one `requests.post` call with the existing URL, JSON payload, timeout, and environment-managed proxy/CA behavior. An integer non-2xx status produces a sanitized `HTTPError` carrying only a synthetic status-code response; the raw response, request, body, and exception context are not attached. The adapter preserves 2xx DataFrame and provider-code handling, sanitizes malformed responses and transport exceptions, and closes every received response. A close failure cannot replace the classified outcome. Injected `data_api_factory` query implementations, the direct-IP route, and process-global SDK/requests behavior remain unchanged.

## Verification and boundary

The default URL 401/403/429 cases changed from RED to GREEN: the controller now retains permission blocks or shared 429 cooldown. Offline tests also cover 408/500 transient backoff, poison non-2xx bodies, valid and empty 2xx frames, malformed 2xx data, provider code/message classification, two client configurations, response closure, timeout sanitization, no secret exposure, and one physical request per call. `tests/unit/test_tushare_client.py` passed **58 tests**. The adjacent set with `tests/unit/test_monitor_runtime.py` and `tests/integration/test_production_certification_gate.py` passed **190 tests**. Whole-repository Ruff and diff checks passed. Independent Sol/`xhigh` review found no P1/P2 in this bounded change.

An unrelated baseline conflict remains in `tests/unit/test_market_data.py`: its injected `requests.Timeout` case expects `TRANSIENT`, while the unchanged HEAD provider code maps it to `TIMEOUT`. The isolated parameter still fails; this slice does not alter that classification or assertion. C1 stays **OPEN**, including the five production permission-recheck scopes recorded in `2026-09-25-c1-provider-recovery-evidence.md`. This offline result does not certify real Tushare permissions or service behavior. No real provider request, external notification, user database migration, deployment, or push was performed.
