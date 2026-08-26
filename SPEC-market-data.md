# Spec: market-data (Tushare Market Data)

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-market-data.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Provide normalized, fresh, and complete A-share market and reference data through Tushare for at most 10 active symbols. This module owns capability probes, time and unit conversion, trading sessions, realtime and historical 1-minute normalization, complete 5-minute aggregation, daily reconciliation, actual daily price limits, and versioned technical indicators.

Tushare is the only first-release market-data source. The internal adapter protocol exists for deterministic tests and future replacement; no second provider is implemented in the first release.

Historical acquisition is a distinct capability used by `backtest`. It shares normalized value objects but never masquerades as realtime data, never changes realtime capability state, and never runs inside the live scheduler. Dataset storage, freezing, replay, simulated execution, and result retention are owned by `SPEC-backtest.md`.

## Tech Stack

- Python 3.14.x (`>=3.14,<3.15`)
- Tushare Pro Python SDK, executed outside the event loop
- pandas for normalization and indicator series
- Pydantic 2 for validating untrusted third-party responses
- `zoneinfo.ZoneInfo("Asia/Shanghai")`
- SQLite repositories supplied by `strategy-state`

Official interface references:

- A-share realtime minute: <https://tushare.pro/document/2?doc_id=374>
- Current-day minute replay: <https://tushare.pro/document/2?doc_id=457>
- Trading calendar: <https://tushare.pro/document/2?doc_id=26>
- Daily price limits: <https://tushare.pro/document/2?doc_id=183>
- Official unadjusted daily bars: <https://tushare.pro/document/1?doc_id=27>

## Commands

```powershell
python -m pytest tests/unit/test_market_data.py -q
python -m pytest tests/unit/test_tushare_historical.py -q
python -m pytest tests/integration/test_tushare_contract.py -q -m "not live"
python -m ruff check src/trade_plan_monitor/market_data tests/unit/test_market_data.py
```

The live market-hours contract test requires a real `TUSHARE_TOKEN` and explicit network authorization and is skipped by default.

## Project Structure

```text
src/trade_plan_monitor/market_data/
├── models.py          # Normalized bars, limits, calendar, and capability states
├── provider.py        # MarketDataProvider protocol
├── historical_provider.py  # HistoricalMinuteProvider and versioned label profiles
├── tushare_historical.py   # Strict stk_mins normalization
├── tushare.py         # Tushare adapter and error classification
├── sessions.py        # A-share minute and session semantics
├── aggregation.py     # Complete 5-minute and provisional-daily aggregation
├── indicators.py      # Versioned ta-v1 indicators
└── reconciliation.py  # Provisional versus official close reconciliation
tests/unit/
├── test_market_data.py
└── test_tushare_historical.py
tests/integration/
└── test_tushare_contract.py
tests/fixtures/market_data/
├── tushare_frames.json
└── tushare_stk_mins_241.json
```

## Market Interface Contract

```python
class MarketDataProvider(Protocol):
    def probe_capabilities(self) -> ProviderCapabilities: ...
    def realtime_minutes(self, symbols: tuple[str, ...]) -> list[MinuteBar]: ...
    def current_day_minutes(self, symbol: str) -> list[MinuteBar]: ...
    def trading_calendar(self, start: date, end: date) -> list[TradingDay]: ...
    def daily_limits(self, trade_date: date) -> list[DailyLimit]: ...
    def daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]: ...
```

Tushare mapping:

- `rt_min(freq="1MIN")`: one comma-separated batch for at most 10 symbols; official documentation states at most 1000 returned rows per call, volume in shares, and amount in yuan.
- `rt_min_daily(freq="1MIN")`: single-symbol current-day startup recovery and gap repair; accept only the documented response symbol aliases `ts_code` and `code`, and retain only exact `1MIN` rows from the receipt date.
- `trade_cal`: trading days, closed days, and previous trading day.
- `stk_limit`: actual daily upper and lower limit prices.
- `daily`: official unadjusted daily bars for close-risk state and daily indicators; raw volume in hands is multiplied by 100 to shares, and raw amount in thousand yuan is multiplied by 1000 to yuan.

Capabilities and rate limits are runtime facts. Probe the five interfaces independently and expose their states instead of inferring them from configuration. Symbol-dependent probes remain `UNVERIFIED` when no validated probe symbol is supplied.

Provider failures expose only the operation and one stable `TushareErrorCode`: `BLOCKED_PERMISSION`, `RATE_LIMITED`, `TRANSIENT`, `INVALID_RESPONSE`, or `ERROR`. A structured HTTP response status takes precedence over message text; text fallback recognizes only explicit HTTP/status/error-code contexts or stable phrases, never numeric substrings embedded in symbols or tokens. Raw SDK messages, authorization details, exception context, and tokens are never part of the public error or capability value.

## Historical Interface Contract

```python
class HistoricalMinuteProvider(Protocol):
    def historical_minutes(self, symbol: str, trade_date: date) -> tuple[MinuteBar, ...]: ...
    def trading_calendar(self, exchange: str, start: date, end: date) -> tuple[TradingDay, ...]: ...
    def daily_limits(self, trade_date: date) -> tuple[DailyLimit, ...]: ...
    def daily_bars(self, symbol: str, start: date, end: date) -> tuple[DailyBar, ...]: ...
```

The Tushare/QuickSync historical mapping is `stk_mins`, `trade_cal`, `stk_limit`, and unadjusted `daily`. Historical probes, permission state, rate limits, and source-label mapping are stored separately from the five realtime operations. `stk_mins=READY` does not imply `rt_min=READY` or `rt_min_daily=READY`, and a historical permission failure does not block the live monitor.

The real historical-reference path selects strict `historical_trading_calendar_for_exchange`, `historical_daily_bars`, and `historical_daily_limits` adapter methods. Unlike realtime partial-health normalization, any unparsable row or duplicate identity, even with equal content, fails the entire raw surface as sanitized `INVALID_RESPONSE`. `trade_cal` also rejects another exchange or an out-of-range date; `daily` rejects another symbol or an out-of-range date; market-wide `stk_limit(trade_date)` rejects another date but permits other valid symbols on that date. The backtest sync layer selects its requested `missing_symbols` from that market-wide limit response and separately requires each selected/reference identity set to equal its complete request, so missing rows also fail before persistence. This strictness is historical-only and does not silently change the approved realtime partial-symbol behavior.

Historical calendar acquisition always passes an explicit `exchange="SSE"` or `exchange="SZSE"` to `trade_cal` for the requested symbols. Official Tushare `trade_cal` documentation does not list BSE, so `.BJ` historical scopes fail before a provider call with stable blocker `UNSUPPORTED_HISTORICAL_CALENDAR:BSE`. BSE history requires a separately verified and approved calendar source; the live market/domain support for `.BJ` is unchanged.

An authorized observation on 2026-08-25 returned 241 `stk_mins` rows for `600000.SH` on 2026-08-24, labeled 09:30 through 15:00. `TushareHistoricalMinuteProvider` defaults to `UNVERIFIED` and fails before the SDK call. The explicit implemented profile `TUSHARE_STK_MINS_241_END_V1` preserves the 09:30 source row as non-strategy `opening_special`, requires every other source label to be an exact canonical minute end, and returns 240 executable bars. No implementation may silently discard, shift, or accept all 241 rows.

Historical network retrieval is allowed only in an explicitly authorized `backtest sync`. It occurs outside database transactions, validates at most 1,000 rows per persistence batch, and emits no raw response or credential material. Offline `backtest verify` and `backtest run` make zero provider calls.

Frozen historical artifacts remain untrusted at rest: every dataset read recomputes the canonical artifact content hash and compares it with the referenced `artifact_hash` before parsing. A mismatch is corruption/tampering and blocks replay; a valid-looking hash string is insufficient.

Offline freeze/reads expose only stable integrity blockers: `INVALID_<KIND>:<identity>:<date>` for malformed referenced content, `INVALID_CALENDAR_CHAIN:<exchange>:<date>` for broken predecessor facts, and `PRICE_OUTSIDE_DAILY_LIMIT:<symbol>:<date>` when OHLC violates the day's actual limit.

## Data Semantics

- Internally use normalized bar-end timestamps with the `Asia/Shanghai` timezone.
- Source minute timestamps must identify exact whole minutes, including zero pandas nanosecond residue; sub-minute identities fail closed.
- A Tushare source label may denote minute start or end. A live contract test must freeze the mapping; the scheduler and gap detector never assume raw-label semantics.
- Realtime and historical source-label profiles are independently versioned and verified. Evidence for one profile cannot authorize the other.
- Monitoring sessions cover 09:30–11:30 and 13:00–15:00. Opening call-auction data is outside the first-release rule stream; the 14:57–15:00 closing call auction remains inside the afternoon monitoring window.
- Data becomes usable only after the minute ends, the default 12-second grace passes, and symbol, OHLC, non-negative volume/amount, and session validation succeed.
- The 1-minute idempotency key is `(symbol, bar_end)`.
- Every required provider column must occur exactly once. Reordered or extra columns are harmless; a missing or ambiguous required column and a schema-less empty frame are `INVALID_RESPONSE`, while a typed empty frame is valid no-data.
- Rows are parsed identity-first. A malformed or conflicting payload permanently invalidates that identity for the response regardless of row order; an unidentifiable, unrequested, or missing row never invalidates healthy identities.
- Decimal powers-of-ten are shifted exactly without consulting the ambient decimal precision. Prices must become positive integer fen, share counts must become exact non-negative integers, and an integer result exceeding 640 decimal digits is rejected before allocation.
- Create a complete 5-minute bar only when every expected minute inside one trading session exists; never aggregate across lunch.
- `aggregate_five_minute_bar` accepts only an exact repeatable tuple of five normalized `MinuteBar` values for one symbol. Missing, duplicate, mixed-symbol, cross-session, closed-day, and unknown-day inputs cannot create a bar; reordered complete input produces the same immutable `(symbol, bar_end, formula_version)` value.
- Five-minute `amount_yuan` is summed exactly from decimal tuples without consulting the ambient decimal context. Zero values do not widen the exponent span; a non-zero aligned coefficient or final sum exceeding the 640-digit safe span fails closed before a large allocation.
- Completeness input is a bounded, repeatable tuple of canonical minute ends; arbitrary iterators or collections are rejected without consumption.
- Incomplete or stale data immediately blocks actionable signals for that symbol.
- The newest complete minute close replaces `latest_quote`; do not create a second quote-history stream.
- The `current_day_minutes` decision-context slice is an immutable exact tuple of normalized complete current-date minutes from the first canonical minute end through an inclusive 5-minute evaluation cutoff, capped at 240 rows and preserving the canonical lunch break. Missing, duplicate, out-of-order, mixed-symbol/date, out-of-session, beyond-cutoff, or arbitrary iterable input fails closed. It reuses persisted minute history and does not create a second quote-history stream.
- Market persistence accepts only bounded list/tuple batches of normalized values, with at most 1,000 rows per call. Minute, daily, and daily-limit corrections advance only on a newer `received_at`; an equal receipt with conflicting facts fails closed, and an older replay is harmless.
- Market-history reads require explicit inclusive start/end bounds and fail closed above 10,000 rows. Calendar reads are also range-bounded; a later authoritative calendar fetch may correct the same `(exchange, cal_date)` because that table has no receipt-version column.
- A persisted 5-minute bar must end on a valid session-contained 5-minute boundary. Its `(symbol, bar_end, formula_version)` identity is deterministic and cannot be overwritten with conflicting facts.
- `aggregate_provisional_daily_bar(current_day_minutes=..., source_as_of=...)` is the pure T032 boundary for the current-date provisional `DailyBar` used by intraday indicators. It derives deterministically from the exact slice: first open, maximum high, minimum low, last close, summed share volume, summed exact yuan amount, `is_official=False`, and the newest source receipt. Its `source_as_of` is the slice cutoff. The aggregate through 15:00 is the provisional close and never relabels or overwrites the separate official row. Only a current-trading-day official `daily` row advances official close-risk state.

`reconcile_daily_close(symbol=..., current_trade_date=..., daily_bars=...)` is a pure boundary over an immutable tuple containing at most the separately persisted provisional and official `DailyBar` rows for one symbol and exact date. Mutable collections, more than two rows, duplicate provenance, mixed symbols, and non-current dates fail closed. Input order is not observable.

The immutable `CloseReconciliationIntent` preserves `provisional_bar` and `official_bar` separately and exposes `status`, `close_delta_fen`, and `advance_close_risk`. Without a current-date official row, status is `CLOSE_PENDING`, the official bar and delta are `None`, and close risk cannot advance. With a real `DailyBar(is_official=True)` for the requested date, status is `OFFICIAL_READY`; `close_delta_fen` is official minus provisional close when both exist, and the unchanged official row is the only close authorized for downstream risk evaluation. Repeated persisted rows and restart reconstruction produce the same intent; the function performs no persistence, scheduling, health mutation, or risk evaluation.

## Indicator Definitions

Formula version `ta-v1`:

- EMA: pandas `ewm(span=n, adjust=False)`;
- MACD `(12,26,9)`, histogram `macd - signal`;
- Bollinger Bands `(20,2)` using population standard deviation;
- RSI14 and ATR14 using Wilder smoothing;
- MA20/MA50/MA200 using unadjusted closes.

`calculate_ta_v1` accepts an immutable tuple containing one symbol and one bar type (`DailyBar` or complete `FiveMinuteBar`), with strictly increasing date/time identities and at most 10,000 values. A duplicate daily date—including simultaneous provisional/official rows—must be resolved by reconciliation before calculation rather than silently deduplicated.

Integer-fen OHLC inputs are converted once to finite float yuan before pandas calculation. Price-valued outputs are `ema10_yuan`, `ema12_yuan`, `ema26_yuan`, `macd_yuan`, `macd_signal_yuan`, `macd_histogram_yuan`, `boll_middle_yuan`, `boll_upper_yuan`, `boll_lower_yuan`, `atr14_yuan`, and `ma20_yuan`/`ma50_yuan`/`ma200_yuan`; `rsi14` is dimensionless on 0–100. Values outside the finite float calculation range fail closed.

RSI14 seeds the average gain/loss from the first 14 close differences and first appears at index 14. ATR14 seeds from the simple mean of the first 14 true ranges and first appears at index 13. Subsequent RSI/ATR values use Wilder's recursive `(previous * 13 + current) / 14` smoothing. Other insufficient rolling windows are explicit `None`; the decision engine treats required missing indicators as blockers.

`IndicatorSeries` and every `IndicatorPoint` are closed and immutable, and public copy updates rerun validation. The fixed OHLCV golden suite locks pandas 3.0.5 results for `ta-v1`; any intentional formula or compatibility change requires a new formula version and updated goldens.

Current-date daily indicator calculation selects exactly one current-date source. A provisional aggregate yields `PROVISIONAL` provenance and its exact slice-cutoff `source_as_of`; a reconciled official row yields `OFFICIAL` provenance with canonical 15:00 `source_as_of` and is eligible for official-close evaluation only when `advance_close_risk=True`. Simultaneous or implicit source selection, missing cutoff provenance, and mixed sources fail closed before `calculate_ta_v1`; the caller pairs `IndicatorSeries` with the selected source facts. A provisional current-day daily bar may support display and momentum evidence but never overwrites an official daily bar or advances official-close state.

## Code Style

```python
class MinuteBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    bar_end: datetime
    open_fen: int
    high_fen: int
    low_fen: int
    close_fen: int
    volume_shares: int
    amount_yuan: Decimal
    received_at: datetime
```

Adapters normalize data and classify errors only; they contain no trading rules.

## Testing Strategy

- Synthetic DataFrames cover all five interfaces, column drift, disorder, duplicates, nulls, invalid values, partial-symbol results, units, and token redaction.
- Cover opening auction, lunch, final minute, weekends, holidays, and unknown trading days.
- Cover missing minutes, duplicate arrival, recovery backfill, and exactly-once complete 5-minute creation.
- Validate indicator golden values from fixed OHLCV fixtures.
- Cover provisional/official close agreement, disagreement, delayed arrival, and next-startup recovery.
- Cover exact/gapped current-day decision slices, the 240-row bound, provisional source cutoffs, and rejection of simultaneous or implicit current-date indicator sources.
- Cover the historical 241-row observation, all explicit 09:30 interpretations, independent historical capability state, immutable revision identity, strict raw reference duplicate/wrong-identity/unparsable-extra rejection, and rejection before a historical-label profile is verified.
- Live tests confirm 10-symbol batches, label semantics, volume/amount units, latency, capabilities, and final-minute behavior.

## Boundaries

- Always: validate every third-party response before persistence.
- Always: redact `TUSHARE_TOKEN` and permission-related error details.
- Always: keep historical and realtime capability/timestamp evidence independent; historical retrieval is authorized only for `backtest sync`.
- Always: fail closed when the trading day is unknown, actual price limits are missing, minutes are stale, or daily history is insufficient.
- Ask first: change formula version, adjustment policy, default grace, or add a second provider.
- Never: substitute a hard-coded 10% limit for actual daily limit prices in a buy decision.
- Never: treat a cached price as an official close.
- Never: perform database work in a Tushare executor thread.
- Never: let `stk_mins` evidence complete `T058`, or call a provider during offline dataset verification or replay.

## Success Criteria

- When Tushare accepts it, at most 10 active symbols use one normalized batch request.
- One missing symbol blocks only itself and not healthy symbols in the same batch.
- Realtime-minute volume remains shares and amount remains yuan without scaling; official-daily raw hands and thousand-yuan values are converted once to shares and yuan at the adapter boundary.
- An incomplete 5-minute bar never enters actionable rule evaluation.
- Unknown capability, calendar, or price-limit data produces explicit health blockers.
- Indicator golden values are stable across runs.
- Official-close reconciliation is auditable and idempotent.
- Historical facts can be normalized into immutable revisions only under an explicit historical-label profile, while unknown 241-row semantics block dataset freezing.

## Open Questions

Actual account entitlements and rate limits are confirmed by capability-specific probes; this specification does not hard-code account-specific thresholds. Realtime timestamp/final-minute behavior remains gated by `T058`, while historical `stk_mins` labeling has its own non-market-hours verification gate under `BT001`.
