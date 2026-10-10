# Spec: index-data

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-index-data.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Fetch or replay validated board-index bars, calculate reusable versioned numeric facts, and publish one immutable shared snapshot per `(indexCode, decisionCutoff)` for all plans evaluated at that cutoff. This module supplies data facts only and never emits a market-strength label or trade effect.

## Tech Stack and Commands

- Python 3.14, frozen strict Pydantic values, exact `Decimal`, SHA-256, and `Asia/Shanghai` timestamps.
- Provider protocols plus deterministic offline fakes; provider responses are untrusted.

```powershell
python -m pytest tests/unit/test_market_index_data.py -q
python -m pytest tests/integration/test_market_index_snapshots.py -q
python -m ruff check src/trade_plan_monitor/market_index tests/unit/test_market_index_data.py tests/integration/test_market_index_snapshots.py
```

Real Tushare or other provider calls are excluded from these commands and require separate authorization.

## Project Structure

```text
src/trade_plan_monitor/market_index/
├── models.py       # bars, health, fact requests, facts, snapshots
├── formulas.py     # market-index-facts-v1 pure calculations
├── provider.py     # live/historical provider protocols and safe errors
├── snapshots.py    # validation, unioned requirements, shared cutoff cache
└── canonical.py    # decimal, bar-set, request-set, and snapshot hashes
tests/unit/test_market_index_data.py
tests/integration/test_market_index_snapshots.py
```

## Data Contracts

`MarketIndexBar` is index-specific and cannot accept a stock symbol. It contains `index_code`, `interval=FIVE_MINUTE|OFFICIAL_DAILY`, `bar_at`, exact positive `open_points`, `high_points`, `low_points`, `close_points`, nullable exact non-negative `volume`/`amount`, `observed_at`, `source_kind=PROVISIONAL|OFFICIAL`, and a bounded provider revision. Daily `bar_at` is canonical 15:00 `+08:00`; five-minute `bar_at` is a completed session bucket. OHLC ordering, identity, duplicates, future cutoffs, gaps, timestamps, decimals, and source semantics validate before use.

`MarketIndexHealth` is `LIVE|STALE|GAPPED|BLOCKED`. Ordered unique issue codes are closed to:

- `MISSING_FIVE_MINUTE_BAR`, `MISSING_OFFICIAL_DAILY_BAR`, `INSUFFICIENT_HISTORY`;
- `STALE_DATA`, `DUPLICATE_IDENTITY`, `GAPPED_SERIES`;
- `INDEX_IDENTITY_MISMATCH`, `FUTURE_DATA`, `INVALID_TIMESTAMP`;
- `NONCANONICAL_DECIMAL`, `INVALID_OHLC`, `FORMULA_MISMATCH`, `PROVIDER_UNAVAILABLE`.

`LIVE` is the only health usable as condition evidence. Other health values remain displayable but make each affected index leaf return `MISSING_INPUT`; they do not create a global blocker outside a plan tree.

`MarketIndexSnapshot` contains identity, latest completed five-minute bar, the official daily history needed by the unioned requests, prior official close, ordered indicator facts, health/issues, `completed_bucket_at`, `observed_at`, `mapping_version`, positive `revision`, `bar_set_hash`, `request_set_hash`, `formula_definition_hash`, and `snapshot_hash`. It is frozen and contains no plan id, condition outcome, signal, `entryAllowed`, `decisionEffect`, or market classification.

## Reusable Facts and Exact Formulas

Formula version is `market-index-facts-v1`. Facts use `POINTS` or `RATIO` and retain parameters, result, input cutoff, source hash, health, and formula hash.

- `SMA(period)`: arithmetic mean of the last exactly `period` official open-day closes ending at the latest official day available at the decision cutoff. `period` is `2..250`.
- `SMA_LOOKBACK(period, lookback)`: a pair consisting of current `SMA(period)` and the `SMA(period)` whose end day is exactly `lookback` official open days earlier. It requires `period + lookback` closes; `lookback` is `1..60`.
- `RETURN(window, window_size)`: `(current_close / base_close) - 1`, where the base is exactly `window_size` completed observations before the current observation. `window` is `FIVE_MINUTE_BUCKETS|OFFICIAL_OPEN_DAYS`, `window_size` is `1..250`, and the input requires `window_size + 1` closes.

No forward fill, interpolation, constituent aggregation, unfinished quote, daily substitute for a five-minute request, or stock-bar substitute is permitted. Equality and condition thresholds are handled by `plan-index-conditions`, not by this module.

## Shared Snapshot Coordination

Before fetching one cutoff, the coordinator groups active Schema v2 plans by derived `indexCode`, extracts only their index fact requirements, and unions/deduplicates those requests. It then calls each index provider surface at most once for that cutoff and publishes one snapshot for that group. Plans read the same object/hash but evaluate independently.

The completed-snapshot cache key is `(mappingVersion, indexCode, decisionCutoff, requestSetHash, providerContentRevision, minimumFiveMinuteBarCount, minimumOfficialDailyBarCount)`. Because the provider revision is not guessed before acquisition, an internal `(mappingVersion, indexCode, decisionCutoff, requestSetHash, minimumFiveMinuteBarCount, minimumOfficialDailyBarCount, observedNoLaterThan)` prefetch key deduplicates only concurrent acquisition and is discarded when that task completes. Minimum counts are validated acquisition requirements used by the turnover projection without adding synthetic fact requests or affecting plan hashes. Usable completed snapshots are immutable and interned in a bounded 512-entry cache; a later call reacquires first so a new provider revision cannot be hidden. Unusable snapshots are not retained. Failure for one index publishes that index's blocked health and does not cancel or replace other indices. A plan with no index condition may receive an informational snapshot in live monitoring, but its decision does not require the snapshot; backtest coverage does not require index history for that plan.

One bounded exception to the ordinary one-acquisition-per-cutoff batch is the next-minute publication-lag retry allowed by `SPEC-monitor-index-trends`: once per cutoff it reacquires only indexes whose latest same-cutoff snapshot has exclusively `MISSING_FIVE_MINUTE_BAR` or `STALE_DATA` issues. It preserves each selected snapshot's fact requests and turnover minimum bar counts. Its partial batch persists only reacquired indexes; unchanged healthy and independently blocked heads remain untouched. A retry result is discarded if a newer cutoff or different request set replaced that index while acquisition was in flight. Ordinary `prepare` always reacquires through the revision-sensitive coordinator, including for new plan requirements and the next trading day.

A second exception recovers a transient `PROVIDER_UNAVAILABLE` for the failing index only. The index adapter classifies request-control `TIMEOUT` and `TRANSIENT` as retryable; permission, rate limit, certification, processing, and unknown errors do not enter this short retry. The same serial scheduler and shared request controller execute up to three additional attempts, due 30, 60, and 120 seconds after the preceding failure and bounded by five minutes from the first failure. Controller backoff and shared cooldown still apply. Recovery state (`indexCode`, cutoff, first failure, completed attempt count, next due time) is committed with the snapshot head and restored after restart only while that head is still blocked and the window has not expired. A newer cutoff or successful head supersedes recovery; older or failed results cannot overwrite an already `LIVE` same-cutoff head. Recovery commits index data and dashboard invalidation without replaying completed plan evaluations or notifications. Dashboard clients may show same-day historical five-minute bars with their explicit last-valid timestamp while current decision facts remain blocked; `recoveryAttempts` and `nextRetryAt` report a pending short retry, and absence means normal scheduling applies. Logs contain only index identity, fixed stage, and closed error code, never provider responses or exception text.

## Canonicalization and Hash Rules

- Decimal values use finite canonical non-exponent text: signed zero becomes `0`, redundant leading/trailing zeros are removed, and binary floats are rejected. An exact fixed-point expansion longer than 10,000 characters fails closed before formatting.
- Timestamps serialize with six fractional digits and explicit `+08:00`; `Z`, offsetless, other offsets, and sub-minute bar identities fail.
- Bars sort by `(interval, barAt)`; requests sort by their full typed key; facts sort by the same key. Array order after sorting is part of the hash.
- `barSetHash = SHA256("market-index-bars-v1\0" + UTF8(canonicalJson(bars)))`.
- `requestSetHash = SHA256("market-index-requests-v1\0" + UTF8(canonicalJson(requests)))`.
- `formulaDefinitionHash = SHA256("market-index-facts-v1\0" + UTF8(canonicalJson(exact formula definitions)))`.
- `snapshotHash = SHA256("market-index-snapshot-v1\0" + UTF8(canonicalJson(all snapshot fields except snapshotHash)))`.

Provider name, raw response ordering, cache hits, plan ids, operational timings, and condition outcomes never enter a content hash. Provider revision and normalized content do.

## Provider Boundary

`LiveMarketIndexProvider` and `HistoricalMarketIndexProvider` expose explicitly named index operations. The Tushare live adapter combines historical `idx_mins(freq="5min")` rows through the prior date with current-day `rt_idx_min_daily(freq="5MIN")` rows, and obtains official daily rows from `index_daily`; the stock `rt_min` endpoint is never an index substitute. Concurrent index batches are admitted only up to the request controller's physical concurrency so one batch's three ordered reads cannot cause later indexes to exhaust the controller's admission timeout. Production composition remains `UNVERIFIED` until an authorized capability probe proves the five board-reference identities plus the hidden turnover benchmark `399107.SZ`, those exact endpoints, timestamp labels, OHLC/prior-close/amount fields, range, quota, and permission. A legacy profile without `399107.SZ` remains valid for the four existing dashboard charts but leaves only the turnover benchmark `UNVERIFIED`. Until the applicable capability is ready, the production adapter returns sanitized `PROVIDER_UNAVAILABLE`; it must not guess or reuse a stock endpoint. Tokens, raw responses, permission text, and exception bodies never enter logs, APIs, reports, or exports.

## Testing Strategy

- Validate exact decimals, timestamps, identity, OHLC, duplicates, gaps, future data, and isolated provider failure.
- Golden-test SMA, lookback SMA, and both return windows including minimum/maximum parameters and insufficient history.
- Prove ten stocks sharing one index and cutoff cause one provider acquisition and one snapshot hash.
- Prove concurrent index batches respect the request controller's physical concurrency and do not falsely block a later index.
- Prove requirement union is order-independent and two different plans receive the same immutable snapshot object/hash.
- Prove any bar/formula/request/revision change changes the appropriate hashes; operational metadata does not.
- Prove no-condition plans retain their original decision when snapshots are absent or blocked.

## Boundaries and Success Criteria

- Always: validate at the provider boundary, use completed facts only, keep snapshots immutable, and isolate index failures.
- Ask first: verify/enable a provider, change formulas, health semantics, hash domains, or cache identity.
- Never: produce a universal market conclusion, hidden trade gate, industry index, synthetic index, unfinished bucket, future fact, or token-bearing diagnostic.
- One `(indexCode, cutoff, requestSet)` yields one byte-stable snapshot; monitoring and replay use these same models, formulas, and hashes.

## ICDR20261009 Closed-session display repair

The accepted [index-close-display-repair](SPEC-index-close-display-repair.md), ICDR03–ICDR04/ICDR07–ICDR08, makes the existing success-retention rule durable. Exact-key `LIVE` data survives later failed/stale/gapped attempts; a later valid correction is ordered by capture time rather than numeric provider revision. Immutable snapshots and plan inputs keep the attempted outcome. `market_index_acquisition_state` stores bounded sanitized latest-attempt metadata and source provenance separately. Migration `0025_index_close_display` adds it and typed recovery storage; startup repair only restores validated same-key captures and preserves decision references. Ordinary transient recovery remains 30/60/120 seconds; final-target supplements share at most 3 starts through target +5 minutes, including reason changes and restarts. No provider endpoint, permission, formula or hash domain changes.
