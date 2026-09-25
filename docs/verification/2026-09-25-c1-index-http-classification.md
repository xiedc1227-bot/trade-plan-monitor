# C1 index SDK HTTP classification: offline correction

## Scope and result

Independent Sol/`xhigh` review approved the bounded correction with no remaining P1/P2 finding in this slice. A private index SDK-call boundary now safely classifies raw HTTP failures for the ordinary `idx_mins`, `rt_idx_min_daily`, and `index_daily` requests, and for the existing historical and realtime index permission probes. The previously added pure `INDEX_DAILY` probe uses the same boundary. The controller, request arguments, cache policy, and physical request order are unchanged.

## Failure behavior

Fake status-only HTTP 401/403 errors now reach the controller as `BLOCKED_PERMISSION` for the affected index operation. Each operation retains its own permission latch and 300-second reservation; unrelated scopes are not latched. HTTP 429 reaches the shared rate-limit cooldown. Each attempt makes one SDK call. `RequestNotStartedError` passes through unchanged and does not become a provider failure. Sanitized provider errors are raised outside the raw exception handler, so raw token, response body, cause, and context do not remain on the exposed error.

## Verification and remaining gate

`tests/unit/test_index_http_classification.py` first produced **16 RED failures and 1 pass** across the five affected boundaries. After the correction, all **17 targeted tests** passed. The adjacent index provider, daily probe, realtime parser, request controller, and production index permission-probe suites passed **198 tests**. Ruff on the changed provider and new test file, and `git diff --check`, passed. All calls used fake SDK responses and temporary offline test state.

No real Tushare call, external notification, user database migration, push, or deployment occurred. The five remaining business permission scopes still lack production maintenance scheduling; persisted anchors and recheck orchestration are separate work. This correction does not close A05, C1, or release acceptance. C1 remains **OPEN**.
