# C1 stock-minute permission proof contract

> Canonical agent-facing English version. The matching human-review copy is `2026-09-27-c1-stock-minute-permission-proof-contract.zh-CN.md`.

## SMP-01 Status and scope

- Date: 2026-09-27.
- Status: **CONTRACT AND CODE REVIEW PASSED / offline implementation complete**.
- Independent Sol/xhigh re-review found no remaining P1/P2 issues after the five requested clarifications and approved offline implementation. This is contract approval, not evidence of implemented behavior or passing tests.
- Subsequent independent code re-review passed after the two implementation fixes: 291 minute tests, 297 adjacent tests, and 32 expanded reproduction assertions; no remaining P1/P2. These reviewer results were reported by the coordinating task and are recorded separately from the author's runs.
- This document preserves coordination proposal v3 and its reviewed refinements. Contract approval is recorded above; real-service certification is not claimed.
- Proposed scope: two stock-minute provider permission methods and their offline contract tests. No production scheduling, permission-controller integration, database migration, user-database access, or real-service call is authorized by this document.
- Offline implementation and final documentation review are complete; the coordinating task authorized a local commit of this slice's eight files. Executed validation is recorded in the paired verification report. C1 and overall runtime-recovery acceptance remain open.

## SMP-02 Existing specification and reviewed rules

Existing paired specifications, [SPEC-market-data.md](../specifications/monitoring/SPEC-market-data.md) and [SPEC-market-data.zh-CN.md](../specifications/monitoring/SPEC-market-data.zh-CN.md), establish certified START/END interpretation, exact whole-minute identities, the default 12-second grace, independent realtime/historical label evidence, and stock numeric units and validation. Ordinary minute reads deliberately isolate invalid identities and can return valid subsets; this proposal does not change that business behavior.

Coordination proposal v3 adds the strict whole-response permission classification below: frozen SDK start/return times, non-proof opening and incomplete rows, the two-row incomplete bound, and a positive completed-row requirement. Before this document, the recovered v3 record was coordination text rather than a paired repository contract. Its persistence here is not independent approval.

Historical `stk_mins` 241-row evidence does not certify `rt_min` or `rt_min_daily`. An offline mixed-row fixture does not establish that real `rt_min` returns any completed proof row; a forming-only real response would remain insufficient.

Relevant existing boundaries are `market_data/tushare.py`, `market_data/sessions.py`, `market_data/models.py`, `runtime/provider_contract.py`, `live_profiles.py`, and `runtime/request_control.py`. Paths are relative to `src/trade_plan_monitor/`.

## SMP-03 Reviewed interface and immutable result

```python
probe_current_day_minutes_permission(
    symbol: str, trade_date: date, *, physical_start: Callable[[], datetime]
) -> MinutePermissionEvidence

probe_realtime_minutes_permission(
    symbol: str, trade_date: date, *, physical_start: Callable[[], datetime]
) -> MinutePermissionEvidence
```

These are the reviewed signatures implemented in this offline slice. Each call validates one canonical stock symbol, makes at most one corresponding SDK call (`rt_min_daily` or `rt_min`) with `freq="1MIN"`, and uses the provider's frozen, compatible, certified STOCK source label. `UNVERIFIED` is rejected before the SDK call; neither data shape nor a historical profile may infer or replace the label.

The reviewed result is a frozen, slots `MinutePermissionEvidence` dataclass: `operation: Literal['rt_min_daily', 'rt_min']` (no runtime enum dependency), `symbol: str`, `request_date: date`, `started_at: datetime`, `received_at: datetime`, `source_label: SourceTimeLabel`, `source_dates: tuple[date, ...]`, and `completed_count`, `opening_count`, `incomplete_count` as integers. Source dates are sorted and deduplicated, covering A/B/C. Construct the value only from fully validated data. A normal result requires at least one structurally valid A row; it remains a candidate until owner calendar/authority validation. It contains no ORM objects, mutable DataFrame, business `MinuteBar` batch, or durable authorization.

Capture and validate the source label before `physical_start` or SDK invocation. Use that same local value for all row interpretation and the returned evidence; callback/SDK mutations of provider fields cannot change this request's label. Future owner authority checks still decide whether such evidence remains usable.

## SMP-04 Frozen timing

- S is the Shanghai-aware time returned by `physical_start()` immediately before the actual synchronous SDK invocation, after queue waiting. R is captured immediately after SDK return and before response parsing.
- Both belong to `trade_date`; require `0 <= R - S <= 15s`. The 15 seconds are a fixed maximum evidence interval: a later result is rejected, not evidence that the SDK was forcibly interrupted at 15 seconds. Configured request timeout defaults to 30 seconds and permits up to 120 seconds; physical transport/runtime timeout policy belongs to composition. Clock rollback, cross-date return, or an unprovable window cannot produce a successful proof. Timeout, cancellation, and revocation checks remain independent; the wall-clock inequality does not replace them.
- Completion uses S exclusively. R only bounds whether a returned ordinary interval could already have started. Later validation time never enlarges the interval or promotes a non-proof row.
- This proposal fixes proof grace at 12 seconds and the maximum evidence interval at 15 seconds. A provider configured with any grace other than 12 seconds is rejected before SDK invocation; ordinary business reads remain unchanged. The two-row bound must not be reused under other parameters without review.
- Classification does not extend the times at which production may start maintenance.

## SMP-05 Whole-response validation and A/B/C classification

Before column hashing, row conversion, or iteration, require a DataFrame and check raw dimensions: exactly 8 or 9 columns and the operation's row bound. Every column name must be an exact built-in `str`, at most 7 characters, unique, and in the permitted set. Required common columns are `time`, `open`, `close`, `high`, `low`, `vol`, `amount`. `rt_min_daily` additionally requires exactly one of `ts_code` or `code`; `rt_min` requires `ts_code` and forbids `code`. The only optional column is `freq`, explicitly permitted for both operations; if present, every value must be the exact string `1MIN`. Unknown extra columns are rejected in these proof methods, without changing ordinary business-read compatibility.

Source `time` is restricted in this proposal to an exact built-in `str` of 19 characters in `YYYY-MM-DD HH:MM:SS`, with exact parse/format round-trip equality and seconds `00`; interpret it in Asia/Shanghai. No whitespace, alternate format, fractional seconds, `datetime`, or pandas Timestamp values are accepted. Adding datetime support would require an explicit equivalent timezone/whole-minute/nanosecond contract and re-review, not implicit coercion. The requested identity must likewise be an exact string matching the validated symbol.

Numeric cells permit only exact built-in `str`, `int`, `float`, or `Decimal` types; reject `bool`, subclasses, and arbitrary objects before invoking conversion hooks. Before decimal/integer normalization or expanded formatting, bound raw text to 640 characters, decimal coefficient to 640 digits, and the calculated expanded fixed-point representation to 640 characters (including sign/decimal point where applicable). Bound integers before decimal string conversion and reject non-finite floats/decimals. Compute exponent-driven expansion bounds without allocating the expansion, including for zero and amount; zero fast paths must not bypass the resource checks. The same bounds apply to A/B/C and all numeric fields. Existing exact integer-fen/share conversion limits still apply after these preflight checks. These are proposed proof-only scalar limits, not changes to ordinary business parsing.

The bounded row iterator must preserve object-cell types until this preflight. `DataFrame.to_dict` is not suitable: it can execute numeric-subclass conversion hooks before the validator sees the cell. Normal pandas integer/float columns remain supported, but object cells containing `int`/`float` subclasses must be rejected without invoking their hooks.

Every row must have the exact requested symbol, a valid source date and the canonical whole-minute timestamp above, valid finite numeric fields, positive exact integer-fen OHLC with consistent bounds, exact non-negative integer share volume, and finite non-negative yuan amount. Reuse existing exact numeric conversion after the bounded scalar preflight; units remain unchanged. Validate B/C payloads as strictly as A. Reject malformed, foreign-symbol, conflicting, or duplicate identities, including equal duplicates; do not drop them to manufacture success.

| Category | Required temporal shape | Positive completion evidence |
| --- | --- | --- |
| A — `COMPLETED_PROOF` candidate | Ordinary session-contained minute with normalized end e and `e + 12s <= S`; final persisted open-day validation is still required. | Yes, after owner validation. |
| B — `OPENING_NON_PROOF` | END label, exactly 09:30:00, `source_date <= trade_date` and `source_at <= R`, at most one row per `(symbol, date)`. | No. |
| C — `MINUTE_NON_PROOF` | Ordinary request-day minute with `e + 12s > S` and interval start `b = e - 1min <= R`. | No. |

Ordinary ends are 09:31–11:30 and 13:01–15:00. START maps source time to e by adding one minute; END uses the source time. Thus START 09:30 is the ordinary 09:31 minute, not B. START 11:30 and 15:00 are rejected because they map outside the session. END 11:30 and 15:00 are valid ordinary ends, subject to A/C timing; END 13:00, lunch-spanning minutes, and 15:01 are invalid.

B does not acquire a business bar end, replace 09:31, contribute coverage, or require invented constraints such as equal OHLC or zero volume. Its timestamp must already have occurred by frozen R: prior-day A plus today's 09:30 B when S/R are 09:20 fails the entire response, as does any future-date B. Every B date still requires final owner calendar validation. For `rt_min`, admitting this shape is a proposed safe non-evidence category, not a claim that the real interface has been observed or certified to return it.

C includes grace-pending, forming, and call-crossing minutes. A minute that becomes complete at R remains C for this request. `b > R` is invalid. An END source label may itself be later than R when its interval start is already `<= R`; this is valid C if all other conditions hold, unlike B's `source_at <= R` rule. C contains at most two distinct minute identities under the fixed 12-second grace and 15-second maximum evidence interval: `e > S - 12s` and `e <= R + 60s` span at most 87 seconds. Three C rows fail. A and C share the same unique `(symbol, e)` identity set. Classification is independent of row order and does not require contiguous history or the newest minute.

## SMP-06 Bounds and positive-proof predicate

- `rt_min_daily`: a positive response has 1–241 raw rows, all on `trade_date`; A+C occupy at most 240 ordinary session identities and END permits at most one B. The maximum two C rows are inside those 240 identities, not added to the 241-row limit.
- `rt_min`: a positive response has 1–1000 raw rows and may span multiple source dates no later than `trade_date`. Every source date must eventually be proven open. C is restricted to `trade_date`; past ordinary rows can be A and past opening rows can be B. Do not impose 241 rows, five dates, or a new historical-age truncation. All B rows count toward the 1000-row budget.
- Candidate success requires valid schema and bounds, every row assigned to exactly one valid category, and A count at least one. Final success additionally requires owner calendar and authority validation.
- A typed empty frame or valid B/C-only frame has `NO_POSITIVE_PROOF`. A schema-less empty frame, malformed row, or exceeded bound is invalid. Neither case clears the existing latch or manufactures a new HTTP 403.

## SMP-07 Errors and request-not-started propagation

`NO_POSITIVE_PROOF` uses a private `TushareProviderError` subclass with `TushareErrorCode.INVALID_RESPONSE` and fixed safe text. Raise it outside the parsing catch so its distinction survives the existing controller failure path. Do not add public diagnostic fields or retain raw payloads. Import runtime `RequestNotStartedError` inside functions to avoid a module import cycle.

Do not return `False`, `None`, or an empty success value for this outcome: current `recheck_permission()` clears its operation after a normal return and successful `validate_after`. Existing reservations remain governed by the controller; this pure provider slice neither creates nor clears them.

Place `physical_start` outside broad supplier-error conversion and preserve the original `RequestNotStartedError` unchanged through the entire call chain. This includes `_fetch_frame`, `_DefaultTushareQuery`, and broad catches on the direct client route; an outer callback alone is insufficient. An SDK call that already happened must not be relabeled as not started.

Classify structured HTTP 401/403 as permission failure and 429 as rate limiting before generic connection-error handling can erase the status. Other actual SDK/HTTP failures retain their sanitized transient, timeout, and invalid-response classification. Test both a fake SDK and the installed-client wrapper with fake transport: one attempt, original request-not-started identity retained, and HTTP classification preserved. Sanitized provider exceptions must not retain raw secrets/payloads in messages, attributes, `__cause__`, or `__context__`; suppressing display alone is insufficient. Trusted local request-not-started sentinels use fixed safe text and propagate unchanged.

## SMP-08 Owner calendar validation and side-effect boundary

The worker validates local timestamp/session structure and returns bounded immutable source dates; it does not call `_is_open_on` or any callback that can read the database. It does not certify persisted open-day facts on its own.

Future owner integration must perform bounded exact-date checks for every A/B/C source date, including dates represented only by B. The date count cannot exceed the raw-row bound. Unknown, closed, changed, or revoked calendar evidence prevents clearing; relevant calendar epoch, configuration, semantics, generation, stop, and time fences must remain valid. This obligation is recorded here but no production integration is implemented by this slice.

The provider writes no history, latest quote, cache, health/READY status, evaluation, or notification. Existing `_normalized_minutes` cannot serve as the strict proof parser because it filters rows and uses receipt-time completion. Reuse low-level validation only. Do not force B/C into `MinuteBar` or fabricate `received_at` to satisfy that model.

## SMP-09 Reviewed decisions and remaining gate

1. **Proof-only schema/scalars:** approved explicit 8/9-column allowlist, optional `freq` for both operations, string-only canonical 19-character time, exact numeric types, and consistent 640 resource bounds. Ordinary `rt_min_daily` tolerates absent `freq`, whereas capability probing requires it; absence tolerance is preserved only as specified in SMP-05.
2. **Custom grace and timeout clarification:** approved pre-SDK rejection for non-12-second grace and a 15-second maximum evidence interval, not forced SDK interruption. Transport/runtime timeout composition remains outside this slice.
3. **Private result/error representation:** approved SMP-03 frozen dataclass and SMP-07 private no-proof subclass, preserving typed `INVALID_RESPONSE` and request-not-started propagation.

These contract decisions and the SMP-03/07 representation passed independent review. Offline implementation is complete, and independent code re-review found no remaining P1/P2. Owner integration, production scheduling, C1 acceptance, and real-service certification remain outside this completed provider slice.

## SMP-10 Acceptance matrix

| ID | Required test boundary |
| --- | --- |
| SMP-RED-01 | A+B, A+C, A+B+C candidates; B, C, B+C and typed empty produce no positive proof; valid A plus any bad row fails the whole response. |
| SMP-RED-02 | END 09:30 versus START 09:30→09:31; equal/conflicting duplicates, wrong symbol/date, missing/duplicate columns, invalid OHLC, fractional shares, invalid amount, and B/C payload validation. |
| SMP-RED-03 | `e + 12s == S`, one microsecond short, `b == R`, `b > R`; advancing validation time cannot reclassify frozen results. |
| SMP-RED-04 | Two C rows across a minute boundary versus three; START 11:30/15:00 and END 13:00 rejected, END 11:30/15:00 valid subject to timing; END future label with interval start `<= R` accepted as C; lunch, noncanonical/sub-minute timestamps, and row-order independence. |
| SMP-RED-05 | `rt_min_daily` 241/242 and cross-date rejection; `rt_min` cross-date 242/1000/1001, no five-date or 241-row restriction, no continuity/latest-row requirement. |
| SMP-RED-06 | Fake SDK plus installed-client wrapper/fake transport, including `_DefaultTushareQuery` and direct route: pre-SDK revocation means zero physical calls; original `RequestNotStartedError` propagates unchanged; one attempt, structured 401/403/429 classified before generic connection failures; sanitized cause/context and payloads. |
| SMP-RED-07 | R-S exact 15-second boundary, overrun, clock rollback, cross-date return, and queue waiting excluded; a configured 30/120-second timeout does not make a result after 15 seconds valid or imply forced interruption. |
| SMP-RED-08 | Worker has zero database access and business writes; result includes every source date; future owner validation rejects unknown/closed/revoked dates including B-only dates. Owner integration tests remain a later slice. |
| SMP-RED-09 | Existing ordinary minute parsing remains unchanged; label UNVERIFIED is rejected before SDK; historical evidence cannot authorize the realtime label; callback/SDK mutation to END or UNVERIFIED cannot change the frozen START classification or result label. |
| SMP-RED-10 | Explicit `freq` absence/presence rules and non-12-second grace rejected before SDK; internal no-proof failure cannot be mistaken for normal controller success. |
| SMP-RED-11 | Prior-day A plus today's 09:30 B at S/R 09:20, and future-date B, reject the whole response; B at `source_at == R` satisfies this timing boundary. |
| SMP-RED-12 | Width checked before row conversion; unknown/duplicate/non-string columns and unsupported identity aliases rejected; canonical 19-character round trip enforced; datetime/Timestamp rejected; numeric bool/arbitrary objects and int/float subclasses rejected with zero conversion hooks across A/B/C; ordinary numeric columns accepted; 640 limits tested at/beyond boundaries for raw length, coefficient, expansion, zero, and amount across A/B/C. |

Executed RED/GREEN, regression, and independent code-review evidence is recorded separately in the paired `2026-09-27-c1-stock-minute-permission-proof-verification` report. Owner integration assertions remain a later slice. This matrix does not close production integration or C1, and does not certify a real service.
